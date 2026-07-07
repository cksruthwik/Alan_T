# Alan_T — Desk-Jarvis Upgrade Plan

Status: proposal · Date: 2026-07-07
Companion docs: [AS_BUILT.md](AS_BUILT.md) (what exists) ·
[SKILLS_UPGRADE_PLAN.md](SKILLS_UPGRADE_PLAN.md) (the brain-content plan).

**North star:** Alan_T as an on-desk Jarvis — always listening at the desk,
hands-free voice both ways, proactive (it speaks first when something matters),
able to act on the desk machine — with Telegram as the same assistant away
from the desk. The server stays in Docker exactly as built; everything
"desk" lands in one small host-side companion process.

**What's already Jarvis-grade and needs no work:** 12-agent roster + supervisor
+ skills · memory (Mem0/pgvector) + nightly consolidation · hybrid RAG ·
planner→reflection autonomy · approval gate with Telegram buttons · full
Telegram parity (text/voice/photos/files) · voice endpoints
(`/voice/turn`, `WS /voice/live` sentence-streamed TTS, `WS /voice/live-native`
Gemini Live S2S) · scheduler · MCP both directions.

The gaps between that and "Jarvis on my desk":

| Gap | Evidence |
|---|---|
| Never run live — every provider integration written-to-spec, unverified | AS_BUILT "Known not-production-yet" |
| Secrets committed to git | `python3 -c "import secrets; print(secret.md` (tracked, contains a real token + Fernet key) |
| No always-on ear — voice is push-to-talk (web UI) or voice notes (Telegram) | `app/voice.py` |
| No desk actuation — desktop agent (PRD FR-8) explicitly not built; Docker can't touch the host | AS_BUILT deviations table |
| Proactivity exists but is off and cron-only — no event triggers, no runtime reminders | `config/automations.yaml` (all `enabled: false`, static YAML) |
| Pending approvals die on restart | AS_BUILT: approvals in-memory |
| No evals, no latency numbers | AS_BUILT |

---

## Phase 0 — Make it real (blockers; nothing else matters until these)

**0.1 Purge the committed secrets — today.**
The tracked file `python3 -c "import secrets; print(secret.md` holds a
generated `ALAN_API_TOKEN` and `FERNET_KEY`.
① `git rm` the file ② if either value made it into `.env`, regenerate both
(the file *is* the generation recipe) ③ they live in git history — before this
repo is ever pushed anywhere, rewrite history (`git filter-repo`) or treat
both values as burned. Fernet-encrypted rows in Postgres need re-encryption if
the key rotates, so rotate **before** real data exists — i.e. now.

**0.2 First live end-to-end run.**
`docker compose up` with real keys → alembic → `alan bootstrap` → one real
conversation on each interface (web, Telegram, REST). Then burn down the
known-unverified list one by one: NVIDIA vision call, Gemini TTS wire format,
DDG scrape, Mem0 round-trip, PDF ingestion, approval button flow. Expect each
to need a fix; that's the point. Keep a `LIVE_NOTES.md` of every fix — it
becomes the runbook.

**0.3 Persist approvals to Postgres.**
A Jarvis whose pending "send this email?" evaporates on container restart
isn't trustworthy. Small table (id, tool, args-json, preview, status,
created/decided timestamps), broker keeps its API, loads pending rows at boot.
This also gives the audit trail AS_BUILT deferred.

**0.4 Turn on the two shipped automations** (morning digest, 03:30 memory
consolidation) once 0.2 proves Telegram delivery. First taste of proactive.

*Exit criteria: a week of daily real use via web + Telegram with zero
container-restart data loss.*

---

## Phase 1 — The desk companion (the "on-desk" essence)

One small host-side Python process (`companion/`, run by launchd on macOS —
**not** in Docker; it needs the mic, speakers, and later the desktop). It is a
thin client of the voice endpoints that already exist — no server changes to
start.

**1.1 Always-on ear, privacy-sane.**
- Wake word locally: **openWakeWord** (free, runs on CPU, custom "Alan"
  possible) — audio never leaves the machine until the wake word fires.
