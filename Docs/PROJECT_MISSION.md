# Alan_T — Project Mission & Overview

**Project:** Alan_T — Personal Autonomous AI Assistant  
**Status:** M0 complete, M1 ready to implement  
**Timeline:** ~6–8 weekends to daily-use (M0–M2)  
**Repo:** `/home/root1/Desktop/Code/PersonalAssist/Alan_T/Alan_T`

---

## What Is Alan_T?

A **self-hosted, persistent AI companion** built from the ground up for one person (you). It:

- **Chats** with you directly (text now, voice later)
- **Remembers** facts about you across restarts (Mem0-backed)
- **Reads your files** — notes, docs, code repos — and answers questions with citations (RAG + pgvector)
- **Takes action** for you — manages your calendar, sends Telegram messages, writes notes (agentic tasks)
- **Routes intelligently** — a Supervisor agent picks the right tool/agent for each request
- **Runs locally** — all your data stays on your machine; no vendor lock-in

**Core principle:** You own it completely. No subscriptions, no APIs logging your data, no opaque behavior.

---

## Why Build It?

### The Problem

Existing AI assistants (ChatGPT, Claude.ai, etc.) are:
- **Stateless** — they don't remember you between conversations
- **Generic** — not tailored to your files, notes, or workflows
- **Extractive** — they take your data to the cloud
- **Passive** — they answer questions; they don't *do* things for you (calendar, messages, repos)
- **Opaque** — you don't control the model, the prompts, or the routing logic

### The Solution

Build a **personal assistant that's yours**:
- **Persistent memory** — tell it something once, it remembers forever
- **Your data** — answers come from your files, not the internet
- **Agentic** — it picks tools and takes actions without asking
- **Transparent** — you write the prompts, choose the models, set the routing rules
- **Local** — runs on your machine; you host it

---

## Core Design: The 10-Agent Model

Rather than one monolithic "AI," Alan_T is **10 thin, specialized agents** on a **shared contract**. Each agent is:

- A **prompt** (tell it how to think)
- A **set of tools** (what it can do)
- The same **Agent interface** (so they compose cleanly)

| Agent | Purpose | Milestone | Status |
|---|---|---|---|
| **Conversation** | Direct chat with you | M0 | ✅ Done |
| **Memory** | Recall and store facts about you | M1 | 📋 Ready to code |
| **File** | RAG over your notes/repos | M2 | 📋 Ready to code |
| **Telegram** | Chat + act via Telegram | M2 | 📋 Ready to code |
| **Supervisor** | Route requests to the right agent | M3 | 📋 Ready to code |
| **Notes** | Create/update your notes | M4 | 📋 Ready to code |
| **Calendar** | Read/write Google Calendar | M4 | 📋 Ready to code |
| **Browser** | Visit URLs, read pages | Deferred | 🚫 Fragile, low priority |
| **Reflection** | Evaluate its own reasoning | Deferred | 🚫 Needs outcomes data |
| **Research** | Deep investigation tasks | Deferred | 🚫 Phase 7+ |

**Key point:** Agent #1 (Conversation) gets the contract right; agents #2–10 are mostly "new prompt + new tools."

---

## The Build Sequence (M0 → M4 → M6)

Why this order? **Dependency + payoff + daily-use readiness.**

| # | Milestone | Ships | Weeks | Definition of Done | Why Here |
|---|---|---|---|---|---|
| **M0** | **Foundation** | Agent contract, Conversation Agent, LiteLLM seam | ~2 | `POST /chat` returns a model answer via LiteLLM fallback chain; Conversation Agent on shared contract | The contract that makes 10 agents tractable. Direct chat. |
| **M1** | **It remembers you** | Memory Agent (Mem0-backed) | ~1 | Tell it "I prefer TypeScript" → restart → "what language do I prefer?" answers correctly | Conversation needs memory. First "this is mine" moment. |
| **M2** | **Reach it + your files** | Telegram (text+files), File Agent (RAG), pgvector store | ~2–3 | Message from Telegram; ingest notes folder; ask Q answerable only from those notes → correct answer with file citation | **The "I use this daily" point.** Phone access + cited answers from your notes. |
| **M3** | **Routing + skills go live** | Supervisor Agent, LangGraph orchestration, Skill registry, seed skills | ~1–2 | Mixed request routed by Supervisor to right agent; seed skill (e.g., note summarization) fires when description matches | 3 agents to route between → Supervisor is real work. Skills become the orchestration model. |
| **M4** | **Productivity** | Notes Agent, Calendar Agent, skill composition | ~2 | "Add 3pm meeting tomorrow" and "summarize my note on Z" both work end-to-end | Real assistant utility. First skills that compose calendar+notes+memory. |
| **M6** | **Voice** | Whisper STT, Gemini TTS, Telegram voice notes | weeks | Send Telegram voice note → transcript → answer → spoken reply | Built last; interfaces from M0/M2 already voice-ready. |

