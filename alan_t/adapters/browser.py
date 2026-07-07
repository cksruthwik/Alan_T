"""Browser adapter (Docs_COMPLEX/agents/BROWSER_AGENT.md, integrations/PLAYWRIGHT.md).

Playwright behind an optional extra (`uv sync --extra browser` + `playwright
install chromium`). Not installed → the tool reports exactly what to install
instead of crashing the agent. The action vocabulary is deliberately small
(goto/click/fill/extract) — selectors rot, so less surface = less maintenance
(the doc's own warning).
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("alan_t.browser")

MAX_ACTIONS = 15  # bounded scripts — a runaway click-loop is a hang, not a feature


class BrowserAdapter:
    async def run(self, url: str, actions: list[dict[str, Any]] | None = None) -> str:
        """Open url, run bounded actions, return the page's visible text.

        actions: [{op: goto|click|fill|wait, selector?, value?}]
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return ("Browser automation is not installed. Run: "
                    "`uv sync --extra browser && playwright install chromium`")

        actions = (actions or [])[:MAX_ACTIONS]
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                for a in actions:
                    op = a.get("op")
                    if op == "goto":
                        await page.goto(a["value"], wait_until="domcontentloaded", timeout=30000)
                    elif op == "click":
                        await page.click(a["selector"], timeout=10000)
                    elif op == "fill":
                        await page.fill(a["selector"], a.get("value", ""), timeout=10000)
                    elif op == "wait":
                        await page.wait_for_selector(a["selector"], timeout=10000)
                    else:
                        return f"unknown browser op: {op!r} (allowed: goto|click|fill|wait)"
                text = await page.inner_text("body")
                title = await page.title()
                return f"[{title}] {page.url}\n\n{text[:12000]}"
            finally:
                await browser.close()
