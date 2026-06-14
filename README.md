```text
 █████╗ ██╗      █████╗ ███╗   ██╗        ████████╗
██╔══██╗██║     ██╔══██╗████╗  ██║        ╚══██╔══╝
███████║██║     ███████║██╔██╗ ██║           ██║
██╔══██║██║     ██╔══██║██║╚██╗██║           ██║
██║  ██║███████╗██║  ██║██║ ╚████║  ███████╗ ██║
╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝  ╚══════╝ ╚═╝
```

# Alan_T — Personal Autonomous AI Assistant

A self-hosted, persistent AI companion: chat (voice later), long-term memory, RAG over your
own notes/files/repos, and progressively autonomous task execution (Telegram, calendar,
browser) — fully under your control.

**Status:** lean build. Canonical build sequence: **[Docs/BUILD_ORDER.md](Docs/BUILD_ORDER.md)** (M0–M4, then M6).
The full original design (all phases) is archived in [`Docs_COMPLEX/`](Docs_COMPLEX/).

## Stack at a Glance

- **Models:** one LiteLLM seam over three free tiers as a fallback chain — **Groq** (Llama 3.3 70B, Whisper), **Google AI Studio** (Gemini 2.5, embeddings, TTS, Live), **NVIDIA NIM** (DeepSeek-R1, Qwen). Model + fallback order from env/config; local models (Ollama) are a later config swap.
- **Agents:** 10-agent target, thin, on one shared contract. **Skills** are the orchestration model — the Supervisor selects `{agent, skills}` from M3.
- **Orchestration:** FastAPI; plain async at M0–M2, **LangGraph + Supervisor** from M3.
- **State:** PostgreSQL + **pgvector** (Mem0 for memory, ai-vfs for files). Redis/Qdrant deferred.
- **Deployment:** Docker Compose, single host; Tailscale for remote, Telegram gateway (from M2).

## Documentation

Start here: [Docs/BUILD_ORDER.md](Docs/BUILD_ORDER.md) · index: [Docs/README.md](Docs/README.md)

| Area | Docs |
|---|---|
| Build / Product | [Build Order](Docs/BUILD_ORDER.md) · [MVP](Docs/product/MVP.md) · [Roadmap](Docs/product/ROADMAP.md) · [PRD](Docs/product/PRD.md) · [Backlog](Docs/product/BACKLOG.md) |
| Architecture | [System Overview](Docs/architecture/SYSTEM_OVERVIEW.md) · [ADD](Docs/architecture/ADD.md) · [Agents](Docs/architecture/AGENTS.md) · [LangGraph](Docs/architecture/LANGGRAPH.md) · [Workflows](Docs/architecture/WORKFLOWS.md) · [Decision Log](Docs/architecture/DECISION_LOG.md) |
| AI | [LLM Strategy](Docs/ai/LLM_STRATEGY.md) · [Skills](Docs/ai/SKILLS.md) · [Prompts](Docs/ai/PROMPTS.md) · [Tool Catalog](Docs/ai/TOOL_CATALOG.md) |
| Memory / Knowledge | [Memory](Docs/memory/MEMORY_ARCHITECTURE.md) · [AI-VFS](Docs/knowledge/AI_VFS.md) · [Ingestion](Docs/knowledge/INGESTION_PIPELINE.md) · [Chunking](Docs/knowledge/CHUNKING_STRATEGY.md) · [RAG](Docs/knowledge/RAG_PIPELINE.md) · [Vector Store](Docs/knowledge/VECTOR_STORE.md) |
| Data / API | [Data Model](Docs/data/DATA_MODEL.md) · [Postgres](Docs/data/POSTGRES_SCHEMA.md) · [API](Docs/api/API_SPECIFICATION.md) |
| Agents | [Supervisor](Docs/agents/SUPERVISOR_AGENT.md) · [Memory](Docs/agents/MEMORY_AGENT.md) · [File](Docs/agents/FILE_AGENT.md) |
| Integrations | [Telegram](Docs/integrations/TELEGRAM.md) · [Google Calendar](Docs/integrations/GOOGLE_CALENDAR.md) · [Tailscale](Docs/integrations/TAILSCALE.md) |
| Voice / Security / Infra | [Voice](Docs/voice/VOICE_ARCHITECTURE.md) · [Security](Docs/security/SECURITY_ARCHITECTURE.md) · [Tool Permissions](Docs/security/TOOL_PERMISSIONS.md) · [Infrastructure](Docs/infra/INFRASTRUCTURE.md) · [Deployment](Docs/infra/DEPLOYMENT.md) |
| Ops | [Test Strategy](Docs/testing/TEST_STRATEGY.md) · [Logging](Docs/observability/LOGGING.md) · [Metrics](Docs/observability/METRICS.md) |

Full original design (Vision, Browser, Planning/Reflection, Automation, all phases): [`Docs_COMPLEX/`](Docs_COMPLEX/).

## Build Milestones

- **M0** Foundation — agent contract + Conversation, `/chat` via LiteLLM
- **M1** Memory — remembers facts across restarts
- **M2** Reach it + files — Telegram (text/files) + RAG over your notes  ← *daily-use point*
- **M3** Routing + skills — Supervisor + LangGraph + seed skills
- **M4** Productivity — Notes + Calendar
- **M6** Voice — Whisper STT + Gemini TTS (built voice-ready from M0)
- **Deferred:** Browser, Reflection+Planning, Research, Automation, Vision

Details: [Docs/BUILD_ORDER.md](Docs/BUILD_ORDER.md) · [Docs/product/ROADMAP.md](Docs/product/ROADMAP.md)
