"""FastAPI app — API shape per Docs/api/API_SPECIFICATION.md."""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
import uuid
from pathlib import Path

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from alan_t.app.bootstrap import App, build
from alan_t.app.chat_service import finish_turn, prepare_task, run_turn
from alan_t.core.observability import render_metrics
from alan_t.core.types import AgentTask, HonestFailure, IncomingMessage, MessageKind

logging.basicConfig(level=logging.INFO)


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    await state.mcp.connect(state.tools)  # external MCP tools enter the gated registry
    state.scheduler.start()               # automations (config/automations.yaml)
    yield
    await state.scheduler.stop()
    await state.mcp.close()


app = FastAPI(title="Alan_T", version="0.1.0", lifespan=_lifespan)
state: App = build()

_bearer = HTTPBearer(auto_error=False)


def auth(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    if not state.settings.alan_api_token:
        raise HTTPException(500, "ALAN_API_TOKEN is not configured")
    if creds is None or creds.credentials != state.settings.alan_api_token:
        raise HTTPException(401, "invalid bearer token")


def problem(status: int, title: str, detail: str, trace_id: str, **extra) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={"type": "about:blank", "title": title, "status": status,
                 "detail": detail, "trace_id": trace_id, **extra},
    )


@app.exception_handler(HonestFailure)
async def honest_failure_handler(request, exc: HonestFailure):
    return problem(
        503, "rate_limited", str(exc), trace_id=str(uuid.uuid4()),
        retry_after_seconds=exc.retry_after_seconds,
    )


# ── chat: sessions are ChatGPT-grade (rename/archive/delete/projects) ──


class CreateSession(BaseModel):
    channel: str = "web"
    title: str | None = None
    project_id: uuid.UUID | None = None


class SendMessage(BaseModel):
    content: str
    modality: str = "text"


class UpdateSession(BaseModel):
    title: str | None = None
    project_id: uuid.UUID | None = None
    clear_project: bool = False
    archived: bool | None = None


def _session_json(s, project_names: dict) -> dict:
    return {"session_id": str(s.id), "title": s.title, "channel": s.channel,
            "project_id": str(s.project_id) if s.project_id else None,
            "project": project_names.get(s.project_id),
            "created_at": s.created_at.isoformat(),
            "last_message_at": s.last_message_at.isoformat() if s.last_message_at else None,
            "archived": s.archived_at is not None}


async def _project_names() -> dict:
    return {uuid.UUID(p["id"]): p["name"] for p in await state.store.list_projects()}


@app.post("/api/v1/chat/sessions", dependencies=[Depends(auth)])
async def create_session(body: CreateSession):
    sid = await state.store.create_session(channel=body.channel, title=body.title,
                                           project_id=body.project_id)
    return {"session_id": str(sid)}


@app.get("/api/v1/chat/sessions", dependencies=[Depends(auth)])
async def list_sessions(archived: bool = False, project_id: uuid.UUID | None = None):
    names = await _project_names()
    return [_session_json(s, names)
            for s in await state.store.list_sessions(archived=archived, project_id=project_id)]


@app.get("/api/v1/chat/sessions/{session_id}", dependencies=[Depends(auth)])
async def session_detail(session_id: uuid.UUID, limit: int = 100, offset: int = 0):
    if not await state.store.session_exists(session_id):
        raise HTTPException(404, "unknown session")
    return [
        {"turn_id": str(t.id), "role": t.role, "content": t.content, "agent": t.agent,
         "modality": t.modality, "created_at": t.created_at.isoformat()}
        for t in await state.store.turns(session_id, limit=limit, offset=offset)
    ]


@app.patch("/api/v1/chat/sessions/{session_id}", dependencies=[Depends(auth)])
async def update_session(session_id: uuid.UUID, body: UpdateSession):
    project_id = None if body.clear_project else (body.project_id if body.project_id else "unset")
    ok = await state.store.update_session(
        session_id, title=body.title, project_id=project_id, archived=body.archived)
    if not ok:
        raise HTTPException(404, "unknown session")
    return {"status": "updated"}


@app.delete("/api/v1/chat/sessions/{session_id}", dependencies=[Depends(auth)])
async def delete_session(session_id: uuid.UUID):
    if not await state.store.delete_session(session_id):
        raise HTTPException(404, "unknown session")
    return {"status": "deleted"}


@app.post("/api/v1/chat/sessions/{session_id}/messages", dependencies=[Depends(auth)])
async def send_message(session_id: uuid.UUID, body: SendMessage):
    if not await state.store.session_exists(session_id):
        raise HTTPException(404, "unknown session")
    turn_id, result, agent_name = await run_turn(
        state, session_id, body.content,
        modality=body.modality if body.modality in ("text", "voice") else "text")
    return {
        "turn_id": str(turn_id), "content": result.response, "agent": agent_name,
        "status": result.status, "degraded": result.degraded,
    }