**Honest timeline:** M0–M2 = daily-use assistant in **6–8 weekends** (you can run it every day). M3 adds routing + skills. M4 productivity. M6 voice layers on top.

**Deferred (not in M0–M4):**
- Browser Agent (high maintenance, low priority until a concrete recurring task justifies it)
- Reflection Agent (needs outcomes + plans to evaluate — pair with Task Planning, Phase 7+)
- Research, Task Planning, Automation (valuable but not blocking daily use)
- Vision (dropped for now; archived in `Docs_COMPLEX/`)

---

## The Tech Stack (Why Each Choice)

### LLM: One Seam Over Three Free Providers

**Setup:** `config/models.yaml` defines model purposes (CHAT, ROUTER, EMBEDDER, etc.) and a **fallback chain** for resilience.

```yaml
CHAT:
  primary: { provider: groq, model: llama-3.3-70b-versatile, temperature: 0.7 }
  fallbacks:
    - { provider: gemini, model: gemini-2.5-flash }
    - { provider: nvidia_nim, model: deepseek-ai/deepseek-r1 }
```

**Providers:**
- **Groq (free tier):** Llama 3.3 70B, fast latency, high RPM. Primary for CHAT.
- **Google AI Studio (free tier):** Gemini 2.5 Flash, good long-context, embeddings, TTS, Live. Primary for long-context; fallback for CHAT.
- **NVIDIA NIM (free credits):** DeepSeek-R1 (reasoning), Qwen. Fallback for CHAT + ROUTER.

**Why:** Three independent free quotas = real resilience. No single point of failure. One LiteLLM seam hides provider details from agents.

**No profiles yet:** ADR-020 says "one config from env" until a real multi-profile swap forces a registry.

### Memory: Mem0

**Setup:** Mem0 handles fact extraction, embedding, and recall. Agents use a simple `MemoryPort` protocol.

```python
class MemoryPort(Protocol):
    async def add(self, user_id: str, content: str) -> None: ...
    async def search(self, user_id: str, query: str, limit: int = 5) -> list[str]: ...
```

**Why Mem0?** It's built for this use case — extract facts from conversations, embed them, and surface them later. Cheaper than building vector search ourselves. Easy to swap backends (Postgres, Pinecone, etc.) later.

**Backend:** Postgres (pgvector) — not Qdrant. Fewer moving parts. pgvector degrades gracefully when overloaded.

### Files: ai-vfs + pgvector

**Setup:** `ai-vfs` ingests your files (notes, repos, docs) into a store; pgvector indexes chunks by semantic embedding.

**Why:** ai-vfs is purpose-built for this — handles markdown, code, PDFs, image alt-text. pgvector is part of Postgres, so no new infrastructure.

### Database: Postgres + pgvector

**Whole stack in one box:**
- Session state (conversations)
- Memory facts (Mem0)
- Vector embeddings (file chunks)
- Skills, prompts, config (later)

**Why not:**
- Redis (no KV cache needed yet; add when jobs queue forms — ADR-021)
- Qdrant (pgvector is simpler; can swap if it measurably hurts)

### Orchestration: Plain async now, LangGraph from M3

**M0–M2:** Plain `async/await`. Simple routing in the Conversation Agent.

**M3+:** LangGraph. Supervisor becomes a LangGraph workflow that:
- Takes the incoming request
- Routes to the right agent
- Executes the agent's selected skill (if any)
- Returns the result

**Why:** LangGraph handles branching, loops, and sub-workflows cleanly. Worth the complexity only when routing is real.

### Deployment: Docker Compose + Tailscale

**M0–M2:** Docker Compose (api + postgres/pgvector).

**M2+:** Tailscale for remote access. Telegram gateway for messaging.

**Why:** One machine, fully self-hosted. Tailscale makes it accessible from your phone without exposing to the internet.

---

## Architecture: Hexagonal (Ports & Adapters)

**Layer 1 — Core (pure domain, zero SDK imports):**
```
core/
├── types.py           # Domain types (ChatMessage, AgentTask, AgentResult, etc.)
├── ports.py           # Protocols (LLMProvider, ConversationStore, MemoryPort, etc.)
├── llm.py             # ModelRouter — the seam over all LLM calls
└── agents/
    ├── base.py        # Agent contract (name, description, run())
    └── conversation.py # ConversationAgent
```

**Layer 2 — Adapters (implement ports, SDK code lives here):**
```
adapters/
├── litellm_provider.py # LiteLLM wrapper (Groq, Google, NVIDIA)
├── mem0_provider.py    # Mem0 wrapper (M1+)
├── db.py               # SQLAlchemy + asyncpg
├── models.py           # ORM (Session, ConversationTurn, etc.)
└── repository.py       # ConversationStore + MemoryStore implementations
```

