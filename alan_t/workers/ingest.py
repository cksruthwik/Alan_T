"""Ingestion (KNOWLEDGE.md §1): sync → ledger check → chunk → embed (batched) → upsert.

Runs as an in-process background task at M2 (ADR-021 — no queue container until a
real concurrency need appears). Jobs are idempotent: deterministic chunk IDs make
re-runs safe; the ledger makes unchanged corpora cost zero API calls.
"""

from __future__ import annotations

import hashlib
import logging
import struct
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from alan_t.adapters.local_files import LocalFiles
from alan_t.adapters.postgres.models import Chunk, EmbeddingCache, IngestLedger
from alan_t.core.knowledge.chunking import chunk_file
from alan_t.core.ports import LLMSeam

log = logging.getLogger("alan_t.ingest")

EMBED_BATCH = 64


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


class Ingester:
    def __init__(self, engine: AsyncEngine, llm: LLMSeam, files: LocalFiles, embedder_model: str):
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self._llm = llm
        self._files = files
        self._embedder_model = embedder_model

    async def run_full(self) -> dict:
        """Scan the mounts directly and ingest changed/new files. Returns stats."""
        sources = await self._files.scan()
        stats = {"seen": len(sources), "skipped": 0, "ingested": 0, "failed": 0, "tombstoned": 0}

        async with self._sessions() as db:
            ledger = {
                row.vpath: row
                for row in await db.scalars(select(IngestLedger))
            }

        live = set()
        for src in sources:
            live.add(src.vpath)
            entry = ledger.get(src.vpath)
            if entry and entry.content_hash == src.content_hash \
                    and entry.embedder_model == self._embedder_model and entry.status == "ok":
                stats["skipped"] += 1
                continue
            try:
                n = await self._ingest_one(src.vpath, src.content_hash)
                stats["ingested" if n >= 0 else "skipped"] += 1
            except Exception as e:
                stats["failed"] += 1
                await self._ledger_update(src.vpath, src.content_hash, 0, "failed", error=str(e))
                log.exception("ingest failed for %s", src.vpath)

        # tombstone scan: ledger vpaths that vanished — but ONLY under mounts
        # that are currently available. A missing mount (failed bind-mount,
        # wrong path) must not wipe its chunks; that's a mount failure, not a
        # user deleting all their files. Its rows are left untouched until the
        # mount returns.
        available = self._files.available_prefixes()
        for vpath in set(ledger) - live:
            if ledger[vpath].status == "tombstoned":
                continue
            if not any(vpath.startswith(prefix) for prefix in available):
                stats["skipped_unavailable"] = stats.get("skipped_unavailable", 0) + 1
                continue
            await self._tombstone(vpath)
            stats["tombstoned"] += 1
        log.info("ingest run: %s", stats)
        return stats

    async def _embed_cached(self, bodies: list[str]) -> list[list[float]]:
        """Embed with the by-content-hash cache (LLM_STRATEGY §6): re-ingesting
        unchanged chunk text — even inside a changed file — costs zero quota."""
        keys = [hashlib.sha256(b.encode()).hexdigest() for b in bodies]
        async with self._sessions() as db:
            rows = await db.execute(
                select(EmbeddingCache.content_hash, EmbeddingCache.vector).where(
                    EmbeddingCache.embedder_model == self._embedder_model,
                    EmbeddingCache.content_hash.in_(set(keys))))
            cached = {h: _unpack(v) for h, v in rows}
        vectors: list[list[float] | None] = [cached.get(k) for k in keys]
        misses = [i for i, v in enumerate(vectors) if v is None]
        fresh: dict[str, list[float]] = {}
        for start in range(0, len(misses), EMBED_BATCH):
            idx_batch = misses[start:start + EMBED_BATCH]
            embedded = await self._llm.embed([bodies[i] for i in idx_batch])
            for i, vec in zip(idx_batch, embedded):
                vectors[i] = vec
                fresh[keys[i]] = vec
        if fresh:
            async with self._sessions.begin() as db:
                for key, vec in fresh.items():
                    await db.execute(insert(EmbeddingCache).values(
                        content_hash=key, embedder_model=self._embedder_model,
                        vector=_pack(vec)).on_conflict_do_nothing(
                            index_elements=["content_hash", "embedder_model"]))
        if misses:
            log.info("embed: %d cached / %d fresh", len(bodies) - len(misses), len(misses))
        return vectors  # type: ignore[return-value]  # all None slots filled above

    async def _ingest_one(self, vpath: str, content_hash: str) -> int:
        data = await self._files.read(vpath)
        chunks = chunk_file(vpath, data, content_hash)
        if chunks is None:  # unsupported type — typed skip
            await self._ledger_update(vpath, content_hash, 0, "ok")
            return 0

        vectors = await self._embed_cached([c.body for c in chunks])

        async with self._sessions.begin() as db:
            # deterministic chunk_ids → idempotent point-upserts; stale chunks removed first
            await db.execute(delete(Chunk).where(Chunk.vpath == vpath))
            for c, v in zip(chunks, vectors):
                stmt = insert(Chunk).values(
                    chunk_id=c.chunk_id, vpath=c.vpath, body=c.body,
                    payload=c.payload, embedding=v,
                ).on_conflict_do_update(
                    index_elements=["chunk_id"],
                    set_={"body": c.body, "payload": c.payload, "embedding": v},
                )
                await db.execute(stmt)
        await self._ledger_update(vpath, content_hash, len(chunks), "ok")
        return len(chunks)

    async def _tombstone(self, vpath: str) -> None:
        async with self._sessions.begin() as db:
            await db.execute(delete(Chunk).where(Chunk.vpath == vpath))
        await self._ledger_update(vpath, "", 0, "tombstoned")

    async def _ledger_update(self, vpath: str, content_hash: str, chunk_count: int,
                             status: str, error: str | None = None) -> None:
        async with self._sessions.begin() as db:
            stmt = insert(IngestLedger).values(
                vpath=vpath, content_hash=content_hash, embedder_model=self._embedder_model,
                chunk_count=chunk_count, status=status, error=error,
                embedded_at=datetime.now(timezone.utc) if status == "ok" else None,
            ).on_conflict_do_update(
                index_elements=["vpath"],
                set_={"content_hash": content_hash, "embedder_model": self._embedder_model,
                      "chunk_count": chunk_count, "status": status, "error": error,
                      "updated_at": func.now()},
            )
            await db.execute(stmt)

    async def status(self) -> dict:
        async with self._sessions() as db:
            rows = (await db.execute(
                select(IngestLedger.status, func.count()).group_by(IngestLedger.status)
            )).all()
            chunk_total = (await db.execute(select(func.count()).select_from(Chunk))).scalar()
        return {"ledger": {s: c for s, c in rows}, "chunks": chunk_total}
