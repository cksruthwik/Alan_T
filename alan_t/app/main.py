"""FastAPI app — API shape per Docs/api/API_SPECIFICATION.md."""

from __future__ import annotations

import contextlib
import logging
import re
import uuid

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from alan_t.app.bootstrap import App, build
from alan_t.core.types import AgentTask, HonestFailure, IncomingMessage, MessageKind

logging.basicConfig(level=logging.INFO)


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    if state.files:
        await state.files.setup()
    yield
    if state.files:
        await state.files.close()


app = FastAPI(title="Alan_T", version="0.1.0", lifespan=_lifespan)
state: App = build()

_bearer = HTTPBearer(auto_error=False)


def auth(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    if not state.settings.alan_api_token:
        raise HTTPException(500, "ALAN_API_TOKEN is not configured")
    if creds is None or creds.credentials != state.settings.alan_api_token:
        raise HTTPException(401, "invalid bearer token")


def problem(status: int, title: str, detail: str, trace_id: str, **extra) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={"type": "about:blank", "title": title, "status": status,
                 "detail": detail, "trace_id": trace_id, **extra},
    )


@app.exception_handler(HonestFailure)
async def honest_failure_handler(request, exc: HonestFailure):
    return problem(
        503, "rate_limited", str(exc), trace_id=str(uuid.uuid4()),
        retry_after_seconds=exc.retry_after_seconds,
    )


# ── chat ──────────────────────────────────────────────────────────────


class CreateSession(BaseModel):
    channel: str = "web"
    title: str | None = None


class SendMessage(BaseModel):
    content: str
    modality: str = "text"


@app.post("/api/v1/chat/sessions", dependencies=[Depends(auth)])
async def create_session(body: CreateSession):
    sid = await state.store.create_session(channel=body.channel, title=body.title)
    return {"session_id": str(sid)}


@app.get("/api/v1/chat/sessions", dependencies=[Depends(auth)])
async def list_sessions():
    return [
        {"session_id": str(s.id), "title": s.title, "channel": s.channel,
         "created_at": s.created_at.isoformat()}
        for s in await state.store.list_sessions()
    ]


@app.get("/api/v1/chat/sessions/{session_id}", dependencies=[Depends(auth)])
async def session_detail(session_id: uuid.UUID, limit: int = 100, offset: int = 0):
    if not await state.store.session_exists(session_id):
        raise HTTPException(404, "unknown session")
    return [
        {"turn_id": str(t.id), "role": t.role, "content": t.content, "agent": t.agent,
         "created_at": t.created_at.isoformat()}
        for t in await state.store.turns(session_id, limit=limit, offset=offset)
    ]


# Pre-M3 routing: a cheap heuristic until the Supervisor lands (BUILD_ORDER M3).
_FILE_HINT = re.compile(r"\b(my notes?|my files?|my docs?|in the notes|in my|according to)\b", re.I)


def _route(text: str):
    if state.file_agent and _FILE_HINT.search(text):
        return state.file_agent
    return state.conversation


@app.post("/api/v1/chat/sessions/{session_id}/messages", dependencies=[Depends(auth)])
async def send_message(session_id: uuid.UUID, body: SendMessage):
    if not await state.store.session_exists(session_id):
        raise HTTPException(404, "unknown session")
    trace_id = str(uuid.uuid4())

    history = await state.store.history(session_id)
    await state.store.add_turn(session_id, "user", body.content, trace_id=trace_id)

    task = AgentTask(
        message=IncomingMessage(kind=MessageKind(body.modality if body.modality in ("text",) else "text"),
                                text=body.content),
        history=history,
    )
    agent = _route(body.content)
    result = await agent.run(task, state.ctx)

    turn_id = await state.store.add_turn(
        session_id, "assistant", result.response,
        agent=agent.name, trace_id=trace_id,
        token_usage={"model": result.model, "fallback_depth": result.fallback_depth},
    )
    # post-turn memory extraction (no-op until M1)
    await state.ctx.memory.extract_from_turn(body.content, result.response)

    return {
        "turn_id": str(turn_id), "content": result.response,
        "status": result.status, "degraded": result.degraded, "trace_id": trace_id,
    }


