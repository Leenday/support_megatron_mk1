import json

import ollama
import pytest
from openai.types.chat import ChatCompletion

from megatron import __main__ as cli
from megatron.llm import (
    BackendError,
    ExtractionError,
    OllamaExtractor,
    OpenAIExtractor,
    build_extractor,
)
from megatron.prompt import build_system_prompt
from megatron.settings import Settings

TICKET = {
    "who": "Петрова",
    "where": "каб. 305",
    "when": "с утра",
    "what": "Принтер не печатает, замятие бумаги",
    "identifiers": [],
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


class FakeCreate:
    """Stands in for `openai.OpenAI().chat.completions.create`."""

    def __init__(self, *answers: str | None) -> None:
        self.answers = list(answers)
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> ChatCompletion:
        self.calls.append(kwargs)
        message = {"role": "assistant", "content": self.answers.pop(0)}
        return ChatCompletion.model_validate(
            {
                "id": "c1",
                "object": "chat.completion",
                "created": 0,
                "model": kwargs["model"],
                "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
            }
        )


def make_openai(departments, *answers: str | None) -> tuple[OpenAIExtractor, FakeCreate]:
    create = FakeCreate(*answers)
    settings = Settings(_env_file=None, openai_model="test-model")
    return OpenAIExtractor(departments, settings, create=create), create


def test_openai_sends_strict_schema(departments):
    extractor, create = make_openai(departments, json.dumps(TICKET))
    assert extractor.extract("С утра не печатает принтер").department == "hardware"
    response_format = create.calls[0]["response_format"]
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    assert schema["properties"]["department"]["enum"] == departments.ids
    assert extractor.endpoint == "https://api.openai.com/v1"


def test_openai_refusal_is_retried(departments):
    extractor, create = make_openai(departments, None, json.dumps(TICKET))
    assert extractor.extract("text").department == "hardware"
    assert len(create.calls) == 2


@pytest.mark.parametrize("key", [None, ""])
def test_openai_needs_a_key(departments, key):
    settings = Settings(_env_file=None, llm_backend="openai", openai_api_key=key)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build_extractor(departments, settings)


def test_openai_empty_base_url_means_openai(departments):
    settings = Settings(_env_file=None, openai_api_key="sk-test", openai_base_url="")
    assert OpenAIExtractor(departments, settings).endpoint == "https://api.openai.com/v1"


def test_build_extractor_picks_backend(departments):
    settings = Settings(_env_file=None, llm_backend="openai", openai_api_key="sk-test")
    assert isinstance(build_extractor(departments, settings), OpenAIExtractor)
    settings = Settings(_env_file=None, llm_backend="ollama")
    assert isinstance(build_extractor(departments, settings), OllamaExtractor)


class UnreachableClient:
    def chat(self, **kwargs) -> ollama.ChatResponse:
        raise ConnectionError("Failed to connect to Ollama")


def test_backend_error_stops_the_run(tmp_path, monkeypatch, capsys, departments, departments_path):
    extractor = OllamaExtractor(departments, Settings(_env_file=None), client=UnreachableClient())
    requests = tmp_path / "requests.txt"
    requests.write_text("one\ntwo\n", encoding="utf-8")
    assert run_cli(monkeypatch, departments_path, extractor, "--file", str(requests)) == 1
    out = capsys.readouterr().out
    assert "error: Ollama at" in out
    assert "> two" not in out
    with pytest.raises(BackendError):
        extractor.extract("text")


def write_jsonl(path, *rows: dict) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )


def test_cli_jsonl_reports_expected_departments(
    tmp_path, monkeypatch, capsys, departments, departments_path
):
    requests = tmp_path / "requests.jsonl"
    write_jsonl(
        requests,
        {"text": "принтер\nне печатает", "expected": "hardware"},
        {"text": "VPN", "expected": "network"},
    )
    extractor, _ = make(departments, json.dumps(TICKET), json.dumps(TICKET))
    output = tmp_path / "results.jsonl"
    argv = ["--file", str(requests), "-o", str(output)]
    assert run_cli(monkeypatch, departments_path, extractor, *argv) == 0
    out = capsys.readouterr().out
    assert "expected hardware ✓" in out
    assert "expected network ✗" in out
    assert "department correct: 1/2" in out
    first = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
    assert (first["request"], first["expected"]) == ("принтер\nне печатает", "hardware")


def test_cli_rejects_unknown_expected_department(
    tmp_path, monkeypatch, capsys, departments, departments_path
):
    requests = tmp_path / "requests.jsonl"
    requests.write_text('{"text": "x", "expected": "accounting"}\n', encoding="utf-8")
    extractor, client = make(departments)
    assert run_cli(monkeypatch, departments_path, extractor, "--file", str(requests)) == 2
    assert "accounting" in capsys.readouterr().err
    assert client.calls == []


def test_multi_line_jsonl_request_with_other_languages_and_no_load(
    tmp_path, monkeypatch, capsys, queues, queues_path
):
    """Done-when of #31: a dataset-style config (en/de, no load) and a multi-line request."""
    text = "Guten Tag,\n\ndie Rechnung INV-2041 wurde doppelt abgebucht.\n\nKonto: k.weber"
    requests = tmp_path / "requests.jsonl"
    write_jsonl(requests, {"id": 1, "text": text, "expected": "billing"})
    answer = {
        **TICKET,
        "who": "k.weber",
        "where": None,
        "when": None,
        "what": "Die Rechnung INV-2041 wurde doppelt abgebucht.",
        "identifiers": ["INV-2041", "k.weber"],
        "summary": "Doppelte Abbuchung",
        "tags": ["Rechnung", "Abbuchung"],
        "department": "billing",
        "language": "de",
    }
    extractor, client = make(queues, json.dumps(answer))
    output = tmp_path / "results.jsonl"
    argv = ["--file", str(requests), "-o", str(output)]
    assert run_cli(monkeypatch, queues_path, extractor, *argv) == 0
    assert client.calls[0]["messages"][1]["content"] == text
    assert "(en, de)" in client.calls[0]["messages"][0]["content"]
    ticket = json.loads(output.read_text(encoding="utf-8"))["ticket"]
    assert ticket["language"] == "de"
    assert ticket["identifiers"] == ["INV-2041", "k.weber"]
    assert "department correct: 1/1" in capsys.readouterr().out


def test_extract_keeps_only_quoted_identifiers(departments):
    answer = {**TICKET, "identifiers": ["a.smirnova", "ticket123"]}
    extractor, _ = make(departments, json.dumps(answer))
    assert extractor.extract("Не могу войти под логином a.smirnova").identifiers == ["a.smirnova"]
