# Alan_T — Memory Consolidation

Version: 0.1
Status: Active (implementation: Phase 2)

The nightly process that turns raw conversation history into durable, compact memory — and keeps the memory store from rotting into a junk drawer.

## 1. Why Consolidation Exists

Per-turn extraction is greedy and local: it catches facts but produces fragments, duplicates, and stale items over time. Without consolidation, recall quality degrades as the store grows (retrieval noise drowns signal). Consolidation is the slow, global pass.

## 2. The Nightly Job (worker, scheduled ~03:00 local)

Runs entirely on SUMMARIZER role (`gemini-2.5-flash-lite`) under background-job quota throttles — it must never starve interactive traffic ([LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §7.4).

### Pass 1 — Episodic summarization
- Input: yesterday's `conversation_turns` (all sessions), task reports, ingestion events.
- Output: one `episode` memory item per meaningful session/task ("2026-06-13: planned X, decided Y, left Z open"), embedded into Qdrant.
- Sessions with no durable content (smalltalk, single lookups) produce nothing — an empty day is a valid result.

### Pass 2 — Deduplication & merge
- Cluster `active` items by embedding similarity (> 0.90) within the same `kind`.
- Each cluster → one merged item (union of content, max confidence, earliest `created_at`, latest `updated_at`); members become `superseded`.

### Pass 3 — Contradiction sweep
- Same-subject items with conflicting values (model-assisted comparison on candidate pairs from Pass 2 clustering): newer wins; older → `superseded`. Ambiguous conflicts (can't tell which is current) → flagged to the review surface instead of auto-resolved.

### Pass 4 — Decay & archive
- `episode` items: > 90 days old AND `access_count` = 0 → rolled up into monthly digest items, originals → `archived`.
- `fact`/`preference` items are NEVER auto-archived by age — staleness there is handled only by contradiction (a preference unused for a year is still a preference).
- `lesson` items: archived when their subject (tool/site/repo) no longer exists in config.

### Pass 5 — Goal/project refresh
- Active `goal`/`project` items cross-checked against recent episodes: goals with no related activity for 30 days → flagged "stale?" on the review surface (asked, not assumed).

## 3. Safety Properties

- **Idempotent:** re-running a night's job is a no-op (ledger of processed turn-ranges in Postgres).
- **Non-destructive:** nothing is hard-deleted; every merge/supersede is reversible via the `superseded` chain until the user purges.
- **Budgeted:** hard cap on tokens per nightly run (config); job stops cleanly at the cap and resumes next night — backlog, not blowout.
- **Audited:** every merge/supersede/archive decision logged with the item IDs and rationale snippet.

## 4. Weekly Review Digest (Phase 7 tie-in)

Sundays, the Automation agent composes a digest from the week's episodes: decisions made, open loops, stale goals, memory items awaiting review. Delivered per [WORKFLOWS.md](../architecture/WORKFLOWS.md) W7. This closes the loop: the user sees what the system is learning about them.

## 5. Metrics That Matter

(emitted per run → [METRICS.md](../observability/METRICS.md))
- items created/merged/superseded/archived per pass
- memory store size by kind over time (growth should be sublinear in conversation volume)
- recall hit-rate: fraction of recalled items actually used (LLM judge sample) — the canary for store rot
- tokens consumed vs. budget
