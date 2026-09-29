"""Tests ensuring examples/quickstart.py executes cleanly and correctly."""

from examples.quickstart import run_quickstart


def test_quickstart_execution_returns_zero(monkeypatch) -> None:
    # Ensure OPENAI_API_KEY is not set so it runs offline deterministically
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    exit_code = run_quickstart()
    assert exit_code == 0


def test_quickstart_execution_with_custom_env_vars(monkeypatch) -> None:
    import json
    from agentcontract.adapters.openai import OpenAICompatibleExtractionClient

    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.mock-provider.com/v1")
    monkeypatch.setenv("OPENAI_RESPONSE_FORMAT", "json_schema")

    canned_req_resp = {
        "constraints": [
            {
                "name": "protect_production_keys",
                "description": "Never write to or delete sensitive key files in secrets/",
                "rule_effect": "DENY",
                "strength": "HARD",
                "scope": {
                    "paths": ["secrets/prod.key", "secrets/*"],
                    "actions": ["FILE_WRITE", "FILE_DELETE", "TOOL_CALL"],
                },
            }
        ]
    }
    canned_claim_resp = {
        "claims": [
            {
                "claim_type": "TESTS_PASSED",
                "description": "All test suites passed successfully with exit code 0.",
                "command": "pytest",
                "expected_exit_code": 0,
            },
            {
                "claim_type": "FILE_EXISTS",
                "description": "Production key file was generated at secrets/prod.key.",
                "target_path": "secrets/prod.key",
            },
        ]
    }
    responses = [canned_req_resp, canned_claim_resp]
    idx = [0]

    def mock_extract(self, *, task, text, schema, context=None):
        r = responses[idx[0]]
        idx[0] += 1
        return r

    monkeypatch.setattr(OpenAICompatibleExtractionClient, "extract", mock_extract)

    exit_code = run_quickstart()
    assert exit_code == 0

