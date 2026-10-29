"""Runtime settings read from environment variables and `.env`."""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_backend: Literal["ollama", "openai", "gigachat"] = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:1.7b"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.4-mini"
    # Empty = api.openai.com; any OpenAI-compatible API otherwise (OpenRouter, vLLM, ...).
    openai_base_url: str | None = None
    gigachat_credentials: SecretStr | None = None
    departments_path: Path = Path("config/departments.yaml")
