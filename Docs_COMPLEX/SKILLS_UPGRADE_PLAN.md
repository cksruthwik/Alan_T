# Alan_T — Skills Upgrade Plan

Status: proposal · Date: 2026-07-07
Companion to [ai/SKILLS.md](ai/SKILLS.md) (the design) and [AS_BUILT.md](AS_BUILT.md) (the ledger).
Goal: close every gap between the SKILLS.md design and the code, then grow the
catalog from 5 seed skills to a full personal-assistant skill set — consumable
by the supervisor (routing), every agent (mid-turn), the planner (plan steps),
and external clients (MCP).

---

## 0. As-built baseline (verified in code, 2026-07-07)

Already working — do not rebuild:

| Piece | Where |
|---|---|
| `SkillLibrary`: SKILL.md dirs, frontmatter parse, availability skip (missing tools → skill not offered) | `alan_t/core/skills/__init__.py` |
| Progressive disclosure: `menu()` (1 line/skill) vs `render()` (full bodies on selection) | same |
| Level-1 selection: one ROUTER call picks agent + skills, heuristic fallback | `alan_t/core/agents/supervisor.py` |
| Injection: `task.skills` → SKILLS layer of the agent prompt | `alan_t/app/chat_service.py:77-78`, `alan_t/core/agents/tool_agent.py:67` |
| MCP exposure: `list_skills` / `get_skill` | `alan_t/mcp_host/server.py` |
| 5 seed skills | email_triage, image_analysis, memory_recap, note_summarization, schedule_block |

Designed in SKILLS.md but **not implemented** — this plan's Phases A–D:

1. `required_tools ⊆ executing agent's grant` is asserted in docstrings, enforced nowhere.
2. `role_hint` is parsed and then ignored — a skill can't request a stronger model.
3. Level-2 selection (agent pulls a skill mid-turn) has no mechanism: `ctx.skills` exists but no tool exposes it to the loop.
4. `resources/` and `scripts/` are never loaded — only the SKILL.md body.
5. The planner never sees the skill menu; a plan step can't say "apply skill X".
6. No skill-selection eval; no skill-usage metric.

---

## Phase A — Harden what exists (small diffs, do first)

### A1. Enforce the grant-subset rule at routing
`Supervisor.route()` currently returns any skill the router names, even if the
chosen agent can't call its tools. One filter after the decision parse:

```python
agent_grant = set(getattr(self._agents[name], "grant", [])) or None
skill_names = [s for s in skill_names
               if agent_grant is None
               or set(self._skills.get(s).required_tools) <= agent_grant]
```

(`grant is None` covers ConversationAgent/FileAgent if they don't expose one —
verify their shape first.) Log the drops; a dropped skill is a router-quality
signal. **Files:** `supervisor.py`. **Test:** route a schedule_block utterance
to the notes agent → skill silently dropped.

### A2. Honor `role_hint`
A skill that says `role_hint: REASONER` should upgrade the turn's model role.
In `ToolAgent.run`, take the max of the agent's role and the selected skills'
hints (ordering: CHAT < SUMMARIZER < CODER < REASONER — confirm against
`config/models.yaml` roles). Requires passing selected skill *names* (not just
rendered bodies) on `AgentTask` — add `task.skill_names: list[str]`.
**Files:** `types.py`, `chat_service.py`, `tool_agent.py`.

### A3. Skill-usage observability
One Prometheus counter next to `AGENT_TURNS`:
`SKILL_SELECTIONS.labels(skill=..., level=("router"|"midturn"|"plan")).inc()`.
Without this you cannot tell dead skills from load-bearing ones, and the
catalog (Phase E) will rot. **Files:** `observability.py`, `chat_service.py`.

### A4. Skill-selection eval (the router-eval sibling)
A table-driven pytest: representative utterances → expected skill (or none).
Two modes:
- **Unit (always runs):** assert menu hygiene — every description has a
  trigger + a NOT clause, no two descriptions share their first 6 content
  words (cheap overlap lint), frontmatter parses, `required_tools` all exist
  in the catalog.
