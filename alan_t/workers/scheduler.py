"""Automation scheduler (Docs_COMPLEX PRD FR-15, agents/AUTOMATION_AGENT.md).

In-process asyncio loop (ADR-021: no queue container until a real need) that
fires named actions at HH:MM local time, driven by config/automations.yaml.
Actions are injected closures — the scheduler knows *when*, bootstrap wires
*what* (digest, consolidate, notify, goal). Every run is guarded: a failing
job logs and retries tomorrow; it never takes the API down.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

log = logging.getLogger("alan_t.scheduler")

TICK_SECONDS = 30

Action = Callable[[dict[str, Any]], Awaitable[str]]


class Scheduler:
    def __init__(self, jobs: list[dict[str, Any]], actions: dict[str, Action]):
        # ALL jobs are kept: `enabled` gates the schedule loop only, so manual
        # triggers (/digest, the API) work on a fresh install where everything
        # ships disabled. Disabled-means-nonexistent 404'd them before.
        self._jobs = list(jobs or [])
        self._actions = actions
        self._last_run: dict[str, date] = {}
        self._task: asyncio.Task | None = None
        for j in self._jobs:
            if j.get("action") not in actions:
                raise ValueError(f"automation '{j.get('name')}' names unknown action "
                                 f"{j.get('action')!r} (have: {sorted(actions)})")

    @property
    def _scheduled(self) -> list[dict[str, Any]]:
        return [j for j in self._jobs if j.get("enabled", True)]

    def start(self) -> None:
        if self._scheduled:
            self._task = asyncio.create_task(self._loop(), name="alan-scheduler")
            log.info("scheduler started with %d scheduled jobs: %s",
                     len(self._scheduled), [j["name"] for j in self._scheduled])

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def jobs_summary(self) -> list[dict]:
        return [{"name": j["name"], "at": j["at"], "action": j["action"],
                 "enabled": j.get("enabled", True),
                 "last_run": str(self._last_run.get(j["name"], "never"))}
                for j in self._jobs]

    async def run_job(self, name: str) -> str:
        """Manual trigger (API /automations/{name}/run, Telegram /digest now)."""
        job = next((j for j in self._jobs if j["name"] == name), None)
        if job is None:
            raise KeyError(f"unknown automation: {name}")
        return await self._actions[job["action"]](job)

    async def _loop(self) -> None:
        while True:
            now = datetime.now()
            for job in self._scheduled:
                due = job["at"] == now.strftime("%H:%M")
                if due and self._last_run.get(job["name"]) != now.date():
                    self._last_run[job["name"]] = now.date()
                    try:
                        result = await self._actions[job["action"]](job)
                        log.info("automation %s ran: %s", job["name"], str(result)[:200])
                    except Exception:
                        log.exception("automation %s failed", job["name"])
            await asyncio.sleep(TICK_SECONDS)
