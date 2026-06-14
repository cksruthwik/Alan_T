# Alan_T — Memory Architecture

Version: 0.2
Status: Active — lean scope, **M1** ([BUILD_ORDER.md](../BUILD_ORDER.md))

Memory is the product. A chat UI over Llama exists everywhere; an assistant that still knows your preferences, projects, and history next month is what Alan_T is for.

> **Decision (ADR-016): use Mem0.** The lean build adopts **Mem0** for long-term memory rather than building a custom confidence-gated layer up front. This document is the contract the Memory agent exposes; Mem0 implements most of it (taxonomy, recall, supersede). Alan_T's own confidence-gated memory is a later upgrade — earned by logged failure cases where Mem0 falls short, not built speculatively.

## 1. The Stores (lean)

| Layer | Store | Lifetime | Contents |
|---|---|---|---|
| **Short-term** | Postgres (session window) | session / hours | conversation window, active task context |
| **Long-term** | Mem0 over Postgres | permanent (user-controlled) | facts, preferences, goals, projects, episodic summaries |
| **Semantic** | pgvector (in Postgres) | permanent (re-derivable) | embeddings of documents, conversation summaries, memory items |

All behind ports (`RelationalStore`, `VectorStore`) — see [SYSTEM_OVERVIEW.md](../architecture/SYSTEM_OVERVIEW.md). Postgres is the source of truth for memory; pgvector holds derived vectors for similarity recall and can always be rebuilt from Postgres + sources. (Redis as a short-term cache is deferred — at single-user scale the session window reads fine from Postgres — ADR-021.)

## 2. Memory Item Model (long-term)

```
memory_items
  id, kind, content, source, confidence, created_at, updated_at,
  last_accessed_at, access_count, status, embedding_ref, tags[]
```

**Kinds:**
- `preference` — "prefers TypeScript", "no meetings before 10:00"
- `fact` — stable personal/world facts: "works at X", "cat named Pixel"
- `goal` — active objectives with optional horizon: "learn Rust by Q4"
- `project` — ongoing work context: "Alan_T uses LangGraph + free-tier APIs"
- `episode` — summarized event: "2026-06-13: designed the memory architecture"
- `lesson` — operational learning (populated once the Reflection agent is built — deferred)

**Source ∈** `explicit` (user said "remember…"), `extracted` (post-turn extraction). `consolidated` (nightly job) and `reflection` arrive with their deferred subsystems.

**Status ∈** `active`, `superseded` (points to replacement), `archived`, `deleted_pending` (soft-delete window).

## 3. Write Paths

1. **Explicit:** `remember_fact` tool → stored at confidence 1.0 immediately.
2. **Extraction:** after each turn, a queued job runs `fact_extract.j2` (SUMMARIZER model) over the turn → candidate facts JSON → rules gate:
   - confidence ≥ 0.8 → store as `active`
   - 0.5–0.8 → store as `active` but flagged for review surface
   - < 0.5 → discard
   - near-duplicate (embedding similarity > 0.92 against existing) → merge/refresh `updated_at` instead of inserting
3. **Consolidation:** a nightly episodic→durable summarization job is a deferred upgrade (arrives with the Automation agent).
4. **Contradiction handling:** new item contradicting an existing one (same subject, conflicting value) → newer wins, older becomes `superseded` with a pointer. Never silently keep both as `active`.

## 4. Read Path (recall)

At `load_context` ([ORCHESTRATION.md](../architecture/ORCHESTRATION.md) W1):

```
score = 0.45·embedding_similarity(query, item)
      + 0.25·recency_decay(updated_at)
      + 0.15·access_frequency_norm
      + 0.15·kind_prior        # preferences/goals get a floor boost
```

Top items up to the 600-token memory budget ([PROMPTS.md](../ai/PROMPTS.md) §2), formatted with dates ("noted 2026-05-02: prefers …"). Preferences and active goals have a small always-include floor so the assistant never forgets who it's talking to.

`last_accessed_at`/`access_count` updated on use — recall strengthens memories, mirroring how consolidation later prunes never-used ones.

## 5. User Control (non-negotiable, per PRD privacy goals)

- "What do you know about me?" → Memory agent lists items grouped by kind, with sources and dates.
- "Forget X" → `forget_memory` (ASK tier) → `deleted_pending` (7-day soft window) → hard delete + vector removal.
- Review surface: flagged low-confidence extractions await confirm/reject.
- Full export: `GET /memory/export` → JSON dump. It's the user's data.

## 6. What Memory Is Not

- Not the conversation log (that's `conversation_turns`, kept verbatim, separately).
- Not the document corpus (that's the knowledge layer — facts ABOUT documents may be memories; document CONTENT is not).
- Not a scratchpad — task state lives in LangGraph checkpoints and dies with the task.

Schema details (memory items + vectors, all in Postgres/pgvector): [POSTGRES_SCHEMA.md](../data/POSTGRES_SCHEMA.md).
