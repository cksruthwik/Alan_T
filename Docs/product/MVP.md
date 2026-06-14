# Alan_T — MVP Definition

Version: 0.2
Status: Active — maps to milestones **M0–M2** in [BUILD_ORDER.md](../BUILD_ORDER.md)

The MVP answers one question: **can Alan_T hold a contextual conversation, remember things
across sessions, and answer questions over your own files — reliably, on free-tier APIs,
reachable from your phone?**

## 1. Scope (M0–M2)

### In

| Capability | Milestone | Definition of done |
|---|---|---|
| Text chat | M0 | Multi-turn conversation via FastAPI `/chat`; context survives a restart |
| Model seam | M0 | One LiteLLM call over Groq + Google + NVIDIA NIM; fallback on rate limit; model/order from env |
| Long-term memory | M1 | Explicit "remember this" + recall by relevance (Mem0 + Postgres); survives restart |
| Document ingestion | M2 | Point Alan_T at folders; Markdown/PDF/text/code ingested, chunked, embedded into **pgvector** (via ai-vfs) |
| Semantic search + RAG | M2 | "What do my notes say about X?" answered with a file citation, < 3 s retrieval |
| Reach from phone | M2 | Telegram (text + files); single-user allowlist |
| Docker Compose deploy | M0–M2 | `docker compose up` brings up **api + postgres (pgvector)** |

### Out (later milestones)

Supervisor routing + skills (M3) · Notes + Calendar (M4) · Voice (M6) · Browser, Planning,
Reflection, Research, Automation (deferred) · Vision (dropped) · multi-user / SaaS / fine-tuning (never).

## 2. Acceptance scenarios (the standing tests)

1. **Cold-start memory:** "I prefer TypeScript over JavaScript." → restart all services → "what language do I prefer?" → correct answer from long-term memory.
2. **Personal RAG:** ingest a folder of notes → ask a question answerable only from them → correct answer with file citation, < 3 s retrieval.
3. **Rate-limit resilience:** saturate Groq's free-tier RPM → next message answered via the Google/NVIDIA fallback (or queued with honest feedback) — no crash, no silent failure.
4. **Provider swap:** change the CHAT model / fallback order in env → restart → everything works (proves the LiteLLM seam, ADR-020).
5. **Context continuity:** 10-turn conversation with follow-ups ("what about the second one?") resolves references correctly.

## 3. Non-goals

- No streaming-UI polish — basic streaming is enough.
- No memory consolidation — nightly summarization is deferred.
- No reranking in RAG v1 — vector + keyword hybrid only.
- No auth beyond a single API token (single-user, localhost/Tailscale).

## 4. Risks

| Risk | Mitigation |
|---|---|
| Free-tier embedding quota too small for the corpus | content-hash embedding cache; incremental indexing; ingest queue with backoff ([../knowledge/KNOWLEDGE.md](../knowledge/KNOWLEDGE.md)) |
| Free-tier model deprecation | model is a config value, fallback chain across three providers; nothing pinned in code |
| Fact extraction pollutes memory | confidence threshold + user-visible memory review ([../memory/MEMORY_ARCHITECTURE.md](../memory/MEMORY_ARCHITECTURE.md)) |
| Cloud round-trip latency | Groq for hot paths (chat); Gemini reserved for long-context |
