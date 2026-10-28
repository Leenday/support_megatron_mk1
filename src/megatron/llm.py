"""LLM adapters: request text -> validated Ticket.

Every adapter sends the ticket's JSON schema to the model (structured outputs), so the
answer is constrained to the schema and the department enum; Pydantic validates it again
and the request is retried if validation still fails.
"""

import logging
from typing import Protocol

import ollama
from pydantic import ValidationError

from megatron.departments import DepartmentsConfig
from megatron.prompt import build_system_prompt
from megatron.settings import Settings
from megatron.ticket import Ticket, build_ticket_model

logger = logging.getLogger(__name__)


class ExtractionError(RuntimeError):
    """The model did not return a valid ticket after all attempts."""


class ChatClient(Protocol):
    def chat(self, **kwargs) -> ollama.ChatResponse: ...


class OllamaExtractor:
    def __init__(
        self,
        config: DepartmentsConfig,
        settings: Settings,
        client: ChatClient | None = None,
        max_retries: int = 2,
    ) -> None:
        self.ticket_model = build_ticket_model(config)
        self.system_prompt = build_system_prompt(config)
        self.model = settings.ollama_model
        self.max_retries = max_retries
        # CPU-only inference can take minutes per request, hence the long timeout.
        self.client = client or ollama.Client(host=settings.ollama_base_url, timeout=600)

    def extract(self, text: str) -> Ticket:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": text},
        ]
        for attempt in range(1, self.max_retries + 2):
            response = self.client.chat(
                model=self.model,
                messages=messages,
                format=self.ticket_model.model_json_schema(),
                think=False,
                options={"temperature": 0},
            )
            content = response.message.content or ""
            try:
                return self.ticket_model.model_validate_json(content)
            except ValidationError as e:
                logger.warning("attempt %d: invalid ticket from %s: %s", attempt, self.model, e)
        raise ExtractionError(f"{self.model} returned no valid ticket after {attempt} attempts")


def build_extractor(config: DepartmentsConfig, settings: Settings) -> OllamaExtractor:
    if settings.llm_backend != "ollama":
        raise NotImplementedError(f"LLM backend {settings.llm_backend!r} is not implemented yet")
    return OllamaExtractor(config, settings)
