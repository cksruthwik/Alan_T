"""The LiteLLM seam + ModelRouter (LLM_STRATEGY §4).

One function per call shape; purpose → primary + fallback chain from config/models.yaml.
No LiteLLM types cross this module's boundary — core domain types only.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import litellm
import yaml

from alan_t.core.observability import LLM_CALLS, LLM_LATENCY, LLM_TOKENS
from alan_t.core.types import (
    ChatDelta,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    HonestFailure,
    LLMToolCall,
)

log = logging.getLogger("alan_t.llm")

# provider label in config → LiteLLM model prefix
_PREFIX = {"groq": "groq/", "google": "gemini/", "nvidia": "nvidia_nim/"}

# Capability gate (LLM_STRATEGY §5): what each role's models must be able to do.
# Capabilities per model come from config/capabilities.yaml; unknown = refuse to start.
ROLE_REQUIREMENTS: dict[str, set[str]] = {
    "CHAT": {"chat", "streaming"},
    "ROUTER": {"chat", "json_mode"},
    "SUMMARIZER": {"chat", "json_mode"},
    "REASONER": {"chat"},
    "LONG_CONTEXT": {"chat", "long_context"},
    "VISION": {"vision_in"},
    "STT": {"audio_in"},
    "TTS": {"audio_out"},
    "EMBEDDER": {"embeddings"},
    "REFLECTOR": {"chat", "json_mode"},
    "LIVE_VOICE": {"audio_in", "audio_out"},
}


def _image_part(ref: str) -> dict[str, Any]:
    """Local path → base64 data URI; URLs/data URIs pass through."""
    if ref.startswith(("http://", "https://", "data:")):
        url = ref
    else:
        mime = mimetypes.guess_type(ref)[0] or "image/jpeg"
        url = f"data:{mime};base64,{base64.b64encode(Path(ref).read_bytes()).decode()}"
    return {"type": "image_url", "image_url": {"url": url}}


def _to_provider_message(m: ChatMessage) -> dict[str, Any]:
    if m.role == "tool":
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
    if m.tool_calls:
        return {"role": m.role, "content": m.content or None, "tool_calls": [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
            for tc in m.tool_calls
        ]}
    if not m.images:
        return {"role": m.role, "content": m.content}
    parts: list[dict[str, Any]] = [{"type": "text", "text": m.content}] if m.content else []
    parts += [_image_part(ref) for ref in m.images]
    return {"role": m.role, "content": parts}


def _parse_tool_calls(message: Any) -> list[LLMToolCall]:
    out = []
    for tc in getattr(message, "tool_calls", None) or []:
        try:
            args = json.loads(tc.function.arguments) if tc.function.arguments else {}
        except json.JSONDecodeError:
            args = {"_raw": tc.function.arguments}
        out.append(LLMToolCall(id=tc.id or f"call_{len(out)}", name=tc.function.name, arguments=args))
    return out


def _tool_schemas(tools: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [{"type": "function", "function": {
        "name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
        for t in tools]

# errors that mean "try the next provider in the chain"
_FALLTHROUGH = (
    litellm.RateLimitError,
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
    litellm.APIConnectionError,
    litellm.Timeout,
)


def _litellm_model(entry: dict[str, Any]) -> str:
    return _PREFIX[entry["provider"]] + entry["model"]


class ModelRouter:
    def __init__(self, models_config_path: str | Path, capabilities_path: str | Path | None = None):
        self._config: dict[str, Any] = yaml.safe_load(Path(models_config_path).read_text())
        self._capabilities: dict[str, list[str]] = {}
        if capabilities_path and Path(capabilities_path).exists():
            self._capabilities = yaml.safe_load(Path(capabilities_path).read_text()) or {}

    def verify(self) -> None:
        """Capability gate at bootstrap (LLM_STRATEGY §5): refuse to start on a
        model that can't do its role's job, or one we can't verify. Config-only,
        no network — a bad swap dies at startup, not mid-conversation."""
        problems: list[str] = []
        for role, cfg in self._config.items():
            required = ROLE_REQUIREMENTS.get(role)
            if required is None:
                continue  # unknown role: allowed (custom role), nothing to check
            for entry in [cfg["primary"], *cfg.get("fallbacks", [])]:
                key = f"{entry['provider']}/{entry['model']}"
                declared = self._capabilities.get(key)
                if declared is None:
                    problems.append(f"{role} → {key}: no entry in capabilities.yaml — can't verify")
                    continue
                missing = required - set(declared)
                if missing:
                    problems.append(f"{role} → {key}: missing {sorted(missing)}")
        if problems:
            raise RuntimeError("capability gate failed:\n  " + "\n  ".join(problems))

    def chain(self, purpose: str) -> list[dict[str, Any]]:
        cfg = self._config.get(purpose)
        if not cfg:
            raise KeyError(f"unknown model purpose: {purpose}")
        return [cfg["primary"], *cfg.get("fallbacks", [])]

    async def complete(self, purpose: str, req: ChatRequest) -> ChatResponse:
        messages = [_to_provider_message(m) for m in req.messages]
        last_err: Exception | None = None
        for depth, entry in enumerate(self.chain(purpose)):
            model = _litellm_model(entry)
            t0 = time.monotonic()
            try:
                resp = await litellm.acompletion(
                    model=model,
                    messages=messages,
                    temperature=req.temperature or entry.get("temperature"),
                    max_tokens=req.max_tokens,
                    response_format=req.response_format,
                    tools=_tool_schemas(req.tools),
                    num_retries=1,
                )
            except _FALLTHROUGH as e:
                last_err = e
                LLM_CALLS.labels(role=purpose, model=model, outcome="fallthrough").inc()
                log.warning("llm fallthrough purpose=%s model=%s err=%s", purpose, model, type(e).__name__)
                continue
            usage = getattr(resp, "usage", None)
            latency = time.monotonic() - t0
            in_tok = getattr(usage, "prompt_tokens", 0) or 0
            out_tok = getattr(usage, "completion_tokens", 0) or 0
            LLM_CALLS.labels(role=purpose, model=model, outcome="ok").inc()
            LLM_LATENCY.labels(role=purpose).observe(latency)
            LLM_TOKENS.labels(role=purpose, direction="in").inc(in_tok)
            LLM_TOKENS.labels(role=purpose, direction="out").inc(out_tok)
            log.info(
                "llm ok purpose=%s model=%s latency_ms=%d tokens=%s/%s fallback_depth=%d",
                purpose, model, latency * 1000, in_tok, out_tok, depth,
            )
            message = resp.choices[0].message
            return ChatResponse(
                text=message.content or "",
                model=model,
                input_tokens=in_tok,
                output_tokens=out_tok,
                fallback_depth=depth,
                tool_calls=_parse_tool_calls(message),
            )
        retry_after = getattr(last_err, "retry_after", None) if last_err else None
        raise HonestFailure(
            f"All providers for {purpose} are unavailable or rate-limited.",
            retry_after_seconds=retry_after,
        )

    async def stream(self, purpose: str, req: ChatRequest) -> AsyncIterator[ChatDelta]:
        messages = [_to_provider_message(m) for m in req.messages]
        for entry in self.chain(purpose):
            model = _litellm_model(entry)
            try:
                resp = await litellm.acompletion(
                    model=model,
                    messages=messages,
                    temperature=req.temperature or entry.get("temperature"),
                    max_tokens=req.max_tokens,
                    stream=True,
                )
            except _FALLTHROUGH:
                continue
            async for chunk in resp:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield ChatDelta(text=delta)
            return
        raise HonestFailure(f"All providers for {purpose} are unavailable or rate-limited.")

    async def transcribe(self, audio_path: str | Path) -> str:
        """STT with the same fallback discipline as chat (LLM_STRATEGY §3 STT role)."""
        last_err: Exception | None = None
        for entry in self.chain("STT"):
            model = _litellm_model(entry)
            try:
                with open(audio_path, "rb") as f:
                    resp = await litellm.atranscription(model=model, file=f)
                log.info("stt ok model=%s", model)
                return resp.text
            except _FALLTHROUGH as e:
                last_err = e
                log.warning("stt fallthrough model=%s err=%s", model, type(e).__name__)
        raise HonestFailure(
            "All STT providers are unavailable or rate-limited.",
            retry_after_seconds=getattr(last_err, "retry_after", None) if last_err else None,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # EMBEDDER deliberately has NO fallback — a silent embedder switch would
        # corrupt the vector space (LLM_STRATEGY §5).
        entry = self._config["EMBEDDER"]["primary"]
        resp = await litellm.aembedding(
            model=_litellm_model(entry),
            input=texts,
            dimensions=entry.get("dimensions"),
        )
        return [d["embedding"] for d in resp.data]

    @property
    def embedder_model(self) -> str:
        e = self._config["EMBEDDER"]["primary"]
        return f"{e['model']}@{e.get('dimensions', 'native')}"

    def active_models(self) -> dict[str, list[str]]:
        """Read-only view for GET /system/models."""
        return {p: [_litellm_model(e) for e in self.chain(p)] for p in self._config}
