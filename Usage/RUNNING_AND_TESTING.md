# Running & Testing Alan_T (M0 + M1)

A copy-pasteable guide to configure env vars, run the assistant, and verify it works —
including the M1 "it remembers you" milestone test.

> Run everything from the project root:
> `/home/root1/Desktop/Code/PersonalAssist/Alan_T/Alan_T`

---

## 1. Get your API keys

For M1 memory to work you **must** have a Groq key — it powers both the CHAT model and
Mem0's fact extraction. The other two are optional fallbacks.

| Key | Where to get it | Needed? |
|---|---|---|
| `GROQ_API_KEY` | https://console.groq.com/keys | **Required** (CHAT + memory) |
| `GOOGLE_API_KEY` | https://aistudio.google.com/apikey | Optional (fallback) |
| `NVIDIA_NIM_API_KEY` | https://build.nvidia.com | Optional (fallback) |

All three have free tiers.

---
```
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock docker/compose:latest [your-command]
Emulate Docker CLI using podman. Create /etc/containers/nodocker to quiet msg.
✔ docker.io/docker/compose:latest
Trying to pull docker.io/docker/compose:latest...
Getting image source signatures
Copying blob 9ac2a98ece5b done   | 
Copying blob b396cd7cbac4 done   | 
Copying blob 0426ec0ed60a done   | 
Copying blob aad63a933944 done   | 
Copying config c3e188a6b3 done   | 
Writing manifest to image destination
WARNING: image platform (linux/amd64) does not match the expected platform (linux/arm64)
Error: statfs /var/run/docker.sock: permission denied
## 2. Create your `.env`
```
```bash
cp .env.example .env
```

Edit `.env` to look like this (fill in your real Groq key; invent any long random token):

```bash
# --- API auth (you invent this; it's the bearer token for requests) ---
ALAN_API_TOKEN=pick-a-long-random-string-abc123

# --- LLM providers ---
GROQ_API_KEY=gsk_your_real_groq_key_here
GOOGLE_API_KEY=
NVIDIA_NIM_API_KEY=

# --- Datastore (leave as-is for Docker; compose overrides the host) ---
DATABASE_URL=postgresql+asyncpg://alan:alan@localhost:5432/alan_t

# --- Memory (Mem0) ---
ALAN_MEMORY_PATH=.data/memory
ALAN_USER_ID=default

# --- Optional ---
ALAN_MODELS_CONFIG=config/models.yaml
ALAN_LOG_LEVEL=INFO
```

> `ALAN_API_TOKEN` is **your** choice — you send it as `Authorization: Bearer <that value>`.

---

## 3. Start it (Docker — recommended)

**Option 1: Using podman-compose (recommended for Python 3.14+)**

If you're on Python 3.14 or later, `pip install docker-compose` fails due to PyYAML compatibility. Use `podman-compose` instead:

```bash
pip install podman-compose
```

Then start the services:

```bash
podman-compose up
```

**Option 2: Using docker-compose (if you have Docker installed)**

```bash
pip install docker-compose
# or via system package manager (apt, brew, etc.)
docker compose up --build
```

Either way, Docker Compose / podman-compose brings up Postgres, runs DB migrations, starts the API, and mounts the
persistent memory volume (needed for the "restart → remembers" test).

Wait for `Uvicorn running on http://0.0.0.0:8000` (or `Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)`). 
Leave this terminal running; open a **second terminal** for the tests below.

> ⚠️ The **first** chat message will be slow (10–30s) — Mem0's local embedding model
> (`bge-small`, ~90MB) downloads on first memory use. Normal, not a hang.

---

## 4. Basic tests

### Test A — health (no auth)
```bash
curl -s http://127.0.0.1:8000/health
```
Expect: `{"status":"ok"}`

### Test B — auth is enforced
```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" -d '{"message":"hi"}'
```
Expect: `401`

