"""Tests for evidence domain models, enums, immutability, and serialization."""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from agentcontract.common.immutable import FrozenDict
from agentcontract.evidence.exceptions import (
    ClaimNotFoundError,
    EvidenceError,
    EvidenceValidationError,
)
from agentcontract.evidence.models import (
    Claim,
    ClaimEvaluation,
    ClaimType,
    ClaimVerdict,
    EvidenceRef,
    EvidenceRelation,
)
from agentcontract.trace.models import (
    ActorKind,
    EventKind,
    ToolCall,
    ToolResult,
    ToolResultStatus,
    TraceEvent,
    TracePointer,
)


def test_enum_values():
    """Verify enum variants for ClaimType, ClaimVerdict, and EvidenceRelation."""
    assert ClaimVerdict.VERIFIED == "VERIFIED"
    assert ClaimVerdict.CONTRADICTED == "CONTRADICTED"
    assert ClaimVerdict.UNVERIFIED == "UNVERIFIED"

    assert ClaimType.TOOL_SUCCEEDED == "TOOL_SUCCEEDED"
    assert ClaimType.COMMAND_EXITED_ZERO == "COMMAND_EXITED_ZERO"
    assert ClaimType.TESTS_PASSED == "TESTS_PASSED"
    assert ClaimType.FILE_EXISTS == "FILE_EXISTS"
    assert ClaimType.ACTION_COMPLETED == "ACTION_COMPLETED"
    assert ClaimType.GENERIC == "GENERIC"

    assert EvidenceRelation.SUPPORTS == "SUPPORTS"
    assert EvidenceRelation.CONTRADICTS == "CONTRADICTS"
    assert EvidenceRelation.NEUTRAL == "NEUTRAL"


def test_claim_validation_and_immutability():
    """Claim must enforce non-empty identifiers, timezone awareness, and immutability."""
    # Empty identifier rejected
    with pytest.raises(ValidationError):
        Claim(claim_id="  ", claim_type=ClaimType.TOOL_SUCCEEDED, description="valid description")

    # Empty description rejected
    with pytest.raises(ValidationError):
        Claim(claim_id="c-1", claim_type=ClaimType.TOOL_SUCCEEDED, description="   ")

    # Timezone-naive created_at rejected
    with pytest.raises(ValidationError):
        Claim(
            claim_id="c-1",
            claim_type=ClaimType.TOOL_SUCCEEDED,
            description="Tool succeeded",
            created_at=datetime(2026, 9, 24, 12, 0, 0),  # naive
        )

    # Valid claim is immutable
    claim = Claim(
        claim_id="c-1",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="Tool succeeded",
        metadata={"scope": "testing"},
    )
    assert isinstance(claim.metadata, FrozenDict)
    with pytest.raises(ValidationError):
        claim.description = "Changed"  # type: ignore


def test_evidence_ref_creation_and_properties():
    """EvidenceRef extracts pointers and properties correctly from TraceEvent."""
    ptr = TracePointer(trace_id="tr-1", event_id="evt-1", session_id="s-1")
    ref = EvidenceRef(
        trace_pointer=ptr,
        relation=EvidenceRelation.SUPPORTS,
        call_id="call-1",
        event_kind=EventKind.TOOL_RESULT,
        reason="Execution exited with 0",
        metadata={"custom": 123},
    )
    assert ref.trace_id == "tr-1"
    assert ref.event_id == "evt-1"
    assert ref.session_id == "s-1"
    assert ref.relation == EvidenceRelation.SUPPORTS
    assert isinstance(ref.metadata, FrozenDict)

    # Test from_event constructor
    tr = ToolResult(call_id="call-42", status=ToolResultStatus.SUCCESS, exit_code=0)
    event = TraceEvent(
        event_id="evt-res-1",
        trace_id="tr-10",
        sequence=1,
        actor=ActorKind.TOOL,
        event_kind=EventKind.TOOL_RESULT,
        payload=tr,
    )
    ref_from_evt = EvidenceRef.from_event(
        event,
        relation=EvidenceRelation.SUPPORTS,
        reason="Tool result matched",
    )
    assert ref_from_evt.trace_id == "tr-10"
    assert ref_from_evt.event_id == "evt-res-1"
    assert ref_from_evt.call_id == "call-42"
    assert ref_from_evt.relation == EvidenceRelation.SUPPORTS


