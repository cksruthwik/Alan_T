"""Ingestion (KNOWLEDGE.md §1): sync → ledger check → chunk → embed (batched) → upsert.

Runs as an in-process background task at M2 (ADR-021 — no queue container until a
real concurrency need appears). Jobs are idempotent: deterministic chunk IDs make
re-runs safe; the ledger makes unchanged corpora cost zero API calls.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from alan_t.adapters.postgres.models import Chunk, IngestLedger
from alan_t.adapters.vfs_files import VfsFiles
from alan_t.core.knowledge.chunking import chunk_file
from alan_t.core.ports import LLMSeam

log = logging.getLogger("alan_t.ingest")

EMBED_BATCH = 64


class Ingester:
    def __init__(self, engine: AsyncEngine, llm: LLMSeam, files: VfsFiles, embedder_model: str):
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self._llm = llm
        self._files = files
        self._embedder_model = embedder_model

    async def run_full(self) -> dict:
        """Sync mounts into the mirror, then ingest changed/new files. Returns stats."""
        await self._files.sync_mounts()
        sources = await self._files.list_sources()
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

        # tombstone scan: ledger vpaths that vanished from the mirror
        for vpath in set(ledger) - live:
            if ledger[vpath].status != "tombstoned":
                await self._tombstone(vpath)
                stats["tombstoned"] += 1
        log.info("ingest run: %s", stats)
        return stats

    async def _ingest_one(self, vpath: str, content_hash: str) -> int:
        data = await self._files.read(vpath)
        chunks = chunk_file(vpath, data, content_hash)
        if chunks is None:  # unsupported type — typed skip
            await self._ledger_update(vpath, content_hash, 0, "ok")
            return 0

        vectors: list[list[float]] = []
        for i in range(0, len(chunks), EMBED_BATCH):
            batch = chunks[i:i + EMBED_BATCH]
            vectors.extend(await self._llm.embed([c.body for c in batch]))

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
