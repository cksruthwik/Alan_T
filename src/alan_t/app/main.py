"""FastAPI app: POST /chat, /health, bearer auth (M0 — BUILD_ORDER.md).

Single static bearer token; single user behind localhost/Tailscale
(SECURITY_ARCHITECTURE.md §3).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, status
from ulid import ULID

from alan_t.app.bootstrap import Container, build_container
from alan_t.app.schemas import ChatRequestBody, ChatResponseBody
from alan_t.core.llm import AllProvidersExhaustedError
from alan_t.core.types import AgentTask, IncomingMessage


def create_app(container: Container | None = None) -> FastAPI:
    container = container or build_container()
    logging.basicConfig(level=container.settings.alan_log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield

    app = FastAPI(title="Alan_T", version="0.0.1", lifespan=lifespan)
    app.state.container = container

    def require_token(authorization: str = Header(default="")) -> None:
        expected = f"Bearer {container.settings.alan_api_token}"
        if authorization != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing token"
            )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/chat", response_model=ChatResponseBody, dependencies=[Depends(require_token)])
    async def chat(body: ChatRequestBody) -> ChatResponseBody:
        session_id = body.session_id or str(ULID())
        task = AgentTask(
            message=IncomingMessage(kind="text", text=body.message),
            session_id=session_id,
            user_id=container.settings.alan_user_id,
        )
        try:
            result = await container.conversation.run(task, container.agent_context())
        except AllProvidersExhaustedError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="all model providers are rate-limited; try again later",
            ) from exc

        return ChatResponseBody(
            session_id=session_id,
            response=result.response,
            model=result.model,
            status=result.status,
            degraded=result.degraded,
        )

    return app
