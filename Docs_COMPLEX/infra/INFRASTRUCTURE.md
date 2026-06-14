# Alan_T — Infrastructure

Version: 0.1
Status: Active

Single host, Docker Compose, five containers, two cloud dependencies (Groq, Google AI Studio). Personal scale — boring on purpose (ADR-008).

## 1. Topology

```
┌────────────────────────── host (Linux, FDE) ──────────────────────────┐
│                                                                       │
│  docker compose:                                                      │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌───────┐  ┌────────┐      │
│  │   api   │  │  worker  │  │ postgres │  │ redis │  │ qdrant │      │
│  │ FastAPI │  │ ingest/  │  │   :5432  │  │ :6379 │  │  :6333 │      │
│  │  :8000  │  │ jobs     │  └──────────┘  └───────┘  └────────┘      │
│  └────┬────┘  └────┬─────┘   (internal network only — no host ports   │
│       │            │          except api on 127.0.0.1 + tailscale0)   │
│       └────────────┴── outbound HTTPS ──▶ Groq API / Google AI API    │
│                                                                       │
│  tailscaled (host) ──▶ remote access from user's devices              │
│  (phase 8) telegram-gateway container ──▶ Telegram long-poll          │
└───────────────────────────────────────────────────────────────────────┘
```

## 2. Services

| Service | Image | Notes |
|---|---|---|
| `api` | project image (uv-based Python 3.12) | FastAPI + LangGraph runtime; binds `127.0.0.1:8000` and the tailscale interface only |
| `worker` | same image, `worker` entrypoint | arq worker: ingestion queues, cron jobs, consolidation (ADR-012) |
| `postgres` | `postgres:17` | volume `pg_data`; healthcheck `pg_isready` |
| `redis` | `redis:8` | `appendonly yes` (queue durability); volume `redis_data` |
| `qdrant` | `qdrant/qdrant` | volume `qdrant_data` |
| `telegram-gateway` (P8) | same project image | long-polling via aiogram (no inbound port needed) |
| `searxng` (optional) | `searxng/searxng` | self-hosted keyless metasearch for the Research agent (ADR-015); internal network only |
| `langfuse` (optional profile) | Langfuse compose bundle | LLM tracing/costs (ADR-013); heavy footprint (ClickHouse + MinIO + own Postgres) — enable only when debugging quality |

One image for api/worker/gateway → one build, no drift.

## 3. Configuration Surface

| File / env | Contents |
|---|---|
| `.env` | `GROQ_API_KEY`, `GOOGLE_API_KEY`, `ALAN_API_TOKEN`, `FERNET_KEY`, `TELEGRAM_BOT_TOKEN`, DB URLs |
| `config/models.<profile>.yaml` + `config/capabilities.yaml` | per-profile role registry + fallbacks + quota budgets; capability overrides for the bootstrap gate ([LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §3, §5) |
| `config/vfs.yaml` | mounts + exclusions ([AI_VFS.md](../knowledge/AI_VFS.md) §3) |
| `config/permissions.yaml` | tool tiers ([TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md) §2) |
| `config/app.yaml` | budgets (context tokens, retries), feature flags per phase |

Config is mounted read-only into containers; changes = restart (no hot-reload machinery at this scale).

## 4. Resource Reality

No GPU required anywhere (ADR-001 — inference is remote). Honest minimums: 4 cores / 8 GB RAM / SSD. Postgres+Redis+Qdrant idle small; the Python services are I/O-bound API orchestrators. The VFS mounts are bind-mounted **read-only** into the worker container (`/vfs/...`) — the container cannot modify source files even if compromised.

## 5. Network Rules

1. No container publishes to `0.0.0.0`. API: loopback + tailscale interface.
2. Inter-service traffic on the compose-internal network; data stores reachable from `api`/`worker` only.
3. Outbound: HTTPS to Groq/Google/Telegram only in spirit — not firewalled in MVP, but egress domains are logged via adapter metrics (a later egress-proxy hardening is backlogged).
4. Tailscale handles remote: device auth, WireGuard encryption, no port forwarding, no reverse proxy, no TLS termination to manage ([TAILSCALE.md](../integrations/TAILSCALE.md)).

## 6. Environments

| Env | What | Differences |
|---|---|---|
| `dev` | compose on the dev machine | SQLite option off (Postgres everywhere — fewer surprises); debug logging; fake-provider mode for offline work |
| `prod` | compose on the always-on host (same machine is fine) | restart policies `unless-stopped`; backups on ([DEPLOYMENT.md](DEPLOYMENT.md) §5); INFO logging |

“Fake-provider mode”: adapters swapped for deterministic fakes via config — full system runs offline for tests and airplane development. This is the abstraction layer paying rent ([TEST_STRATEGY.md](../testing/TEST_STRATEGY.md) §3).