@app.websocket("/api/v1/chat/ws/{session_id}")
async def chat_ws(ws: WebSocket, session_id: uuid.UUID):
    # Browsers can't set Authorization on WS; accept token as query param too.
    token = ws.query_params.get("token") or (ws.headers.get("authorization") or "").removeprefix("Bearer ")
    if token != state.settings.alan_api_token:
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "abort":
                continue
            if msg.get("type") != "message":
                await ws.send_json({"type": "error", "problem": {"title": "unknown message type"}})
                continue

            content = msg.get("content", "")
            trace_id = str(uuid.uuid4())
            history = await state.store.history(session_id)
            await state.store.add_turn(session_id, "user", content, trace_id=trace_id)

            task = AgentTask(
                message=IncomingMessage(kind=MessageKind.TEXT, text=content), history=history
            )
            full: list[str] = []
            try:
                async for delta in state.conversation.run_stream(task, state.ctx):
                    full.append(delta.text)
                    await ws.send_json({"type": "token", "text": delta.text})
            except HonestFailure as e:
                await ws.send_json({"type": "error", "problem": {
                    "title": "rate_limited", "detail": str(e), "status": 503}})
                continue

            answer = "".join(full)
            turn_id = await state.store.add_turn(
                session_id, "assistant", answer,
                agent=state.conversation.name, trace_id=trace_id,
            )
            await ws.send_json({"type": "done", "turn_id": str(turn_id), "degraded": []})
            await state.ctx.memory.extract_from_turn(content, answer)
    except WebSocketDisconnect:
        pass


# ── knowledge (API_SPECIFICATION §4) ──────────────────────────────────


class SearchBody(BaseModel):
    query: str
    top_k: int = 8


def _knowledge_or_501():
    if state.ingester is None:
        raise HTTPException(501, "knowledge layer not enabled (features.knowledge in config/app.yaml)")


@app.post("/api/v1/knowledge/search", dependencies=[Depends(auth)])
async def knowledge_search(body: SearchBody):
    _knowledge_or_501()
    chunks = await state.retriever.search(body.query, top_k=body.top_k)
    return [
        {"chunk_id": c.chunk_id, "vpath": c.vpath, "body": c.body,
         "score": c.score, "similarity": c.similarity, "payload": c.payload}
        for c in chunks
    ]


@app.get("/api/v1/knowledge/sources", dependencies=[Depends(auth)])
async def knowledge_sources():
    _knowledge_or_501()
    return {"mounts": state.files.mounts_summary(), **(await state.ingester.status())}


@app.post("/api/v1/ingest", dependencies=[Depends(auth)])
async def ingest(background: BackgroundTasks):
    """Sync mounts + ingest changed files, as an in-process background task (ADR-021)."""
    _knowledge_or_501()
    background.add_task(state.ingester.run_full)
    return {"status": "started", "note": "poll /api/v1/ingest/status"}


@app.get("/api/v1/ingest/status", dependencies=[Depends(auth)])
async def ingest_status():
    _knowledge_or_501()
    return await state.ingester.status()


# ── memory (user control — MEMORY_ARCHITECTURE §5) ───────────────────


class RememberBody(BaseModel):
    content: str
    kind: str = "fact"


def _memory_or_501():
    mem = state.ctx.memory
    if not hasattr(mem, "list_all"):
        raise HTTPException(501, "memory layer not enabled (features.memory in config/app.yaml)")
    return mem


@app.get("/api/v1/memory", dependencies=[Depends(auth)])
async def list_memory():
    return await _memory_or_501().list_all()


@app.post("/api/v1/memory", dependencies=[Depends(auth)])
async def add_memory(body: RememberBody):
    await _memory_or_501().remember(body.content, kind=body.kind)
    return {"status": "stored"}


@app.delete("/api/v1/memory/{memory_id}", dependencies=[Depends(auth)])
async def delete_memory(memory_id: str):
    await _memory_or_501().forget(memory_id)
    return {"status": "deleted"}


@app.get("/api/v1/memory/export", dependencies=[Depends(auth)])
async def export_memory():
    return {"user": state.settings.user_name, "memories": await _memory_or_501().list_all()}


# ── system ────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/v1/health/deps", dependencies=[Depends(auth)])
async def health_deps():
    deps: dict[str, str] = {}
    try:
        await state.store.list_sessions()
        deps["postgres"] = "ok"
    except Exception as e:
        deps["postgres"] = f"error: {type(e).__name__}"
    for provider, key in (
        ("groq", state.settings.groq_api_key),
        ("google", state.settings.google_api_key),
        ("nvidia", state.settings.nvidia_api_key),
    ):
        deps[provider] = "configured" if key else "missing_key"
    return deps


@app.get("/api/v1/system/models", dependencies=[Depends(auth)])
async def system_models():
    return state.router.active_models()
