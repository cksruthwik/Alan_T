# Alan_T — Agent Architecture

Version: 0.2
Status: Active — lean scope ([BUILD_ORDER.md](../BUILD_ORDER.md))

## 1. Topology: Supervisor with Specialist Agents

A single **Supervisor** owns intent classification and routing (from M3). Specialists own one capability each and expose a uniform contract. Agents do not call each other directly — composition happens through the Supervisor — keeping the graph debuggable.

Before M3 there is no Supervisor: the Conversation Agent is invoked directly. The Supervisor earns its place at M3 once there are 3+ agents to route between.

```
                         ┌──────────────┐
        user turn ──────▶│  SUPERVISOR  │◀────── Telegram / scheduled triggers
                         └──────┬───────┘
        ┌──────────┬───────────┼───────────┬──────────┐
        ▼          ▼           ▼           ▼          ▼
   Conversation  Memory      File        Notes     Calendar
                                                      
   (deferred, same contract): Browser · Reflection · Task Planning · Research · Automation
```

## 2. Agent Contract (the one early investment)

Every agent implements the same interface (core type, not LangGraph-specific). Getting this right at agent #1 is what makes agents #4–#10 cheap — each is then mostly "new prompt + new tools."

```python
class Agent(Protocol):
    name: str
    description: str          # used by supervisor for routing
    tools: list[ToolSpec]     # registered in TOOL_CATALOG, permission-gated

    async def run(self, task: AgentTask, ctx: AgentContext) -> AgentResult: ...
```

- `AgentTask` — the routed instruction + relevant conversation slice + any **skills the supervisor selected** for this turn (from M3 — [SKILLS.md](../ai/SKILLS.md)).
- `AgentContext` — injected shared services: the **LLM seam** (LiteLLM), **Memory** (Mem0), **Files** (ai-vfs), permission checker, and an injected **SKILLS layer** (empty until M3). Agents never construct adapters.
- `AgentResult` — `{response, tool_calls, handoff?, status}` where `status ∈ {ok, degraded, needs_approval}`, plus trace metadata.

Agents are built **skill-ready from M0** (the contract accepts the SKILLS layer) and **voice-ready** (input modeled as `IncomingMessage{text|audio|file}`; `audio` raises "not yet" until M6).

## 3. Roster (10-agent target, sequenced by milestone)

| Agent | Milestone | Responsibility | Spec |
|---|---|---|---|
| Conversation | M0 | general dialogue, follow-ups, tone | — (thin; lives in supervisor doc) |
| Memory | M1 | fact extraction, recall, forget requests (Mem0) | [MEMORY_AGENT.md](../agents/MEMORY_AGENT.md) |
| Telegram | M2 | remote text + file gateway | [../integrations/TELEGRAM.md](../integrations/TELEGRAM.md) |
| File | M2 | search/QA over ingested knowledge (RAG) | [FILE_AGENT.md](../agents/FILE_AGENT.md) |
| Supervisor | M3 | intent classification, routing, skill selection, clarification | [SUPERVISOR_AGENT.md](../agents/SUPERVISOR_AGENT.md) |
| Notes | M4 | note CRUD/search via NotesProvider | — (thin adapter wrapper) |
| Calendar | M4 | event CRUD via CalendarProvider | — (thin adapter wrapper) |
| **Deferred — still in the target:** | | | |
| Browser | after M4 | web navigation/extraction (Playwright) — highest fragility, build for a concrete task only | (archived in `Docs_COMPLEX/`) |
| Task Planning | later | goal → task DAG | (archived) |
| Reflection | later | outcome evaluation, plan repair — pairs with Task Planning | (archived) |
| Research | later | multi-source web research | (archived) |
| Automation | later | scheduled jobs, digests, goal tracking | (archived) |

**Dropped (for now):** Vision. All models are addressed through the one LiteLLM seam — agents request a model by config, not a role registry (ADR-020).

## 4. Routing Rules (from M3)

1. Supervisor classifies intent with a fast model via the LiteLLM seam: cheap, low-latency target.
2. Classification is constrained generation: choose an agent from registered names + `clarify` + `smalltalk`, **and** select zero or more skills from the description menu ([SKILLS.md](../ai/SKILLS.md)) — one decision, one model call.
3. Confidence below threshold → ask one clarifying question; never guess on action-taking intents.
4. Action-taking agents (Calendar writes, later Browser) additionally require permission-tier checks before execution — routing alone never grants execution rights ([TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md)).

## 5. Agent Design Rules

- One capability per agent. If an agent needs another's capability, that's a Supervisor decision, not an import.
- Agents are stateless between invocations; all state lives in memory systems or LangGraph checkpoints.
- Agents read the SKILLS layer directly — never through the Supervisor. Reads are free; tool *execution* is still permission-gated.
- Every agent declares its tools up front; undeclared tool use is impossible (registry-enforced).
- Every agent result carries trace metadata (model calls, tools used, tokens) for the audit log and metrics.
- Failure is a first-class result: agents return structured failure (cause, retryable?) rather than raising through the graph.

## 6. Graph Implementation

LangGraph wiring, state schema, checkpointing, and interrupt (human-approval) mechanics: [ORCHESTRATION.md](ORCHESTRATION.md).
