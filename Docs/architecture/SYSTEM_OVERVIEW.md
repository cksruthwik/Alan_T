# Alan_T — System Overview

Version: 0.2
Status: Active — lean scope ([BUILD_ORDER.md](../BUILD_ORDER.md))

One-page orientation for anyone (human or agent) touching the codebase. Authoritative detail lives in the linked docs.

## What Alan_T Is

A self-hosted, single-user personal AI assistant: text chat with persistent memory, RAG over your own files/notes/repos, reachable from your phone, and (progressively) autonomous task execution via notes, calendar, and later browser. A **10-agent target** built one milestone at a time (M0→M4, then M6). Voice comes last but interfaces are built voice-ready.

## The Stack (lean)

| Layer | Technology | Why |
|---|---|---|
| API / interface | FastAPI (HTTP + WebSocket) | async, typed, streaming |
| Agent orchestration | LangGraph (from M3) | stateful multi-agent graphs, checkpointing, human-in-the-loop interrupts |
| LLM gateway | **LiteLLM (one seam)** | single function over all providers; fallback chain, retries |
| Models | **Groq + Google AI Studio + NVIDIA NIM** (free tiers) | 3 independent quotas as a fallback chain for rate-limit resilience |
| Embeddings | gemini-embedding-001 | free, strong quality |
| Memory | **Mem0** | long-term facts/preferences with recall |
| Operational data | PostgreSQL | conversations, memory, audit, LangGraph checkpoints |
| Semantic search | **pgvector** (in Postgres) | vector search at single-user scale — one less container than Qdrant |
| Knowledge access | ai-vfs (sibling library) | versioned mirror of sources + permission-scoped agent workspace |
| Remote access | Telegram Bot API (M2) + Tailscale | phone access early — the "I use this daily" unlock |
| STT / TTS | Whisper (Groq) / Gemini TTS (M6) | voice last, built voice-ready |
| Deployment | Docker Compose, single host | personal scale |

**Nothing above is load-bearing by name.** Every row is an adapter behind a port and swappable via config. Models specifically go through **one LiteLLM seam** with the model + fallback order read from env — no role registry, no profiles, no capability gate until a real swap forces them (ADR-020). See [../ai/LLM_STRATEGY.md](../ai/LLM_STRATEGY.md).

## How a Message Flows

1. User message arrives (HTTP/WS/Telegram) → API layer normalizes to a `UserTurn`.
2. **Supervisor** (LangGraph entry node, from M3) classifies intent, routes to an agent, and selects any relevant **skills** from the catalog — one decision. (Before M3: direct to the Conversation Agent.)
3. The agent (Conversation, File, Memory, Notes, Calendar…) may call tools — every tool call passes the **permission layer** and is audited.
4. Model calls go through the **ModelRouter → LiteLLM seam**: model → quota check → fallback chain (Groq → Google → NVIDIA NIM).
5. Memory hooks: relevant long-term facts injected before the turn; new facts extracted after it (async, via Mem0).
6. Response streams back; conversation state checkpoints to Postgres.

Detailed flows: [ORCHESTRATION.md](ORCHESTRATION.md).

## The Agents (10-agent target, sequenced)

Built by milestone, not all at once:

- **M0** — Conversation (on the shared `Agent` contract; no Supervisor yet)
- **M1** — Memory (Mem0-backed)
- **M2** — Telegram, File (RAG)
- **M3** — Supervisor (routing + skills go live)
- **M4** — Notes, Calendar
- **M6** — voice wired into Telegram + Conversation
- **Deferred** (still in the target): Browser, Reflection, Task Planning, Research, Automation
- **Dropped (for now):** Vision

Roster, responsibilities, and routing: [AGENTS.md](AGENTS.md). Per-agent specs: `Docs/agents/`.

## The Skills

Reusable, packaged capabilities (instructions + required tools + optional scripts) applied on demand via progressive disclosure — modeled on Claude Agent Skills. Only a skill's `name`+`description` sits in context until the Supervisor selects it. Distinct from agents (personas) and tools (single calls); they *orchestrate* tools and never bypass the permission gate. **Skills go live at M3** with the Supervisor; M0–M2 agents are built skill-ready. Spec: [../ai/SKILLS.md](../ai/SKILLS.md).

## The Memory Model (lean)

