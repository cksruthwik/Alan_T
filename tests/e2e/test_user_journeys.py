"""End-to-end user journeys against the real app + real Postgres.

Every test is phrased as what a user actually does: ask a question, create a
note, upload a file, approve an action, talk. Only the model seam is scripted.
"""

import time

import pytest

pytestmark = pytest.mark.e2e


def _wait(cond, timeout=6.0, step=0.15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = cond()
        if result:
            return result
        time.sleep(step)
    return None


# ── journey 1: first conversation ─────────────────────────────────────


def test_user_says_hello_and_chat_gets_auto_titled(client):
    r = client.post("/api/v1/chat/sessions", json={"channel": "web"})
    sid = r.json()["session_id"]

    r = client.post(f"/api/v1/chat/sessions/{sid}/messages",
                    json={"content": "hello, who are you?"})
    assert r.status_code == 200
    body = r.json()
    assert body["agent"] == "conversation"
    assert "hello, who are you?" in body["content"]

    # both turns persisted
    turns = client.get(f"/api/v1/chat/sessions/{sid}").json()
    assert [t["role"] for t in turns] == ["user", "assistant"]

    # auto-title lands asynchronously, like ChatGPT naming a chat
    title = _wait(lambda: next((s["title"] for s in client.get("/api/v1/chat/sessions").json()
                                if s["session_id"] == sid and s["title"]), None))
    assert title == "Dummy Test Chat"


def test_streaming_over_websocket(client):
    sid = client.post("/api/v1/chat/sessions", json={}).json()["session_id"]
    with client.websocket_connect(f"/api/v1/chat/ws/{sid}?token=e2e-test-token") as ws:
        ws.send_json({"type": "message", "content": "stream me a reply please"})
        tokens, done = [], None
        while done is None:
            m = ws.receive_json()
            if m["type"] == "token":
                tokens.append(m["text"])
            elif m["type"] == "done":
                done = m
        assert done["agent"] == "conversation"
        assert "stream me a reply" in "".join(tokens)


# ── journey 2: knowledge — ingest my notes, ask about them ────────────


def test_ingest_then_ask_about_my_notes_with_citation(client):
    r = client.post("/api/v1/ingest")
    assert r.status_code == 200
    def _ingested():
        s = client.get("/api/v1/ingest/status").json()
        return s if s.get("chunks", 0) > 0 else None

    status = _wait(_ingested, timeout=15)
    assert status and status["ledger"].get("ok", 0) >= 2  # alpha.md + beta.md

    hits = client.post("/api/v1/knowledge/search", json={"query": "Project Alpha launch"}).json()
    assert any("alpha.md" in h["vpath"] for h in hits)

    sid = client.post("/api/v1/chat/sessions", json={}).json()["session_id"]
    r = client.post(f"/api/v1/chat/sessions/{sid}/messages",
                    json={"content": "what do my notes say about alpha?"})
    body = r.json()
    assert body["agent"] == "file"
    assert "vfs://notes/alpha.md" in body["content"]  # cited answer


# ── journey 3: agent uses a tool — create a note ──────────────────────


def test_create_note_via_notes_agent(client):
    sid = client.post("/api/v1/chat/sessions", json={}).json()["session_id"]
    r = client.post(f"/api/v1/chat/sessions/{sid}/messages",
                    json={"content": "create a note called Groceries saying: milk and eggs"})
    body = r.json()
    assert body["agent"] == "notes" and body["status"] == "ok"

    lib = client.get("/api/v1/library").json()
    assert any(n["name"] == "groceries.md" for n in lib["notes"])



# ── journey 4: autonomy with a human in the loop ──────────────────────


def test_goal_needs_approval_then_approving_executes_the_plan(client):
    sid = client.post("/api/v1/chat/sessions", json={}).json()["session_id"]
    r = client.post(f"/api/v1/chat/sessions/{sid}/messages",
                    json={"content": "please run a goal to write my weekly summary"})
    body = r.json()
    assert body["agent"] == "automation"
    assert body["status"] == "needs_approval"  # run_goal is ASK-tier

    pending = client.get("/api/v1/approvals").json()
    assert pending and pending[0]["tool"] == "run_goal"

    # user taps Approve → planner runs → notes agent executes the step
    r = client.post(f"/api/v1/approvals/{pending[0]['id']}", json={"approve": True})
    assert r.json()["status"] == "approved"

    runs = client.get("/api/v1/tasks").json()
    assert runs and runs[0]["status"] == "succeeded"
    detail = client.get(f"/api/v1/tasks/{runs[0]['id']}").json()
    assert detail["reflection"]["verdict"] == "success"
    lib = client.get("/api/v1/library").json()
    assert any(n["name"] == "weekly-summary.md" for n in lib["notes"])

    # denying never executes
    r2 = client.post(f"/api/v1/chat/sessions/{sid}/messages",
                     json={"content": "run a goal to do it again"})
    assert r2.json()["status"] == "needs_approval"
    pid = client.get("/api/v1/approvals").json()[0]["id"]
    assert client.post(f"/api/v1/approvals/{pid}", json={"approve": False}).json()["status"] == "denied"


# ── journey 5: projects change behavior ───────────────────────────────


def test_project_instructions_reach_the_prompt(client):
    pid = client.post("/api/v1/projects",
                      json={"name": "Pirate Mode",
                            "instructions": "Always answer like a pirate."}).json()["project_id"]
    sid = client.post("/api/v1/chat/sessions", json={"project_id": pid}).json()["session_id"]
    client.post(f"/api/v1/chat/sessions/{sid}/messages", json={"content": "hi there"})

    router = client.state_obj.router
    chat_calls = [req for role, req in router.requests if role == "CHAT"]
    assert any("Always answer like a pirate." in req.messages[0].content
               for req in chat_calls)

    sessions = client.get("/api/v1/chat/sessions").json()
    assert any(s["project"] == "Pirate Mode" for s in sessions)


# ── journey 6: chat management ────────────────────────────────────────


def test_rename_archive_delete(client):
    sid = client.post("/api/v1/chat/sessions", json={}).json()["session_id"]
    client.patch(f"/api/v1/chat/sessions/{sid}", json={"title": "Keep Me"})
    assert any(s["title"] == "Keep Me" for s in client.get("/api/v1/chat/sessions").json())

    client.patch(f"/api/v1/chat/sessions/{sid}", json={"archived": True})
    active = client.get("/api/v1/chat/sessions").json()
    assert all(s["session_id"] != sid for s in active)
    archived = client.get("/api/v1/chat/sessions?archived=true").json()
    assert any(s["session_id"] == sid for s in archived)

    assert client.delete(f"/api/v1/chat/sessions/{sid}").json()["status"] == "deleted"
    assert client.get(f"/api/v1/chat/sessions/{sid}").status_code == 404


# ── journey 7: voice note in ──────────────────────────────────────────


def test_voice_turn_transcribes_and_answers(client):
    r = client.post("/api/v1/voice/turn",
                    files={"audio": ("note.ogg", b"\x00fake-ogg-bytes", "audio/ogg")})
    assert r.status_code == 200
    body = r.json()
    assert body["transcript"] == "hello alan can you hear me"
    assert body["content"]  # answered
    turns = client.get(f"/api/v1/chat/sessions/{body['session_id']}").json()
    assert all(t["modality"] == "voice" for t in turns)  # transcripts are first-class


def test_voice_live_websocket_text_roundtrip(client):
    with client.websocket_connect("/api/v1/voice/live?token=e2e-test-token") as ws:
        assert ws.receive_json()["type"] == "session"
        ws.send_json({"type": "text", "text": "talk to me"})
        got = {"token": False, "done": False}
        while not got["done"]:
            m = ws.receive_json()
            if m["type"] == "token":
                got["token"] = True
            elif m["type"] == "done":
                got["done"] = True
        assert got["token"]


# ── journey 8: library uploads ────────────────────────────────────────


def test_upload_lands_in_library_and_knowledge(client):
    r = client.post("/api/v1/library/upload",
                    files={"file": ("meeting.txt", b"Kickoff meeting is on Friday.", "text/plain")})
    saved = r.json()["saved"]
    assert saved.startswith("meeting")

    lib = client.get("/api/v1/library").json()
    assert saved in lib["uploads"]

    ok = _wait(lambda: any("uploads" in h["vpath"] for h in client.post(
        "/api/v1/knowledge/search", json={"query": "kickoff meeting Friday"}).json()),
        timeout=15)
    assert ok, "uploaded file never became searchable"


# ── journey 9: vision + compare + surfaces ────────────────────────────


def test_vision_analyze(client):
    r = client.post("/api/v1/vision/analyze",
                    files={"image": ("t.png", b"\x89PNG fake", "image/png")},
                    data={"question": "what is this?"})
    assert "red square" in r.json()["content"]


def test_compare_models(client):
    r = client.post("/api/v1/compare", json={"prompt": "pick a database", "roles": ["CHAT", "REASONER"]})
    body = r.json()
    assert len(body["candidates"]) == 2 and body["synthesis"]


def test_web_ui_is_ours_and_served(client):
    home = client.get("/")
    assert home.status_code == 200 and "Alan_T" in home.text
    assert "odysseus" not in home.text.lower()
    js = client.get("/assets/app.js")
    assert js.status_code == 200 and "single-file client" in js.text
    # no Odysseus-shape endpoints remain
    assert client.get("/api/sessions").status_code in (401, 404)


def test_metrics_and_agents_surface(client):
    metrics = client.get("/metrics").text
    assert "alan_llm_calls_total" in metrics and "alan_tool_executions_total" in metrics
    agents = {a["name"] for a in client.get("/api/v1/agents").json()}
    assert {"conversation", "file", "notes", "automation", "vision"} <= agents


def test_automation_manual_trigger(client):
    r = client.post("/api/v1/automations/morning_digest/run")
    assert r.status_code == 200
    assert r.json()["result"]  # the briefing text itself (no push channel configured)
    jobs = client.get("/api/v1/automations").json()
    assert jobs and jobs[0]["name"] == "morning_digest"


# ── journeys added by the review-fix pass ─────────────────────────────


def test_chat_ws_survives_backend_crash_and_recovers(client):
    """A mid-turn crash must produce an error frame, not a dead socket."""
    sid = client.post("/api/v1/chat/sessions", json={}).json()["session_id"]
    with client.websocket_connect(f"/api/v1/chat/ws/{sid}?token=e2e-test-token") as ws:
        ws.send_json({"type": "message", "content": "please explode now"})
        m = ws.receive_json()
        assert m["type"] == "error" and m["problem"]["status"] == 500

        # same socket, next turn works — the user just retries
        ws.send_json({"type": "message", "content": "ok try again normally"})
        done = None
        while done is None:
            m = ws.receive_json()
            if m["type"] == "done":
                done = m
        assert done["agent"] == "conversation"


def test_voice_ws_survives_stt_rate_limit(client):
    """STT rate-limit → 503 error frame; the socket stays usable."""
    import base64 as b64

    with client.websocket_connect("/api/v1/voice/live?token=e2e-test-token") as ws:
        assert ws.receive_json()["type"] == "session"
        ws.send_json({"type": "audio", "format": "ogg",
                      "data": b64.b64encode(b"RATELIMIT-audio").decode()})
        m = ws.receive_json()
        assert m["type"] == "error" and m.get("status") == 503

        ws.send_json({"type": "text", "text": "still alive?"})
        types = set()
        while "done" not in types:
            types.add(ws.receive_json()["type"])
        assert "token" in types


def test_voice_ws_binds_turns_to_the_requested_session(client):
    """Server side of the wrong-session fix: ?session= is honored."""
    sid_a = client.post("/api/v1/chat/sessions", json={}).json()["session_id"]
    sid_b = client.post("/api/v1/chat/sessions", json={}).json()["session_id"]
    with client.websocket_connect(
            f"/api/v1/voice/live?token=e2e-test-token&session={sid_b}") as ws:
        assert ws.receive_json()["session_id"] == sid_b
        ws.send_json({"type": "text", "text": "record me in B"})
        while ws.receive_json()["type"] != "done":
            pass
    turns_b = client.get(f"/api/v1/chat/sessions/{sid_b}").json()
    turns_a = client.get(f"/api/v1/chat/sessions/{sid_a}").json()
    assert any("record me in B" in t["content"] for t in turns_b)
    assert turns_a == []


def test_embedding_cache_makes_reingest_free(client):
    """Changing one section of a file must re-embed ONLY that section —
    unchanged chunks come from the by-content-hash cache. Driven entirely
    through the public ingest API, like a user re-indexing their notes."""
    from pathlib import Path as P

    router = client.state_obj.router
    notes_dir = P(client.state_obj.files.mounts_summary()["notes"])
    sec1 = "Dolphins communicate with whistles. " * 12   # big enough to stay
    sec2 = "Rockets need staged combustion to reach orbit efficiently. " * 8
    doc = notes_dir / "cachetest.md"
    doc.write_text(f"# Cache Test\n\n## Marine\n\n{sec1}\n\n## Space\n\n{sec2}\n")

    def _ingest_and_wait():
        client.post("/api/v1/ingest")
        assert _wait(lambda: client.get("/api/v1/ingest/status").json()
                     .get("ledger", {}).get("ok", 0) > 0, timeout=15)

    _ingest_and_wait()
    _wait(lambda: any("Dolphins" in x for x in router.embedded_texts), timeout=10)
    assert sum("Dolphins communicate" in x for x in router.embedded_texts) == 1
    assert sum("staged combustion" in x for x in router.embedded_texts) == 1

    # append a NEW section: file hash changes, whole file re-chunks…
    with doc.open("a") as f:
        f.write("\n## Fresh\n\n" + "Glaciers carve valleys over millennia. " * 10 + "\n")
    _ingest_and_wait()
    assert _wait(lambda: any("Glaciers carve" in x for x in router.embedded_texts),
                 timeout=10), "new section never embedded"

    # …but the unchanged sections hit the cache: still embedded exactly once ever
    assert sum("Dolphins communicate" in x for x in router.embedded_texts) == 1
    assert sum("staged combustion" in x for x in router.embedded_texts) == 1


def test_disabled_digest_is_triggerable_via_api(client):
    """Fresh-install /digest must work even though the job ships disabled."""
    # the e2e config enables morning_digest; flip it off in the live scheduler
    job = next(j for j in client.state_obj.scheduler._jobs if j["name"] == "morning_digest")
    job["enabled"] = False
    try:
        r = client.post("/api/v1/automations/morning_digest/run")
        assert r.status_code == 200 and r.json()["result"]
        listing = client.get("/api/v1/automations").json()
        assert listing[0]["enabled"] is False
    finally:
        job["enabled"] = True
