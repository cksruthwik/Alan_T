# Alan_T — Agent Architecture

Version: 0.1
Status: Active

## 1. Topology: Supervisor with Specialist Agents

A single **Supervisor** owns intent classification and routing. Specialists own one capability each and expose a uniform contract. Agents do not call each other directly — composition happens through the supervisor (or through an explicit plan in Phase 7), keeping the graph debuggable.

```
                         ┌──────────────┐
        user turn ──────▶│  SUPERVISOR  │◀────── scheduled triggers
                         └──────┬───────┘
        ┌───────┬───────┬───────┼───────┬───────┬───────┐
        ▼       ▼       ▼       ▼       ▼       ▼       ▼
   Conversation File   Code  Vision  Browser Desktop Calendar
        ▼       ▼       ▼       ▼       ▼       ▼       ▼
      Notes  Research Memory Automation Reflection  (Phase 7+)
```

## 2. Agent Contract

Every agent implements the same interface (core type, not LangGraph-specific):

```python
class Agent(Protocol):
    name: str
    description: str          # used by supervisor for routing
    tools: list[ToolSpec]     # registered in TOOL_CATALOG, permission-gated

    async def run(self, task: AgentTask, ctx: AgentContext) -> AgentResult: ...
```

- `AgentTask` — the routed instruction + relevant conversation slice + any **skills the supervisor selected** for this turn ([SKILLS.md](../ai/SKILLS.md)).
- `AgentContext` — injected ports (ModelRouter, VectorStore, …), memory snapshot, permission checker, the loaded bodies of supervisor-selected skills (injected into prompt assembly), and **direct read access to the Shared Resource Layer** ([ADD.md](ADD.md) §4a) so the agent can pull an additional skill/prompt mid-turn when a subtask reveals the need (Level-2 selection — [SKILLS.md](../ai/SKILLS.md) §4). Agents never construct adapters.
- `AgentResult` — answer/artifacts + `degraded: bool` + trace metadata.

## 3. Roster

| Agent | Phase | Responsibility | Primary model role | Spec |
|---|---|---|---|---|
| Supervisor | 1 | intent classification, routing, clarification | ROUTER | [SUPERVISOR_AGENT.md](../agents/SUPERVISOR_AGENT.md) |
| Conversation | 1 | general dialogue, follow-ups, tone | CHAT | — (thin; lives in supervisor doc) |
| Memory | 1 | fact extraction, recall, forget requests | SUMMARIZER | [MEMORY_AGENT.md](../agents/MEMORY_AGENT.md) |
| File | 1 | search/QA over ingested knowledge (RAG) | CHAT + LONG_CONTEXT | [FILE_AGENT.md](../agents/FILE_AGENT.md) |
| Code | 3 | repo search, explanation, generation | CODER | [CODE_AGENT.md](../agents/CODE_AGENT.md) |
| Vision | 4 | image/screenshot/camera QA, OCR | VISION | [VISION_AGENT.md](../agents/VISION_AGENT.md) |
| Browser | 5 | web navigation and extraction | REASONER + VISION | [BROWSER_AGENT.md](../agents/BROWSER_AGENT.md) |
| Desktop | 6 | mouse/keyboard/window automation | REASONER + VISION | — (spec with Phase 6) |
| Calendar | 2+ | event CRUD via CalendarProvider | CHAT | — (thin adapter wrapper) |
| Notes | 2+ | note CRUD/search via NotesProvider | CHAT | — (thin adapter wrapper) |
| Research | 3+ | multi-source web research | WEB_AGENT (groq/compound) | — |
| Automation | 7 | scheduled jobs, digests, goal tracking | SUMMARIZER | [AUTOMATION_AGENT.md](../agents/AUTOMATION_AGENT.md) |
| Planner | 7 | goal → task DAG | REASONER | [PLANNING_ENGINE.md](../ai/PLANNING_ENGINE.md) |
| Reflection | 7 | outcome evaluation, plan repair | REFLECTOR | [REFLECTION_ENGINE.md](../ai/REFLECTION_ENGINE.md) |

Model roles resolve via the registry — see [LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §3.

## 4. Routing Rules

1. Supervisor classifies with ROUTER (llama-3.1-8b-instant): cheap, < 300 ms target.
2. Classification is constrained generation: choose an agent from registered names + `clarify` + `smalltalk`, **and** select zero or more skills from the description menu ([SKILLS.md](../ai/SKILLS.md) §4) — one decision, one model call.
3. Confidence below threshold → ask one clarifying question, never guess on action-taking intents.
4. Action-taking agents (Browser, Desktop, Calendar writes) additionally require permission-tier checks before execution — routing alone never grants execution rights ([TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md)).
5. Multi-capability requests (Phase 7): supervisor delegates to Planner, which emits a task DAG executed across agents.

## 5. Agent Design Rules

- One capability per agent. If an agent needs another's capability, that's a plan, not an import.
- Agents are stateless between invocations; all state lives in memory systems or LangGraph checkpoints.
- Agents read the Shared Resource Layer directly (skills, prompts, resources) — never through the supervisor. This keeps a multi-agent run from serializing on the orchestrator and lets an agent compose a skill mid-task. Reads are free; tool *execution* by that agent is still gated (ADR-019).
- Every agent declares its tools up front; undeclared tool use is impossible (registry-enforced).
- Every agent result carries trace metadata (model calls, tools used, tokens) for the audit log and metrics.
- Failure is a first-class result: agents return structured failure (cause, retryable?) rather than raising through the graph.

## 6. Graph Implementation

LangGraph wiring, state schema, checkpointing, and interrupt (human-approval) mechanics: [LANGGRAPH.md](LANGGRAPH.md).
