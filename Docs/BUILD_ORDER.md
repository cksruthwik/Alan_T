# Alan_T — Build Order

Version: 0.2
Status: Active

The **build order** for the lean, incremental path to a working multi-agent assistant.
This is the "Monday-morning checklist." The design docs are the **north-star**; this doc
is what actually gets built, in what sequence, and why. Where a design doc describes more
than the lean build, this doc and `DECISION_LOG` ADR-020..024 win.

Rule going forward: **a design doc may run at most one milestone ahead of code.** When a
milestone ships, its docs become "as-built."

---

## Locked scope decisions

- **Target: 10 agents** (non-negotiable). Target ≠ build order — agents are sequenced by dependency and payoff below.
- **Thin agents on one shared contract.** Each agent = prompt + tools + the shared `Agent` interface.
- **Skills are the orchestration model** (kept, not deferred). Claude-Agent-Skills pattern + progressive disclosure: only a skill's `name`+`description` sits in context until the Supervisor selects it. The Supervisor selects `{agent, skills[]}` per turn ([ai/SKILLS.md](ai/SKILLS.md)). Skills go **live at M3** with the Supervisor; M0–M2 agents are built skill-*ready*. Deferred: Level-2 mid-turn pulls, Planner composition (Phase 7), self-authoring, skill-selection eval.
- **Three free LLM providers** behind a single LiteLLM seam: Groq, Google AI Studio (Gemini), NVIDIA NIM (build.nvidia.com — DeepSeek-R1, Qwen, etc.). Used as a **fallback chain** for rate-limit resilience. Model + fallback order from env/config. No role registry, no 3-profile system, no capability-gate bootstrap yet (ADR-020).
- **No Vision** for now (archived in `Docs_COMPLEX/`).
- **Browser Agent deferred** — highest fragility/maintenance; build only when a specific recurring task justifies it.
- **Voice is last** (M6), but interfaces are built **voice-ready** so it slots in without a refactor.
- **Focus: M0 → M4, then M6.** Reflection/Research/Task-Planning/Automation come after.
- **One model config from env**, not a 3-profile registry. **pgvector** (not Qdrant). **Mem0** for memory. **ai-vfs** for files. Redis/arq deferred (ADR-021).

---

## Providers (the LiteLLM seam)

One function wraps all LLM calls; model + fallback order come from config/env.

| Provider | Access | Good for | Notes |
|---|---|---|---|
| Groq | free tier | fast CHAT (Llama 3.3 70B) | high RPM, low latency |
| Google AI Studio | free tier | LONG_CONTEXT, embeddings, (later) TTS/Live | Gemini 2.5 family |
| NVIDIA NIM | free/preview credits | REASONER (DeepSeek-R1, Qwen) | OpenAI-compatible; treat as rate-limited |

Fallback example: `CHAT → [groq/llama-3.3-70b, google/gemini-2.5-flash, nvidia/deepseek-r1]`.
Three independent free quotas = real resilience. The full role registry / profiles /
capability-gate bootstrap return only when a real multi-profile swap needs them (ADR-020).

---

## The shared Agent contract (build once, at M0)

```
Agent.run(messages, context) -> {
    response,          # text for the user
    tool_calls,        # tools the agent invoked
    handoff?,          # optional: route to another agent
    status,            # ok | degraded | needs_approval
}
```

Plus shared services every agent can reach: **LLM** (LiteLLM seam), **Memory** (Mem0),
**Files** (ai-vfs). The prompt assembly accepts an injected **SKILLS layer** (empty until
M3) so skills slot in without reworking agents. Get this right at agent #1; the rest are
mostly "new prompt + new tools."

---

## Build order

| # | Milestone | Agents | Est. (weekends) | Why here |
|---|---|---|---|---|
| **M0** | Foundation | Agent contract + **Conversation** | ~2 | The contract (incl. empty SKILLS layer) that makes 10 tractable. Direct chat, no Supervisor yet. LiteLLM → Groq. |
| **M1** | It remembers you | **Memory** (Mem0) | ~1 | Conversation needs it. First "this is mine" moment. |
| **M2** | Reach it + your files | **Telegram** (text+files), **File** (RAG) | ~2–3 | **The "I use this daily" point.** Phone access + cited answers from your notes (ai-vfs + pgvector). |
| **M3** | Routing + skills go live | **Supervisor** | ~1–2 | 3 agents to route between → Supervisor is real work. **Adopt LangGraph here.** Skill registry + progressive disclosure + Supervisor Level-1 selection + a few seed skills land now. |
| **M4** | Productivity | **Notes** (overlaps File, cheap), **Calendar** (Google; OAuth is the cost) | ~2 | Real assistant utility; first skills that compose calendar+notes+memory. |
| **M6** | Voice | STT (Whisper/Groq) + TTS (Gemini); wire into Telegram + Conversation | weeks | Built last; interfaces from M0/M2 already voice-ready. |

**Deferred (still in the 10-agent target):**
- **Browser Agent** — after M4, only for a concrete recurring task. Playwright selectors break constantly; budget for maintenance.
- **Reflection Agent** — needs outcomes + plans to evaluate. Pair with the **Task Planning Agent** (currently "Later").
- **Later bucket:** Research, Task Planning, Automation. **Vision** — dropped for now.

**Honest timeline:** M0–M2 = an assistant you open every day in **~6–8 weekends**. M3 adds
routing + skills, M4 productivity. The rest is the year-plus after — fine, because you're
*using it the whole time*.

---

## Build voice-ready, build thin (two design rules)

**Voice-ready (so M6 is additive, not a refactor):**
- Model inbound as `IncomingMessage{ kind: text | audio | file, ... }`. Handle `text`/`file` now; `audio` raises "not yet." Adding voice = implementing the audio branch + STT, not rewriting agents.
- Keep response *rendering* separate from *transport*, so a TTS layer can wrap outbound text later.

**Thin:**
- An agent is a prompt + a few tool-functions behind the shared contract. No per-agent frameworks.
- Tools are plain functions; a **skill** packages a reusable multi-step workflow over those tools (thin SKILL.md, selected by the Supervisor from M3).
- One prompt file per agent.

---

## Ceremony to skip (until a real pain forces it)

- **3 model profiles + capability-gate bootstrap** — one config from env (ADR-020).
- **Qdrant + Redis** — pgvector until it measurably hurts; Redis/arq when a real job queue exists (ADR-021).
- **Full hexagonal ports + import-linter CI** — one LLM seam now; add ports reactively (ADR-022).
- **Modular prompt registry** — one prompt file per agent.

**Keep:** the Agent contract, **Skills** (thin, from M3), Supervisor + LangGraph (from M3), ai-vfs, the LiteLLM seam, Mem0.

---

## Definition of done (per milestone)

- **M0:** `POST /chat` returns a model answer via the LiteLLM seam; Conversation Agent runs on the shared contract (with an empty SKILLS layer).
- **M1:** Tell it "I prefer TypeScript" → restart → "what language do I prefer?" answers correctly. *(MVP scenario #1)*
- **M2:** Message it from Telegram; ingest a notes folder; ask a question answerable only from those notes → correct answer **with a file citation**. *(MVP scenario #2 + daily-use test)*
- **M3:** A mixed request is routed by the Supervisor to the right agent, and a seed skill (e.g. note-summarization) fires when its description matches.
- **M4:** "Add a 3pm meeting tomorrow" and "summarize my note on Z" both work end-to-end.
- **M6:** Send a Telegram voice note → transcript → answer; spoken reply back.
