# Alan_T — Skill System

Version: 0.1
Status: Active (implementation: Phase 1 minimal, expands through Phase 7)
Governing decision: ADR-018 in [DECISION_LOG.md](../architecture/DECISION_LOG.md)

The unit of **reuse** in Alan_T. A skill packages know-how — instructions + the tools it needs + optional scripts — so the orchestrator can apply it on demand without that knowledge being welded into an agent or scattered across prompts. Modeled on Claude Agent Skills (SKILL.md + progressive disclosure).

## 1. What a Skill Is (and what it is not)

| Primitive | Is | Lifetime / scope |
|---|---|---|
| **Agent** | a routing target with a persona + a tool grant | long-lived; supervisor picks exactly one per turn |
| **Tool** | a single permission-gated function call | per-call |
| **Prompt template** | instruction text for one model call | per-call |
| **Skill** | a packaged, reusable capability: trigger + instructions + required tools + optional scripts | loaded on demand, reused across agents |
| **MCP server** | an external process exposing tools/resources | external; its tools enter the registry |

A skill sits **above tools** (it orchestrates several) and is **more reusable than an agent** (many agents can apply the same skill; a skill is a capability, not a persona). It is the home for "reusable multi-step workflow X" that none of the other primitives fit cleanly.

## 2. Skill Anatomy

A skill is a versioned directory, mirroring Claude Agent Skills:

```
core/skills/
  react_interview_prep/
    SKILL.md          # metadata + instruction body
    scripts/          # optional helpers (run ONLY in the sandboxed executor)
    resources/        # optional checklists, templates, reference snippets
```

`SKILL.md` frontmatter + body:

```markdown
---
name: react_interview_prep
description: >
  Build a study plan for a React interview from the user's notes and calendar.
  Use when the user asks to prepare/study for a React (or frontend) interview.
  NOT for general "explain React" questions — that's the Code agent directly.
required_tools: [search_knowledge, read_source, calendar_read, calendar_write, set_reminder]
role_hint: REASONER          # which model role the skill's reasoning wants
version: 1
---

1. Gather existing React notes via search_knowledge (topics: hooks, rendering, state…).
2. Identify gaps against a standard topic checklist (resources/topics.md).
3. Draft a day-by-day plan sized to the interview date.
4. Propose calendar blocks (calendar_write is ASK-tier — user confirms).
5. Set reminders for each session.
```

- **`description`** is the **trigger** — the only part always in context (§3). Write it like a tool description: what it's for, when to use, when NOT.
- **`required_tools`** must all be registered ([TOOL_CATALOG.md](TOOL_CATALOG.md)) and within the executing agent's grant. The skill cannot name a tool the agent isn't allowed.
- **`role_hint`** lets a skill request a stronger model role (e.g. REASONER) for its turn.
- **Body** is a Jinja2 template like any other prompt; it may reference context vars.

## 3. The Shared Resource Layer & Progressive Disclosure (the efficiency property)

Skills are **not owned by the orchestrator**. They live in the **Shared Resource Layer** alongside prompt templates, resources, the tool catalog, and the model registry (ADR-019, [ADD.md](../architecture/ADD.md) §4a): **loaded once at startup, immutable at runtime, concurrently readable — no locks, no proxy hop through the supervisor — by the supervisor, every agent, and any model-using tool.** Decentralizing access is the bottleneck fix: a multi-agent system must never serialize resource reads through one actor, and an agent must be able to reach a skill directly when a subtask needs it.

**Progressive disclosure** is the token-efficiency layer on top: at any selection point only each skill's `name` + `description` is in context (a cheap menu); a skill's full body and resources load **only when selected** — fifty skills cost fifty one-line descriptions until one fires. Descriptions must therefore be tight and discriminative.

**Access is not authority** (ADR-019): any agent or tool may *read* the layer freely, but *acting* through a tool a skill names still passes the permission gate (§5). Fanning out access never fans out authorization.

## 4. Selection: Two Deliberate Levels (never ambient)

Selection — *deciding a skill fires* — is owned, and happens at exactly two levels. Neither is ambient self-activation:

**Level 1 — supervisor at routing time (the common path).** In one routing decision the supervisor selects the agent **and** the relevant skill(s) from the description menu ([SUPERVISOR_AGENT.md](../agents/SUPERVISOR_AGENT.md)):

```
supervisor (ROUTER model) → { agent, skills: [...], confidence, task_summary }
   → load selected skill bodies + resources from the shared layer
   → inject as the SKILLS layer of the executing agent's prompt (PROMPTS §2)
   → agent runs with the skill's instructions + the union of its required_tools (still gated)
```

