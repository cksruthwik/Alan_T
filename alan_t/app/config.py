"""Settings from env + config/*.yaml. Secrets exist only here (layering rule #3)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    groq_api_key: str = ""
    google_api_key: str = ""
    nvidia_api_key: str = ""
    alan_api_token: str = ""
    fernet_key: str = ""
    telegram_bot_token: str = ""
    telegram_allowed_user_id: int = 0
    database_url: str = "postgresql+asyncpg://alan:alan@localhost:5432/alan_t"
    user_name: str = "Ruthwik"
    # ai-vfs stores (AI_VFS.md §2) — sqlite+local blobs by default; swap to the
    # shared Postgres by env when deployed (AIFS_* consumed via these settings)
    vfs_metadata_uri: str = "sqlite:///./data/aifs.db"
    vfs_blob_uri: str = "file:///./data/aifs_blobs/"


def load_settings() -> Settings:
    return Settings()


def load_app_config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "app.yaml").read_text())


MODELS_YAML = CONFIG_DIR / "models.yaml"