- After wake: **silero-vad** to capture until end-of-speech.
- Ship a hard-mute toggle (hotkey + tray/menu-bar state) from day one.

**1.2 The loop.**
wake → capture → stream to `WS /api/v1/voice/live` → play sentence-streamed
TTS as it arrives → resume listening. Fallback mode: `POST /voice/turn`
(simpler, higher latency) as the first milestone, WS streaming as the second.
Native mode: a config flag switches the bridge to `/voice/live-native`
(Gemini Live S2S) — same companion, different endpoint.

**1.3 Barge-in.**
VAD keeps running during playback; user speech kills the audio queue and
starts a new capture. The architecture already assigns interruption to the
client (ADR-014 deviation) — the companion *is* that client.

**1.4 Presence signal.**
Companion holds its WS open (or heartbeats `/api/v1/status`). "Companion
connected" = user is at the desk — Phase 3 routes proactive output on this
single bit.

**1.5 Latency budget.** Target wake→first spoken syllable **< 2 s**
(sentence-streamed TTS was built exactly for this). Add one histogram metric;
tune only what it exposes.

Stack: `sounddevice` + `openwakeword` + `silero-vad` + `websockets` —
~300 lines, one file to start. No Pipecat (already rejected in AS_BUILT), no
GUI, no tray app beyond a mute indicator.

*Exit criteria: say "Alan, what's on my calendar?" from across the desk,
hear the answer, interrupt it mid-sentence with a follow-up.*

---

## Phase 2 — Desk hands (the unbuilt desktop agent, PRD FR-8)

The companion grows a second face: an **MCP server** exposing desk tools. This
rides plumbing that already exists — external MCP tools register as
`<server>_<tool>` and pass the same ALLOW/ASK/DENY gate (`config/mcp.yaml`).

**2.1 Transport (the one real integration task).**
`mcp_host/client.py` spawns stdio servers; a Dockerized server can't spawn a
host process. Add **one** streamable-HTTP/SSE transport to the MCP client;
companion serves MCP on `localhost:<port>`; server reaches it at
`host.docker.internal`. Bind localhost-only + bearer token (reuse
`ALAN_API_TOKEN` — post-rotation).

**2.2 Desk tools, gated conservatively:**

| Tool | Tier | Does |
|---|---|---|
| `desk_screenshot` | ALLOW | capture screen → temp file path (vision agent answers "what's on my screen?") |
| `desk_notify` | ALLOW | native desktop notification |
| `desk_media` | ALLOW | play/pause/next/volume (macOS: `osascript` media keys) |
| `desk_open` | ASK | open app / file / URL |
| `desk_clipboard_read` | ASK | read clipboard (may hold passwords — never ALLOW) |
| `desk_clipboard_write` | ASK | set clipboard |

Explicitly **never**: host shell (`shell_exec` stays permanently DENY),
keystroke/mouse injection, arbitrary file writes. The Jarvis fantasy dies the
day it types into the wrong window.

**2.3 Wire into the brain:** a `desk` agent (persona + grant over the
`desk_*` tools) in the roster, plus one skill — `screen_helper`
("what am I looking at / read this error on my screen": screenshot →
analyze_image → answer, offer to save to notes). Registration is conditional
on the MCP server being reachable, matching the email/calendar pattern.

*Exit criteria: "Alan, what does this error on my screen mean?" answered
hands-free; "open the PR page" prompts one approval and does it.*

---

## Phase 3 — Proactive Jarvis (it speaks first)

**3.1 Event triggers, not just cron.** One polling worker (extend the existing
scheduler; no event bus, no queue):
- **Email:** IMAP poll every few minutes (IDLE later if poll chafes); a new
  message matching "important" heuristics (sender in contacts, or urgent
  keywords) → one-line triage ping. Quiet hours respected.
- **Calendar lookahead:** event starting in ~15 min → warning with the
  meeting's one-liner (later: the `meeting_prep` skill output).
- **Goal completion:** planner run finishes → result summary.

