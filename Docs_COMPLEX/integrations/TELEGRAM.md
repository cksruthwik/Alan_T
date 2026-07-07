# Integration — Telegram

Phase: 8 · Port: `MessagingGateway` · Adapter: `adapters/telegram/` (Bot API, long-polling)
Workflow: [WORKFLOWS.md](../architecture/WORKFLOWS.md) W8

## Design

A separate gateway process (same image, own entrypoint) that consumes the internal HTTP API — it holds no business logic and gets no private endpoints ([API_SPECIFICATION.md](../api/API_SPECIFICATION.md) §8). Long-polling, so no inbound port, no webhook TLS to manage. Built on **aiogram** (async Bot API framework — ADR-015): dispatch, inline keyboards, and media handling come from the library; the gateway stays a thin translation layer.

```
Telegram ◀──long poll──▶ gateway ──HTTP (localhost)──▶ api
```

## Identity (the security line)

- `TELEGRAM_ALLOWED_USER_ID` — exactly one numeric ID. Updates from any other sender: dropped, counted in metrics, never answered (answering reveals the bot is alive). This is the entire authN model and it is not negotiable ([SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md) §2).
- Bot token in env; bot set to privacy mode; never added to groups.

## Message Handling

| Incoming | Handling |
|---|---|
| Text | → W1 chat turn (session per chat, persistent `session_id` mapping) |
| Voice note | → W4: Groq Whisper STT → answer → reply as text + voice note (TTS) since the user spoke first |
| File/photo | → confirm intent ("ingest, analyze, or just hold?") → W3 ingestion or VISION analysis accordingly |
| `/commands` | `/status` (health+quota), `/tasks` (running task runs), `/forget`, `/digest now` |

| Outgoing | Handling |
|---|---|
| Long answers | chunked at 4096 chars on paragraph boundaries; code blocks kept intact |
| Citations | rendered as `vpath` lines (no local links exist on phone) |
| **ASK approvals** | inline keyboard `[Approve] [Deny]` with the full preview text — the remote half of [TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md) §4; decision resumes the LangGraph interrupt |
| Digests/notifications | from the Automation agent via this gateway |

## Failure Posture

- Gateway down → core unaffected (chat/web still works); missed updates fetched on restart (long-poll offset persisted in Redis).
- API unreachable from gateway → user gets one honest "backend unreachable" message, then silence until recovery (no spam loop).
- Rate limits (Telegram's): outgoing queue with pacing; approvals jump the queue.
