"""Tests for OpenAI-compatible structured extraction client adapter."""

import json
import urllib.error
import urllib.request
import pytest

from agentcontract.adapters.exceptions import AdapterConfigurationError
from agentcontract.adapters.openai import (
    OpenAICompatibleExtractionClient,
    get_openai_claim_extraction_schema,
    get_openai_requirement_extraction_schema,
    to_strict_json_schema,
    validate_strict_json_schema,
)
from agentcontract.constraints.models import ConstraintSource, ConstraintStrength, RuleEffect
from agentcontract.extraction.claims import ClaimExtractor
from agentcontract.extraction.exceptions import ClientExtractionError
from agentcontract.extraction.models import (
    DiagnosticSeverity,
    get_claim_extraction_schema,
    get_requirement_extraction_schema,
)
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
    expected_strict_schema = to_strict_json_schema(schema)
    assert p1["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "my_task",
            "strict": True,
            "schema": expected_strict_schema,
        },
    }
    validate_strict_json_schema(p1["response_format"]["json_schema"]["schema"])

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


def test_strict_json_schema_validator_rules() -> None:
    """validate_strict_json_schema must reject non-compliant schemas and accept valid strict schemas."""
    # Valid strict schema
    valid_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "count": {"type": "integer"},
        },
        "required": ["count", "title"],
    }
    validate_strict_json_schema(valid_schema)

    # Missing additionalProperties: False
    invalid_no_add_props = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    }
    with pytest.raises(AssertionError, match="additionalProperties: False"):
        validate_strict_json_schema(invalid_no_add_props)

    # Properties not equal to required keys
    invalid_missing_required = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "optional_field": {"type": ["string", "null"]},
        },
        "required": ["title"],
    }
    with pytest.raises(AssertionError, match="properties keys != required keys"):
        validate_strict_json_schema(invalid_missing_required)

    # Unrestricted object without properties
    invalid_unrestricted = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "meta": {"type": "object"},
        },
        "required": ["meta"],
    }
    with pytest.raises(AssertionError, match="unrestricted object"):
        validate_strict_json_schema(invalid_unrestricted)


def test_requirement_schema_strict_compatible() -> None:
    """The requirement extraction schema sent to OpenAI must be strict Structured Outputs compatible."""
    strict_schema = to_strict_json_schema(get_requirement_extraction_schema())
    validate_strict_json_schema(strict_schema)

    # Helper function produces identical validated schema
    direct_openai_schema = get_openai_requirement_extraction_schema()
    validate_strict_json_schema(direct_openai_schema)
    assert strict_schema == direct_openai_schema

    # Detailed structural checks:
    # 1. Root object
    assert strict_schema["type"] == "object"
    assert strict_schema["additionalProperties"] is False
    assert set(strict_schema["properties"].keys()) == set(strict_schema["required"])

    # 2. Constraints array items
    constraint_item = strict_schema["properties"]["constraints"]["items"]
    assert constraint_item["type"] == "object"
    assert constraint_item["additionalProperties"] is False
    assert set(constraint_item["properties"].keys()) == set(constraint_item["required"])

    # 3. Scope object
    scope = constraint_item["properties"]["scope"]
    assert scope["type"] == "object"
    assert scope["additionalProperties"] is False
    assert set(scope["properties"].keys()) == set(scope["required"])
    # selectors must NOT be exposed
    assert "selectors" not in scope["properties"]
    # optional target_type and description must be nullable
    assert "null" in scope["properties"]["target_type"]["type"]
    assert "null" in scope["properties"]["description"]["type"]

    # 4. Compliance scope object
    comp_scope = constraint_item["properties"]["compliance_scope"]
    assert "anyOf" in comp_scope
    anyof_types = [
        v.get("type") if isinstance(v, dict) else None for v in comp_scope["anyOf"]
    ]
    assert "null" in anyof_types
    inner_scope = [v for v in comp_scope["anyOf"] if v.get("type") == "object"][0]
    assert inner_scope["additionalProperties"] is False
    assert set(inner_scope["properties"].keys()) == set(inner_scope["required"])
    assert "selectors" not in inner_scope["properties"]


