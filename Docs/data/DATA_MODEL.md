# Alan_T — Data Model

Version: 0.2
Status: Active — lean scope ([BUILD_ORDER.md](../BUILD_ORDER.md))

Conceptual entities and where they live. Physical schema: [POSTGRES_SCHEMA.md](POSTGRES_SCHEMA.md). In the lean build **everything durable lives in Postgres** — operational data, memory, and (via pgvector) the vectors. No Redis, no separate vector DB (ADR-021).

## 1. Entity Map

```
User (singleton)
 ├── Session ──< ConversationTurn
 ├── MemoryItem  (kinds: preference/fact/goal/project/episode)   [Mem0 + Postgres]
 ├── KnowledgeSource ──< IngestLedgerEntry ──< Chunk (→ pgvector)
 ├── ToolAuditEntry
 └── QuotaWindow (per provider+model)
```

Single-user system (ADR-008): `User` is configuration, not a table — no `user_id` foreign keys anywhere. If that ever changes it's a major migration, accepted knowingly.

Deferred entities (arrive with their agents): `TaskRun / TaskStep` (Task Planning), `ScheduledJob / JobRun` (Automation).

## 2. Entities

| Entity | Store | Purpose | Lifecycle |
|---|---|---|---|
| Session | Postgres | one conversation thread; maps to LangGraph `thread_id` | created on first turn; never deleted (archived) |
| ConversationTurn | Postgres | verbatim user/assistant turns + modality + trace ref | append-only |
| MemoryItem | Mem0 over Postgres (vector → pgvector `memory`) | durable knowledge about the user ([MEMORY_ARCHITECTURE.md](../memory/MEMORY_ARCHITECTURE.md) §2) | status machine: active→superseded/archived/deleted |
| IngestLedgerEntry | Postgres | content-hash ledger per vpath ([KNOWLEDGE.md](../knowledge/KNOWLEDGE.md) §1) | upserted per ingest |
| EmbeddingCacheEntry | Postgres | content_hash → vector (quota shield) | LRU-pruned by size |
| Chunk | pgvector `knowledge` | embedded chunk + provenance payload | overwritten by deterministic ID |
| ToolAuditEntry | Postgres | every tool execution: who/what/args-hash/verdict/duration | append-only, never pruned silently |
| QuotaWindow | Postgres (or in-memory) counters | rolling counters per provider+model+window | TTL = window |
| LangGraph checkpoint | Postgres (`lg_checkpoints`) | graph state per thread | managed by checkpointer |

## 3. State that was Redis (now Postgres / in-process)

At single-user scale there's no Redis. The state that would have lived there:

| State | Lean home |
|---|---|
| session window / scratch | Postgres (read per turn — cheap at this scale) |
| job queues (ingestion) | in-process background tasks, or a worker when concurrency demands one |
| quota counters | Postgres counters or an in-memory window per process |
| dead-letter | a Postgres table or log entry |

Redis returns only if a real concurrency/latency need appears — the `VectorStore`/queue boundaries keep that swap honest.

## 4. Data Rules

1. **One source of truth per fact.** Postgres for operational/memory data; sources+ledger for knowledge; pgvector rows are always derived and rebuildable.
2. **Append-only history.** Turns, audits are never updated in place — corrections are new rows. Memory items are the exception with an explicit status machine.
3. **Provenance everywhere.** Every derived artifact (chunk, memory item) records what produced it (source vpath/turn ids + model used).
4. **Soft delete with a window** (7 days) for user-facing deletions (memories, sources); hard delete + vector removal after.
5. **PII lives at home.** Postgres (incl. pgvector) holds everything; cloud providers see only what a specific call sends them — and the audit/trace records *that it was sent* ([SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md)).
6. **All access through repositories** (`RelationalStore` port) — no raw SQL outside the Postgres adapter; no ORM models leaking into core.
