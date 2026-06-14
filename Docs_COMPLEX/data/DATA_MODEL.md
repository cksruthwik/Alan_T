# Alan_T — Data Model

Version: 0.1
Status: Active

Conceptual entities and where they live. Physical schemas: [POSTGRES_SCHEMA.md](POSTGRES_SCHEMA.md), [QDRANT_SCHEMA.md](QDRANT_SCHEMA.md). Redis structures defined here (they have no schema file of their own).

## 1. Entity Map

```
User (singleton)
 ├── Session ──< ConversationTurn
 ├── MemoryItem  (kinds: preference/fact/goal/project/episode/lesson)
 ├── KnowledgeSource ──< IngestLedgerEntry ──< Chunk(→Qdrant)
 ├── TaskRun ──< TaskStep ──< StepAttempt
 ├── ToolAuditEntry
 ├── ScheduledJob ──< JobRun
 └── QuotaWindow (per provider+model)
```

Single-user system (ADR-008): `User` is configuration, not a table — no `user_id` foreign keys anywhere. If that ever changes it's a major migration, accepted knowingly.

## 2. Entities

| Entity | Store | Purpose | Lifecycle |
|---|---|---|---|
| Session | Postgres (+Redis cache) | one conversation thread; maps to LangGraph `thread_id` | created on first turn; never deleted (archived) |
| ConversationTurn | Postgres | verbatim user/assistant turns + modality + trace ref | append-only |
| MemoryItem | Postgres (vector → Qdrant `memory`) | durable knowledge about the user ([MEMORY_ARCHITECTURE.md](../memory/MEMORY_ARCHITECTURE.md) §2) | status machine: active→superseded/archived/deleted |
| IngestLedgerEntry | Postgres | content-hash ledger per vpath ([INGESTION_PIPELINE.md](../knowledge/INGESTION_PIPELINE.md) §3) | upserted per ingest |
| EmbeddingCacheEntry | Postgres | content_hash → vector (quota shield) | LRU-pruned by size |
| Chunk | Qdrant `knowledge` | embedded chunk + provenance payload | overwritten by deterministic ID |
| TaskRun / TaskStep / StepAttempt | Postgres | agentic task execution record ([PLANNING_ENGINE.md](../ai/PLANNING_ENGINE.md)) | append-only; terminal states |
| ToolAuditEntry | Postgres | every tool execution: who/what/args-hash/verdict/duration | append-only, never pruned silently |
| ScheduledJob / JobRun | Postgres | automations + their outcomes | jobs editable; runs append-only |
| QuotaWindow | Redis | rolling counters per provider+model+window | TTL = window |
| LangGraph checkpoint | Postgres (`lg_checkpoints`) | graph state per thread | managed by checkpointer |

## 3. Redis Structures (ephemeral state only — losing Redis must never lose user data)

| Key pattern | Type | TTL | Purpose |
|---|---|---|---|
| `sess:{id}:window` | list | 24h | recent turns cache (truth in Postgres) |
| `sess:{id}:scratch` | hash | 24h | active task context |
| `arq:*` | arq structures | — | job queues + cron: ingestion (per-priority), extraction, consolidation (ADR-012) |
| `quota:{provider}:{model}:{window}` | counter | window | budget tracking ([LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §7) |
| `dlq:*` | list | — | dead-letter queues |

## 4. Data Rules

1. **One source of truth per fact.** Postgres for operational/memory data; sources+ledger for knowledge; Qdrant is always derived and rebuildable.
2. **Append-only history.** Turns, audits, task runs, job runs are never updated in place — corrections are new rows. Memory items are the exception with an explicit status machine.
3. **Provenance everywhere.** Every derived artifact (chunk, memory item, digest) records what produced it (source vpath/turn ids/job id + model used).
4. **Soft delete with a window** (7 days) for user-facing deletions (memories, sources); hard delete + vector removal after.
5. **PII lives at home.** Postgres/Redis/Qdrant hold everything; cloud providers see only what a specific call sends them — and the audit/trace records *that it was sent* ([SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md) §5).
6. **All access through repositories** (`RelationalStore` port) — no raw SQL outside the Postgres adapter; no ORM models leaking into core.
