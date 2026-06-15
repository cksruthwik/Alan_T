"""ModelRouter — the thin choke point over the LLM seam (LLM_STRATEGY.md §4).

Resolves a *purpose* (CHAT, ROUTER, …) to a primary + fallback chain from config,
then calls the `LLMProvider` port, falling through the chain on rate-limit/unavailable.
Pure core: it depends on the port, never on LiteLLM.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from alan_t.core.ports import (
    LLMProvider,
    ModelSpec,
    ProviderUnavailableError,
    RateLimitedError,
)
from alan_t.core.types import ChatRequest, ChatResponse

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PurposeConfig:
    """A model purpose: its primary target plus an ordered fallback chain."""

    primary: ModelSpec
    fallbacks: tuple[ModelSpec, ...] = ()

    @property
    def chain(self) -> tuple[ModelSpec, ...]:
        return (self.primary, *self.fallbacks)


class AllProvidersExhaustedError(Exception):
    """Every model in a purpose's chain failed — honest failure for the caller."""


class ModelRouter:
    """Routes a purpose to a model, with fallback across the three providers."""

    def __init__(self, provider: LLMProvider, purposes: dict[str, PurposeConfig]) -> None:
        self._provider = provider
        self._purposes = purposes

    def has_purpose(self, purpose: str) -> bool:
        return purpose in self._purposes

    async def complete(self, purpose: str, req: ChatRequest) -> ChatResponse:
        """Call `purpose`'s model, falling through the chain on transient failure."""
        try:
            config = self._purposes[purpose]
        except KeyError as exc:
            raise KeyError(f"unknown model purpose: {purpose!r}") from exc

        last_error: Exception | None = None
        for depth, spec in enumerate(config.chain):
            try:
                resp = await self._provider.chat(spec, req)
            except (RateLimitedError, ProviderUnavailableError) as exc:
                last_error = exc
                log.warning(
                    "model.fallback purpose=%s from=%s reason=%s",
                    purpose,
                    spec.litellm_model,
                    type(exc).__name__,
                )
                continue
            if depth:
                log.info(
                    "model.call purpose=%s model=%s fallback_depth=%d",
                    purpose,
                    resp.model,
                    depth,
                )
            return resp

        raise AllProvidersExhaustedError(
            f"all providers exhausted for purpose {purpose!r}"
        ) from last_error
