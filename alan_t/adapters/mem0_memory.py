"""Mem0-backed MemoryStore (ADR-016) — long-term facts/preferences with recall.

Mem0 owns extraction, dedup, and supersede; this adapter is the thin port
implementation. Vectors live in pgvector inside the same Postgres (ADR-021).
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from alan_t.core.types import MemoryFact

log = logging.getLogger("alan_t.memory")

USER_ID = "owner"  # single-user system


def _mem0_config(database_url: str, summarizer_model: str, embed_dim: int) -> dict:
    u = urlparse(database_url.replace("postgresql+asyncpg://", "postgresql://"))
    return {
        "llm": {
            "provider": "litellm",
            "config": {"model": summarizer_model, "temperature": 0.0},
        },
        "embedder": {
            "provider": "gemini",
            "config": {"model": "models/gemini-embedding-001", "embedding_dims": embed_dim},
        },
        "vector_store": {
            "provider": "pgvector",
            "config": {
                "user": u.username,
                "password": u.password,
                "host": u.hostname,
                "port": u.port or 5432,
                "dbname": u.path.lstrip("/"),
                "collection_name": "mem0_memories",
                "embedding_model_dims": embed_dim,
            },
        },
    }


class Mem0Memory:
    def __init__(self, database_url: str, summarizer_model: str = "gemini/gemini-2.5-flash-lite",
                 embed_dim: int = 1536):
        from mem0 import AsyncMemory

        self._memory_cls = AsyncMemory
        self._config = _mem0_config(database_url, summarizer_model, embed_dim)
        self._memory = None

    async def _mem(self):
        if self._memory is None:
            self._memory = self._memory_cls.from_config(self._config)
        return self._memory

    async def recall(self, query: str, limit: int = 10) -> list[MemoryFact]:
        mem = await self._mem()
        results = await mem.search(query=query, user_id=USER_ID, limit=limit)
        facts = []
        for r in results.get("results", []):
            noted = (r.get("created_at") or "")[:10]
            facts.append(MemoryFact(content=r["memory"], kind=r.get("category") or "fact",
                                    noted_at=noted))
        return facts

    async def remember(self, content: str, kind: str = "fact", source: str = "explicit") -> None:
        mem = await self._mem()
        # explicit "remember X" is stored verbatim, not re-inferred (confidence 1.0 path)
        await mem.add(content, user_id=USER_ID, infer=False, metadata={"kind": kind, "source": source})

    async def extract_from_turn(self, user_text: str, assistant_text: str) -> None:
        try:
            mem = await self._mem()
            await mem.add(
                [{"role": "user", "content": user_text},
                 {"role": "assistant", "content": assistant_text}],
                user_id=USER_ID,
                metadata={"source": "extracted"},
            )
        except Exception:
            # extraction is best-effort; a failed extraction never breaks the turn
            log.exception("post-turn memory extraction failed")

    # ── user-control surface (API_SPECIFICATION §3) ──

    async def list_all(self) -> list[dict]:
        mem = await self._mem()
        results = await mem.get_all(user_id=USER_ID)
        return results.get("results", [])

    async def forget(self, memory_id: str) -> None:
        mem = await self._mem()
        await mem.delete(memory_id=memory_id)
