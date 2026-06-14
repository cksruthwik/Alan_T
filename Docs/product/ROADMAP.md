# Alan_T — Roadmap

Version: 0.2
Status: Active — re-sequenced to the lean build. Canonical sequence: [BUILD_ORDER.md](../BUILD_ORDER.md). De-scoping recorded in [DECISION_LOG.md](../architecture/DECISION_LOG.md) ADR-020..024.

Milestones are sequenced by dependency and daily-use payoff; each ships something usable.
A milestone is "done" when its acceptance checks pass and its docs are updated. The 10-agent
roster ([../architecture/AGENTS.md](../architecture/AGENTS.md)) is the target; this is the order it's built in.

## Stack (lean build)

- **LLM:** one LiteLLM seam over **Groq + Google AI Studio + NVIDIA NIM** (free), as a fallback chain (ADR-020).
- **Stores:** Postgres + **pgvector**; Mem0 for memory; ai-vfs for files. Redis/Qdrant deferred (ADR-021).
- **Orchestration:** plain async at M0–M2; **LangGraph + Supervisor + Skills** from M3.
- **No Vision; Browser deferred; Voice last (M6) but built voice-ready.**

## M0 — Foundation

Agent contract (with empty SKILLS layer) + **Conversation Agent**. FastAPI `/chat`, LiteLLM seam → Groq, Postgres.
**Exit:** `POST /chat` returns a model answer; Conversation runs on the shared contract.

## M1 — It remembers you

**Memory Agent** (Mem0-backed) behind the contract.
**Exit:** "I prefer TypeScript" → restart → "what language do I prefer?" answers correctly. *(MVP #1)*

## M2 — Reach it + your files

**Telegram Agent** (text + files) + **File Agent** (ingestion + hybrid search over your notes via ai-vfs + pgvector).
**Exit:** message it from your phone; ask a notes-only question → correct answer with a file citation. *(MVP #2 + daily-use)*

## M3 — Routing + skills go live

**Supervisor Agent** (ROUTER) + **LangGraph**. Skill registry + progressive disclosure + Supervisor Level-1 selection + a few seed skills ([../ai/SKILLS.md](../ai/SKILLS.md)).
**Exit:** mixed request routed to the right agent; a seed skill fires when its description matches, stays quiet otherwise.

## M4 — Productivity

**Notes Agent** (Markdown/Obsidian; overlaps File) + **Calendar Agent** (Google; OAuth is the cost). First skills composing calendar + notes + memory.
**Exit:** "add a 3pm meeting tomorrow" and "summarize my note on Z" both work end-to-end.

## M6 — Voice (last)

STT (`whisper-large-v3-turbo`, Groq) + TTS (Gemini), wired into Telegram + Conversation via the voice-ready interfaces.
**Exit:** Telegram voice note → transcript → answer; spoken reply back.

## Deferred (still in the 10-agent target)

- **Browser Agent** — after M4, only for a concrete recurring task (Playwright; high maintenance).
- **Reflection Agent** — pair with **Task Planning Agent**; reflection-on-plans needs a planner.
- **Later:** Research, Task Planning, Automation.
- **Vision** — dropped for now ([../../Docs_COMPLEX/vision/VISION_ARCHITECTURE.md](../../Docs_COMPLEX/vision/VISION_ARCHITECTURE.md), ADR-006/023).

## Cross-cutting (every milestone)

- **Quota awareness:** every model call goes through the LiteLLM fallback chain.
- **Observability:** every agent emits structured logs + metrics ([../observability/OBSERVABILITY.md](../observability/OBSERVABILITY.md)).
- **Security:** every tool registered in the permission system before first use ([../security/TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md)).

## Later / Aspirational

Local-model return (Ollama via the same LiteLLM seam), role registry + capability-gate when multi-profile swaps get real (ADR-020), Qdrant if pgvector falls short (ADR-021), Vision, Desktop, MCP ecosystem. Tracked in [BACKLOG.md](BACKLOG.md). Full original design preserved in `Docs_COMPLEX/`.
