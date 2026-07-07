# Alan_T — Architecture Decision Log

Version: 0.1
Status: Living document — append-only; supersede, don't edit history.

Format: lightweight ADR. Status ∈ {Accepted, Superseded, Proposed}.

---

## ADR-001 — Free-tier cloud APIs (Groq + Google AI Studio) instead of local models for MVP

**Status:** Accepted (2026-06-13)
**Context:** PRD v0.1 specified local inference (Qwen 72B via Ollama). Local 70B-class inference requires hardware the project doesn't want to depend on yet; free tiers at Groq and Google AI Studio offer strong models at zero cost.
**Decision:** All model inference (LLM, embeddings, STT, TTS, vision, live voice) uses Groq and Google AI Studio free tiers for the MVP era. Role-based registry defined in [LLM_STRATEGY.md](../ai/LLM_STRATEGY.md).
**Consequences:**
- (+) Zero inference cost; access to 70B–120B-class quality; Groq latency excellent.
- (−) **Conflicts with the local-first privacy principle.** Personal data (notes, code, emails) is sent to third parties; free tiers may use data for training. This is a knowing, temporary trade — documented mitigations in [SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md) §5.
- (−) Rate limits become a core design constraint (quota-aware ModelRouter, embedding cache, fallback chains).
- (−) Free-tier models get deprecated/changed without notice → nothing pins a model name outside config.
**Escape hatch:** ADR-002's port layer means returning to local models (Ollama adapter) is config + one adapter, no core change. This is a planned backlog item, not an abandoned goal.

## ADR-002 — Hexagonal architecture (Ports & Adapters) for all external dependencies

**Status:** Accepted (2026-06-13)
**Context:** User requirement: swap any external system (models, DBs, integrations) without touching core functionality. ADR-001 makes this urgent — cloud providers are explicitly temporary.
**Decision:** Core imports only ports (Python Protocols). Adapters per provider, wired at the composition root from config. Import direction enforced by lint rule in CI.
**Consequences:** (+) provider swaps are leaf changes; core testable on fakes. (−) interface ceremony; discipline required to keep SDK types from leaking.

## ADR-003 — LangGraph for agent orchestration

**Status:** Accepted (2026-06-13)
**Context:** Need stateful multi-agent routing, durable checkpoints, and human-in-the-loop interrupts for tool approval.
**Decision:** LangGraph with Postgres checkpointer. Kept behind an orchestration adapter — node functions contain no business logic ([LANGGRAPH.md](LANGGRAPH.md) §1).
**Alternatives considered:** plain function pipeline (no checkpointing/interrupts for free), CrewAI/AutoGen (less control over state).

## ADR-004 — Role-based model registry instead of direct model references