### Test C — a real chat turn
Replace `YOUR_TOKEN` with your `ALAN_API_TOKEN`:
```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Hello, who are you?"}'
```
Expect JSON like:
```json
{"session_id":"01K...","response":"I'm Alan_T...","model":"groq/llama-3.3-70b-versatile","status":"ok","degraded":[]}
```
- `status:"ok"` and empty `degraded` → memory is working.
- `status:"degraded"` with `"memory_write_unavailable"` → chat works but Mem0 failed
  (usually a missing/invalid Groq key — check the logs).

---

## 5. The M1 "it remembers you" test (milestone DoD)

**Step 1 — tell it a preference:**
```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"I prefer TypeScript."}'
```

**Step 2 — restart the process (memory volume persists):**
```bash
# If using podman-compose:
source ./ai-vfs/.venv/bin/activate && podman-compose restart api

# If using docker-compose:
docker compose restart api
```
Wait for `Uvicorn running` again (check logs in the original terminal).

**Step 3 — ask in a brand-new conversation** (no `session_id` → fresh session, the real test):
```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"What programming language do I prefer?"}'
```

✅ **Pass:** the `response` mentions **TypeScript**, even though it's a new session after a
restart. That is M1 working.

---

## 6. See it working under the hood

**Watch logs** (in the `docker compose up` terminal) as you send messages — provider calls
and any `memory recall/write failed` warnings appear there.

**Confirm memory persisted to disk:**
```bash
# If using podman-compose:
source ./ai-vfs/.venv/bin/activate && podman-compose exec api ls -R /app/.data/memory

# If using docker-compose:
docker compose exec api ls -R /app/.data/memory
```
You should see a `qdrant/` directory and `history.db`.

**Multi-turn within one conversation** (carry the `session_id` from a response back in):
```bash
# first turn returns a session_id; reuse it:
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Authorization: Bearer YOUR_TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"My name is Sai.","session_id":"PASTE_SESSION_ID"}'

curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Authorization: Bearer YOUR_TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"What is my name?","session_id":"PASTE_SESSION_ID"}'
```

---

## 7. Stop / reset

**Using podman-compose:**
```bash
source ./ai-vfs/.venv/bin/activate
podman-compose down          # stop, keep data
podman-compose down -v       # stop AND wipe memory + DB (fresh start)
```

**Using docker-compose:**
```bash
docker compose down          # stop, keep data
docker compose down -v       # stop AND wipe memory + DB (fresh start)
```

---

## 8. Run the automated test suite (no keys needed)

The unit/integration tests use fakes — no API keys, no Docker:
```bash
uv run pytest -q
uv run ruff check src tests
```
Expect all tests passing and `All checks passed!`.

---

## 9. Troubleshooting

### "invalid or missing token" error on `/chat`
- Verify `.env` has `ALAN_API_TOKEN=your-token-here`
- **If you just changed `.env`, restart the containers:**
  ```bash
  source ./ai-vfs/.venv/bin/activate && podman-compose down
  podman-compose up
  ```
- Ensure the curl header matches: `Authorization: Bearer <exact-token-from-.env>`

### PyYAML build error with `pip install docker-compose`
- This is a Python 3.14+ compatibility issue
- **Solution:** Use `podman-compose` instead (see section 3)

---

## Appendix: run without Docker (dev)

Requires a local Postgres reachable at `DATABASE_URL`:
```bash
uv sync
uv run alembic upgrade head
uv run uvicorn alan_t.app.main:create_app --factory --reload --port 8000
```
Docker is simpler since it provisions Postgres + migrations for you.

---

## Quick reference

| What | Endpoint / command |
|---|---|
| Health | `GET /health` |
| Chat | `POST /chat` — body `{"message": "...", "session_id": "optional"}` |
| Auth | header `Authorization: Bearer $ALAN_API_TOKEN` |
| Memory data | `/app/.data/memory` (Docker volume `mem_data`) |
| Memory identity | `ALAN_USER_ID` (long-term memory is keyed by this) |
