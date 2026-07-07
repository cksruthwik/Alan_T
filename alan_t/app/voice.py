"""Voice surfaces (Docs_COMPLEX/voice/VOICE_ARCHITECTURE.md).

Path A — turn-based (voice notes / push-to-talk), provider-neutral:
    POST /api/v1/voice/turn        audio → STT → full chat turn → text + TTS
    WS   /api/v1/voice/live        same loop over a socket; long answers start
                                   speaking at the FIRST SENTENCE BOUNDARY
                                   (stream → sentence → TTS chunk), per the doc's
                                   latency rule. This is also the documented
                                   provider-neutral escape for live mode.

Path B — native Gemini Live (speech-to-speech):
    WS   /api/v1/voice/live-native browser audio ↔ Gemini Live session; persona +
                                   recalled memories injected at session start;
                                   tool calls bridged through the SAME permission
                                   gate (ALLOW executes, ASK reports pending);
                                   transcript persisted at session end.

Shared rules honored: transcripts are first-class conversation turns
(modality="voice"); audio blobs are never stored; live mode is explicitly
user-initiated per session.
"""

from __future__ import annotations

import base64
import contextlib
import logging
import re
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect

from alan_t.app.chat_service import finish_turn, prepare_task, run_turn
from alan_t.core.types import HonestFailure

log = logging.getLogger("alan_t.voice")

_SENTENCE_END = re.compile(r"[.!?]\s")
_MIN_SPEAK_CHARS = 60  # don't TTS fragments; wait for a real first sentence


async def _transcribe_bytes(state, audio: bytes, suffix: str = ".ogg") -> str:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio)
        tmp = f.name
    try:
        return (await state.router.transcribe(tmp)).strip()
    finally:
        Path(tmp).unlink(missing_ok=True)


def _sentences(buffer: str) -> tuple[list[str], str]:
    """Split completed sentences off the front of a streaming buffer."""
    out = []
    while True:
        m = _SENTENCE_END.search(buffer)
        if not m or m.end() < _MIN_SPEAK_CHARS:
            break
        out.append(buffer[:m.end()].strip())
        buffer = buffer[m.end():]
    return out, buffer


