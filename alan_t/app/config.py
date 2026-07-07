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

    # email agent (IMAP/SMTP; unset → agent not registered)
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 587
    email_address: str = ""
    email_password: str = ""

    # calendar agent (Google OAuth refresh-token flow; unset → not registered)
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_refresh_token: str = ""
    google_calendar_id: str = "primary"

    # web research / notifications / media
    brave_api_key: str = ""          # empty → DuckDuckGo fallback
    ntfy_topic: str = ""
    tts_voice: str = "Kore"

    # writable data (bind-mount in Docker to persist)
    notes_dir: str = "./data/notes"
    images_dir: str = "./data/images"
    uploads_dir: str = "./data/uploads"


def load_settings() -> Settings:
    return Settings()


def load_app_config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "app.yaml").read_text())


MODELS_YAML = CONFIG_DIR / "models.yaml"
