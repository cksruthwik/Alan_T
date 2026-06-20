# Session Continuation: M0 Complete, Planning M1

**Date:** 2026-06-20  
**Status:** M0 complete and validated; M1 ready to implement  
**Model:** Claude Sonnet 4.6  

---

## Context: Recovering from Session Cutoff

This session is a continuation from a prior Claude session that hit context limits. The prior session (documented in [`WebChat.md`](WebChat.md)) completed:

1. **Full docs rewrite**: 50 → 32 lean docs, consolidated and cleaned
2. **M0 implementation**: FastAPI scaffold + LiteLLM seam + Agent contract + Conversation Agent
3. **Verification**: 15 tests passing, ruff clean, end-to-end proven

---

## What Was Done Before This Session

### M0 Completion Summary

**Definition of done (from BUILD_ORDER.md):** `POST /chat` returns a model answer via the LiteLLM seam; Conversation Agent runs on the shared contract.

**Status:** ✅ COMPLETE

#### Architecture

- **Hexagonal (Ports & Adapters):**
  - `src/alan_t/core/` — pure domain, zero provider imports
  - `src/alan_t/adapters/` — LiteLLM seam, Postgres/SQLAlchemy store
  - `src/alan_t/app/` — FastAPI + bootstrap (composition root)

- **LLM Seam (LiteLLM):**
  - Three providers as fallback chain: Groq (Llama 3.3 70B) → Google AI Studio (Gemini 2.5 Flash) → NVIDIA NIM (DeepSeek-R1)
  - Model purposes from `config/models.yaml`: CHAT, ROUTER, LONG_CONTEXT, SUMMARIZER, EMBEDDER
  - Normalizes provider errors (RateLimitError, ServiceUnavailableError) to domain exceptions

- **Agent Contract (shared by all 10 agents):**
  ```python
  @dataclass
  class AgentContext:
      models: ModelRouter
      store: ConversationStore
      skills: list[str] = field(default_factory=list)  # empty until M3
  
  @runtime_checkable
  class Agent(Protocol):
      name: str
      description: str
      async def run(self, task: AgentTask, ctx: AgentContext) -> AgentResult: ...
  ```

- **ConversationAgent:**
  - Builds PERSONA prompt, loads recent history, calls CHAT purpose
  - Non-text kinds (audio, file) return `status="degraded"` (voice-ready boundary)
  - Persists both user and assistant turns

#### Files Implemented

**Core domain (`src/alan_t/core/`):**
- `types.py` — Role(StrEnum), IncomingMessage, AgentTask, AgentResult, ChatMessage, ChatRequest, ChatResponse, Usage
- `ports.py` — ModelSpec, RateLimitedError, ProviderUnavailableError, LLMProvider(Protocol), ConversationStore(Protocol)
- `llm.py` — PurposeConfig, AllProvidersExhaustedError, ModelRouter (fallback chain + purpose routing)
- `agents/base.py` — AgentContext(dataclass), Agent(Protocol)
- `agents/conversation.py` — ConversationAgent implementation

**Adapters (`src/alan_t/adapters/`):**
- `litellm_provider.py` — LiteLLMProvider wrapping `litellm.acompletion()`, error normalization
- `db.py` — async SQLAlchemy engine + session factory
- `models.py` — Session + ConversationTurn ORM (mapped_column style)
- `repository.py` — SqlConversationStore, orders turns by ULID `id` (not `created_at` — deterministic ordering)

**App (`src/alan_t/app/`):**
- `config.py` — Settings (pydantic-settings), `load_purposes()` YAML parser
- `bootstrap.py` — Container dataclass, `build_container()`, `_export_provider_keys()`
- `schemas.py` — ChatRequestBody, ChatResponseBody
- `main.py` — `create_app()` factory; `GET /health`, `POST /chat` (bearer token auth)

