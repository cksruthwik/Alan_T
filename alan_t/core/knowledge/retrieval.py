"""Hybrid retrieval (KNOWLEDGE.md §4): vector ∥ keyword → RRF fusion → top-k.

The keyword leg catches exact identifiers/names that embeddings blur —
non-negotiable for code and personal names.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from alan_t.core.ports import LLMSeam

RRF_K = 60
TOP_K = 8


@dataclass
class RetrievedChunk:
    chunk_id: str
    vpath: str
    body: str
    payload: dict
    score: float          # fused RRF score
    similarity: float     # cosine similarity from the vector leg (0 if keyword-only)


class Retriever:
    def __init__(self, engine: AsyncEngine, llm: LLMSeam):
        self._engine = engine
        self._llm = llm

    async def search(self, query: str, top_k: int = TOP_K) -> list[RetrievedChunk]:
        [qvec] = await self._llm.embed([query])
        qvec_str = "[" + ",".join(f"{x:g}" for x in qvec) + "]"

        async with self._engine.connect() as conn:
            vec_rows = (await conn.execute(text(
                "SELECT chunk_id, vpath, body, payload, "
                "1 - (embedding <=> CAST(:q AS vector)) AS sim "
                "FROM chunks ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
            ), {"q": qvec_str, "k": top_k * 2})).mappings().all()

            kw_rows = (await conn.execute(text(
                "SELECT chunk_id, vpath, body, payload "
                "FROM chunks WHERE tsv @@ plainto_tsquery('english', :q) "
                "ORDER BY ts_rank(tsv, plainto_tsquery('english', :q)) DESC LIMIT :k"
            ), {"q": query, "k": top_k * 2})).mappings().all()

        # Reciprocal Rank Fusion
        fused: dict[str, RetrievedChunk] = {}
        for rank, row in enumerate(vec_rows):
            fused[row["chunk_id"]] = RetrievedChunk(
                chunk_id=row["chunk_id"], vpath=row["vpath"], body=row["body"],
                payload=row["payload"], score=1 / (RRF_K + rank + 1), similarity=row["sim"],
            )
        for rank, row in enumerate(kw_rows):
            if row["chunk_id"] in fused:
                fused[row["chunk_id"]].score += 1 / (RRF_K + rank + 1)
            else:
                fused[row["chunk_id"]] = RetrievedChunk(
                    chunk_id=row["chunk_id"], vpath=row["vpath"], body=row["body"],
                    payload=row["payload"], score=1 / (RRF_K + rank + 1), similarity=0.0,
                )
        return sorted(fused.values(), key=lambda c: c.score, reverse=True)[:top_k]
