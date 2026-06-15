"""LiteLLM adapter — the only place provider SDK code lives (ADR-011).

Implements the `LLMProvider` port. Translates core domain types to/from LiteLLM and
normalizes provider 429s to `RateLimitedError` so the ModelRouter can fall through.
"""

from __future__ import annotations

import litellm
from litellm.exceptions import RateLimitError, ServiceUnavailableError

from alan_t.core.ports import (
    ModelSpec,
    ProviderUnavailableError,
    RateLimitedError,
)
from alan_t.core.types import ChatRequest, ChatResponse, Usage

# Don't let LiteLLM mutate global state or drop params silently on us.
litellm.drop_params = True


class LiteLLMProvider:
    """A single seam over Groq + Google + NVIDIA NIM (and any LiteLLM provider)."""

    async def chat(self, spec: ModelSpec, req: ChatRequest) -> ChatResponse:
        messages = [{"role": m.role.value, "content": m.content} for m in req.messages]
        kwargs: dict = {"model": spec.litellm_model, "messages": messages}
        temperature = req.temperature if req.temperature is not None else spec.temperature
        if temperature is not None:
            kwargs["temperature"] = temperature
        max_tokens = req.max_tokens if req.max_tokens is not None else spec.max_tokens
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        try:
            resp = await litellm.acompletion(**kwargs)
        except RateLimitError as exc:
            raise RateLimitedError(str(exc)) from exc
        except ServiceUnavailableError as exc:
            raise ProviderUnavailableError(str(exc)) from exc
        except Exception as exc:
            # Any other provider error → treat as unavailable so the router can fall through.
            raise ProviderUnavailableError(str(exc)) from exc

        choice = resp.choices[0]
        usage = getattr(resp, "usage", None)
        return ChatResponse(
            text=choice.message.content or "",
            model=resp.model or spec.litellm_model,
            usage=Usage(
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            ),
            finish_reason=getattr(choice, "finish_reason", None),
        )
