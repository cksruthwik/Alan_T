"""Web tools: search + fetch as plain gated tools any granted agent can call.

Search: DuckDuckGo's HTML endpoint — no API key, no dependency; if
BRAVE_API_KEY is set, Brave Search is used instead (better results, still free
tier). Fetch: httpx + a stdlib HTMLParser text extraction. Both are plain
ALLOW-tier tools any granted agent can call — not buried inside one agent.
"""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser

import httpx

log = logging.getLogger("alan_t.web")

UA = {"User-Agent": "Mozilla/5.0 (compatible; Alan_T/0.2; personal assistant)"}
_SKIP_TAGS = {"script", "style", "noscript", "svg", "header", "footer", "nav"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth and data.strip():
            self._chunks.append(data.strip())

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "\n".join(self._chunks))


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    return p.text()


class WebTools:
    def __init__(self, brave_api_key: str = ""):
        self._brave_key = brave_api_key

    async def search(self, query: str, max_results: int = 6) -> list[dict]:
        if self._brave_key:
            return await self._brave(query, max_results)
        return await self._duckduckgo(query, max_results)

    async def _brave(self, query: str, n: int) -> list[dict]:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": n},
                headers={"X-Subscription-Token": self._brave_key, **UA})
            r.raise_for_status()
            return [{"title": w.get("title", ""), "url": w.get("url", ""),
                     "snippet": w.get("description", "")}
                    for w in r.json().get("web", {}).get("results", [])[:n]]

    async def _duckduckgo(self, query: str, n: int) -> list[dict]:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.post("https://html.duckduckgo.com/html/",
                                  data={"q": query}, headers=UA)
            r.raise_for_status()
        results = []
        # DDG's html endpoint: results are <a class="result__a" href=...>title</a>
        # with a sibling snippet. Regex over one known-stable page beats a parser dep.
        for m in re.finditer(
                r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
                r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>', r.text, re.S):
            url, title, snippet = m.groups()
            results.append({"url": url, "title": html_to_text(title),
                            "snippet": html_to_text(snippet)[:300]})
            if len(results) >= n:
                break
        return results

    async def fetch(self, url: str, max_chars: int = 12000) -> str:
        if not url.startswith(("http://", "https://")):
            raise ValueError("web_fetch requires an http(s) URL")
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(url, headers=UA)
            r.raise_for_status()
            content_type = r.headers.get("content-type", "")
            if "html" in content_type:
                return html_to_text(r.text)[:max_chars]
            return r.text[:max_chars]
