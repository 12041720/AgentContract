"""Tests for candidate draft models, diagnostics, and extraction results."""

import json
import pytest

from agentcontract.common.immutable import FrozenDict
from agentcontract.constraints.models import (
    ConstraintProvenance,
    ConstraintSource,
    ConstraintStrength,
    RuleEffect,
)
from agentcontract.evidence.models import Claim, ClaimType
from agentcontract.extraction.exceptions import ExtractionValidationError
from agentcontract.extraction.models import (
    ClaimDraft,
    ConstraintDraft,
    ConstraintScopeDraft,
    DiagnosticSeverity,
    ExtractionDiagnostic,
    ExtractionResult,
    get_claim_extraction_schema,
    get_requirement_extraction_schema,
)


def test_constraint_scope_draft_normalization_and_validation() -> None:
    # 1. Normal list input
    draft = ConstraintScopeDraft(
        target_type="filesystem",
        paths=["/etc/hosts", "/etc/passwd"],
        tools=["bash"],
        actions=["write", "delete"],
        selectors={"mode": "strict"},
        description="Restricted system files",
    )
    assert draft.paths == ("/etc/hosts", "/etc/passwd")
    assert draft.tools == ("bash",)
    assert draft.actions == ("write", "delete")
    assert draft.selectors == FrozenDict({"mode": "strict"})

    scope = draft.to_scope()
    assert scope.paths == ("/etc/hosts", "/etc/passwd")
    assert scope.target_type == "filesystem"

    # 2. Reject unordered set
    with pytest.raises(ExtractionValidationError, match="ordered sequences"):
        ConstraintScopeDraft(paths={"/etc/hosts"})  # type: ignore[arg-type]

    # 3. Reject invalid selector type
    with pytest.raises(ExtractionValidationError, match="selectors must be a mapping"):
        ConstraintScopeDraft(selectors="not_a_map")  # type: ignore[arg-type]


def test_constraint_draft_enum_normalization_and_invariants() -> None:
    # 1. String normalization for strength and rule_effect
    draft = ConstraintDraft(
        name="no_rm",
        description="Never delete files",
        strength="hard",
        rule_effect="deny",
        scope=ConstraintScopeDraft(actions=["delete"]),
    )
    assert draft.strength == ConstraintStrength.HARD
    assert draft.rule_effect == RuleEffect.DENY

    prov = ConstraintProvenance(
        source=ConstraintSource.USER,
        source_text="Never delete files",
    )
    c = draft.to_constraint(constraint_id="c_0001", provenance=prov)
    assert c.id == "c_0001"
    assert c.name == "no_rm"
    assert c.strength == ConstraintStrength.HARD
    assert c.rule_effect == RuleEffect.DENY
    assert c.provenance.source == ConstraintSource.USER

    # 2. Invalid strength string raises ExtractionValidationError
    with pytest.raises(ExtractionValidationError, match="Invalid constraint strength"):
        ConstraintDraft(
            name="foo",
            description="bar",
            strength="ULTRA_HARD",  # type: ignore[arg-type]
        )

    # 3. Invalid rule effect string raises ExtractionValidationError
    with pytest.raises(ExtractionValidationError, match="Invalid rule effect"):
        ConstraintDraft(
            name="foo",
            description="bar",
            rule_effect="FORBIDDEN",  # type: ignore[arg-type]
        )

    # 4. Invariant: AGENT_INFERENCE cannot be HARD
    inf_prov = ConstraintProvenance(
        source=ConstraintSource.AGENT_INFERENCE,
        source_text="Inferring rule",
    )
    hard_draft = ConstraintDraft(
        name="inferred_hard",
        description="Inferred rule",
        strength=ConstraintStrength.HARD,
    )
    with pytest.raises(ExtractionValidationError, match="AGENT_INFERENCE cannot be declared with HARD"):
        hard_draft.to_constraint(constraint_id="c_inf", provenance=inf_prov)

    # 5. Invariant: REQUIRE requires compliance_scope
    require_draft = ConstraintDraft(
        name="require_schema",
        description="Require schema validation",
        rule_effect=RuleEffect.REQUIRE,
        compliance_scope=None,
    )
    with pytest.raises(ExtractionValidationError, match="requires a compliance_scope"):
        require_draft.to_constraint(constraint_id="c_req", provenance=prov)


