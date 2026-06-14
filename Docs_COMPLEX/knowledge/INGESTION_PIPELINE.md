# Alan_T — Ingestion Pipeline

Version: 0.1
Status: Active

Sources → searchable vectors, incrementally, within free-tier quota. Runs in the worker process, never in the API process.

## 1. Pipeline

```
trigger ─▶ enqueue(vpath) ─▶ ledger check ─▶ parse ─▶ chunk ─▶ embed (batched) ─▶ upsert ─▶ ledger update
   │                            │ unchanged: skip                      │ quota: pause+resume
 watcher / manual / rescan      └──────────────── tombstone scan handles deletions
```

**Triggers:** sync-service ChangeEvents (the source sync service mirrors real folders into ai-vfs and emits events after each mirror commit — [AI_VFS.md](AI_VFS.md) §2–3); `POST /ingest` (manual, ASK-tier tool); scheduled full re-scan (weekly, cheap thanks to ledger).

## 2. Queue Semantics (arq on Redis — ADR-012)

- One job = one vpath. Jobs are idempotent and safe to re-run.
- Priorities: manual > watcher > rescan, implemented as separate arq queues drained in priority order.
- Concurrency: low (default 2 workers) — ingestion is deliberately slow-and-steady; it shares quota with nothing interactive ([LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §7.4).
- Failures: 3 attempts with exponential backoff (arq retry mechanics) → dead-letter list (thin custom layer on retry exhaustion), surfaced in metrics and the weekly digest.

## 3. The Ingest Ledger (Postgres — the quota shield)

```
ingest_ledger: vpath, content_hash, chunk_count, embedder_model,
               embedded_at, status(ok|failed|pending|tombstoned)
```

- `content_hash` is the BLAKE3 hash ai-vfs already computed for the mirrored version — `stat` is one metadata read, no re-hashing ([AI_VFS.md](AI_VFS.md) §4).
- Job starts: `stat(vpath)` → hash equal to ledger & same `embedder_model` → **skip**. Re-ingesting an unchanged corpus costs zero API calls.
- Separately, `embedding_cache(content_hash → vector)` lets even changed files reuse vectors for unchanged chunks.
- **Deletions:** rescan diff (ledger vpaths minus VFS listing) → tombstone → delete vectors from Qdrant → ledger row marked.

## 4. Parsers

| Type | Parser | Output |
|---|---|---|
| Markdown / txt | native | text + heading tree |
| PDF / Office | docling — layout-aware (ADR-015); OCR fallback via VISION role for scanned pages (ASK-tier on first use — it's a cloud call per page) | text + structure + page map |
| Code | tree-sitter | text + symbol tree (functions/classes) |
| HTML | trafilatura | main-content text |
| Images | VISION role caption+OCR (deferred to Phase 4) | description + extracted text |
| Email | stdlib `email` | text + headers |

Parser errors → typed skip, never fatal (AI-VFS contract rule 3).

## 5. Chunking

Delegated entirely to [CHUNKING_STRATEGY.md](CHUNKING_STRATEGY.md). The pipeline passes parser structure (headings/symbols/pages) through so chunkers can cut on semantic boundaries.

## 6. Embedding (the rate-limited step)

- Model: `EMBEDDER` role → `gemini-embedding-001`. No silent fallback (embedding-space discipline, [LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §6).
- Batched requests; batch size and RPM throttle from config.
- On 429: pause the queue (not the job), respect `Retry-After`, resume — a half-embedded file stays `pending`, finishing later; chunks already upserted are fine (idempotent point-upserts by deterministic chunk ID).
- Each vector upserted with full payload (source, hash, position, metadata) per [QDRANT_SCHEMA.md](../data/QDRANT_SCHEMA.md).

## 7. Post-Ingest Verification

Per batch: sample N chunks, run a search for distinctive phrases from each, assert the chunk comes back top-5. Failures → batch flagged `failed` in ledger + alert metric. (The cheap canary for silent pipeline corruption — embedder mismatch, payload bugs, collection misconfig.)

## 8. Initial Corpus Bootstrap (practical reality)

First ingestion of years of notes + repos will exceed daily free embedding quota. Expected and fine:

- The queue simply runs for days, resuming at each quota window.
- Priority config lets the user front-load what matters (`notes` mount before `repos`).
- Progress visible: `GET /ingest/status` → files done/pending, ETA at current quota burn.

Don't "solve" this with a paid burst or a second API key pool unless the user asks — slow bootstrap is the honest free-tier behavior.
