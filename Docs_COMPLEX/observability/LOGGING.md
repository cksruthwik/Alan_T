# Alan_T — Logging

Version: 0.1
Status: Active

Structured, correlated, redacted. Logs answer "what did the system do and why" — for a system that acts autonomously on personal data, that's a trust feature, not an ops nicety.

## 1. Format & Transport

- JSON lines to stdout (structlog); Docker captures; optional Loki later — no logging infrastructure beyond that at personal scale.
- Levels: DEBUG (dev only), INFO (state changes, decisions), WARNING (degradations, fallbacks), ERROR (failed operations). No log-and-continue on ERROR without a degraded flag surfacing somewhere user-visible.

## 2. Correlation

Every request/turn/job gets a `trace_id` at the edge (API middleware, queue consumer, scheduler) propagated through **contextvars** so every log line, audit row ([POSTGRES_SCHEMA.md](../data/POSTGRES_SCHEMA.md) `tool_audit.trace_id`), metric exemplar, and `conversation_turns.trace_id` correlates. "Why did Alan_T say/do that?" must be answerable from one grep.

## 3. Canonical Events (consistent keys, greppable)

| Event | Key fields |
|---|---|
| `turn.start / turn.end` | session_id, modality, agent_routed, duration_ms, degraded[] |
| `model.call` | role, provider, model, latency_ms, tokens_in/out, fallback_depth, outcome |
| `model.fallback` | role, from_model, to_model, reason (rate_limit/error) |
| `quota.exhausted` | provider, model, window, resumes_at |
| `tool.exec` | tool, agent, tier, decision, outcome, duration_ms (mirror of audit row) |
| `retrieval.run` | query_hash, collections, top_score, k_returned, fused |
| `memory.write / memory.merge / memory.supersede` | item_id, kind, source, confidence |
| `ingest.file` | vpath, status, chunk_count, skip_reason? |
| `task.step` | run_id, step_key, agent, verdict, attempt |
| `job.run` | job name, status, token_cost |
| `gateway.rejected` | channel, reason (e.g., telegram non-allowlisted sender — counted, ID logged) |

## 4. Redaction (security boundary, tested)

Processor chain before emission strips/masks: API keys & bearer tokens (pattern + known-prefix), `.env`-style assignments, OAuth tokens, anything matching the secret patterns from [SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md) §4.

**Content policy:** user message/document content is NOT logged at INFO+ — hashes and lengths only (`query_hash`, `args_preview` pre-redacted). DEBUG may log content in dev; the prod config physically disables DEBUG. Planted-secret tests verify the chain ([SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md) §8).

## 5. Retention

Docker local rotation: 7 days / 500 MB. The durable behavioral record is `tool_audit` + `conversation_turns` + `job_runs` in Postgres (backed up) — logs are diagnostics, not the system of record.
