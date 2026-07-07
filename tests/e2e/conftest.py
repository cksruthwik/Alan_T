"""E2E harness: the real app, end to end, offline.

Real: FastAPI app built by the real bootstrap, real Postgres (dedicated
`alan_t_e2e` database, migrated from zero by alembic), real tool registry,
gate, approvals, planner, stores, web client files.

Scripted: the model seam only. FakeRouter answers every role deterministically
(routing JSON, tool calls, plans, verdicts, titles, embeddings, transcripts),
so journeys exercise the entire machine without a single network call.

Skips cleanly when Postgres isn't running (CI provides one as a service).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import socket
import struct
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
E2E_DB = "alan_t_e2e"
E2E_TOKEN = "e2e-test-token"


def _pg_password() -> str:
    env_file = REPO / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("POSTGRES_PASSWORD="):
                return line.split("=", 1)[1].split("#")[0].strip() or "alan"
    return os.environ.get("POSTGRES_PASSWORD", "alan")


def _pg_available() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 5432), timeout=1):
            return True
    except OSError:
        return False


# ── the scripted model seam ─────────────────────────────────────────────


class FakeRouter:
    """Deterministic stand-in for ModelRouter — same interface, zero network."""

    ROLES = ["CHAT", "ROUTER", "REASONER", "REFLECTOR", "SUMMARIZER", "LONG_CONTEXT",
             "CODER", "VISION", "STT", "TTS", "EMBEDDER", "LIVE_VOICE", "IMAGE_GEN"]

    def __init__(self, *args, **kwargs):
        self.requests: list = []
        self.embedded_texts: list = []  # every text actually sent for embedding

    def verify(self) -> None:
        pass

    def chain(self, purpose):
        return [{"provider": "fake", "model": f"fake-{purpose.lower()}"}]

    def active_models(self):
        return {r: [f"fake/{r.lower()}"] for r in self.ROLES}

    @property
    def embedder_model(self) -> str:
        return "fake-embedder@1536"

    async def transcribe(self, audio_path) -> str:
        from alan_t.core.types import HonestFailure

        if b"RATELIMIT" in Path(audio_path).read_bytes():
            raise HonestFailure("STT chain exhausted (scripted)")
        return "hello alan can you hear me"

    async def embed(self, texts):
        self.embedded_texts.extend(texts)
        return [self._vector(t) for t in texts]

    @staticmethod
    def _vector(text: str, dim: int = 1536):
        seed = hashlib.sha256(text.encode()).digest()
        raw = [struct.unpack("b", bytes([seed[i % 32]]))[0] + ((i * 37) % 13) - 6
               for i in range(dim)]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]

    async def stream(self, purpose, req):
        from alan_t.core.types import ChatDelta

        resp = await self.complete(purpose, req)
        for i in range(0, len(resp.text), 12):
            yield ChatDelta(text=resp.text[i:i + 12])

    async def complete(self, purpose, req):
        from alan_t.core.types import ChatResponse, LLMToolCall

        self.requests.append((purpose, req))
        system = req.messages[0].content if req.messages else ""
        last = req.messages[-1]
        last_user = next((m.content for m in reversed(req.messages) if m.role == "user"), "")

        def text(t, calls=None):
            return ChatResponse(text=t, model=f"fake/{purpose.lower()}",
                                tool_calls=calls or [])

        if "explode" in last_user.lower() and purpose in ("CHAT", "ROUTER"):
            raise RuntimeError("scripted mid-turn provider crash")

        if purpose == "ROUTER":
            low = last_user.lower()
            if "note" in low and ("create" in low or "add" in low):
                agent = "notes"
            elif "my notes" in low or "alpha" in low:
                agent = "file"
            elif "goal" in low or "automation" in low:
                agent = "automation"
            else:
                agent = "conversation"
            return text(json.dumps({"agent": agent, "skills": []}))

        if purpose == "REASONER" and "task planner" in system:
            return text(json.dumps({"steps": [{
                "agent": "notes",
                "instruction": "Create a note called Weekly Summary saying: everything on track"}]}))

        if purpose == "REFLECTOR":
            return text(json.dumps({"verdict": "success", "reasoning": "steps completed",
                                    "lesson": ""}))

        if purpose == "SUMMARIZER":
            if "Title this conversation" in system:
                return text("Dummy Test Chat")
            if req.response_format:
                return text(json.dumps({"facts": []}))
            return text("candidate B is best because it is concise")

        if purpose == "VISION":
            return text("I see a tiny test image containing a red square.")

        # tool-using agents (CHAT/CODER/…): scripted tool calls, then a wrap-up
        if req.tools:
            tool_names = {t["name"] for t in req.tools}
            if last.role == "tool":
                return text(f"Done. Result: {last.content[:120]}")
            m = re.search(r"note called ([A-Za-z ]+?)(?: saying:? (.+))?$",
                          last_user, re.I)
            if m and "note_create" in tool_names:
                return text("", [LLMToolCall(id="c1", name="note_create", arguments={
                    "title": m.group(1).strip().rstrip("."),
                    "content": (m.group(2) or "created in e2e").strip()})])
            if "goal" in last_user.lower() and "run_goal" in tool_names:
                return text("", [LLMToolCall(id="c2", name="run_goal", arguments={
                    "goal": "write my weekly summary note"})])
        if "chunks" in system or "[vfs://" in system or "search results" in system.lower():
            return text("According to your notes, Project Alpha launches in June "
                        "[vfs://notes/alpha.md].")
        return text(f"fake-{purpose.lower()} says: {last_user[:60] or 'hello'}")


# ── the app fixture ─────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def client(tmp_path_factory):
    if not _pg_available():
        pytest.skip("Postgres not reachable on 127.0.0.1:5432 — e2e needs it")

    pw = _pg_password()
    admin_dsn = f"postgresql://alan:{pw}@127.0.0.1:5432/postgres"
    test_dsn = f"postgresql+asyncpg://alan:{pw}@127.0.0.1:5432/{E2E_DB}"

    async def recreate_db():
        import asyncpg

        conn = await asyncpg.connect(admin_dsn)
        await conn.execute(f'DROP DATABASE IF EXISTS {E2E_DB} WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE {E2E_DB}')
        await conn.close()

    asyncio.run(recreate_db())

    # isolated data + config trees
    root = tmp_path_factory.mktemp("e2e")
    notes_src = root / "user_notes"
    notes_src.mkdir()
    (root / "uploads").mkdir()
    (notes_src / "alpha.md").write_text(
        "# Project Alpha\n\nProject Alpha launches in June. Budget approved.\n")
    (notes_src / "beta.md").write_text("# Beta\n\nBeta is on hold until Q3.\n")

    conf = root / "config"
    conf.mkdir()
    for name in ("models.yaml", "capabilities.yaml", "permissions.yaml", "mcp.yaml"):
        (conf / name).write_text((REPO / "config" / name).read_text())
    (conf / "automations.yaml").write_text(yaml.safe_dump({"jobs": [
        {"name": "morning_digest", "at": "23:58", "action": "digest", "enabled": True}]}))
    (conf / "mounts.yaml").write_text(yaml.safe_dump({
        "mounts": {
            "notes": {"path": str(notes_src), "include": ["**/*.md", "**/*.txt", "**/*.pdf"]},
            "uploads": {"path": str(root / "uploads"),
                        "include": ["**/*.md", "**/*.txt", "**/*.pdf"]},
        },
        "exclude_global": ["**/.env*"]}))
    (conf / "app.yaml").write_text(yaml.safe_dump({
        "budgets": {"memory_tokens": 600, "conversation_tokens": 2000, "context_tokens": 4000},
        "features": {"webui": True, "memory": False, "knowledge": True,
                     "telegram": False, "supervisor": True, "voice": True}}))

    env = {
        "DATABASE_URL": test_dsn, "ALAN_API_TOKEN": E2E_TOKEN,
        "GROQ_API_KEY": "", "GOOGLE_API_KEY": "", "NVIDIA_API_KEY": "",
        "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_ALLOWED_USER_ID": "0",
        "NOTES_DIR": str(root / "alan_notes"), "IMAGES_DIR": str(root / "images"),
        "UPLOADS_DIR": str(root / "uploads"), "USER_NAME": "Tester",
    }
    os.environ.update(env)

    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                   cwd=REPO, env={**os.environ}, check=True, capture_output=True)

    # wire the fakes into the real composition root, then boot the real app
    import alan_t.app.bootstrap as bootstrap
    from alan_t.app.config import load_app_config as _real_load  # noqa: F401

    bootstrap.CONFIG_DIR = conf
    bootstrap.MODELS_YAML = conf / "models.yaml"
    bootstrap.ModelRouter = FakeRouter
    bootstrap.load_app_config = lambda: yaml.safe_load((conf / "app.yaml").read_text())

    for mod in ("alan_t.app.main", "alan_t.app.voice", "alan_t.app.webui"):
        sys.modules.pop(mod, None)
    import alan_t.app.main as main

    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        c.headers.update({"Authorization": f"Bearer {E2E_TOKEN}"})
        c.state_obj = main.state
        yield c