- **e2e (needs a live ROUTER key, marked):** feed each utterance through
  `Supervisor.route` and assert the right skill fires and — as important —
  that the wrong one stays quiet. Seed set: 3 positive + 2 negative
  utterances per skill, stored as `tests/fixtures/skill_selection.yaml` so
  adding a skill means adding fixture lines, not test code.

**Definition of done for Phase A:** a skill misfire is visible (metric + eval),
impossible to escalate (A1), and able to buy better reasoning (A2).

---

## Phase B — Level-2 selection: the `use_skill` tool

The deep-agent path from SKILLS.md §4: an agent discovers mid-turn that a
packaged workflow applies. Mechanism — one ALLOW-tier, read-only tool,
registered in bootstrap and appended to **every** agent's granted specs:

```
use_skill(name) → the skill's full instruction body
```

- Returns the body only if `required_tools ⊆ this agent's grant`; otherwise a
  one-line refusal naming the missing tools (so the model stops asking).
  Implementation: the tool needs the calling agent's grant — thread it via the
  tool call (bootstrap closure can't know the caller), simplest is for
  ToolAgent to special-case `use_skill` in its loop rather than routing it
  through the registry. That also keeps it out of `permissions.yaml`.
- The agent prompt template gains one conditional block: *"Reusable skills you
  can pull with use_skill (only when one clearly applies):"* + `skills.menu()`.
  Cost: one line per skill in every agentic turn — this is the progressive-
  disclosure price and it's the cheap one.
- Count it: `SKILL_SELECTIONS.labels(level="midturn")`.

**Files:** `tool_agent.py` (special-case + menu in template vars),
`agent_generic.j2`, `observability.py`. **Test:** an agent granted only
note tools calls `use_skill("schedule_block")` → refusal string.

---

## Phase C — `resources/` (third disclosure level)

Skills like meeting_prep and dependency_audit want checklists/templates that
would bloat the body. Load them at **selection** time, not startup:

- `SkillLibrary.render()` additionally inlines `resources/*.md` (sorted,
  each under a `### Resource: <filename>` heading, capped ~4 KB/file).
- Keep startup cheap: `render()` reads from disk on demand; skills are
  selected a few times a day, not per-token.
- `scripts/` stays **backlog** — the sandboxed executor (ai-vfs Monty) isn't
  wired, and unsandboxed skill scripts are exactly the ADR-018 hazard.
  Ship nothing rather than a shelled-out version.

**Files:** `skills/__init__.py` only.

---

## Phase D — Planner composition (SKILLS.md §6)

Let a plan step carry a skill:

1. `TaskPlanner` prompt gains the skills menu (same `menu()` string) and the
   step schema gains optional `"skill": "<name>"`.
2. Plan validation: a step's skill must exist and its `required_tools` must
   sit inside the step's agent grant — reject the plan otherwise (same
   posture as rejecting fabricated tools).
3. Execution: before dispatching a step, `task.skills = library.render([step.skill])`.
4. Count it: `level="plan"`.

**Files:** `planning.py`. **Test:** plan fixture with a valid and an invalid
skill reference.

**Backlog (do NOT build now):** distilling successful plans into draft skills.
Revisit when there are ≥20 completed task runs to distill from.

---

## Phase E — The skill catalog

