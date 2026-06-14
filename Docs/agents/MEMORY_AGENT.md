# Memory Agent

Milestone: **M1** · Model purpose: `SUMMARIZER` (`gemini-2.5-flash-lite` → `llama-3.1-8b-instant`)
Architecture: [MEMORY_ARCHITECTURE.md](../memory/MEMORY_ARCHITECTURE.md) · Backed by **Mem0** over Postgres

## Responsibility

All reads and writes of long-term memory: explicit remember/forget, post-turn fact extraction (as the background worker job), recall formatting, and the "what do you know about me?" surface. Other agents consume recalled memory via `AgentContext`; only this agent writes it. Memory is backed by **Mem0** — Alan_T's own confidence-gated layer is a later upgrade earned by evidence, not built up front (ADR-016).

## Tools

`remember_fact` (ALLOW) · `recall_memory` (ALLOW) · `forget_memory` (ASK) — see [TOOL_CATALOG.md](../ai/TOOL_CATALOG.md).

## Behaviors

### Explicit remember
"Remember that X" → store at confidence 1.0, kind inferred (preference/fact/goal), confirmation echoed back with the stored wording — the user should see exactly what was saved.

### Post-turn extraction (worker job, not in the response path)
`fact_extract.j2` over each completed turn → candidate JSON → gates from [MEMORY_ARCHITECTURE.md](../memory/MEMORY_ARCHITECTURE.md) §3: ≥0.8 store, 0.5–0.8 store+flag, <0.5 drop, >0.92 similarity → merge. Extraction prompt is conservative by instruction: *durable* facts only — no transient state ("user is debugging X today" is an episode, not a fact), no inferences beyond the text.

### Recall ("what do you know about me?", "what did we decide about X?")
- Inventory questions → grouped listing by kind with dates and sources, honest about flagged/unconfirmed items.
- Topical questions → scored recall ([MEMORY_ARCHITECTURE.md](../memory/MEMORY_ARCHITECTURE.md) §4) + the `memory` pgvector collection for episodes; answers cite the memory's origin ("you told me on 2026-05-02…" vs "I inferred this from our session on…"). The explicit/extracted distinction is always surfaced — inferred memories presented as user statements would be trust poison.

### Forget
ASK-tier confirm → soft delete (7-day window) → hard delete + vector removal. "Forget everything about X" expands to the matching item list shown *before* the confirm.

## Quality Bars

- Extraction precision > recall: a missed fact costs a future re-statement; a wrong fact costs trust. Eval set gates extraction prompt changes.
- No memory writes during degraded extraction (model fallback exhausted) — queue retries instead; memory corruption is worse than memory lag.
