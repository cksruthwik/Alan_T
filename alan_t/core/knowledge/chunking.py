"""Chunking (KNOWLEDGE.md §2): cut on meaning, every chunk stands alone, deterministic IDs.

v1 parsers: Markdown/txt (heading-based). PDF (docling) and code (tree-sitter) are
later additions per the parser table — typed skip for unknown types, never fatal.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

MAX_TOKENS = 512
MIN_TOKENS = 40
OVERLAP_RATIO = 0.12

TEXT_SUFFIXES = (".md", ".markdown", ".txt", ".rst")


@dataclass
class DocChunk:
    chunk_id: str
    vpath: str
    body: str            # embedded text = context_header + "\n\n" + section body
    payload: dict = field(default_factory=dict)


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)  # cheap estimate; budgets are targets, not dogma


def _chunk_id(vpath: str, structural_path: str, position: int) -> str:
    return hashlib.sha256(f"{vpath}|{structural_path}|{position}".encode()).hexdigest()[:32]


def _split_long(text: str, max_tokens: int) -> list[str]:
    """Split an oversized section on paragraph boundaries with overlap."""
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    parts: list[str] = []
    cur: list[str] = []
    for p in paras:
        if cur and _tokens("\n\n".join(cur) + p) > max_tokens:
            parts.append("\n\n".join(cur))
            overlap = cur[-1] if _tokens(cur[-1]) < max_tokens * OVERLAP_RATIO * 2 else ""
            cur = [overlap, p] if overlap else [p]
        else:
            cur.append(p)
    if cur:
        parts.append("\n\n".join(cur))
    return parts or [text]


def chunk_markdown(vpath: str, text: str, mount: str, content_hash: str) -> list[DocChunk]:
    """Split on heading hierarchy; oversized sections split on paragraphs with overlap."""
    doc_title = vpath.rsplit("/", 1)[-1]
    # sections: (heading_path, body_text)
    sections: list[tuple[list[str], str]] = []
    heading_stack: list[tuple[int, str]] = []
    current: list[str] = []

    def flush():
        body = "\n".join(current).strip()
        if body:
            sections.append(([h for _, h in heading_stack], body))
        current.clear()

    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            flush()
            level = len(m.group(1))
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, m.group(2).strip()))
        else:
            current.append(line)
    flush()
    if not sections:
        sections = [([], text.strip())]

    # merge tiny trailing sections into the previous chunk
    merged: list[tuple[list[str], str]] = []
    for path, body in sections:
        if merged and _tokens(body) < MIN_TOKENS:
            prev_path, prev_body = merged[-1]
            merged[-1] = (prev_path, prev_body + "\n\n" + body)
        else:
            merged.append((path, body))

    chunks: list[DocChunk] = []
    for path, body in merged:
        structural = " > ".join([doc_title, *path]) if path else doc_title
        header = f"[{mount}] {structural}"
        for pos, part in enumerate(_split_long(body, MAX_TOKENS)):
            chunks.append(DocChunk(
                chunk_id=_chunk_id(vpath, structural, pos),
                vpath=vpath,
                body=f"{header}\n\n{part}",
                payload={
                    "mount": mount,
                    "structural_path": structural,
                    "position": pos,
                    "content_hash": content_hash,
                    "doc_type": "prose",
                },
            ))
    return chunks


def chunk_file(vpath: str, data: bytes, content_hash: str) -> list[DocChunk] | None:
    """Returns None for unsupported types (typed skip, never fatal)."""
    # vpath = vfs://<mount>/<relpath>
    mount = vpath.removeprefix("vfs://").split("/", 1)[0]
    if not vpath.lower().endswith(TEXT_SUFFIXES):
        return None
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        return None
    return chunk_markdown(vpath, text, mount, content_hash)
