# Alan_T — PostgreSQL Schema

Version: 0.2
Status: Active — lean scope ([BUILD_ORDER.md](../BUILD_ORDER.md)); normative DDL sketch; migrations (Alembic) are the executable truth once code exists.

In the lean build, embedding vectors live in **pgvector inside this database** (ADR-021). There is no Redis. Task/job tables (Task Planning, Automation) are deferred and arrive with their agents — shown at the end for reference but not created in M0–M4.

Conventions: `id` = UUIDv7 PK (time-ordered); timestamps `timestamptz`, `created_at` default `now()`; enums as Postgres enums; JSONB for provider-variable payloads only — queryable fields get real columns.

```sql
-- ───────────────────────── conversations ─────────────────────────
CREATE TABLE sessions (
    id            uuid PRIMARY KEY,
    title         text,                          -- auto-generated, editable
    channel       text NOT NULL DEFAULT 'web',   -- web | telegram | voice | api
    created_at    timestamptz NOT NULL DEFAULT now(),
    archived_at   timestamptz
);

CREATE TABLE conversation_turns (
    id            uuid PRIMARY KEY,
    session_id    uuid NOT NULL REFERENCES sessions(id),
    role          text NOT NULL CHECK (role IN ('user','assistant','system','tool')),
    content       text NOT NULL,
    modality      text NOT NULL DEFAULT 'text',  -- text | voice | image
    agent         text,                          -- which agent answered
    trace_id      text,                          -- links to logs/metrics
    token_usage   jsonb,                         -- {input, output, model, role}
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON conversation_turns (session_id, created_at);
-- keyword leg of hybrid search over chunk text lives in chunks_fts (below), not here

-- ───────────────────────── memory ─────────────────────────
CREATE TYPE memory_kind   AS ENUM ('preference','fact','goal','project','episode','lesson');
CREATE TYPE memory_source AS ENUM ('explicit','extracted','consolidated','reflection');
CREATE TYPE memory_status AS ENUM ('active','superseded','archived','deleted_pending');

CREATE TABLE memory_items (
    id               uuid PRIMARY KEY,
    kind             memory_kind NOT NULL,
    content          text NOT NULL,
    source           memory_source NOT NULL,
    confidence       real NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    status           memory_status NOT NULL DEFAULT 'active',
    superseded_by    uuid REFERENCES memory_items(id),
    origin_ref       jsonb,            -- {turn_id}
    tags             text[] NOT NULL DEFAULT '{}',
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    last_accessed_at timestamptz,
    access_count     int NOT NULL DEFAULT 0,
    delete_after     timestamptz,      -- set when deleted_pending
    embedding        vector(3072)      -- pgvector; memory-item embedding for similarity recall
);
CREATE INDEX ON memory_items (status, kind);
CREATE INDEX ON memory_items USING gin (tags);
-- (Mem0 may manage its own tables; this is the contract/shape the Memory agent exposes.)

-- ───────────────────────── knowledge / ingestion ─────────────────────────
CREATE TYPE ingest_status AS ENUM ('ok','failed','pending','tombstoned');

CREATE TABLE ingest_ledger (
    vpath          text PRIMARY KEY,             -- vfs://mount/path
    content_hash   text NOT NULL,
    embedder_model text NOT NULL,
    chunk_count    int  NOT NULL DEFAULT 0,
    status         ingest_status NOT NULL,
    error          text,
    embedded_at    timestamptz,
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE embedding_cache (
    content_hash   text NOT NULL,
    embedder_model text NOT NULL,
    vector         bytea NOT NULL,               -- packed float32
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (content_hash, embedder_model)
);

-- chunks: pgvector + keyword leg of hybrid retrieval (KNOWLEDGE.md §3–4)
CREATE TABLE chunks (
    chunk_id   text PRIMARY KEY,                 -- deterministic: hash(vpath, structural_path, position)
    vpath      text NOT NULL,
    body       text NOT NULL,
    payload    jsonb NOT NULL,                   -- mount, structural_path, start/end_line, page, doc_type, tags
    embedding  vector(3072) NOT NULL,            -- pgvector — the `knowledge` collection
    tsv        tsvector GENERATED ALWAYS AS (to_tsvector('english', body)) STORED
);
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);  -- vector leg
CREATE INDEX ON chunks USING gin (tsv);                            -- keyword leg
CREATE INDEX ON chunks (vpath);                                    -- tombstone deletes

-- ───────────────────────── audit ─────────────────────────
CREATE TABLE tool_audit (
    id           uuid PRIMARY KEY,
    tool         text NOT NULL,
    agent        text NOT NULL,
    tier         text NOT NULL,                  -- ALLOW/ASK at execution time
    args_hash    text NOT NULL,                  -- args themselves in encrypted blob if sensitive
    args_preview text,                           -- redacted human-readable preview
    decision     text NOT NULL,                  -- auto_allowed | user_approved | user_denied
    outcome      text NOT NULL,                  -- ok | error | timeout
    duration_ms  int,
    trace_id     text,
    session_id   uuid,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON tool_audit (created_at);
CREATE INDEX ON tool_audit (tool, created_at);

-- lg_checkpoints: created/owned by langgraph-checkpoint-postgres (from M3); not hand-defined here.

-- ───────────── deferred (created with their agents, not in M0–M4) ─────────────
-- task_runs / task_steps   → Task Planning + Reflection agents
-- scheduled_jobs / job_runs → Automation agent (cron digests, rescans, consolidation)
-- Shapes preserved in Docs_COMPLEX/data/POSTGRES_SCHEMA.md.
```

## Notes

1. **Migrations:** Alembic from day one; this file tracks intent, migrations track truth. Divergence = doc bug.
2. **`embedding_cache.vector` as bytea, not pgvector** — it's a hash-keyed cache, never searched. The searchable vectors live in `chunks.embedding` (and `memory_items.embedding`) as real pgvector columns.
3. **Sensitive args** in `tool_audit` are previewed redacted; full args only in an encrypted blob if forensics demand it later — default is hash+preview only ([SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md)).
4. **Retention:** nothing auto-deletes except `deleted_pending` memory items past `delete_after` and LRU pruning of `embedding_cache`. Conversation history is the user's life record — kept until the user says otherwise.
5. **pgvector dimension** (`vector(3072)`) matches `gemini-embedding-001`; a model change is a re-embed migration that re-creates the column at the new dimension ([../ai/LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §5).
