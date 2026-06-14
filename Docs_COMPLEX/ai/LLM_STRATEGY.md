# Alan_T — LLM Strategy

Version: 0.2
Status: Active
Governing decisions: ADR-002 (ports), ADR-004 (role registry), ADR-011 (LiteLLM), ADR-017 (provider neutrality) in [DECISION_LOG.md](../architecture/DECISION_LOG.md)

## 1. Principles

Two layers, kept strictly separate — conflating them is how a system drifts into vendor lock-in.

**Architecture (permanent, vendor-agnostic):**

1. **Agents request roles, never models.** Model names exist only in the registry config; core code never names a provider or model.
2. **Any model, any vendor — OSS or paid.** The provider leg is LiteLLM (ADR-011); any provider it speaks to is selectable by config. Swapping a model is a config edit, never a code change.
3. **Swapping must be safe, not just possible.** Every role declares the capabilities it needs; a model that can't satisfy its role is rejected at startup, not discovered at runtime (§5).
4. **Fallback chains, not failures.** Primary unavailable/rate-limited → next in chain → queue or honest error.

**Current default configuration (the `free` profile — chosen, not load-bearing):**

5. **Groq for hot paths** in the default profile — fastest free inference for routing, chat, coding.
6. **Google for what the free profile needs beyond Groq** — long context (1M), vision, embeddings, TTS, live voice.
7. **Free-tier quota is the default profile's budget** — the ModelRouter enforces it (§7). This concern largely evaporates under the `paid` or `local` profiles.

Principles 5–7 describe *the profile we ship by default*, not the system. Run Alan_T entirely on local Ollama or entirely on OpenAI and principles 1–4 still hold unchanged.

## 2. Provider Neutrality & Model Swapping

### The provider universe

Anything LiteLLM addresses is a one-line config target. Concretely:

| Class | Providers (examples) | Typical use |
|---|---|---|
| **OSS / local** | Ollama, vLLM, LM Studio, HuggingFace TGI, llama.cpp server | fully offline, zero-cost, max privacy (the ADR-001 escape hatch realized) |
| **Paid hosted** | OpenAI, Anthropic, Google Vertex, AWS Bedrock, Azure OpenAI, Mistral, Together, Fireworks | quality/SLA when a workload outgrows free tiers |
| **Free hosted** | Groq, Google AI Studio | the default `free` profile |
| **Aggregators** | OpenRouter | one key, many models, easy A/B |

### Config profiles

A profile is a complete role→model mapping in `config/models.<profile>.yaml`, selected by `ALAN_MODEL_PROFILE` (default `free`). Switching the profile is the whole-system model swap — nothing else changes.

| Profile | Roles resolve to | When |
|---|---|---|
| `free` (default) | Groq + Google free tier | day-to-day, zero cost |
| `paid` | OpenAI + Anthropic | quality-critical work, no rate-limit friction |
| `local` | Ollama / vLLM on the host or LAN | fully offline, nothing leaves the machine |

Profiles are first-class equals — `free` is not privileged in the code, only in the default env var. A mixed profile (e.g. local CHAT, paid REASONER) is just another file.

### What swapping looks like

