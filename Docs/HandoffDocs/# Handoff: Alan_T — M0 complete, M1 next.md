# Handoff: Alan_T — M0 complete, M1 next

* Date: 2026-06-15
* Project/Repo: Alan_T — `/home/root1/Desktop/Code/PersonalAssist/Alan_T/Alan_T`
* Goal: Build a self-hosted personal AI assistant in lean, milestone-by-milestone increments. M0 is done. M1 is the immediate next task.

---

## Current State

* Status: ready for handoff (M0 done, M1 not started)

### Completed

* **Full Docs rewrite**

  * 50 → 32 docs
  * Lean-scope-native
  * Zero ⚠️ banners
  * Zero broken links

* Consolidated:

  * `LANGGRAPH + WORKFLOWS` → `ORCHESTRATION`
  * `RAG + INGESTION + CHUNKING + VECTOR_STORE` → `KNOWLEDGE`
  * `DEPLOYMENT` → `INFRASTRUCTURE`
  * `LOGGING + METRICS` → `OBSERVABILITY`

* Deleted:

  * `DEPLOYMENT.md`

* **M0 implementation**

  * FastAPI skeleton
  * LiteLLM seam
  * Agent contract
  * Conversation Agent
  * 15 tests passing
  * Ruff clean
  * End-to-end proven with `/health` and `/chat`

* Key files:

  * `pyproject.toml`
  * `config/models.yaml`
  * `src/alan_t/`
  * `migrations/versions/0001_initial.py`
  * `docker-compose.yml`
  * `Dockerfile`
  * `tests/`

### Pending

* **M1 — Memory Agent backed by Mem0**

  * Definition of done:

    * User says: `"I prefer TypeScript"`
    * Docker compose restart
    * User asks: `"what language do I prefer?"`
    * Assistant answers correctly

* M2

  * Telegram
  * RAG

* M3

  * Supervisor
  * LangGraph
  * Skills

* M4

  * Notes
  * Calendar

* M6

  * Voice

---

# Decisions and Rationale

## 10-agent target (non-negotiable)

1. Telegram
2. Supervisor
3. Conversation
4. Memory
5. File
6. Browser (deferred)
7. Calendar
8. Notes
9. Reflection (deferred)

Vision dropped.

---

## LLM Strategy

Three free providers behind a single LiteLLM seam:

1. Groq → Llama 3.3 70B
2. Google AI Studio → Gemini 2.5 Flash
3. NVIDIA NIM → DeepSeek-R1

Purpose:

* Rate-limit resilience
* Provider failover

Configured in:

```yaml
config/models.yaml
```

---

## Deferred Complexity

### ADR-020

No:

* Role registry
* 3-profile system
* Capability-gate bootstrap

Until a real swap forces it.

Single configuration from environment variables.

### ADR-021

No:

* Redis
* arq

Until concurrency demands it.

pgvector remains sufficient.

---

## Core Technology Choices

* Vector DB: pgvector
* Memory: Mem0
* Files: ai-vfs

---

## Architecture

Hexagonal architecture:

```text
core/
  ↓ Protocols only

adapters/
  ↓ Implement ports

app/bootstrap.py
  ↓ Only wiring point
```

### Skills

Skills are IN and central.

Arrive in M3 with Supervisor.

All agents are skill-ready now.

```python
AgentContext.skills: list[str]
```

---

## Voice Readiness

Supported from M0:

```python
IncomingMessage.kind:
- text
- audio
- file
```

Current behavior:

```text
audio → "not yet"
```

Voice implementation arrives in M6.

---

## ID Strategy

Using:

```python
python-ulid
```

Reason:

* Time ordered
* Globally unique

Ordering:

```sql
ORDER BY id DESC
```

instead of:

```sql
ORDER BY created_at DESC
```

SQLite same-microsecond ties previously caused test failures.

---

## Uvicorn Decision

Do NOT place:

```python
app = create_app()
```

at bottom of `main.py`.

Run using factory mode:

```bash
uvicorn ... --factory
```

Avoids application creation during module import.

---

## Database Portability

`ensure_session()` uses:

```python
db.get()
```

instead of PostgreSQL-specific:

```sql
INSERT ... ON CONFLICT
```

This keeps SQLite tests passing.

---

# Changes Made

## Files Touched

### Documentation

```text
Docs/
```

* 32 lean docs
* See `Docs/README.md`

```text
Docs_COMPLEX/
```

* Archived original 50-doc design
* Not touched during M0

---

### Project Configuration

```text
pyproject.toml
```

Includes:

* uv build
* FastAPI
* LiteLLM
* SQLAlchemy
* pydantic-settings
* structlog
* python-ulid

