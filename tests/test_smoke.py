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