**Infrastructure:**
- `config/models.yaml` — purpose → primary + fallback chain
- `alembic.ini`, `migrations/env.py` — async Alembic setup
- `migrations/versions/0001_initial.py` — sessions + conversation_turns DDL
- `docker-compose.yml` — api (runs migrations then uvicorn) + pgvector/pgvector:pg17
- `Dockerfile` — uv-based, factory mode
- `.env.example` — ALAN_API_TOKEN, DATABASE_URL, GROQ_API_KEY, GEMINI_API_KEY, NVIDIA_NIM_API_KEY

**Tests (`tests/`):**
- `fakes.py` — FakeLLMProvider (scripted), AlwaysDownProvider, InMemoryConversationStore
- `test_model_router.py` — 4 tests (primary, fallthrough, exhaustion, unknown purpose)
- `test_conversation_agent.py` — 3 tests (happy path + persistence, non-text degraded, history across turns)
- `test_api.py` — 5 tests (health no auth, missing token → 401, happy path, session continuity, validation)
- `test_sql_store.py` — 2 tests (idempotent ensure_session, oldest-to-newest ordering)

**Docs rewrite (consolidated, all lean-scope-native):**
- 32 total docs (50 → 32)
- Key consolidations:
  - `LANGGRAPH.md` + `WORKFLOWS.md` → `architecture/ORCHESTRATION.md`
  - `RAG_PIPELINE.md` + `INGESTION_PIPELINE.md` + `CHUNKING_STRATEGY.md` + `VECTOR_STORE.md` → `knowledge/KNOWLEDGE.md`
  - `LOGGING.md` + `METRICS.md` → `observability/OBSERVABILITY.md`
  - `DEPLOYMENT.md` merged into `infra/INFRASTRUCTURE.md`
  - `ADD.md` removed (content merged into `SYSTEM_OVERVIEW.md`)
- Zero ⚠️ banners, zero broken links

#### Verification

- **Tests:** `uv run pytest --tb=no -q` → **15 passed, 0 failed**
- **Lint:** `uv run ruff check src tests` → **All checks passed**
- **End-to-end (FakeLLMProvider, SQLite):**
  - `GET /health` → `{"status":"ok"}`
  - `POST /chat` (with bearer token) → `{"response":"...", "status":"ok", "session_id":"01KV..."}`
  - Follow-up with same `session_id` carried history
  - No token → `401 Unauthorized`

#### Key Decisions (Locked)

1. **10-agent target** (Telegram, Supervisor, Conversation, Memory, File, Browser-deferred, Calendar, Notes, Reflection-deferred)
2. **3 free LLM providers** (Groq, Google AI Studio, NVIDIA NIM) as fallback chain; no role registry/profiles until real swap
3. **No Redis/arq** until concurrency demanded (ADR-021)
4. **pgvector** not Qdrant; **Mem0** for memory; **ai-vfs** for files
5. **Skills live at M3** with Supervisor; M0–M2 built skill-ready
6. **Voice-ready from M0** (IncomingMessage{text|audio|file}; audio→"not yet" until M6)
7. **ULID** for deterministic same-microsecond ordering
8. **Hexagonal layering enforced**: core imports only Protocols; adapters implement; bootstrap wires

---

## What Was Clarified in This Continuation Session

### Question 1: Is M1 also implemented?

**Answer:** No. Only M0 is coded. M1 (Memory Agent backed by Mem0) is **designed** (docs exist) but **not yet implemented**.

**Code check results:**
- Source tree has no `mem0_provider.py`, `memory.py` agent, or `test_memory_agent.py`
- Only 17 Python source files exist (M0 only)
- Tests folder has only 5 test files

### Question 2: Where are the rest of the plans?

**Answer:** All remaining milestone designs live in `Docs/`:

