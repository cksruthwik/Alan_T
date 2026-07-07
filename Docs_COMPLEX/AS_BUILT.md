# Docs_COMPLEX — As-Built Ledger

Date: 2026-07-05 · Status: full-architecture build complete (alpha)

The BUILD_ORDER rule was "a doc may run at most one milestone ahead of code."
This ledger is the reverse discipline: every place the code deliberately
diverges from the 51 docs, with the reason. Anything not listed here is built
as designed.

## Built as designed

Agent contract + thin agents (12 registered: conversation, file, code, vision,
memory, notes, documents, calendar*, email*, research, browser, automation —
\*conditional on credentials) · Supervisor with skill selection · Skill system
(progressive disclosure, 7 skills) · Tool registry + ALLOW/ASK/DENY gate +
Prometheus audit metrics · Role registry with fallback chains + boot capability
gate · Hybrid RAG (vector ∥ keyword, RRF) with PDF ingestion · Mem0 memory +
consolidation job · Planner → agents → Reflection (verdict + banked lesson) ·
Automation scheduler (digest/consolidate/notify/goal) · MCP both directions ·
Telegram gateway (voice in/out, photos, chat picker, approval buttons) ·
Metrics endpoint · Approvals API.

## Deliberate deviations

| Doc said | Built instead | Why |
|---|---|---|
| ai-vfs as file layer (AI_VFS.md) | `adapters/local_files.py` — direct reads, filters, containment | ai-vfs was a copy-middleman with single-user permission theater; removed by owner decision 2026-07-05 |
| LangGraph at M3 (LANGGRAPH.md, ADR) | Plain routing dict + agentic loop; no graph dependency | Supervisor is one model call + dispatch; LangGraph adds a dependency without a payoff until multi-turn graph state is real. Revisit when interrupt/resume approvals are wanted |
| ASK approvals resume the interrupted turn (TOOL_PERMISSIONS §4) | Approval = deferred standalone execution; the turn ends honestly ("pending #id") | Turn-resumption needs checkpointing (the LangGraph deferral above); deferred execution keeps the audit identical with far less machinery |
| Qdrant (VECTOR_STORE.md) | pgvector | One less container; BUILD_ORDER already made this call |
| 3 model profiles (`models.<profile>.yaml`) | One `models.yaml` | Owner runs one profile; profiles return when a second real profile exists |
| Redis for budgets/counters | Prometheus counters, no pre-flight budget windows | Budget pre-flight needs Redis; fallback chains + honest 429 handling cover the failure mode today. Add when quota exhaustion is observed in practice |
| WEB_AGENT role on groq/compound | Research agent = REASONER + web_search/web_fetch tools | compound's tool-calling support is unverified; plain tools work on every provider |
| Desktop agent (PRD FR-8) | **Not built** | The server runs in Docker; it cannot control the host desktop. Needs a host-side companion process — out of scope |
| Live voice via Pipecat (ADR-014) | Built WITHOUT Pipecat: composed WS pipeline (sentence-boundary TTS streaming) + native Gemini Live WS bridge (`adapters/gemini_live.py`, optional `live-voice` extra); VAD/interruption is client-side | Pipecat is a heavy framework for what two WS handlers cover; revisit if barge-in/VAD server-side becomes real |
| Vision on Gemini primary (ADR-006) | NVIDIA NIM primary, Gemini fallback | Owner directive: Google free-tier vision quota is the tighter constraint |
| Email as RAG source only (PRD FR-4) | Full email agent (IMAP/SMTP, triage, gated send) | Owner-requested capability expansion |
| — (not in plan) | Contacts, versioned documents, model compare, image gen, ntfy push | Owner-requested capability expansion, native to our architecture |
| shell_exec as an agent tool | **DENY, permanently** | SECURITY_ARCHITECTURE's line: agents never get a host shell |

## Known not-production-yet

- **Zero live end-to-end runs** — needs Docker + API keys; every provider
  integration (NVIDIA model IDs, Gemini TTS wire format, DDG scrape) is
  written-to-spec but unverified against the real services.
- Web client is first-party (alan_t/webui_static) — no third-party UI is
  served or redistributed; licensing is MIT throughout.
- Approvals are in-memory (restart clears the pending queue; audit counters
  survive in metrics only). Persist to `tool_audit` when it matters.
- No eval sets yet (router/skill-selection evals per TEST_STRATEGY §5).
- Voice paths + Gemini Live bridge are written-to-spec, never run against live
  APIs (model IDs now verified against live catalogs; wire formats still
  pending a live voice session).

## Fullscale additions (2026-07-05, second pass)

Projects (ChatGPT-style: grouping + shared instructions, injected per turn) ·
auto-titled sessions · rename/archive/hard-delete · Library (unified
notes/documents/images/uploads + upload→ingest) · one shared chat-turn service
(`app/chat_service.py`) behind REST/WS/webui/voice · Telegram full parity
(/start /list /switch /rename /delete /project /library, file uploads, bot
command menu) · voice: /voice/turn, WS /voice/live (composed, sentence-streamed
TTS), WS /voice/live-native (Gemini Live, ALLOW-tools only, transcript
persisted) · migration 0003.
