"""Composition root — the one place adapters are built and bound to ports.

`build_container` is the only function that knows about concrete adapters
(SYSTEM_OVERVIEW.md layering rule 4).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from alan_t.adapters.db import make_engine, make_session_factory
from alan_t.adapters.litellm_provider import LiteLLMProvider
from alan_t.adapters.mem0_provider import Mem0Provider
from alan_t.adapters.repository import SqlConversationStore
from alan_t.app.config import Settings, load_purposes
from alan_t.core.agents.base import AgentContext
from alan_t.core.agents.conversation import ConversationAgent
from alan_t.core.llm import ModelRouter
from alan_t.core.ports import MemoryPort

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Container:
    """Wired application services."""

    settings: Settings
    models: ModelRouter
    store: SqlConversationStore
    conversation: ConversationAgent
    memory: MemoryPort | None

    def agent_context(self) -> AgentContext:
        return AgentContext(models=self.models, store=self.store, memory=self.memory)


def _export_provider_keys(settings: Settings) -> None:
    """Make provider keys visible to LiteLLM under the names it expects."""
    if settings.groq_api_key:
        os.environ.setdefault("GROQ_API_KEY", settings.groq_api_key)
    if settings.google_api_key:
        # LiteLLM's `gemini/` provider reads GEMINI_API_KEY.
        os.environ.setdefault("GEMINI_API_KEY", settings.google_api_key)
    if settings.nvidia_nim_api_key:
        os.environ.setdefault("NVIDIA_NIM_API_KEY", settings.nvidia_nim_api_key)


def _build_memory(settings: Settings) -> MemoryPort | None:
    """Build Mem0Provider when required API keys are present; otherwise return None.

    LLM: Groq (fact extraction). Embedder: fastembed (local, no API key). Vector store:
    Qdrant (local path). Returns None if Groq key is absent so the app degrades gracefully.
    """
    if not settings.groq_api_key:
        logger.warning("GROQ_API_KEY not set — long-term memory disabled")
        return None

    # Self-hosted, single-user, the user's data: opt out of Mem0's phone-home telemetry
    # (MEMORY_ARCHITECTURE.md §5). Must precede the import — Mem0 reads this at import time.
    os.environ.setdefault("MEM0_TELEMETRY", "False")

    try:
        from mem0 import Memory
        from mem0.configs.base import EmbedderConfig, LlmConfig, MemoryConfig, VectorStoreConfig
    except ImportError:
        logger.warning("mem0ai not installed — long-term memory disabled")
        return None

    # Keep every piece of memory state under one directory so a single persistent volume
    # (and one config knob) covers it — this is what survives a restart for the M1 DoD.
    base = settings.alan_memory_path
    config = MemoryConfig(
        # Route Mem0's fact-extraction LLM through LiteLLM (the project's one model seam)
        # rather than the standalone `groq` SDK — reuses GROQ_API_KEY exported above.
        llm=LlmConfig(
            provider="litellm",
            config={"model": "groq/llama-3.3-70b-versatile"},
        ),
        embedder=EmbedderConfig(
            provider="fastembed",
            config={"model": "BAAI/bge-small-en-v1.5"},
        ),
        vector_store=VectorStoreConfig(
            provider="qdrant",
            config={
                "collection_name": "alan_t_memory",
                "embedding_model_dims": 384,
                "path": os.path.join(base, "qdrant"),
            },
        ),
        history_db_path=os.path.join(base, "history.db"),
    )
    return Mem0Provider(Memory(config=config))


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    _export_provider_keys(settings)

    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    store = SqlConversationStore(factory)

    purposes = load_purposes(settings.alan_models_config)
    models = ModelRouter(LiteLLMProvider(), purposes)
    memory = _build_memory(settings)

    return Container(
        settings=settings,
        models=models,
        store=store,
        conversation=ConversationAgent(),
        memory=memory,
    )
