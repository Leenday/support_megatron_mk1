"""LLM adapters: request text -> validated Ticket.

Every adapter sends the ticket's JSON schema to the model (structured outputs), so the
answer is constrained to the schema and the department enum; Pydantic validates it again
and the request is retried if validation still fails. Adapters differ only in how they call
the model (`Extractor.complete`); the backend is picked by `LLM_BACKEND`.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, Protocol

import ollama
import openai
from pydantic import ValidationError

from megatron.departments import DepartmentsConfig
from megatron.prompt import build_system_prompt
from megatron.settings import Settings
from megatron.ticket import (
    Ticket,
    build_ticket_model,
    keep_fallback_alone,
    keep_quoted_identifiers,
)

logger = logging.getLogger(__name__)

Messages = list[dict[str, str]]


class ExtractionError(RuntimeError):
    """The model did not return a valid ticket after all attempts."""


class BackendError(RuntimeError):
    """The model server cannot be used (unreachable, wrong key, unknown model)."""


class Extractor(ABC):
    """Prompt, schema, validation and retry; subclasses only call their model."""

    def __init__(self, config: DepartmentsConfig, model: str, endpoint: str, max_retries: int):
        self.ticket_model = build_ticket_model(config)
        self.system_prompt = build_system_prompt(config)
        self.fallback = config.fallback.id
        self.model = model
        self.endpoint = endpoint
        self.max_retries = max_retries

    @abstractmethod
    def complete(self, messages: Messages, schema: dict[str, Any]) -> str:
        """Send the chat with the schema as the output format; return the answer text."""

    def extract(self, text: str) -> Ticket:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": text},
        ]
        schema = self.ticket_model.model_json_schema()
        for attempt in range(1, self.max_retries + 2):
            content = self.complete(messages, schema)
            try:
                ticket = self.ticket_model.model_validate_json(content)
            except ValidationError as e:
                logger.warning("attempt %d: invalid ticket from %s: %s", attempt, self.model, e)
            else:
                ticket = keep_quoted_identifiers(ticket, text)
                return keep_fallback_alone(ticket, self.fallback)
        raise ExtractionError(f"{self.model} returned no valid ticket after {attempt} attempts")


class ChatClient(Protocol):
    def chat(self, **kwargs) -> ollama.ChatResponse: ...


class OllamaExtractor(Extractor):
    def __init__(
        self,
        config: DepartmentsConfig,
        settings: Settings,
        client: ChatClient | None = None,
        max_retries: int = 2,
    ) -> None:
        super().__init__(config, settings.ollama_model, settings.ollama_base_url, max_retries)
        # CPU-only inference can take minutes per request, hence the long timeout.
        self.client = client or ollama.Client(host=settings.ollama_base_url, timeout=600)

    def complete(self, messages: Messages, schema: dict[str, Any]) -> str:
        try:
            response = self.client.chat(
                model=self.model,
                messages=messages,
                format=schema,
                think=False,
                options={"temperature": 0},
            )
        except (ollama.ResponseError, ConnectionError) as e:
            raise BackendError(f"Ollama at {self.endpoint}: {e}") from e
        return response.message.content or ""


class OpenAIExtractor(Extractor):
    """OpenAI, or any OpenAI-compatible API (OpenRouter, vLLM, LM Studio, ...) via OPENAI_BASE_URL.

    Takes the `chat.completions.create` function rather than the client, so tests can pass a
    plain function instead of faking the SDK's nested client objects.
    """

    def __init__(
        self,
        config: DepartmentsConfig,
        settings: Settings,
        create: Callable[..., Any] | None = None,
        max_retries: int = 2,
    ) -> None:
        # Always pass an explicit URL and key: given None, the SDK falls back to the
        # OPENAI_* environment variables, which compose sets to "" when they are unset.
        base_url = settings.openai_base_url or "https://api.openai.com/v1"
        super().__init__(config, settings.openai_model, base_url, max_retries)
        if create is None:
            api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
            if not api_key:
                raise ValueError("LLM_BACKEND=openai needs OPENAI_API_KEY")
            client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=120)
            create = client.chat.completions.create
        self.create: Callable[..., Any] = create

    def complete(self, messages: Messages, schema: dict[str, Any]) -> str:
        try:
            response = self.create(
                model=self.model,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "ticket", "strict": True, "schema": schema},
                },
                temperature=0,
            )
        except openai.APIError as e:
            raise BackendError(f"{self.endpoint}: {e}") from e
        # A refusal comes with content None; an empty answer fails validation and is retried.
        return response.choices[0].message.content or ""


def build_extractor(config: DepartmentsConfig, settings: Settings) -> Extractor:
    match settings.llm_backend:
        case "ollama":
            return OllamaExtractor(config, settings)
        case "openai":
            return OpenAIExtractor(config, settings)
        case _:
            raise NotImplementedError(
                f"LLM backend {settings.llm_backend!r} is not implemented yet"
            )
