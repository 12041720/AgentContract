"""Tests for ClaimExtractor covering atomic claim parsing, scope enforcement, and EvidenceGate integration."""

import pytest

from agentcontract.evidence.gate import EvidenceGate
from agentcontract.evidence.models import ClaimType, ClaimVerdict
from agentcontract.extraction.client import FakeStructuredExtractionClient
from agentcontract.extraction.claims import ClaimExtractor
from agentcontract.extraction.exceptions import (
    ClientExtractionError,
    ExtractionValidationError,
)
from agentcontract.runtime.models import IdGenerator
from agentcontract.trace.models import (
    ActorKind,
    EventKind,
    TraceEvent,
    _freeze_trace_value,
)
from agentcontract.trace.store import TraceStore


def test_scenario_8_atomic_claim_decomposition_in_deterministic_order() -> None:
    """8. One completion sentence can produce multiple atomic typed claims in deterministic order."""
    text = "pytest passed and build.bin exists"

    client = FakeStructuredExtractionClient(
        {
            "claims": [
                {
                    "claim_type": "TESTS_PASSED",
                    "description": "Test suite executed with all tests passing",
                    "command": "pytest",
                    "expected_exit_code": 0,
                },
                {
                    "claim_type": "FILE_EXISTS",
                    "description": "Output binary build.bin was generated",
                    "target_path": "build.bin",
                },
            ]
        }
    )

    id_gen = IdGenerator(prefix="test_", deterministic=True)
    extractor = ClaimExtractor(client, id_generator=id_gen)

    result = extractor.extract(
        text,
        trace_id="tr-100",
        session_id="s-100",
    )

    assert client.call_count == 1
    assert result.is_success is True
    assert len(result.items) == 2

    # Claim 1: TESTS_PASSED
    c1 = result.items[0]
    assert c1.claim_id == "test_claim_0001"
    assert c1.claim_type == ClaimType.TESTS_PASSED
    assert c1.description == "Test suite executed with all tests passing"
    assert c1.command == "pytest"
    assert c1.expected_exit_code == 0
    assert c1.trace_id == "tr-100"
    assert c1.session_id == "s-100"

    # Claim 2: FILE_EXISTS
    c2 = result.items[1]
    assert c2.claim_id == "test_claim_0002"
    assert c2.claim_type == ClaimType.FILE_EXISTS
    assert c2.description == "Output binary build.bin was generated"
    assert c2.target_path == "build.bin"
    assert c2.trace_id == "tr-100"
    assert c2.session_id == "s-100"


def test_scenario_9_caller_trace_and_session_id_override_model_proposals() -> None:
    """9. Caller trace_id/session_id override any model-supplied scope."""
    client = FakeStructuredExtractionClient(
        {
            "claims": [
                {
                    "claim_type": "TOOL_SUCCEEDED",
                    "description": "Tool completed",
                    "tool_name": "linter",
                    "trace_id": "spoofed-trace-999",  # Model tries to set arbitrary trace_id!
                    "session_id": "spoofed-session-999",
                }
            ]
        }
    )

    extractor = ClaimExtractor(client)
    result = extractor.extract(
        "Linter finished",
        trace_id="authoritative-trace-1",
        session_id="authoritative-session-1",
    )

    assert result.is_success is True
    c = result.items[0]
    # Caller authority strictly enforced
    assert c.trace_id == "authoritative-trace-1"
    assert c.session_id == "authoritative-session-1"

    # Warning diagnostic recorded
    assert any("SCOPE_SPOOF_IGNORED" in (d.code or "") for d in result.diagnostics)


def test_scenario_10_generic_statement_remains_generic() -> None:
    """10. Subjective or unverifiable statements become GENERIC, never falsely promoted to verifiable types."""
    client = FakeStructuredExtractionClient(
        {
            "claims": [
                {
                    "claim_type": "GENERIC",
                    "description": "The architecture is clean and excellent",
                }
            ]
        }
    )

    extractor = ClaimExtractor(client)
    result = extractor.extract("The architecture is clean and excellent")
    assert len(result.items) == 1
    assert result.items[0].claim_type == ClaimType.GENERIC


def test_scenario_11_and_15_model_text_tests_passed_remains_unverified() -> None:
    """11 & 15. Model text 'tests passed' creates at most a TESTS_PASSED Claim;
    it is still UNVERIFIED before EvidenceGate evidence, and no AGENT_MESSAGE can verify it."""
    client = FakeStructuredExtractionClient(
        {
            "claims": [
                {
                    "claim_type": "TESTS_PASSED",
                    "description": "Unit tests passed",
                    "command": "pytest",
                    "expected_exit_code": 0,
                }
            ]
        }
    )

    extractor = ClaimExtractor(client)
    result = extractor.extract(
        "I ran the suite and all unit tests passed!",
        trace_id="tr-test-eval",
    )
    assert len(result.items) == 1
    claim = result.items[0]

    trace_store = TraceStore()
    gate = EvidenceGate()

    # 1. With empty store: Claim is UNVERIFIED
    eval1 = gate.evaluate(claim, trace_store)
    assert eval1.verdict == ClaimVerdict.UNVERIFIED

    # 2. Add an AGENT_MESSAGE event saying "I swear the tests passed!"
    trace_store.append(
        TraceEvent(
            event_id="evt-msg-1",
            trace_id="tr-test-eval",
            sequence=0,
            actor=ActorKind.AGENT,
            event_kind=EventKind.AGENT_MESSAGE,
            payload=_freeze_trace_value({"message": "I swear all unit tests passed!"}),
        )
    )

    # Agent's own prose is NEVER evidence -> MUST REMAIN UNVERIFIED!
    eval2 = gate.evaluate(claim, trace_store)
    assert eval2.verdict == ClaimVerdict.UNVERIFIED


