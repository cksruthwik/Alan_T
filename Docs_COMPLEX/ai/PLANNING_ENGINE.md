# Alan_T — Planning Engine

Version: 0.1
Status: Active (implementation: Phase 7)

Turns a user goal into an executable, inspectable task DAG. Pairs with [REFLECTION_ENGINE.md](REFLECTION_ENGINE.md) for the execute–evaluate loop.

## 1. Position in the System

```
goal ─▶ PLANNER (REASONER model) ─▶ task DAG ─▶ approval gate ─▶ EXECUTOR
                                                                    │ per step
                                                              REFLECTION ENGINE
                                                                    │ verdicts
                                              next / retry / replan / abort
```

Planning runs in the agentic task graph ([LANGGRAPH.md](../architecture/LANGGRAPH.md) §6), not the chat graph. The chat supervisor routes to it when intent = multi-step goal.

## 2. Plan Schema

```json
{
  "goal": "Prepare for React interview on 2026-07-01",
  "success_criteria": ["study plan exists", "sessions scheduled", "notes compiled"],
  "tasks": [
    {
      "id": "t1",
      "title": "Gather existing React notes",
      "agent": "file_agent",
      "tools": ["search_knowledge", "read_source"],
      "inputs": {"query": "React hooks, rendering, state management"},
      "success_check": "≥1 relevant note found OR explicit empty result",
      "depends_on": [],
      "risk": "none"
    },
    {
      "id": "t3",
      "title": "Schedule study sessions",
      "agent": "calendar_agent",
      "tools": ["calendar_read", "calendar_write"],
      "depends_on": ["t2"],
      "risk": "external_action"
    }
  ],
  "max_replans": 2
}
```

Schema-validated (Pydantic) before anything executes. Invalid plan → one repair attempt with the validation errors → fail honestly.

## 3. Planner Rules (encoded in `plan.j2`)

1. Every task names a **registered agent** and only tools in that agent's scope ([TOOL_CATALOG.md](TOOL_CATALOG.md)) — the validator rejects fabricated tools (the model WILL invent tools otherwise).
2. Every task has a machine-checkable-ish `success_check` the Reflection engine can evaluate.
3. Tasks with `risk: external_action` are surfaced in the approval gate even if individual tools are ALLOW-tier.
4. Prefer fewer, larger tasks (3–8 typical). A 25-step plan is a planning failure.
5. Plans declare what they DON'T cover when the goal is ambiguous, instead of guessing scope.

## 4. Approval Gate

- Plan rendered to the user (chat or Telegram) as a checklist with risk flags.
- Any ASK-tier tool or `external_action` risk → plan requires explicit approval before execution (LangGraph interrupt).
- Pure-read plans (search/summarize) auto-execute; the plan is still shown.

## 5. Execution Semantics

- Topological order; independent branches may run concurrently (bounded: 2 parallel steps to respect quota).
- Each step gets a fresh `AgentTask` with: its inputs, outputs of dependencies, and the goal context.
- Step timeout per `risk` class; results (incl. structured failures) go to Reflection.
- Budgets: ≤2 retries per step, ≤2 replans per task run, global token budget per plan (config). Exhausted → abort with a completed-so-far report. **No unbounded loops, ever.**
- State checkpoints after every step → resumable after restart.

## 6. Replanning

Reflection verdict `replan` returns to the Planner with: original plan, step outcomes so far, failure analysis. The planner amends the *remaining* DAG only — completed work is never re-executed (idempotency guard via step result ledger).

## 7. What the MVP-era Planner Is Not

- Not a general agent swarm — single plan, supervised execution.
- Not self-extending — it cannot add tools or agents to the registry.
- Not learning (yet) — plan quality improvements come from prompt/eval iteration; pattern reuse from past successful plans is realized as **skills** ([SKILLS.md](SKILLS.md) §6): a plan step can be "apply skill X", and a successful ad-hoc plan can be distilled into a reviewed skill so the know-how compounds without bloating any agent.
