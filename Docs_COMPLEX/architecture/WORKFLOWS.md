# Alan_T — Core Workflows

Version: 0.1
Status: Active

Step-by-step flows for the system's main operations. These are the sequences tests assert against ([TEST_STRATEGY.md](../testing/TEST_STRATEGY.md)).

## W1 — Chat Turn (Phase 1)

1. Client sends message over WebSocket (or POST) with `session_id`.
2. API normalizes to `UserTurn`, appends to session window (Redis).
3. `load_context`: recall top-k relevant long-term memories (Postgres, keyword + recency + embedding similarity).
4. Supervisor classifies intent (ROUTER: `llama-3.1-8b-instant`).
5. Routed agent runs; any model call goes ModelRouter → quota check → provider adapter → fallback on `RateLimited`.
6. Response streams to client; first token target < 1.5 s.
7. Turn persisted to Postgres (`conversation_turns`); fact-extraction job enqueued (Redis queue) — does not block.
8. LangGraph checkpoint written.

**Degradation:** memory recall fails → proceed, flag `degraded:["memory_recall"]`, tell the user only if it affects the answer.

## W2 — RAG Answer (Phase 1)

1. File Agent receives question.
2. Query rewrite (SUMMARIZER model): conversational query → standalone search query (skipped if already standalone).
3. Hybrid retrieval: Qdrant vector search (gemini-embedding-001 of query) + keyword search, merged via RRF. Top 8 after merge.
4. (Phase 3+) Rerank to top 4.
5. Answer generation (CHAT, or LONG_CONTEXT if assembled context > 24k tokens) with mandatory citation instruction.
6. Citations rendered as `source_path#chunk` links; uncited claims about user documents are a defect.
7. If retrieval returns nothing relevant: say so explicitly — never improvise an answer about the user's files.

Full pipeline detail: [RAG_PIPELINE.md](../knowledge/RAG_PIPELINE.md).

## W3 — Document Ingestion (Phase 1)

1. Trigger: watcher event (file added/changed), manual `POST /ingest`, or scheduled re-scan.
2. Worker pulls job from Redis queue.
3. AI-VFS resolves source → raw content + metadata.
4. Content hash checked against `ingest_ledger` (Postgres) — unchanged content is skipped (quota protection).
5. Parse (per type) → chunk ([CHUNKING_STRATEGY.md](../knowledge/CHUNKING_STRATEGY.md)) → embed (batched, rate-limit-aware) → upsert to Qdrant with payload.
6. Ledger updated; deleted source files trigger vector deletion (tombstone scan).

Full pipeline: [INGESTION_PIPELINE.md](../knowledge/INGESTION_PIPELINE.md).

## W4 — Voice Note (Phase 2)

1. Audio arrives (web upload or Telegram voice note).
2. STT: `whisper-large-v3-turbo` (Groq) → transcript.
3. Transcript enters W1 as a normal user turn (tagged `modality:voice`).
4. Reply → TTS (Gemini) → audio returned alongside text.
5. Both transcript and reply text persist to conversation history.

## W5 — Live Voice (Phase 2)

1. Client opens WS `/voice/live`; server bridges to Gemini Live API session.
2. Server injects context (persona prompt + recalled memories) at session start.
3. Tool calls from the live session route through the same permission layer as text.
4. Session transcript captured and persisted on close; fact extraction runs on it.

## W6 — Agentic Task (Phase 7)

1. User states a goal; supervisor routes to Planner.
2. Planner (REASONER: `openai/gpt-oss-120b`) emits task DAG with per-step agent, tools, success criteria.
3. Plan shown to user for approval if any step touches ASK/DENY-tier tools.
4. Executor runs steps; each step's result goes to Reflection (REFLECTOR: `deepseek-r1-distill-llama-70b`).
5. Verdict: success → next step; retry (≤2/step); replan (≤2/task); abort → honest failure report with completed-so-far summary.
6. Every step audited; long tasks checkpoint per step and are resumable.

## W7 — Scheduled Automation (Phase 7)

1. Scheduler fires job (e.g., daily digest 08:00).
2. Automation Agent gathers inputs (calendar, recent memory, task list) via ports.
3. SUMMARIZER model composes digest; delivered via MessagingGateway (Telegram) or stored for next session greeting.
4. Job result + cost (tokens used) logged to metrics.

## W8 — Telegram Round Trip (Phase 8)

1. Telegram update → gateway validates sender against single allowed `user_id` (hard reject otherwise).
2. Text → W1; voice → W4; file → W3 (with confirmation).
3. Replies chunked to Telegram limits; voice replies sent as voice notes when the user spoke first.