Also:

* Ruff config
* pytest asyncio_mode=auto

---

### Models

```text
config/models.yaml
```

Purposes:

1. CHAT
2. ROUTER
3. LONG_CONTEXT
4. SUMMARIZER
5. EMBEDDER

---

### Domain Layer

#### src/alan_t/core/types.py

Contains:

* Role(StrEnum)
* IncomingMessage
* AgentTask
* AgentResult
* ChatMessage
* ChatRequest
* ChatResponse
* Usage

#### src/alan_t/core/ports.py

Contains:

* ModelSpec
* RateLimitedError
* ProviderUnavailableError
* LLMProvider (Protocol)
* ConversationStore (Protocol)

#### src/alan_t/core/llm.py

Contains:

* PurposeConfig
* AllProvidersExhaustedError
* ModelRouter

#### src/alan_t/core/agents/base.py

Contains:

```python
AgentContext
Agent
```

#### src/alan_t/core/agents/conversation.py

ConversationAgent:

* Persona prompt
* History load
* CHAT purpose
* Persist both turns
* Non-text degraded response

---

### Adapters

#### src/alan_t/adapters/litellm_provider.py

* Uses `litellm.acompletion`
* Normalizes errors into domain exceptions
* `litellm.drop_params = True`

#### src/alan_t/adapters/db.py

* Async SQLAlchemy engine
* Session factory

#### src/alan_t/adapters/models.py

Contains:

* Session ORM
* ConversationTurn ORM

#### src/alan_t/adapters/repository.py

SqlConversationStore:

```sql
ORDER BY id DESC
```

using ULIDs.

---

### App Layer

#### src/alan_t/app/config.py

* Settings
* YAML purpose loader

#### src/alan_t/app/bootstrap.py

Contains:

* Container dataclass
* build_container()
* _export_provider_keys()

#### src/alan_t/app/schemas.py

Contains:

* ChatRequestBody
* ChatResponseBody

#### src/alan_t/app/main.py

Factory app:

```python
create_app()
```

Endpoints:

* GET `/health`
* POST `/chat`

Auth:

* Bearer token

Error mapping:

```python
AllProvidersExhaustedError → HTTP 503
```

---

### Migrations

#### alembic.ini

#### migrations/env.py

Async Alembic configuration.

#### migrations/versions/0001_initial.py

Creates:

* sessions
* conversation_turns

---

### Infrastructure

#### docker-compose.yml

Services:

* api
* pgvector/pgvector:pg17

API startup:

```bash
run migrations
→ start uvicorn
```

#### Dockerfile

* uv based
* factory mode

#### .env.example

Contains:

* ALAN_API_TOKEN
* DATABASE_URL
* GROQ_API_KEY
* GEMINI_API_KEY
* NVIDIA_NIM_API_KEY

---

### Tests

#### tests/fakes.py

Contains:

* FakeLLMProvider
* AlwaysDownProvider
* InMemoryConversationStore

#### tests/test_model_router.py

4 tests:

* primary
* failthrough
* exhaustion
* unknown purpose

#### tests/test_conversation_agent.py

3 tests:

* happy path
* persistence
* non-text degraded
* history

#### tests/test_api.py

5 tests:

* health
* auth failure
* happy path
* session continuity
* validation

#### tests/test_sql_store.py

2 tests:

* idempotent ensure_session
* ordering

---

## Commit

```text
842b261
```

Description:

```text
Plans_Simple
```

Includes:

* Documentation rewrite
* M0 implementation

---

# Validation

## Executed

### Tests

```bash
uv run pytest --tb=no -q
```

Result:

```text
15 passed
0 failed
```

### Lint

```bash
uv run ruff check src tests
```

Result:

```text
All checks passed
```

### Live E2E

Using:

* FakeLLMProvider
* SQLite

Verified:

```http
GET /health
```

Response:

```json
{"status":"ok"}
```

Verified:

```http
POST /chat
```

Response:

```json
{
  "response":"...",
  "status":"ok",
  "session_id":"01KV..."
}
```

Also verified:

* Session continuity
* History carry-forward
* Missing token → 401

---

## Not Run

### Real Providers

Not tested against:

* Groq
* Gemini
* NVIDIA NIM

Requires API keys.

### Docker

Not tested:

```bash
docker compose up
```

Requires:

* Docker
* API keys

---

# Blockers and Risks

## Blockers

None for M1.

Only real-provider testing requires API keys.

---

## Risks

### Mem0 API Surface

PyPI package:

```text
mem0ai
```

May differ from docs.

Verify:

```python
mem0.add(...)
mem0.search(...)
```

before wiring.

---

### SQLite vs PostgreSQL JSON

