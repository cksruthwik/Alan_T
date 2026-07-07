# Alan_T — Roadmap

Version: 0.1
Status: Active

Phases are sequential but each ships something usable. A phase is "done" when its acceptance scenarios pass and its docs are updated.

## Phase 1 — Foundation (MVP)

Chat + memory + personal RAG on free-tier APIs. Full definition: [MVP.md](MVP.md).

Deliverables: FastAPI service, LangGraph conversation graph, model-provider abstraction (LiteLLM adapter + role registry; Groq/Google as the default `free` profile), bootstrap capability gate, Postgres/Redis/Qdrant behind ports, ingestion pipeline, hybrid search, Docker Compose.

## Phase 2 — Voice

- Voice note transcription: `whisper-large-v3-turbo` (Groq).
- TTS replies: Gemini TTS.
- Live voice mode: Gemini Live API (speech-to-speech, interruption support).
- Memory consolidation job (nightly summarization) lands here too.

Exit: 2-minute spoken conversation with interruptions; voice note → transcript → answer round trip < 5 s.

## Phase 3 — Knowledge Platform

- Git repository indexing (code-aware chunking, [CHUNKING_STRATEGY.md](../knowledge/CHUNKING_STRATEGY.md)).
- Code search + explanation via `qwen/qwen3-32b`; long-file analysis via `gemini-2.5-pro` (1M context).
- AI-VFS as the unified knowledge access layer ([AI_VFS.md](../knowledge/AI_VFS.md)).
- Reranking + query rewriting in RAG.

Exit: "where is auth handled in repo X and how does it work?" answered with file:line citations.

## Phase 4 — Vision

- Image/screenshot QA, OCR, object detection — all via Gemini multimodal (ADR-006).
- Camera capture pipeline.

Exit: paste a screenshot, ask "what's the error and how do I fix it?" → correct extraction and answer.

## Phase 5 — Browser Agent

- Playwright + Browser Use behind a `BrowserDriver` port.
- Navigation, form fill, extraction; per-action permission policy ([TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md)).

Exit: "find the three cheapest X on site Y and summarize reviews" completes unattended.

## Phase 6 — Desktop Agent

- Mouse/keyboard/window control, app launching, screenshot loop with Vision Agent.
- Highest-risk surface → strictest permission tier, dry-run mode first.

Exit: "open my IDE, create a branch, and open file X" executes with confirmation prompts.

## Phase 7 — Agentic Intelligence

- Planning engine: goal → task DAG ([PLANNING_ENGINE.md](../ai/PLANNING_ENGINE.md)).
- Reflection engine: outcome evaluation, retry, plan repair ([REFLECTION_ENGINE.md](../ai/REFLECTION_ENGINE.md)).
- Scheduled automations: daily summary, weekly review.

Exit: "prepare me for a React interview" produces and executes a multi-day plan with tracked progress.

## Phase 8 — Remote Companion

- Telegram gateway: text, voice notes (STT→answer→TTS), file intake.
- Tailscale remote access; push notifications.

Exit: full voice-note conversation with Alan_T from a phone, away from home network.

## Cross-Cutting Tracks (every phase)

- **Abstraction discipline:** provider-swap drill run per phase.
- **Quota awareness:** every new model call goes through the rate-limit-aware client.
- **Observability:** every new agent emits structured logs + metrics ([LOGGING.md](../observability/LOGGING.md), [METRICS.md](../observability/METRICS.md)).
- **Security:** every new tool registered in the permission system before first use.

## Later / Aspirational (post Phase 8)

Local model return (Ollama adapter), multi-device sync, mobile app, smart home, voice cloning, MCP ecosystem integration, digital twin. Tracked in [BACKLOG.md](BACKLOG.md).
