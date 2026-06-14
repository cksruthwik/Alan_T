# Supervisor Agent

Milestone: **M3** (routing earns its place once there are 3+ agents) · Model purpose: `ROUTER` (`llama-3.1-8b-instant` → `gemini-2.5-flash-lite`)
Framework context: [AGENTS.md](../architecture/AGENTS.md), [ORCHESTRATION.md](../architecture/ORCHESTRATION.md) §1.2

## Responsibility

Entry node of every conversation graph turn (from M3): classify intent, route to exactly one specialist (or clarify), **select any relevant skill(s) from the shared catalog**, and strip the dispatched agent's tool set to the task's minimum. The Supervisor never answers content questions itself. It is the **primary** skill selector (Level 1, the common path), **not the sole one and not a resource gatekeeper**: agents read the SKILLS layer directly and may pull additional skills mid-turn (Level 2 — [SKILLS.md](../ai/SKILLS.md) §4, ADR-019). What stays excluded is *ambient* skill self-activation with no owner.

Before M3 there is no Supervisor — the Conversation Agent is invoked directly.

## Classification Contract

- Template `router.j2`, temperature 0, JSON mode: `{"agent": <label>, "skills": [<skill_name>...], "confidence": 0..1, "task_summary": <one line>}`.
- Label set = registered agents for the current milestone + `smalltalk` + `clarify`. The set is injected from the agent registry at prompt-assembly time — enabling a new agent automatically extends routing, no prompt edit.
- The **skill menu** (each skill's `name` + `description`, nothing more — progressive disclosure, [SKILLS.md](../ai/SKILLS.md) §3) is injected the same way. `skills` is usually empty; selecting none is the common, correct case.
- `smalltalk` short-circuits to the Conversation agent with no tools and no skills (cheapest path for greetings/chitchat).

## Routing Rules

1. `confidence < 0.6` on an action-taking intent (calendar write / ingest) → `clarify`, one question max. Read-only intents may proceed at lower confidence — wrong answers there cost a correction, not an action.
2. Multi-intent messages: route the primary intent; mention the deferred one in the response ("done X; want me to also Y?"). When the Task Planning Agent exists (deferred), route goal-shaped requests there instead.
3. Goal-shaped requests ("prepare me for…", "organize my…") → honest decline + the pieces it CAN do now, until the Planner is built.
4. Follow-ups inherit the previous turn's agent unless the new message clearly switches domains (router sees a 2-turn window).
5. **Tool stripping:** the dispatch carries only the routed agent's declared tools intersected with what `task_summary` needs, **plus** any `required_tools` of selected skills (which must already be a subset of the agent's grant — [SKILLS.md](../ai/SKILLS.md) §5) — injection blast-radius control ([SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md)).
6. **Skill selection:** match against the description menu; a weak match selects no skill rather than forcing one (a misfired skill is the analogue of a misroute). Never pair a skill with an agent lacking its `required_tools`. Selected skill bodies load and inject into the agent's prompt ([PROMPTS.md](../ai/PROMPTS.md) §2).

## Failure Modes & Handling

| Failure | Handling |
|---|---|
| Router model rate-limited | LiteLLM fallback chain; if exhausted → default route to Conversation agent (never block a turn on routing) |
| Invalid JSON / unknown label | one repair retry → default to Conversation agent, log `router_misroute` metric |
| Systematic misroutes (eval set) | fix `router.j2` examples; the eval set (~50 labeled utterances) gates router prompt changes ([TEST_STRATEGY.md](../testing/TEST_STRATEGY.md)) |
| Skill misfire (wrong skill fires / right one stays quiet) | sharpen the offending skill `description`; the skill-selection eval gates skill description changes ([SKILLS.md](../ai/SKILLS.md) §8) |

## Explicitly Not the Supervisor's Job

Planning (the deferred Planner's), answering (specialists'), permission decisions (the gate's, [TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md)), memory writes (Memory agent's).
