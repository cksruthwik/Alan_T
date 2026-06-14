# Alan_T — LangGraph Design

Version: 0.1
Status: Active

How Alan_T uses LangGraph: graph shapes, state, checkpointing, interrupts, and the boundary between LangGraph and the core.

## 1. Boundary Rule

LangGraph is the **orchestration adapter**, not the core. Agents implement the core `Agent` contract ([AGENTS.md](AGENTS.md) §2); a thin wrapper exposes each as a LangGraph node. If LangGraph were replaced, only `adapters/orchestration/` changes. Practically: no business logic inside node functions — nodes unpack state, call core, repack state.

## 2. Main Conversation Graph (Phase 1)

```
START
  └─▶ load_context          # session + relevant long-term memories
        └─▶ supervisor       # ROUTER model: classify intent
              ├─▶ conversation_agent ──▶ memory_hooks ─▶ respond ─▶ END
              ├─▶ file_agent ─────────▶ memory_hooks ─▶ respond ─▶ END
              ├─▶ memory_agent ───────▶ respond ─▶ END
              └─▶ clarify ────────────▶ respond ─▶ END
```

- `load_context` — assembles `AgentContext`: session window (Redis), recalled facts (Postgres), retrieval availability flags.
- `memory_hooks` — post-turn fact extraction (async fire-and-forget to the worker queue; never blocks the response).
- `respond` — streams tokens out over WebSocket/SSE.

New agents (Code, Vision, Browser…) are added as supervisor branches per phase — the graph shape doesn't change.

## 3. State Schema

```python
class ConversationState(TypedDict):
    session_id: str
    turns: Annotated[list[Turn], add_turns]   # reducer appends
    routed_agent: str | None
    agent_result: AgentResult | None
    recalled_memories: list[MemoryItem]
    pending_approval: ToolRequest | None      # set when interrupted
    degraded: list[str]                       # e.g. ["vector_store_down"]
```

Keep state minimal: large artifacts (retrieved chunks, transcripts, images) are stored via ports and referenced by ID in state, not embedded in it. Checkpoints must stay small and serializable.

## 4. Checkpointing

- **Checkpointer:** Postgres (`langgraph-checkpoint-postgres`), table `lg_checkpoints` — survives restarts, enables session resume and time-travel debugging.
- `thread_id` = `session_id`. One thread per conversation session.
- Redis is NOT used for checkpoints (it's for ephemeral session cache and queues) — one durable source of truth.

## 5. Interrupts: Human-in-the-Loop Approval

Tool calls at permission tier **ASK** ([TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md)) raise a LangGraph interrupt:

1. Node sets `pending_approval` and the graph pauses at the checkpoint.
2. API surfaces the approval request to the user (chat UI or Telegram inline button).
3. User decision resumes the thread with `approve` / `deny`; deny returns a structured refusal to the agent, which must adapt or report.

This is the only sanctioned mechanism for mid-task user input — no ad-hoc polling.

## 6. Agentic Task Graph (Phase 7)

Separate graph for autonomous tasks (not bolted onto the chat graph):

```
plan (Planner/REASONER) ─▶ execute_step ─▶ reflect (Reflection/REFLECTOR)
        ▲                                      │
        └────────── repair / replan ◀──────────┘   (bounded retries)
                            └─▶ done / give_up_with_report
```

- `execute_step` fans out to specialist agents per the task DAG.
- Reflection verdicts: `success` / `retry_same` / `replan` / `abort`. Retry budgets per step and per task — no unbounded loops ([REFLECTION_ENGINE.md](../ai/REFLECTION_ENGINE.md)).
- Long-running tasks checkpoint after every step; resumable after crash/restart.

## 7. Streaming

- `astream_events` drives token streaming to the client and progress events ("searching your notes…") to the UI.
- Voice mode consumes the same event stream; TTS begins on first sentence boundary, not on completion ([VOICE_ARCHITECTURE.md](../voice/VOICE_ARCHITECTURE.md)).

## 8. Testing the Graphs

- Unit: nodes tested as plain functions with fake `AgentContext`.
- Graph: compiled graph with in-memory checkpointer + fake model router (scripted responses) asserting routing and interrupt behavior.
- See [TEST_STRATEGY.md](../testing/TEST_STRATEGY.md) §4.
