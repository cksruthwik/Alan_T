# Alan_T — MVP Definition

Version: 0.1
Status: Active

The MVP answers one question: **can Alan_T hold a contextual conversation, remember things across sessions, and answer questions over the user's own files — reliably, on free-tier APIs?**

Everything else (voice, vision, browser, desktop, Telegram, planning) is staged after this core proves out.

## 1. MVP Scope (Phase 1 of the roadmap)

### In

| Capability | Definition of done |
|---|---|
| Text chat | Multi-turn conversation via FastAPI endpoint + minimal web UI; context survives a restart |
| Model routing | Role-based registry (ROUTER/CHAT/REASONER/…) over the LiteLLM adapter, default `free` profile (Groq/Google), automatic fallback on rate limit, bootstrap capability gate |
| Short-term memory | Session state in Redis; conversation log in Postgres |
| Long-term memory | Explicit "remember this" + automatic fact extraction into Postgres; recalled into context by relevance |
| Document ingestion | Point Alan_T at folders; Markdown/PDF/text/code ingested, chunked, embedded into Qdrant |
| Semantic search + RAG | "What do my notes say about X?" answered with citations to source files |
| Abstraction layer | All external calls behind ports; swapping any provider touches only adapters + config |
| Docker Compose deploy | `docker compose up` brings up API, Postgres, Redis, Qdrant |

### Out (explicitly deferred)

- Voice (STT/TTS/live) — Phase 2
- Code intelligence beyond plain-text code search — Phase 3
- Vision — Phase 4
- Browser/desktop automation — Phases 5–6
- Planning/reflection loops — Phase 7
- Telegram, Tailscale remote access — Phase 8
- Multi-user, SaaS, fine-tuning — out of scope entirely (PRD §4)

## 2. MVP Acceptance Scenarios

1. **Cold-start memory:** Tell Alan_T "I prefer TypeScript over JavaScript." Restart all services. Ask "what language do I prefer?" → correct answer from long-term memory.
2. **Personal RAG:** Ingest a folder of notes. Ask a question answerable only from those notes → correct answer with file citation, < 3 s retrieval.
3. **Rate-limit resilience:** Saturate Groq free-tier RPM. Next chat message → answered via Google fallback (or queued with honest feedback), no crash, no silent failure.
4. **Provider swap drill:** Change `CHAT` role from `llama-3.3-70b-versatile` to `gemini-2.5-flash` in config only. Restart. Everything works. *(This drill is the test of A2 — run it before calling MVP done.)*
5. **Context continuity:** 10-turn conversation with follow-ups ("what about the second one?") resolves references correctly.

## 3. MVP Non-Goals

- No streaming-token UI polish — basic streaming is enough.
- No fancy memory consolidation — nightly summarization job is Phase 2+ ([MEMORY_CONSOLIDATION.md](../memory/MEMORY_CONSOLIDATION.md)).
- No reranking model in RAG v1 — vector + keyword hybrid only.
- No auth beyond a single local API token (single-user, localhost/Tailscale only).

## 4. MVP Risks

| Risk | Mitigation |
|---|---|
| Free-tier embedding quota too small for initial corpus | Content-hash embedding cache; incremental indexing; ingest queue with backoff ([INGESTION_PIPELINE.md](../knowledge/INGESTION_PIPELINE.md)) |
| Free-tier model deprecation/changes | Role registry makes any model a config swap; pin nothing in code |
| Fact extraction pollutes long-term memory | Confidence threshold + user-visible memory review ([MEMORY_ARCHITECTURE.md](../memory/MEMORY_ARCHITECTURE.md)) |
| Latency of cloud round-trips | Groq for hot paths (router, chat); Gemini reserved for long-context/vision |
