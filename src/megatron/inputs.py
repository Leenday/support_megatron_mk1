"""Request files for the CLI: plain text (one request per line) or JSON Lines.

JSON Lines carry multi-line requests and, for evaluation, the correct department:
{"id": 17, "text": "Не доставляется СМС...\\nПопытки отправки: ...", "expected": "delivery"}
Other keys are ignored, so a dataset export can be used as is if it has a `text` key.
"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Request(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = Field(min_length=1)
    id: str | int | None = None
    expected: str | None = Field(default=None, description="correct department id, if known")


class RequestFileError(ValueError):
    """A line of a request file is not a valid request."""


def load_requests(path: Path) -> list[Request]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if path.suffix != ".jsonl":
        return [Request(text=line.strip()) for line in lines if line.strip() and line[0] != "#"]
    requests = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            requests.append(Request.model_validate_json(line))
        except ValidationError as e:
            raise RequestFileError(f"{path}:{number}: {e}") from e
    return requests
