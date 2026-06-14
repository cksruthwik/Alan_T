# Alan_T — Test Strategy

Version: 0.1
Status: Active

What gets tested, at which layer, and what CI gates on. The architecture ([ADD.md](../architecture/ADD.md)) was chosen partly FOR testability — core on fakes, adapters on contracts.

## 1. The Pyramid (adapted for an LLM system)

```
        ┌──────────────┐   manual / phase acceptance scenarios (MVP.md §2)
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
- Targets: ModelRouter (fallback chains, budget refusal, chain exhaustion), **capability gate** (role-requirement satisfaction; a known-bad pairing like `CHAT`→no-tools-model is refused; an unknown capability fails loud rather than default-allow/deny — [LLM_STRATEGY.md](../ai/LLM_STRATEGY.md) §5), permission gate (tiers, promotions, session overrides, stale-approval timeout), memory scoring/dedup/contradiction logic, chunkers (golden-file tests per content type), RAG fusion (RRF determinism), plan validator (fabricated tools rejected, budget clamps).
- Import-direction lint (`import-linter`): `core/*` must not import `adapters/*` or any provider SDK — **CI-blocking**, this guards the entire ADR-002 premise mechanically.

## 3. Contract Tests (adapters, real services, opt-in)

- One suite per adapter asserting port semantics: LiteLLM adapter (auth, streaming, tool-call mapping, 429→`RateLimited` normalization, capability introspection — run against the active profile's providers), Qdrant (embedder-stamp refusal!, deterministic upsert idempotency, filter deletes), Postgres repos (against a real container), Redis.
- Run: locally with keys present (`pytest -m contract`); CI runs DB/Redis/Qdrant contracts via service containers; **cloud-provider contracts are a scheduled weekly job, not per-commit** (free-tier quota is budget — don't spend it on every push).
- A contract test failing after a provider "upgrade" is the early-warning system ADR-001 needs.

## 4. Graph & E2E Tests

- Graph tests: compiled LangGraph + in-memory checkpointer + FakeLLMProvider scripts — assert routing decisions, interrupt/resume on ASK tools, degraded-flag propagation, checkpoint resume mid-task.
- E2E: full compose in fake-provider mode ([INFRASTRUCTURE.md](../infra/INFRASTRUCTURE.md) §6) — the MVP acceptance scenarios as automated flows: cold-start memory, ingest→search→cited answer, rate-limit fallback (fake provider scripted to 429), provider-swap drill.
- **Provider-swap drill (the ADR-017 guard):** flip `ALAN_MODEL_PROFILE` (e.g. `free`→`local`), restart, assert (a) the capability gate passes for the new profile and (b) the full acceptance suite stays green — proving a whole-vendor swap is config-only. A deliberately broken profile (a role pointed at an incapable model) is asserted to fail the gate at bootstrap, not at runtime.

## 5. Evals (model quality — separate from correctness tests)

- Per-role curated sets in `tests/evals/`: router classification (~50 labeled utterances), **skill-selection** (representative utterances → expected skill fires, distractors → no skill fires — [SKILLS.md](../ai/SKILLS.md) §8), RAG set (~30 question/source/gist triples from the real corpus, [RAG_PIPELINE.md](../knowledge/RAG_PIPELINE.md) §5), fact-extraction precision set, plan-validity set.
- Run on: any prompt change, any registry change, weekly schedule. NOT on every commit (quota + flakiness discipline).
- Pass/fail thresholds (hit@5 > 85%, citation validity > 95%, router accuracy > 95%) — a threshold miss blocks the prompt/model change, not unrelated work.
- RAG metrics (faithfulness, context precision/recall) computed with **Ragas** (ADR-015) rather than hand-written judges.
- LLM-judge based evals always pin the judge model + version in the eval config.

## 6. What We Deliberately Don't Test

- Provider model quality regressions outside our eval scope — unwinnable; the registry swap is the remedy, not tests.
- UI pixel testing — personal tool, manual eyes suffice.
- Load/perf beyond a simple latency assertion in e2e (p95 first-token < 1.5 s with fakes) — single user.

## 7. CI Gates (per PR)

1. lint + typecheck (ruff, mypy --strict on `core/`)
2. import-direction check ← architectural guard
3. unit suite
4. DB/Redis/Qdrant contract suites (service containers)
5. e2e fake-provider suite
Weekly scheduled: cloud contract suites + full evals + backup-restore drill in a scratch dir.
