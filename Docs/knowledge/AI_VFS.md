# Alan_T — AI-VFS Integration

Version: 0.2 (rewritten after reviewing the actual `ai-vfs` repository)
Status: Active
Repository: `ai-vfs/` (in this workspace) — design doc at `ai-vfs/.specs/ai-vfs-design-doc.md`
Governing decision: ADR-010 in [DECISION_LOG.md](../architecture/DECISION_LOG.md)

## 1. What ai-vfs Actually Is

A Python **library** providing virtual filesystem semantics for AI agents — not a pass-through layer over existing folders. Its own storage, two layers:

- **Blob store** — immutable, content-addressed (BLAKE3); local FS or S3/MinIO. Identical content = one blob (dedup for free).
- **Metadata store** — pluggable (SQLite / **Postgres** / Mongo); paths, versions, permissions, audit log, search artifacts.

On top: **namespaces** (isolated workspaces), **principals** (agent/user/service identities), path-prefix permissions (default-deny, invisible pruning), per-file **versioning with rollback** and Time-Machine retention/GC, **native FTS** (Postgres `tsvector` + `pg_trgm`: regex/fulltext with zero blob reads on the fresh path), OTel tracing + append-only audit, and (designed, future) sandboxed code execution via Monty with VFS operations injected as callbacks.

Operations: `stat, read, write, delete, list, search, versions, rollback, copy, move` — all principal-scoped.

**Key consequence for Alan_T:** ai-vfs does not watch or mount the user's `~/Notes` or repos. Getting external sources into it is the consumer's job. The unified namespace over all knowledge is explicitly a consumer-layer concern in ai-vfs's own design — Alan_T is that consumer layer.

## 2. Integration Architecture

```
 user's real files: ~/Notes │ git repos │ ~/Documents/Papers │ email archive
        └───────────────┬───────────────────────┘
                        ▼
              SOURCE SYNC SERVICE  (Alan_T worker — owns watching)
              watches real paths · honors exclusions/.alanignore
              writes changed files into ai-vfs · tombstones deletions
              emits ingestion-queue events
                        ▼
   ┌──────────────────── ai-vfs ────────────────────────┐
   │ namespace `sources`   (read-mostly mirror)         │
   │   /notes/** /repos/<name>/** /papers/**            │
   │ namespace `workspace` (agent read-write)           │
   │   /drafts/** /task-artifacts/** /downloads/**      │
   │ Postgres metadata (shared instance, own database)  │
   │ local-FS blob store                                │
   └──────┬──────────────────────────┬──────────────────┘
          ▼                          ▼
   FileSource port            WorkspaceStore port
   (ingestion, File agent)    (agents' persistent scratch)
```

### Namespace `sources` — the knowledge mirror

- The sync service is the only writer; agents and ingestion read it through the `FileSource` port. File watching via **watchfiles** (Rust-backed — ADR-015).
- Mirror sync: content hash comparison means unchanged files cost nothing (idempotent `put`); deletions become tombstones; **the user's notes gain version history as a side effect** ("what did this note say last month?" becomes answerable — rollback/versions exposed as a later tool).
- Sync config (`config/vfs.yaml`) keeps the same shape as before — source paths, include/exclude globs, `.alanignore` — but now configures the **sync service**, not ai-vfs itself. Exclusions remain a security boundary: what never enters the mirror can never reach a cloud API ([SECURITY_ARCHITECTURE.md](../security/SECURITY_ARCHITECTURE.md) §5).

### Namespace `workspace` — persistent agent scratch

What the original doc was missing entirely: agents get a real, versioned, permission-scoped place to put things — task artifacts, drafts, browser downloads, generated reports. Rollbackable, auditable, GC'd by retention policy. Browser downloads land here instead of a raw host folder (relevant when the deferred Browser agent lands — [../../Docs_COMPLEX/integrations/PLAYWRIGHT.md](../../Docs_COMPLEX/integrations/PLAYWRIGHT.md)).

### Principals = Alan_T agents (defense in depth)

Each agent is an ai-vfs principal with explicit grants, aligned with [TOOL_PERMISSIONS.md](../security/TOOL_PERMISSIONS.md):

| Principal | Grants |
|---|---|
| `sync-service` | write on `sources:/` |
| `file-agent`, `code-agent` | read on `sources:/` |
| `ingestion-worker` | read on `sources:/` |
| `browser-agent` | write on `workspace:/downloads/` only |
| all agents | read/write on their `workspace:/task-artifacts/<agent>/` |

