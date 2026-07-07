"""Approval broker — the interactive half of the permission gate
(Docs_COMPLEX/security/TOOL_PERMISSIONS.md §4).

ASK-tier tool calls become pending approvals instead of refusals. The agent's
turn finishes immediately (the model is told the call is pending and phrases
that to the user); approving — via API, web, or the Telegram inline keyboard —
executes the tool then and there and returns the result to that surface.

Deliberate deviation from the doc's LangGraph-interrupt design: no mid-turn
suspend/resume. Approval = deferred standalone execution. Simpler, honest,
and it keeps the audit trail identical. Recorded in Docs_COMPLEX/AS_BUILT.md.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from alan_t.core.tools import ToolRegistry

log = logging.getLogger("alan_t.approvals")

PENDING, APPROVED, DENIED, EXPIRED, FAILED = "pending", "approved", "denied", "expired", "failed"
MAX_PENDING = 100  # oldest expire first — an unbounded queue is a footgun


@dataclass
class Approval:
    id: str
    tool: str
    args: dict[str, Any]
    preview: str
    status: str = PENDING
    result: Any = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ApprovalBroker:
    def __init__(self, registry: ToolRegistry):
        self._registry = registry
        self._approvals: dict[str, Approval] = {}

    def create(self, tool: str, args: dict[str, Any]) -> Approval:
        pending = [a for a in self._approvals.values() if a.status == PENDING]
        if len(pending) >= MAX_PENDING:
            oldest = min(pending, key=lambda a: a.created_at)
            oldest.status = EXPIRED
        approval = Approval(
            id=uuid.uuid4().hex[:8],
            tool=tool,
            args=args,
            preview=f"{tool}({', '.join(f'{k}={v!r}' for k, v in args.items())})",
        )
        self._approvals[approval.id] = approval
        log.info("approval created id=%s tool=%s", approval.id, tool)
        return approval

    def get(self, approval_id: str) -> Approval | None:
        return self._approvals.get(approval_id)

    def pending(self) -> list[Approval]:
        return sorted((a for a in self._approvals.values() if a.status == PENDING),
                      key=lambda a: a.created_at)

    async def resolve(self, approval_id: str, approve: bool) -> Approval:
        approval = self._approvals.get(approval_id)
        if approval is None:
            raise KeyError(f"unknown approval: {approval_id}")
        if approval.status != PENDING:
            return approval  # idempotent: double-tap on a Telegram button is harmless
        if not approve:
            approval.status = DENIED
            log.info("approval denied id=%s tool=%s", approval_id, approval.tool)
            return approval
        try:
            approval.result = await self._registry.execute(
                approval.tool, approval.args, approved=True)
        except Exception as e:
            # terminal: the tool may have partially executed — re-approving
            # could double a side effect (e.g. send an email twice)
            approval.status = FAILED
            approval.result = f"execution failed — {type(e).__name__}: {e}"
            log.exception("approval execution failed id=%s tool=%s", approval_id, approval.tool)
            return approval
        approval.status = APPROVED
        log.info("approval executed id=%s tool=%s", approval_id, approval.tool)
        return approval
