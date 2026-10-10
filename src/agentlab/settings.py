from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTLAB_", env_file=".env", extra="ignore")

    config_dir: Path = Path("config")
    data_dir: Path = Path(".agentlab")
    env_file: Path = Path(".env")
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    database_url: str | None = None
    store_backend: str = "auto"
    runtime: str = "raw"
    sandbox: str = "docker"
