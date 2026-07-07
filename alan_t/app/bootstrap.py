"""The one composition root — wires adapters to ports (layering rule #4).

Conditional registration rule: an agent whose backing adapter isn't configured
(email creds, calendar OAuth…) is not registered at all, so the supervisor
never routes to something that can't work. Tools follow their adapters.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from alan_t.adapters.browser import BrowserAdapter
from alan_t.adapters.email_imap import EmailAdapter
from alan_t.adapters.google_calendar import GoogleCalendarAdapter
from alan_t.adapters.google_media import GoogleMediaAdapter
from alan_t.adapters.local_files import LocalFiles
from alan_t.adapters.model_router import ModelRouter
from alan_t.adapters.notes_store import NotesStore
from alan_t.adapters.notify import Notifier
from alan_t.adapters.null_memory import NullMemory
from alan_t.adapters.postgres.personal_store import PersonalStore
from alan_t.adapters.postgres.store import ConversationStore, make_engine
from alan_t.adapters.web_tools import WebTools
from alan_t.app.config import CONFIG_DIR, MODELS_YAML, Settings, load_app_config, load_settings
from alan_t.core.agents.base import Agent, AgentContext
from alan_t.core.agents.conversation import ConversationAgent
from alan_t.core.agents.file_agent import FileAgent
from alan_t.core.agents.roster import (
    AutomationAgent,
    BrowserAgent,
    CalendarAgent,
    CodeAgent,
    DocumentsAgent,
    EmailAgent,
    MemoryAgent,
    NotesAgent,
    ResearchAgent,
)
from alan_t.core.agents.supervisor import Supervisor
from alan_t.core.agents.vision import VisionAgent
from alan_t.core.approvals import ApprovalBroker
from alan_t.core.knowledge.retrieval import Retriever
from alan_t.core.planning import TaskPlanner
from alan_t.core.reflection import ReflectionEngine
from alan_t.core.skills import SkillLibrary
from alan_t.core.tools import ToolRegistry
from alan_t.core.types import ChatMessage, ChatRequest
from alan_t.mcp_host.client import McpConnections
from alan_t.workers.ingest import Ingester
from alan_t.workers.scheduler import Scheduler


@dataclass
class App:
    settings: Settings
    router: ModelRouter
    store: ConversationStore
    personal: PersonalStore
    ctx: AgentContext
    conversation: ConversationAgent
    tools: ToolRegistry
    skills: SkillLibrary
    supervisor: Supervisor
    approvals: ApprovalBroker
    mcp: McpConnections
    planner: TaskPlanner
    reflector: ReflectionEngine
    scheduler: Scheduler
    notifier: Notifier
    media: GoogleMediaAdapter
    notes: NotesStore
    agents: dict[str, Agent] = field(default_factory=dict)
    vision_agent: VisionAgent | None = None
    file_agent: FileAgent | None = None
    files: LocalFiles | None = None
    ingester: Ingester | None = None
    retriever: Retriever | None = None


def _register_core_tools(reg: ToolRegistry, router, memory, retriever, ingester, files) -> None:
    reg.register(
        "recall_memory", "Recall stored long-term facts about the user matching a query.",
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        lambda query: memory.recall(query),
    )
    reg.register(
        "remember_fact", "Store a long-term fact/preference/goal about the user.",
        {"type": "object", "properties": {"content": {"type": "string"},
                                          "kind": {"type": "string", "default": "fact"}},
         "required": ["content"]},
        lambda content, kind="fact": memory.remember(content, kind=kind),
    )
    if hasattr(memory, "forget"):
        reg.register(
            "forget_memory", "Delete a stored memory by id (user-owned data).",
            {"type": "object", "properties": {"memory_id": {"type": "string"}},
             "required": ["memory_id"]},
            lambda memory_id: memory.forget(memory_id),
        )

    async def analyze_image(image: str, question: str = "Describe this image in detail.") -> str:
        resp = await router.complete("VISION", ChatRequest(messages=[
            ChatMessage(role="user", content=question, images=[image])]))
        return resp.text

    reg.register(
        "analyze_image", "Analyze an image (path or URL): describe, OCR, answer a question about it.",
        {"type": "object", "properties": {"image": {"type": "string"},
                                          "question": {"type": "string"}},
         "required": ["image"]},
        analyze_image,
    )
    reg.register(
        "transcribe_audio", "Transcribe an audio file (path) to text.",
        {"type": "object", "properties": {"audio_path": {"type": "string"}},
         "required": ["audio_path"]},
        lambda audio_path: router.transcribe(audio_path),
    )
    if retriever:
        async def search_knowledge(query: str, top_k: int = 8):
            chunks = await retriever.search(query, top_k=top_k)
            return [{"vpath": c.vpath, "body": c.body, "similarity": c.similarity} for c in chunks]

        reg.register(
            "search_knowledge", "Semantic search over the user's ingested notes/files; returns cited chunks.",
            {"type": "object", "properties": {"query": {"type": "string"},
                                              "top_k": {"type": "integer", "default": 8}},
             "required": ["query"]},
            search_knowledge,
        )
    if ingester:
        reg.register(
            "ingest_files", "Sync configured mounts and ingest new/changed files into the knowledge base.",
            {"type": "object", "properties": {}},
            lambda: ingester.run_full(),
        )
    if files:
        async def read_source(vpath: str) -> str:
            return (await files.read(vpath)).decode(errors="replace")[:20000]

        async def list_source_files(mount: str = "") -> list[str]:
            paths = [s.vpath for s in await files.scan()]
            if mount:
                paths = [p for p in paths if p.startswith(f"vfs://{mount}/")]
            return paths[:300]

        reg.register(
            "read_source", "Read a mounted source file by vpath (vfs://mount/path).",
            {"type": "object", "properties": {"vpath": {"type": "string"}}, "required": ["vpath"]},
            read_source,
        )
        reg.register(
            "list_source_files", "List vpaths of mounted source files (optionally one mount).",
            {"type": "object", "properties": {"mount": {"type": "string"}}},
            list_source_files,
        )
        reg.register(
            "grep_sources", "Regex search across all mounted source files; returns vpath+line hits.",
            {"type": "object", "properties": {"pattern": {"type": "string"},
                                              "max_results": {"type": "integer", "default": 25}},
             "required": ["pattern"]},
            lambda pattern, max_results=25: files.grep(pattern, max_results),
        )


def _register_jarvis_tools(reg: ToolRegistry, *, settings, personal, notes, web, browser,
                           email, calendar, notifier, media) -> None:
    # documents (versioned writing surface, Postgres-backed)
    reg.register(
        "document_create", "Create a versioned writing document (report, letter, post).",
        {"type": "object", "properties": {"title": {"type": "string"},
                                          "content": {"type": "string"}},
         "required": ["title"]},
        lambda title, content="": personal.create_document(title, content),
    )
    reg.register(
        "document_update", "Replace a document's content (bumps its version).",
        {"type": "object", "properties": {"document_id": {"type": "string"},
                                          "content": {"type": "string"},
                                          "title": {"type": "string"}},
         "required": ["document_id", "content"]},
        lambda document_id, content, title=None: personal.update_document(document_id, content, title),
    )
    reg.register(
        "document_read", "Read a document by id.",
        {"type": "object", "properties": {"document_id": {"type": "string"}},
         "required": ["document_id"]},
        lambda document_id: personal.get_document(document_id),
    )
    reg.register(
        "document_list", "List recent documents.",
        {"type": "object", "properties": {}},
        lambda: personal.list_documents(),
    )

    # contacts (Postgres-backed address book)
    reg.register(
        "resolve_contact", "Find a contact by name or email fragment.",
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        lambda query: personal.resolve_contact(query),
    )
    reg.register(
        "manage_contact", "Create or update a contact (name required; email/phone/notes optional).",
        {"type": "object", "properties": {"name": {"type": "string"}, "email": {"type": "string"},
                                          "phone": {"type": "string"}, "notes": {"type": "string"}},
         "required": ["name"]},
        lambda name, email=None, phone=None, notes=None: personal.upsert_contact(name, email, phone, notes),
    )

    # notes (markdown folder)
    reg.register(
        "note_create", "Create a markdown note with a title and body.",
        {"type": "object", "properties": {"title": {"type": "string"},
                                          "content": {"type": "string"}},
         "required": ["title"]},
        lambda title, content="": notes.create(title, content),
    )
    reg.register(
        "note_append", "Append content to an existing note by filename.",
        {"type": "object", "properties": {"name": {"type": "string"},
                                          "content": {"type": "string"}},
         "required": ["name", "content"]},
        lambda name, content: notes.append(name, content),
    )
    reg.register(
        "note_read", "Read a note by filename.",
        {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        lambda name: notes.read(name),
    )
    reg.register(
        "note_list", "List notes, newest first.",
        {"type": "object", "properties": {}},
        lambda: notes.list_notes(),
    )
    reg.register(
        "note_search", "Full-text search inside notes.",
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        lambda query: notes.search(query),
    )

    # web (search is ALLOW; it reads the world, changes nothing)
    reg.register(
        "web_search", "Search the web; returns title/url/snippet results.",
        {"type": "object", "properties": {"query": {"type": "string"},
                                          "max_results": {"type": "integer", "default": 6}},
         "required": ["query"]},
        lambda query, max_results=6: web.search(query, max_results),
    )
    reg.register(
        "web_fetch", "Fetch a URL and return its readable text.",
        {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        lambda url: web.fetch(url),
    )
    reg.register(
        "browser_run", "Drive a real browser: open a page, run bounded actions "
                       "[{op: goto|click|fill|wait, selector, value}], return page text.",
        {"type": "object", "properties": {
            "url": {"type": "string"},
            "actions": {"type": "array", "items": {"type": "object"}}},
         "required": ["url"]},
        lambda url, actions=None: browser.run(url, actions),
    )

    if email.configured:
        reg.register(
            "email_list", "List recent inbox emails (uid, from, subject, date).",
            {"type": "object", "properties": {"limit": {"type": "integer", "default": 10},
                                              "unread_only": {"type": "boolean", "default": False}}},
            lambda limit=10, unread_only=False: email.list_inbox(limit, unread_only),
        )
        reg.register(
            "email_read", "Read a full email by uid.",
            {"type": "object", "properties": {"uid": {"type": "string"}}, "required": ["uid"]},
            lambda uid: email.read_email(uid),
        )
        reg.register(
            "email_send", "Send an email (outward-facing — always needs approval).",
            {"type": "object", "properties": {"to": {"type": "string"},
                                              "subject": {"type": "string"},
                                              "body": {"type": "string"}},
             "required": ["to", "subject", "body"]},
            lambda to, subject, body: email.send_email(to, subject, body),
        )

    if calendar.configured:
        reg.register(
            "calendar_list", "List upcoming calendar events (default next 7 days).",
            {"type": "object", "properties": {"days_ahead": {"type": "integer", "default": 7},
                                              "query": {"type": "string"}}},
            lambda days_ahead=7, query=None: calendar.list_events(days_ahead, query),
        )
        reg.register(
            "calendar_create", "Create a calendar event (RFC3339 start/end).",
            {"type": "object", "properties": {
                "summary": {"type": "string"}, "start_iso": {"type": "string"},
                "end_iso": {"type": "string"}, "description": {"type": "string"},
                "location": {"type": "string"}},
             "required": ["summary", "start_iso", "end_iso"]},
            lambda summary, start_iso, end_iso, description="", location="":
                calendar.create_event(summary, start_iso, end_iso, description, location),
        )
        reg.register(
            "calendar_update", "Update an event's summary/start/end by id.",
            {"type": "object", "properties": {
                "event_id": {"type": "string"}, "summary": {"type": "string"},
                "start_iso": {"type": "string"}, "end_iso": {"type": "string"}},
             "required": ["event_id"]},
            lambda event_id, summary=None, start_iso=None, end_iso=None:
                calendar.update_event(event_id, summary, start_iso, end_iso),
        )
        reg.register(
            "calendar_delete", "Delete a calendar event by id.",
            {"type": "object", "properties": {"event_id": {"type": "string"}},
             "required": ["event_id"]},
            lambda event_id: calendar.delete_event(event_id),
        )

    if notifier.configured:
        reg.register(
            "notify", "Push a notification to the user's phone (Telegram/ntfy).",
            {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            lambda text: notifier.send(text),
        )

    if media.configured:
        images_dir = Path(settings.images_dir).expanduser()
        images_dir.mkdir(parents=True, exist_ok=True)

        async def generate_image(prompt: str) -> str:
            png = await media.generate_image(prompt)
            out = images_dir / f"gen-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.png"
            out.write_bytes(png)
            return f"image saved to {out}"

        reg.register(
            "generate_image", "Generate an image from a text prompt; returns the saved path.",
            {"type": "object", "properties": {"prompt": {"type": "string"}},
             "required": ["prompt"]},
            generate_image,
        )


def build() -> App:
    settings = load_settings()

    # LiteLLM reads provider keys from its own env names; map ours once, here.
    os.environ.setdefault("GROQ_API_KEY", settings.groq_api_key)
    os.environ.setdefault("GEMINI_API_KEY", settings.google_api_key)
    os.environ.setdefault("NVIDIA_NIM_API_KEY", settings.nvidia_api_key)

    router = ModelRouter(MODELS_YAML, CONFIG_DIR / "capabilities.yaml")
    router.verify()  # capability gate — a bad model swap dies here, not mid-chat
    engine = make_engine(settings.database_url)
    store = ConversationStore(engine)
    personal = PersonalStore(engine)
    app_config = load_app_config()

    memory = NullMemory()
    if app_config.get("features", {}).get("memory"):
        try:
            from alan_t.adapters.mem0_memory import Mem0Memory

            memory = Mem0Memory(settings.database_url)
        except ImportError:
            pass  # mem0 extra not installed → degrade to no memory

    files = file_agent = ingester = retriever = None
    if app_config.get("features", {}).get("knowledge"):
        files = LocalFiles(CONFIG_DIR / "mounts.yaml")
        retriever = Retriever(engine, router)
        ingester = Ingester(engine, router, files, embedder_model=router.embedder_model)
        file_agent = FileAgent(retriever)

    # adapters (each declares whether it's configured)
    email = EmailAdapter(settings.imap_host, settings.smtp_host, settings.email_address,
                         settings.email_password, settings.imap_port, settings.smtp_port)
    calendar = GoogleCalendarAdapter(settings.google_oauth_client_id,
                                     settings.google_oauth_client_secret,
                                     settings.google_oauth_refresh_token,
                                     settings.google_calendar_id)
    tts_model = router.chain("TTS")[0]["model"]
    image_model = (router.chain("IMAGE_GEN")[0]["model"]
                   if "IMAGE_GEN" in router.active_models() else "imagen-4.0-generate-001")
    media = GoogleMediaAdapter(settings.google_api_key, tts_model, image_model,
                               settings.tts_voice)
    web = WebTools(settings.brave_api_key)
    browser = BrowserAdapter()
    notes = NotesStore(settings.notes_dir)
    notifier = Notifier(settings.telegram_bot_token, settings.telegram_allowed_user_id,
                        settings.ntfy_topic)

    tools = ToolRegistry()
    tools.set_tiers(yaml.safe_load((CONFIG_DIR / "permissions.yaml").read_text()).get("tools", {}))
    _register_core_tools(tools, router, memory, retriever, ingester, files)
    _register_jarvis_tools(tools, settings=settings, personal=personal, notes=notes, web=web,
                           browser=browser, email=email, calendar=calendar,
                           notifier=notifier, media=media)

    approvals = ApprovalBroker(tools)

    # the roster — conditional on the adapter behind each agent
    agents: dict[str, Agent] = {
        "conversation": ConversationAgent(),
        "vision": VisionAgent(),
        "memory": MemoryAgent(),
        "notes": NotesAgent(),
        "documents": DocumentsAgent(),
        "research": ResearchAgent(),
        "browser": BrowserAgent(),
        "automation": AutomationAgent(),
    }
    if file_agent:
        agents["file"] = file_agent
        agents["code"] = CodeAgent()
    if email.configured:
        agents["email"] = EmailAgent()
    if calendar.configured:
        agents["calendar"] = CalendarAgent()

    # skills validate against whatever tools this configuration actually has
    skills = SkillLibrary(registered_tools=set(tools.names()))

    supervisor = Supervisor(
        agents, skills, use_llm=bool(app_config.get("features", {}).get("supervisor")))

    mcp_cfg = {}
    mcp_path = CONFIG_DIR / "mcp.yaml"
    if mcp_path.exists():
        mcp_cfg = (yaml.safe_load(mcp_path.read_text()) or {}).get("servers") or {}
    mcp = McpConnections(mcp_cfg)

    ctx = AgentContext(
        llm=router,
        memory=memory,
        files=files,
        config=app_config,
        user_name=settings.user_name,
        tools=tools,
        skills=skills,
        approvals=approvals,
    )

    reflector = ReflectionEngine()
    planner = TaskPlanner(agents, personal)

    # planner exposed as a gated tool: Jarvis can decompose its own goals — with approval
    reg_goal_ctx = ctx  # closure capture

    async def run_goal(goal: str) -> str:
        record = await planner.run(goal, reg_goal_ctx, reflector)
        return json.dumps({"task_id": record["task_id"], "status": record["status"],
                           "steps": [{k: s[k] for k in ("agent", "status")} for s in record["steps"]]})

    tools.register(
        "run_goal", "Decompose a goal into a multi-step plan and execute it via the agents "
                    "(autonomous multi-step action — always needs approval).",
        {"type": "object", "properties": {"goal": {"type": "string"}}, "required": ["goal"]},
        run_goal,
    )
    tools.register(
        "list_task_runs", "List recent planner task runs with status.",
        {"type": "object", "properties": {}},
        lambda: personal.list_task_runs(),
    )

    scheduler = _build_scheduler(ctx, store, personal, approvals, planner, reflector,
                                 email, calendar, notifier)
    tools.register(
        "list_automations", "List scheduled automations and when they last ran.",
        {"type": "object", "properties": {}},
        lambda: scheduler.jobs_summary(),
    )
    tools.register(
        "run_automation", "Trigger a scheduled automation right now, by name.",
        {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        lambda name: scheduler.run_job(name),
    )

    return App(
        settings=settings, router=router, store=store, personal=personal, ctx=ctx,
        conversation=agents["conversation"], tools=tools, skills=skills,
        supervisor=supervisor, approvals=approvals, mcp=mcp, planner=planner,
        reflector=reflector, scheduler=scheduler, notifier=notifier, media=media, notes=notes,
        agents=agents, vision_agent=agents["vision"], file_agent=file_agent,
        files=files, ingester=ingester, retriever=retriever,
    )


def _build_scheduler(ctx, store, personal, approvals, planner, reflector,
                     email, calendar, notifier) -> Scheduler:
    """Wire the scheduler's action vocabulary to the live services."""

    async def digest(job: dict) -> str:
        parts: list[str] = []
        if calendar.configured:
            try:
                events = await calendar.list_events(days_ahead=1)
                parts.append("Today's calendar:\n" + ("\n".join(
                    f"- {e['start']}: {e['summary']}" for e in events) or "- nothing scheduled"))
            except Exception as e:
                parts.append(f"Calendar unavailable ({type(e).__name__}).")
        if email.configured:
            try:
                unread = await email.list_inbox(limit=10, unread_only=True)
                parts.append(f"Unread email: {len(unread)}\n" + "\n".join(
                    f"- {m['from']}: {m['subject']}" for m in unread[:5]))
            except Exception as e:
                parts.append(f"Email unavailable ({type(e).__name__}).")
        pending = approvals.pending()
        if pending:
            parts.append("Pending approvals:\n" + "\n".join(
                f"- #{a.id} {a.preview}" for a in pending))
        runs = await personal.list_task_runs(5)
        if runs:
            parts.append("Recent tasks:\n" + "\n".join(
                f"- [{r['status']}] {r['goal'][:60]}" for r in runs))
        raw = "\n\n".join(parts) or "Nothing on the radar today."
        resp = await ctx.llm.complete("SUMMARIZER", ChatRequest(messages=[
            ChatMessage(role="system",
                        content="Compose a tight, friendly morning briefing from this data. "
                                "No preamble, no invented items."),
            ChatMessage(role="user", content=raw)]))
        if notifier.configured:
            await notifier.send(resp.text, title="Morning digest")
        return resp.text

    async def consolidate(job: dict) -> str:
        turns = await store.recent_turns(hours=24)
        if not turns:
            return "no conversations to consolidate"
        transcript = "\n".join(f"{t.role}: {t.content[:400]}" for t in turns)[-12000:]
        resp = await ctx.llm.complete("SUMMARIZER", ChatRequest(
            messages=[
                ChatMessage(role="system", content=(
                    "Extract durable facts about the user from this transcript — preferences, "
                    "goals, projects, decisions. Reply ONLY with JSON: "
                    '{"facts": ["...", ...]} — empty list if nothing durable.')),
                ChatMessage(role="user", content=transcript)],
            response_format={"type": "json_object"}))
        facts = json.loads(resp.text).get("facts", [])[:10]
        for fact in facts:
            await ctx.memory.remember(fact, kind="fact", source="consolidated")
        return f"consolidated {len(facts)} facts from {len(turns)} turns"

    async def notify_action(job: dict) -> str:
        return await notifier.send(job.get("message", "(automation fired with no message)"))

    async def goal_action(job: dict) -> str:
        record = await planner.run(job["goal"], ctx, reflector)
        summary = f"Task '{job['goal'][:60]}' → {record['status']}"
        if notifier.configured:
            await notifier.send(summary, title="Automation task")
        return summary

    jobs = []
    automations_path = CONFIG_DIR / "automations.yaml"
    if automations_path.exists():
        jobs = (yaml.safe_load(automations_path.read_text()) or {}).get("jobs") or []
    return Scheduler(jobs, {"digest": digest, "consolidate": consolidate,
                            "notify": notify_action, "goal": goal_action})
