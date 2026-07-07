"""Regression tests for the code-review fixes — one test per confirmed finding.

The web UI renderer tests execute the REAL app.js md() function in node
(skipped when node isn't installed), because a renderer bug that only lives
in the browser is exactly what the E2E suite missed last time.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from alan_t.core.approvals import ApprovalBroker
from alan_t.core.tools import ToolRegistry
from alan_t.workers.scheduler import Scheduler

APP_JS = Path(__file__).resolve().parents[1] / "alan_t" / "webui_static" / "app.js"


# ── finding 1: md() ate plain numbers ─────────────────────────────────


def _run_md(text: str) -> str:
    """Execute the real md() from app.js in node, DOM-free."""
    script = f"""
    const src = require('fs').readFileSync({json.dumps(str(APP_JS))}, 'utf8');
    const escFn = src.match(/function esc\\([\\s\\S]*?\\n}}/)[0];
    const mdFn = src.match(/function md\\([\\s\\S]*?\\n}}/)[0];
    eval(escFn); eval(mdFn);
    process.stdout.write(md({json.dumps(text)}));
    """
    return subprocess.run(["node", "-e", script], capture_output=True,
                          text=True, check=True).stdout


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


@needs_node
def test_md_preserves_plain_numbers():
    out = _run_md("I have 3 apples and 12 oranges. Port 8000 is open.")
    assert "3 apples" in out and "12 oranges" in out and "8000" in out
    assert "undefined" not in out


@needs_node
def test_md_renders_fences_and_numbers_together():
    out = _run_md("Run this:\n```py\nprint(1)\n```\nthen wait 5 seconds")
    assert "<pre><code>print(1)" in out
    assert "wait 5 seconds" in out and "undefined" not in out


@needs_node
def test_md_escapes_html():
    out = _run_md('<script>alert(1)</script> & "quotes"')
    assert "<script>" not in out and "&lt;script&gt;" in out


@needs_node
def test_md_sentinel_injection_cannot_leak_markup():
    # a hostile message carrying the private-use sentinels + digit must not
    # inject markup — worst case the sentinel span renders empty
    out = _run_md("evil 0 text")
    assert "<pre>" not in out and "undefined" not in out


# ── finding 2: telegram resumption is channel-based, not title-based ──


def test_telegram_resume_picks_latest_telegram_session_regardless_of_title():
    pytest.importorskip("aiogram", reason="telegram extra not installed")
    from alan_t.app.telegram_gateway import _pick_resume_session

    sessions = [  # newest-activity-first, as the API returns
        {"session_id": "w1", "channel": "web", "title": "Web chat"},
        {"session_id": "t1", "channel": "telegram", "title": "Trip planning"},  # auto-titled!
        {"session_id": "t2", "channel": "telegram", "title": None},
    ]
    assert _pick_resume_session(sessions) == "t1"
    assert _pick_resume_session([{"session_id": "w1", "channel": "web", "title": "x"}]) is None
    assert _pick_resume_session([]) is None


# ── finding 3: disabled automations are triggerable, just not scheduled ─


async def test_disabled_job_manual_trigger_works_but_never_schedules():
    ran = []

    async def digest(job):
        ran.append(job["name"])
        return "briefing text"

    s = Scheduler([{"name": "morning_digest", "at": "08:00", "action": "digest",
                    "enabled": False}], {"digest": digest})
    assert s._scheduled == []                       # never fires on the clock
    assert s.jobs_summary()[0]["enabled"] is False  # but it exists
    assert await s.run_job("morning_digest") == "briefing text"  # and /digest works
    assert ran == ["morning_digest"]
    s.start()
    assert s._task is None  # nothing scheduled → no loop task


# ── finding 8: failed approval is terminal, never double-executes ─────


async def test_failed_approval_is_terminal_no_double_execution():
    executions = []

    async def flaky():
        executions.append(1)
        raise RuntimeError("smtp died after partial send")

    reg = ToolRegistry()
    reg.register("flaky_tool", "d", {"type": "object", "properties": {}}, flaky)
    broker = ApprovalBroker(reg)
    a = broker.create("flaky_tool", {})

    resolved = await broker.resolve(a.id, approve=True)
    assert resolved.status == "failed"
    assert "RuntimeError" in resolved.result
    assert executions == [1]

    # user taps Approve again out of frustration — must NOT re-execute
    again = await broker.resolve(a.id, approve=True)
    assert again.status == "failed" and executions == [1]


# ── safety: a missing mount must NOT wipe its ingested chunks ──────────


async def test_ingest_does_not_tombstone_chunks_of_a_missing_mount(tmp_path, monkeypatch):
    """If a bind-mount fails (dir gone), re-ingest must preserve that mount's
    knowledge, not delete it. Regression for the tombstoned-10 incident."""
    import yaml as _yaml

    from alan_t.adapters.local_files import LocalFiles

    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "keep.md").write_text("# Keep\n\nimportant knowledge here\n")
    cfg = tmp_path / "mounts.yaml"
    cfg.write_text(_yaml.safe_dump({"mounts": {"notes": {"path": str(notes)}}}))

    lf = LocalFiles(cfg)
    assert lf.available_prefixes() == {"vfs://notes/"}

    # simulate the mount vanishing (failed bind-mount / wrong path)
    import shutil
    shutil.rmtree(notes)
    assert lf.available_prefixes() == set()          # mount now unavailable
    assert await lf.scan() == []                     # nothing scannable

    # the ingester's tombstone guard keys off available_prefixes(): a vpath
    # whose mount is unavailable is skipped, so its chunks survive.
    ledger_vpaths = {"vfs://notes/keep.md"}
    tombstoned = [v for v in ledger_vpaths
                  if any(v.startswith(p) for p in lf.available_prefixes())]
    assert tombstoned == []  # keep.md is NOT tombstoned while the mount is down
