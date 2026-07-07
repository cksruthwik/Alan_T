"""One chat-turn pipeline, shared by REST, WebSocket, web UI, and voice.

Owns the turn choreography: history → project instructions → supervisor
routing → skills → agent → persistence → memory extraction → auto-title.
Surfaces stay thin translations (the TELEGRAM.md rule, applied everywhere).
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from alan_t.core.types import AgentResult, AgentTask, ChatMessage, ChatRequest, IncomingMessage, MessageKind

log = logging.getLogger("alan_t.chat")

_PLACEHOLDER_TITLES = ("telegram:",)  # legacy rows from before untitled creation
_background_tasks: set[asyncio.Task] = set()


async def prepare_task(state, session_id: uuid.UUID, content: str, *,
                       channel: str = "web", modality: str = "text") -> AgentTask:
    history = await state.store.history(session_id)
    task = AgentTask(
        message=IncomingMessage(kind=MessageKind.TEXT, text=content, channel=channel),
        history=history,
    )
    session = await state.store.get_session(session_id)
    if session is not None and session.project_id is not None:
        project = await state.store.get_project(session.project_id)
        if project is not None and project.instructions:
            task.project_instructions = f"[Project: {project.name}] {project.instructions}"
    return task


async def _auto_title(state, session_id: uuid.UUID, user_text: str, answer: str) -> None:
    """First exchange → a 3–6 word title, like ChatGPT names its chats."""
    try:
        session = await state.store.get_session(session_id)
        stale = session is not None and (
            not session.title or session.title.startswith(_PLACEHOLDER_TITLES))
        if not stale:
            return
        resp = await state.ctx.llm.complete("SUMMARIZER", ChatRequest(messages=[
            ChatMessage(role="system",
                        content="Title this conversation in 3-6 plain words. "
                                "Reply with ONLY the title, no quotes."),
            ChatMessage(role="user", content=f"User: {user_text[:400]}\nAssistant: {answer[:400]}"),
        ]))
        title = resp.text.strip().strip('"')[:80]
        if title:
            await state.store.update_session(session_id, title=title)
    except Exception:
        log.debug("auto-title failed for %s", session_id, exc_info=True)


async def finish_turn(state, session_id: uuid.UUID, user_text: str, answer: str, *,
                      agent_name: str, trace_id: str, modality: str = "text",
                      token_usage: dict | None = None) -> uuid.UUID:
    turn_id = await state.store.add_turn(
        session_id, "assistant", answer, agent=agent_name,
        trace_id=trace_id, token_usage=token_usage, modality=modality)
    await state.ctx.memory.extract_from_turn(user_text, answer)
    task = asyncio.create_task(_auto_title(state, session_id, user_text, answer))
    _background_tasks.add(task)  # the loop holds only weak refs — anchor it
    task.add_done_callback(_background_tasks.discard)
    return turn_id


async def run_turn(state, session_id: uuid.UUID, content: str, *,
                   channel: str = "web", modality: str = "text") -> tuple[uuid.UUID, AgentResult, str]:
    """Full non-streaming turn. Returns (turn_id, result, agent_name)."""
    trace_id = str(uuid.uuid4())
    task = await prepare_task(state, session_id, content, channel=channel, modality=modality)
    await state.store.add_turn(session_id, "user", content, trace_id=trace_id, modality=modality)
    agent, skill_names = await state.supervisor.route(task, state.ctx)
    task.skills = state.skills.render(skill_names)
    result = await agent.run(task, state.ctx)
    turn_id = await finish_turn(
        state, session_id, content, result.response, agent_name=agent.name,
        trace_id=trace_id, modality=modality,
        token_usage={"model": result.model, "fallback_depth": result.fallback_depth})
    return turn_id, result, agent.name