| Milestone | Definition of Done | Primary Doc |
|---|---|---|
| **M0** | ✅ Done | `POST /chat` returns a model answer; Conversation Agent on shared contract |
| **M1** | Ready to code | Tell it "I prefer TypeScript" → restart → "what language do I prefer?" answers correctly |
| **M2** | Ready to design | Message from Telegram; ingest notes; Q answerable only from notes → correct answer with file citation |
| **M3** | Ready to design | Mixed request routed by Supervisor; seed skill fires when description matches |
| **M4** | Ready to design | "Add 3pm meeting tomorrow" and "summarize my note on Z" both work end-to-end |
| **M6** | Ready to design | Telegram voice note → transcript → answer; spoken reply |

**Documentation:**
- [BUILD_ORDER.md](BUILD_ORDER.md) — master build sequence, locked scope, definitions of done
- [architecture/AGENTS.md](architecture/AGENTS.md) — 10-agent roster, skills, M0→M4→M6
- [memory/MEMORY_ARCHITECTURE.md](memory/MEMORY_ARCHITECTURE.md) — Mem0 design (M1)
- [integrations/TELEGRAM.md](integrations/TELEGRAM.md) — Telegram Agent + gateway (M2)
- [knowledge/KNOWLEDGE.md](knowledge/KNOWLEDGE.md) — RAG pipeline, pgvector, ai-vfs (M2)
- [agents/SUPERVISOR_AGENT.md](agents/SUPERVISOR_AGENT.md) — Supervisor, LangGraph, Skills registry (M3)
- [ai/SKILLS.md](ai/SKILLS.md) — skill model, progressive disclosure (M3+)
- [integrations/GOOGLE_CALENDAR.md](integrations/GOOGLE_CALENDAR.md) — Calendar Agent + OAuth (M4)
- [voice/VOICE_ARCHITECTURE.md](voice/VOICE_ARCHITECTURE.md) — Whisper STT, Gemini TTS (M6)

All other docs (SYSTEM_OVERVIEW, LLM_STRATEGY, PROMPTS, DATA_MODEL, POSTGRES_SCHEMA, SECURITY, TEST_STRATEGY, etc.) provide supporting design context.

---

## Current State Summary

### What's Working

- ✅ Full hexagonal architecture (core/adapters/app separation enforced)
- ✅ LiteLLM seam with 3-provider fallback chain
- ✅ Agent contract (empty SKILLS layer ready for M3)
- ✅ Conversation Agent (prompt assembly, history, persistence)
- ✅ Postgres + SQLAlchemy + Alembic + pgvector container
- ✅ FastAPI `/chat` with bearer auth and `/health` probe
- ✅ ULID-based deterministic ordering (fixes SQLite tie-break bug)
- ✅ 15 tests, all passing, no external deps (fakes + SQLite)
- ✅ Ruff lint clean
- ✅ Docs lean, consolidated, zero broken links

### What's Next (M1)

**Implementation order per BUILD_ORDER.md:**

1. Add `mem0ai` to `pyproject.toml` and `uv sync`
2. Add `MemoryPort` protocol to `core/ports.py` (add, search, delete)
3. Build `Mem0Provider` adapter in `adapters/mem0_provider.py`
4. Build `InMemoryMemoryStore` fake in `tests/fakes.py`
5. Build `MemoryAgent` in `core/agents/memory.py` (or embed in ConversationAgent as a first step)
6. Extend `AgentContext` to carry `memory: MemoryPort | None`
7. Update `ConversationAgent` to:
   - Before LLM call: recall facts from memory (inject into prompt under `# MEMORY` section)
   - After user turn persisted: store the user's statement as a fact
8. Wire memory into `bootstrap.py`
9. Write tests (memory write/recall across restart)
10. Optional: add Alembic migration for `memory_items` table if Mem0 uses Postgres as vector store

**Definition of done:** "I prefer TypeScript" → `docker compose restart` → "what language do I prefer?" → answers correctly with the fact recalled from memory.

---

## Key Files & Patterns (for reference)

### Hexagonal Layering (Iron Rule)

