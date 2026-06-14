# Alan_T — PostgreSQL Schema

Version: 0.1
Status: Active — normative DDL sketch; migrations (Alembic) are the executable truth once code exists.

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
    origin_ref       jsonb,            -- {turn_id | job_id | task_id}
    tags             text[] NOT NULL DEFAULT '{}',
    embedding_ref    text,             -- qdrant point id in `memory` collection
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    last_accessed_at timestamptz,
    access_count     int NOT NULL DEFAULT 0,
    delete_after     timestamptz       -- set when deleted_pending
);
CREATE INDEX ON memory_items (status, kind);
CREATE INDEX ON memory_items USING gin (tags);

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

-- keyword search leg (hybrid retrieval, RAG_PIPELINE §2)
CREATE TABLE chunks_fts (
    chunk_id   text PRIMARY KEY,                 -- = qdrant point id
    vpath      text NOT NULL,
    body       text NOT NULL,
    tsv        tsvector GENERATED ALWAYS AS (to_tsvector('english', body)) STORED
);
CREATE INDEX ON chunks_fts USING gin (tsv);
CREATE INDEX ON chunks_fts (vpath);              -- tombstone deletes

-- ───────────────────────── agentic tasks ─────────────────────────
CREATE TYPE run_status  AS ENUM ('planning','awaiting_approval','running','done','aborted','failed');
CREATE TYPE step_status AS ENUM ('pending','running','success','failed','skipped');

CREATE TABLE task_runs (
    id           uuid PRIMARY KEY,
    goal         text NOT NULL,
    plan         jsonb NOT NULL,                 -- validated plan DAG
    status       run_status NOT NULL,
    replan_count int NOT NULL DEFAULT 0,
    report       text,                           -- final user-facing report
    created_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz
);

CREATE TABLE task_steps (
    id          uuid PRIMARY KEY,
    run_id      uuid NOT NULL REFERENCES task_runs(id),
    step_key    text NOT NULL,                   -- plan task id (t1, t2…)
    agent       text NOT NULL,
    status      step_status NOT NULL,
    attempts    int NOT NULL DEFAULT 0,
    result      jsonb,                           -- AgentResult summary
    verdict     jsonb,                           -- reflection verdict
    UNIQUE (run_id, step_key)
);

-- ───────────────────────── audit & automation ─────────────────────────
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

CREATE TABLE scheduled_jobs (
    id         uuid PRIMARY KEY,
    name       text UNIQUE NOT NULL,
    cron       text NOT NULL,
    job_type   text NOT NULL,                    -- digest | consolidation | rescan | custom
    config     jsonb NOT NULL DEFAULT '{}',
    enabled    boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE job_runs (
    id          uuid PRIMARY KEY,
    job_id      uuid NOT NULL REFERENCES scheduled_jobs(id),
    status      text NOT NULL,                   -- ok | failed | partial
    summary     text,
    token_cost  jsonb,
    started_at  timestamptz NOT NULL,
    finished_at timestamptz
);

-- lg_checkpoints: created/owned by langgraph-checkpoint-postgres; not hand-defined here.
```

## Notes

1. **Migrations:** Alembic from day one; this file tracks intent, migrations track truth. Divergence = doc bug.
2. **`embedding_cache.vector` as bytea, not pgvector** — it's a cache keyed by hash, never searched. If the pgvector adapter ([BACKLOG.md](../product/BACKLOG.md)) lands, chunks move to a real `vector` column in their own table; this cache stays as-is.
3. **Sensitive args** in `tool_audit` are previewed redacted; full args only in an encrypted blob if forensics demand it later — default is hash+preview only ([SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md) §4).
4. **Retention:** nothing auto-deletes except `deleted_pending` memory items past `delete_after` and LRU pruning of `embedding_cache`. Conversation history is the user's life record — kept until the user says otherwise.
