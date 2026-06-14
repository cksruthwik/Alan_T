# Alan_T — Documentation (lean build)

**Start here:** [BUILD_ORDER.md](BUILD_ORDER.md) — the canonical build sequence (M0–M4 + M6).

Every doc here is written **lean-scope-native**: it describes the committed build, not a
target with caveats. The full original design (all phases, 50 docs) is preserved in
[`../Docs_COMPLEX/`](../Docs_COMPLEX/). Where any question of scope arises, `BUILD_ORDER.md`
and `DECISION_LOG` **ADR-020..024** are authoritative.

## Scope at a glance

- **LLM:** one LiteLLM seam over **Groq + Google AI Studio + NVIDIA NIM** (free), fallback chain (ADR-020).
- **Stores:** Postgres + **pgvector**; Mem0 for memory; ai-vfs for files. Redis/Qdrant deferred (ADR-021).
- **Agents:** 10-agent target, built M0→M4 then M6. Thin agents on one shared contract.
- **Skills:** the orchestration model — Supervisor selects `{agent, skills}` from M3 ([ai/SKILLS.md](ai/SKILLS.md)).
- **No Vision; Browser deferred; Voice last (M6), built voice-ready.**

## Map

| Area | Docs |
|---|---|
| Build / Product | [BUILD_ORDER](BUILD_ORDER.md) · [MVP](product/MVP.md) · [Roadmap](product/ROADMAP.md) · [PRD](product/PRD.md) · [Backlog](product/BACKLOG.md) |
| Architecture | [System Overview](architecture/SYSTEM_OVERVIEW.md) · [Agents](architecture/AGENTS.md) · [Orchestration & Workflows](architecture/ORCHESTRATION.md) · [Decision Log](architecture/DECISION_LOG.md) |
| AI | [LLM Strategy](ai/LLM_STRATEGY.md) · [Skills](ai/SKILLS.md) · [Prompts](ai/PROMPTS.md) · [Tool Catalog](ai/TOOL_CATALOG.md) |
| Memory / Knowledge | [Memory](memory/MEMORY_ARCHITECTURE.md) · [AI-VFS](knowledge/AI_VFS.md) · [Knowledge Pipeline](knowledge/KNOWLEDGE.md) |
| Data / API | [Data Model](data/DATA_MODEL.md) · [Postgres Schema](data/POSTGRES_SCHEMA.md) · [API](api/API_SPECIFICATION.md) |
| Agents (built) | [Supervisor](agents/SUPERVISOR_AGENT.md) · [Memory](agents/MEMORY_AGENT.md) · [File](agents/FILE_AGENT.md) |
| Integrations | [Telegram](integrations/TELEGRAM.md) · [Google Calendar](integrations/GOOGLE_CALENDAR.md) · [Tailscale](integrations/TAILSCALE.md) |
| Voice | [Voice Architecture](voice/VOICE_ARCHITECTURE.md) (M6) |
| Security / Infra | [Security](security/SECURITY_ARCHITECTURE.md) · [Tool Permissions](security/TOOL_PERMISSIONS.md) · [Infrastructure & Deployment](infra/INFRASTRUCTURE.md) |
| Ops | [Test Strategy](testing/TEST_STRATEGY.md) · [Observability](observability/OBSERVABILITY.md) |

## Consolidations (this lean rewrite)

- `LANGGRAPH` + `WORKFLOWS` → [architecture/ORCHESTRATION.md](architecture/ORCHESTRATION.md)
- `ADD` → folded into [architecture/SYSTEM_OVERVIEW.md](architecture/SYSTEM_OVERVIEW.md)
- `RAG` + `INGESTION` + `CHUNKING` + `VECTOR_STORE` → [knowledge/KNOWLEDGE.md](knowledge/KNOWLEDGE.md)
- `DEPLOYMENT` → folded into [infra/INFRASTRUCTURE.md](infra/INFRASTRUCTURE.md)
- `LOGGING` + `METRICS` → [observability/OBSERVABILITY.md](observability/OBSERVABILITY.md)

## Archived in `Docs_COMPLEX/` (deferred or dropped)

Vision (agent + architecture), Browser agent + Playwright, Code/Automation agents,
Planning & Reflection engines, Memory consolidation, Skills-advanced features, Qdrant
schema, MCP, the master requirements doc — all retained as the target design for when
those milestones arrive.