```
core/
├── types.py              # Domain types (no imports of adapters)
├── ports.py              # Protocols (LLMProvider, ConversationStore, etc.)
├── llm.py                # ModelRouter (uses ports, not concrete adapters)
└── agents/
    ├── base.py           # Agent contract, AgentContext
    └── conversation.py   # ConversationAgent (uses ports)

adapters/
├── litellm_provider.py   # LiteLLMProvider implements LLMProvider
├── db.py                 # SQLAlchemy engine
├── models.py             # ORM (Session, ConversationTurn)
└── repository.py         # SqlConversationStore implements ConversationStore

app/
├── config.py             # Settings, load_purposes()
├── bootstrap.py          # build_container() — the ONLY wiring point
├── schemas.py            # FastAPI request/response
└── main.py               # create_app() factory, endpoints
```

**Rule:** `core/` imports **zero** adapter code; imports only Protocols. Adapters implement Protocols. Bootstrap wires them.

### Testing Pattern (no external deps)

```python
# tests/fakes.py
class FakeLLMProvider:
    async def chat(self, spec: ModelSpec, req: ChatRequest) -> ChatResponse:
        if spec.provider in self.fail_providers:
            raise RateLimitedError(...)
        return ChatResponse(...)

class InMemoryConversationStore:
    async def ensure_session(self, session_id: str, channel: str = "api") -> None: ...
    async def append_turn(self, session_id: str, message: ChatMessage) -> None: ...
    async def recent_turns(self, session_id: str, limit: int = 20) -> list[ChatMessage]: ...

# tests/test_conversation_agent.py
async def test_happy_path():
    provider = FakeLLMProvider(reply="I like TypeScript")
    store = InMemoryConversationStore()
    agent = ConversationAgent()
    result = await agent.run(task, AgentContext(models=..., store=store))
    assert result.status == "ok"
    assert "TypeScript" in result.response
```

### ULID Ordering (why it matters)

```python
# Old (broken on SQLite): order by created_at (ties on same microsecond)
stmt = select(ConversationTurn).order_by(ConversationTurn.created_at.desc())

# New (correct): order by ULID id (time-ordered + unique)
stmt = select(ConversationTurn).order_by(ConversationTurn.id.desc())
```

ULID = millisecond timestamp + random bits → inherent ordering, no ties.

### Model Router (fallback chain)

```python
# In ModelRouter.complete(purpose, request):
for depth, spec in enumerate(config.chain):  # [primary, fallback1, fallback2, ...]
    try:
        resp = await self._provider.chat(spec, req)
        return resp
    except (RateLimitedError, ProviderUnavailableError):
        log.warning(f"fallback from {spec.litellm_model}")
        continue
raise AllProvidersExhaustedError(...)
```

---

## Git & Branches

**Current branch:** `feature/v1`  
**Main branch:** `main`  
**Commits:**
- `eb56188` switchingOS
- `2eb89a8` M0,M1 (docs + M0 implementation)
- `842b261` Plans_Simple
- `75f5810` plans
- `316972e` List_docs

M0 implementation is on the current branch; docs rewrite fully merged.

---

## Next Session: Starting M1

If continuing in a new conversation, use this handoff to:

1. Read this file for full context
2. Check [BUILD_ORDER.md](BUILD_ORDER.md) for M1 definition of done
3. Read [memory/MEMORY_ARCHITECTURE.md](memory/MEMORY_ARCHITECTURE.md) for Mem0 design
4. Start with Step 1: add `mem0ai` to `pyproject.toml`
5. Follow the 10-step sequence above

**No external API keys or Docker needed for M1 tests** — use `InMemoryMemoryStore` fake and SQLite.

---

## References

- [WebChat.md](WebChat.md) — full prior session transcript (~1200 lines)
- [BUILD_ORDER.md](BUILD_ORDER.md) — master build sequence, locked decisions
- [architecture/SYSTEM_OVERVIEW.md](architecture/SYSTEM_OVERVIEW.md) — lean stack
- [architecture/DECISION_LOG.md](architecture/DECISION_LOG.md) — ADRs (ADR-020: no profiles yet, ADR-021: no Redis yet)
- [Docs/README.md](README.md) — full doc index (32 docs)
