"""ai-vfs adapter: the `sources` mirror + FileSource port (Docs/knowledge/AI_VFS.md).

Alan_T is the consumer layer: the sync service (here) mirrors real folders into the
`sources` namespace; agents and ingestion only ever read the mirror. Exclusions are a
security boundary — what never enters the mirror can never reach a cloud API.

vpath convention: vfs://<mount>/<relpath> ↔ namespace `sources`, path /<mount>/<relpath>.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from pathlib import Path

import blake3
import yaml
from vfs import VFS, NotFoundError, VFSConfig

log = logging.getLogger("alan_t.vfs")

SYNC_PRINCIPAL = "sync-service"
READ_PRINCIPALS = ("file-agent", "ingestion-worker")


@dataclass
class SourceFile:
    vpath: str
    content_hash: str
    version: int


def _vpath(namespace_path: str) -> str:
    return "vfs:/" + namespace_path  # "/notes/x.md" → "vfs://notes/x.md"


def _ns_path(vpath: str) -> str:
    return vpath.removeprefix("vfs:/")


class VfsFiles:
    """Owns the ai-vfs instance: setup, mirror sync, and read access for ingestion/agents."""

    def __init__(self, metadata_uri: str, blob_uri: str, vfs_config_path: str | Path):
        self._vfs = VFS(VFSConfig(metadata_store_uri=metadata_uri, blob_store_uri=blob_uri))
        self._mounts_config = yaml.safe_load(Path(vfs_config_path).read_text()) or {}
        self._ns: str | None = None  # `sources` namespace id
        self._principals: dict[str, str] = {}

    async def setup(self) -> None:
        """Idempotent: create namespace + principals + grants on first run."""
        await self._vfs.initialize()
        ns = await self._vfs.resolve_name("namespace", "sources")
        if ns is None:
            ns = (await self._vfs.create_namespace("sources", created_by="alan_t")).id
        self._ns = ns
        first_run = await self._vfs.resolve_name("principal", SYNC_PRINCIPAL) is None
        for name in (SYNC_PRINCIPAL, *READ_PRINCIPALS):
            pid = await self._vfs.resolve_name("principal", name)
            if pid is None:
                pid = (await self._vfs.create_principal(name, principal_type="service")).id
            self._principals[name] = pid
        if first_run:
            sync_id = self._principals[SYNC_PRINCIPAL]
            # admin = grant-management only; the syncer self-grants read/write/delete.
            # NB: a grant REPLACES the permission row for (principal, prefix), so
            # admin must be re-included or the self-grant wipes it.
            await self._vfs.bootstrap_admin(sync_id, ns)
            await self._vfs.grant(sync_id, sync_id, ns, "/", {"admin", "read", "write", "delete"})
            for name in READ_PRINCIPALS:
                await self._vfs.grant(sync_id, self._principals[name], ns, "/", {"read"})

    async def close(self) -> None:
        await self._vfs.close()

    # ── sync service (the only writer of `sources`) ──

    def _iter_mount_files(self, mount: str, cfg: dict):
        root = Path(cfg["path"]).expanduser()
        include = cfg.get("include", ["**/*"])
        exclude = cfg.get("exclude", []) + (self._mounts_config.get("exclude_global") or [])
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if not any(fnmatch.fnmatch(rel, pat.removeprefix("**/")) or p.match(pat) for pat in include):
                continue
            if any(p.match(pat) or fnmatch.fnmatch(rel, pat) for pat in exclude):
                continue
            yield p, f"/{mount}/{rel}"

    async def sync_mounts(self) -> list[str]:
        """Mirror all configured mounts into `sources`. Returns changed vpaths."""
        assert self._ns, "setup() first"
        sync_id = self._principals[SYNC_PRINCIPAL]
        changed: list[str] = []
        mounts = self._mounts_config.get("mounts") or {}
        seen: set[str] = set()
        for mount, cfg in mounts.items():
            for local, ns_path in self._iter_mount_files(mount, cfg):
                seen.add(ns_path)
                data = local.read_bytes()
                new_hash = blake3.blake3(data).hexdigest()
                if await self._current_hash(ns_path) == new_hash:
                    continue  # unchanged: idempotent skip, zero blob writes
                await self._vfs.write(self._ns, ns_path, data, principal_id=sync_id)
                changed.append(_vpath(ns_path))
        # deletions → tombstones
        for meta in await self._vfs.list(self._ns, "/", principal_id=sync_id, recursive=True):
            if meta.path not in seen and not meta.is_deleted:
                await self._vfs.delete(self._ns, meta.path, principal_id=sync_id)
                changed.append(_vpath(meta.path))
        log.info("vfs sync: %d changed paths", len(changed))
        return changed

    async def _current_hash(self, ns_path: str) -> str | None:
        try:
            versions = await self._vfs.versions(
                self._ns, ns_path, principal_id=self._principals[SYNC_PRINCIPAL]
            )
        except NotFoundError:
            return None
        return versions[0].content_hash if versions else None  # newest-first

    # ── FileSource port (read side) ──

    async def list_sources(self) -> list[SourceFile]:
        pid = self._principals["ingestion-worker"]
        out = []
        for meta in await self._vfs.list(self._ns, "/", principal_id=pid, recursive=True):
            if meta.is_deleted:
                continue
            versions = await self._vfs.versions(self._ns, meta.path, principal_id=pid)
            out.append(SourceFile(
                vpath=_vpath(meta.path),
                content_hash=versions[0].content_hash,  # newest-first
                version=meta.current_version_number,
            ))
        return out

    async def read(self, vpath: str) -> bytes:
        return await self._vfs.read(
            self._ns, _ns_path(vpath), principal_id=self._principals["file-agent"]
        )

    def mounts_summary(self) -> dict:
        return {m: cfg.get("path") for m, cfg in (self._mounts_config.get("mounts") or {}).items()}
