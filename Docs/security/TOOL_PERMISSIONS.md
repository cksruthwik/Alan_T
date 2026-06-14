# Alan_T — Tool Permission System

Version: 0.2
Status: Active — lean scope ([BUILD_ORDER.md](../BUILD_ORDER.md))

The mechanism that makes "autonomous" safe: every tool execution passes a permission gate that runs **in code, outside the model** — model cleverness cannot bypass it.

## 1. Tiers

| Tier | Behavior | Intended for |
|---|---|---|
| `ALLOW` | executes immediately; audited | reads of already-ingested data; reversible local writes |
| `ASK` | LangGraph interrupt → user approves/denies (chat button or Telegram inline keyboard); audited with decision | external actions, new cloud egress, deletions |
| `DENY` | not in the registry at all — uncallable | arbitrary shell, external email, payments ([TOOL_CATALOG.md](../ai/TOOL_CATALOG.md) "Never-Tools") |

Default for any new tool: `ASK`. Promotion to `ALLOW` is a deliberate config change with rationale.

## 2. Configuration

```yaml
# config/permissions.yaml
defaults:
  tier: ASK
tools:
  search_knowledge:   { tier: ALLOW }
  calendar_write:     { tier: ASK }
  browser_navigate:
    tier: ASK
    promotions:
      - { match: { domain: ["github.com", "docs.python.org"] }, tier: ALLOW }
  send_telegram:
    tier: ASK
    promotions:
      - { match: { recipient: "owner" }, tier: ALLOW }
session_overrides:
  enabled: true        # "allow calendar writes for this task" — expires with the task
```

- **Promotions** are conditional narrowings (per-domain, per-recipient, per-path) — never wildcards.
- **Session overrides:** during an approved plan, the user can grant a tool for the remainder of that task run only; recorded in the audit as `user_approved(scope=task)`.

## 3. Enforcement Path (every call, no exceptions)

```
agent emits tool_call
  → registry lookup (unknown tool → hard reject + log)
  → JSON-schema validation of args
  → tier resolution (base + promotions + session overrides)
  → ALLOW: execute   |   ASK: interrupt → human decision   |   (DENY never reaches here)
  → execute with per-tool timeout
  → audit row (tool, agent, tier, decision, args_preview redacted, outcome, duration, trace_id)
```

Implementation notes:
- The gate is a core service wrapping every tool invocation; agents receive a `PermissionChecker` in `AgentContext` and physically cannot invoke a tool around it (tools are only callable through the gated executor).
- Denials return a structured refusal to the agent — the model must adapt or report, not retry the same call (executor suppresses identical re-calls within a turn).
- ASK requests carry a human-readable **preview** ("Create calendar event 'Dentist' 2026-06-20 14:00") — approval must be informed, args shown, not just tool names.

## 4. Approval UX Requirements

1. Preview shows *exactly* what will happen, including target (file path, recipient, event details).
2. Batch approvals at plan level arrive with the deferred Task Planning agent — but any step whose args materially changed since approval re-asks.
3. Timeout on pending approvals (default 1h) → step fails as `permission_denied`; never executes stale approvals.
4. Telegram approvals only from the allowlisted user ID, naturally.

## 5. Per-Milestone Posture

| Milestone | Posture |
|---|---|
| M0–M2 (read-heavy) | almost everything ALLOW except `ingest_path`, `forget_memory` |
| M2 (remote) | approvals via Telegram inline buttons (from M3 interrupts); same rules, different surface |
| M4 (productivity) | `calendar_write`, `notes_write` ASK with full preview |
| Deferred (browser) | reads ASK→promotable per domain; interactions always ASK initially |
| Deferred (autonomy) | plan-level batch approval; session overrides become the main flow |

## 6. Skills Compose Tools but Never Escalate

A skill ([SKILLS.md](../ai/SKILLS.md)) bundles a multi-step workflow over several tools, but it grants **no** new authority:

- Every tool a skill invokes passes the gate (§3) exactly as a direct agent call would — same tiers, same ASK interrupts, same audit rows. A skill is not a "trusted" caller.
- A skill's `required_tools` must be a **subset of the executing agent's grant**; routing never pairs a skill with an agent that lacks its tools, so a skill can't smuggle a capability into an agent that wasn't allowed it.
- Skill-bundled `scripts/` execute only in the sandboxed executor (ai-vfs — VFS callbacks only, budget-capped), never host shell. This keeps skills clear of the DENY'd `shell_exec` line.
- Skills are first-party and version-controlled (not user-uploaded at MVP), so a skill body is trusted code, not untrusted input — but the tools it drives are gated regardless, defense in depth.

## 7. Anti-Patterns (rejected designs)

- ❌ "The model decides what's safe" — tier resolution never consults a model.
- ❌ Global "autonomous mode" toggle disabling ASK — overrides are per-tool, per-scope, time-bounded.
- ❌ Approval fatigue by over-ASKing reads — that trains reflexive clicking; keep reads ALLOW and actions meaningfully gated.