- **Short-term:** session window in Postgres — current conversation.
- **Long-term:** **Mem0** (over Postgres) — preferences, goals, facts, project history; survives restart.
- **Semantic:** **pgvector** — embeddings of documents, notes, conversation summaries.

Architecture: [../memory/MEMORY_ARCHITECTURE.md](../memory/MEMORY_ARCHITECTURE.md).

## The Knowledge Pipeline

Sources (folders, repos, PDFs, notes) → ai-vfs → ingestion (parse → chunk → embed → upsert to pgvector) → hybrid retrieval → RAG with citations. Doc: [../knowledge/KNOWLEDGE.md](../knowledge/KNOWLEDGE.md).

## Repository Layout (planned)

```
alan_t/
├── core/            # domain logic — NO provider imports
│   ├── agents/      # conversation, memory, file, notes, calendar, supervisor
│   ├── ports/       # all interfaces
│   ├── memory/      # memory logic (Mem0 integration)
│   ├── knowledge/   # RAG orchestration, chunking
│   └── security/    # permission policy
├── adapters/        # one package per provider
│   ├── litellm/  postgres/  pgvector/
│   ├── telegram/  google_calendar/
│   └── ai_vfs/  mem0/
├── app/             # FastAPI app, bootstrap/composition root, config
├── workers/         # ingestion + background job entrypoints
└── tests/           # unit (fakes) / contract (real adapters) / e2e
```

## Architectural Pattern: Hexagonal (Ports & Adapters)

**The core contains domain logic; the edges contain providers.**

- The **core** holds agents, memory logic, RAG orchestration, permissions. It is pure Python, imports no provider SDKs, and is testable with fakes.
- **Ports** are Python interfaces (Protocols) the core depends on.
- **Adapters** implement ports against concrete providers (LiteLLM, Postgres, pgvector, Mem0, ai-vfs, Telegram, etc.). Adapters are wired at startup from config.

Every external dependency must be swappable without touching the core (PRD requirement). The lean build adds ports **reactively** — only the LLM seam, plus Mem0/ai-vfs/store boundaries, exist up front; more are introduced the first time something is actually swapped (ADR-022).

```
            ┌────────────────────────────────────────────────┐
 Interfaces │  FastAPI HTTP/WS  │  Telegram  │  CLI  │ Sched │
            └─────────┬──────────────────────────────────────┘
                      ▼
            ┌────────────────────────────────────────────────┐
            │         APPLICATION CORE (pure logic)          │
            │  Supervisor · Agents · Memory · RAG · Perms    │
            │  depends only on PORTS (interfaces)            │
            └─────────┬──────────────────────────────────────┘
                      ▼
            ┌────────────────────────────────────────────────┐
 Providers  │ Groq · Google · NVIDIA · Postgres · pgvector   │
            │ Mem0 · ai-vfs · Telegram · ...                │
            └────────────────────────────────────────────────┘
```

**Layering rules (enforced):**
1. Core never imports adapters. Direction: adapters → core ports only.
2. Provider SDK types never cross a port boundary; adapters translate to/from core domain types.
3. Model names, connection strings, secrets exist only in config.
4. One composition root (`app/bootstrap.py`) wires adapters to ports.

**Key ports (lean build):**
- `LLMProvider` — chat/completion, tool calling, streaming via LiteLLM (any provider).
- `EmbeddingProvider` — text → vector via Gemini embeddings.
- `VectorStore` — pgvector (not Qdrant in M0–M4).
- `RelationalStore` — Postgres for conversations, memory, audit.
- `FileSource` — ai-vfs for knowledge access + versioning.
- `CalendarProvider` — Google Calendar (M4).
- `NotesProvider` — Markdown folder (M4).
- `MessagingGateway` — Telegram (M2).
- `STTProvider`, `TTSProvider` — Groq Whisper, Gemini TTS (M6).

Detailed port spec and future swaps: see the codebase `core/ports/`.

## Where to Read Next

- Orchestration & flows → [ORCHESTRATION.md](ORCHESTRATION.md).
- Agents & routing → [AGENTS.md](AGENTS.md).
- Touching models → [../ai/LLM_STRATEGY.md](../ai/LLM_STRATEGY.md).
- Why is X this way? → [DECISION_LOG.md](DECISION_LOG.md).
