# Alan_T — System Overview

Version: 0.1
Status: Active

One-page orientation for anyone (human or agent) touching the codebase. Authoritative detail lives in the linked docs.

## What Alan_T Is

A self-hosted personal AI assistant: chat + voice interface, persistent memory, RAG over the user's own files/repos/notes, and (progressively) autonomous task execution via browser, desktop, calendar, notes, and Telegram.

## The Stack

| Layer | Technology | Why |
|---|---|---|
| API / interface | FastAPI (HTTP + WebSocket) | async, typed, streaming |
| Agent orchestration | LangGraph | stateful multi-agent graphs, checkpointing, human-in-the-loop interrupts |
| Models (text) | Groq free tier (Llama 3.3 70B, Qwen3-32B, GPT-OSS-120B, DeepSeek-R1-Distill) | fastest free inference for hot paths |
| Models (multimodal/long-context) | Google AI Studio (Gemini 2.5 Pro/Flash/Flash-Lite) | 1M context, vision, free tier |
| Embeddings | gemini-embedding-001 | free, strong quality |
| STT | whisper-large-v3-turbo (Groq) | near-realtime transcription |
| TTS / live voice | Gemini TTS / Gemini Live API | free-tier speech |
| LLM gateway | LiteLLM (SDK mode) | one adapter for all chat/embedding providers; fallbacks, budgets (ADR-011) |
| Background jobs | arq (Redis) | queues + cron: ingestion, extraction, consolidation, automations (ADR-012) |
| Voice pipeline | Pipecat | realtime transport, VAD, interruptions (ADR-014) |
| LLM observability | Langfuse (optional profile) | per-call traces, token costs, prompt versions (ADR-013) |
| Operational data | PostgreSQL | conversations, memory, tasks, audit |
| Runtime state | Redis | sessions, queues, rate-limit budgets |
| Semantic memory | Qdrant | vector search with payload filtering |
| Knowledge access | ai-vfs (sibling library) | versioned mirror of all sources + permission-scoped agent workspace (ADR-010) |
| Automation | Playwright (browser), pyautogui (desktop) | phases 5–6 |
| Remote access | Telegram Bot API + Tailscale | phase 8 |
| Deployment | Docker Compose, single host | personal scale |

**Nothing above is load-bearing by name.** Every row is an adapter behind a port ([ADD.md](ADD.md) §3) and swappable via config. Models specifically: any vendor, OSS or paid, selected by config *profile* (`free`/`paid`/`local`) with a bootstrap capability gate making swaps safe — [LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §2, ADR-017.

## How a Message Flows

1. User message arrives (HTTP/WS/Telegram) → API layer normalizes to a `UserTurn`.
2. **Supervisor** (LangGraph entry node) classifies intent with the ROUTER model (fast, cheap), routes to an agent, and selects any relevant **skills** from the catalog — one decision.
3. The agent (Conversation, File, Code, …) may call tools — every tool call passes the **permission layer** and is audited.
4. Model calls go through the **ModelRouter**: role → model → quota check → fallback chain.
5. Memory hooks: relevant long-term facts injected before the turn; new facts extracted after it.
6. Response streams back; conversation state checkpoints to Postgres.

Detailed flows: [WORKFLOWS.md](WORKFLOWS.md).

## The Agents

Supervisor + specialists (Conversation, Memory, File, Code, Vision, Browser, Desktop, Calendar, Notes, Research, Automation, Reflection). Roster, responsibilities, and routing rules: [AGENTS.md](AGENTS.md). Per-agent specs: `Docs/agents/`.

## The Skills

Reusable, packaged capabilities (instructions + required tools + optional scripts) applied on demand via progressive disclosure — the unit of reuse, modeled on Claude Agent Skills. Distinct from agents (personas) and tools (single calls); they *orchestrate* tools and never bypass the permission gate. Spec: [SKILLS.md](../ai/SKILLS.md).

Skills, prompts, and registries live in the **Shared Resource Layer** ([ADD.md](ADD.md) §4a): loaded once, immutable, read *directly* by the supervisor, every agent, and model-using tools — no proxy through the orchestrator, so a multi-agent run never bottlenecks on resource access. Access fans out; authority (the permission gate) stays central (ADR-019).

## The Memory Model

- **Short-term:** Redis — current session, active task context.
- **Long-term:** Postgres — preferences, goals, facts, project history.
- **Semantic:** Qdrant — embeddings of documents, code, conversation summaries.

Architecture: [MEMORY_ARCHITECTURE.md](../memory/MEMORY_ARCHITECTURE.md). Consolidation (episodic → durable): [MEMORY_CONSOLIDATION.md](../memory/MEMORY_CONSOLIDATION.md).

## The Knowledge Pipeline

Sources (folders, repos, PDFs, notes, emails, transcripts) → AI-VFS → ingestion (parse → chunk → embed → upsert) → hybrid retrieval → RAG with citations. Docs: `Docs/knowledge/`.

## Repository Layout (planned)

```
alan_t/
├── core/            # domain logic — NO provider imports
│   ├── agents/      # supervisor + specialist agents
│   ├── ports/       # all interfaces
│   ├── memory/      # memory logic
│   ├── knowledge/   # RAG orchestration, chunking
│   ├── planning/    # planning + reflection engines
│   └── security/    # permission policy
├── adapters/        # one package per provider
│   ├── groq/  google/  qdrant/  postgres/  redis/
│   ├── telegram/  playwright_/  desktop/
│   └── ai_vfs/
├── app/             # FastAPI app, bootstrap/composition root, config
├── workers/         # ingestion + scheduled job entrypoints
└── tests/           # unit (fakes) / contract (real adapters) / e2e
```

## Where to Read Next

- Building a feature → [ADD.md](ADD.md), then the area doc.
- Touching models → [LLM_STRATEGY.md](../ai/LLM_STRATEGY.md).
- Touching agent graphs → [LANGGRAPH.md](LANGGRAPH.md).
- Why is X this way? → [DECISION_LOG.md](DECISION_LOG.md).
