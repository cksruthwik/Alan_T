"""The fullscale pass: voice sentence streaming, chat service glue, uploads safety."""


from alan_t.app.voice import _sentences
from alan_t.core.types import AgentTask, ChatResponse, IncomingMessage, MessageKind


def test_sentence_boundary_splitting():
    # too short → hold (don't TTS fragments)
    done, rest = _sentences("Hi. ")
    assert done == [] and rest == "Hi. "
    # a real first sentence flushes as soon as it completes
    long = "This is a properly long first sentence that should absolutely flush now. And then"
    done, rest = _sentences(long)
    assert len(done) == 1 and done[0].endswith("now.") and rest == "And then"
    # multiple completed sentences flush in order
    two = ("Sentence number one is long enough to pass the minimum threshold easily, yes. "
           "Sentence number two is also long enough to pass the minimum, absolutely. tail")
    done, rest = _sentences(two)
    assert len(done) == 2 and rest == "tail"


def test_agent_task_carries_project_instructions():
    task = AgentTask(message=IncomingMessage(kind=MessageKind.TEXT, text="hi"),
                     project_instructions="[Project: Thesis] Always cite sources.")
    assert "Thesis" in task.project_instructions


async def test_conversation_prompt_includes_project_context():
    from alan_t.core.agents.conversation import ConversationAgent

    class LLM:
        async def complete(self, purpose, req):
            return ChatResponse(text="ok", model="fake")

    class Mem:
        async def recall(self, q, limit=10):
            return []

    class Ctx:
        llm = LLM()
        memory = Mem()
        config = {"features": {"knowledge": False, "telegram": False}}
        user_name = "T"

    task = AgentTask(message=IncomingMessage(kind=MessageKind.TEXT, text="hello"),
                     project_instructions="[Project: X] speak like a pirate")
    req, _ = await ConversationAgent()._assemble(task, Ctx())
    assert "speak like a pirate" in req.messages[0].content


def test_upload_filename_is_sanitized():
    from pathlib import Path

    # the upload endpoint keeps only the basename — traversal dies here
    assert Path("../../etc/passwd").name == "passwd"
    assert Path("nested/dir/file.pdf").name == "file.pdf"


def test_gemini_live_bridge_offers_only_allow_tools():
    from alan_t.adapters.gemini_live import GeminiLiveBridge
    from alan_t.core.approvals import ApprovalBroker
    from alan_t.core.tools import ALLOW, ToolRegistry

    reg = ToolRegistry()
    reg.set_tiers({"safe_tool": ALLOW})
    reg.register("safe_tool", "reads stuff", {"type": "object", "properties": {}}, lambda: "x")
    reg.register("risky_tool", "sends stuff", {"type": "object", "properties": {}}, lambda: "y")
    bridge = GeminiLiveBridge("key", reg, ApprovalBroker(reg))
    offered = {d["name"] for d in bridge._tool_declarations()}
    assert offered == {"safe_tool"}  # ASK-tier never offered mid-speech


async def test_live_bridge_dispatch_respects_gate():
    from alan_t.adapters.gemini_live import GeminiLiveBridge
    from alan_t.core.approvals import ApprovalBroker
    from alan_t.core.tools import ToolRegistry

    reg = ToolRegistry()
    reg.register("ask_tool", "needs ok", {"type": "object", "properties": {}},
                 lambda: "should not run")
    broker = ApprovalBroker(reg)
    bridge = GeminiLiveBridge("key", reg, broker)
    out = await bridge._dispatch_tool("ask_tool", {})
    assert "NOT EXECUTED" in out and len(broker.pending()) == 1
