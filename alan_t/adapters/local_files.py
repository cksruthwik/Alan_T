"""LocalFiles — our own file source. Replaces ai-vfs (removed).

No mirror, no blob copy, no principals: the mounted directory (read-only in
Docker) is the single source of truth; Postgres (chunks + ingest ledger) is
the only derived store. Files live in ONE place instead of three.

The security boundary survives the removal intact and lives here:
- include/exclude filters decide what can EVER reach a cloud API;
- symlinks are never followed (no escaping a mount via a planted link);
- read() refuses any vpath that resolves outside its mount or that the
  filters exclude — a crafted vpath can't fish out .env.

Faster than the mirror it replaced: unchanged files are never re-read —
an (mtime_ns, size) cache skips hashing them; hashing is chunked (constant
memory on big files); blocking I/O runs in a worker thread, off the event loop.

vpath convention unchanged: vfs://<mount>/<relpath>.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
from dataclasses import dataclass
from pathlib import Path

import blake3
import yaml

log = logging.getLogger("alan_t.files")

_HASH_CHUNK = 1 << 20  # 1 MiB


@dataclass(frozen=True)
class SourceFile:
    vpath: str
    content_hash: str


def _vpath(mount: str, rel: str) -> str:
    return f"vfs://{mount}/{rel}"


class LocalFiles:
    def __init__(self, mounts_config_path: str | Path):
        cfg = yaml.safe_load(Path(mounts_config_path).read_text()) or {}
        self._mounts: dict[str, dict] = {}
        for name, mcfg in (cfg.get("mounts") or {}).items():
            self._mounts[name] = {**mcfg, "root": Path(mcfg["path"]).expanduser().resolve()}
        self._exclude_global: list[str] = cfg.get("exclude_global") or []
        # abs path → (mtime_ns, size, hash): unchanged files are never re-read
        self._hash_cache: dict[str, tuple[int, int, str]] = {}

    # ── filters: the cloud-egress boundary ────────────────────────────

    def _included(self, mcfg: dict, p: Path, rel: str) -> bool:
        include = mcfg.get("include", ["**/*"])
        exclude = (mcfg.get("exclude") or []) + self._exclude_global
        if not any(fnmatch.fnmatch(rel, pat.removeprefix("**/")) or p.match(pat) for pat in include):
            return False
        return not any(p.match(pat) or fnmatch.fnmatch(rel, pat) for pat in exclude)

    def _iter_mount(self, mount: str, mcfg: dict):
        root: Path = mcfg["root"]
        if not root.is_dir():
            log.warning("mount '%s' missing: %s", mount, root)
            return
        for p in sorted(root.rglob("*")):
            if p.is_symlink() or not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if self._included(mcfg, p, rel):
                yield p, rel

    def _hash(self, p: Path) -> str:
        st = p.stat()
        cached = self._hash_cache.get(str(p))
        if cached and cached[:2] == (st.st_mtime_ns, st.st_size):
            return cached[2]
        h = blake3.blake3()
        with p.open("rb") as f:
            while chunk := f.read(_HASH_CHUNK):
                h.update(chunk)
        digest = h.hexdigest()
        self._hash_cache[str(p)] = (st.st_mtime_ns, st.st_size, digest)
        return digest

    # ── the FileSource port ────────────────────────────────────────────

    def _scan_sync(self) -> list[SourceFile]:
        out = [
            SourceFile(vpath=_vpath(mount, rel), content_hash=self._hash(p))
            for mount, mcfg in self._mounts.items()
            for p, rel in self._iter_mount(mount, mcfg)
        ]
        log.info("scan: %d source files across %d mounts", len(out), len(self._mounts))
        return out

    async def scan(self) -> list[SourceFile]:
        """All ingestable files with content hashes. Deletions are implicit:
        a vpath absent from the scan is tombstoned by the ingester's ledger —
        but only for AVAILABLE mounts (see available_prefixes)."""
        return await asyncio.to_thread(self._scan_sync)

    def available_prefixes(self) -> set[str]:
        """vpath prefixes whose mount root currently exists. A mount whose
        directory is missing (failed bind-mount, wrong path) is 'unavailable',
        NOT 'emptied' — the ingester must not tombstone its chunks over a
        transient mount failure (that would silently wipe the knowledge base)."""
        return {f"vfs://{name}/" for name, mcfg in self._mounts.items()
                if mcfg["root"].is_dir()}

    def _read_sync(self, vpath: str) -> bytes:
        mount, _, rel = vpath.removeprefix("vfs://").partition("/")
        mcfg = self._mounts.get(mount)
        if mcfg is None:
            raise FileNotFoundError(f"unknown mount in {vpath}")
        root: Path = mcfg["root"]
        # resolve() follows symlinks and collapses "..", so containment on the
        # resolved path blocks both traversal and symlink escape in one check
        target = (root / rel).resolve()
        if not target.is_relative_to(root):
            raise PermissionError(f"refusing path outside mount: {vpath}")
        if not self._included(mcfg, target, target.relative_to(root).as_posix()):
            raise PermissionError(f"refusing excluded path: {vpath}")
        return target.read_bytes()

    async def read(self, vpath: str) -> bytes:
        return await asyncio.to_thread(self._read_sync, vpath)

    def _grep_sync(self, pattern: str, max_results: int) -> list[dict]:
        import re as _re
        rx = _re.compile(pattern, _re.IGNORECASE)
        hits: list[dict] = []
        for mount, mcfg in self._mounts.items():
            for p, rel in self._iter_mount(mount, mcfg):
                try:
                    for lineno, line in enumerate(
                            p.read_text(errors="replace").splitlines(), 1):
                        if rx.search(line):
                            hits.append({"vpath": _vpath(mount, rel), "line": lineno,
                                         "text": line.strip()[:300]})
                            if len(hits) >= max_results:
                                return hits
                except OSError:
                    continue
        return hits

    async def grep(self, pattern: str, max_results: int = 25) -> list[dict]:
        """Regex search across all mounted sources (Code agent's grep tool)."""
        return await asyncio.to_thread(self._grep_sync, pattern, max_results)

    def mounts_summary(self) -> dict:
        return {m: str(cfg["root"]) for m, cfg in self._mounts.items()}
