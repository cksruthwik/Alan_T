# Code Agent

Phase: 3 · Model roles: `CODER` (`qwen/qwen3-32b` → `openai/gpt-oss-120b` → `gemini-2.5-pro`), `LONG_CONTEXT` for whole-repo questions
Indexing: code-aware chunking in [CHUNKING_STRATEGY.md](../knowledge/CHUNKING_STRATEGY.md) §2

## Responsibility

Questions and tasks over indexed repositories: search, explanation, dependency answers, doc generation, code generation in-context. Read-only — Alan_T does not edit repos in the MVP era (generation outputs go to chat/notes, never to files).

## Tools

`code_search` (ALLOW) · `read_file_lines` (ALLOW) · `repo_overview` (ALLOW).

## Behaviors

- **"Where is X / how does Y work":** `code_search` (hybrid — embeddings catch concepts, FTS catches exact identifiers; both legs mandatory for code) → `read_file_lines` to pull real context around hits → explanation with `repo/path.py:start-end` citations. The Phase 3 exit bar: every code claim resolvable to file:line.
- **Read vs inferred discipline** (`code_explain.j2`): "this function does X (read from src/a.py:40-60)" vs "callers likely rely on Y (inferred)" — explicitly distinguished, always.
- **Whole-repo questions** ("what's the architecture of repo X"): `repo_overview` (symbol tree + dependency summary from the index) + LONG_CONTEXT assembly of key files. Gemini's 1M context is the budget here, not a license — assembly stays selective, repo dumps don't fit quota.
- **Code generation:** in-repo idiom matching — retrieval pulls neighboring code first so generated code reads like the codebase, not like a tutorial.
- **Doc generation:** docstrings/READMEs produced from read code, citing what was read; gaps stated ("tests/ not indexed — coverage claims omitted").

## Indexing Notes

- Mounts of type `git_repo_set` ([AI_VFS.md](../knowledge/AI_VFS.md) §4): tracked files at HEAD, `.gitignore` respected; `repo`, `lang`, `symbol`, line ranges in payload ([QDRANT_SCHEMA.md](../data/QDRANT_SCHEMA.md)).
- Re-index trigger: watcher on HEAD change (post-commit), not per-keystroke — the index serves questions, not autocomplete.

## Degradation & Limits

- Unindexed repo asked about → say so + offer `ingest_path`, never answer from model memory of "typical projects".
- Symbol-graph expansion (callers/callees) is the recorded Phase 3+ upgrade ([RAG_PIPELINE.md](../knowledge/RAG_PIPELINE.md) §6); v1 is chunks + lines, honestly limited on deep call-chain questions.
