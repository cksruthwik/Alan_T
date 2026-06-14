# Alan_T — Backlog

Version: 0.2
Status: Living document — reprioritize freely; milestones in [ROADMAP.md](ROADMAP.md) and [BUILD_ORDER.md](../BUILD_ORDER.md) pull from here.

Priority: P1 = needed for current/next milestone, P2 = wanted soon, P3 = someday.

## P1 — Foundation & Core (M0–M2)

- [ ] LiteLLM seam: one function over **Groq + Google + NVIDIA NIM**, model + fallback order from config — ADR-011/020
- [ ] ModelRouter: quota windows (Postgres/in-memory counters) + honest-degradation fallback chain
- [ ] Structured outputs via instructor
- [ ] Adopt **Mem0** for memory — ADR-016 (decided: use Mem0)
- [ ] `VectorStore` port + **pgvector** adapter (in Postgres) — ADR-021
- [ ] `RelationalStore` port (repository pattern) + Postgres adapter (SQLAlchemy)
- [ ] Agent contract (with empty SKILLS layer + voice-ready `IncomingMessage`) — M0
- [ ] Conversation Agent + FastAPI `/chat` + session persistence/resume
- [ ] Long-term memory: fact extraction, storage, relevance recall (Mem0) — M1
- [ ] Ingestion pipeline: watcher → parser → chunker → embedder → upsert (pgvector) — M2
- [ ] Embedding cache keyed by content hash (quota protection)
- [ ] Hybrid search (pgvector + Postgres FTS) with citations — M2
- [ ] Telegram gateway (text + files) + single-user allowlist — M2
- [ ] Tailscale remote access — M2
- [ ] Docker Compose stack (api + postgres/pgvector) + healthchecks
- [ ] Structured logging + request tracing baseline

## P2 — Near-Term (M3–M4)

- [ ] LangGraph conversation graph (supervisor → agent → tools) — M3
- [ ] Supervisor Agent (ROUTER) + intent classification + tool stripping — M3
- [ ] Skill system: registry + progressive disclosure + Supervisor selection — ADR-018/024, M3
- [ ] Seed skills (note summarization) + skill-selection eval set — M3
- [ ] Notes Agent (Markdown/Obsidian via `NotesProvider`) — M4
- [ ] Calendar Agent (Google via `CalendarProvider`, OAuth) — M4
- [ ] Skills composing calendar + notes + memory — M4
- [ ] Tool permission system: allow/ask/deny tiers + audit log
- [ ] Secrets management (encrypted at rest; never in logs)
- [ ] Memory review surface ("what do you know about me?" + delete/edit)
- [ ] Query rewriting in RAG
- [ ] Evaluate chonkie for chunker implementations (vs hand-written)

## P3 — Later (deferred agents + upgrades)

- [ ] Voice (M6): voice notes (Whisper → answer → Gemini TTS), Pipecat pipeline, Gemini Live
- [ ] RAG reranking (top 8 → top 4)
- [ ] Git repo indexing with code-aware chunking + Code Agent
- [ ] Browser Agent (Playwright) — only for a concrete recurring task
- [ ] Task Planning engine (goal → task DAG → execution) + Reflection engine
- [ ] Automation agent: daily digest, weekly review, goal tracking (+ scheduled jobs, cron)
- [ ] Memory consolidation nightly job (episodic → summary)
- [ ] Email ingestion (IMAP) into knowledge layer
- [ ] Planner composition of skills; distill successful plans into reviewed skills
- [ ] Self-authoring + user-defined skills with a sandbox/trust model
- [ ] **Local model adapter (Ollama)** — the "swap back" proving the seam — ADR-001 escape hatch
- [ ] Role registry + profiles + capability-gate bootstrap — when multi-profile swaps get real (ADR-020)
- [ ] Qdrant adapter — only if pgvector measurably falls short (ADR-021)
- [ ] Redis + dedicated worker queue — when concurrency demands it
- [ ] Sensitivity tagging + redaction layer before cloud calls
- [ ] MCP client support (consume external MCP servers as tools)
- [ ] Vision agent (dropped for now — ADR-023)
- [ ] Mobile app / PWA; multi-device sync

## Bug / Debt Log

(empty — populate as they appear)

## Icebox / Rejected

- Multi-user support — single-user by design (PRD §3)
- Financial trading, autonomous purchasing — out of scope permanently
- Social media automation — out of scope for the MVP era
