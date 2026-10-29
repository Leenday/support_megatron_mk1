import json

import ollama
import pytest

from megatron import __main__ as cli
from megatron.llm import ExtractionError, OllamaExtractor
from megatron.prompt import build_system_prompt
from megatron.settings import Settings

TICKET = {
    "who": "Петрова",
    "where": "каб. 305",
    "when": "с утра",
    "what": "Принтер не печатает, замятие бумаги",
    "summary": "Замятие бумаги в принтере",
    "tags": ["принтер", "замятие"],
    "department": "hardware",
    "language": "ru",
}


class FakeClient:
    """Returns the given answers in order and records the calls."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.calls: list[dict] = []

    def chat(self, **kwargs) -> ollama.ChatResponse:
        self.calls.append(kwargs)
        content = self.answers.pop(0)
        return ollama.ChatResponse(message=ollama.Message(role="assistant", content=content))


def make(departments, *answers: str) -> tuple[OllamaExtractor, FakeClient]:
    client = FakeClient(*answers)
    settings = Settings(_env_file=None, ollama_model="test-model")
    return OllamaExtractor(departments, settings, client=client), client


def test_prompt_lists_departments_and_fallback(departments):
    prompt = build_system_prompt(departments)
    for d in departments.departments:
        assert f"- {d.id}: " in prompt
    assert 'Use "general"' in prompt


def test_extract_sends_schema_and_returns_ticket(departments):
    extractor, client = make(departments, json.dumps(TICKET))
    ticket = extractor.extract("С утра не печатает принтер")
    assert ticket.department == "hardware"
    call = client.calls[0]
    assert call["model"] == "test-model"
    assert call["think"] is False
    assert call["format"]["properties"]["department"]["enum"] == departments.ids


def test_invalid_answer_is_retried(departments):
    bad = json.dumps({**TICKET, "department": "accounting"})
    extractor, client = make(departments, bad, json.dumps(TICKET))
    assert extractor.extract("text").department == "hardware"
    assert len(client.calls) == 2


def test_gives_up_after_retries(departments):
    extractor, client = make(departments, "not json", "{}", "[]")
    with pytest.raises(ExtractionError):
        extractor.extract("text")
    assert len(client.calls) == 3


def test_cli_file_mode(tmp_path, monkeypatch, capsys, departments, departments_path):
    requests = tmp_path / "requests.txt"
    requests.write_text("# comment\nпринтер не печатает\n\nVPN drops\n", encoding="utf-8")
    extractor, _ = make(departments, json.dumps(TICKET), json.dumps(TICKET))
    monkeypatch.setattr(cli, "build_extractor", lambda config, settings: extractor)
    monkeypatch.setenv("DEPARTMENTS_PATH", str(departments_path))
    assert cli.main(["--file", str(requests)]) == 0
    out = capsys.readouterr().out
    assert "=== 2/2 ===" in out
    assert "> VPN drops" in out
    assert '"department": "hardware"' in out


def run_cli(monkeypatch, departments_path, extractor, *argv: str) -> int:
    monkeypatch.setattr(cli, "build_extractor", lambda config, settings: extractor)
    monkeypatch.setenv("DEPARTMENTS_PATH", str(departments_path))
    return cli.main(list(argv))


def test_cli_output_saves_ticket_json(tmp_path, monkeypatch, capsys, departments, departments_path):
    extractor, _ = make(departments, json.dumps(TICKET))
    output = tmp_path / "out" / "ticket.json"
    assert run_cli(monkeypatch, departments_path, extractor, "принтер", "-o", str(output)) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == TICKET
    assert '"department"' not in capsys.readouterr().out


def test_cli_output_file_mode_writes_json_lines(
    tmp_path, monkeypatch, departments, departments_path
):
    requests = tmp_path / "requests.txt"
    requests.write_text("принтер не печатает\nVPN drops\n", encoding="utf-8")
    extractor, _ = make(departments, json.dumps(TICKET), "bad", "bad", "bad")
    output = tmp_path / "results.jsonl"
    argv = ["--file", str(requests), "-o", str(output)]
    assert run_cli(monkeypatch, departments_path, extractor, *argv) == 1
    first, second = (json.loads(line) for line in output.read_text(encoding="utf-8").splitlines())
    assert first["request"] == "принтер не печатает"
    assert first["ticket"] == TICKET
    assert "seconds" in first
    assert second["request"] == "VPN drops"
    assert "error" in second


def test_cli_output_not_written_when_single_request_fails(
    tmp_path, monkeypatch, departments, departments_path
):
    extractor, _ = make(departments, "bad", "bad", "bad")
    output = tmp_path / "ticket.json"
    assert run_cli(monkeypatch, departments_path, extractor, "text", "-o", str(output)) == 1
    assert not output.exists()