def test_claim_schema_strict_compatible() -> None:
    """The claim extraction schema sent to OpenAI must be strict Structured Outputs compatible."""
    strict_schema = to_strict_json_schema(get_claim_extraction_schema())
    validate_strict_json_schema(strict_schema)

    # Helper function produces identical validated schema
    direct_openai_schema = get_openai_claim_extraction_schema()
    validate_strict_json_schema(direct_openai_schema)
    assert strict_schema == direct_openai_schema

    # Detailed structural checks:
    # 1. Root object
    assert strict_schema["type"] == "object"
    assert strict_schema["additionalProperties"] is False
    assert set(strict_schema["properties"].keys()) == set(strict_schema["required"])

    # 2. Claim items
    claim_item = strict_schema["properties"]["claims"]["items"]
    assert claim_item["type"] == "object"
    assert claim_item["additionalProperties"] is False
    assert set(claim_item["properties"].keys()) == set(claim_item["required"])

    # metadata must NOT be exposed
    assert "metadata" not in claim_item["properties"]

    # All optional fields must be nullable and in required
    for opt_field in ["call_id", "tool_name", "command", "target_path", "expected_exit_code"]:
        assert opt_field in claim_item["properties"]
        assert opt_field in claim_item["required"]
        assert "null" in claim_item["properties"][opt_field]["type"]


def test_openai_client_captured_payload_has_strict_compatible_schema() -> None:
    """Verify that HTTP payloads actually captured over the wire contain strict-compatible schemas."""
    captured_requests = []

    def mock_transport(req: urllib.request.Request):
        captured_requests.append(req)
        # Return valid minimal mock responses
        body = json.loads(req.data.decode("utf-8"))
        task_name = body["response_format"]["json_schema"]["name"]
        if task_name == "extract_requirements":
            resp_content = {
                "constraints": [
                    {
                        "name": "safe_write",
                        "description": "Do not delete root",
                        "strength": "HARD",
                        "rule_effect": "DENY",
                        "scope": {
                            "target_type": None,
                            "paths": ["/root"],
                            "tools": [],
                            "actions": ["FILE_DELETE"],
                            "description": None,
                        },
                        "compliance_scope": None,
                    }
                ]
            }
        else:
            resp_content = {
                "claims": [
                    {
                        "claim_type": "TESTS_PASSED",
                        "description": "Tests passed",
                        "call_id": None,
                        "tool_name": None,
                        "command": "pytest",
                        "target_path": None,
                        "expected_exit_code": 0,
                    }
                ]
            }
        return json.dumps({
            "choices": [{"message": {"content": json.dumps(resp_content)}}]
        }).encode("utf-8")

    client = OpenAICompatibleExtractionClient(
        api_key="sk-test",
        transport=mock_transport,
    )

    # 1. Requirement extraction over wire
    req_extractor = RequirementExtractor(client=client)
    res_req = req_extractor.extract(
        text="Never delete /root",
        source=ConstraintSource.USER,
    )
    assert len(res_req.items) == 1
    assert client.call_count == 1
    assert len(captured_requests) == 1

    req_payload = json.loads(captured_requests[0].data.decode("utf-8"))
    assert req_payload["response_format"]["type"] == "json_schema"
    assert req_payload["response_format"]["json_schema"]["strict"] is True
    sent_req_schema = req_payload["response_format"]["json_schema"]["schema"]
    validate_strict_json_schema(sent_req_schema)

    # 2. Claim extraction over wire
    claim_extractor = ClaimExtractor(client=client)
    res_claim = claim_extractor.extract(
        text="All tests passed",
        trace_id="tr_wire_001",
    )
    assert len(res_claim.items) == 1
    assert client.call_count == 2
    assert len(captured_requests) == 2

    claim_payload = json.loads(captured_requests[1].data.decode("utf-8"))
    assert claim_payload["response_format"]["type"] == "json_schema"
    assert claim_payload["response_format"]["json_schema"]["strict"] is True
    sent_claim_schema = claim_payload["response_format"]["json_schema"]["schema"]
    validate_strict_json_schema(sent_claim_schema)


def test_openai_client_env_var_configuration(monkeypatch) -> None:
    """Client respects OPENAI_MODEL, OPENAI_BASE_URL, and OPENAI_RESPONSE_FORMAT env vars."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key-999")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://custom.openai.endpoint/v1")
    monkeypatch.setenv("OPENAI_RESPONSE_FORMAT", "json_object")

    client = OpenAICompatibleExtractionClient()
    assert client.model == "gpt-4o"
    assert client.base_url == "https://custom.openai.endpoint/v1"
    assert client.response_format_mode == "json_object"