**Level 2 — an agent mid-turn (the deep-agent path).** When a subtask reveals a need the router couldn't foresee, the executing agent **deliberately** pulls an additional skill from the shared layer (it has direct read access — §3) and layers it into its own prompt. This is an explicit, owned request, not a background match.

**Still excluded:** an *ambient* skill layer that self-activates with no owner, racing the router for control of a turn (the ADR-018 hazard). Adding a second *deliberate* selector is not that. Most turns select zero skills at either level — selecting none is the common, correct case, and selection has a relevance threshold (a weak match adds nothing rather than forcing a skill; a misfire is the analogue of a misroute).

## 5. Composes Tools, Never Escalates

A skill **orchestrates** tools; it does not bypass them. This is the hard line that makes decentralized *access* (§3) safe: read freely, act gated.

- Every tool a skill invokes passes the permission gate at execution time, exactly as if the agent called it directly ([TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md)). A skill that uses `calendar_write` still triggers the ASK interrupt. This holds no matter which selection level (§4) pulled the skill — the gate is the single authority choke even though access fans out (ADR-019).
- `required_tools` must be a **subset of the executing agent's grant** — a skill can never widen what an agent is allowed to do. Bootstrap rejects a skill whose tools aren't registered; routing won't pair a skill with an agent that lacks its tools.
- Bundled `scripts/` run **only in the sandboxed executor** (ai-vfs Monty, when available — [AI_VFS.md](../knowledge/AI_VFS.md) §4): VFS callbacks only, no host shell, budget-capped. Never the DENY'd `shell_exec`.
- Skills may declare **MCP-provided tools** ([MCP.md](../integrations/MCP.md)); those enter the registry and are gated like any tool. A skill is the natural consumer of an MCP server's toolset.

## 6. Reuse by the Planner (Phase 7)

A plan step can be **"apply skill X"** — skills are the concrete realization of the plan-pattern reuse flagged in [PLANNING_ENGINE.md](PLANNING_ENGINE.md) §7. The Planner sees the same description menu and can compose skills into a task DAG; a successful ad-hoc plan can later be distilled into a skill (authoring is human-reviewed — §8). This is how the system's know-how compounds without bloating any single agent.

## 7. Skills vs. Modular Prompts

Skills **generalize** the prompt-template system ([PROMPTS.md](PROMPTS.md)) upward, they don't replace it:

- A per-agent task template (`rag_answer.j2`) is the agent's *baseline* behavior — always present for that agent.
- A skill is *selective, reusable, cross-agent* know-how layered in when relevant, carrying its own tool requirements and optional scripts.

Both are versioned Jinja2 artifacts under the same change discipline (§8). A skill body may itself include or compose templates.

## 8. Lifecycle: Authoring, Versioning, Eval

- **First-party, in-repo, reviewed like code.** Skills are not user-uploaded at MVP (no marketplace, no runtime upload) — that's a trust/injection boundary, deferred ([SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md) §6).
- **Versioned artifacts**: `version` in frontmatter; a description change re-runs the **skill-selection eval** (did the right skill fire for representative utterances, and did the wrong one stay quiet?) — a sibling of the router eval ([TEST_STRATEGY.md](../testing/TEST_STRATEGY.md) §5).
- **Quality bar:** descriptions must be discriminative (overlapping triggers cause misfires, the skill analogue of router misroutes); `required_tools` must be honest (the validator rejects undeclared tool use inside a skill, like the plan validator rejects fabricated tools).

## 9. What Skills Are Not (MVP)

- Not user-uploaded or a marketplace — first-party only.
- Not self-authoring — the assistant doesn't write its own skills yet (backlog).
- Not a replacement for agents (personas/routing) or tools (gated calls).
- Not an *ambient* trigger layer — selection happens at two **deliberate**, owned levels (supervisor routing + agent mid-turn, §4), never a background match that self-fires with no owner.
- Not a privilege path — decentralized read access never widens what a tool call is authorized to do (§5, ADR-019).

## 10. Relationship to Claude Agent Skills

Directly modeled on the SKILL.md + progressive-disclosure pattern Alan_T's own builders use in Claude Code. Adapted for this system: **orchestrator-selected** rather than ambiently self-triggering, **permission-gated** tool use, and **planner-reusable** as plan building blocks. The familiarity is intentional — authoring an Alan_T skill should feel like authoring a Claude skill.

## 11. Phasing

- **Phase 1:** registry + progressive disclosure + supervisor selection + prompt injection; a handful of seed skills (e.g. a digest-composition skill, a note-summarization skill).
- **Phase 3+:** code-workflow skills (repo onboarding, dependency audit).
- **Phase 7:** planner composition of skills; distilling successful plans into reviewed skills.
- **Backlog:** self-authoring, user-defined skills with a sandbox/trust model.
