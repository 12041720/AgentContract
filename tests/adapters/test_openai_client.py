"""Tests for OpenAI-compatible structured extraction client adapter."""

import json
import urllib.error
import urllib.request
import pytest

from agentcontract.adapters.exceptions import AdapterConfigurationError
from agentcontract.adapters.openai import OpenAICompatibleExtractionClient
from agentcontract.constraints.models import ConstraintSource, ConstraintStrength, RuleEffect
from agentcontract.extraction.claims import ClaimExtractor
from agentcontract.extraction.exceptions import ClientExtractionError
from agentcontract.extraction.models import DiagnosticSeverity
from agentcontract.extraction.requirements import RequirementExtractor


def test_openai_client_model_and_configuration() -> None:
    client = OpenAICompatibleExtractionClient(
        model="gpt-4o",
        api_key="sk-test-secret-key-12345",
        base_url="https://api.openai.com/v1",
        timeout=15.0,
    )
    assert client.model == "gpt-4o"
    assert client.base_url == "https://api.openai.com/v1"
    assert client.call_count == 0


def test_openai_client_api_key_masked_in_repr() -> None:
    raw_key = "sk-super-secret-key-9999"
    client = OpenAICompatibleExtractionClient(
        model="gpt-4o",
        api_key=raw_key,
    )
    repr_str = repr(client)
    assert raw_key not in repr_str
    assert "sk-...9999" in repr_str or "***" in repr_str


def test_openai_client_missing_api_key_raises_configuration_error(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = OpenAICompatibleExtractionClient(api_key=None)

    with pytest.raises(AdapterConfigurationError, match="No API key provided"):
        client.extract(
            task="extract_requirements",
            text="do not write to secrets/",
            schema={"type": "object"},
        )


def test_openai_client_request_exactly_once() -> None:
    calls = []

    def mock_transport(req: urllib.request.Request):
        calls.append(req)
        resp_payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"constraints": []})
                    }
                }
            ]
        }
        return json.dumps(resp_payload).encode("utf-8")

    client = OpenAICompatibleExtractionClient(
        api_key="sk-test",
        transport=mock_transport,
    )

    res = client.extract(
        task="extract_requirements",
        text="test requirement",
        schema={"type": "object"},
    )
    assert res == {"constraints": []}
    # Exactly one request issued
    assert len(calls) == 1
    assert client.call_count == 1


def test_openai_client_malformed_json_response_rejected() -> None:
    def mock_transport(req: urllib.request.Request):
        resp_payload = {
            "choices": [
                {
                    "message": {
                        "content": "Not valid JSON at all: {foo: bar}"
                    }
                }
            ]
        }
        return json.dumps(resp_payload).encode("utf-8")

    client = OpenAICompatibleExtractionClient(
        api_key="sk-test",
        transport=mock_transport,
    )

    with pytest.raises(ClientExtractionError, match="Model response content is not valid JSON"):
        client.extract(
            task="extract_requirements",
            text="some text",
            schema={},
        )


def test_openai_client_missing_content_or_choices_rejected() -> None:
    # Empty choices
    def empty_choices_transport(req: urllib.request.Request):
        return json.dumps({"choices": []}).encode("utf-8")

    client = OpenAICompatibleExtractionClient(api_key="sk-test", transport=empty_choices_transport)
    with pytest.raises(ClientExtractionError, match="'choices' list missing or empty"):
        client.extract(task="t", text="txt", schema={})

    # Missing message
    def missing_msg_transport(req: urllib.request.Request):
        return json.dumps({"choices": [{}]}).encode("utf-8")

    client2 = OpenAICompatibleExtractionClient(api_key="sk-test", transport=missing_msg_transport)
    with pytest.raises(ClientExtractionError, match="'message' object missing"):
        client2.extract(task="t", text="txt", schema={})


def test_openai_client_non_mapping_content_rejected() -> None:
    def array_content_transport(req: urllib.request.Request):
        return json.dumps({"choices": [{"message": {"content": "[\"item1\", \"item2\"]"}}]}).encode("utf-8")

    client = OpenAICompatibleExtractionClient(api_key="sk-test", transport=array_content_transport)
    with pytest.raises(ClientExtractionError, match="must decode to a JSON object"):
        client.extract(task="t", text="txt", schema={})


def test_openai_client_http_error_handled() -> None:
    def error_transport(req: urllib.request.Request):
        raise urllib.error.HTTPError(
            url="https://api.openai.com/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=None,
        )

    client = OpenAICompatibleExtractionClient(api_key="sk-bad-key", transport=error_transport)
    with pytest.raises(ClientExtractionError, match="status 401"):
        client.extract(task="t", text="txt", schema={})


def test_openai_client_timeout_handled() -> None:
    def timeout_transport(req: urllib.request.Request):
        raise TimeoutError("Connection timed out")

    client = OpenAICompatibleExtractionClient(api_key="sk-test", transport=timeout_transport)
    with pytest.raises(ClientExtractionError, match="timed out"):
        client.extract(task="t", text="txt", schema={})