def test_claim_draft_validation_and_conversion() -> None:
    # 1. Normal claim draft
    draft = ClaimDraft(
        claim_type="command_exited_zero",
        description="pytest completed successfully",
        command="pytest -v",
        expected_exit_code=0,
    )
    assert draft.claim_type == ClaimType.COMMAND_EXITED_ZERO

    claim = draft.to_claim(
        claim_id="claim_0001",
        trace_id="tr-100",
        session_id="s-200",
    )
    assert claim.claim_id == "claim_0001"
    assert claim.claim_type == ClaimType.COMMAND_EXITED_ZERO
    assert claim.description == "pytest completed successfully"
    assert claim.trace_id == "tr-100"
    assert claim.session_id == "s-200"
    assert claim.command == "pytest -v"
    assert claim.expected_exit_code == 0

    # 2. Invalid claim_type string raises ExtractionValidationError
    with pytest.raises(ExtractionValidationError, match="Invalid claim type"):
        ClaimDraft(
            claim_type="TOTALLY_PASSED",  # type: ignore[arg-type]
            description="something",
        )

    # 3. Blank description raises ExtractionValidationError
    with pytest.raises(ExtractionValidationError, match="description must not be empty"):
        ClaimDraft(
            claim_type=ClaimType.GENERIC,
            description="   ",
        )


def test_extraction_result_container_methods_and_serialization() -> None:
    diag_warn = ExtractionDiagnostic(
        message="Proposed source ignored",
        severity=DiagnosticSeverity.WARNING,
        field="source",
    )
    diag_err = ExtractionDiagnostic(
        message="Missing compliance scope",
        severity=DiagnosticSeverity.ERROR,
        field="compliance_scope",
    )

    claim = Claim(
        claim_id="cl-1",
        claim_type=ClaimType.TESTS_PASSED,
        description="tests passed",
    )

    result_with_errors = ExtractionResult[Claim](
        items=(claim,),
        diagnostics=(diag_err,),
        raw_response=FrozenDict({"foo": "bar"}),
    )
    assert result_with_errors.has_errors is True
    assert result_with_errors.is_success is False
    assert len(result_with_errors) == 1
    assert result_with_errors[0] == claim
    assert list(result_with_errors) == [claim]

    result_clean = ExtractionResult[Claim](
        items=(claim,),
        diagnostics=(diag_warn,),
        raw_response=FrozenDict({"foo": "bar"}),
    )
    assert result_clean.has_errors is False
    assert result_clean.has_warnings is True
    assert result_clean.is_success is True

    # JSON round-trip
    dumped = result_clean.model_dump(mode="json")
    assert len(dumped["items"]) == 1
    assert dumped["items"][0]["claim_type"] == "TESTS_PASSED"
    assert dumped["diagnostics"][0]["severity"] == "WARNING"
    assert dumped["raw_response"] == {"foo": "bar"}

    json_str = result_clean.model_dump_json()
    parsed = json.loads(json_str)
    assert parsed["items"][0]["claim_id"] == "cl-1"


def test_schema_helpers_structure() -> None:
    req_schema = get_requirement_extraction_schema()
    assert req_schema["type"] == "object"
    assert "constraints" in req_schema["properties"]

    claim_schema = get_claim_extraction_schema()
    assert claim_schema["type"] == "object"
    assert "claims" in claim_schema["properties"]


def test_top_level_package_exports_extraction() -> None:
    from agentcontract import (
        ClaimDraft as RootClaimDraft,
        ClaimExtractor as RootClaimExtractor,
        ClientExtractionError as RootClientExtractionError,
        ConstraintDraft as RootConstraintDraft,
        ConstraintScopeDraft as RootConstraintScopeDraft,
        DiagnosticSeverity as RootDiagnosticSeverity,
        ExtractionDiagnostic as RootExtractionDiagnostic,
        ExtractionError as RootExtractionError,
        ExtractionRequest as RootExtractionRequest,
        ExtractionResult as RootExtractionResult,
        ExtractionValidationError as RootExtractionValidationError,
        FakeStructuredExtractionClient as RootFakeStructuredExtractionClient,
        RequirementExtractor as RootRequirementExtractor,
        StructuredExtractionClient as RootStructuredExtractionClient,
        extract_and_verify_claims as root_extract_and_verify_claims,
        get_claim_extraction_schema as root_get_claim_extraction_schema,
        get_requirement_extraction_schema as root_get_requirement_extraction_schema,
    )

    assert RootStructuredExtractionClient is not None
    assert RootRequirementExtractor is not None
    assert RootClaimExtractor is not None
    assert RootConstraintDraft is not None
    assert RootClaimDraft is not None

