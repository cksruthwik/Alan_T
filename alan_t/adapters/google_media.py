"""Google media adapter: TTS voice replies + image generation.

Direct httpx against the Generative Language REST API — LiteLLM's coverage of
Gemini TTS/Imagen is not stable enough to sit on a critical path, so this
adapter owns the wire format; models still come from config/models.yaml
(TTS / IMAGE_GEN roles), keys from settings. No cross-provider fallback:
NVIDIA NIM offers neither TTS nor image gen via API (honest gap, models.yaml).
"""

from __future__ import annotations

import base64
import logging
import struct

import httpx

log = logging.getLogger("alan_t.media")

API = "https://generativelanguage.googleapis.com/v1beta"


def _pcm_to_wav(pcm: bytes, rate: int = 24000) -> bytes:
    """Gemini TTS returns raw 16-bit mono PCM; wrap a minimal WAV header."""
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16,
        1, 1, rate, rate * 2, 2, 16, b"data", len(pcm),
    )
    return header + pcm


class GoogleMediaAdapter:
    def __init__(self, api_key: str, tts_model: str, image_model: str, voice: str = "Kore"):
        self._key = api_key
        self._tts_model = tts_model
        self._image_model = image_model
        self._voice = voice

    @property
    def configured(self) -> bool:
        return bool(self._key)

    async def speak(self, text: str) -> bytes:
        """text → WAV bytes (voice replies for Telegram/web)."""
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{API}/models/{self._tts_model}:generateContent",
                params={"key": self._key},
                json={
                    "contents": [{"parts": [{"text": text}]}],
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {"voiceConfig": {
                            "prebuiltVoiceConfig": {"voiceName": self._voice}}},
                    },
                },
            )
            r.raise_for_status()
            part = r.json()["candidates"][0]["content"]["parts"][0]
            return _pcm_to_wav(base64.b64decode(part["inlineData"]["data"]))

    async def generate_image(self, prompt: str) -> bytes:
        """prompt → PNG bytes (IMAGE_GEN role; not on any critical path)."""
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{API}/models/{self._image_model}:predict",
                params={"key": self._key},
                json={"instances": [{"prompt": prompt}],
                      "parameters": {"sampleCount": 1}},
            )
            r.raise_for_status()
            pred = r.json()["predictions"][0]
            return base64.b64decode(pred["bytesBase64Encoded"])
