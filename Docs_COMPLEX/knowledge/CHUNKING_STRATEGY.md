# Alan_T — Chunking Strategy

Version: 0.1
Status: Active

How content is cut before embedding. Chunking quality bounds retrieval quality — garbage cuts make every downstream stage worse.

## 1. Principles

1. **Cut on meaning, not on character counts.** Parser structure (headings, symbols, pages) defines boundaries; size limits only force splits within a unit.
2. **Every chunk must stand alone.** A chunk is what the model sees at answer time — it carries its own context header (title path / symbol path).
3. **Deterministic IDs.** `chunk_id = hash(vpath, structural_path, position)` — re-ingestion overwrites in place, no duplicates.
4. **Targets, not dogma:** ~256–512 tokens body, 10–15% overlap for prose; code follows symbol boundaries instead.

## 2. Per-Type Strategies

### Prose (Markdown, notes, HTML→text)
- Split on heading hierarchy first; sections > 512 tokens split on paragraph boundaries with overlap.
- Context header prepended: `"[Notes] Alan_T design > Memory > Recall scoring"` (mount + heading path).
- Tiny trailing sections (< 40 tokens) merge into the previous chunk.
- Obsidian wikilinks preserved in payload metadata (future graph features).

### Code (tree-sitter)
- One chunk per top-level symbol (function/class/method); oversized symbols split at nested-block boundaries with the signature repeated in each part's header.
- Context header: `"[repo:ai-vfs] src/mount.py > class MountTable > def resolve"`.
- File-level docstring/imports form one "file overview" chunk per file.
- Payload carries `start_line`/`end_line` → enables `file:line` citations (Phase 3 exit criterion).

### PDF
- Heading detection where extractable; fallback: page-window chunks (1 page, 20% overlap) with `page` in payload for citation.
- Scanned PDFs: OCR'd page text chunked as prose.

### Conversation transcripts / episodes
- One chunk per episode summary (already consolidation-sized — [MEMORY_CONSOLIDATION.md](../memory/MEMORY_CONSOLIDATION.md) Pass 1). Raw turns are NOT embedded (noise; the log stays in Postgres).

### Email (P3)
- One chunk per message (subject + stripped body); long threads: one per message, thread ID in payload.

## 3. Chunk Record (what gets embedded & stored)

```
embedded text   = context_header + "\n\n" + body
payload         = { vpath, mount, content_hash, structural_path,
                    start_line?, end_line?, page?, mtime, doc_type, tags[] }
```

Payload schema is normative in [QDRANT_SCHEMA.md](../data/QDRANT_SCHEMA.md).

## 4. Known Trade-offs / Revisit Triggers

- Overlap costs quota (~10–15% extra embedding volume) — accepted for recall; revisit if bootstrap quota pain dominates.
- No semantic (embedding-distance) chunking in v1 — it doubles embedding cost for marginal gain at this corpus size. Revisit with evidence from retrieval metrics.
- Context headers slightly bias vectors toward titles — accepted; headers also massively help the answering model. Revisit only if retrieval evals show title-drift.
- Parent-document retrieval (small chunks for search, big windows for answers) is a Phase 3 candidate, noted in [RAG_PIPELINE.md](RAG_PIPELINE.md) §6.
