# Alan_T — Product Requirements Document (PRD)

Version: 0.2
Status: Active
Author: CKSR
Supersedes: [master_requirements_document.md](../master_requirements_document.md) (v0.1)

---

## 1. Summary

Alan_T is a self-hosted, personal, agentic AI assistant — a persistent digital companion that knows the user's projects, code, notes, and goals; remembers across sessions; and executes multi-step tasks via browser, desktop, calendar, notes, and messaging integrations.

The full product rationale, personas, functional requirements (FR-1 … FR-15), and success metrics are defined in v0.1 and remain in force except where amended below.

## 2. Amendments over v0.1

### A1 — Model strategy: cloud free-tier APIs replace local inference (MVP)

v0.1 specified local models (Qwen 3 72B / Qwen 14B / DeepSeek Coder via Ollama). For the MVP, the **default** model profile moves to **free-tier hosted APIs**:

- **Groq** — fast text inference (Llama 3.x, Qwen3-32B, GPT-OSS, DeepSeek-R1-Distill) and Whisper STT.
- **Google AI Studio** — Gemini 2.5/3.x (reasoning, long-context, vision), Gemini Embedding, Gemini TTS, Gemini Live API, Imagen 4.

This is the `free` profile — **one of three first-class profiles** (`free`/`paid`/`local`). Local inference is not abandoned; it's the `local` profile, selectable by config (ADR-017). Full role-to-model mapping and profiles: [LLM_STRATEGY.md](../ai/LLM_STRATEGY.md).
Decision records: [DECISION_LOG.md](../architecture/DECISION_LOG.md) ADR-001 (free-tier default), ADR-017 (vendor neutrality).

**Consequence acknowledged:** this temporarily weakens the "no cloud dependency" privacy stance. Mitigations (sensitivity tagging, ingestion exclusions, redaction, swap-back path to local models) are specified in [SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md).

### A2 — Mandatory abstraction layer for all external interactions

Every external dependency — LLM providers, embedding providers, STT/TTS, vector store, relational store, cache, calendar, notes, messaging, browser, desktop — sits behind a provider-agnostic interface (port). Core/domain logic never imports a provider SDK. Swapping Groq→Ollama or Qdrant→pgvector must be a configuration + adapter change with zero core-code changes.

For models this is elevated to a hard, enforced guarantee (ADR-017): any model vendor — open-source or paid — is swappable by config *profile*, and a bootstrap capability gate refuses to start on a model that can't satisfy its role, so swaps are safe rather than merely possible.

Architecture: [ADD.md](../architecture/ADD.md) §3 (Ports & Adapters); model neutrality: [LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §2.

### A3 — Vision stack simplification (MVP)

v0.1 specified Qwen VL + YOLO + PaddleOCR (local). MVP uses **Gemini multimodal** for visual QA, OCR, object detection, and UI understanding in a single call. Local specialist models remain a future swap behind the `VisionProvider` port. (ADR-006)

### A4 — Voice stack (MVP)

- STT: `whisper-large-v3-turbo` (Groq) instead of local Faster-Whisper.
- TTS: Gemini TTS instead of local Kokoro (Kokoro remains the planned local swap).
- Live voice: **Gemini Live API** instead of Moshi.

Details: [VOICE_ARCHITECTURE.md](../voice/VOICE_ARCHITECTURE.md).

## 3. Goals (unchanged)

- O1 Personal Knowledge Companion — intelligent access to documents, notes, repos, PDFs, emails, history.
- O2 Autonomous Task Execution — browser, desktop, tools, multi-step workflows.
- O3 Human-Like Interaction — real-time voice, voice notes, text, vision.
- O4 Persistent Memory — preferences, goals, projects, historical context.

## 4. Non-Functional Requirements (amended)

| Requirement | v0.1 | v0.2 |
|---|---|---|
| Text response | < 5 s | < 5 s |
| Voice response | < 2 s | < 3 s (network round-trips to Groq/Google) |
| Search results | < 3 s | < 3 s |
| Reliability | 99% workflow success | unchanged, **plus**: graceful degradation when a free-tier rate limit is hit (fallback chain, queue, or honest "try later") |
| Privacy | no cloud dependency | **no architectural cloud lock-in**; data sent to providers is minimized, logged, and user-controllable |

Free-tier rate limits (RPM/RPD/TPM) are a first-class design constraint under the default `free` profile, not an afterthought. Every pipeline that calls a model must be quota-aware. See [LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §7.

## 5. Scope

In scope / out of scope: unchanged from v0.1 §4. MVP cut: [MVP.md](MVP.md). Sequencing: [ROADMAP.md](ROADMAP.md). Everything else: [BACKLOG.md](BACKLOG.md).

## 6. Document Map

| Area | Documents |
|---|---|
| Product | PRD, [MVP](MVP.md), [ROADMAP](ROADMAP.md), [BACKLOG](BACKLOG.md) |
| Architecture | [ADD](../architecture/ADD.md), [SYSTEM_OVERVIEW](../architecture/SYSTEM_OVERVIEW.md), [AGENTS](../architecture/AGENTS.md), [LANGGRAPH](../architecture/LANGGRAPH.md), [WORKFLOWS](../architecture/WORKFLOWS.md), [DECISION_LOG](../architecture/DECISION_LOG.md) |
| AI | [LLM_STRATEGY](../ai/LLM_STRATEGY.md), [PROMPTS](../ai/PROMPTS.md), [SKILLS](../ai/SKILLS.md), [TOOL_CATALOG](../ai/TOOL_CATALOG.md), [PLANNING_ENGINE](../ai/PLANNING_ENGINE.md), [REFLECTION_ENGINE](../ai/REFLECTION_ENGINE.md) |
| Memory | [MEMORY_ARCHITECTURE](../memory/MEMORY_ARCHITECTURE.md), [MEMORY_CONSOLIDATION](../memory/MEMORY_CONSOLIDATION.md) |
| Knowledge | [AI_VFS](../knowledge/AI_VFS.md), [INGESTION_PIPELINE](../knowledge/INGESTION_PIPELINE.md), [CHUNKING_STRATEGY](../knowledge/CHUNKING_STRATEGY.md), [VECTOR_STORE](../knowledge/VECTOR_STORE.md), [RAG_PIPELINE](../knowledge/RAG_PIPELINE.md) |
| Data | [DATA_MODEL](../data/DATA_MODEL.md), [POSTGRES_SCHEMA](../data/POSTGRES_SCHEMA.md), [QDRANT_SCHEMA](../data/QDRANT_SCHEMA.md) |
| API | [API_SPECIFICATION](../api/API_SPECIFICATION.md) |
| Security | [SECURITY_ARCHITECTURE](../security/SECURITY_ARCHITECTURE.md), [TOOL_PERMISSIONS](../security/TOOL_PERMISSIONS.md) |
| Infra | [INFRASTRUCTURE](../infra/INFRASTRUCTURE.md), [DEPLOYMENT](../infra/DEPLOYMENT.md) |
| Testing | [TEST_STRATEGY](../testing/TEST_STRATEGY.md) |