If Mem0 stores JSONB structures:

* SQLite tests may fail
* Use fake memory adapter in tests

---

# Next Steps (Ordered)

## 1. Add Mem0 Dependency

Add to:

```toml
pyproject.toml
```

Then:

```bash
uv sync
```

---

## 2. Add MemoryPort

File:

```python
src/alan_t/core/ports.py
```

```python
class MemoryPort(Protocol):
    async def add(
        self,
        user_id: str,
        content: str
    ) -> None:
        ...

    async def search(
        self,
        user_id: str,
        query: str,
        limit: int = 5
    ) -> list[str]:
        ...
```

---

## 3. Extend AgentContext

File:

```python
src/alan_t/core/agents/base.py
```

Add:

```python
memory: MemoryPort | None = None
```

---

## 4. Build Mem0 Adapter

Create:

```python
src/alan_t/adapters/mem0_provider.py
```

Implements:

```python
MemoryPort
```

using:

```python
mem0ai
```

---

## 5. Build Test Fake

File:

```python
tests/fakes.py
```

Add:

```python
InMemoryMemoryStore
```

Implementation:

```python
dict[str, list[str]]
```

Must satisfy:

```python
MemoryPort
```

---

## 6. Wire Memory into ConversationAgent

File:

```python
src/alan_t/core/agents/conversation.py
```

### Before LLM Call

```python
await ctx.memory.search(
    session_id,
    task.message.text,
)
```

Inject results into prompt:

```text
# MEMORY
...
```

### After Persistence

```python
await ctx.memory.add(
    session_id,
    task.message.text,
)
```

Store user facts.

---

## 7. Update Bootstrap

File:

```python
src/alan_t/app/bootstrap.py
```

Instantiate:

```python
Mem0Provider
```

Inject into:

```python
AgentContext
```

---

## 8. Write Tests

Create:

```python
tests/test_memory_agent.py
```

Verify:

### Store Memory

```text
"I prefer TypeScript"
```

gets stored.

### Recall Memory

Fresh context.

Same session.

Ask:

```text
"What language do I prefer?"
```

Response mentions:

```text
TypeScript
```

---

## 9. Validation

Run:

```bash
uv run pytest
uv run ruff check src tests
```

Everything must pass.

---

## 10. Optional Migration

Create:

```text
0002_memory_items.py
```

Only if Mem0 is configured to use PostgreSQL storage.

Check:

```python
vector_store.provider
```

first.

---

# Open Questions

## Memory Backend for M1

Options:

### A. In-process / SQLite

Pros:

* Fastest iteration
* Minimal setup

Recommended for M1.

### B. pgvector

Pros:

* Matches final architecture

Cons:

* More setup overhead

Recommendation:

```text
Use SQLite/in-process for M1.
Move to pgvector later.
```

---

## Identity Key

Should memory be keyed by:

### Option A

```text
session_id
```

### Option B

```text
user_id
```

For now:

```text
session_id == user_id
```

Single-user self-hosted system.

Revisit in M2 when Telegram introduces a stable Telegram user ID.

---

# Startup Prompt for Next Conversation

Continue this work using only this handoff. Assume no access to prior chat history.

Project: Alan_T — a self-hosted personal AI assistant at:

```text
/home/root1/Desktop/Code/PersonalAssist/Alan_T/Alan_T
```

Git branch:

```text
develop
```

M0 is fully complete:

* FastAPI `/chat`
* FastAPI `/health`
* LiteLLM fallback seam

  * Groq → Gemini → NVIDIA NIM
* ConversationAgent
* SqlConversationStore
* Alembic migration complete
* 15 tests passing
* Ruff clean

Architecture:

```text
src/alan_t/core/
    ↓ pure domain

src/alan_t/adapters/
    ↓ edge adapters

src/alan_t/app/
    ↓ FastAPI + bootstrap
```

Tests:

```text
tests/fakes.py
```

Use:

* SQLite
* No Docker
* No API keys

Start with:

```text
M1 — "It remembers you"
```

Follow the Next Steps section above.

Step 1:

```text
Add mem0ai to pyproject.toml and run uv sync.
```

Definition of Done:

```text
User: "I prefer TypeScript"

Restart process

User: "What language do I prefer?"
```

Assistant answers:

```text
TypeScript
```

Implementation guidance:

* Build fake memory first
* Keep tests key-free
* Then wire real Mem0Provider

Architecture rules:

1. core/ imports zero adapter/provider code
2. Only Protocols cross boundaries
3. AgentContext is the dependency injection point
4. tests/fakes.py is the testing API
5. Run:

```bash
uv run pytest
uv run ruff check src tests
```

before calling M1 complete.
