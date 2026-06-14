# Automation Agent

Phase: 7 · Model role: `SUMMARIZER` (digests), `REASONER` (goal tracking analysis)
Workflow: [WORKFLOWS.md](../architecture/WORKFLOWS.md) W7 · Scheduling: `Scheduler` port (APScheduler adapter)

## Responsibility

Time-triggered work — the proactive half of Alan_T: daily digests, weekly reviews, reminders, goal tracking, and user-defined recurring jobs. Everything here runs unattended, so honesty and budget discipline matter more than brilliance.

## Job Types

| Job | Default schedule | What it does |
|---|---|---|
| `daily_digest` | 08:00 | calendar today + open task runs + flagged memory items + yesterday's episode summary → one scannable message |
| `weekly_review` | Sun 18:00 | week's episodes, decisions, open loops, stale goals, external-action audit count ([MEMORY_CONSOLIDATION.md](../memory/MEMORY_CONSOLIDATION.md) §4) |
| `reminder` | user-set | `set_reminder` tool output → notification at time T |
| `goal_check` | weekly | active `goal` memories vs recent episodes → progress/stall assessment |
| `rescan` | weekly | ingestion full re-scan (ledger makes it cheap) |
| `consolidation` | 03:00 | delegates to the memory consolidation job |
| custom | user-defined | natural-language defined recurring tasks, stored as plan templates, executed via the Phase 7 task graph |

## Rules

1. **Budgeted:** all scheduled work runs under background-job quota throttles ([LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §7.4); a digest that can't run within budget is skipped with a logged reason — it never queues into the user's morning interactive quota.
2. **Permission tiers apply unattended too:** a custom job whose plan contains ASK-tier steps parks at the approval and notifies — unattended ≠ auto-approved. Standing approvals are explicit per-job grants in `permissions.yaml`, reviewed in the weekly digest.
3. **Silence is a valid output:** empty digest day → "nothing needs your attention", or no message at all (user preference) — manufactured insight is noise.
4. **Delivery** via `MessagingGateway` (Telegram, Phase 8) or stored as the next-session greeting before that. `notify` (ALLOW) for in-app.
5. **Every run recorded** in `job_runs` with token cost — automations are the most likely silent quota drain; metrics watch them specifically ([METRICS.md](../observability/METRICS.md)).

## Custom Automation Definition Flow

"Every Friday, summarize what I worked on and what's unfinished" → Planner produces a plan template → user approves once (including its standing permissions) → stored in `scheduled_jobs` → runs via the task graph with Reflection evaluating each run. Edits and disabling via `/automations` API.

## Failure Posture

Failed runs: one retry (transient class only), then logged + surfaced in the next digest — a broken automation must announce itself, not silently stop. Three consecutive failures → job auto-disabled + notification (zombie jobs burning quota are worse than missing jobs).
