# Alan_T — LLM Strategy

Version: 0.3
Status: Active — lean scope ([BUILD_ORDER.md](../BUILD_ORDER.md))
Governing decisions: ADR-011 (LiteLLM), ADR-020 (lean seam + 3-provider fallback) in [DECISION_LOG.md](../architecture/DECISION_LOG.md)

## 1. Principles

**Architecture (permanent, vendor-agnostic):**

1. **One LiteLLM seam.** Every model call — chat, embeddings, later STT/TTS — goes through a single function. Core code never names a provider directly; the model + fallback order come from env/config.
2. **Any model, any vendor.** Because the seam is LiteLLM, any provider it speaks to is selectable by config. Swapping a model is a config edit, never a code change. Returning to local Ollama later is the same edit (the ADR-001 escape hatch).
3. **Fallback chains, not failures.** Primary unavailable/rate-limited → next in chain → queue or honest error. Never a silent hang.

**What the lean build deliberately does NOT have yet** (added only when a real swap forces it — ADR-020):
- No role registry — agents reference a model purpose (chat / reasoner / embedder) resolved from a flat config, not a YAML role→model matrix with 14 roles.
- No `free`/`paid`/`local` profile system — one config, model names from env.
- No capability-gate bootstrap — add it the day a swap actually breaks on a missing capability.

## 2. The three free providers (the fallback chain)

Three **independent** free-tier quotas behind one seam. When Groq rate-limits, fall through to Google, then NVIDIA NIM. This is what makes "rate-limit resilience" (MVP scenario #3) real rather than theoretical.

| Provider | Access | Good for | Notes |
|---|---|---|---|
| **Groq** | free tier | fast chat (Llama 3.3 70B), Whisper STT | high RPM, low latency — the hot path |
| **Google AI Studio** | free tier | long-context (Gemini 2.5, 1M), embeddings, TTS, Live (M6) | the multimodal/long-context leg |
| **NVIDIA NIM** (build.nvidia.com) | free/preview credits | reasoning (DeepSeek-R1, Qwen) | OpenAI-compatible; treat as rate-limited, not unlimited |

Treat all three as **rate-limited free tiers in a fallback chain**, not one big pool.

## 3. Model purposes (flat config, not a registry)

Agents ask for a model by a small purpose label; config maps it to a primary + fallback chain. This is the *lean* form of what was a 14-role registry — start with what M0–M4 actually use, grow only as needed.

| Purpose | Used by | Primary (default) | Fallback chain |
|---|---|---|---|
| `CHAT` | Conversation, File, Notes, Calendar | `llama-3.3-70b-versatile` (Groq) | `gemini-2.5-flash` → `nvidia/...` |
| `ROUTER` | Supervisor (M3) | `llama-3.1-8b-instant` (Groq) | `gemini-2.5-flash-lite` |
| `LONG_CONTEXT` | File agent on large inputs | `gemini-2.5-pro` | `gemini-2.5-flash` |
| `REASONER` | complex queries (later agents) | `deepseek-r1` (NVIDIA NIM) | `gemini-2.5-pro` |
| `EMBEDDER` | ingestion, retrieval, memory | `gemini-embedding-001` | — (no fallback by design — §5) |
| `SUMMARIZER` | memory extraction, query rewrite | `gemini-2.5-flash-lite` | `llama-3.1-8b-instant` |
| `STT` (M6) | voice notes | `whisper-large-v3-turbo` (Groq) | `whisper-large-v3` |
| `TTS` (M6) | voice replies | Gemini TTS | — |

Example config (`config/models.yaml`):

```yaml
CHAT:
  primary:   { provider: groq,   model: llama-3.3-70b-versatile, temperature: 0.7 }
  fallbacks:
    - { provider: google, model: gemini-2.5-flash }
    - { provider: nvidia, model: deepseek-ai/deepseek-r1 }
```

`provider:` accepts any LiteLLM provider id (`groq`, `google`, `nvidia`/openai-compatible base URL, and later `ollama`, `openai`, `anthropic`…). New models are adopted by editing config after a quick quality pass — never by code change.

## 4. The seam + ModelRouter

```python
# One function. Core domain types only — no LiteLLM types cross this line.
async def complete(purpose: str, req: ChatRequest) -> ChatResponse: ...
async def stream(purpose: str, req: ChatRequest) -> AsyncIterator[ChatDelta]: ...
async def embed(texts: list[str]) -> list[Vector]: ...
```

The thin **ModelRouter** wraps the seam:

```
resolve(purpose) → config entry (primary + fallback chain)
  → quota pre-check (per provider+model+window)
  → primary call via LiteLLM
  → on RateLimited/Unavailable: next in fallback chain
  → on chain exhausted: enqueue (background) or raise HonestFailure (interactive)
  → always: log {purpose, model, latency, tokens, fallback_depth} → metrics
```

LiteLLM (SDK mode) provides the unified API, retry/backoff, and fallback execution. Ours: purpose resolution, quota windows, the EMBEDDER no-fallback rule (§5), and logging/redaction.

## 5. Embedding-space discipline

Changing the embedding model **invalidates every vector** — so `EMBEDDER` is the one purpose swapping is deliberately *hard* for (friction, not lock-in):

- **No automatic fallback** — a silent embedder switch would corrupt the search space.
- Embedding model + dimension stamped into every pgvector collection's metadata; the adapter refuses cross-model upserts (hard error).
- A model change is an explicit re-embedding migration (worker job, ledger-driven, resumable).
- Embeddings cached by content hash in Postgres — re-ingestion of unchanged content costs zero quota.

## 6. Free-tier quota management

Free tiers impose RPM/RPD/TPM limits that change without notice:

1. **Budget tracking:** counters per (provider, model, window), configured conservatively below published caps.
2. **Pre-flight check:** ModelRouter refuses a call to an exhausted-window model → immediate fallback, no wasted call.
3. **Backoff:** 429s respect `Retry-After`; jittered exponential backoff for background jobs.
4. **Hot/cold separation:** bulk jobs (ingestion) run throttled; never compete with interactive traffic when avoidable.
5. **Honest degradation:** everything exhausted → user told "rate-limited until ~HH:MM", never a silent hang.
6. **Cost telemetry:** daily token usage per purpose/provider in metrics — the dataset that later justifies adding a `paid` config.

## 7. Honest constraints

- **`EMBEDDER`** — swappable, but a swap is a re-embed migration (§5). Friction, not lock-in.
- **NVIDIA NIM free tier** is credit/preview-limited, not unlimited — good as a REASONER leg behind the seam, not as a primary hot path.
- **Voice (M6)** — native realtime speech-to-speech would be Gemini-specific; the neutral path is composed `STT → CHAT → TTS`, which works on any provider. Deferred to M6 either way ([../voice/VOICE_ARCHITECTURE.md](../voice/VOICE_ARCHITECTURE.md)).

## 8. Model swap procedure

1. Add candidate to the purpose's fallback chain (or change primary) in config.
2. Run the purpose's eval set (`tests/evals/` — small, curated).
3. Compare quality/latency/quota-cost; promote by config edit; record in [DECISION_LOG.md](../architecture/DECISION_LOG.md) if it's a default change.
4. Re-run the provider-swap drill (MVP acceptance #4) — the standing test that the seam stays honest.

## 9. Prompting conventions

System prompts, persona, per-agent templates: [PROMPTS.md](PROMPTS.md). Tool schemas: [TOOL_CATALOG.md](TOOL_CATALOG.md).
