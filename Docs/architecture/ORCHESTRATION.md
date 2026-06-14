# Alan_T — Orchestration & Workflows

Version: 0.2
Status: Active — consolidated from LangGraph design + core workflows

How Alan_T orchestrates agents and flows: LangGraph integration, state management, checkpointing, interrupts, and the step-by-step sequences for key operations.

## 1. Orchestration: LangGraph Integration

### 1.1 Boundary Rule

LangGraph is the **orchestration adapter**, not the core. Agents implement the core `Agent` contract ([AGENTS.md](AGENTS.md) §2); a thin wrapper exposes each as a LangGraph node. If LangGraph were replaced, only `adapters/orchestration/` changes. Practically: no business logic inside node functions — nodes unpack state, call core, repack state.

### 1.2 Main Conversation Graph (M0–M4)

```
START
  └─▶ load_context          # session + relevant long-term memories
        └─▶ supervisor       # ROUTER model: classify intent + select skills
              ├─▶ conversation_agent ──▶ memory_hooks ─▶ respond ─▶ END
              ├─▶ file_agent ─────────▶ memory_hooks ─▶ respond ─▶ END
              ├─▶ memory_agent ───────▶ respond ─▶ END
              ├─▶ notes_agent ────────▶ respond ─▶ END
              ├─▶ calendar_agent ─────▶ respond ─▶ END
              └─▶ clarify ────────────▶ respond ─▶ END
```

- `load_context` — assembles `AgentContext`: session window (Postgres), recalled facts (Postgres), retrieval availability flags.
- `supervisor` — routes to the best agent + selects relevant skills from the catalog (progressive disclosure; only description in context until selected).
- `memory_hooks` — post-turn fact extraction (async fire-and-forget; never blocks the response).
- `respond` — streams tokens out over HTTP/WebSocket/Telegram.

New agents (Browser, etc.) are added as supervisor branches per milestone — the graph shape doesn't change.

### 1.3 State Schema

```python
class ConversationState(TypedDict):
    session_id: str
    turns: Annotated[list[Turn], add_turns]   # reducer appends
    routed_agent: str | None
    agent_result: AgentResult | None
    recalled_memories: list[MemoryItem]
    pending_approval: ToolRequest | None      # set when interrupted
    degraded: list[str]                       # e.g. ["memory_recall"]
```

Keep state minimal: large artifacts (retrieved chunks, images) are stored via ports and referenced by ID in state, not embedded in it. Checkpoints must stay small and serializable.

### 1.4 Checkpointing

- **Checkpointer:** Postgres, table `lg_checkpoints` — survives restarts, enables session resume.
- `thread_id` = `session_id`. One thread per conversation session.
- Checkpoints record every node transition; durable source of truth.

### 1.5 Interrupts: Human-in-the-Loop Approval

Tool calls at permission tier **ASK** raise a LangGraph interrupt:

1. Node sets `pending_approval` and the graph pauses at the checkpoint.
2. API surfaces the approval request to the user (chat UI or Telegram inline button).
3. User decision resumes the thread with `approve` / `deny`; deny returns a structured refusal to the agent.

This is the only sanctioned mechanism for mid-task user input.

### 1.6 Streaming

- `astream_events` drives token streaming to the client and progress events ("searching your notes…") to the UI.
- Voice mode (M6) consumes the same event stream; TTS begins on first sentence boundary, not on completion.

### 1.7 Testing the Graphs

- Unit: nodes tested as plain functions with fake `AgentContext`.
- Graph: compiled graph with in-memory checkpointer + scripted responses asserting routing and interrupt behavior.
- See [TEST_STRATEGY.md](../testing/TEST_STRATEGY.md) §4.

---

## 2. Core Workflows

Step-by-step sequences for the system's main operations. These are the flows tests assert against.

### W1 — Chat Turn (M0)

