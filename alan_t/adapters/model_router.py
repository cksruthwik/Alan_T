"""The LiteLLM seam + ModelRouter (LLM_STRATEGY §4).

One function per call shape; purpose → primary + fallback chain from config/models.yaml.
No LiteLLM types cross this module's boundary — core domain types only.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import litellm
import yaml

from alan_t.core.types import ChatDelta, ChatRequest, ChatResponse, HonestFailure

log = logging.getLogger("alan_t.llm")

# provider label in config → LiteLLM model prefix
_PREFIX = {"groq": "groq/", "google": "gemini/", "nvidia": "nvidia_nim/"}

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
    def __init__(self, models_config_path: str | Path):
        self._config: dict[str, Any] = yaml.safe_load(Path(models_config_path).read_text())

    def chain(self, purpose: str) -> list[dict[str, Any]]:
        cfg = self._config.get(purpose)
        if not cfg:
            raise KeyError(f"unknown model purpose: {purpose}")
        return [cfg["primary"], *cfg.get("fallbacks", [])]

    async def complete(self, purpose: str, req: ChatRequest) -> ChatResponse:
        messages = [{"role": m.role, "content": m.content} for m in req.messages]
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
                    num_retries=1,
                )
            except _FALLTHROUGH as e:
                last_err = e
                log.warning("llm fallthrough purpose=%s model=%s err=%s", purpose, model, type(e).__name__)
                continue
            usage = getattr(resp, "usage", None)
            log.info(
                "llm ok purpose=%s model=%s latency_ms=%d tokens=%s/%s fallback_depth=%d",
                purpose, model, (time.monotonic() - t0) * 1000,
                getattr(usage, "prompt_tokens", "?"), getattr(usage, "completion_tokens", "?"), depth,
            )
            return ChatResponse(
                text=resp.choices[0].message.content or "",
                model=model,
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                fallback_depth=depth,
            )
        retry_after = getattr(last_err, "retry_after", None) if last_err else None
        raise HonestFailure(
            f"All providers for {purpose} are unavailable or rate-limited.",
            retry_after_seconds=retry_after,
        )

    async def stream(self, purpose: str, req: ChatRequest) -> AsyncIterator[ChatDelta]:
        messages = [{"role": m.role, "content": m.content} for m in req.messages]
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
