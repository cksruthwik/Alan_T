# Alan_T — Test Strategy

Version: 0.2
Status: Active — lean scope ([BUILD_ORDER.md](../BUILD_ORDER.md))

What gets tested, at which layer, and what CI gates on. The architecture ([SYSTEM_OVERVIEW.md](../architecture/SYSTEM_OVERVIEW.md)) was chosen partly FOR testability — core on fakes, adapters on contracts.

## 1. The Pyramid (adapted for an LLM system)

```
        ┌──────────────┐   manual / milestone acceptance scenarios (MVP.md §2)
        │  acceptance   │
        ├──────────────┤   evals: model-behavior quality (small, curated, run on change)
        │    evals      │
        ├──────────────┤   e2e: compose stack + fake providers, API-level flows
        │     e2e       │
        ├──────────────┤   contract: each adapter vs its real service (opt-in, keyed)
        │   contract    │
        ├──────────────┤   unit: core logic with fakes — the bulk
        │     unit      │
        └──────────────┘
```

## 2. Unit Tests (core, no network, milliseconds)

- Every port has a **fake** in `tests/fakes/` (FakeLLMProvider with scripted responses, InMemoryVectorStore, FakeClock…). Fakes are maintained first-class — they are the testing API of the system.
- Targets: ModelRouter (fallback chains across the 3 providers, budget refusal, chain exhaustion), permission gate (tiers, promotions, session overrides, stale-approval timeout), memory scoring/dedup/contradiction logic, chunkers (golden-file tests per content type), RAG fusion (RRF determinism).
- Import-direction lint (`import-linter`, added when the core/adapters split is real — not M0 day one): `core/*` must not import `adapters/*` or any provider SDK — **CI-blocking** once present, guarding the hexagonal premise mechanically.

## 3. Contract Tests (adapters, real services, opt-in)

- One suite per adapter asserting port semantics: LiteLLM seam (auth, streaming, tool-call mapping, 429→`RateLimited` normalization — run against Groq/Google/NVIDIA), pgvector (embedder-stamp refusal!, deterministic upsert idempotency, filter deletes), Postgres repos (against a real container).
- Run: locally with keys present (`pytest -m contract`); CI runs Postgres/pgvector contracts via service containers; **cloud-provider contracts are a scheduled weekly job, not per-commit** (free-tier quota is budget — don't spend it on every push).
- A contract test failing after a provider "upgrade" is the early-warning system ADR-001 needs.

## 4. Graph & E2E Tests

- Graph tests (from M3): compiled LangGraph + in-memory checkpointer + FakeLLMProvider scripts — assert routing decisions, interrupt/resume on ASK tools, degraded-flag propagation, checkpoint resume mid-task.
- E2E: full compose in fake-provider mode ([INFRASTRUCTURE.md](../infra/INFRASTRUCTURE.md) §7) — the MVP acceptance scenarios as automated flows: cold-start memory, ingest→search→cited answer, rate-limit fallback (fake provider scripted to 429), provider-swap drill.
- **Provider-swap drill (the ADR-020 guard):** change the CHAT model/fallback order in `config/models.yaml`, restart, assert the full acceptance suite stays green — proving a model swap is config-only.

## 5. Evals (model quality — separate from correctness tests)

- Curated sets in `tests/evals/`: RAG set (~30 question/source/gist triples from the real corpus, [KNOWLEDGE.md](../knowledge/KNOWLEDGE.md) §4), fact-extraction precision set, and (from M3) router classification (~50 labeled utterances) + **skill-selection** (representative utterances → expected skill fires, distractors → no skill fires — [SKILLS.md](../ai/SKILLS.md) §8).
- Run on: any prompt change, any model-config change, weekly schedule. NOT on every commit (quota + flakiness discipline).
- Pass/fail thresholds (hit@5 > 85%, citation validity > 95%, router accuracy > 95%) — a threshold miss blocks the prompt/model change, not unrelated work.
- RAG metrics (faithfulness, context precision/recall) computed with **Ragas** rather than hand-written judges. LLM-judge evals always pin the judge model + version.

## 6. What We Deliberately Don't Test

- Provider model quality regressions outside our eval scope — unwinnable; the model-config swap is the remedy, not tests.
- UI pixel testing — personal tool, manual eyes suffice.
- Load/perf beyond a simple latency assertion in e2e (p95 first-token < 1.5 s with fakes) — single user.

## 7. CI Gates (per PR)

1. lint + typecheck (ruff, mypy --strict on `core/`)
2. import-direction check (once the core/adapters split exists) ← architectural guard
3. unit suite
4. Postgres/pgvector contract suites (service containers)
5. e2e fake-provider suite
Weekly scheduled: cloud contract suites + full evals + backup-restore drill in a scratch dir.
