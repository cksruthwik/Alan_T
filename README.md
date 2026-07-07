```text
 █████╗ ██╗      █████╗ ███╗   ██╗        ████████╗
██╔══██╗██║     ██╔══██╗████╗  ██║        ╚══██╔══╝
███████║██║     ███████║██╔██╗ ██║           ██║
██╔══██║██║     ██╔══██║██║╚██╗██║           ██║
██║  ██║███████╗██║  ██║██║ ╚████║  ███████╗ ██║
╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝  ╚══════╝ ╚═╝
```

# Alan_T — Personal Autonomous AI

A self-hosted, single-user AI companion in the Jarvis mold: persistent memory,
RAG over your own notes/PDFs/repos, a 12-agent roster behind one supervisor,
multi-step goal execution with reflection, and a hard permission gate on every
tool call. Reachable from the web UI, Telegram (text · voice · photos), a REST
API, and MCP. **No local model hosting** — three hosted free tiers (Groq,
Google, NVIDIA NIM) as fallback chains behind one seam.

> **Status: beta.** The full Docs_COMPLEX architecture is implemented, with
> unit + end-to-end suites and all model IDs verified against live provider
> catalogs. See [Docs_COMPLEX/AS_BUILT.md](Docs_COMPLEX/AS_BUILT.md) for the
> honest build-vs-plan ledger.

## What it does

| Capability | How |
|---|---|
| Chat with memory | ChatGPT-grade chats: auto-titled, rename/archive/delete, **projects** with shared instructions |
| Memory | Mem0 over pgvector; remembers across restarts; nightly consolidation |
| Your files, cited | Hybrid RAG (vector ∥ keyword, RRF) over mounted folders — md/txt/**PDF** |
| Autonomy | `/goal …` → planner decomposes → agents execute → reflection grades & learns |
| Email | Triage/summarize inbox, draft replies; **sending needs your approval** |
| Calendar | Google Calendar read/schedule/move (writes need approval) |
| Notes & documents | Obsidian-compatible markdown notes; versioned writing documents |
| Library | Unified view of notes/documents/images/uploads; upload anything → auto-ingest to RAG |
| Web research | Search (Brave/DDG) + fetch + cited synthesis |
| Browser | Playwright automation for pages static fetch can't reach (approval-gated) |
| Vision | Photos/screenshots → NVIDIA llama-3.2-90b-vision, Gemini backup |
| Voice | Voice notes → spoken replies; live WS voice (sentence-streamed TTS); native Gemini Live speech-to-speech with gated tools |
| Automations | Scheduled morning digest, memory consolidation, reminders, goals |
| Approvals | Every risky tool is ASK-tier: approve/deny from Telegram buttons or API |

## Interfaces

- **Web** — Alan_T's own client at `http://localhost:8000/`: streaming chat,
  auto-titled sessions grouped by project, hold-to-talk voice with spoken
  replies, approvals strip, library/tasks/projects panels, drag-drop uploads.
  Self-contained (no frameworks, no CDNs), token-authenticated
- **Telegram** — the whole assistant: text/voice/photos/files; `/start`, `/list`,
  `/switch`, `/rename`, `/delete`, `/project`, `/library`, `/goal`, `/approvals`,
  `/digest`, `/status` — a full ChatGPT-style client in your pocket
- **Voice** — `POST /api/v1/voice/turn` (voice note → spoken answer),
  `WS /api/v1/voice/live` (push-to-talk, replies start speaking at the first
  sentence), `WS /api/v1/voice/live-native` (Gemini Live speech-to-speech,
  tools still permission-gated)
- **REST API** — sessions/projects/chat (WS streaming), knowledge, memory,
  library, vision, tasks, approvals, automations, compare, `/metrics` (Prometheus)
- **MCP** — `alan-mcp` exposes every tool, agent, and skill to Claude Code etc.;
  external MCP servers plug in via `config/mcp.yaml` (same permission gate)

## The agents

conversation · file (RAG) · code · vision · memory · notes · documents ·
research · browser · automation — plus email and calendar, which register
themselves only when their credentials exist in `.env`. Each agent is a
persona + a tool grant on one shared agentic loop; the supervisor picks the
agent (and any skills) per message.

## Quick start

Full walkthrough with screenshots-level detail: **[setup.md](setup.md)**. The short version:

```bash
cp .env.example .env        # fill: 3 provider keys, ALAN_API_TOKEN, FERNET_KEY, Telegram
# review config/mounts.yaml — which folders Alan_T may read (cloud-egress boundary!)
docker compose up -d --build
docker compose exec api alembic upgrade head
docker compose exec api alan bootstrap          # sanity check
open http://localhost:8000                      # web UI
docker compose --profile telegram up -d         # + Telegram gateway
```

Optional agents light up when their credentials exist in `.env`: email
(IMAP/SMTP app password), calendar (Google OAuth refresh token), Brave search,
ntfy push — all in [setup.md §9](setup.md). Extras:
`--extra browser` (Playwright) · `--extra live-voice` (Gemini Live).

## Architecture in one breath

Ports & adapters. One **LiteLLM seam** (role → model + fallback chain,
`config/models.yaml`) with a boot-time **capability gate** that refuses a bad
model swap. One **tool registry** with ALLOW/ASK/DENY tiers
(`config/permissions.yaml`) — native, MCP, and skill-invoked tools all pass the
same gate; ASK becomes an interactive **approval**. Thin **agents** = persona +
tool grant on a shared agentic loop. A **supervisor** (fast ROUTER model) picks
agent + skills per message. **Planner → agents → reflection** is the autonomy
loop. Postgres+pgvector is the only stateful service.

Design docs: [`Docs_COMPLEX/`](Docs_COMPLEX/) (51 docs) ·
as-built deltas: [Docs_COMPLEX/AS_BUILT.md](Docs_COMPLEX/AS_BUILT.md)

## Development

```bash
uv sync --extra telegram
uv run pytest             # 37 unit + 15 e2e journeys (e2e needs Postgres up)
uv run ruff check alan_t tests
uv run uvicorn alan_t.app.main:app --reload
```

## License

[MIT](LICENSE). Everything Alan_T ships — backend, agents, and the web client —
is first-party code. Anything under `Resources/` is local reference material,
gitignored and never distributed.
