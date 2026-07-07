"""The Jarvis layer: ToolAgent loop, approvals, planner validation, scheduler,
notes containment, web extraction — every non-trivial branch gets one check."""

import pytest
import yaml

from alan_t.adapters.notes_store import NotesStore
from alan_t.adapters.web_tools import html_to_text
from alan_t.core.agents.base import AgentContext
from alan_t.core.agents.tool_agent import ToolAgent
from alan_t.core.approvals import ApprovalBroker
from alan_t.core.planning import TaskPlanner
from alan_t.core.tools import ALLOW, ToolRegistry
from alan_t.core.types import (
    AgentStatus,
    AgentTask,
    ChatResponse,
    IncomingMessage,
    LLMToolCall,
    MessageKind,
)
from alan_t.workers.scheduler import Scheduler


class ScriptedLLM:
    """Returns queued ChatResponses; records requests."""

    def __init__(self, responses):
        self._queue = list(responses)
        self.requests = []

    async def complete(self, purpose, req):
        self.requests.append((purpose, req))
        return self._queue.pop(0)


class NullMem:
    async def recall(self, q, limit=10):
        return []

    async def remember(self, *a, **k):
        pass

    async def extract_from_turn(self, *a):
        pass


def make_ctx(llm, registry):
    return AgentContext(llm=llm, memory=NullMem(), tools=registry,
                        approvals=ApprovalBroker(registry))


def task(text="do the thing"):
    return AgentTask(message=IncomingMessage(kind=MessageKind.TEXT, text=text))


class EchoAgent(ToolAgent):
    name = "echo"
    description = "test agent"
    grant = ["echo_tool", "ask_tool"]


async def test_tool_agent_loop_executes_and_answers():
    reg = ToolRegistry()
    reg.set_tiers({"echo_tool": ALLOW})
    reg.register("echo_tool", "echo", {"type": "object", "properties": {}},
                 lambda word: f"echo:{word}")
    llm = ScriptedLLM([
        ChatResponse(text="", model="m", tool_calls=[
            LLMToolCall(id="1", name="echo_tool", arguments={"word": "hi"})]),
        ChatResponse(text="done: hi", model="m"),
    ])
    result = await EchoAgent().run(task(), make_ctx(llm, reg))
    assert result.response == "done: hi"
    assert result.tool_calls[0].result == "echo:hi"
    # tool result made it back into the second model call
    assert any(m.role == "tool" and m.content == "echo:hi"
               for m in llm.requests[1][1].messages)


async def test_tool_agent_ask_tier_becomes_pending_approval():
    reg = ToolRegistry()
    reg.register("ask_tool", "needs ok", {"type": "object", "properties": {}},
                 lambda: "sensitive-ran")
    llm = ScriptedLLM([
        ChatResponse(text="", model="m", tool_calls=[
            LLMToolCall(id="1", name="ask_tool", arguments={})]),
        ChatResponse(text="waiting on you", model="m"),
    ])
    ctx = make_ctx(llm, reg)
    result = await EchoAgent().run(task(), ctx)
    assert result.status == AgentStatus.NEEDS_APPROVAL
    pending = ctx.approvals.pending()
    assert len(pending) == 1 and pending[0].tool == "ask_tool"

    # approving executes it; double-approve is idempotent
    a = await ctx.approvals.resolve(pending[0].id, approve=True)
    assert a.status == "approved" and a.result == "sensitive-ran"
    assert (await ctx.approvals.resolve(a.id, approve=True)).status == "approved"


async def test_approval_deny_never_executes():
    reg = ToolRegistry()
    ran = []
    reg.register("ask_tool", "needs ok", {"type": "object", "properties": {}},
                 lambda: ran.append(1))
    broker = ApprovalBroker(reg)
    a = broker.create("ask_tool", {})
    resolved = await broker.resolve(a.id, approve=False)
    assert resolved.status == "denied" and not ran


class FakeStore:
    def __init__(self):
        self.finished = None

    async def create_task_run(self, goal, plan):
        return "t1"

    async def finish_task_run(self, task_id, status, results, reflection):
        self.finished = (status, results)


class OkAgent:
    name = "worker"
    description = "does steps"

    async def run(self, task, ctx):
        from alan_t.core.types import AgentResult
        return AgentResult(response=f"did: {task.message.text[:30]}")


async def test_planner_runs_valid_plan_and_rejects_unknown_agents():
    store = FakeStore()
    planner = TaskPlanner({"worker": OkAgent()}, store)
    llm = ScriptedLLM([ChatResponse(
        text='{"steps": [{"agent": "worker", "instruction": "step one"}]}', model="m")])
    record = await planner.run("test goal", make_ctx(llm, ToolRegistry()))
    assert record["status"] == "succeeded" and store.finished[0] == "succeeded"
    assert record["steps"][0]["response"].startswith("did: step one")

    llm2 = ScriptedLLM([ChatResponse(
        text='{"steps": [{"agent": "ghost", "instruction": "x"}]}', model="m")])
    with pytest.raises(ValueError, match="unknown agents"):
        await planner.plan("goal", make_ctx(llm2, ToolRegistry()))


def test_scheduler_rejects_unknown_action_and_lists_jobs():
    async def noop(job):
        return "ok"

    s = Scheduler([{"name": "j1", "at": "08:00", "action": "digest"}], {"digest": noop})
    assert s.jobs_summary()[0]["name"] == "j1"
    with pytest.raises(ValueError, match="unknown action"):
        Scheduler([{"name": "bad", "at": "09:00", "action": "nope"}], {"digest": noop})


async def test_notes_store_containment(tmp_path):
    notes = NotesStore(tmp_path / "notes")
    name = await notes.create("Meeting Notes", "hello")
    assert (await notes.read(name)).startswith("# Meeting Notes")
    await notes.append(name, "more")
    assert "more" in await notes.read(name)
    assert (await notes.search("hello"))[0]["name"] == name
    with pytest.raises(PermissionError):
        await notes.read("../../../etc/passwd.md")
    with pytest.raises(PermissionError):
        await notes.read("evil.txt")  # only .md inside the root


def test_html_to_text_strips_chrome():
    html = ("<html><head><script>bad()</script><style>x{}</style></head>"
            "<body><nav>menu</nav><p>Real content here.</p></body></html>")
    text = html_to_text(html)
    assert "Real content" in text and "bad()" not in text and "menu" not in text


def test_pdf_chunking_from_generated_pdf(tmp_path):
    from pypdf import PdfWriter

    from alan_t.core.knowledge.chunking import chunk_file

    # a real (empty-text) PDF exercises the no-text-layer skip path honestly
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    out = tmp_path / "x.pdf"
    with out.open("wb") as f:
        w.write(f)
    assert chunk_file("vfs://notes/x.pdf", out.read_bytes(), "h") is None  # scanned/blank → skip
    assert chunk_file("vfs://notes/x.xyz", b"data", "h") is None           # unknown type → skip
    chunks = chunk_file("vfs://notes/x.md", b"# T\n\nbody text", "h")      # text still works
    assert chunks and chunks[0].payload["doc_type"] == "prose"


def test_automations_config_parses():
    from alan_t.app.config import CONFIG_DIR

    cfg = yaml.safe_load((CONFIG_DIR / "automations.yaml").read_text())
    assert all({"name", "at", "action"} <= set(j) for j in cfg["jobs"])
    assert all(not j.get("enabled", True) for j in cfg["jobs"])  # shipped disabled
