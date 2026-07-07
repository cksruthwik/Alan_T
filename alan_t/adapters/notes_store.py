"""Notes store (Docs_COMPLEX PRD FR-11): plain markdown files in a writable
folder — Obsidian-compatible by construction, greppable, and ingestable by
adding the folder to config/mounts.yaml (so notes flow into RAG).

Same containment discipline as LocalFiles: everything stays under the root;
names are slugified; no path traversal via crafted titles.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("alan_t.notes")


def _slug(title: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9\- ]", "", title).strip().replace(" ", "-").lower()
    return s[:80] or "untitled"


class NotesStore:
    def __init__(self, root: str | Path):
        self._root = Path(root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        p = (self._root / name).resolve()
        if not p.is_relative_to(self._root) or p.suffix != ".md":
            raise PermissionError(f"refusing path outside notes root: {name}")
        return p

    def _create_sync(self, title: str, content: str) -> str:
        name = f"{_slug(title)}.md"
        p = self._path(name)
        if p.exists():
            name = f"{_slug(title)}-{datetime.now(timezone.utc):%Y%m%d%H%M%S}.md"
            p = self._path(name)
        p.write_text(f"# {title}\n\n{content}\n")
        log.info("note created %s", name)
        return name

    def _append_sync(self, name: str, content: str) -> str:
        p = self._path(name)
        if not p.exists():
            raise FileNotFoundError(f"no such note: {name}")
        with p.open("a") as f:
            f.write(f"\n{content}\n")
        return name

    def _list_sync(self) -> list[dict]:
        return [{"name": p.name, "modified": datetime.fromtimestamp(
                    p.stat().st_mtime, timezone.utc).isoformat()}
                for p in sorted(self._root.glob("*.md"),
                                key=lambda p: p.stat().st_mtime, reverse=True)]

    def _search_sync(self, query: str, limit: int = 8) -> list[dict]:
        needle = query.lower()
        hits = []
        for p in self._root.glob("*.md"):
            text = p.read_text(errors="replace")
            idx = text.lower().find(needle)
            if idx >= 0:
                hits.append({"name": p.name,
                             "snippet": text[max(0, idx - 80):idx + 160].strip()})
                if len(hits) >= limit:
                    break
        return hits

    async def create(self, title: str, content: str = "") -> str:
        return await asyncio.to_thread(self._create_sync, title, content)

    async def append(self, name: str, content: str) -> str:
        return await asyncio.to_thread(self._append_sync, name, content)

    async def read(self, name: str) -> str:
        return await asyncio.to_thread(lambda: self._path(name).read_text(errors="replace"))

    async def list_notes(self) -> list[dict]:
        return await asyncio.to_thread(self._list_sync)

    async def search(self, query: str) -> list[dict]:
        return await asyncio.to_thread(self._search_sync, query)

    @property
    def root(self) -> Path:
        return self._root
