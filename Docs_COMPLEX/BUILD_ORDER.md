# Alan_T — Build Order

Version: 0.1
Status: Active

The **build order** for the lean, incremental path to a working multi-agent assistant.
This is the "Monday-morning checklist." The 50 design docs are the **north-star**; this
doc is what actually gets built, in what sequence, and why.

Rule going forward: **a design doc may run at most one milestone ahead of code.** When a
milestone ships, its docs become "as-built." This is how we keep the rigor without the
50-docs-zero-code trap.

---

## Locked scope decisions

- **Target: 10 agents** (non-negotiable). But target ≠ build order — agents are sequenced by dependency and payoff below.
- **Thin agents on one shared contract.** Each agent = prompt + tools + the shared `Agent` interface. The contract is the one early investment that makes agents #4–#10 cheap.
- **Three free LLM providers** behind a single LiteLLM seam: Groq, Google AI Studio (Gemini), NVIDIA NIM (build.nvidia.com — DeepSeek-R1, Qwen, etc.). Used as a **fallback chain** for rate-limit resilience, not one pool.
- **No Vision** for now (Vision Agent dropped from current scope).
- **Browser Agent deferred** — highest fragility/maintenance; build only when a specific recurring task justifies it.
- **Voice is last** (M6), but interfaces are built **voice-ready** so it slots in without a refactor.
- **Focus: M0 → M4, then M6.** Reflection/Research/Task-Planning/Automation come after.
- **One model config from env**, not a 3-profile registry. **pgvector** (not Qdrant). **Mem0** for memory. **ai-vfs** for files.

---

## Providers (the LiteLLM seam)

One function wraps all LLM calls; model + fallback order come from config/env.

| Provider | Access | Good for | Notes |
|---|---|---|---|
| Groq | free tier | fast CHAT (Llama 3.3 70B) | high RPM, low latency |
| Google AI Studio | free tier | LONG_CONTEXT, embeddings, (later) TTS/Live | Gemini 2.5 family |
| NVIDIA NIM | free/preview credits | REASONER (DeepSeek-R1, Qwen) | OpenAI-compatible; treat as rate-limited |

Fallback example: `CHAT → [groq/llama-3.3-70b, google/gemini-2.5-flash, nvidia/deepseek-r1]`.
Three independent free quotas = real resilience. **No capability-gate bootstrap, no role
registry, no profiles yet** — add those only when a real swap forces it.

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
**Files** (ai-vfs). Get this right at agent #1; the rest are mostly "new prompt + new tools."

---

## Build order

| # | Milestone | Agents | Est. (weekends) | Why here |
|---|---|---|---|---|
| **M0** | Foundation | Agent contract + **Conversation** | ~2 | The contract that makes 10 tractable. Direct chat, no Supervisor yet. LiteLLM → Groq. |
| **M1** | It remembers you | **Memory** (Mem0) | ~1 | Conversation needs it. First "this is mine" moment. |
| **M2** | Reach it + your files | **Telegram** (text+files), **File** (RAG) | ~2–3 | **The "I use this daily" point.** Phone access + cited answers from your notes (ai-vfs + pgvector). |
| **M3** | Routing earns its place | **Supervisor** | ~1–2 | 3 agents to route between → Supervisor is real work. **Adopt LangGraph here**, not before. |
| **M4** | Productivity | **Notes** (overlaps File, cheap), **Calendar** (Google; OAuth is the cost) | ~2 | Real assistant utility. |
| **M6** | Voice | STT (Whisper/Groq) + TTS (Gemini); wire into Telegram + Conversation | weeks | Built last; interfaces from M0/M2 already voice-ready. |

**Deferred (still in the 10-agent target):**
- **Browser Agent** — after M4, only for a concrete recurring task. Playwright selectors break constantly; budget for maintenance, not a one-time build.
- **Reflection Agent** — needs outcomes + plans to evaluate. Pair it with the **Task Planning Agent** (currently "Later"); reflection-on-plans is half-defined without a planner.
- **Later bucket:** Research, Task Planning, Automation.
- **Vision** — dropped for now.

**Honest timeline:** M0–M2 = an assistant you open every day in **~6–8 weekends**. M3–M4
add routing + productivity. The rest is the year-plus after that — and that's fine,
because you're *using it the whole time* instead of building in the dark.

---

## Build voice-ready, build thin (two design rules)

**Voice-ready (so M6 is additive, not a refactor):**
- At the interface boundary (Telegram gateway, Conversation input), model inbound as a typed `IncomingMessage{ kind: text | audio | file, ... }`. Handle `text` and `file` now; `audio` raises "not yet." Adding voice = implementing the audio branch + STT, not rewriting agents.
- Keep response *rendering* separate from *transport*, so a TTS layer can wrap outbound text later.

**Thin:**
- An agent is a prompt + a few tool-functions behind the shared contract. No per-agent frameworks.
- Tools are plain functions, not a "skills system."
- One prompt file per agent, not a prompt registry.

---

## Ceremony to skip (until a real pain forces it)

- Skills-as-first-class-primitive (ADR-018) — few tools per agent; no selection system needed yet.
- 3 model profiles + capability-gate bootstrap — one config from env.
- Qdrant — pgvector until it measurably hurts (one less container).
- Modular prompt registry — one prompt file per agent.

Keep: the Agent contract, Supervisor + LangGraph (from M3), ai-vfs, the LiteLLM seam, Mem0.

---

## Definition of done (per milestone)

- **M0:** `POST /chat` returns a model answer via the LiteLLM seam; Conversation Agent runs on the shared contract.
- **M1:** Tell it "I prefer TypeScript" → restart → "what language do I prefer?" answers correctly. *(MVP scenario #1)*
- **M2:** Message it from Telegram on your phone; ingest a notes folder; ask a question answerable only from those notes → correct answer **with a file citation**. *(MVP scenario #2 + the daily-use test)*
- **M3:** A mixed request ("remember X, then find Y in my notes") is routed by the Supervisor to the right agents.
- **M4:** "Add a 3pm meeting tomorrow" and "summarize my note on Z" both work end-to-end.
- **M6:** Send a Telegram voice note → transcript → answer; spoken reply back.

When M2 passes in ~6–8 weekends, you own more working software — and have learned more —
than another 50 docs would ever give you.
