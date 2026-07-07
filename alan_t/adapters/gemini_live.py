"""Gemini Live bridge (VOICE_ARCHITECTURE.md Path B, ADR-007/014).

Browser WS ↔ Gemini Live session, native speech-to-speech. The doc's honest
capability asymmetry applies: the live model is Gemini's, not the role
registry's. Tool calls are bridged through the ONE permission gate — ALLOW
executes, ASK reports "pending approval" into the conversation instead of
running. Requires the optional `google-genai` package (extra: live-voice).

Client protocol (JSON over our WS):
  → {"type": "audio", "data": <b64 pcm16 @16kHz mono>}   mic chunks
  → {"type": "end"}                                       hang up
  ← {"type": "audio", "data": <b64 pcm16 @24kHz mono>}    model speech
  ← {"type": "transcript", "role": "user"|"assistant", "text": ...}
  ← {"type": "turn_complete"}
"""

from __future__ import annotations

import asyncio
import base64
import logging

from fastapi import WebSocket, WebSocketDisconnect

from alan_t.core.tools import ALLOW, NeedsApproval, ToolRegistry

log = logging.getLogger("alan_t.live")

DEFAULT_LIVE_MODEL = "gemini-2.5-flash-native-audio-latest"


class GeminiLiveBridge:
    def __init__(self, api_key: str, registry: ToolRegistry, approvals, model: str = DEFAULT_LIVE_MODEL):
        self._api_key = api_key
        self._model = model
        self._registry = registry
        self._approvals = approvals

    def _tool_declarations(self) -> list[dict]:
        # only ALLOW-tier tools are offered live; ASK mid-speech is jarring —
        # the model is told to route those through a normal chat instead
        return [{"name": t["name"], "description": t["description"],
                 "parameters": t["parameters"]}
                for t in self._registry.specs() if t["tier"] == ALLOW]

    async def _dispatch_tool(self, name: str, args: dict) -> str:
        try:
            result = await self._registry.execute(name, args or {})
            return str(result)[:4000]
        except NeedsApproval:
            a = self._approvals.create(name, args or {})
            return f"NOT EXECUTED — needs approval (request #{a.id}); tell the user."
        except Exception as e:
            return f"TOOL ERROR ({type(e).__name__}): {e}"

    async def run(self, ws: WebSocket, system_instruction: str,
                  transcript: list[tuple[str, str]]) -> None:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._api_key)
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=system_instruction,
            input_audio_transcription={},
            output_audio_transcription={},
            tools=[{"function_declarations": self._tool_declarations()}] or None,
        )
        async with client.aio.live.connect(model=self._model, config=config) as session:
            async def pump_client_to_model():
                while True:
                    msg = await ws.receive_json()
                    if msg.get("type") == "end":
                        return
                    if msg.get("type") == "audio":
                        await session.send_realtime_input(audio=types.Blob(
                            data=base64.b64decode(msg["data"]),
                            mime_type="audio/pcm;rate=16000"))

            async def pump_model_to_client():
                async for response in session.receive():
                    sc = response.server_content
                    if sc is not None:
                        if sc.input_transcription and sc.input_transcription.text:
                            transcript.append(("user", sc.input_transcription.text))
                            await ws.send_json({"type": "transcript", "role": "user",
                                                "text": sc.input_transcription.text})
                        if sc.output_transcription and sc.output_transcription.text:
                            transcript.append(("assistant", sc.output_transcription.text))
                            await ws.send_json({"type": "transcript", "role": "assistant",
                                                "text": sc.output_transcription.text})
                        if sc.model_turn:
                            for part in sc.model_turn.parts or []:
                                if part.inline_data and part.inline_data.data:
                                    await ws.send_json({
                                        "type": "audio",
                                        "data": base64.b64encode(part.inline_data.data).decode()})
                        if sc.turn_complete:
                            await ws.send_json({"type": "turn_complete"})
                    if response.tool_call:
                        results = []
                        for fc in response.tool_call.function_calls:
                            log.info("live tool call: %s", fc.name)
                            output = await self._dispatch_tool(fc.name, dict(fc.args or {}))
                            results.append(types.FunctionResponse(
                                id=fc.id, name=fc.name, response={"result": output}))
                        await session.send_tool_response(function_responses=results)

            up = asyncio.create_task(pump_client_to_model())
            down = asyncio.create_task(pump_model_to_client())
            try:
                done, pending = await asyncio.wait(
                    {up, down}, return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
                for t in done:
                    if t.exception() and not isinstance(t.exception(), WebSocketDisconnect):
                        raise t.exception()
            finally:
                up.cancel()
                down.cancel()
