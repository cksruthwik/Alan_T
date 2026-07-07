# Alan_T — Setup Guide

Zero to a running assistant (web UI + Telegram + voice). Follow in order.
Core setup is steps 1–8; step 9 lights up the optional agents.

Throughout, `$ALAN_API_TOKEN` means the token you create in step 4 — never
paste the real value into files that get committed.

---

## 1. Install Docker Desktop

Docker runs Postgres (with pgvector) and the API — nothing else to install.

1. Download from https://www.docker.com/products/docker-desktop/ (on a Mac,
   check `uname -m`: `arm64` = Apple Silicon build).
2. Install, open, wait for the whale icon to go steady.
3. Verify: `docker --version` and `docker compose version` both print versions.

## 2. Get the three free LLM API keys

Three independent free tiers form the fallback chains — no single rate limit
takes the assistant down.

| Provider | Where | Powers | Key looks like |
|---|---|---|---|
| **Groq** | https://console.groq.com/keys | fast chat (Llama 3.3), Whisper STT | `gsk_…` |
| **Google AI Studio** | https://aistudio.google.com/apikey | Gemini, **embeddings**, TTS, live voice, image gen | `AIza…` |
| **NVIDIA NIM** | https://build.nvidia.com (any model page → Get API Key) | vision (primary), reasoning, quota backups | `nvapi-…` |

The Google key is the most important — embeddings, voice replies, and live
voice all need it. NVIDIA is optional but recommended (it's the primary
vision model and the backup when Google/Groq quotas hit).

## 3. Create your Telegram bot

1. In Telegram, talk to **@BotFather** → `/newbot` → pick a name and a
   username ending in `bot`. Copy the token (`123456789:AAH…`) →
   `TELEGRAM_BOT_TOKEN`.
2. Get **your own** numeric user id: talk to **@userinfobot**, copy the
   number → `TELEGRAM_ALLOWED_USER_ID`.

That id is the entire security model: the bot silently ignores everyone else.

## 4. Generate your app secrets

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # → ALAN_API_TOKEN
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # → FERNET_KEY
```

`ALAN_API_TOKEN` authenticates your own API/web requests. Treat it like a
password: it lives in `.env` only. If it ever lands in a committed file,
rotate it.

## 5. Fill in `.env`

```bash
cp .env.example .env
```

Required for core:

```
GROQ_API_KEY=…        GOOGLE_API_KEY=…      NVIDIA_API_KEY=…    # step 2
ALAN_API_TOKEN=…      FERNET_KEY=…                              # step 4
TELEGRAM_BOT_TOKEN=…  TELEGRAM_ALLOWED_USER_ID=…                # step 3
USER_NAME=YourName    # what Alan_T calls you
DATABASE_URL / POSTGRES_PASSWORD — leave the defaults unless you know why not
```

Everything else in `.env.example` (email, calendar, Brave search, ntfy) is
optional — step 9.

## 6. Point Alan_T at your files

Edit `config/mounts.yaml`. Each mount is a folder Alan_T may read; the
`include`/`exclude` filters are the **cloud-egress boundary** — whatever they
admit gets chunked and sent to Google's embedding API on first ingest. Start
with one small folder if unsure.

```yaml
mounts:
  notes:
    path: /Users/you/Documents/notes      # HOST path
    include: ["**/*.md", "**/*.txt", "**/*.pdf"]   # PDFs are ingested too
