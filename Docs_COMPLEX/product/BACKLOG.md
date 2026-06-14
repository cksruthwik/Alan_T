# Alan_T — Backlog

Version: 0.1
Status: Living document — reprioritize freely; phases in [ROADMAP.md](ROADMAP.md) pull from here.

Priority: P1 = needed for current/next phase, P2 = wanted soon, P3 = someday.

## P1 — Foundation & Core

- [ ] Model provider port (`LLMProvider`) + LiteLLM adapter for Groq + Google — ADR-011
- [ ] Role-based model registry (YAML config, fallback chains, per-role params) on top of LiteLLM
- [ ] Role-level quota windows + honest-degradation path (LiteLLM budgets where they fit, Redis counters where not)
- [ ] arq job runner: queues + cron, dead-letter layer — ADR-012
- [ ] Structured outputs via instructor — ADR-015
- [ ] Mem0 spike vs custom memory build — ADR-016 (decide by end of Phase 1)
- [ ] Khoj UX review before building the Phase 1 chat UI (steal patterns, not code)
- [ ] `VectorStore` port + Qdrant adapter
- [ ] `RelationalStore` port (repository pattern) + Postgres adapter (SQLAlchemy)
- [ ] `CacheStore` port + Redis adapter
- [ ] LangGraph conversation graph (supervisor → conversation agent → tools)
- [ ] Skill system: registry + progressive disclosure + supervisor selection + prompt injection — ADR-018
- [ ] Seed skills (digest composition, note summarization) + skill-selection eval set
- [ ] Conversation persistence + session resume
- [ ] Long-term memory: fact extraction, storage, relevance recall
- [ ] Ingestion pipeline: watcher → parser → chunker → embedder → upsert
- [ ] Embedding cache keyed by content hash (quota protection)
- [ ] Hybrid search (vector + keyword) with citations
- [ ] Minimal web chat UI
- [ ] Docker Compose stack + healthchecks
- [ ] Structured logging + request tracing baseline

## P2 — Near-Term Capabilities

- [ ] Voice notes: upload → Groq Whisper → answer → Gemini TTS
- [ ] Gemini Live API integration (live voice mode)
- [ ] Memory consolidation nightly job (episodic → summary)
- [ ] Memory review UI ("what do you know about me?" + delete/edit)
- [ ] Git repo indexing with code-aware chunking
- [ ] Query rewriting + reranking in RAG
- [ ] Source sync service: real folders → ai-vfs `sources` namespace (watch, exclusions, tombstones)
- [ ] Agent workspace on ai-vfs (`WorkspaceStore` port, per-agent principals + grants)
- [ ] Evaluate ai-vfs native FTS as keyword leg of hybrid retrieval (vs chunk-level chunks_fts)
- [ ] Screenshot/image QA via Gemini multimodal
- [ ] Telegram bot: text first (precedes Phase 8 if convenient)
- [ ] Tool permission system: allow/ask/deny tiers + audit log
- [ ] Secrets management (encrypted at rest; never in logs)
- [ ] Voice pipeline on Pipecat (Gemini Live + Groq Whisper + Gemini TTS) — ADR-014
- [ ] Langfuse optional compose profile + ModelRouter instrumentation — ADR-013
- [ ] SearXNG container + Research agent search tool — ADR-015
- [ ] Evaluate chonkie for the chunker implementations (vs hand-written)
- [ ] Watch: deepagents × ai-vfs backend synergy (ai-vfs design already cites it)

## P3 — Later

- [ ] Playwright browser agent + Browser Use
- [ ] Desktop control agent (dry-run mode first)
- [ ] Planning engine (goal → task DAG → execution)
- [ ] Reflection engine (evaluate → repair → retry)
- [ ] Scheduled automations: daily digest, weekly review, goal tracking
- [ ] Google Calendar + Outlook adapters behind `CalendarProvider`
- [ ] Obsidian/Markdown notes adapter behind `NotesProvider`
- [ ] Email ingestion (IMAP) into knowledge layer
- [ ] Planner composition of skills (plan step = "apply skill X"); distill successful plans into reviewed skills
- [ ] Self-authoring + user-defined skills with a sandbox/trust model (skill marketplace deferred)
- [ ] Local model adapter (Ollama) — the "swap back" proving the abstraction
- [ ] pgvector adapter as Qdrant alternative (second proof)
- [ ] Sensitivity tagging + redaction layer before cloud calls
- [ ] MCP client support (consume external MCP servers as tools)
- [ ] Imagen 4 image generation tool
- [ ] Mobile app / PWA
- [ ] Multi-device sync
- [ ] Voice cloning, personal digital twin

## Bug / Debt Log

(empty — populate as they appear)

## Icebox / Rejected

- Multi-user support — single-user by design (PRD §4)
- Financial trading, autonomous purchasing — out of scope permanently
- Social media automation — out of scope for MVP era
