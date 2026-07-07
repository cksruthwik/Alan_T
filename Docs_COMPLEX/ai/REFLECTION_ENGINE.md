# Alan_T — Reflection Engine

Version: 0.1
Status: Active (implementation: Phase 7)

Evaluates task outcomes, decides retry/replan/abort, and feeds lessons back into memory. The honesty layer of autonomy: its job is to catch failure, not to declare success.

## 1. Inputs and Output

**Input per step:** the task spec (incl. `success_check`), the agent's `AgentResult` (artifacts, tool transcript, errors, degraded flags), and execution metadata (duration, retries so far).

**Output — verdict (schema-validated):**

```json
{
  "verdict": "success | retry_same | retry_adjusted | replan | abort",
  "confidence": 0.0,
  "evidence": ["calendar_write returned event_id evt_123",
               "calendar_read confirms event exists on 2026-06-20"],
  "failure_class": null,
  "adjustment": null,
  "lesson": null
}
```

Model role: `REFLECTOR` (`deepseek-r1-distill-llama-70b`, fallback `openai/gpt-oss-120b`) — reasoning-tuned models verbalize evidence chains well.

## 2. Evaluation Rules (encoded in `reflect.j2` + code)

1. **Evidence over claims.** An agent saying "done" is not evidence. Tool outputs are evidence. Where cheap verification exists (read-after-write: `calendar_read` after `calendar_write`), the engine runs it *in code* before the model ever judges.
2. **Degraded ≠ failed, but must be weighed.** A RAG answer flagged `degraded:["vector_store_down"]` cannot satisfy "find my notes on X".
3. **Classify failures:**
   - `transient` (rate limit, timeout, network) → `retry_same` after backoff
   - `input_error` (bad selector, wrong query) → `retry_adjusted` with a concrete adjustment
   - `plan_error` (step impossible as specified, missing dependency) → `replan`
   - `permission_denied` (user said no) → never retried; `replan` around it or `abort`
   - `capability_gap` (system genuinely can't do this) → `abort` with explanation
4. **Budgets enforced in code, not by the model:** ≤2 retries/step, ≤2 replans/run ([PLANNING_ENGINE.md](PLANNING_ENGINE.md) §5). The model recommends; the executor clamps.

## 3. Self-Consistency Guard

For external-action steps (calendar writes, browser interactions, desktop actions), a `success` verdict with confidence < 0.7 triggers one independent re-evaluation with a different REFLECTOR fallback model; disagreement → treated as `retry_adjusted` at best. Cheap insurance against rubber-stamping.

## 4. Lessons → Memory

Verdicts with a non-null `lesson` ("site X's login needs 2FA — ask user first", "repo Y's docs live in /docs not /wiki") are written to long-term memory as `lesson` facts via the Memory agent, tagged with task context. Recalled by the Planner on similar future goals. This is the system's only learning loop in the MVP era — deliberately simple and auditable.

## 5. Final Task Report

On terminal state (`done` or `abort`), the engine composes the user-facing report: goal, steps completed/failed (with evidence), anything left undone, lessons stored. Abort reports must answer "what did you finish, what's left, why" — a silent or vague abort is a defect.

## 6. Reflection Outside Phase 7

Two lightweight uses precede the full engine:

- **RAG self-check (Phase 1):** after `rag_answer`, a SUMMARIZER-model check that every claim maps to a cited chunk; uncited claims are stripped or the answer is flagged.
- **Ingestion sanity (Phase 1):** post-ingest verification job — sampled chunks must round-trip from search ([INGESTION_PIPELINE.md](../knowledge/INGESTION_PIPELINE.md) §7).