def mount_voice(app: FastAPI, state, auth_dep=None) -> None:
    deps = [auth_dep] if auth_dep else []
    async def _resolve_session(session_id: str | None) -> uuid.UUID:
        if session_id:
            sid = uuid.UUID(session_id)
            if await state.store.session_exists(sid):
                return sid
        return await state.store.create_session(channel="voice")

    # ── Path A: one-shot voice turn ────────────────────────────────────

    @app.post("/api/v1/voice/turn", dependencies=deps)
    async def voice_turn(audio: UploadFile, session_id: str | None = None,
                         speak: bool = True):
        sid = await _resolve_session(session_id)
        suffix = Path(audio.filename or "note.ogg").suffix or ".ogg"
        transcript = await _transcribe_bytes(state, await audio.read(), suffix)
        if not transcript:
            raise HTTPException(422, "no speech recognized")
        turn_id, result, agent_name = await run_turn(
            state, sid, transcript, channel="voice", modality="voice")
        reply_audio = None
        if speak and state.media.configured:
            try:
                reply_audio = base64.b64encode(
                    await state.media.speak(result.response[:1500])).decode()
            except Exception:
                log.warning("TTS failed for voice turn — text-only reply", exc_info=True)
        return {"session_id": str(sid), "turn_id": str(turn_id), "transcript": transcript,
                "content": result.response, "agent": agent_name, "status": result.status,
                "audio_wav_b64": reply_audio}

    # ── Path A: composed live loop (WS, push-to-talk utterances) ──────

    @app.websocket("/api/v1/voice/live")
    async def voice_live(ws: WebSocket):
        token = ws.query_params.get("token") or ""
        if token != state.settings.alan_api_token:
            await ws.close(code=4401)
            return
        await ws.accept()
        sid = await _resolve_session(ws.query_params.get("session"))
        await ws.send_json({"type": "session", "session_id": str(sid)})
        try:
            while True:
                msg = await ws.receive_json()
                if msg.get("type") == "audio":
                    try:
                        text = await _transcribe_bytes(
                            state, base64.b64decode(msg["data"]), f".{msg.get('format', 'ogg')}")
                    except HonestFailure as e:
                        await ws.send_json({"type": "error", "detail": str(e), "status": 503})
                        continue
                    if not text:
                        await ws.send_json({"type": "error", "detail": "no speech recognized"})
                        continue
                    await ws.send_json({"type": "transcript", "text": text})
                elif msg.get("type") == "text":
                    text = msg.get("text", "").strip()
                    if not text:
                        continue
                else:
                    await ws.send_json({"type": "error", "detail": "send audio|text"})
                    continue

                try:
                    await _live_turn(ws, sid, text)
                except HonestFailure as e:
                    await ws.send_json({"type": "error", "detail": str(e), "status": 503})
                except Exception:
                    log.exception("voice turn failed")
                    await ws.send_json({"type": "error", "status": 500,
                                        "detail": "that turn failed on the backend — try again"})
        except WebSocketDisconnect:
            pass

    async def _speak_chunk(ws: WebSocket, sentence: str) -> None:
        if not state.media.configured:
            return
        try:
            wav = await state.media.speak(sentence)
            await ws.send_json({"type": "audio", "format": "wav",
                                "data": base64.b64encode(wav).decode()})
        except Exception:
            log.warning("TTS chunk failed — continuing text-only", exc_info=True)

    async def _live_turn(ws: WebSocket, sid: uuid.UUID, text: str) -> None:
        """One spoken exchange: route; stream tokens; TTS at sentence boundaries."""
        trace_id = str(uuid.uuid4())
        task = await prepare_task(state, sid, text, channel="voice", modality="voice")
        await state.store.add_turn(sid, "user", text, trace_id=trace_id, modality="voice")
        agent, skill_names = await state.supervisor.route(task, state.ctx)
        task.skills = state.skills.render(skill_names)

        if hasattr(agent, "run_stream"):
            buffer, parts = "", []
            async for delta in agent.run_stream(task, state.ctx):
                parts.append(delta.text)
                buffer += delta.text
                await ws.send_json({"type": "token", "text": delta.text})
                done_sentences, buffer = _sentences(buffer)
                for s in done_sentences:
                    await _speak_chunk(ws, s)
            answer = "".join(parts)
            if buffer.strip():
                await _speak_chunk(ws, buffer.strip()[:1500])
        else:
            result = await agent.run(task, state.ctx)
            answer = result.response
            await ws.send_json({"type": "token", "text": answer})
            await _speak_chunk(ws, answer[:1500])

        turn_id = await finish_turn(state, sid, text, answer, agent_name=agent.name,
                                    trace_id=trace_id, modality="voice")
        await ws.send_json({"type": "done", "turn_id": str(turn_id), "agent": agent.name})

    # ── Path B: native Gemini Live bridge ─────────────────────────────

    @app.websocket("/api/v1/voice/live-native")
    async def voice_live_native(ws: WebSocket):
        token = ws.query_params.get("token") or ""
        if token != state.settings.alan_api_token:
            await ws.close(code=4401)
            return
        await ws.accept()
        try:
            from alan_t.adapters.gemini_live import GeminiLiveBridge
        except ImportError:
            await ws.send_json({"type": "error", "detail":
                                "Native live voice needs the google-genai package: "
                                "uv sync --extra live-voice"})
            await ws.close()
            return
        live_model = state.router.chain("LIVE_VOICE")[0]["model"] \
            if "LIVE_VOICE" in state.router.active_models() else None
        bridge = GeminiLiveBridge(
            api_key=state.settings.google_api_key,
            registry=state.tools,
            approvals=state.approvals,
            **({"model": live_model} if live_model else {}),
        )
        sid = await _resolve_session(ws.query_params.get("session"))
        memories = []
        try:
            memories = await state.ctx.memory.recall("user preferences goals", limit=8)
        except Exception:
            pass
        persona = (f"You are Alan_T, {state.settings.user_name}'s personal assistant, "
                   "in a live voice conversation. Be concise and natural — this is speech. "
                   "For long multi-step work, say you'll handle it in the background "
                   "rather than narrating it.")
        if memories:
            persona += "\n\nWhat you remember:\n" + "\n".join(f"- {m.content}" for m in memories)
        transcript: list[tuple[str, str]] = []
        try:
            await bridge.run(ws, system_instruction=persona, transcript=transcript)
        except WebSocketDisconnect:
            pass
        except Exception as e:
            log.exception("live-native session failed")
            with contextlib.suppress(Exception):
                await ws.send_json({"type": "error", "detail": f"{type(e).__name__}: {e}"})
        finally:
            # shared rule 1: voice conversations are first-class, searchable turns
            for role, text in transcript:
                if text.strip():
                    await state.store.add_turn(sid, role, text, modality="voice",
                                               agent="live_voice" if role == "assistant" else None)
