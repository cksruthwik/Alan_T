# Alan_T — Product Requirements Document (PRD)

Version: 0.3
Status: Active
Author: CKSR
Canonical build sequence: [BUILD_ORDER.md](../BUILD_ORDER.md)

## 1. Summary

Alan_T is a **self-hosted, single-user, agentic AI assistant** — a persistent companion
that knows your projects, notes, and goals, remembers across sessions, answers questions
over your own files, and executes multi-step tasks (Telegram, calendar, notes today;
browser and voice later). Built lean and incrementally; the 10-agent system is reached one
milestone at a time.

## 2. Goals

- **O1 — Personal knowledge companion:** RAG over your notes/files/repos, with citations.
- **O2 — Persistent memory:** preferences, facts, goals, and project context across sessions.
- **O3 — Reachable:** text from your phone (Telegram) early; voice last (M6).
- **O4 — Autonomous task execution:** calendar/notes now; browser/desktop later.

## 3. Users & principles

Single user (you), single host. **Local-first by default**; cloud LLM calls are minimized,
logged, and user-controllable. **Provider-neutral by convention** — all model calls go
through one LiteLLM seam, so returning to local models (Ollama) is a config change, not a
rewrite ([../ai/LLM_STRATEGY.md](../ai/LLM_STRATEGY.md), ADR-020/022).

## 4. Model strategy

Three free-tier providers behind **one LiteLLM seam**, used as a **fallback chain** for
rate-limit resilience:

- **Groq** — fast chat (Llama 3.3 70B), Whisper STT.
- **Google AI Studio** — Gemini 2.5 (long-context, embeddings, TTS, Live API).
- **NVIDIA NIM** (build.nvidia.com) — DeepSeek-R1, Qwen, other strong reasoning models.

Model + fallback order come from env/config. No role registry, profiles, or capability-gate
bootstrap in the lean build (those return when a real multi-profile swap needs them — ADR-020).

## 5. Scope

- **Agents:** 10-agent target, built **M0→M4 then M6** ([ROADMAP.md](ROADMAP.md)).
- **Now:** chat, memory, RAG, Telegram, calendar, notes; Supervisor + skills from M3.
- **Deferred:** Browser; Reflection + Task Planning; Research; Automation.
- **Dropped (for now):** Vision.
- **Out of scope entirely:** multi-user, SaaS, model fine-tuning.

## 6. Non-functional requirements

| Requirement | Target |
|---|---|
| Text response | < 5 s |
| Retrieval | < 3 s |
| Voice round-trip (M6) | < 3 s |
| Reliability | graceful degradation on free-tier limits: fallback chain → queue → honest "try later", never a silent failure |
| Privacy | no architectural cloud lock-in; data sent to providers is minimized, logged, user-controllable |

Free-tier rate limits are a first-class design constraint — every model call goes through
the quota-aware LiteLLM fallback chain.

## 7. Document map

Index: [../README.md](../README.md) · Sequence: [BUILD_ORDER.md](../BUILD_ORDER.md) ·
Decisions: [../architecture/DECISION_LOG.md](../architecture/DECISION_LOG.md) ·
Scope cut: [MVP.md](MVP.md) · Everything else: [BACKLOG.md](BACKLOG.md).
Full original design (all phases) archived in `../../Docs_COMPLEX/`.