**Status:** Accepted (2026-06-13)
**Context:** Agents need different model capabilities; models will be swapped often (ADR-001 consequence).
**Decision:** Agents request roles (ROUTER, CHAT, REASONER, CODER, VISION, EMBEDDER, STT, TTS, LIVE_VOICE, REFLECTOR, SUMMARIZER, WEB_AGENT, LONG_CONTEXT, IMAGE_GEN). A YAML registry maps role → primary model + fallback chain + params. One ModelRouter choke point handles quota, retry, fallback, logging.
**Consequences:** (+) model changes are one-line config edits; uniform observability. (−) roles must be kept honest (don't proliferate near-duplicate roles).

## ADR-005 — Qdrant for semantic memory; Postgres for operational data; Redis for runtime state

**Status:** Accepted (2026-06-13)
**Context:** Three distinct data shapes: vectors+payload filtering, relational/durable, ephemeral/fast.
**Decision:** As titled, each behind its own port (`VectorStore`, `RelationalStore`, `CacheStore`).
**Alternatives:** pgvector (fewer moving parts — kept as planned second adapter to prove the port); single-store designs rejected for muddled semantics.

## ADR-006 — Gemini multimodal replaces the local vision stack (Qwen-VL + YOLO + PaddleOCR) for MVP

**Status:** Accepted (2026-06-13)
**Context:** v0.1 vision stack is three local models with separate pipelines. Gemini 2.5 Flash handles VQA, OCR, object detection, and UI understanding in one call, free.
**Decision:** Single `VisionProvider` port; Gemini adapter for MVP. Specialist local models remain a future adapter if precision (e.g., exact bounding boxes) demands it.
**Consequences:** (+) Phase 4 collapses to one integration. (−) per-image quota costs; cloud exposure of camera/screen content — camera/screen sources are ASK-tier by default ([TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md)).

## ADR-007 — Gemini Live API for live voice instead of Moshi; Groq Whisper + Gemini TTS for the non-live path

**Status:** Accepted (2026-06-13)
**Context:** Moshi (local) is heavy and immature for the latency target; the free Gemini Live API does native speech-to-speech with interruptions.
**Decision:** `LiveVoiceProvider` → Gemini Live adapter. `STTProvider` → Groq Whisper. `TTSProvider` → Gemini TTS; Kokoro stays the planned local TTS swap.
**Consequences:** (+) Phase 2 dramatically simpler. (−) live audio leaves the machine; live sessions are opt-in per session.

## ADR-008 — Single-user, single-host system

**Status:** Accepted (2026-06-13)
**Context:** PRD excludes multi-user/SaaS. HA adds cost with no user benefit at personal scale.
**Decision:** One user identity, hard-wired (e.g., Telegram allowlist of one). Docker Compose on one host; Tailscale for remote reach. No horizontal scaling design.

## ADR-009 — Documentation lives in `Docs/` (capitalized), structured per list_docs.md

**Status:** Accepted (2026-06-13)
**Context:** list_docs.md shows lowercase `docs/`; the repo already had `Docs/` with the master requirements. A second case-variant directory would be confusing on case-sensitive filesystems.
**Decision:** Keep the existing `Docs/` directory as the single docs root; subfolders follow list_docs.md structure exactly.

## ADR-010 — ai-vfs as mirror + agent workspace, with a source sync service

**Status:** Accepted (2026-06-13)
**Context:** The actual `ai-vfs` repository (sibling project, v0.0.1) is a writable, versioned VFS library — namespaces, principals, path permissions with invisible pruning, BLAKE3 content-addressed blobs, per-file versioning/rollback, native FTS (Postgres tsvector+pg_trgm), audit log — **not** a read-only mount layer over existing folders, which is what the first draft of AI_VFS.md assumed. It has no watch/mount API; external content must be written in.
**Decision:** Alan_T integrates it as: (1) a **source sync service** (Alan_T worker) that watches real folders/repos, honors exclusions, and mirrors content into a read-mostly `sources` namespace; (2) a `workspace` namespace as versioned, permission-scoped agent scratch (new `WorkspaceStore` port); (3) Alan_T agents registered as ai-vfs **principals** with default-deny path grants — filesystem-level enforcement beneath the tool permission gate. Ingest ledger keys on ai-vfs's BLAKE3 hashes. Detail: [AI_VFS.md](../knowledge/AI_VFS.md).
**Consequences:** (+) user files gain version history; per-agent filesystem permissions; native corpus grep with zero blob reads; shared Postgres, no new containers. (−) blob-storage duplication of the corpus (accepted at personal scale); a sync service to build and keep honest; ai-vfs is pre-1.0 — version pinned, breaking changes absorbed in the adapter.
**Deferred:** ai-vfs native FTS as the hybrid-retrieval keyword leg (vs chunk-level FTS); Monty sandboxed execution as a `vfs_execute` tool (needs its own ADR + ASK tier when ai-vfs ships it).

## ADR-011 — LiteLLM as the provider leg of the LLM layer

**Status:** Accepted (2026-06-13)
**Context:** The plan called for hand-written Groq and Google adapters plus a custom ModelRouter implementing fallbacks, retries, and budget tracking — the largest chunk of undifferentiated Phase-1 infrastructure. LiteLLM (SDK mode, not the proxy server) provides a unified OpenAI-format interface over both providers with fallback chains, retry/backoff, and cost/budget primitives built in.
**Decision:** One `LiteLLMAdapter` implements the `LLMProvider` and `EmbeddingProvider` ports for chat and embeddings. The role registry, role-level quota config, embedding-space discipline (no silent embedder fallback — configured explicitly), and logging hooks remain ours in the ModelRouter; LiteLLM supplies the provider plumbing beneath. Gemini Live API and Gemini TTS stay on `google-genai` directly (outside LiteLLM's sweet spot; the voice path goes through Pipecat anyway, ADR-014).
**Consequences:** (+) deletes most planned adapter/router code; new providers (incl. the future Ollama swap) become config. (−) a large, fast-churning dependency — version pinned, weekly cloud contract tests are the upgrade gate; care needed so LiteLLM types don't leak past the adapter (the port boundary rule applies to it like any SDK).

## ADR-012 — arq for background jobs and scheduling

**Status:** Accepted (2026-06-13)
**Context:** The ingestion/memory pipelines hand-rolled Redis list queues (priorities, retries, backoff, dead-letter) and APScheduler was slated for cron. arq provides async Redis job queues with retries, backoff, and built-in cron.
**Decision:** arq runs all background work: ingestion jobs, fact extraction, consolidation, scheduled automations. The `Scheduler` port's adapter is arq cron; APScheduler is dropped. Dead-letter handling remains a thin custom layer on arq's retry exhaustion.
**Consequences:** (+) one job system instead of two; queue semantics we don't have to debug. (−) Redis is now load-bearing for job durability (`appendonly yes` already configured); arq's priority support is coarser than the hand-rolled design — priority becomes separate queues, which is fine.

## ADR-013 — Langfuse (self-hosted, optional profile) for LLM observability

**Status:** Accepted (2026-06-13)
**Context:** METRICS.md §2 specifies per-call token/cost accounting and trace correlation; PROMPTS.md §7 wants prompt versioning. Langfuse covers traces, costs, prompt management, and eval-score recording, self-hostable.
**Decision:** Adopt Langfuse as an **optional Docker Compose profile**, instrumented from the ModelRouter choke point. structlog + Prometheus remain the always-on baseline and the alerting source; Langfuse is enabled when debugging quality/cost, not required for operation.
**Consequences:** (+) purpose-built LLM tracing without building dashboards. (−) honest footprint warning: self-hosted Langfuse v3 brings ClickHouse + MinIO + its own Postgres — heavy for one host, which is exactly why it's a profile, not a core service.

## ADR-014 — Pipecat for the voice pipeline

**Status:** Accepted (2026-06-13)
**Context:** Phase 2 needs realtime transport, VAD, interruption handling, and streaming STT→LLM→TTS orchestration — weeks of fiddly plumbing. Pipecat (Daily's open-source voice-agent framework) ships all of it, provider-agnostic, with native support for Gemini Live and Groq Whisper.
**Decision:** Both voice paths in VOICE_ARCHITECTURE.md are built as Pipecat pipelines inside the voice adapter layer. The `STTProvider`/`TTSProvider`/`LiveVoiceProvider` ports stand; Pipecat is the engine behind them, not a replacement for them. The non-realtime Telegram voice-note path may bypass Pipecat (it's a simple file STT→chat→TTS sequence) if the framework adds no value there.
**Consequences:** (+) interruptions, VAD, and transport solved; provider-agnostic design aligns with ADR-002. (−) a framework dependency in the voice path; local-swap goals (Kokoro/Faster-Whisper) must be re-verified against Pipecat's service catalog when that day comes.

## ADR-015 — Leaf-library adoptions (reuse-first for undifferentiated code)

**Status:** Accepted (2026-06-13)
**Context:** Several planned components are solved problems. Policy: where a maintained library replaces code that gives Alan_T no identity, adopt it behind the existing port/pipeline stage.
**Decision:** instructor (Pydantic-validated structured LLM outputs with repair-retry — implements PROMPTS.md §5), docling (layout-aware PDF/Office parsing), Ragas (RAG eval metrics: faithfulness, context precision), aiogram (Telegram gateway), watchfiles (sync-service file watching), SearXNG (self-hosted keyless metasearch for the Research agent, optional container), gcsa (Google Calendar API ergonomics), imap-tools (email ingestion, Phase 3+).
**Consequences:** (+) each deletes a chunk of bug surface. (−) eight dependencies to track; each is leaf-level and individually disposable, which is the criterion for being on this list at all.

## ADR-016 — Memory layer: Mem0 spike before building custom

**Status:** Proposed (2026-06-13) — decision due by end of Phase 1
**Context:** MEMORY_ARCHITECTURE.md specifies extraction, dedup/merge, contradiction supersedence, scored recall, and user-controlled review/forget/export. Mem0 implements most of this and supports our exact stack (Qdrant, Groq, Gemini). Building custom means owning that logic forever; adopting means mapping our taxonomy onto its model.
**Decision (gate, not adoption):** Run a time-boxed spike: stand up Mem0 against Qdrant + the role registry's models and score it against MEMORY_ARCHITECTURE.md as a requirements checklist — the six kinds taxonomy, supersede chains, confidence gating, review surface, full export, soft-delete window. Adopt if it clears the checklist without fighting it; otherwise build custom and record the failing requirements here.
**Consequences:** either way, MEMORY_ARCHITECTURE.md remains the contract — Mem0 would be an adapter detail behind the Memory agent, not a rewrite of the design.

## ADR-017 — Provider neutrality is a hard requirement, enforced at bootstrap

**Status:** Accepted (2026-06-13)
**Context:** Hard user requirement: Alan_T must never be locked to a model vendor — any model, open-source or paid, hosted or local, must be swappable by configuration, and the same holds for every port. The mechanism already existed (ADR-002 ports, ADR-004 role registry, ADR-011 LiteLLM), but the docs framed Groq/Google as if they were the architecture, the registry examples showed only two provider ids, and nothing validated that a swapped-in model can actually do what its role needs. Swapping was possible but implicit and unsafe.
**Decision:**
1. **Neutrality is a stated design property, not a side effect.** The architecture is provider-agnostic; Groq + Google free tier is one selectable *profile*. The registry's `provider:` field accepts any LiteLLM provider id — OSS/local (Ollama, vLLM, LM Studio, HuggingFace TGI) or paid (OpenAI, Anthropic, Bedrock, Vertex AI, Azure, OpenRouter, Mistral, Together).
2. **Config profiles:** `config/models.<profile>.yaml`, selected via `ALAN_MODEL_PROFILE`. Three ship as first-class equals: `free` (Groq/Google — default), `paid` (OpenAI/Anthropic), `local` (Ollama/vLLM). Switching profile is the whole-system swap. ([LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §2)
3. **Capability contract + bootstrap gate:** every role declares required capabilities (tools, vision, json_mode, min context…); `alan bootstrap` resolves each configured model's capabilities and **hard-fails on mismatch**, naming role / model / missing capability. Swapping must be safe, not merely possible.
**Scoped exceptions, recorded honestly (each with its escape path):**
- `EMBEDDER` — fully swappable, but any change invalidates the vector space → explicit re-embed migration ([LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §6). Friction, not lock-in.
- `LIVE_VOICE` — native speech-to-speech is Gemini-specific **by choice** (quality/latency); the provider-neutral escape is the composed STT→CHAT→TTS pipeline, documented as the fallback live path.
- Library-backend couplings: LangGraph checkpointer assumes Postgres; arq assumes Redis. Both sit behind ports — swappable in principle, but the chosen libraries carry the assumption.
**Consequences:** (+) "run everything on Ollama" or "move CHAT to Claude" is a config edit that either passes the gate or fails loudly at startup, never at runtime mid-conversation. (−) a per-model capability map must be maintained in config (seeded from LiteLLM model metadata); three profiles must be kept current instead of one.

## ADR-018 — Skills as a first-class, orchestrator-selected primitive

**Status:** Accepted (2026-06-13); selection/access model refined by ADR-019
**Context:** The build goal is "modular prompts and create/reuse skills wherever possible." The architecture had agents (routing targets), tools (gated function calls), and prompt templates (per-call text) — but no unit for a *reusable, packaged capability*: a multi-step workflow + its instructions + the tools it needs + optional helper scripts, pulled in on demand. Without one, reusable know-how has no home: it gets baked into an agent (not reusable), forced into a tool (too coarse), or scattered across prompt templates (no triggering, no bundling, no reuse). The user wants the Claude Agent Skills model (SKILL.md + progressive disclosure).
**Decision:** Introduce a **Skill** primitive ([SKILLS.md](../ai/SKILLS.md)):
1. **Anatomy:** a skill is a versioned package — `SKILL.md` (metadata: name, trigger description, `required_tools`, role hints, version + instruction body) plus optional `scripts/` and `resources/`. Modeled directly on Claude Agent Skills.
2. **Progressive disclosure (the efficiency property):** only skill *descriptions* sit in context (a cheap menu); a skill's full body loads only when selected. N skills cost N short descriptions until one fires.
3. **Orchestrator-selected (single decision point):** the supervisor holds the catalog and selects the agent **and** the relevant skill(s) in one routing decision; chosen skill bodies are injected into the executing agent's prompt assembly ([PROMPTS.md](../ai/PROMPTS.md) §2). This deliberately avoids a second, competing trigger layer (skill self-triggering vs. agent routing) — refines the initial "skills trigger within an agent's turn" idea in favor of the cleaner orchestrator-owned model.
4. **Composes, never escalates:** a skill *orchestrates* tools but every tool call still passes the permission gate ([TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md)); a skill's `required_tools` must be a subset of the executing agent's grants. Skills can declare MCP-provided tools ([MCP.md](../integrations/MCP.md)). Bundled scripts run only in the sandboxed executor (ai-vfs Monty), never host shell.
5. **Planner-reusable (Phase 7):** a plan step can be "apply skill X" — skills are the concrete form of the plan-pattern reuse noted in [PLANNING_ENGINE.md](../ai/PLANNING_ENGINE.md).
**Consequences:** (+) reuse gets a real home; modular prompts generalize upward into composable capability packages; the catalog scales cheaply via progressive disclosure. (−) a skill-selection decision is added to the supervisor (new eval surface: did the right skill fire?); skills are versioned artifacts to maintain.
**Scoped out (MVP):** no user-uploaded/marketplace skills (first-party, in-repo, reviewed like code); no autonomous self-authoring of skills (backlog).

## ADR-019 — Shared Resource Layer: decentralize access, keep selection owned and authority central

**Status:** Accepted (2026-06-13) — refines ADR-018
**Context:** A multi-agent system must not bottleneck on the orchestrator. ADR-018 framed the supervisor as the single point that *selects* skills, and let that imply it also *serves* them — which would serialize every turn through one actor and stop an agent from pulling a skill it discovers it needs mid-task. But naively decentralizing everything risks (a) reintroducing ambient skill self-triggering that races with routing (the exact hazard ADR-018 excluded) and (b) blurring the permission model into "any agent can do anything." The fix is to separate three concerns ADR-018 collapsed: **access**, **selection**, **authority**.
**Decision:**
1. **Access — decentralized, the bottleneck fix.** Skills, prompt templates, resources, the tool catalog, and the model registry live in a **Shared Resource Layer**: loaded once at startup, immutable at runtime, concurrently readable (no locks) by the supervisor, every agent, and any model-using tool — with no proxy hop through the orchestrator. Load-once, read-many. ([SKILLS.md](../ai/SKILLS.md) §3, [ADD.md](ADD.md) §4a)
2. **Selection — two deliberate levels, never ambient.** (a) The supervisor selects skills at routing time (common path, progressive disclosure). (b) An agent may *deliberately* pull additional skills/prompts mid-turn when a subtask reveals the need. Both are owned, explicit decisions. There is still **no ambient self-firing skill layer** with no owner — the ADR-018 hazard stays excluded; this adds a second *deliberate* selector, not an autonomous one.
3. **Authority — centralized, unchanged.** Decentralized access is **not** decentralized authorization. Reading a skill/prompt is free; *acting* through a tool still passes the one permission gate ([TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md)), regardless of which agent or skill pulled it. The gate remains the single enforcement choke even as access fans out.
4. **Tools read, agents trigger.** Model-using tools read their prompts/resources directly from the shared layer (no hand-down from the orchestrator); triggering a *skill* stays with agents/orchestrator — a tool triggering a skill would invert the tool→agent layering.
**Consequences:** (+) no orchestrator serialization; concurrent resource reads; deep agents compose skills mid-task; parallel plan steps (Phase 7) don't contend on a central server. (−) two selection levels is more surface than "one decision point" — bounded by the no-ambient rule and by the permission gate staying the single authority choke.

---

*Template for new entries:*

```
## ADR-NNN — Title
**Status:** Proposed | Accepted | Superseded by ADR-MMM (date)
**Context:** what forced a decision
**Decision:** what was decided
**Consequences:** (+) and (−), honestly
```