"Move CHAT to Claude": edit one registry entry, `provider: anthropic, model: claude-...`. "Run everything locally": `ALAN_MODEL_PROFILE=local`. Either way the bootstrap capability gate (§5) verifies the new models before the system accepts traffic, and the provider-swap drill (MVP acceptance #4) is the standing test that this stays true.

## 3. Role Registry

Agents resolve a **role**; the registry maps role → (provider, model, params) + fallback chain. The table below is the **`free` profile** (default). `paid` and `local` profiles map the same roles to different models.

| Role | Used by | `free` primary | `free` fallback chain | Notes |
|---|---|---|---|---|
| `ROUTER` | Supervisor intent classification | `llama-3.1-8b-instant` (Groq) | `gemini-2.5-flash-lite` | constrained output; temp 0; < 300 ms target |
| `CHAT` | Conversation, File, Calendar, Notes agents | `llama-3.3-70b-versatile` (Groq) | `gemini-2.5-flash` → `meta-llama/llama-4-scout-17b-16e-instruct` | main workhorse |
| `REASONER` | Planner, Browser agent, complex queries | `openai/gpt-oss-120b` (Groq) | `gemini-2.5-pro` | deep multi-step reasoning |
| `LONG_CONTEXT` | File/Code agents on large inputs | `gemini-2.5-pro` | `gemini-2.5-flash` | 1M context; whole-repo / many-doc analysis |
| `CODER` | Code agent | `qwen/qwen3-32b` (Groq) | `openai/gpt-oss-120b` → `gemini-2.5-pro` | code search/explain/generate |
| `VISION` | Vision, Browser, Desktop agents | `gemini-2.5-flash` | `gemini-2.5-pro` | VQA, OCR, detection (ADR-006; openable — §8) |
| `EMBEDDER` | Ingestion, retrieval, memory recall | `gemini-embedding-001` | — (no fallback by design — §6) | single embedding space |
| `STT` | Voice notes, transcription | `whisper-large-v3-turbo` (Groq) | `whisper-large-v3` | turbo realtime; v3 accuracy |
| `TTS` | Voice replies | Gemini TTS (`gemini-2.5-flash-preview-tts`) | — | Kokoro (local) is the planned swap |
| `LIVE_VOICE` | Live voice mode | Gemini Live API | STT→CHAT→TTS pipeline | native S2S default (§8, ADR-007/014) |
| `REFLECTOR` | Reflection engine | `deepseek-r1-distill-llama-70b` (Groq) | `openai/gpt-oss-120b` | verdict reasoning over outcomes |
| `SUMMARIZER` | Memory extraction/consolidation, digests, query rewrite | `gemini-2.5-flash-lite` | `llama-3.1-8b-instant` | high-volume, cheap |
| `WEB_AGENT` | Research agent | `groq/compound` | `groq/compound-mini` | built-in web search + code execution |
| `IMAGE_GEN` | optional image tool | `imagen-4` | Gemini image preview models | not on any critical path |

### Role capability requirements

Each role demands a capability set. The bootstrap gate (§5) checks the configured model against this — *this* table is profile-independent; it's the contract every profile's models must satisfy.

| Role | Required capabilities |
|---|---|
| `ROUTER`, `SUMMARIZER` | `json_mode` |
| `CHAT` | `tools`, `streaming` |
| `REASONER`, `CODER` | `tools`, `min_context: 32k` |
| `LONG_CONTEXT` | `min_context: 200k` |
| `VISION` | `vision_in` |
| `EMBEDDER` | `embeddings` |
| `STT` | `audio_in` |
| `TTS` | `audio_out` |
| `LIVE_VOICE` | `audio_in`, `audio_out`, `streaming` (native path); none extra for the composed fallback |
| `WEB_AGENT` | `tools` |

`provider:` accepts any LiteLLM provider id (`groq`, `google`, `openai`, `anthropic`, `ollama`, `vertex_ai`, `bedrock`, `openrouter`, `mistral`, `together_ai`, …). Newer models (e.g. Gemini 3.x) are adopted by editing a profile after a manual quality pass — never by code change.

## 4. The `LLMProvider` Port, Capability Contract, and ModelRouter

```python
class LLMProvider(Protocol):
    async def chat(self, req: ChatRequest) -> ChatResponse: ...
    async def chat_stream(self, req: ChatRequest) -> AsyncIterator[ChatDelta]: ...
    def capabilities(self, model: str) -> ProviderCapabilities: ...

# Capability contract — what a role checks against (§3, §5):
# ProviderCapabilities(
#     chat, streaming, tools, vision_in, json_mode,
#     embeddings, audio_in, audio_out, max_context: int)
#
# Core domain types (no provider/LiteLLM types cross this line):
# ChatRequest(messages, tools, temperature, max_tokens, response_format)
# ChatResponse(text, tool_calls, usage, finish_reason)
```

**ModelRouter** (core service, the single choke point):

```
resolve(role) → registry entry (from the active profile)
  → budget check (Redis counters per provider+model+window)
  → primary call via adapter
  → on RateLimited/ProviderUnavailable: next in fallback chain
  → on chain exhausted: enqueue (background jobs) or raise HonestFailure (interactive)
  → always: log {role, model, latency, tokens, fallback_depth} → metrics
```

**Implementation split (ADR-011):** the provider leg — unified API, retry/backoff, fallback execution, cost primitives — is LiteLLM (SDK mode) inside `LiteLLMAdapter`. Ours in the ModelRouter: role resolution, profile selection, role-level budgets, the EMBEDDER no-fallback discipline (§6), and logging/redaction hooks. LiteLLM types never cross the port boundary.

A profile's registry entry (example `config/models.free.yaml`):

```yaml
# provider: any LiteLLM provider id (groq | google | openai | anthropic | ollama | ...)
roles:
  CHAT:
    primary: { provider: groq, model: llama-3.3-70b-versatile, temperature: 0.7 }
    fallbacks:
      - { provider: google, model: gemini-2.5-flash }
      - { provider: groq, model: meta-llama/llama-4-scout-17b-16e-instruct }
```

The same role in other profiles — pure config, no code touched:

```yaml
# config/models.paid.yaml
CHAT: { primary: { provider: openai, model: gpt-4o } }
# config/models.local.yaml
CHAT: { primary: { provider: ollama, model: llama3.3 } }
```

## 5. Capability Gate at Bootstrap

The hard-fail gate that makes swapping safe (ADR-017). For each role in the active profile, `alan bootstrap` resolves the configured model's `ProviderCapabilities` and asserts they satisfy the role's requirements (§3). On any mismatch it **refuses to start**, naming `role / model / missing capability` — e.g. `CHAT → ollama/llama3.2 : missing 'tools'`. The system never accepts traffic on a model that can't do its job; a bad swap dies at startup, not mid-conversation.

**Where capability truth comes from** (hybrid, fail-loud on gaps):

1. **Introspection base:** LiteLLM model metadata (`supports_function_calling`, `supports_vision`, `get_model_info().max_input_tokens`, …) — zero maintenance, covers most hosted models automatically.
2. **Declared overrides:** `config/capabilities.yaml` — a small hand-maintained map that fills introspection's gaps. In practice this is local/OSS models (Ollama reports almost nothing) and any model whose LiteLLM metadata is missing or wrong. Shipped pre-populated for every model in the three default profiles, so `free`/`paid`/`local` all boot clean out of the box.
3. **Fail-loud on the unknown:** if a configured model has *no* capability data from either source for a capability its role demands, bootstrap fails with "can't verify X — add it to `capabilities.yaml`." Never default-allow (gate theater) and never silently default-deny (blocks valid swaps).

Runtime capability probing (calling each model with a tiny tool/vision probe at startup) was considered and deferred: it costs calls on every cold start and can't observe some capabilities (`max_context`) anyway. The introspection+override+fail-loud path is the v1; probing is the principled escalation if metadata proves unreliable in practice.

## 6. Embedding Space Discipline

Changing the embedding model **invalidates every vector in Qdrant** — so `EMBEDDER` is the one role swapping is deliberately *hard* for (friction, not lock-in):

- No automatic fallback — a silent embedder switch would corrupt the search space.
- Embedding model + dimension stamped into every Qdrant collection's metadata ([QDRANT_SCHEMA.md](../data/QDRANT_SCHEMA.md)); the adapter refuses cross-model upserts.
- A model change is an explicit re-embedding migration (worker job, ledger-driven, resumable — [DEPLOYMENT.md](../infra/DEPLOYMENT.md) §4).
- Cross-provider dimension differences matter (gemini-embedding-001 is 3072; a local BGE model is 768/1024) — the migration re-creates the collection at the new dimension.
- Embeddings cached by content hash in Postgres — re-ingestion of unchanged content costs zero quota.

## 7. Free-Tier Quota Management

Relevant chiefly under the `free` profile; the `paid`/`local` profiles largely retire it. Free tiers impose RPM/RPD/TPM/TPD limits that change without notice:

1. **Budget tracking:** Redis counters per (provider, model, window), configured per profile conservatively below published caps. LiteLLM budget primitives used where they map cleanly; role-level windows remain our counters.
2. **Pre-flight check:** ModelRouter refuses a call to an exhausted-window model → immediate fallback, no wasted call.
3. **Backoff:** 429s respect `Retry-After`; jittered exponential backoff for background jobs.
4. **Hot/cold separation:** bulk jobs (ingestion, consolidation) run on throttled queues; never compete with interactive traffic for the same window when avoidable.
5. **Honest degradation:** everything exhausted → user told "rate-limited until ~HH:MM", never a silent hang.
6. **Cost telemetry:** daily token usage per role/provider in metrics ([METRICS.md](../observability/METRICS.md)) — the dataset that later justifies switching a role (or the whole profile) to `paid` or `local`.

## 8. Honest Constraints

Where full neutrality has a real caveat — each named with its escape path, because pretending otherwise is the lie that erodes the whole guarantee:

- **`EMBEDDER`** — swappable, but a swap is a re-embed migration (§6). Friction, not lock-in.
- **`LIVE_VOICE`** — native realtime speech-to-speech is **Gemini-specific by choice** (quality/latency; ADR-007/014). The provider-neutral escape is the composed `STT → CHAT → TTS` pipeline, which works on any provider's models and is the documented fallback live path ([VOICE_ARCHITECTURE.md](../voice/VOICE_ARCHITECTURE.md)). The native path is the only place a single vendor sits on a default — and it degrades gracefully to neutral, never hard-fails.
- **`VISION`** — currently Gemini in all profiles, but genuinely openable: LiteLLM routes vision to GPT-4o, Claude, and local llava (via Ollama). The `paid`/`local` profiles can and should set `VISION` accordingly; the gate's `vision_in` requirement already enforces correctness regardless of provider.
- **Library-backend couplings (non-model ports):** the LangGraph checkpointer assumes Postgres; arq assumes Redis. Both sit behind ports (`RelationalStore`-adjacent, `CacheStore`/`Scheduler`) and are swappable in principle, but the chosen libraries carry those backend assumptions — an honest caveat on "every port swaps freely" ([ADD.md](../architecture/ADD.md) §3).

## 9. Model Evaluation & Swap Procedure

1. Add candidate to the role's fallback chain (or a new profile) in config.
2. Run the role's eval set (`tests/evals/` — small, curated, graded).
3. Compare quality/latency/quota-cost; promote to primary by config edit; record in [DECISION_LOG.md](../architecture/DECISION_LOG.md) if it's a default-profile change.
4. Bootstrap capability gate (§5) + provider-swap drill (MVP acceptance #4) re-run after any registry change.

## 10. Prompting Conventions

System prompts, persona, per-agent templates: [PROMPTS.md](PROMPTS.md). Tool schemas: [TOOL_CATALOG.md](TOOL_CATALOG.md).
