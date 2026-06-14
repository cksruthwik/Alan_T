# Integration — Telegram

Milestone: **M2** (the "I use this daily" unlock — pulled early, not last) · Port: `MessagingGateway` · Adapter: `adapters/telegram/` (Bot API, long-polling)
Workflow: [ORCHESTRATION.md](../architecture/ORCHESTRATION.md) §2

## Design

A separate gateway process (same image, own entrypoint) that consumes the internal HTTP API — it holds no business logic and gets no private endpoints ([API_SPECIFICATION.md](../api/API_SPECIFICATION.md)). Long-polling, so no inbound port, no webhook TLS to manage. Built on **aiogram** (async Bot API framework): dispatch, inline keyboards, and media handling come from the library; the gateway stays a thin translation layer.

```
Telegram ◀──long poll──▶ gateway ──HTTP (localhost)──▶ api
```

## Identity (the security line)

- `TELEGRAM_ALLOWED_USER_ID` — exactly one numeric ID. Updates from any other sender: dropped, counted in metrics, never answered (answering reveals the bot is alive). This is the entire authN model and it is not negotiable ([SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md) §2).
- Bot token in env; bot set to privacy mode; never added to groups.

## Message Handling

| Incoming | Handling |
|---|---|
| Text | → chat turn (session per chat, persistent `session_id` mapping) |
| File | → confirm intent ("ingest or just hold?") → ingestion accordingly |
| Voice note (M6) | → Groq Whisper STT → answer → reply as text + voice note (TTS) since the user spoke first |
| `/commands` | `/status` (health+quota), `/forget` |

| Outgoing | Handling |
|---|---|
| Long answers | chunked at 4096 chars on paragraph boundaries; code blocks kept intact |
| Citations | rendered as `vpath` lines (no local links exist on phone) |
| **ASK approvals** | inline keyboard `[Approve] [Deny]` with the full preview text — the remote half of [TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md); decision resumes the LangGraph interrupt (from M3) |

Modeled as a voice-ready `IncomingMessage{text|file|audio}` (the `audio` branch lights up at M6) so adding voice is additive, not a refactor.

## Failure Posture

- Gateway down → core unaffected (chat/web still works); missed updates fetched on restart (long-poll offset persisted in Postgres).
- API unreachable from gateway → user gets one honest "backend unreachable" message, then silence until recovery (no spam loop).
- Rate limits (Telegram's): outgoing queue with pacing; approvals jump the queue.