def test_claim_evaluation_immutability_and_properties():
    """ClaimEvaluation must be frozen, reject unordered sets, and provide properties."""
    claim = Claim(
        claim_id="c-test",
        claim_type=ClaimType.TESTS_PASSED,
        description="All tests passed",
    )
    ptr = TracePointer(trace_id="tr-1", event_id="evt-1")
    ref = EvidenceRef(trace_pointer=ptr, relation=EvidenceRelation.SUPPORTS)

    eval_res = ClaimEvaluation(
        claim=claim,
        verdict=ClaimVerdict.VERIFIED,
        supporting_evidence=[ref],
        reason="Tests passed with exit 0",
    )
    assert eval_res.is_verified is True
    assert eval_res.is_contradicted is False
    assert eval_res.is_unverified is False
    assert eval_res.evidence_refs == (ref,)
    assert isinstance(eval_res.supporting_evidence, tuple)

    # Mutation prohibited
    with pytest.raises(ValidationError):
        eval_res.verdict = ClaimVerdict.CONTRADICTED  # type: ignore

    # Timezone-naive timestamp rejected
    with pytest.raises(ValidationError):
        ClaimEvaluation(
            claim=claim,
            verdict=ClaimVerdict.VERIFIED,
            reason="ok",
            evaluated_at=datetime(2026, 9, 24, 10, 0, 0),
        )

    # Deterministic sequence: sets and frozensets rejected
    with pytest.raises(ValidationError) as exc_info:
        ClaimEvaluation(
            claim=claim,
            verdict=ClaimVerdict.VERIFIED,
            supporting_evidence={ref},  # type: ignore
            reason="ok",
        )
    assert "ordered list or tuple" in str(exc_info.value)


def test_serialization_round_trip():
    """Claim, EvidenceRef, and ClaimEvaluation round-trip faithfully through JSON."""
    claim = Claim(
        claim_id="claim-serialize-1",
        claim_type=ClaimType.COMMAND_EXITED_ZERO,
        description="Build command succeeded",
        trace_id="tr-build",
        session_id="s-build",
        call_id="call-build-1",
        tool_name="bash",
        command="npm run build",
        target_path="dist/index.js",
        expected_exit_code=0,
        metadata={"author": "agent-1"},
    )
    claim_json = claim.model_dump_json()
    rebuilt_claim = Claim.model_validate_json(claim_json)
    assert rebuilt_claim == claim

    ref = EvidenceRef(
        trace_pointer=TracePointer(trace_id="tr-build", event_id="evt-build-res", session_id="s-build"),
        relation=EvidenceRelation.SUPPORTS,
        call_id="call-build-1",
        event_kind=EventKind.TOOL_RESULT,
        reason="Build exited 0",
        metadata={"duration_ms": 1250},
    )
    ref_json = ref.model_dump_json()
    rebuilt_ref = EvidenceRef.model_validate_json(ref_json)
    assert rebuilt_ref == ref

    evaluation = ClaimEvaluation(
        claim=claim,
        verdict=ClaimVerdict.VERIFIED,
        supporting_evidence=[ref],
        contradicting_evidence=[],
        reason="Claim is VERIFIED by trace evidence: Build exited 0",
    )
    eval_json = evaluation.model_dump_json()
    rebuilt_eval = ClaimEvaluation.model_validate_json(eval_json)
    assert rebuilt_eval == evaluation
    assert rebuilt_eval.is_verified is True


def test_top_level_package_exports_evidence():
    """Verify evidence symbols are exported from root agentcontract package."""
    from agentcontract import (
        Claim as RootClaim,
        ClaimEvaluation as RootClaimEvaluation,
        ClaimNotFoundError as RootClaimNotFoundError,
        ClaimType as RootClaimType,
        ClaimVerdict as RootClaimVerdict,
        EvidenceError as RootEvidenceError,
        EvidenceGate as RootEvidenceGate,
        EvidenceGraph as RootEvidenceGraph,
        EvidenceRef as RootEvidenceRef,
        EvidenceRelation as RootEvidenceRelation,
        EvidenceValidationError as RootEvidenceValidationError,
    )
    from agentcontract.evidence.gate import EvidenceGate
    from agentcontract.evidence.graph import EvidenceGraph

    assert RootClaim is Claim
    assert RootClaimEvaluation is ClaimEvaluation
    assert RootClaimNotFoundError is ClaimNotFoundError
    assert RootClaimType is ClaimType
    assert RootClaimVerdict is ClaimVerdict
    assert RootEvidenceError is EvidenceError
    assert RootEvidenceValidationError is EvidenceValidationError
    assert RootEvidenceRef is EvidenceRef
    assert RootEvidenceRelation is EvidenceRelation
    assert RootEvidenceGate is EvidenceGate
    assert RootEvidenceGraph is EvidenceGraph


def test_frozen_dict_hash_equality_contract():
    """Verify FrozenDict preserves Python equality/hash contract and raises TypeError for unhashable values."""
    from agentcontract.common.immutable import FrozenDict

    class UnhashableValue:
        def __init__(self, value: int) -> None:
            self.value = value

        def __eq__(self, other: object) -> bool:
            return isinstance(other, UnhashableValue) and self.value == other.value

    # Two distinct equal unhashable values
    val1 = UnhashableValue(42)
    val2 = UnhashableValue(42)
    assert val1 is not val2
    assert val1 == val2

    d1 = FrozenDict({"item": val1})
    d2 = FrozenDict({"item": val2})
    assert d1 == d2

    # Attempting to hash must raise TypeError rather than using hash(id(v)) fallback
    with pytest.raises(TypeError):
        hash(d1)
    with pytest.raises(TypeError):
        hash(d2)

    # For hashable values, equality strictly guarantees equal hash values
    d3 = FrozenDict({"a": 1, "b": "hello", "c": (1, 2)})
    d4 = FrozenDict({"b": "hello", "a": 1, "c": (1, 2)})
    assert d3 == d4
    assert hash(d3) == hash(d4)


