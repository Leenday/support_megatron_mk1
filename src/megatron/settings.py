"""Runtime settings read from environment variables and `.env`."""

from pathlib import Path
from typing import Literal, Self

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # fake: keyword matching, no model; for development and tests without a key or a GPU.
    llm_backend: Literal["ollama", "openai", "gigachat", "fake"] = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:1.7b"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.4-mini"
    # Empty = api.openai.com; any OpenAI-compatible API otherwise (OpenRouter, vLLM, ...).
    openai_base_url: str | None = None
    gigachat_credentials: SecretStr | None = None
    departments_path: Path = Path("config/departments.yaml")

    # Web service (iteration 2). Empty DATABASE_URL = SQLite file in web/.
    database_url: str | None = None
    django_secret_key: SecretStr | None = None
    django_debug: bool = False
    django_allowed_hosts: list[str] = ["localhost", "127.0.0.1"]

    def with_llm(self, backend: str | None = None, model: str | None = None) -> Self:
        """These settings with the backend and its model replaced, e.g. by command-line flags."""
        if backend is None and model is None:
            return self
        backend = backend or self.llm_backend
        if backend not in ("ollama", "openai", "fake"):
            raise ValueError(f"backend {backend!r} is not implemented yet")
        update: dict[str, str] = {"llm_backend": backend}
        if model and backend != "fake":
            update[f"{backend}_model"] = model
        return self.model_copy(update=update)
