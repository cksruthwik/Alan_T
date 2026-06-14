# Alan_T — Knowledge Pipeline (Ingestion · Chunking · Vector Store · RAG)

Version: 0.2
Status: Active — lean scope ([BUILD_ORDER.md](../BUILD_ORDER.md)). Consolidates ingestion, chunking, vector store, and RAG.

How the user's files become cited answers. Sources → ai-vfs → ingest (parse → chunk → embed → upsert to **pgvector**) → hybrid retrieval → RAG with citations. Lands at **M2**. Embeddings and chat both go through the **one LiteLLM seam** (Groq / Google / NVIDIA NIM fallback chain).

---

## 1. Ingestion

Sources → searchable vectors, incrementally, within free-tier quota. Runs in the worker process, never in the API process.

```
trigger ─▶ enqueue(vpath) ─▶ ledger check ─▶ parse ─▶ chunk ─▶ embed (batched) ─▶ upsert ─▶ ledger update
   │                            │ unchanged: skip                      │ quota: pause+resume
 watcher / manual / rescan      └──────────────── tombstone scan handles deletions
```

**Triggers:** ai-vfs ChangeEvents (sync service mirrors real folders into ai-vfs and emits events — [AI_VFS.md](AI_VFS.md)); `POST /ingest` (manual, ASK-tier tool); scheduled full re-scan (weekly, cheap thanks to the ledger).

### Queue semantics (background worker)

- One job = one vpath. Jobs are idempotent and safe to re-run.
- Priorities: manual > watcher > rescan.
- Concurrency low (default 2 workers) — ingestion is deliberately slow-and-steady; it shares quota with nothing interactive.
- Failures: 3 attempts with exponential backoff → dead-letter, surfaced in metrics.

*(Lean note: the M2 build can run ingestion as an in-process background task or a simple worker. A dedicated queue (e.g. arq/Redis) is added only when a real concurrency/scheduling need appears — ADR-021.)*

### The ingest ledger (Postgres — the quota shield)

```
ingest_ledger: vpath, content_hash, chunk_count, embedder_model,
               embedded_at, status(ok|failed|pending|tombstoned)
```

- `content_hash` is the hash ai-vfs already computed for the mirrored version — one metadata read, no re-hashing.
- Job starts: `stat(vpath)` → hash equal to ledger & same `embedder_model` → **skip**. Re-ingesting an unchanged corpus costs zero API calls.
- `embedding_cache(content_hash → vector)` lets even changed files reuse vectors for unchanged chunks.
- **Deletions:** rescan diff (ledger vpaths minus VFS listing) → tombstone → delete vectors from pgvector → ledger row marked.

### Parsers

| Type | Parser | Output |
|---|---|---|
| Markdown / txt | native | text + heading tree |
| PDF / Office | docling — layout-aware | text + structure + page map |
| Code | tree-sitter | text + symbol tree (functions/classes) |
| HTML | trafilatura | main-content text |
| Email | stdlib `email` | text + headers |

Parser errors → typed skip, never fatal. *(Image OCR/captioning deferred — Vision is dropped for now.)*

### Embedding (the rate-limited step)

- Model: `gemini-embedding-001` via the LiteLLM seam. **No silent fallback to a different embedding model** — embedding-space discipline (mixing models corrupts the vector space).
- Batched requests; batch size and RPM throttle from config.
- On 429: pause the queue (not the job), respect `Retry-After`, resume — a half-embedded file stays `pending`; chunks already upserted are fine (idempotent point-upserts by deterministic chunk ID).

### Initial corpus bootstrap (practical reality)

First ingestion of years of notes + repos will exceed daily free embedding quota. Expected and fine: the queue runs for days, resuming at each quota window; priority config front-loads what matters (`notes` before `repos`); progress visible via `GET /ingest/status`. Don't "solve" this with a paid burst or a second key pool unless the user asks — slow bootstrap is the honest free-tier behavior.

---

## 2. Chunking

Chunking quality bounds retrieval quality — garbage cuts make every downstream stage worse.

**Principles:**
1. **Cut on meaning, not character counts.** Parser structure (headings, symbols, pages) defines boundaries; size limits only force splits within a unit.
2. **Every chunk stands alone.** It carries its own context header (title path / symbol path).
3. **Deterministic IDs.** `chunk_id = hash(vpath, structural_path, position)` — re-ingestion overwrites in place, no duplicates.
4. **Targets, not dogma:** ~256–512 tokens body, 10–15% overlap for prose; code follows symbol boundaries.

**Per-type:**
- **Prose (Markdown/notes/HTML):** split on heading hierarchy; sections > 512 tokens split on paragraphs with overlap. Context header prepended: `"[Notes] Alan_T design > Memory > Recall scoring"`. Tiny trailing sections (< 40 tokens) merge into the previous chunk.
- **Code (tree-sitter):** one chunk per top-level symbol; oversized symbols split at nested-block boundaries with the signature repeated. Header: `"[repo:ai-vfs] src/mount.py > class MountTable > def resolve"`. Payload carries `start_line`/`end_line` → `file:line` citations.
- **PDF:** heading detection where extractable; fallback page-window chunks (1 page, 20% overlap) with `page` in payload.
- **Conversation episodes:** one chunk per episode summary. Raw turns are NOT embedded (noise; the log stays in Postgres).

