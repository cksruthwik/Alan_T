# Alan_T — Architecture Design Document (ADD)

Version: 0.1
Status: Active

## 1. Architectural Style

**Hexagonal (Ports & Adapters) around an agentic core.**

- The **core** contains domain logic: agents, memory logic, planning, RAG orchestration, permission policy. It is pure Python, imports no provider SDKs, and is fully testable with fakes.
- **Ports** are Python interfaces (Protocols/ABCs) the core depends on.
- **Adapters** implement ports against concrete providers (Groq, Google, Qdrant, Postgres, Redis, Playwright, Telegram, …). Adapters live at the edge and are wired in by configuration at startup.

This is the load-bearing decision of the whole system (PRD A2): every external dependency must be swappable without touching the core.

```
            ┌────────────────────────────────────────────────┐
 Interfaces │  FastAPI HTTP/WS  │  Telegram  │  CLI  │ Sched │   (driving adapters)
            └─────────┬──────────────────────────────────────┘
                      ▼
            ┌────────────────────────────────────────────────┐
            │                 APPLICATION CORE               │
            │  Supervisor ─ Agents ─ Planning ─ Reflection   │
            │  Memory logic ─ RAG orchestration ─ Permissions│
            │                                                │
            │  depends only on PORTS (interfaces):           │
            │  LLMProvider · EmbeddingProvider · STTProvider │
            │  TTSProvider · LiveVoiceProvider ·VisionProvider│
            │  VectorStore · RelationalStore · CacheStore    │
            │  FileSource · CalendarProvider · NotesProvider │
            │  MessagingGateway · BrowserDriver·DesktopDriver│
            └─────────┬──────────────────────────────────────┘
                      ▼
            ┌────────────────────────────────────────────────┐
 Providers  │ Groq │ Google AI │ Qdrant │ Postgres │ Redis   │   (driven adapters)
            │ Playwright │ pyautogui │ Telegram API │ AI-VFS │
            └────────────────────────────────────────────────┘
```

## 2. Layering Rules (enforced)

1. `core/` never imports from `adapters/`. Dependency direction is one-way: adapters → core ports.
2. Provider SDK types never cross a port boundary. Adapters translate to/from core domain types (e.g., `ChatMessage`, `ToolCall`, `EmbeddingVector`, `RetrievedChunk`).
3. Model names, connection strings, API keys exist only in configuration, read at composition time.
4. The composition root (`app/bootstrap.py`) is the only place adapters are instantiated and bound to ports.
5. Import-linter (or equivalent) CI rule guards rules 1–2 mechanically. See [TEST_STRATEGY.md](../testing/TEST_STRATEGY.md).

## 3. Ports (canonical list)

| Port | Responsibility | MVP adapter | Future swaps |
|---|---|---|---|
| `LLMProvider` | chat/completion, tool calling, streaming | `LiteLLMAdapter` — any LiteLLM provider, OSS or paid; Groq/Google is the default `free` profile (ADR-011, ADR-017) | swap by profile/config |
| `EmbeddingProvider` | text → vector | `LiteLLMAdapter` (gemini-embedding-001; fallbacks disabled) | BGE/local, Voyage — swap = re-embed migration |
| `STTProvider` | audio → text | `GroqWhisperAdapter` | Faster-Whisper local |
| `TTSProvider` | text → audio | `GeminiTTSAdapter` | Kokoro local |
| `LiveVoiceProvider` | bidirectional audio streaming | `GeminiLiveAdapter` | Moshi local |
| `VisionProvider` | image+prompt → analysis (VQA/OCR/detect) | `GoogleAIAdapter` (gemini-2.5-flash) | any LiteLLM vision model (GPT-4o, Claude, local llava); Qwen-VL + YOLO + PaddleOCR |
| `VectorStore` | upsert/search/delete vectors + payload | `QdrantAdapter` | pgvector, Chroma |
| `RelationalStore` | repositories for domain entities | `PostgresAdapter` (SQLAlchemy) | SQLite (dev) |
| `CacheStore` | KV, TTL, queues, session state | `RedisAdapter` | Valkey, in-memory (tests) |
| `FileSource` | unified read access to the knowledge mirror | `AiVfsAdapter` (+ source sync service), `LocalFsAdapter` | S3, GDrive |
| `WorkspaceStore` | versioned read-write agent workspace | `AiVfsAdapter` (namespace `workspace`) | local FS |
| `CalendarProvider` | CRUD events | `GoogleCalendarAdapter` | Outlook, CalDAV |
| `NotesProvider` | CRUD/search notes | `MarkdownFolderAdapter` | Obsidian REST, Notion |
| `MessagingGateway` | send/receive remote messages | `TelegramAdapter` | Matrix, Signal |
| `BrowserDriver` | navigate/click/fill/extract | `PlaywrightAdapter` | — |
| `DesktopDriver` | mouse/keyboard/window/screenshot | `PyAutoGuiAdapter` | OS-native |
| `Scheduler` | cron-like job registration | `ArqAdapter` — arq cron (ADR-012) | APScheduler, Celery beat |