```

Keep the built-in `alan_notes` and `uploads` mounts — they make the notes the
assistant writes, and files you send it, searchable.

If you change the notes path, mirror it in `docker-compose.yml`'s bind-mount
(or set `NOTES_PATH` in `.env`) so the container sees the same path.

## 7. Bring the stack up

```bash
docker compose up -d --build                      # Postgres + API
docker compose exec api alembic upgrade head      # migrations (0001→0003)
docker compose exec api alan bootstrap            # config + DB sanity check
curl -H "Authorization: Bearer $ALAN_API_TOKEN" http://localhost:8000/api/v1/health/deps
```

`health/deps` should show postgres ok and all three providers configured.
Rebuilding after a git pull: `docker compose up -d --build` again, and re-run
the `alembic upgrade head` line (new migrations are additive).

**Web UI:** open http://localhost:8000 — chats are auto-titled, grouped by
project, and stream live. The port is bound to localhost only; for phone/
laptop access use Tailscale rather than exposing the port.

## 8. Telegram gateway

```bash
docker compose --profile telegram up -d
```

Message your bot "hi" — it should answer. `/start` shows every command:

- **Chats:** `/new`, `/list` (all chats, tap to switch), `/switch` (quick
  picker), `/rename <name>`, `/delete`, `/project <name>`, `/projects`
- **Assistant:** `/goal <thing>` (multi-step autonomy), `/approvals`
  (tap ✅/❌), `/digest`, `/library`, `/ingest`, `/status`
- **Media:** voice notes get transcribed AND answered with voice; photos go
  to the vision model; any file you send lands in your library (md/txt/pdf
  auto-ingest into knowledge).

## 9. Optional agents (light up when their credentials exist in `.env`)

### Email (IMAP/SMTP)
1. Use an **app password**, never your real one. Gmail: enable 2FA →
   https://myaccount.google.com/apppasswords.
2. `.env`: `IMAP_HOST=imap.gmail.com`, `SMTP_HOST=smtp.gmail.com`,
   `EMAIL_ADDRESS=you@gmail.com`, `EMAIL_PASSWORD=<app password>`.
3. Restart (`docker compose up -d`). Reading/triage is automatic; **sending
   always asks for approval**.

### Calendar (Google OAuth refresh token, one-time)
1. https://console.cloud.google.com → create project → enable **Google
   Calendar API** → OAuth consent screen (External; add yourself as test
   user) → create **OAuth client ID** (Desktop app).
2. Mint a refresh token once:
   ```bash
   uv run python - <<'PY'
   from urllib.parse import urlencode
   cid = input("client id: ")
   print("Open:\nhttps://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
       "client_id": cid, "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
       "response_type": "code", "access_type": "offline", "prompt": "consent",
       "scope": "https://www.googleapis.com/auth/calendar"}))
   import httpx
   code = input("paste code: "); secret = input("client secret: ")
   r = httpx.post("https://oauth2.googleapis.com/token", data={
       "client_id": cid, "client_secret": secret, "code": code,
       "redirect_uri": "urn:ietf:wg:oauth:2.0:oob", "grant_type": "authorization_code"})
   print(r.json())
   PY
   ```
3. Put client id/secret + `refresh_token` into `.env` (`GOOGLE_OAUTH_*`).
   Restart. Reads are automatic; event writes always ask for approval.

### Voice
Turn-based voice (voice notes → spoken replies) works out of the box with the
Google key. The live endpoints:

- `WS /api/v1/voice/live?token=$ALAN_API_TOKEN` — push-to-talk: send
  `{"type":"audio","data":<b64>,"format":"ogg"}` or `{"type":"text","text":…}`;
  receive transcript, streamed tokens, and WAV audio chunks that start at the
  first sentence.
- `WS /api/v1/voice/live-native?token=…` — native Gemini Live speech-to-speech
  (needs `uv sync --extra live-voice`; streams your mic to Google for the
  session — user-initiated only, by design).

### Browser automation
`uv sync --extra browser && playwright install chromium`. Without it, the
browser tool answers with install instructions instead of failing.

### Web search & push notifications
- `BRAVE_API_KEY` upgrades web search from DuckDuckGo scraping to Brave's API.
- `NTFY_TOPIC=<random private string>` adds push notifications via ntfy.sh.

### Automations
Edit `config/automations.yaml` — morning digest, nightly memory
consolidation, reminders, scheduled goals. **Everything ships disabled**;
flip `enabled: true` deliberately (each run spends quota and can message your
phone). `/digest` in Telegram runs the briefing on demand.

### MCP
- Alan_T **as a server**: point Claude Code (or any MCP client) at the
  `alan-mcp` command — every tool, agent, and skill, same permission gate.
- Alan_T **as a client**: add external servers in `config/mcp.yaml`; their
  tools default to ASK tier.

## 10. First-run checklist

- [ ] Web chat answers and the chat gets an auto-title
- [ ] Telegram `/status` shows all deps green
- [ ] `/ingest` then ask a question only your notes can answer — cited reply
- [ ] Voice note → transcript + spoken reply
- [ ] Photo → description
- [ ] "remember I prefer X" → restart → "what do I prefer?"
- [ ] `/goal write a note summarizing my week` → plan runs, note appears in `/library`
- [ ] An ASK action (e.g. "email Sarah …") produces approval buttons, not action