# ── projects (ChatGPT-style grouping + shared instructions) ───────────


class ProjectBody(BaseModel):
    name: str
    instructions: str = ""


@app.get("/api/v1/projects", dependencies=[Depends(auth)])
async def list_projects():
    return await state.store.list_projects()


@app.post("/api/v1/projects", dependencies=[Depends(auth)])
async def create_project(body: ProjectBody):
    pid = await state.store.create_project(body.name.strip(), body.instructions)
    return {"project_id": str(pid)}


@app.delete("/api/v1/projects/{project_id}", dependencies=[Depends(auth)])
async def delete_project(project_id: uuid.UUID):
    if not await state.store.delete_project(project_id):
        raise HTTPException(404, "unknown project")
    return {"status": "deleted", "note": "its chats survive, ungrouped"}


@app.websocket("/api/v1/chat/ws/{session_id}")
async def chat_ws(ws: WebSocket, session_id: uuid.UUID):
    # Browsers can't set Authorization on WS; accept token as query param too.
    token = ws.query_params.get("token") or (ws.headers.get("authorization") or "").removeprefix("Bearer ")
    if token != state.settings.alan_api_token:
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "abort":
                continue
            if msg.get("type") != "message":
                await ws.send_json({"type": "error", "problem": {"title": "unknown message type"}})
                continue

            content = msg.get("content", "")
            trace_id = str(uuid.uuid4())
            task = await prepare_task(state, session_id, content)
            await state.store.add_turn(session_id, "user", content, trace_id=trace_id)
            agent, skill_names = await state.supervisor.route(task, state.ctx)
            task.skills = state.skills.render(skill_names)

            full: list[str] = []
            try:
                if hasattr(agent, "run_stream"):
                    async for delta in agent.run_stream(task, state.ctx):
                        full.append(delta.text)
                        await ws.send_json({"type": "token", "text": delta.text})
                else:
                    result = await agent.run(task, state.ctx)
                    full.append(result.response)
                    await ws.send_json({"type": "token", "text": result.response})
            except HonestFailure as e:
                await ws.send_json({"type": "error", "problem": {
                    "title": "rate_limited", "detail": str(e), "status": 503}})
                continue
            except Exception:
                logging.getLogger("alan_t").exception("chat ws turn failed")
                await ws.send_json({"type": "error", "problem": {
                    "title": "internal_error",
                    "detail": "That turn failed on the backend — try again.", "status": 500}})
                continue

            answer = "".join(full)
            turn_id = await finish_turn(state, session_id, content, answer,
                                        agent_name=agent.name, trace_id=trace_id)
            await ws.send_json({"type": "done", "turn_id": str(turn_id),
                                "agent": agent.name, "degraded": []})
    except WebSocketDisconnect:
        pass


# ── knowledge (API_SPECIFICATION §4) ──────────────────────────────────


class SearchBody(BaseModel):
    query: str
    top_k: int = 8


def _knowledge_or_501():
    if state.ingester is None:
        raise HTTPException(501, "knowledge layer not enabled (features.knowledge in config/app.yaml)")


@app.post("/api/v1/knowledge/search", dependencies=[Depends(auth)])
async def knowledge_search(body: SearchBody):
    _knowledge_or_501()
    chunks = await state.retriever.search(body.query, top_k=body.top_k)
    return [
        {"chunk_id": c.chunk_id, "vpath": c.vpath, "body": c.body,
         "score": c.score, "similarity": c.similarity, "payload": c.payload}
        for c in chunks
    ]


@app.get("/api/v1/knowledge/sources", dependencies=[Depends(auth)])
async def knowledge_sources():
    _knowledge_or_501()
    return {"mounts": state.files.mounts_summary(), **(await state.ingester.status())}


@app.post("/api/v1/ingest", dependencies=[Depends(auth)])
async def ingest(background: BackgroundTasks):
    """Sync mounts + ingest changed files, as an in-process background task (ADR-021)."""
    _knowledge_or_501()
    background.add_task(state.ingester.run_full)
    return {"status": "started", "note": "poll /api/v1/ingest/status"}


@app.get("/api/v1/ingest/status", dependencies=[Depends(auth)])
async def ingest_status():
    _knowledge_or_501()
    return await state.ingester.status()


# ── vision + voice (hosted models: NVIDIA-primary vision, Groq STT) ──


