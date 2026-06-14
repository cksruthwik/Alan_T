# Alan_T — Infrastructure & Deployment

Version: 0.2
Status: Active — lean scope ([BUILD_ORDER.md](../BUILD_ORDER.md)). Consolidates infrastructure + deployment.

Single host, Docker Compose. The lean build runs **api + postgres (pgvector)** — that's it for M0–M2; a worker container joins when ingestion needs it, Telegram when M2 lands. Three free cloud providers (Groq, Google AI Studio, NVIDIA NIM). Personal scale — boring on purpose (ADR-008).

## 1. Topology (lean)

```
┌────────────────────────── host (Linux, FDE) ──────────────────────────┐
│  docker compose:                                                      │
│  ┌─────────┐  ┌──────────────────────┐                               │
│  │   api   │  │ postgres + pgvector   │                               │
│  │ FastAPI │  │        :5432          │                               │
│  │  :8000  │  └──────────────────────┘                               │
│  └────┬────┘   (internal network; api on 127.0.0.1 + tailscale0 only) │
│       └── outbound HTTPS ──▶ Groq / Google AI / NVIDIA NIM            │
│                                                                       │
│  (M2) telegram-gateway ──▶ Telegram long-poll                        │
│  tailscaled (host) ──▶ remote access from the user's devices         │
└───────────────────────────────────────────────────────────────────────┘
```

Add containers **reactively**: a `worker` (background ingestion/jobs) when a real queue need appears; `telegram-gateway` at M2. Redis and a dedicated vector DB (Qdrant) are explicitly deferred (ADR-021) — pgvector lives inside Postgres and ingestion can run as an in-process background task until concurrency demands a worker.

## 2. Services

| Service | Image | Milestone | Notes |
|---|---|---|---|
| `api` | project image (uv-based Python 3.12) | M0 | FastAPI (+ LangGraph from M3); binds `127.0.0.1:8000` and the tailscale interface only |
| `postgres` | `postgres:17` + `pgvector` | M0 | volume `pg_data`; healthcheck `pg_isready`; holds operational data, vectors, LangGraph checkpoints |
| `worker` | same image, `worker` entrypoint | M2 (when needed) | background ingestion + jobs |
| `telegram-gateway` | same project image | M2 | long-polling via aiogram (no inbound port needed) |

One image for api/worker/gateway → one build, no drift.

## 3. Configuration Surface

| File / env | Contents |
|---|---|
| `.env` | `GROQ_API_KEY`, `GOOGLE_API_KEY`, `NVIDIA_API_KEY`, `ALAN_API_TOKEN`, `FERNET_KEY`, `TELEGRAM_BOT_TOKEN`, DB URL |
| `config/models.yaml` | model purpose → primary + fallback chain + quota budgets ([../ai/LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §3) |
| `config/vfs.yaml` | mounts + exclusions ([../knowledge/AI_VFS.md](../knowledge/AI_VFS.md)) |
| `config/permissions.yaml` | tool tiers ([../security/TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md)) |
| `config/app.yaml` | budgets (context tokens, retries), feature flags per milestone |

Config is mounted read-only into containers; changes = restart (no hot-reload at this scale).

## 4. Resource Reality

No GPU required anywhere (ADR-001 — inference is remote). Honest minimums: 4 cores / 8 GB RAM / SSD. Postgres idles small; the Python services are I/O-bound API orchestrators. VFS mounts are bind-mounted **read-only** into the worker container — it cannot modify source files even if compromised.

## 5. Network Rules

1. No container publishes to `0.0.0.0`. API: loopback + tailscale interface only.
2. Inter-service traffic on the compose-internal network; Postgres reachable from `api`/`worker` only.
3. Outbound HTTPS to Groq/Google/NVIDIA/Telegram; egress domains logged via adapter metrics (egress-proxy hardening backlogged).
4. Tailscale handles remote: device auth, WireGuard encryption, no port forwarding, no reverse proxy, no TLS to manage ([../integrations/TAILSCALE.md](../integrations/TAILSCALE.md)).

## 6. Deployment

### First deploy

```bash
docker compose up -d                               # builds image, starts api + postgres
docker compose exec api alembic upgrade head       # migrations
docker compose exec api alan bootstrap             # creates pgvector collections (embedder-stamped),
                                                   # sanity-checks config
curl -H "Authorization: Bearer $ALAN_API_TOKEN" localhost:8000/api/v1/health/deps
```

`health/deps` must show all dependencies green (postgres, groq, google, nvidia) before ingesting anything. Review `config/vfs.yaml` mounts **before first ingest** — first ingest is the first cloud egress of your files.

### Update

```bash
git pull && docker compose build && docker compose up -d
docker compose exec api alembic upgrade head
```

- Migrations are forward-only; rollback = restore backup (accepted at this scale).
- `config/models.yaml` changes need only a restart, not a rebuild.
- After any model-config change: run the provider-swap drill (MVP acceptance #4) + the relevant eval set.

### Operational runbook

| Situation | Action |
|---|---|
| Provider outage (Groq down) | nothing — the LiteLLM fallback chain absorbs it; check metrics for `fallback_depth` spike |
| All providers rate-limited | system degrades honestly; interactive traffic queues; check daily-budget config vs reality |
| Vector data suspect | rebuild: `alan reindex --collection knowledge` (ledger-driven re-embed from cache where possible) |
| Embedding model change | `alan reembed --plan` (shows quota cost) → `alan reembed --execute` (resumable migration, [../ai/LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §5) |
| Restore from backup | restore `pg_data`, `docker compose up -d` |

### Backups

| What | Method | Cadence | Retention |
|---|---|---|---|
| Postgres (the irreplaceable store: memory, history, audit, ledger, **and vectors**) | `pg_dump` to encrypted tarball → off-host (restic) | nightly | 30 days |
| Config + `.env` | encrypted copy in the same restic repo | on change | versions |
| Source corpus | NOT Alan_T's job — the user's own backup regime; Alan_T only ever reads it |

**Restore drill is part of M2 done-criteria:** one full restore onto a clean directory must succeed before the MVP is called done. An untested backup is a hope, not a backup. (With pgvector, the `knowledge` vectors live inside Postgres, so one DB restore brings them back too — or rebuild from sources via the ledger.)

### Monitoring hooks

- `/health` for uptime checks.
- Log shipping: JSON logs to stdout → `docker logs` ([../observability/OBSERVABILITY.md](../observability/OBSERVABILITY.md)).
- Metrics: Prometheus endpoint `/metrics` ([../observability/OBSERVABILITY.md](../observability/OBSERVABILITY.md)); dashboards optional until autonomy makes them worth it.

## 7. Environments

| Env | What | Differences |
|---|---|---|
| `dev` | compose on the dev machine | Postgres everywhere; debug logging; fake-provider mode for offline work |
| `prod` | compose on the always-on host | restart policies `unless-stopped`; backups on; INFO logging |

**Fake-provider mode:** adapters swapped for deterministic fakes via config — the full system runs offline for tests and airplane development. This is the abstraction layer paying rent ([../testing/TEST_STRATEGY.md](../testing/TEST_STRATEGY.md)).
