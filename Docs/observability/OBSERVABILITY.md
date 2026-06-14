# Alan_T — Observability (Logging + Metrics)

Version: 0.2
Status: Active — lean scope ([BUILD_ORDER.md](../BUILD_ORDER.md)). Consolidates logging + metrics.

Structured, correlated, redacted logs + Prometheus metrics. For a system that acts autonomously on personal data, "what did it do and why" is a trust feature, not an ops nicety.

---

## 1. Logging

### Format & transport

- JSON lines to stdout (structlog); Docker captures; optional Loki later — no logging infrastructure beyond that at personal scale.
- Levels: DEBUG (dev only), INFO (state changes, decisions), WARNING (degradations, fallbacks), ERROR (failed operations). No log-and-continue on ERROR without a degraded flag surfacing somewhere user-visible.

### Correlation

Every request/turn/job gets a `trace_id` at the edge (API middleware, queue consumer) propagated through **contextvars** so every log line, audit row ([../data/POSTGRES_SCHEMA.md](../data/POSTGRES_SCHEMA.md) `tool_audit.trace_id`), metric exemplar, and `conversation_turns.trace_id` correlates. "Why did Alan_T say/do that?" must be answerable from one grep.

### Canonical events (consistent keys, greppable)

| Event | Key fields |
|---|---|
| `turn.start / turn.end` | session_id, modality, agent_routed, duration_ms, degraded[] |
| `model.call` | purpose, provider, model, latency_ms, tokens_in/out, fallback_depth, outcome |
| `model.fallback` | purpose, from_model, to_model, reason (rate_limit/error) |
| `quota.exhausted` | provider, model, window, resumes_at |
| `tool.exec` | tool, agent, tier, decision, outcome, duration_ms (mirror of audit row) |
| `retrieval.run` | query_hash, collections, top_score, k_returned, fused |
| `memory.write / memory.merge` | item_id, kind, source, confidence |
| `ingest.file` | vpath, status, chunk_count, skip_reason? |
| `gateway.rejected` | channel, reason (e.g. telegram non-allowlisted sender — counted, ID logged) |

### Redaction (security boundary, tested)

Processor chain before emission strips/masks: API keys & bearer tokens (pattern + known-prefix), `.env`-style assignments, OAuth tokens, anything matching the secret patterns from [../security/SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md).

**Content policy:** user message/document content is NOT logged at INFO+ — hashes and lengths only (`query_hash`, `args_preview` pre-redacted). DEBUG may log content in dev; the prod config physically disables DEBUG. Planted-secret tests verify the chain.

### Retention

Docker local rotation: 7 days / 500 MB. The durable behavioral record is `tool_audit` + `conversation_turns` + `job_runs` in Postgres (backed up) — logs are diagnostics, not the system of record.

---

## 2. Metrics

Prometheus endpoint `/metrics` on `api` (and `worker` when present). Dashboards optional; the metrics themselves are not — they answer the three questions that decide this project's choices: *is it fast enough, is it within quota, is it actually good?*

### Latency (the NFR watch — PRD §6)

| Metric | Type | Labels | Target |
|---|---|---|---|
| `turn_duration_seconds` | histogram | agent, modality | p95 < 5 s text |
| `first_token_seconds` | histogram | agent | p95 < 1.5 s |
| `retrieval_duration_seconds` | histogram | collection | p95 < 3 s |
| `model_call_duration_seconds` | histogram | purpose, provider, model | per-model baselines |
| `voice_roundtrip_seconds` (M6) | histogram | path | p95 < 3 s (short answers) |

### Quota & cost (the free-tier survival watch — [../ai/LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §6)

| Metric | Type | Labels |
|---|---|---|
| `model_tokens_total` | counter | purpose, provider, model, direction (in/out) |
| `model_calls_total` | counter | purpose, provider, model, outcome (ok/rate_limited/error) |
| `model_fallback_total` | counter | purpose, from_model, reason |
| `quota_window_remaining_ratio` | gauge | provider, model, window |
| `quota_exhausted_total` | counter | provider, model |

This series is the dataset that eventually justifies (or kills) a paid tier / local models — ADR-001's review evidence.

### Quality (the "is it good" watch)

| Metric | Type | Source |
|---|---|---|
| `retrieval_top_score` | histogram | per query — drifting down = index rot or chunking regression |
| `rag_empty_retrieval_total` | counter | honest-empty answers (a rate spike = corpus gap or query problem) |
| `citation_check_failures_total` | counter | the RAG self-check ([../knowledge/KNOWLEDGE.md](../knowledge/KNOWLEDGE.md) §4) |
| `router_misroute_total` | counter | repair-fallbacks in Supervisor ([../agents/SUPERVISOR_AGENT.md](../agents/SUPERVISOR_AGENT.md)) — from M3 |
| `memory_recall_used_ratio` | gauge (sampled) | recalled-and-used vs recalled — store-rot canary |
| eval scores | recorded per run in `job_runs`, not Prometheus | eval job ([../testing/TEST_STRATEGY.md](../testing/TEST_STRATEGY.md)) |

### Health & throughput

`dependency_up` gauge (postgres / groq / google / nvidia — feeds `/health/deps`), `ingest_queue_depth`, `ingest_files_total{status}`, `dlq_depth`, `approval_pending_age_seconds` (an old pending approval = a stuck task), `telegram_rejected_total` (allowlist hits — should be ~0; a spike means someone found the bot).

### Alerting (lightweight)

At lean scale the user IS the on-call. A simple periodic digest (or a manual `/metrics` glance) surfaces: any `quota_exhausted` events, `dlq_depth > 0`, dependency flaps, eval-threshold misses, `citation_check_failures` spike. A dedicated Automation agent digest is a deferred upgrade.
