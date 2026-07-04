"""The one composition root — wires adapters to ports (layering rule #4)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from alan_t.adapters.model_router import ModelRouter
from alan_t.adapters.null_memory import NullMemory
from alan_t.adapters.postgres.store import ConversationStore, make_engine
from alan_t.adapters.vfs_files import VfsFiles
from alan_t.app.config import CONFIG_DIR, MODELS_YAML, Settings, load_app_config, load_settings
from alan_t.core.agents.base import AgentContext
from alan_t.core.agents.conversation import ConversationAgent
from alan_t.core.agents.file_agent import FileAgent
from alan_t.core.knowledge.retrieval import Retriever
from alan_t.workers.ingest import Ingester


@dataclass
class App:
    settings: Settings
    router: ModelRouter
    store: ConversationStore
    ctx: AgentContext
    conversation: ConversationAgent
    file_agent: FileAgent | None = None
    files: VfsFiles | None = None
    ingester: Ingester | None = None
    retriever: Retriever | None = None


def build() -> App:
    settings = load_settings()

    # LiteLLM reads provider keys from its own env names; map ours once, here.
    os.environ.setdefault("GROQ_API_KEY", settings.groq_api_key)
    os.environ.setdefault("GEMINI_API_KEY", settings.google_api_key)
    os.environ.setdefault("NVIDIA_NIM_API_KEY", settings.nvidia_api_key)

    router = ModelRouter(MODELS_YAML)
    engine = make_engine(settings.database_url)
    store = ConversationStore(engine)
    app_config = load_app_config()

    memory = NullMemory()
    if app_config.get("features", {}).get("memory"):
        try:
            from alan_t.adapters.mem0_memory import Mem0Memory

            memory = Mem0Memory(settings.database_url)
        except ImportError:
            pass  # mem0 extra not installed → degrade to no memory

    files = file_agent = ingester = retriever = None
    if app_config.get("features", {}).get("knowledge"):
        files = VfsFiles(settings.vfs_metadata_uri, settings.vfs_blob_uri, CONFIG_DIR / "vfs.yaml")
        retriever = Retriever(engine, router)
        ingester = Ingester(engine, router, files, embedder_model=router.embedder_model)
        file_agent = FileAgent(retriever)

    ctx = AgentContext(
        llm=router,
        memory=memory,
        files=files,
        config=app_config,
        user_name=settings.user_name,
    )
    return App(
        settings=settings,
        router=router,
        store=store,
        ctx=ctx,
        conversation=ConversationAgent(),
        file_agent=file_agent,
        files=files,
        ingester=ingester,
        retriever=retriever,
    )