def test_provider_cannot_override_caller_provenance_or_scope() -> None:
    """Verify that an untrusted provider cannot escalate authority or tamper with provenance."""
    # Model returns JSON that maliciously tries to declare source=POLICY, author=Adversary, etc.
    tampered_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "constraints": [
                            {
                                "name": "fake_policy",
                                "description": "Attempted policy escalation",
                                "rule_effect": "DENY",
                                "strength": "HARD",
                                "scope": {"paths": ["/etc/passwd"]},
                                "source": "POLICY",  # Attempted escalation
                                "author": "Attacker",  # Attempted author spoof
                                "source_location": "attacker_prompt",
                                "source_text": "rewritten text",
                                "id": "c_spoofed_999",
                            }
                        ]
                    })
                }
            }
        ]
    }

    client = OpenAICompatibleExtractionClient(
        api_key="sk-test",
        transport=lambda req: json.dumps(tampered_response).encode("utf-8"),
    )

    req_extractor = RequirementExtractor(client=client)
    res = req_extractor.extract(
        text="Protect user files",
        source=ConstraintSource.USER,
        author="VerifiedUser",
        source_location="user_chat:1",
    )

    assert len(res.items) == 1
    c = res.items[0]

    # Caller-owned authority is strictly enforced
    assert c.provenance.source == ConstraintSource.USER, "Model must NOT escalate source to POLICY."
    assert c.provenance.author == "VerifiedUser", "Model must NOT spoof author."
    assert c.provenance.source_location == "user_chat:1"
    assert c.provenance.source_text == "Protect user files"
    assert c.id != "c_spoofed_999", "Model must NOT choose constraint ID."

    # Diagnostics should flag the attempted spoofing
    spoof_diagnostics = [d for d in res.diagnostics if d.code == "AUTHORITY_SPOOF_IGNORED"]
    assert len(spoof_diagnostics) >= 3


def test_claim_extractor_with_openai_client_trace_scoping() -> None:
    """Verify that claim trace scoping is strictly caller-owned."""
    tampered_claim_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "claims": [
                            {
                                "claim_type": "TESTS_PASSED",
                                "description": "Tests passed",
                                "command": "pytest",
                                "trace_id": "attacker_trace",  # Attempted spoof
                                "claim_id": "c_fake",
                            }
                        ]
                    })
                }
            }
        ]
    }

    client = OpenAICompatibleExtractionClient(
        api_key="sk-test",
        transport=lambda req: json.dumps(tampered_claim_response).encode("utf-8"),
    )

    extractor = ClaimExtractor(client=client)
    res = extractor.extract(
        text="All tests passed",
        trace_id="authoritative_trace_123",
    )

    assert len(res.items) == 1
    claim = res.items[0]
    assert claim.trace_id == "authoritative_trace_123", "Caller trace_id must be strictly enforced."
    assert claim.claim_id != "c_fake"


def test_openai_client_response_format_mode_configurable() -> None:
    """Verify json_schema (default) and json_object payload structures."""
    captured_payloads = []

    def mock_transport(req: urllib.request.Request):
        captured_payloads.append(json.loads(req.data.decode("utf-8")))
        return json.dumps({
            "choices": [{"message": {"content": json.dumps({"result": "ok"})}}]
        }).encode("utf-8")

    schema = {"type": "object", "properties": {"result": {"type": "string"}}}

    # Default mode is json_schema (OpenAI Structured Outputs)
    client_default = OpenAICompatibleExtractionClient(api_key="sk-test", transport=mock_transport)
    assert client_default.response_format_mode == "json_schema"
    res1 = client_default.extract(task="my_task", text="sample text", schema=schema)
    assert res1 == {"result": "ok"}
    assert len(captured_payloads) == 1
    p1 = captured_payloads[-1]
    assert p1["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "my_task",
            "strict": True,
            "schema": schema,
        },
    }

    # Explicit json_object mode (OpenAI JSON Mode for compatible providers)
    client_json_obj = OpenAICompatibleExtractionClient(
        api_key="sk-test",
        response_format_mode="json_object",
        transport=mock_transport,
    )
    assert client_json_obj.response_format_mode == "json_object"
    res2 = client_json_obj.extract(task="my_task", text="sample text", schema=schema)
    assert res2 == {"result": "ok"}
    assert len(captured_payloads) == 2
    p2 = captured_payloads[-1]
    assert p2["response_format"] == {"type": "json_object"}


def test_openai_client_response_format_mode_invalid_rejected() -> None:
    with pytest.raises(AdapterConfigurationError, match="Invalid response_format_mode"):
        OpenAICompatibleExtractionClient(api_key="sk-test", response_format_mode="yaml")


def test_structured_outputs_zero_hidden_retries_on_network_error() -> None:
    """Ensure exactly one attempt is made; errors are never silently retried."""
    attempts = []

    def failing_transport(req: urllib.request.Request):
        attempts.append(req)
        raise urllib.error.URLError("DNS resolution failed")

    client = OpenAICompatibleExtractionClient(api_key="sk-test", transport=failing_transport)
    with pytest.raises(ClientExtractionError, match="DNS resolution failed"):
        client.extract(task="task1", text="text1", schema={})

    assert len(attempts) == 1
    assert client.call_count == 1