Authoring rules (from SKILLS.md §8, enforced by the A4 unit eval):
- **Description = trigger + NOT clause.** It's the only text always in context; it competes with every other skill's line.
- **Body = numbered steps an average model can follow**, naming exact tools, with the approval expectation stated (ASK-tier calls are the confirmation, don't double-ask).
- **`required_tools` honest and minimal** — the availability skip means an email skill simply doesn't exist on a box without email creds. This is the mechanism that keeps the menu short per-deployment; exploit it.
- **A skill earns its place only if it beats the bare agent.** The agent already has the tools; the skill adds *procedure* — ordering, buckets, output shape, judgment calls. If the body would just restate the tool descriptions, don't write it.

Every tool named below is registered today in `alan_t/app/bootstrap.py`.

### Wave 1 — core tools, always available (ship with Phases A–B)

**daily_briefing** — `role_hint: CHAT`
`required_tools: [recall_memory, list_task_runs, note_list]` (+ `calendar_list`, `email_list` — see note)
> Trigger: "brief me / what's my day / morning summary / catch me up."
> NOT for a single-domain question ("what's on my calendar" → calendar agent directly).
Body: ① calendar next 24 h ② unread email count + top senders ③ pending
approvals & running goals via list_task_runs ④ anything memory flags as due
⑤ one screen, most-urgent first, offer to expand any section.
*Note:* the scheduler's digest action already composes this for the cron path;
the skill is the **on-demand** twin. Two options: (a) declare the optional
tools and accept the skill disappearing when neither email nor calendar is
configured, or (b) split required vs optional — Phase E introduces an
`optional_tools:` frontmatter key (render mentions only the available ones).
Prefer (b); it's ~6 lines in the loader and several Wave-2 skills want it too.

**research_brief** — `role_hint: REASONER`
`required_tools: [web_search, web_fetch, note_create]`
> Trigger: "research X / find out about X / compare A vs B and write it up."
> NOT for a quick factual lookup — the research agent answers those directly.
Body: ① search 2–3 query variants ② fetch the 3–5 most credible hits (prefer
primary sources) ③ synthesize: TL;DR, findings with per-claim URL citations,
disagreements between sources, open questions ④ offer `note_create` to save
the brief ⑤ never cite a page you didn't fetch.

**web_clip** — `role_hint: CHAT`
`required_tools: [web_fetch, note_create, ingest_files]`
> Trigger: "save this article/link to my notes / clip this / remember this page."
> NOT for answering questions about a page — that's plain web_fetch.
Body: ① fetch the URL ② note with: title, source URL, date clipped, 3-bullet
summary, then the readable full text ③ `ingest_files` so it's immediately
RAG-searchable ④ confirm with the note name.

**memory_hygiene** — `role_hint: CHAT`
`required_tools: [recall_memory, forget_memory, remember_fact]`
> Trigger: "clean up your memory / review what you know / that's outdated."
> NOT for a simple recall — memory_recap covers that.
Body: ① broad recall on the topic (or full) ② present grouped, flag likely-stale
entries (superseded, dated, contradictory) ③ propose forget/replace per entry
④ execute only what the user confirms in chat — forget is destructive; never
bulk-delete unprompted.

**voice_journal** — `role_hint: CHAT`
`required_tools: [transcribe_audio, note_append, note_create, note_list]`
> Trigger: a voice note framed as a journal/diary/log entry ("journal this,"
> "note to self"). NOT for voice *commands* — those route normally after transcription.
Body: ① transcribe ② find today's journal note (`journal-YYYY-MM-DD`), create
if absent ③ append with an HH:MM stamp, light cleanup only (fillers out,
wording kept) ④ reply with one-line confirmation + the entry.

**image_capture** — `role_hint: VISION`
`required_tools: [analyze_image, note_create]`
> Trigger: an image of a *document* — receipt, whiteboard, business card,
> handwritten page — where the user wants the contents kept.
> NOT for "what is this picture" — image_analysis covers that.
Body: ① OCR-focused analyze_image pass ② structure by kind: receipt →
merchant/date/total/items; whiteboard → verbatim text + a "decisions/actions"
pass; card → contact fields ③ save as a note titled by kind+date ④ for a card,
offer `manage_contact` if granted.

**note_to_document** — `role_hint: REASONER`
`required_tools: [note_read, note_search, search_knowledge, document_create]`
> Trigger: "turn my notes on X into a report/post/letter/proper draft."
> NOT for summarizing (note_summarization) or writing from scratch (documents agent).
Body: ① gather every relevant note (search both note_search and RAG) ② outline
from the notes' actual content — flag gaps rather than inventing ③ draft in the
requested register ④ `document_create` (versioned) ⑤ report which notes fed it
and which sections are thin.

**document_review** — `role_hint: REASONER`
`required_tools: [document_read, document_update]`
> Trigger: "review/critique/tighten my draft/document."
> NOT for reviewing text pasted in chat — the agent does that directly.
Body: ① read the document ② three-layer pass: argument (claims supported?
structure?), paragraph (order, redundancy), line (passive voice, hedges,
long sentences) ③ present the top issues with concrete rewrites ④ apply via
document_update only on explicit go-ahead — versioning makes it safe, but the
user owns the text.

**repo_onboarding** — `role_hint: CODER`
`required_tools: [list_source_files, grep_sources, read_source, note_create]`
> Trigger: "explain this repo / how does this codebase work / onboard me to X."
> NOT for one specific function or bug — the code agent handles those directly.
Body: ① list files, identify the manifest + entry points ② read manifest,
entry point, and the 3–4 largest/most-imported modules ③ map: purpose, layers,
data flow, external deps, where tests live ④ write an onboarding note ⑤ end
with "three places to start reading, and why."

**bug_hunt** — `role_hint: CODER`
`required_tools: [grep_sources, read_source, list_source_files]`
> Trigger: "find why X breaks / trace this error / where does Y get set."
> NOT for style review or explanation of code the user pasted.
Body: ① grep the literal error string / symptom symbol first ② read every hit
plus **every caller** of the suspect function before concluding ③ present:
root cause, evidence chain (vpath:line), why it presents this way, minimal-fix
sketch ④ if not confirmable from mounted source, say exactly what's missing —
never guess a diagnosis.

**dependency_audit** — `role_hint: REASONER`
`required_tools: [read_source, grep_sources, web_search, note_create]`
> Trigger: "audit my dependencies / anything outdated or vulnerable in X?"
> NOT for adding/choosing a new library — research agent territory.
Resources: `resources/checklist.md` (per-ecosystem manifest names, risk rubric).
Body: ① find manifests (pyproject/package.json/go.mod…) ② extract direct deps +
pins ③ web_search each major dep for latest version + known CVEs — batch,
newest-info-wins ④ report table: dep / pinned / latest / risk / note ⑤ offer to
save as note. Honest cap: no lockfile parsing, direct deps only — say so in output.

### Wave 2 — email + calendar deployments (needs `optional_tools` from Wave 1)

**meeting_prep** — `role_hint: REASONER`
`required_tools: [calendar_list, search_knowledge, note_search]` · `optional_tools: [email_list, email_read, resolve_contact]`
> Trigger: "prep me for my meeting with X / what do I need for tomorrow's call."
> NOT for scheduling one — schedule_block does that.
Body: ① find the event (attendees, agenda text) ② pull context per attendee:
contacts, recent email threads, notes/RAG mentions ③ one-pager: who, last
interactions, open threads, likely topics, 3 suggested talking points ④ offer
to save as note. This is the flagship cross-domain skill — no single agent
composes calendar+email+RAG today; run it on the email agent or widen a
`assistant` agent's grant (decide in Phase E review — do NOT create a new
agent just for this).

