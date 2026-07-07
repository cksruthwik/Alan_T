# Alan_T — RAG Pipeline

Version: 0.1
Status: Active

How a question becomes a cited answer over the user's own knowledge. Workflow W2 in [WORKFLOWS.md](../architecture/WORKFLOWS.md); this doc is the stage-by-stage specification.

## 1. Stages

```
question
  ─▶ scope resolution        # which mounts/types? ("in my notes" → mount:notes)
  ─▶ query rewrite           # SUMMARIZER: conversational → standalone (skip if standalone)
  ─▶ hybrid retrieval        # vector (Qdrant) ∥ keyword (BM25) → RRF fusion → top 8
  ─▶ rerank                  # Phase 3+: top 8 → top 4
  ─▶ context assembly        # dedupe, order, token budget, source tags
  ─▶ answer generation       # CHAT (or LONG_CONTEXT if context > 24k tokens)
  ─▶ citation check          # every claim maps to a cited chunk
  ─▶ answer + citations
```

## 2. Stage Rules

**Scope resolution** — explicit user scoping ("in my notes", "in repo X") → payload filters. No scope → all of `knowledge`. Memory questions ("what did we decide…") additionally search the `memory` collection.

**Query rewrite** — only when the question contains anaphora ("that", "the second one", "his") or is a fragment; detector is a cheap heuristic + ROUTER check. Rewrite quota cost: 1 small call; skipping when unneeded is the point.

**Hybrid retrieval** — vector search (query embedded via EMBEDDER) and keyword search run in parallel; fused with Reciprocal Rank Fusion. Keyword side (Postgres FTS over chunk text in MVP) catches exact identifiers/names that embeddings blur — non-negotiable for code and personal names.

**Rerank (Phase 3+)** — listwise rerank of top 8 → top 4 via a single SUMMARIZER-role call (no free dedicated reranker on these providers; an LLM-rerank is fine at top-8 scale). Skipped under quota pressure → flag `degraded:["rerank_skipped"]`.

**Context assembly** — dedupe near-identical chunks (same vpath ±1 position), order: highest-scored first, then adjacent-chunk stitching for readability. Budget: 6k tokens default. Each chunk introduced as `--- source: {vpath}#{position} ---`.

**Answer generation** — `rag_answer.j2` contract ([PROMPTS.md](../ai/PROMPTS.md)): answer only from provided chunks; cite `[vpath]` inline; if chunks don't contain the answer, say exactly that and optionally suggest where it might live. Code questions route to CODER role with `file:line` citation format.

**Citation check** — post-generation pass (cheap SUMMARIZER call, Phase 1's mini-reflection): claims without citation → stripped or answer flagged. Uncited assertions about the user's own documents are defects, full stop.

## 3. Honesty Contract (what makes personal RAG trustworthy)

1. Empty retrieval → "I didn't find anything about X in your files" — never a fluent improvisation.
2. Low-relevance retrieval (top score under threshold) → answer prefixed with uncertainty + what WAS searched.
3. Degraded pipeline (Qdrant down, rerank skipped) → stated in the answer when it could matter.
4. Citations link to reality: `vpath#position` resolves to the actual chunk via `read_source` (UI can expand them).

## 4. Quota Profile per Question

Typical: 1 embedding call + 0–1 rewrite + 1 answer call (+1 rerank +1 citation check when enabled) — ~2–4 small calls. Budget tracked per role in metrics; if RAG becomes the quota hog, the rewrite and citation-check stages are the configurable sacrifices, in that order.

## 5. Evaluation (keep it small and real)

- Curated eval set: ~30 (question, expected-source, expected-answer-gist) triples from the user's actual corpus, grown when failures occur.
- Metrics: retrieval hit@5 (expected source in top 5), answer faithfulness + context precision via Ragas (ADR-015), citation validity (mechanical).
- Run on every chunking/embedding/prompt change ([TEST_STRATEGY.md](../testing/TEST_STRATEGY.md) §6). Targets: hit@5 > 85% (PRD's retrieval-precision goal), citation validity > 95%.

## 6. Phase 3+ Upgrades (recorded, not promised)

- Parent-document retrieval (search small, answer big) — pairs with [CHUNKING_STRATEGY.md](CHUNKING_STRATEGY.md) §4.
- Repo-aware retrieval: symbol-graph expansion (pull callers/callees of a hit) for code questions.
- Multi-hop: decompose comparative questions into sub-queries (REASONER), answer over union.
- Qdrant native hybrid (sparse vectors) replacing the two-system fusion if Postgres FTS becomes the bottleneck.
