# Alan_T — Qdrant Schema

Version: 0.1
Status: Active

Two collections ([VECTOR_STORE.md](../knowledge/VECTOR_STORE.md) §3). Payloads are normative — retrieval filters and citations depend on these exact fields.

## 1. Collection: `knowledge`

```yaml
name: knowledge
vectors:
  size: 3072                  # gemini-embedding-001 default; SET AT CREATION from config
  distance: Cosine
metadata:                     # collection-level, written at creation
  embedder_model: gemini-embedding-001
  embedder_dim: 3072
  schema_version: 1
```

**Point ID:** deterministic chunk ID = `uuid5(vpath + structural_path + position)` ([CHUNKING_STRATEGY.md](../knowledge/CHUNKING_STRATEGY.md) §1.3).

**Payload (all points):**

| Field | Type | Indexed | Purpose |
|---|---|---|---|
| `vpath` | keyword | ✓ | source file (citation + tombstone deletes) |
| `mount` | keyword | ✓ | scope filter ("in my notes") |
| `doc_type` | keyword | ✓ | prose / code / pdf / email / transcript |
| `content_hash` | keyword | — | staleness checks |
| `structural_path` | text | — | heading/symbol path (display) |
| `position` | integer | — | chunk order within source |
| `body` | text | — | chunk text (returned to context assembly) |
| `mtime` | datetime | — | source modified time |
| `tags` | keyword[] | ✓ | user/auto tags |

**Code chunks add:** `repo` (keyword, ✓), `lang` (keyword, ✓), `symbol` (keyword, ✓), `start_line`, `end_line` (integer).
**PDF chunks add:** `page` (integer).

## 2. Collection: `memory`

```yaml
name: memory
vectors: { size: 3072, distance: Cosine }
metadata: { embedder_model: gemini-embedding-001, embedder_dim: 3072, schema_version: 1 }
```

**Point ID:** = `memory_items.id` (Postgres PK) — 1:1, Postgres is truth, this collection is rebuildable from it.

**Payload:** `kind` (keyword, ✓), `status` (keyword, ✓ — only `active` is searched), `content` (text), `tags` (keyword[], ✓), `updated_at` (datetime).

## 3. Invariants (enforced by the Qdrant adapter)

1. **Embedder stamp check:** adapter compares configured EMBEDDER model/dim against collection metadata on startup and before every upsert batch; mismatch → hard error. Changing the embedding model requires the explicit re-embed migration ([LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §6).
2. **Upserts only by deterministic ID** — no auto-generated point IDs anywhere.
3. **Deletes only by payload filter** on `vpath` (knowledge) or by ID (memory) — keeps tombstoning exact.
4. **`schema_version`** bumps require a documented migration note in [DECISION_LOG.md](../architecture/DECISION_LOG.md).

## 4. Search Defaults

| Use | Collection | Filter | top_k |
|---|---|---|---|
| RAG retrieval | knowledge | scope filters from query | 8 (pre-fusion) |
| Memory recall | memory | `status=active` | 12 (pre-scoring, [MEMORY_ARCHITECTURE.md](../memory/MEMORY_ARCHITECTURE.md) §4) |
| Dedup check (memory write) | memory | `status=active`, same `kind` | 3 |
| Consolidation clustering | memory | `status=active`, per kind | scroll all |

## 5. Ops

- Snapshots: nightly, retained 7 days ([DEPLOYMENT.md](../infra/DEPLOYMENT.md) §5) — convenience; both collections are rebuildable.
- No quantization/sharding/replicas at personal scale ([VECTOR_STORE.md](../knowledge/VECTOR_STORE.md) §5).
- Capacity sanity: 100k chunks × 3072-dim float32 ≈ 1.2 GB raw vectors — fine on one node. If the corpus
  somehow grows 10×, consider 768-dim output (gemini-embedding-001 supports Matryoshka truncation) — that is an embedding-space change, full re-embed migration required.
