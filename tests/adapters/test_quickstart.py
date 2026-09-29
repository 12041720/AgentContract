"""Tests ensuring examples/quickstart.py executes cleanly and correctly."""

from examples.quickstart import run_quickstart


def test_quickstart_execution_returns_zero(monkeypatch) -> None:
    # Ensure OPENAI_API_KEY is not set so it runs offline deterministically
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    exit_code = run_quickstart()
    assert exit_code == 0