**Layer 3 — App (FastAPI + bootstrap):**
```
app/
├── config.py           # Settings, model purposes loader
├── bootstrap.py        # build_container() — the ONLY wiring point
├── schemas.py          # FastAPI request/response
└── main.py             # create_app() factory, endpoints (/chat, /health)
```

**Rule:** `core/` imports **zero** adapter/SDK code. Adapters implement Protocols. Bootstrap wires them.

**Payoff:** Swap Groq for Ollama? Edit one adapter. Add a new agent? Implement the Protocol. Change storage from Postgres to SQLite? New adapter, core untouched.

---

## Shared Agent Services (AgentContext)

Every agent reaches the same services via `AgentContext`:

```python
@dataclass
class AgentContext:
    models: ModelRouter      # All LLM calls
    store: ConversationStore # Session history
    memory: MemoryPort | None # Facts about the user (M1+)
    # files: FileStore       # Your notes/repos (M2+)
    # skills: list[str]      # Skill bodies (M3+)
```

**Benefit:** No agent builds its own adapters. All integration logic lives in one place. Agents are just prompts + tool-calls.

---

## Voice-Ready From M0

**Design rule:** Model inbound as `IncomingMessage{kind: text | audio | file}`. Handle `text`/`file` now; raise "not yet" for `audio` until M6.

```python
@dataclass
class IncomingMessage:
    kind: Literal["text", "audio", "file"]
    text: str | None = None
    ref: str | None = None
```

**Payoff:** M6 (voice) = implement the audio branch + STT, not a refactor of agents.

---

## Skills: The Orchestration Model (M3+)

**Idea:** A *skill* is a reusable multi-step workflow that combines agents + tools.

Examples:
- "Summarize my notes on X" = File Agent + prompt
- "Find meetings next Tuesday and add a reminder" = Calendar Agent + memory lookup
- "Create a note from my Telegram chat" = Telegram Agent + Notes Agent + context

**How it works (M3+):**
1. Supervisor receives a request
2. Supervisor searches the skill registry for a match: "does any skill's description match this request?"
3. If yes: Supervisor routes to the agent that *owns* that skill, injecting the skill body into the prompt
4. Agent executes the skill's workflow

**Why:**
- Decouples skill authorship from agent code
- Skills scale without touching agents
- New skills = new prompts, not new code

**M0–M2:** Skills layer is there (empty `skills: list[str]` in AgentContext), but the Supervisor doesn't exist yet.

---

## Testing: Fakes-First

All tests use **fakes** — no external APIs, no Docker, no keys needed.

```python
# tests/fakes.py
class FakeLLMProvider:
    async def chat(self, spec: ModelSpec, req: ChatRequest) -> ChatResponse:
        if spec.provider in self.fail_providers:
            raise RateLimitedError(...)
        return ChatResponse(text="...", model=spec.litellm_model)

class InMemoryConversationStore:
    async def ensure_session(self, session_id: str) -> None: ...
    async def append_turn(self, session_id: str, message: ChatMessage) -> None: ...
    async def recent_turns(self, session_id: str, limit: int = 20) -> list[ChatMessage]: ...
```

**Payoff:** Fast, reliable tests. No flaky API timeouts. Same test code works for Unit + Integration (just swap fake ↔ real adapter).

---

## Scope: What's In, What's Not

### ✅ In (M0–M4)

- 10-agent target (Conversation, Memory, File, Telegram, Supervisor, Notes, Calendar, + 3 deferred)
- Persistent memory (Mem0)
- RAG over your files (ai-vfs + pgvector)
- Agentic task execution (Calendar, Notes, Telegram)
- Intelligent routing (Supervisor + LangGraph)
- Skills (progressive disclosure, Supervisor selection)
- Voice (M6, but interfaces built now)

### 🚫 Deferred (not blocking daily use)

- **Browser Agent** — Playwright is fragile; only build when a concrete recurring task justifies it
- **Vision** — dropped; archived in `Docs_COMPLEX/`
- **Reflection Agent** — needs outcomes + plans to evaluate
- **Task Planning / Research / Automation** — Phase 7+
- **Role registry / 3-profile capability gates** — one config from env (ADR-020)
- **Redis / job queue** — pgvector + async until concurrency demands it (ADR-021)

### 🚫 Explicitly Out of Scope

- Cloud hosting (fully self-hosted)
- Multi-user (single-user assistant)
- UI/frontend (API-first; Telegram is the interface)
- Real-time collab (personal assistant, not team tool)

---

## Ceremonies to Skip (Until They Hurt)

