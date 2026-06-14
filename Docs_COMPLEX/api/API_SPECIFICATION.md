# Alan_T — API Specification

Version: 0.1
Status: Active — FastAPI generates the executable OpenAPI; this doc fixes the contract shape and conventions.

## 1. Conventions

- Base: `http://<host>:8000/api/v1` (versioned path; v1 is frozen at MVP shape).
- Auth: single static bearer token (`Authorization: Bearer <ALAN_API_TOKEN>`) — single-user system behind localhost/Tailscale ([SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md) §3). No OAuth, no user management.
- Errors: RFC 9457 problem+json: `{type, title, status, detail, trace_id}`. Rate-limit exhaustion → `503` with `retry_after_seconds` and which provider window is exhausted — honesty surfaced at the API layer too.
- All responses carry `trace_id` (correlates with logs/audit).
- Streaming: WebSocket for chat/voice; SSE fallback for chat.

## 2. Chat

| Endpoint | Method | Purpose |
|---|---|---|
| `/chat/sessions` | POST | create session → `{session_id}` |
| `/chat/sessions` | GET | list sessions (id, title, channel, last_activity) |
| `/chat/sessions/{id}` | GET | session detail + turns (paginated) |
| `/chat/sessions/{id}/messages` | POST | send message (non-streaming) → full answer |
| `/chat/ws/{session_id}` | WS | bidirectional streaming chat |

**WS protocol (client→server):** `{type:"message", content, modality:"text"}` · `{type:"approval", request_id, decision:"approve"|"deny"}` · `{type:"abort"}`

**(server→client):** `{type:"token", text}` · `{type:"status", note}` ("searching your notes…") · `{type:"citation", vpath, position}` · `{type:"approval_request", request_id, tool, preview, risk}` ([LANGGRAPH.md](../architecture/LANGGRAPH.md) §5) · `{type:"done", turn_id, degraded:[]}` · `{type:"error", problem}`

## 3. Memory

| Endpoint | Method | Purpose |
|---|---|---|
| `/memory` | GET | list items; filters: `kind`, `status`, `q` |
| `/memory` | POST | explicit remember `{content, kind?, tags?}` |
| `/memory/{id}` | PATCH | edit content/tags; confirm flagged item |
| `/memory/{id}` | DELETE | soft delete (7-day window) |
| `/memory/export` | GET | full JSON export |
| `/memory/review` | GET | items awaiting confirmation ([MEMORY_ARCHITECTURE.md](../memory/MEMORY_ARCHITECTURE.md) §5) |

## 4. Knowledge

| Endpoint | Method | Purpose |
|---|---|---|
| `/knowledge/search` | POST | `{query, scope?, top_k?}` → chunks + scores + citations (raw retrieval, no LLM) |
| `/knowledge/sources` | GET | mounts + per-mount ingest stats |
| `/knowledge/sources/{vpath}` | GET | resolve a citation → full chunk/source content |
| `/ingest` | POST | `{path}` enqueue ingestion (ASK-tier — confirms before first cloud embed of a new tree) |
| `/ingest/status` | GET | queue depth, done/pending counts, ETA ([INGESTION_PIPELINE.md](../knowledge/INGESTION_PIPELINE.md) §8) |

## 5. Voice (Phase 2)

| Endpoint | Method | Purpose |
|---|---|---|
| `/voice/transcribe` | POST | audio file → `{transcript}` (STT only) |
| `/voice/messages` | POST | audio → full W4 round trip → `{transcript, answer_text, answer_audio_url}` |
| `/voice/live` | WS | live voice bridge to Gemini Live ([VOICE_ARCHITECTURE.md](../voice/VOICE_ARCHITECTURE.md)) |

## 6. Tasks (Phase 7)

| Endpoint | Method | Purpose |
|---|---|---|
| `/tasks` | POST | `{goal}` → plan → `{run_id, plan, requires_approval}` |
| `/tasks/{run_id}/approve` | POST | approve/deny plan or pending step |
| `/tasks/{run_id}` | GET | status, steps, verdicts, report |
| `/tasks` | GET | list runs |
| `/automations` | GET/POST/PATCH | manage scheduled jobs |

## 7. System

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | liveness (no auth) |
| `/health/deps` | GET | per-dependency status: postgres, redis, qdrant, groq, google — feeds degradation flags |
| `/system/quota` | GET | current window budgets per provider/model ([LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §7) |
| `/system/audit` | GET | tool audit log (paginated, filterable) |
| `/system/models` | GET | active role→model registry (read-only view of config) |

## 8. Non-Goals of This API

No multi-tenant concepts, no API keys management, no public exposure (Tailscale-only beyond localhost), no GraphQL. Telegram is a gateway process consuming this same API internally — it gets no private endpoints.