def test_scenario_12_malformed_claim_type_rejected() -> None:
    """12. Malformed claim type -> extraction failure in strict mode."""
    client = FakeStructuredExtractionClient(
        {
            "claims": [
                {
                    "claim_type": "TOTALLY_ACCURATE_PROOF",  # Not a valid ClaimType enum!
                    "description": "Invalid claim type",
                }
            ]
        }
    )

    extractor = ClaimExtractor(client)
    with pytest.raises(ExtractionValidationError, match="Invalid claim type"):
        extractor.extract("Invalid text", strict=True)


def test_scenario_13_deterministic_claim_ids() -> None:
    """13. Deterministic claim IDs generated sequentially."""
    client = FakeStructuredExtractionClient(
        {
            "claims": [
                {"claim_type": "FILE_EXISTS", "description": "file1"},
                {"claim_type": "FILE_EXISTS", "description": "file2"},
                {"claim_type": "FILE_EXISTS", "description": "file3"},
            ]
        }
    )

    id_gen = IdGenerator(prefix="cid_", deterministic=True)
    extractor = ClaimExtractor(client, id_generator=id_gen)
    result = extractor.extract("Some text")

    assert [c.claim_id for c in result.items] == ["cid_claim_0001", "cid_claim_0002", "cid_claim_0003"]


def test_unknown_fields_and_verdict_rejected_extra_forbid() -> None:
    """Extra fields such as verdict='VERIFIED' or typos cannot be silently ignored."""
    client_verdict = FakeStructuredExtractionClient(
        {
            "claims": [
                {
                    "claim_type": "TESTS_PASSED",
                    "description": "Tests passed",
                    "verdict": "VERIFIED",  # Model claims verdict!
                }
            ]
        }
    )
    extractor = ClaimExtractor(client_verdict)

    # strict=True raises
    with pytest.raises(ExtractionValidationError, match="Extra inputs are not permitted"):
        extractor.extract("pytest passed", strict=True)

    # strict=False records ERROR diagnostic and skips
    res = extractor.extract("pytest passed", strict=False)
    assert res.has_errors is True
    assert len(res.items) == 0
    assert any("Extra inputs are not permitted" in d.message for d in res.diagnostics)


def test_independent_claim_extractor_instances_default_ids_do_not_collide() -> None:
    """Default ClaimExtractor instances use collision-resistant ID generators to avoid duplicate IDs."""
    data = {
        "claims": [
            {
                "claim_type": "FILE_EXISTS",
                "description": "File exists",
                "target_path": "output.txt",
            }
        ]
    }
    client1 = FakeStructuredExtractionClient(data)
    client2 = FakeStructuredExtractionClient(data)

    ext1 = ClaimExtractor(client1)
    ext2 = ClaimExtractor(client2)

    res1 = ext1.extract("Text 1")
    res2 = ext2.extract("Text 2")

    id1 = res1.items[0].claim_id
    id2 = res2.items[0].claim_id
    assert id1 != id2, f"Independent claim extractors must not produce colliding IDs: {id1} == {id2}"


def test_complete_claim_scope_and_identifier_spoof_diagnostics() -> None:
    """Model attempts to spoof claim_id, trace_id, session_id must not alter durable output
    and must emit SCOPE_SPOOF_IGNORED diagnostics."""
    client = FakeStructuredExtractionClient(
        {
            "claims": [
                {
                    "claim_type": "TOOL_SUCCEEDED",
                    "description": "Tool succeeded",
                    "tool_name": "bash",
                    "claim_id": "spoofed_claim_999",
                    "trace_id": "spoofed_trace_999",
                    "session_id": "spoofed_session_999",
                }
            ]
        }
    )

    id_gen = IdGenerator(prefix="claim_auth_", deterministic=True)
    extractor = ClaimExtractor(client, id_generator=id_gen)

    result = extractor.extract(
        "Bash completed",
        trace_id="real_trace_123",
        session_id="real_session_123",
        strict=True,
    )

    assert result.is_success is True
    assert len(result.items) == 1
    c = result.items[0]

    # Caller values strictly enforced
    assert c.claim_id == "claim_auth_claim_0001"
    assert c.claim_id != "spoofed_claim_999"
    assert c.trace_id == "real_trace_123"
    assert c.session_id == "real_session_123"

    # Check diagnostics
    spoof_diags = [d for d in result.diagnostics if d.code == "SCOPE_SPOOF_IGNORED"]
    fields_spoofed = {d.field for d in spoof_diags}
    assert "claims[0].claim_id" in fields_spoofed
    assert "claims[0].trace_id" in fields_spoofed
    assert "claims[0].session_id" in fields_spoofed


def test_client_safety_and_error_handling() -> None:
    # Blank text
    extractor = ClaimExtractor(FakeStructuredExtractionClient({}))
    with pytest.raises(ExtractionValidationError, match="cannot be empty or blank"):
        extractor.extract("   ")

    # Client returns non-mapping
    non_map_client = FakeStructuredExtractionClient(lambda req: "not_a_mapping")  # type: ignore[return-value]
    ext2 = ClaimExtractor(non_map_client)
    with pytest.raises(ClientExtractionError, match="expected a Mapping"):
        ext2.extract("Some text")

    # Missing claims list in strict mode
    empty_client = FakeStructuredExtractionClient({"other_field": 42})
    ext3 = ClaimExtractor(empty_client)
    with pytest.raises(ExtractionValidationError, match="does not contain 'claims'"):
        ext3.extract("Some text", strict=True)