**Chunk record:**
```
embedded text = context_header + "\n\n" + body
payload       = { vpath, mount, content_hash, structural_path,
                  start_line?, end_line?, page?, mtime, doc_type, tags[] }
```

**Trade-offs:** overlap costs ~10–15% extra embedding volume (accepted for recall). No semantic chunking in v1 (doubles cost for marginal gain at this scale). Revisit with evidence from retrieval metrics.

---

## 3. Vector Store (pgvector)

The `VectorStore` port, backed by **pgvector inside Postgres** — one less container than a dedicated vector DB, ample at single-user scale (ADR-021).

```python
class VectorStore(Protocol):
    async def upsert(self, collection: str, points: list[VectorPoint]) -> None
    async def search(self, collection: str, query: SearchQuery) -> list[ScoredPoint]
    async def delete(self, collection: str, filter: PayloadFilter) -> int
```

- Core types only — no DB client types cross the boundary. Swap target if pgvector ever falls short: Qdrant/Chroma (the port keeps that honest).
- **Two logical collections**, scoped by payload filters (`mount`, `doc_type`, `repo`, `kind`), not ten:

| Collection | Contents | Source of truth |
|---|---|---|
| `knowledge` | document/code/PDF chunks | re-derivable from sources via ledger |
| `memory` | embedded memory items + episodes | Postgres / Mem0 |

**Operational rules:**
1. **Embedder stamp:** each collection records `embedder_model` + `dimension`; the adapter refuses vectors from a different model (hard error).
2. **Deterministic point IDs** = chunk IDs → idempotent upserts.
3. **Deletes by payload filter** (vpath) on tombstone events — no orphan vectors.
4. **Rebuildable:** `knowledge` regenerates from sources + ledger; `memory` from Postgres. Take nightly DB backups anyway.
5. **Health degradation:** vector search down → File agent answers without retrieval, flagged `degraded` — never a hard crash of chat.

**Sizing:** tens of thousands of chunks × embedding vectors — trivial for pgvector with a standard HNSW/IVFFlat index. No quantization, sharding, or tuning until metrics say otherwise.

---

## 4. RAG (question → cited answer)

```
question
  ─▶ scope resolution        # which mounts/types? ("in my notes" → mount:notes)
  ─▶ query rewrite           # conversational → standalone (skip if standalone)
  ─▶ hybrid retrieval        # vector (pgvector) ∥ keyword (Postgres FTS) → RRF fusion → top 8
  ─▶ context assembly        # dedupe, order, token budget, source tags
  ─▶ answer generation       # CHAT (or LONG_CONTEXT if context > 24k tokens)
  ─▶ citation check          # every claim maps to a cited chunk
  ─▶ answer + citations
```

**Stage rules:**
- **Scope resolution** — explicit user scoping ("in my notes", "in repo X") → payload filters. No scope → all of `knowledge`. Memory questions additionally search the `memory` collection.
- **Query rewrite** — only when the question contains anaphora ("that", "the second one") or is a fragment; cheap heuristic + a small model call. Skipping when unneeded is the point.
- **Hybrid retrieval** — vector search (query embedded via Gemini) and keyword search (Postgres FTS) run in parallel; fused with Reciprocal Rank Fusion. Keyword side catches exact identifiers/names that embeddings blur — non-negotiable for code and personal names.
- **Context assembly** — dedupe near-identical chunks, order highest-scored first, stitch adjacent chunks for readability. Budget ~6k tokens. Each chunk introduced as `--- source: {vpath}#{position} ---`.
- **Answer generation** — answer only from provided chunks; cite `[vpath]` inline; if chunks don't contain the answer, say exactly that. Code questions use `file:line` citation format.
- **Citation check** — post-generation pass: claims without citation → stripped or answer flagged. Uncited assertions about the user's own documents are defects.

**Honesty contract (what makes personal RAG trustworthy):**
1. Empty retrieval → "I didn't find anything about X in your files" — never a fluent improvisation.
2. Low-relevance retrieval → answer prefixed with uncertainty + what WAS searched.
3. Degraded pipeline (vector store down, rewrite skipped) → stated in the answer when it could matter.
4. Citations link to reality: `vpath#position` resolves to the actual chunk.

**Quota profile per question:** ~2–4 small calls (1 embedding + 0–1 rewrite + 1 answer + optional citation check). If RAG becomes the quota hog, rewrite and citation-check are the configurable sacrifices, in that order.

**Evaluation (small and real):** ~30 (question, expected-source, expected-answer-gist) triples from the actual corpus. Metrics: retrieval hit@5, answer faithfulness, citation validity (mechanical). Targets: hit@5 > 85%, citation validity > 95%. Run on every chunking/embedding/prompt change.

---

## 5. Later Upgrades (recorded, not promised)

- **Rerank** (top 8 → top 4 via an LLM-rerank call) — add when retrieval precision needs it; skip under quota pressure with `degraded:["rerank_skipped"]`.
- **Parent-document retrieval** (search small, answer big).
- **Repo-aware retrieval:** symbol-graph expansion for code questions.
- **Multi-hop:** decompose comparative questions into sub-queries, answer over union.

Each is earned by evidence from retrieval metrics, not built speculatively.
