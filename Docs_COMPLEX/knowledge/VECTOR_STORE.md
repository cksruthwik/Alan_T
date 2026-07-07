# Alan_T — Vector Store

Version: 0.1
Status: Active

Qdrant behind the `VectorStore` port. ADR-005 in [DECISION_LOG.md](../architecture/DECISION_LOG.md).

## 1. The Port

```python
class VectorStore(Protocol):
    async def ensure_collection(self, spec: CollectionSpec) -> None
    async def upsert(self, collection: str, points: list[VectorPoint]) -> None
    async def search(self, collection: str, query: SearchQuery) -> list[ScoredPoint]
    async def delete(self, collection: str, filter: PayloadFilter) -> int
    async def info(self, collection: str) -> CollectionInfo
```

- `SearchQuery`: vector, top_k, payload filter, optional keyword component (adapter maps to native hybrid if supported, else the core fuses separately).
- Core types only — no Qdrant client types cross the boundary. Swap targets: pgvector (planned proof adapter), Chroma.

## 2. Why Qdrant First

- Payload filtering at search time (mount/doc_type/repo scoping) is first-class and fast.
- Named vectors + sparse vector support → native hybrid search path when we want it.
- Single container, low ops burden, snapshot backups.

pgvector remains attractive (one less service); it's the designated second adapter to prove the port honest ([BACKLOG.md](../product/BACKLOG.md) P3).

## 3. Collections

| Collection | Contents | Source of truth |
|---|---|---|
| `knowledge` | document/code/PDF chunks | re-derivable from sources via ledger |
| `memory` | embedded memory items + episodes | Postgres `memory_items` |

Two collections, not ten: payload filters do the scoping (`mount`, `doc_type`, `repo`, `kind`). New collections require a reason recorded in the decision log (e.g., a different embedding model or distance metric — not mere categories).

Collection config, payload schema, and index parameters: [QDRANT_SCHEMA.md](../data/QDRANT_SCHEMA.md).

## 4. Operational Rules

1. **Embedder stamp:** every collection stores `embedder_model` + `dimension` in its metadata; the adapter refuses to upsert vectors produced by a different model (hard error, not warning) — see embedding-space discipline, [LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §6.
2. **Deterministic point IDs** = chunk IDs ([CHUNKING_STRATEGY.md](CHUNKING_STRATEGY.md) §1.3) → idempotent upserts.
3. **Deletes by payload filter** (vpath) on tombstone events — no orphan vectors after file deletion ([INGESTION_PIPELINE.md](INGESTION_PIPELINE.md) §3).
4. **Rebuildable:** `knowledge` can be regenerated from sources + ledger; `memory` from Postgres. Qdrant snapshots are a convenience, not the safety net — but take them anyway (nightly, [DEPLOYMENT.md](../infra/DEPLOYMENT.md) §5).
5. **Health degradation:** Qdrant down → File agent answers without retrieval, flagged `degraded` ([WORKFLOWS.md](../architecture/WORKFLOWS.md) W1) — never a hard crash of chat.

## 5. Sizing Reality Check (personal scale)

Tens of thousands of chunks × 768–3072-dim vectors — trivial for a single Qdrant node; default HNSW parameters are fine. No quantization, no sharding, no tuning until metrics say otherwise. Resist premature ops sophistication.
