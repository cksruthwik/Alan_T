# Alan_T — Security Architecture

Version: 0.2
Status: Active — lean scope ([BUILD_ORDER.md](../BUILD_ORDER.md))

Threat model and controls for a single-user assistant that reads personal data, sends slices of it to cloud APIs, and (progressively) acts on the user's machine and accounts.

## 1. Assets

1. Personal corpus (notes, code, PDFs) and memory store — the crown jewels.
2. Credentials: provider API keys (Groq/Google/NVIDIA), calendar OAuth tokens, Telegram bot token.
3. Action capability: calendar now, browser/desktop later — an attacker who steers Alan_T steers the user's accounts.
4. The audit trail's integrity.

## 2. Threat Model (what we defend against)

| Threat | Vector | Primary control |
|---|---|---|
| Remote access to the API | exposed port | localhost + Tailscale only; bearer token; nothing port-forwarded |
| Telegram impersonation | messages to the bot | hard allowlist of one Telegram `user_id`; everything else dropped + logged ([TELEGRAM.md](../integrations/TELEGRAM.md)) |
| Prompt injection via content | hostile text in web pages, emails, PDFs, OCR'd images | data/instruction separation in prompts; minimum-tool dispatch; ASK-tier on all external actions (§6) |
| Tool misuse by the model | hallucinated/over-eager tool calls | registry-only tools, schema validation, permission tiers, audit ([TOOL_PERMISSIONS.md](TOOL_PERMISSIONS.md)) |
| Credential leakage | logs, prompts, repos | secrets only via env/secret store; log redaction filters; VFS exclusion of `.env`/keys; secrets never enter prompt assembly |
| Data exposure to providers | every model call (ADR-001) | minimization + exclusions + user awareness (§5) |
| Local theft of the machine | disk access | OS-level full-disk encryption (deployment prerequisite); encrypted credential store |

**Out of scope (accepted):** nation-state attackers, malicious provider (we trust Groq/Google with what we send — that's ADR-001's bargain), multi-user isolation (no second user exists).

## 3. Access Control

- **Network:** API binds localhost; remote = Tailscale mesh only (WireGuard, device-authorized). No public ingress, ever ([TAILSCALE.md](../integrations/TAILSCALE.md)).
- **AuthN:** one static bearer token for the API; rotation = edit env + restart. Telegram identity = sender ID allowlist.
- **AuthZ:** there are no roles — there is one human. Authorization complexity lives entirely in *tool* permissions, where it matters.

## 4. Credentials & Secrets

1. All secrets via environment (`.env` for dev, Docker secrets in compose) — never in code, config files in git, or docs.
2. OAuth tokens (Google Calendar) encrypted at rest (Fernet, key from env) in Postgres.
3. Log pipeline applies redaction filters (key patterns, bearer tokens) before write ([OBSERVABILITY.md](../observability/OBSERVABILITY.md) §1).
4. `tool_audit.args_preview` is redacted by the same filters; raw args are hashed ([POSTGRES_SCHEMA.md](../data/POSTGRES_SCHEMA.md) note 3).
5. VFS exclusions (`.env*`, `*.key`, `secrets/`) are the first line against secrets entering the corpus → cloud ([AI_VFS.md](../knowledge/AI_VFS.md)).

## 5. Cloud Data Exposure (the ADR-001 trade, managed honestly)

What leaves the machine: chat turns, retrieved chunks in context, chunk text at embedding time, audio for STT/TTS (M6). Free tiers may use submitted data for training — assume they do.

Controls:
1. **Exclusion-first:** `.alanignore` + mount include/exclude lists keep whole categories (secrets, finance folder, whatever the user marks) out of the system entirely.
2. **Sensitivity tags (backlog, P2):** sources tagged `sensitive` are ingested/searched but their chunks are never sent to cloud answer-models — the answer cites them and tells the user to open them locally. (Becomes fully useful when a local model adapter exists.)
3. **Awareness:** ingestion of a new tree is ASK-tier *because* it implies cloud embedding; camera/screen capture is ASK-tier *because* frames leave the machine.
4. **Audit of egress:** every model call logs provider + role + token counts (not content) — the user can see what categories of traffic go where (`/system/quota`, metrics).
5. **The exit:** the port layer keeps local inference one adapter away; the privacy posture upgrades to v0.1's original intent without re-architecture (ADR-001 escape hatch).

## 6. Prompt Injection (the defining LLM-agent threat)

Stance: injection is **unsolved**; we contain blast radius rather than claim prevention.

1. **Data/instruction separation:** all retrieved/external content is delimited and declared as non-instruction data ([PROMPTS.md](../ai/PROMPTS.md) §6).
2. **Minimum tools per dispatch:** the Supervisor strips the tool set to what the routed task needs; a poisoned PDF being summarized meets an agent that has no calendar tools to abuse.
3. **Tier gates are independent of model judgment:** ASK-tier confirmation happens in code, outside the model — a perfectly injected model still can't act externally without the human click.
4. **Egress guard (when Browser lands):** form-fill/submission to domains not in the task's origin set will require explicit approval (exfiltration-via-form containment) — designed in now, enforced when the deferred Browser agent is built.
5. **Audit everything:** post-hoc detection is a real control when prevention can't be guaranteed.

## 7. Audit Log

Append-only `tool_audit` for every tool execution + approval decisions + degradations; `trace_id` correlates to logs and conversation turns. Reviewed via `/system/audit` and surfaced in the weekly digest ("Alan_T performed N external actions this week"). PRD's audit requirement is satisfied here, not in prose.

## 8. Secure Defaults Checklist (deployment gate)

- [ ] Full-disk encryption on host
- [ ] `.env` not in git (CI check)
- [ ] API unreachable from non-Tailscale interfaces (verified, not assumed)
- [ ] Telegram allowlist set to exactly one ID
- [ ] VFS exclusions reviewed against the actual filesystem
- [ ] All ASK tiers verified interactive end-to-end
- [ ] Log redaction filters tested with planted fake secrets