**ADR-020:** No role registry / 3-profile capability gates. One config from env.
- **When it becomes a problem:** You want different model behavior for "quick questions" vs. "deep reasoning." Swap config, restart.
- **Then build:** A profiles registry + capability gates. But not before it's a real pain.

**ADR-021:** No Redis / job queue.
- **When it becomes a problem:** Lots of Telegram messages queue up; responses get backed up. Build an arq queue + Celery.
- **Then build:** Job persistence + worker threads. But not before.

**ADR-022:** Hexagonal ports, but minimal import-linter CI.
- **When it becomes a problem:** An adapter starts importing core logic. Add a pre-commit hook to enforce the rule.
- **Then build:** import-linter config + CI gate.

---

## How to Get Started

### For Running M0 (Now)

```bash
# 1. Install deps
uv sync

# 2. Run tests (fakes + SQLite, no keys needed)
uv run pytest

# 3. Run lint
uv run ruff check src tests

# 4. Run locally (if you have API keys)
cp .env.example .env
# Edit .env: set ALAN_API_TOKEN + at least GROQ_API_KEY
docker compose up -d --build
curl -s localhost:8000/health
```

### For Next Steps (M1)

1. Read [Docs/BUILD_ORDER.md](BUILD_ORDER.md) — exact milestones + definitions of done
2. Read [Docs/memory/MEMORY_ARCHITECTURE.md](memory/MEMORY_ARCHITECTURE.md) — M1 design
3. Implement Memory Agent (follow [Docs/SESSION_CONTINUATION.md](SESSION_CONTINUATION.md), Step 1–10)
4. Run tests: `uv run pytest` should still pass with M1 tests added
5. Verify M1 definition of done: "I prefer TypeScript" → restart → "what language do I prefer?" answers correctly

---

## Decision Log

**Key decisions that cannot be changed without a rebuild:**

| ADR | Decision | Reason | Change If |
|---|---|---|---|
| ADR-011 | One LiteLLM seam for all LLM calls | Single point of model config + fallback logic | A provider's API changes incompatibly |
| ADR-016 | Mem0 for memory (not custom vector search) | Purpose-built, handles extraction + embedding | Mem0 can't scale to millions of facts |
| ADR-017 | pgvector for vectors (not Qdrant) | Simpler ops (one box); can scale with Postgres | pgvector measurably hurts performance |
| ADR-020 | No role registry / profiles yet (one config from env) | YAGNI — complexity when you need it | You regularly swap models for different tasks |
| ADR-021 | No Redis / job queue yet (async + pgvector for now) | YAGNI — complexity when you need it | Telegram queue backs up; responses lag |
| ADR-022 | Hexagonal but minimal import-linter CI | Manual discipline sufficient at 10 agents | Core starts importing adapters |

All ADRs documented in [Docs/architecture/DECISION_LOG.md](architecture/DECISION_LOG.md).

---

## References

**Essential reading:**
- [BUILD_ORDER.md](BUILD_ORDER.md) — **the Monday-morning checklist**; read this first
- [architecture/SYSTEM_OVERVIEW.md](architecture/SYSTEM_OVERVIEW.md) — lean stack at a glance
- [architecture/AGENTS.md](architecture/AGENTS.md) — 10-agent roster + contract

**Design docs (by milestone):**
- M0: [architecture/ORCHESTRATION.md](architecture/ORCHESTRATION.md)
- M1: [memory/MEMORY_ARCHITECTURE.md](memory/MEMORY_ARCHITECTURE.md)
- M2: [integrations/TELEGRAM.md](integrations/TELEGRAM.md), [knowledge/KNOWLEDGE.md](knowledge/KNOWLEDGE.md)
- M3: [agents/SUPERVISOR_AGENT.md](agents/SUPERVISOR_AGENT.md), [ai/SKILLS.md](ai/SKILLS.md)
- M4: [integrations/GOOGLE_CALENDAR.md](integrations/GOOGLE_CALENDAR.md)
- M6: [voice/VOICE_ARCHITECTURE.md](voice/VOICE_ARCHITECTURE.md)

**Full doc index:** [Docs/README.md](README.md) (32 lean docs)

---

## Summary: What You're Building

A **personal AI assistant, fully under your control**, that:

1. **Talks to you** (text now, voice later)
2. **Remembers you** (persists facts forever)
3. **Knows your files** (RAG + citations)
4. **Does things for you** (calendar, messages, notes)
5. **Routes intelligently** (Supervisor picks the right tool)
6. **Runs locally** (your machine, your rules)

**Timeline:** 6–8 weekends to daily-use (M0–M2). Voice by M6. It's ambitious but bounded — the architecture makes it tractable.

**Next step:** M1 (Memory). Read BUILD_ORDER.md for the definition of done, then start coding.