**inbox_reply** — `role_hint: REASONER`
`required_tools: [email_read, email_send, resolve_contact, recall_memory]`
> Trigger: "reply to X / draft an answer to that email."
> NOT for triage (email_triage) or a fresh unrelated email (plain email_send).
Body: ① read the full thread, note asks + deadlines ② recall memory for
relationship/tone context ③ draft answering every ask; match the thread's
register; no invented commitments ④ show the draft — email_send is ASK-tier,
the approval is the confirmation ⑤ user tweaks are cheap, send-then-regret isn't.

**commitments_tracker** — `role_hint: REASONER`
`required_tools: [email_list, email_read, note_create]` · `optional_tools: [calendar_create, notify]`
> Trigger: "what have I promised people / anything I said I'd do this week / follow-ups?"
> NOT for triage or general inbox summary.
Body: ① scan recent sent+received threads for commitment language ("I'll",
"by Friday", "will send") in both directions ② list: who / what / when / source
uid ③ overdue first ④ offer per-item: calendar block or reminder note.

**weekly_review** — `role_hint: REASONER`
`required_tools: [list_task_runs, note_create, note_list, recall_memory]` · `optional_tools: [calendar_list, email_list]`
> Trigger: "weekly review / how was my week / plan next week."
> NOT for the daily digest — daily_briefing is the small twin.
Resources: `resources/template.md` (review sections).
Body: ① past week's calendar + completed/failed goal runs ② notes created this
week (note_list is newest-first) ③ fill the template: went well / didn't /
carried over / next week's top-3 ④ save as `review-YYYY-WW` note ⑤ offer to
remember durable takeaways.

