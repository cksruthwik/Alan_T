# File Agent

Phase: 1 · Model roles: `CHAT` (answers), `LONG_CONTEXT` (large assemblies), `SUMMARIZER` (rewrite/citation check)
Pipeline: [RAG_PIPELINE.md](../knowledge/RAG_PIPELINE.md) — this agent is its primary operator

## Responsibility

Questions over the user's ingested knowledge: notes, documents, PDFs, transcripts (code questions go to the Code Agent — the supervisor splits on "code-shaped" intent, and File hands off mid-task if a question turns out to be about code internals).

## Tools

`search_knowledge` (ALLOW) · `read_source` (ALLOW) · `ingest_path` (ASK — new tree = new cloud egress).

## Behaviors

- **Question answering:** full W2 pipeline — scope resolution, optional rewrite, hybrid retrieval, assembly, cited answer, citation check. The honesty contract ([RAG_PIPELINE.md](../knowledge/RAG_PIPELINE.md) §3) is this agent's identity: empty retrieval gets an honest "nothing found", never fluent invention.
- **Summarization requests** ("summarize my notes on X"): retrieval breadth raised (top 16, no rerank), LONG_CONTEXT model, output structured by source.
- **Source navigation:** "show me that file/section" → `read_source` on a prior citation — citations are interactive handles, not decoration.
- **Ingestion requests:** "index my ~/Papers folder" → preview (file count, types, estimated embedding quota cost from [INGESTION_PIPELINE.md](../knowledge/INGESTION_PIPELINE.md)) → ASK confirm → enqueue → report via `/ingest/status` semantics.
- **Comparison/multi-doc questions** (Phase 3+): sub-query decomposition per [RAG_PIPELINE.md](../knowledge/RAG_PIPELINE.md) §6; before that, answered from union retrieval with the limitation stated.

## Degradation Ladder

1. Qdrant down → keyword-only search (Postgres FTS), flagged.
2. FTS also unavailable → honest inability ("can't search your files right now"), no guessing.
3. Rerank/rewrite skipped under quota → flagged in trace; user told only when relevance visibly suffers.

## Quality Bars

- Every claim about user documents cited (`citation validity > 95%` eval, [TEST_STRATEGY.md](../testing/TEST_STRATEGY.md) §5).
- hit@5 > 85% on the personal eval set; misses become new eval cases.