**3.2 Presence-routed delivery.** One rule: companion connected → speak it at
the desk (`desk_notify` + TTS); else → Telegram. This single rule is what
makes it feel like *one* assistant across desk and phone.

**3.3 Runtime reminders.** "Remind me at 6 to call mom" currently has no
mechanism (automations are static YAML). Add one-shot jobs: a `reminders`
table + a `set_reminder` tool (ALLOW) + scheduler pickup. This is the single
most-used Jarvis feature; it's ~50 lines on the existing scheduler.

**3.4 Digest goes spoken.** Morning digest at the desk = Alan says good
morning and reads it; away = Telegram message as today.

*Exit criteria: you sit down, Alan greets you with the digest; a reminder you
set by voice fires at the right place (desk speaker or phone).*

---

## Phase 4 — Feel: latency, voice, manners

- **4.1 Instant acks.** For turns that will run tools, speak a short ack
  ("On it.") before the tool rounds, then the answer. One change in the voice
  path: emit a canned ack sentence when the first response round contains
  tool calls.
- **4.2 One voice.** Pin a single TTS voice/rate; time-of-day greeting
  variants. Personality lives in `core/prompts/chat.j2`, not in code.
- **4.3 Measure.** Histograms: wake→first-audio, turn→first-token,
  tool-round count per turn. Tune the worst offender only.
- **4.4 Barge-in polish** from Phase 1 field notes.
- **Skip:** speaker diarization (single-user system), emotion detection,
  local LLM hosting.

---

## Phase 5 — Brain content (parallel track, already planned)

The skills catalog is the Jarvis *behavior* layer and has its own plan —
[SKILLS_UPGRADE_PLAN.md](SKILLS_UPGRADE_PLAN.md). The Jarvis-critical subset,
in order: `daily_briefing` · `meeting_prep` · `inbox_reply` ·
`commitments_tracker` · `screen_helper` (Phase 2 above) · `reminder` flows
(Phase 3.3). Do its Phase A (hardening + evals) during Phase 0's live-run
week — it's small and independent.

---

## Phase 6 — Always-on hardening

- `restart: unless-stopped` + healthchecks on api/postgres/telegram services;
  companion: launchd `KeepAlive` + exponential WS reconnect.
- Nightly `pg_dump` to the host (one cron line) — Postgres is the only state.
- Watch `/metrics` for provider 429/fallback-depth; add budget pre-flight only
  if quota exhaustion is actually observed (AS_BUILT's Redis deferral stands).
- Quiet hours + rate cap on proactive pings (config keys, not a subsystem).

---

## Explicitly not building (revisit only on real need)

- **Home control** — when a real smart device exists, a Home Assistant MCP
  server drops into `config/mcp.yaml` with zero code. Not before.
- Multi-user / speaker ID · wake-word training UI · kiosk display / avatar /
  face · local model hosting · Pipecat · an event bus · a mobile app
  (Telegram *is* the mobile app).

---

## Order & size

| # | Item | Depends on | Size |
|---|---|---|---|
| 1 | 0.1 secrets purge + rotation | — | minutes, **do first** |
| 2 | 0.2 first live run + fix list | keys, Docker | days of poking |
| 3 | 0.3 durable approvals | 0.2 | ~1 migration + broker edit |
| 4 | 0.4 enable digest/consolidation | 0.2 | config flip |
| 5 | Skills Phase A (evals/hardening) | — | small, parallel |
| 6 | 1 desk companion (PTT→wake→WS→barge-in) | 0.2 | the big one; ~300-line start |
| 7 | 3.3 reminders | 0.2 | ~50 lines |
| 8 | 3.1–3.2 event triggers + presence routing | 1 | small worker |
| 9 | 2 desk MCP (transport + tools + agent) | 1 | the second big one |
| 10 | 4 feel/latency | 1 | iterative |
| 11 | 5 Jarvis skills waves | Skills plan | steady drip |
| 12 | 6 hardening | all | config + cron |

The shape of the whole plan: **the server is done — go live with it, then
build one small host process (ear → mouth → hands) and one proactivity worker.**
Everything else is tuning.
