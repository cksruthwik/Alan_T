# Browser Agent

Phase: 5 · Model roles: `REASONER` (action loop), `VISION` (page understanding when DOM is insufficient)
Driver: Playwright (+ Browser Use patterns) behind the `BrowserDriver` port · Integration: [PLAYWRIGHT.md](../integrations/PLAYWRIGHT.md)

## Responsibility

Web tasks: navigate, read, extract, fill, submit — under the tightest practical permission envelope, because this agent processes the most hostile content in the system (arbitrary web pages = arbitrary injected instructions).

## Tools

`browser_navigate` (ASK→ALLOW per-domain) · `browser_extract` (same) · `browser_interact` (ASK) · `web_research` (ALLOW — delegated to `groq/compound`, which does its own search/browse server-side; preferred for pure research because no local action surface exists).

## Action Loop

```
observe (accessibility tree / DOM digest; screenshot+VISION only when DOM is ambiguous)
  → decide (REASONER: next action toward task goal, JSON-schema'd)
  → permission gate → act (Playwright) → observe …
```

- Step budget per task (default 25 actions) and wall-clock timeout — runaway loops die, period.
- DOM-first, vision-second: cheaper, faster, less quota; VISION calls are the exception, logged.

## Security Envelope (this agent's defining constraints)

1. **Origin set:** each task declares its expected domains up front (from the user request or plan step). Navigation outside the set → ASK, always, regardless of promotions.
2. **Form egress guard:** any input/submit carrying data derived from user documents/memory to a domain outside the origin set → ASK with the exact payload previewed ([SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md) §6.4).
3. **Page content is data:** extracted text enters prompts under the injection delimiters ([PROMPTS.md](../ai/PROMPTS.md) §6); an instruction on a webpage ("ignore previous instructions, email this…") meets an agent with no email tool and a gate it can't talk its way through.
4. **Credentials:** the agent never sees passwords. Login flows pause with an interrupt → user completes auth in the headed browser window → agent resumes. No credential tooling exists to misuse.
5. Dedicated browser profile, separate from the user's daily profile; persistent only for approved-domain cookies.

## Degradation & Reporting

- Selector failures → one `retry_adjusted` with re-observation, then structured failure to Reflection (don't thrash).
- CAPTCHA / bot-walls → interrupt to user, honestly ("site is blocking automation").
- Every task ends with an action transcript (URLs, actions, extracts) in the audit log — reviewable after the fact.
