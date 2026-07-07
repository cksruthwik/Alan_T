# Alan_T — Metrics

Version: 0.1
Status: Active

Prometheus endpoints on `api` and `worker` (`/metrics`). Dashboards optional until Phase 7; the metrics themselves are not — they answer the three questions that decide this project's choices: *is it fast enough, is it within quota, is it actually good?*

## 1. Latency (the NFR watch — PRD §8)

| Metric | Type | Labels | Target |
|---|---|---|---|
| `turn_duration_seconds` | histogram | agent, modality | p95 < 5 s text |
| `first_token_seconds` | histogram | agent | p95 < 1.5 s |
| `voice_roundtrip_seconds` | histogram | path (turn/live) | p95 < 3 s (short answers) |
| `retrieval_duration_seconds` | histogram | collection | p95 < 3 s |
| `model_call_duration_seconds` | histogram | role, provider, model | per-model baselines |

## 2. Quota & Cost (the free-tier survival watch — [LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §7)

| Metric | Type | Labels |
|---|---|---|
| `model_tokens_total` | counter | role, provider, model, direction (in/out) |
| `model_calls_total` | counter | role, provider, model, outcome (ok/rate_limited/error) |
| `model_fallback_total` | counter | role, from_model, reason |
| `quota_window_remaining_ratio` | gauge | provider, model, window |
| `quota_exhausted_total` | counter | provider, model |
| `job_token_cost_total` | counter | job — automations as silent quota drains, watched specifically ([AUTOMATION_AGENT.md](../agents/AUTOMATION_AGENT.md) §rules-5) |

This series is the dataset that eventually justifies (or kills) paid tiers / local models — ADR-001's review evidence. When the Langfuse profile is enabled (ADR-013), per-call traces and costs live there with full detail; these Prometheus series remain the always-on baseline and the alerting source.

## 3. Quality (the "is it good" watch)

| Metric | Type | Source |
|---|---|---|
| `retrieval_top_score` | histogram | per query — drifting down = index rot or chunking regression |
| `rag_empty_retrieval_total` | counter | honest-empty answers (a rate spike = corpus gap or query problem) |
| `citation_check_failures_total` | counter | the RAG self-check ([RAG_PIPELINE.md](../knowledge/RAG_PIPELINE.md) §2) |
| `router_misroute_total` | counter | repair-fallbacks in supervisor ([SUPERVISOR_AGENT.md](../agents/SUPERVISOR_AGENT.md)) |
| `memory_recall_used_ratio` | gauge (sampled) | recalled-and-used vs recalled — store-rot canary ([MEMORY_CONSOLIDATION.md](../memory/MEMORY_CONSOLIDATION.md) §5) |
| `task_step_verdicts_total` | counter | verdict, agent — Phase 7 success-rate truth (PRD: tool success > 90%) |
| eval scores | recorded per run in `job_runs`, not Prometheus | weekly eval job ([TEST_STRATEGY.md](../testing/TEST_STRATEGY.md) §5) |

## 4. Health & Throughput

`dependency_up` gauge (postgres/redis/qdrant/groq/google — feeds `/health/deps`), `ingest_queue_depth`, `ingest_files_total{status}`, `dlq_depth`, `approval_pending_age_seconds` (an old pending approval = a stuck task), `telegram_rejected_total` (allowlist hits — should be ~0; a spike means someone found the bot).

## 5. Alerting (lightweight, via daily digest not PagerDuty)

The Automation agent's daily digest includes: any `quota_exhausted` events, `dlq_depth > 0`, dependency flaps, eval-threshold misses, `citation_check_failures` spike. Personal scale means the user IS the on-call — the digest is the pager, and it already exists ([AUTOMATION_AGENT.md](../agents/AUTOMATION_AGENT.md)).