@app.post("/api/v1/vision/analyze", dependencies=[Depends(auth)])
async def vision_analyze(image: UploadFile, question: str = Form("Describe this image in detail.")):
    suffix = Path(image.filename or "img.jpg").suffix or ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(await image.read())
        tmp = f.name
    try:
        task = AgentTask(message=IncomingMessage(kind=MessageKind.FILE, text=question, file_path=tmp))
        result = await state.vision_agent.run(task, state.ctx)
    finally:
        os.unlink(tmp)
    return {"content": result.response, "model": result.model, "status": result.status}


@app.post("/api/v1/voice/transcribe", dependencies=[Depends(auth)])
async def voice_transcribe(audio: UploadFile):
    suffix = Path(audio.filename or "note.ogg").suffix or ".ogg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(await audio.read())
        tmp = f.name
    try:
        text = await state.router.transcribe(tmp)
    finally:
        os.unlink(tmp)
    return {"text": text}


# ── library (ChatGPT-style: everything Alan_T holds for you) ─────────


@app.get("/api/v1/library", dependencies=[Depends(auth)])
async def library():
    """Unified listing: notes, documents, generated images, uploads, sources."""
    uploads_dir = Path(state.settings.uploads_dir).expanduser()
    images_dir = Path(state.settings.images_dir).expanduser()
    out = {
        "notes": await state.notes.list_notes(),
        "documents": await state.personal.list_documents(50),
        "images": sorted((p.name for p in images_dir.glob("*.png")), reverse=True)
                  if images_dir.is_dir() else [],
        "uploads": sorted((p.name for p in uploads_dir.iterdir() if p.is_file()), reverse=True)
                   if uploads_dir.is_dir() else [],
    }
    if state.ingester:
        out["knowledge"] = await state.ingester.status()
    return out


@app.post("/api/v1/library/upload", dependencies=[Depends(auth)])
async def library_upload(file: UploadFile, background: BackgroundTasks, ingest: bool = True):
    """Save into the uploads mount; by default ingest it into RAG right away."""
    uploads_dir = Path(state.settings.uploads_dir).expanduser()
    uploads_dir.mkdir(parents=True, exist_ok=True)
    safe = Path(file.filename or "upload.bin").name  # strip any path components
    dest = uploads_dir / safe
    if dest.exists():
        dest = uploads_dir / f"{dest.stem}-{uuid.uuid4().hex[:6]}{dest.suffix}"
    dest.write_bytes(await file.read())
    ingested = False
    if ingest and state.ingester:
        background.add_task(state.ingester.run_full)
        ingested = True
    return {"saved": dest.name, "ingest_started": ingested}


# ── autonomy: tasks (planner), approvals, automations ────────────────


class GoalBody(BaseModel):
    goal: str


@app.post("/api/v1/tasks", dependencies=[Depends(auth)])
async def run_task(body: GoalBody):
    """Plan + execute + reflect, synchronously (a goal typically takes 10–60s)."""
    try:
        return await state.planner.run(body.goal, state.ctx, state.reflector)
    except ValueError as e:  # plan validation failure — nothing ran
        raise HTTPException(422, str(e))


@app.get("/api/v1/tasks", dependencies=[Depends(auth)])
async def list_tasks():
    return await state.personal.list_task_runs()


@app.get("/api/v1/tasks/{task_id}", dependencies=[Depends(auth)])
async def task_detail(task_id: str):
    record = await state.personal.get_task_run(task_id)
    if record is None:
        raise HTTPException(404, "unknown task run")
    return record


@app.get("/api/v1/approvals", dependencies=[Depends(auth)])
async def list_approvals():
    return [{"id": a.id, "tool": a.tool, "preview": a.preview, "created_at": a.created_at}
            for a in state.approvals.pending()]


class ApprovalBody(BaseModel):
    approve: bool


@app.post("/api/v1/approvals/{approval_id}", dependencies=[Depends(auth)])
async def resolve_approval(approval_id: str, body: ApprovalBody):
    try:
        a = await state.approvals.resolve(approval_id, body.approve)
    except KeyError:
        raise HTTPException(404, "unknown approval")
    result = a.result if isinstance(a.result, str) else None
    if a.result is not None and result is None:
        import json as _json
        result = _json.dumps(a.result, default=str)
    return {"id": a.id, "tool": a.tool, "status": a.status,
            "result": (result or "")[:4000]}


@app.get("/api/v1/automations", dependencies=[Depends(auth)])
async def list_automations():
    return state.scheduler.jobs_summary()


@app.post("/api/v1/automations/{name}/run", dependencies=[Depends(auth)])
async def trigger_automation(name: str):
    try:
        return {"result": await state.scheduler.run_job(name)}
    except KeyError:
        raise HTTPException(404, "unknown automation")
    except Exception as e:  # a broken job is a 500 with a reason, not a crash page
        raise HTTPException(500, f"automation failed: {type(e).__name__}: {e}")


