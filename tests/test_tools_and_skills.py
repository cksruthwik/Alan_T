"""Registry gate + skill loading + supervisor routing — the new M3 seams."""

import pytest

from alan_t.core.agents.supervisor import Supervisor
from alan_t.core.skills import SkillLibrary
from alan_t.core.tools import ALLOW, DENY, NeedsApproval, ToolRegistry
from alan_t.core.types import AgentTask, ChatResponse, IncomingMessage, MessageKind


def make_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.set_tiers({"open_tool": ALLOW, "danger_tool": DENY})
    reg.register("open_tool", "d", {}, lambda: "ran")
    reg.register("ask_tool", "d", {}, lambda: "ran")  # unlisted → ASK
    reg.register("danger_tool", "d", {}, lambda: "ran")
    return reg


async def test_gate_allow_ask_deny():
    reg = make_registry()
    assert await reg.execute("open_tool", {}) == "ran"
    with pytest.raises(NeedsApproval):
        await reg.execute("ask_tool", {})
    assert await reg.execute("ask_tool", {}, approved=True) == "ran"
    with pytest.raises(PermissionError):
        await reg.execute("danger_tool", {}, approved=True)  # DENY: approval can't help
    with pytest.raises(KeyError):
        await reg.execute("nope", {})


def test_skills_load_and_validate():
    lib = SkillLibrary(registered_tools={"search_knowledge", "recall_memory", "analyze_image"})
    assert set(lib.names()) >= {"note_summarization", "memory_recap", "image_analysis"}
    assert "note_summarization:" in lib.menu()
    rendered = lib.render(["memory_recap"])
    assert len(rendered) == 1 and "recall_memory" in rendered[0]
    # skills whose tools aren't available this run are skipped, never offered
    assert "email_triage" not in lib.names()
    lean = SkillLibrary(registered_tools={"recall_memory"})
    assert lean.names() == ["memory_recap"]


class FakeAgent:
    def __init__(self, name, description="d"):
        self.name, self.description, self.tools = name, description, []


class FakeLLM:
    def __init__(self, text):
        self._text = text

    async def complete(self, purpose, req):
        return ChatResponse(text=self._text, model="fake")


class Ctx:
    def __init__(self, llm):
        self.llm = llm


def make_supervisor(use_llm=True):
    lib = SkillLibrary(registered_tools={"search_knowledge", "recall_memory", "analyze_image"})
    agents = {"conversation": FakeAgent("conversation"), "file": FakeAgent("file")}
    return Supervisor(agents, lib, use_llm=use_llm), lib


def task(text, kind=MessageKind.TEXT):
    return AgentTask(message=IncomingMessage(kind=kind, text=text))


async def test_supervisor_llm_route():
    sup, _ = make_supervisor()
    agent, skills = await sup.route(
        task("what do you remember about me?"),
        Ctx(FakeLLM('{"agent": "conversation", "skills": ["memory_recap"]}')),
    )
    assert agent.name == "conversation" and skills == ["memory_recap"]


async def test_supervisor_falls_back_to_heuristic_on_garbage():
    sup, _ = make_supervisor()
    agent, skills = await sup.route(task("find X in my notes"), Ctx(FakeLLM("not json")))
    assert agent.name == "file" and skills == []


async def test_supervisor_heuristic_only_mode():
    sup, _ = make_supervisor(use_llm=False)
    agent, _ = await sup.route(task("hello"), Ctx(FakeLLM("should not be called")))
    assert agent.name == "conversation"


async def test_supervisor_ignores_unknown_agent_and_skill():
    sup, _ = make_supervisor()
    agent, skills = await sup.route(
        task("hi"), Ctx(FakeLLM('{"agent": "browser", "skills": ["made_up"]}')))
    assert agent.name == "conversation" and skills == []