Port signatures and domain types: defined in code under `core/ports/`; documented per area in the relevant doc (e.g., `LLMProvider` in [LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §4).

**Honesty note on "every port swaps freely":** the model ports are fully vendor-neutral (any LiteLLM provider, swap by config — ADR-017). The data ports swap behind their interfaces too, but two chosen *libraries* carry a backend assumption: the LangGraph checkpointer assumes Postgres, and arq assumes Redis. Replacing those backends means replacing (or reconfiguring) the library, not just the adapter — swappable in principle, with more friction than the model layer. Stated plainly rather than implied away.

## 4. The Model Routing Layer

Between agents and `LLMProvider` sits the **ModelRouter** (core service). Its provider leg is LiteLLM inside the adapter (ADR-011); the role semantics below are ours:

- Agents request a **role** (`CHAT`, `REASONER`, `CODER`, …), never a model name.
- The router resolves role → (provider, model, params) from the registry config, checks the quota budget, and falls back down the chain on rate limit or provider error.
- All calls pass through one choke point → uniform logging, token accounting, retries, and redaction hooks.

Detail: [LLM_STRATEGY.md](../ai/LLM_STRATEGY.md).

## 4a. The Shared Resource Layer (anti-bottleneck)

Distinct from ports (which front *external* systems), the **Shared Resource Layer** fronts *internal* read-only assets: skills ([SKILLS.md](../ai/SKILLS.md)), prompt templates ([PROMPTS.md](../ai/PROMPTS.md)), resources, the tool catalog, and the model registry.

Design (ADR-019):

- **Load-once, immutable, concurrently-readable.** Built at the composition root during bootstrap; never mutated at runtime. Any number of agents/tools read it simultaneously without locks.
- **No proxy hop.** The supervisor, every agent, and any model-using tool reach it *directly* — it is not owned by or served through the orchestrator. This is the core bottleneck fix for a multi-agent system: resource reads never serialize through one actor, and an agent can pull a skill the moment a subtask needs it.
- **Access ≠ authority.** Reading the layer is unrestricted; *acting* through a tool still passes the single permission gate ([TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md)). Fanning out access never fans out authorization.
- **Progressive disclosure** keeps it cheap in context: only skill/prompt *descriptions* are ambient; bodies load on selection.

The layer is the read-side complement to the ports: ports make external dependencies swappable; the resource layer makes internal know-how shared and fast.

## 5. Runtime Topology

Single-host Docker Compose (see [INFRASTRUCTURE.md](../infra/INFRASTRUCTURE.md)):

- `api` — FastAPI app: HTTP + WebSocket, LangGraph runtime in-process (MVP).
- `worker` — background jobs: ingestion, consolidation, scheduled automations (same image, different entrypoint).
- `postgres`, `redis`, `qdrant` — state.
- (Phase 8) `telegram-gateway` — long-polling bot process.

LangGraph state checkpoints to Postgres so conversations survive restarts ([LANGGRAPH.md](LANGGRAPH.md)).

## 6. Key Flows

Documented step-by-step in [WORKFLOWS.md](WORKFLOWS.md): chat turn, RAG answer, ingestion, voice note, agentic task with planning/reflection.

## 7. Error Handling & Degradation Policy

- Provider errors are caught at adapters and normalized to core exceptions: `RateLimited`, `ProviderUnavailable`, `ProviderRejected` (safety/content), `AdapterBug`.
- ModelRouter handles `RateLimited` → fallback chain → queue-or-fail-honestly.
- Agents must surface degraded answers explicitly ("answered without document search — vector store unreachable"), never silently skip a step.
- Every tool execution is wrapped in the permission + audit layer ([TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md)).

## 8. What This Architecture Optimizes For

1. **Swap-ability** — providers are leaves, not roots (the user's explicit #1 requirement). Any model vendor, OSS or paid, is config not code; the bootstrap capability gate makes the swap *safe*, not merely possible (ADR-017).
2. **No orchestrator bottleneck** — internal resources (skills, prompts, registries) are a shared, lock-free, directly-readable layer (§4a), not served through the supervisor; authority stays central while access fans out (ADR-019).
3. **Free-tier survival** — single choke point for quota management.
4. **Testability** — core runs entirely on fakes; adapter contract tests run against real services selectively.
5. **Incremental capability** — new agents/tools plug into the supervisor graph without core rewrites.

Trade-offs accepted: more upfront interface ceremony; one extra hop of indirection per call; single-host (no HA) by design.
