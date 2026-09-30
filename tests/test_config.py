"""Unit tests for configuration file loading and variable expansion."""

import os
from pathlib import Path
import pytest

from agentcontract.common.config import load_config, parse_config_content
from agentcontract.adapters.openai import OpenAICompatibleExtractionClient


def test_parse_config_basic_key_value() -> None:
    content = """
    # This is a comment
    KEY1=value1
    export KEY2="quoted value with spaces"
    KEY3 = 'single quoted'
    KEY4=
    """
    parsed = parse_config_content(content)
    assert parsed["KEY1"] == "value1"
    assert parsed["KEY2"] == "quoted value with spaces"
    assert parsed["KEY3"] == "single quoted"
    assert parsed["KEY4"] == ""


def test_parse_config_variable_expansion(monkeypatch) -> None:
    monkeypatch.setenv("BASE_DIR", "/opt/app")
    monkeypatch.setenv("SECRET_TOKEN", "secret123")

    content = """
    DIR_PATH=${BASE_DIR}/data
    TOKEN_VAL=$SECRET_TOKEN
    COMPOSED="$BASE_DIR/${SECRET_TOKEN}"
    """
    parsed = parse_config_content(content)
    assert parsed["DIR_PATH"] == "/opt/app/data"
    assert parsed["TOKEN_VAL"] == "secret123"
    assert parsed["COMPOSED"] == "/opt/app/secret123"


def test_parse_config_powershell_syntax(monkeypatch) -> None:
    monkeypatch.setenv("BUPT_API_KEY", "bupt-key-999")

    content = """
    $env:OPENAI_API_KEY = $env:BUPT_API_KEY
    $env:OPENAI_MODEL = "deepseek-v4-flash"
    $env:OPENAI_BASE_URL = "https://myai.bupt.edu.cn/llm-gw/v1"
    $env:OPENAI_RESPONSE_FORMAT = "json_object"
    $env:OPENAI_TIMEOUT = "240"
    """
    parsed = parse_config_content(content)
    assert parsed["OPENAI_API_KEY"] == "bupt-key-999"
    assert parsed["OPENAI_MODEL"] == "deepseek-v4-flash"
    assert parsed["OPENAI_BASE_URL"] == "https://myai.bupt.edu.cn/llm-gw/v1"
    assert parsed["OPENAI_RESPONSE_FORMAT"] == "json_object"
    assert parsed["OPENAI_TIMEOUT"] == "240"


def test_load_config_explicit_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TEST_CONF_KEY", raising=False)
    conf_file = tmp_path / "custom.env"
    conf_file.write_text("TEST_CONF_KEY=hello_world\n", encoding="utf-8")

    loaded = load_config(path=conf_file)
    assert loaded["TEST_CONF_KEY"] == "hello_world"
    assert os.environ.get("TEST_CONF_KEY") == "hello_world"


def test_load_config_override_behavior(tmp_path: Path, monkeypatch) -> None:
    conf_file = tmp_path / "custom.env"
    conf_file.write_text("TEST_OVERRIDE=from_file\n", encoding="utf-8")

    # 1. Without override, existing value is preserved
    monkeypatch.setenv("TEST_OVERRIDE", "from_env")
    loaded = load_config(path=conf_file, override=False)
    assert loaded["TEST_OVERRIDE"] == "from_file"
    assert os.environ["TEST_OVERRIDE"] == "from_env"

    # 2. With override=True, file value takes precedence
    loaded_override = load_config(path=conf_file, override=True)
    assert loaded_override["TEST_OVERRIDE"] == "from_file"
    assert os.environ["TEST_OVERRIDE"] == "from_file"


def test_load_config_missing_file_returns_empty() -> None:
    loaded = load_config(path="nonexistent_path_file.env")
    assert loaded == {}


def test_openai_client_picks_up_loaded_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    conf_file = tmp_path / ".agentcontract.env"
    conf_file.write_text(
        "OPENAI_MODEL=deepseek-custom\nOPENAI_API_KEY=sk-config-key\n",
        encoding="utf-8",
    )

    load_config(path=conf_file)

    client = OpenAICompatibleExtractionClient()
    assert client.model == "deepseek-custom"
    assert client._api_key == "sk-config-key"
