import pytest

from megatron import __version__
from megatron.__main__ import main
from megatron.settings import Settings


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "gigachat")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
    settings = Settings(_env_file=None)
    assert settings.llm_backend == "gigachat"
    assert settings.ollama_base_url == "http://host.docker.internal:11434"


@pytest.mark.parametrize(
    ("backend", "model", "expected"),
    [
        (None, None, ("ollama", "qwen3:1.7b", "gpt-5.4-mini")),
        ("openai", None, ("openai", "qwen3:1.7b", "gpt-5.4-mini")),
        ("openai", "gpt-5.4-nano", ("openai", "qwen3:1.7b", "gpt-5.4-nano")),
        (None, "qwen3:4b", ("ollama", "qwen3:4b", "gpt-5.4-mini")),
    ],
)
def test_with_llm_replaces_backend_and_its_model(backend, model, expected):
    settings = Settings(_env_file=None).with_llm(backend, model)
    assert (settings.llm_backend, settings.ollama_model, settings.openai_model) == expected


def test_with_llm_rejects_a_model_for_an_unimplemented_backend():
    with pytest.raises(ValueError, match="not implemented"):
        Settings(_env_file=None, llm_backend="gigachat").with_llm(model="GigaChat-2")
