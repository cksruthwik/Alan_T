# Alan_T — Deployment

Version: 0.1
Status: Active

How Alan_T gets onto the host, updates, backs up, and recovers. Companion to [INFRASTRUCTURE.md](INFRASTRUCTURE.md).

## 1. Prerequisites (one-time host setup)

1. Linux host with full-disk encryption ([SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md) §8).
2. Docker + Compose plugin.
3. Tailscale: `tailscale up`, device authorized in the tailnet.
4. API keys created: Groq console, Google AI Studio; Telegram bot via BotFather (Phase 8).
5. Clone repo; `cp .env.example .env`; fill secrets; review `config/vfs.yaml` mounts and exclusions **before first ingest** (first ingest = first cloud egress of your files).

## 2. First Deploy

```bash
docker compose up -d                  # builds image, starts stack
docker compose exec api alembic upgrade head   # migrations
docker compose exec api alan bootstrap         # creates qdrant collections (embedder-stamped),
                                               # registers default scheduled jobs, sanity-checks config,
                                               # RUNS THE CAPABILITY GATE for the active model profile
curl -H "Authorization: Bearer $ALAN_API_TOKEN" localhost:8000/api/v1/health/deps
```

**Capability gate ([LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §5):** `alan bootstrap` resolves every role's configured model (in the `ALAN_MODEL_PROFILE` profile, default `free`) and hard-fails if a model can't satisfy its role's required capabilities — printing `role / model / missing capability` and exiting non-zero. A bad model swap is caught here, before any traffic. If it fails on an unknown capability, add the model to `config/capabilities.yaml` and re-run.

`health/deps` must show all dependencies green before ingesting anything. The set is profile-dependent: `free` → postgres, redis, qdrant, groq, google; `local` → postgres, redis, qdrant, ollama; `paid` → postgres, redis, qdrant, openai, anthropic.

## 3. Update Procedure

```bash
git pull
docker compose build
docker compose up -d                  # rolling enough at personal scale
docker compose exec api alembic upgrade head
```

- Migrations are forward-only; rollback = restore backup (accepted at this scale).
- `config/models.<profile>.yaml` changes don't need a rebuild — restart only; the capability gate re-runs on restart.
- Switching the whole system to another model vendor is `ALAN_MODEL_PROFILE=<free|paid|local>` + restart — the gate verifies the new profile before traffic.
- After any model-registry change: run the provider-swap drill (MVP acceptance #4) + role eval set ([LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §9).

## 4. Operational Runbook

| Situation | Action |
|---|---|
| Provider outage (Groq down) | nothing — fallback chains absorb it; check `/system/quota` + metrics for fallback_depth spike |
| Both providers rate-limited | system degrades honestly; interactive traffic queues; check daily-budget config vs reality |
| Qdrant data suspect | rebuild: `alan reindex --collection knowledge` (ledger-driven re-embed from cache where possible — cache makes this cheap) |
| Embedding model change | `alan reembed --plan` (shows quota cost) → `alan reembed --execute` (resumable migration, [LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §6) |
| Redis lost | queues/session cache lost, no user data lost ([DATA_MODEL.md](../data/DATA_MODEL.md) §3); pending extractions re-derived by weekly rescan |
| Restore from backup | restore `pg_data` + volumes, `docker compose up -d`; Qdrant optionally rebuilt instead of restored |

## 5. Backups

| What | Method | Cadence | Retention |
|---|---|---|---|
| Postgres (the irreplaceable store: memory, history, audit, ledger) | `pg_dump` to encrypted tarball → off-host (restic to user's choice) | nightly | 30 days |
| Qdrant snapshots | native snapshot → same off-host target | nightly | 7 days (rebuildable; convenience only) |
| Config + `.env` | encrypted copy in the same restic repo | on change | versions |
| Source corpus | NOT Alan_T's job — user's own backup regime; Alan_T only ever reads it |

**Restore drill is part of Phase 1 done-criteria:** one full restore onto a clean directory must succeed before MVP is called done. An untested backup is a hope, not a backup.

## 6. Monitoring Hooks

- `/health` for uptime checks (e.g., a cron ping or the Automation agent's own daily digest noting uptime).
- Log shipping: JSON logs to stdout → `docker logs` / optional Loki later ([LOGGING.md](../observability/LOGGING.md)).
- Metrics: Prometheus endpoint `/metrics` on api and worker ([METRICS.md](../observability/METRICS.md)); dashboards optional until Phase 7 makes autonomy worth watching closely.
