"""Web UI: Alan_T's own single-page client (alan_t/webui_static/).

Self-contained HTML/CSS/JS with zero external assets. The page itself is
public; every API call it makes carries the bearer token the user pastes on
first load (stored in the browser's localStorage) — the same auth as any
other API client. No unauthenticated endpoints exist for it.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parents[1] / "webui_static"


def mount_webui(app: FastAPI) -> None:
    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="webui-assets")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC_DIR / "index.html")
