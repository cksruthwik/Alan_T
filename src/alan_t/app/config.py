"""Settings (env) + the models.yaml loader (INFRASTRUCTURE.md §3).

Secrets and connection strings exist only here, read at composition time
(SYSTEM_OVERVIEW.md layering rule 3).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from alan_t.core.llm import PurposeConfig
from alan_t.core.ports import ModelSpec


class Settings(BaseSettings):
    """Environment-driven configuration."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    alan_api_token: str = "change-me"
    database_url: str = "postgresql+asyncpg://alan:alan@localhost:5432/alan_t"
    alan_models_config: str = "config/models.yaml"
    alan_log_level: str = "INFO"

    # Provider keys (read by LiteLLM from the process env; declared so .env loads them).
    groq_api_key: str = ""
    google_api_key: str = ""
    nvidia_nim_api_key: str = ""

    # Memory (Mem0). Path for the local Qdrant vector store used by the memory layer.
    alan_memory_path: str = ".data/memory"
    # Stable identity long-term memory is keyed by. Single-user for now; revisit at M2 when
    # Telegram supplies a per-user id (BUILD_ORDER.md M2 / MEMORY_ARCHITECTURE.md §5).
    alan_user_id: str = "default"


def _spec_from_dict(raw: dict) -> ModelSpec:
    return ModelSpec(
        provider=raw["provider"],
        model=raw["model"],
        temperature=raw.get("temperature"),
        max_tokens=raw.get("max_tokens"),
    )


def load_purposes(path: str | Path) -> dict[str, PurposeConfig]:
    """Parse models.yaml into the ModelRouter's purpose map."""
    data = yaml.safe_load(Path(path).read_text())
    purposes: dict[str, PurposeConfig] = {}
    for purpose, cfg in data.items():
        primary = _spec_from_dict(cfg["primary"])
        fallbacks = tuple(_spec_from_dict(f) for f in cfg.get("fallbacks", []) or [])
        purposes[purpose] = PurposeConfig(primary=primary, fallbacks=fallbacks)
    return purposes
