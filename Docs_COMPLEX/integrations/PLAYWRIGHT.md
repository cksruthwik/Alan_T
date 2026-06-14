# Integration — Playwright

Phase: 5 · Port: `BrowserDriver` · Adapter: `adapters/playwright_/`
Consumer: [BROWSER_AGENT.md](../agents/BROWSER_AGENT.md) (the security envelope lives there; this doc is the driver mechanics)

## Port Surface

```python
class BrowserDriver(Protocol):
    async def new_session(self, profile: BrowserProfile) -> BrowserSession
class BrowserSession(Protocol):
    async def goto(self, url: str) -> PageState
    async def observe(self) -> PageState           # accessibility tree + DOM digest + url/title
    async def act(self, action: BrowserAction) -> PageState   # click/fill/select/scroll/press
    async def screenshot(self) -> ImageRef          # for VISION fallback
    async def close(self) -> None
```

- `PageState` is a **digest**, not raw HTML: interactive elements with stable refs (role, name, ref-id), visible text summary, URL. Token-budgeted (~2k) — raw DOM never enters a prompt.
- `BrowserAction` references elements by ref-id from the last `observe` — the model never composes selectors. Stale ref (page changed) → typed `StaleObservation` error → agent re-observes. This single design choice eliminates the largest class of brittle-selector failures.

## Adapter Implementation Notes

- Chromium, headed by default (the user can watch; trust is visual at first), dedicated profile dir under `data/browser_profile/` — never the user's daily browser profile.
- Accessibility-tree-first observation (Playwright's aria snapshots), DOM digest fallback for a11y-poor pages, screenshot+VISION as last resort — in that cost order ([BROWSER_AGENT.md](../agents/BROWSER_AGENT.md)).
- Downloads are written into the ai-vfs `workspace` namespace under `/downloads/` (the browser agent's only write grant — [AI_VFS.md](../knowledge/AI_VFS.md) §2), surfaced as candidate ingestion items (ASK) — never auto-opened or auto-executed.
- Per-action timeout 10 s, per-task wall clock from the agent's budget; browser process killed on task end (no idle sessions holding state).
- "Browser Use" library: adopted for its DOM-digest/action-loop patterns if its abstractions fit the port; otherwise its ideas are reimplemented against the port. The port is the commitment, the library is not.

## Login & Sessions

Approved-domain cookies persist in the profile between tasks (so "check my X dashboard" doesn't re-auth every time) — but login itself is always human-performed via interrupt ([BROWSER_AGENT.md](../agents/BROWSER_AGENT.md) §security-envelope-4). Cookie persistence per domain is listed in the permission promotions config — visible, revocable.

## Testing

Contract tests against a local static test site (fixtures in `tests/fixtures/web/`) covering: observe-digest stability, ref-based actions, stale-ref behavior, download sandboxing. No tests against live third-party sites in CI (flaky + impolite).