**travel_prep** — `role_hint: REASONER`
`required_tools: [calendar_list, web_search, note_create]` · `optional_tools: [calendar_create, email_list]`
> Trigger: "I'm traveling to X / prep my trip / build me an itinerary note."
> NOT for booking anything — Alan_T doesn't transact.
Body: ① find travel-window events (conflicts!) ② search: weather, local
basics, anything user-asked ③ itinerary note: dates, flights/hotels found in
email if available, conflicts flagged, packing/prep checklist sized to weather
④ offer calendar blocks for prep tasks (ASK-tier).

### Wave 3 — planner + automations (after Phase D)

**project_kickoff** — `role_hint: REASONER`
`required_tools: [run_goal, note_create, remember_fact]`
> Trigger: "help me start project X / set up a plan for X."
> NOT for a single task — run_goal alone covers that.
Body: ① interview: outcome, deadline, constraints (use what's already in the
message; ask at most 2 questions) ② write a project charter note ③ remember
the project + deadline ④ propose the run_goal decomposition — ASK-tier, the
approval launches it.

**topic_watch** — `role_hint: CHAT`
`required_tools: [web_search, note_append, note_create]` · `optional_tools: [notify]`
> Trigger: "keep an eye on X / what's new since last time on X."
> NOT for one-shot research — research_brief.
Body: ① read the topic's watch-note for last-seen state ② search for
developments since ③ append dated delta (only what's new) ④ notify if
anything crosses the user's stated threshold. Pairs with a scheduled
automation calling the same skill via the planner path.

### Catalog discipline

- **Ship Wave 1 in two batches** (5 + 6), running the A4 selection eval after each — 16 menu lines is where description overlap starts to bite, and you want the eval red-lining collisions *before* Wave 2 doubles the surface.
- Every skill lands with its 3+2 eval fixtures in the same commit.
- After 2 weeks of `SKILL_SELECTIONS` data: a skill with zero router selections and zero mid-turn pulls gets its description rewritten once, then deleted. The menu is a budget, not a trophy shelf.

---

## Phase F — Lifecycle (keep it boring)

- **Authoring checklist** (goes in SKILLS.md §8, enforced by A4 unit eval): trigger + NOT clause · numbered steps naming exact tools · honest required_tools · ASK-tier expectation stated · 3+2 fixtures · version bumped on any description change.
- **Description change ⇒ re-run the e2e selection eval** — that's the whole release gate.
- **Quarterly prune** off the metrics (Phase E discipline).
- **Explicit non-goals, unchanged from SKILLS.md §9:** no user upload, no marketplace, no self-authoring, no ambient triggers, no skill `scripts/` until the sandbox exists.

---

## Sequencing & size

| Order | Phase | Touches | Size |
|---|---|---|---|
| 1 | A1 grant enforcement | supervisor.py | ~10 lines |
| 2 | A3 metrics | observability.py, chat_service.py | ~10 lines |
| 3 | A4 eval harness | tests/ + fixtures yaml | ~1 file |
| 4 | A2 role_hint | types.py, chat_service.py, tool_agent.py | ~20 lines |
| 5 | B use_skill | tool_agent.py, agent_generic.j2 | ~40 lines |
| 6 | E Wave 1 (+`optional_tools`) | core/skills/* , loader +6 lines | 11 skill dirs |
| 7 | C resources | skills/__init__.py | ~15 lines |
| 8 | D planner steps | planning.py | ~30 lines |
| 9 | E Waves 2–3 | core/skills/* | 7 skill dirs |
| 10 | F lifecycle docs | SKILLS.md | prose |

Everything above rides existing seams — no new services, no new dependencies,
no schema migrations. The only new frontmatter key is `optional_tools`; the
only new tool is `use_skill` (and it deliberately bypasses the registry, so
`permissions.yaml` is untouched).
