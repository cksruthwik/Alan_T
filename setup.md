Alan_T Setup Guide

Complete walkthrough to get from zero to a working Telegram bot. Follow in order.

---
1. Install Docker Desktop

Docker runs Postgres (with pgvector) and the API in containers — nothing to install manually.

1. Go to https://www.docker.com/products/docker-desktop/
2. Download Docker Desktop for Mac (choose Apple Silicon or Intel — check with ! uname -m; arm64 = Apple Silicon)
3. Install it, open it, let it finish starting (whale icon in the menu bar goes steady)
4. Verify from a terminal:
docker --version
docker compose version
4. Both should print version numbers, not "command not found."

---
2. Get your three free LLM API keys

Alan_T uses three independent free tiers as a fallback chain, so no single rate limit takes the assistant down.

Groq (primary chat model — fast Llama 3.3)

1. Go to https://console.groq.com/keys
2. Sign in (Google/GitHub/email)
3. Click Create API Key, name it alan-t, copy the value (starts with gsk_...) — you won't see it again, paste it somewhere temporarily safe

Google AI Studio (Gemini — fallback chat, embeddings, long-context)

1. Go to https://aistudio.google.com/apikey
2. Sign in with a Google account
3. Click Create API key → Create API key in new project (or existing project)
4. Copy the key (starts with AIza...)

This key is the most important one — it also powers embeddings, so knowledge search won't work without it.

NVIDIA NIM (reasoning fallback — optional but recommended)

1. Go to https://build.nvidia.com
2. Sign in, open any model page (e.g. search "deepseek-r1")
3. Click Get API Key on the right side
4. Copy the key (starts with nvapi-...)

If you skip this one, the app still works — the REASONER fallback chain just has one less rung.

---
3. Create your Telegram bot

1. Open Telegram, search for @BotFather, start a chat
2. Send /newbot
3. Give it a name (e.g. "Alan T") and a username ending in bot (e.g. alan_t_ruthwik_bot)
4. BotFather replies with a token like 123456789:AAH... — copy it, this is TELEGRAM_BOT_TOKEN
5. Now get your own numeric Telegram user ID (not the bot's): search for @userinfobot, start it, i6789 — copy that number, this is TELEGRAM_ALLOWED_USER_ID

This ID is the entire security model: the bot will silently ignore anyone else, even if they find it.

---
4. Generate your own app token

This is a token you invent yourself — it authenticates your own requests to the API (not tied to any provider).

Run in terminal:
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
Copy the output — this is ALAN_API_TOKEN.

---
5. Fill in .env

  Ran 1 shell command

I've created Alan_T/.env from the template. Open it in any editor and fill in the values you collected:

GROQ_API_KEY=gsk_...              # step 2
GOOGLE_API_KEY=AIza...            # step 2
NVIDIA_API_KEY=nvapi-...          # step 2 (optional)

ALAN_API_TOKEN=...                # step 4 (the random string you generated)
FERNET_KEY=                       # step 5a, below

TELEGRAM_BOT_TOKEN=123456789:...  # step 3
TELEGRAM_ALLOWED_USER_ID=123456789  # step 3 (your numeric ID, not the bot's)

DATABASE_URL=postgresql+asyncpg://alan:alan@localhost:5432/alan_t   # leave as-is
POSTGRES_PASSWORD=alan            # leave as-is, or pick your own — must match DATABASE_URL

5a. Generate FERNET_KEY (used for encrypting sensitive data at rest):

  Ran 2 shell commands

Copy that output into FERNET_KEY= in .env (run the command again yourself if you'd rather not reusn here in this conversation).

---
6. Point Alan_T at your notes

  Read 1 file

Edit config/vfs.yaml, uncomment the notes: block, and point path: at a real folder on your machine

mounts:
  notes:
    path: /Users/cksr/Documents/notes
    include: ["**/*.md", "**/*.txt"]
    exclude: ["**/.git/**", "**/node_modules/**"]

This is important: whatever's under that path gets read, chunked, and sent to Google's embedding API on first ingest. Point it at something you're comfortable sending to the cloud (start with one small test folder if unsure — you can add more mounts later).

Tell me the path once you've decided and I'll fill it in for you, or just edit the file yourself a.

---
7. Bring the stack up

Once .env and config/vfs.yaml are ready:

cd "/Users/cksr/Desktop/C/Projects/Gen AI/Alan_T_Root/Alan_T"

# 1. build the image + start Postgres and the API
docker compose up -d

# 2. run database migrations
docker compose exec api alembic upgrade head

# 3. sanity-check everything is wired correctly
docker compose exec api alan bootstrap

# 4. check dependency health (should show postgres/groq/google/nvidia all green/configured)
curl -H "Authorization: Bearer YOUR_ALAN_API_TOKEN" http://localhost:8000/api/v1/health/deps

8. Start the Telegram gateway

docker compose --profile telegram up -d

Then message your bot on Telegram — send it "hi" and it should reply. Try /status for a health che

9. (Optional) Ingest your notes for RAG

curl -X POST -H "Authorization: Bearer YOUR_ALAN_API_TOKEN" http://localhost:8000/api/v1/ingest
curl -H "Authorization: Bearer YOUR_ALAN_API_TOKEN" http://localhost:8000/api/v1/ingest/status

Or just send /ingest to the Telegram bot. First ingest of a large notes folder can take a while under free-tier embedding quota — that's expected, it resumes automatically.

---
Your action items right now: install Docker Desktop, collect the 3 LLM keys + Telegram token/ID, fill in .env, and tell me your notes folder path. Ping me once Docker's installed and I'll walk through step 7 with you live.