# ── voice out + model compare ─────────────────────────────────────────


class SpeakBody(BaseModel):
    text: str


@app.post("/api/v1/voice/speak", dependencies=[Depends(auth)])
async def voice_speak(body: SpeakBody):
    if not state.media.configured:
        raise HTTPException(501, "TTS needs GOOGLE_API_KEY")
    wav = await state.media.speak(body.text[:2000])
    return Response(content=wav, media_type="audio/wav")


class CompareBody(BaseModel):
    prompt: str
    roles: list[str] = ["CHAT", "REASONER", "LONG_CONTEXT"]


@app.post("/api/v1/compare", dependencies=[Depends(auth)])
async def compare_models(body: CompareBody):
    """Blind A/B across model roles: anonymized outputs + a synthesis verdict."""
    from alan_t.core.types import ChatMessage as _M, ChatRequest as _R

    outputs = []
    for role in body.roles[:4]:
        try:
            r = await state.router.complete(role, _R(messages=[_M(role="user", content=body.prompt)]))
            outputs.append({"role": role, "model": r.model, "text": r.text})
        except Exception as e:
            outputs.append({"role": role, "model": "?", "text": f"(failed: {type(e).__name__})"})
    anonymized = "\n\n".join(f"### Candidate {chr(65 + i)}\n{o['text'][:3000]}"
                             for i, o in enumerate(outputs))
    synth = await state.router.complete("SUMMARIZER", _R(messages=[
        _M(role="system", content="Compare these anonymous candidate answers to the same prompt. "
                                  "Name the best one (by letter) and why, in a short paragraph."),
        _M(role="user", content=f"Prompt: {body.prompt}\n\n{anonymized}")]))
    return {"prompt": body.prompt, "candidates": outputs, "synthesis": synth.text}


@app.get("/api/v1/agents", dependencies=[Depends(auth)])
async def list_agents():
    return [{"name": n, "description": a.description,
             "grant": getattr(a, "grant", [])} for n, a in state.agents.items()]


@app.get("/metrics", dependencies=[Depends(auth)])
async def metrics():
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)


# ── tools + skills (the shared resource layer, read-only views) ──────


@app.get("/api/v1/tools", dependencies=[Depends(auth)])
async def list_tools():
    return state.tools.specs()


@app.get("/api/v1/skills", dependencies=[Depends(auth)])
async def list_skills():
    return [{"name": n, "description": state.skills.get(n).description,
             "required_tools": state.skills.get(n).required_tools}
            for n in state.skills.names()]


# ── memory (user control — MEMORY_ARCHITECTURE §5) ───────────────────


class RememberBody(BaseModel):
    content: str
    kind: str = "fact"


def _memory_or_501():
    mem = state.ctx.memory
    if not hasattr(mem, "list_all"):
        raise HTTPException(501, "memory layer not enabled (features.memory in config/app.yaml)")
    return mem


@app.get("/api/v1/memory", dependencies=[Depends(auth)])
async def list_memory():
    return await _memory_or_501().list_all()


@app.post("/api/v1/memory", dependencies=[Depends(auth)])
async def add_memory(body: RememberBody):
    await _memory_or_501().remember(body.content, kind=body.kind)
    return {"status": "stored"}


@app.delete("/api/v1/memory/{memory_id}", dependencies=[Depends(auth)])
async def delete_memory(memory_id: str):
    await _memory_or_501().forget(memory_id)
    return {"status": "deleted"}


@app.get("/api/v1/memory/export", dependencies=[Depends(auth)])
async def export_memory():
    return {"user": state.settings.user_name, "memories": await _memory_or_501().list_all()}


# ── system ────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/v1/health/deps", dependencies=[Depends(auth)])
async def health_deps():
    deps: dict[str, str] = {}
    try:
        await state.store.list_sessions()
        deps["postgres"] = "ok"
    except Exception as e:
        deps["postgres"] = f"error: {type(e).__name__}"
    for provider, key in (
        ("groq", state.settings.groq_api_key),
        ("google", state.settings.google_api_key),
        ("nvidia", state.settings.nvidia_api_key),
    ):
        deps[provider] = "configured" if key else "missing_key"
    return deps


@app.get("/api/v1/system/models", dependencies=[Depends(auth)])
async def system_models():
    return state.router.active_models()


# ── voice (Path A composed + Path B native — Docs_COMPLEX/voice) ──────

from alan_t.app.voice import mount_voice  # noqa: E402

mount_voice(app, state, auth_dep=Depends(auth))


# ── web UI (Alan_T's own client) ──────────────────────────────────────

if state.ctx.config.get("features", {}).get("webui"):
    from alan_t.app.webui import mount_webui

    mount_webui(app)
