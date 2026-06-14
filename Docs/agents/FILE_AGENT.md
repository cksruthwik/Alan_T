# File Agent

Milestone: **M2** · Model purposes: `CHAT` (answers), `LONG_CONTEXT` (large assemblies), `SUMMARIZER` (rewrite/citation check)
Pipeline: [KNOWLEDGE.md](../knowledge/KNOWLEDGE.md) §4 — this agent is its primary operator

## Responsibility

Questions over the user's ingested knowledge: notes, documents, PDFs, transcripts. (A dedicated Code Agent is deferred; until then File handles code-in-notes questions directly.)

## Tools

`search_knowledge` (ALLOW) · `read_source` (ALLOW) · `ingest_path` (ASK — new tree = new cloud egress).

## Behaviors

- **Question answering:** full RAG pipeline — scope resolution, optional rewrite, hybrid retrieval, assembly, cited answer, citation check. The honesty contract ([KNOWLEDGE.md](../knowledge/KNOWLEDGE.md) §4) is this agent's identity: empty retrieval gets an honest "nothing found", never fluent invention.
- **Summarization requests** ("summarize my notes on X"): retrieval breadth raised, LONG_CONTEXT model, output structured by source.
- **Source navigation:** "show me that file/section" → `read_source` on a prior citation — citations are interactive handles, not decoration.
- **Ingestion requests:** "index my ~/Papers folder" → preview (file count, types, estimated embedding quota cost from [KNOWLEDGE.md](../knowledge/KNOWLEDGE.md) §1) → ASK confirm → enqueue → report via `/ingest/status` semantics.
- **Comparison/multi-doc questions:** answered from union retrieval with the limitation stated; sub-query decomposition is a later upgrade ([KNOWLEDGE.md](../knowledge/KNOWLEDGE.md) §5).

## Degradation Ladder

1. Vector search down → keyword-only search (Postgres FTS), flagged.
2. FTS also unavailable → honest inability ("can't search your files right now"), no guessing.
3. Rewrite skipped under quota → flagged in trace; user told only when relevance visibly suffers.

## Quality Bars

- Every claim about user documents cited (`citation validity > 95%` eval, [TEST_STRATEGY.md](../testing/TEST_STRATEGY.md)).
- hit@5 > 85% on the personal eval set; misses become new eval cases.
