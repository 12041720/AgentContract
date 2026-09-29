"""Tests for AgentContract CLI and packaging entry points."""

import importlib
import importlib.metadata
import json
import pytest

import agentcontract
from agentcontract.cli import main


def test_cli_version(capsys) -> None:
    """agentcontract version prints version and returns 0."""
    ret = main(["version"])
    assert ret == 0
    captured = capsys.readouterr()
    assert f"AgentContract {agentcontract.__version__}" in captured.out


def test_cli_help(capsys) -> None:
    """agentcontract without arguments prints help and returns 0."""
    ret = main([])
    assert ret == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out.lower() or "commands" in captured.out.lower()


def test_cli_invalid_command(capsys) -> None:
    """agentcontract with unknown command exits with non-zero code."""
    with pytest.raises(SystemExit) as excinfo:
        main(["nonexistent_command_123"])
    assert excinfo.value.code != 0


def test_cli_offline_demo(capsys) -> None:
    """agentcontract demo runs deterministic offline demo and returns 0."""
    ret = main(["demo"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "AgentContract Quickstart: End-to-End Reliability Workflow" in captured.out
    assert "Violations Prevented: 1" in captured.out
    assert "Summary:" in captured.out


def test_cli_benchmark_text(capsys) -> None:
    """agentcontract benchmark prints formatted text report table."""
    ret = main(["benchmark", "--format", "text"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "AgentContract Reliability Benchmark Report" in captured.out
    assert "BASELINE" in captured.out
    assert "SPECGUARD" in captured.out
    assert "EVIDENCEGATE" in captured.out
    assert "FULL_AGENTCONTRACT" in captured.out


def test_cli_benchmark_markdown(capsys) -> None:
    """agentcontract benchmark --format markdown prints markdown table."""
    ret = main(["benchmark", "--format", "markdown"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "| `BASELINE` |" in captured.out
    assert "| `FULL_AGENTCONTRACT` |" in captured.out


def test_cli_benchmark_json(capsys) -> None:
    """agentcontract benchmark --format json prints valid JSON report."""
    ret = main(["benchmark", "--format", "json"])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "run_id" in data
    assert "metrics" in data
    assert "FULL_AGENTCONTRACT" in data["metrics"]


def test_package_root_imports() -> None:
    """All items declared in agentcontract.__all__ must be importable attributes."""
    for item in agentcontract.__all__:
        assert hasattr(agentcontract, item), f"Missing export: {item}"


def test_pyproject_console_entry_point() -> None:
    """Installed package exposes the agentcontract CLI console entry point."""
    entry_points = importlib.metadata.entry_points(group="console_scripts")
    ac_ep = [ep for ep in entry_points if ep.name == "agentcontract"]
    assert len(ac_ep) >= 1, "agentcontract console script not found in metadata"
    assert ac_ep[0].value == "agentcontract.cli:main"