Default-deny + invisible pruning means a compromised/injected agent cannot even *list* paths it wasn't granted — filesystem-level enforcement underneath the tool permission gate, with ai-vfs's own audit log as a second witness to every write.

## 3. Ports

`FileSource` (read side — unchanged shape, reinterpreted):

```python
class FileSource(Protocol):
    async def list(self, prefix: VPath, recursive: bool = ...) -> list[VStat]
    async def read(self, path: VPath) -> SourceContent
    async def stat(self, path: VPath) -> VStat        # content_hash = BLAKE3 from ai-vfs version
    async def watch(self, prefix: VPath) -> AsyncIterator[ChangeEvent]
```

- `AiVfsAdapter` implements list/read/stat over namespace `sources` (vpaths map 1:1: `vfs://notes/x.md` → `sources:/notes/x.md`).
- **`watch` is implemented by the sync service, not ai-vfs** (which has no watch API) — the syncer emits ChangeEvents as it commits mirror writes, which is strictly better: events fire only after content is actually available to read.
- `LocalFsAdapter` remains the bypass for tests and for a no-ai-vfs minimal mode.

`WorkspaceStore` (write side — new port):

```python
class WorkspaceStore(Protocol):
    async def write(self, path: VPath, data: bytes, expected_version: int | None = ...) -> VersionRef
    async def read(self, path: VPath, version: int | None = ...) -> bytes
    async def list(self, prefix: VPath) -> list[VStat]
    async def versions(self, path: VPath) -> list[VersionRef]
    async def rollback(self, path: VPath, to_version: int) -> VersionRef
```

Backed by namespace `workspace`. Optimistic concurrency (`expected_version`) surfaces as a typed conflict — relevant once parallel plan steps write artifacts (Phase 7).

## 4. Alignment Wins (why this is better than the v0.1 sketch)

1. **Ingest ledger keys on BLAKE3** — the same hash ai-vfs already computes per version; `stat` is one metadata read, no re-hashing ([KNOWLEDGE.md](KNOWLEDGE.md) §1).
2. **Native FTS over the mirror** — Postgres `pg_trgm` regex/fulltext with zero blob reads gives agents a real `grep_sources` tool (Claude-Code-style corpus grep) far cheaper than embedding-based search for exact identifiers. Candidate replacement for the chunk-level `chunks_fts` keyword leg in hybrid retrieval — deferred decision, recorded in [BACKLOG.md](../product/BACKLOG.md) (file-level vs chunk-level granularity needs a real comparison on the actual corpus).
3. **Postgres is shared infra** — ai-vfs metadata store rides the existing Postgres instance (own database); blob store on local FS. Zero new containers ([INFRASTRUCTURE.md](../infra/INFRASTRUCTURE.md)).
4. **Sandboxed execution, later:** ai-vfs's Monty provider (designed, not yet implemented in v0.0.1) would give Alan_T a `vfs_execute` tool — agent-written Python running in a Rust sandbox whose *only* capabilities are injected VFS callbacks, budget-capped (`max_operations`). This is not the DENY'd `shell_exec` ([TOOL_CATALOG.md](../ai/TOOL_CATALOG.md) Never-Tools): no host filesystem, no network, no processes. When ai-vfs ships it, adoption needs an ADR + ASK tier, but the architecture slot exists.

## 5. Costs, Accepted

- **Storage duplication:** the mirror stores a blob copy of every source file. Personal corpus scale (GBs) makes this cheap; dedup and GC contain it. Accepted for versioning + permissions + FTS in return.
- **Sync lag:** watcher → mirror commit → ingestion event. Seconds at worst; nothing user-facing depends on sub-second freshness.
- **A second schema to migrate:** ai-vfs owns its Alembic migrations; Alan_T pins the library version and upgrades deliberately ([INFRASTRUCTURE.md](../infra/INFRASTRUCTURE.md) §6 update procedure applies).

## 6. Contract Rules (revised)

1. Agents never import `ai_vfs` directly — everything flows through `FileSource`/`WorkspaceStore` ports ([SYSTEM_OVERVIEW.md](../architecture/SYSTEM_OVERVIEW.md) layering rules). The ports keep ai-vfs swappable in principle, even though it's a sibling project we control.
2. The `sources` namespace is written only by the sync service; agent writes go to `workspace`. Notes *editing* still goes through `NotesProvider` to the real files — the mirror is derived, never the editing surface (the sync loop would otherwise fight itself).
3. Every `read` carries provenance (namespace, path, version, BLAKE3) → citation data in RAG.
4. ai-vfs version pinned in `pyproject.toml`; its breaking changes (pre-1.0!) are absorbed in the adapter, never in core.