1. Client sends message (HTTP POST/WebSocket) with `session_id`.
2. API normalizes to `UserTurn`, appends to session.
3. `load_context`: recall top-k relevant long-term memories (Postgres, keyword + recency + embedding similarity).
4. Supervisor classifies intent (ROUTER model via LiteLLM).
5. Routed agent runs; any model call goes ModelRouter → quota check → provider adapter (LiteLLM fallback chain).
6. Response streams to client; first token target < 1.5 s.
7. Turn persisted to Postgres; fact-extraction job enqueued (background) — does not block.
8. LangGraph checkpoint written.

**Degradation:** memory recall fails → proceed, flag `degraded:["memory_recall"]`, tell the user only if it affects the answer.

### W2 — RAG Answer (M2)

1. File Agent receives question.
2. Query rewrite (optional): conversational query → standalone search query.
3. Hybrid retrieval: pgvector vector search (via Gemini embeddings) + keyword search, merged via RRF. Top 8 after merge.
4. Answer generation (CHAT or LONG_CONTEXT model) with mandatory citation instruction.
5. Citations rendered as `source_path#chunk` links; uncited claims about user documents are a defect.
6. If retrieval returns nothing relevant: say so explicitly — never improvise an answer about the user's files.

Full pipeline detail: [../knowledge/KNOWLEDGE.md](../knowledge/KNOWLEDGE.md).

### W3 — Document Ingestion (M2)

1. Trigger: watcher event (file added/changed), manual `POST /ingest`, or scheduled re-scan.
2. Worker pulls job from background queue.
3. AI-VFS resolves source → raw content + metadata.
4. Content hash checked against `ingest_ledger` (Postgres) — unchanged content is skipped (quota protection).
5. Parse (per type) → chunk → embed (batched, rate-limit-aware via LiteLLM fallback) → upsert to pgvector.
6. Ledger updated; deleted source files trigger vector deletion.

Full pipeline: [../knowledge/KNOWLEDGE.md](../knowledge/KNOWLEDGE.md).

### W4 — Voice Note (M6)

1. Audio arrives (web upload or Telegram voice note).
2. STT: Whisper (Groq) → transcript.
3. Transcript enters W1 as a normal user turn (tagged `modality:voice`).
4. Reply → TTS (Gemini) → audio returned alongside text.
5. Both transcript and reply text persist to conversation history.

### W5 — Live Voice (M6, deferred)

1. Client opens WebSocket `/voice/live`; server bridges to Gemini Live API session.
2. Server injects context (persona prompt + recalled memories) at session start.
3. Tool calls from the live session route through the same permission layer as text.
4. Session transcript captured and persisted on close; fact extraction runs on it.

### W6 — Memory Extraction (M1, async)

1. Turn completed; fact-extraction job enqueued.
2. Worker processes the turn + response through extraction model (SUMMARIZER).
3. Structured facts (preferences, goals, project context) extracted with confidence scores.
4. Stored to `memory_items` table (Postgres) with recency decay for recall ranking.
5. Low-confidence items flagged for user review before use in recall.

### W7 — Note / Calendar Operations (M4)

1. User: "Add a 3pm meeting tomorrow" or "Note: I prefer TypeScript."
2. Supervisor routes to Notes Agent or Calendar Agent.
3. Agent calls tool: write Markdown note to `workspace` namespace (ai-vfs) or CRUD via Google Calendar API.
4. Tool result confirmed to user; persisted and indexed (notes are ingested like documents).

---

## 3. Architectural Constraints

- **One model seam:** All LLM calls go through ModelRouter → LiteLLM adapter → three-provider fallback chain (Groq, Google, NVIDIA NIM).
- **No provider SDKs in core:** Only the LiteLLM adapter uses provider-specific code; the core sees only the generic interface.
- **Orchestration adapter only:** LangGraph is replaceable; no business logic in node functions.
- **State is minimal:** Large artifacts stored in databases and referenced by ID, not embedded in checkpoints.
