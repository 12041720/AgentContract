"""Tests for constraint domain models and invariants."""

import pytest
from pydantic import ValidationError

from agentcontract.constraints.exceptions import ConstraintValidationError
from agentcontract.constraints.models import (
    Constraint,
    ConstraintProvenance,
    ConstraintRelation,
    ConstraintScope,
    ConstraintSource,
    ConstraintStatus,
    ConstraintStrength,
)


def test_create_explicit_user_hard_constraint():
    """Scenario 1: Add explicit hard user constraint: 'do not modify DB schema'."""
    provenance = ConstraintProvenance(
        source=ConstraintSource.USER,
        source_location="turn:1",
        source_text="Do not modify the database schema under any circumstances.",
        author="user_primary",
    )
    scope = ConstraintScope(
        target_type="database",
        paths=["migrations/", "schema.sql"],
        actions=["write", "execute", "migrate"],
        description="Database migrations and schema definitions",
    )
    constraint = Constraint(
        id="c-no-schema-change",
        name="no_schema_modifications",
        description="Do not modify DB schema",
        strength=ConstraintStrength.HARD,
        provenance=provenance,
        scope=scope,
    )

    assert constraint.id == "c-no-schema-change"
    assert constraint.name == "no_schema_modifications"
    assert constraint.strength == ConstraintStrength.HARD
    assert constraint.status == ConstraintStatus.ACTIVE
    assert constraint.is_active is True
    assert constraint.is_hard is True
    assert constraint.is_assumption is False
    assert constraint.is_terminal is False
    assert constraint.source == ConstraintSource.USER
    assert constraint.provenance.source_text == "Do not modify the database schema under any circumstances."
    assert "schema.sql" in constraint.scope.paths


def test_agent_assumption_distinguishable_from_user_authority():
    """Scenario 2: Add agent assumption and demonstrate it remains distinguishable from user authority."""
    user_constraint = Constraint(
        id="c-user-req",
        name="use_port_8080",
        description="The service must listen on port 8080",
        strength=ConstraintStrength.HARD,
        provenance=ConstraintProvenance(
            source=ConstraintSource.USER,
            source_text="Bind server to port 8080",
        ),
    )

    agent_assumption = Constraint(
        id="c-agent-assump",
        name="assume_sqlite_db",
        description="Assume development database is SQLite based on local config",
        strength=ConstraintStrength.ASSUMPTION,
        provenance=ConstraintProvenance(
            source=ConstraintSource.AGENT_INFERENCE,
            source_text="sqlite3 string found in settings.py",
            author="code_agent_planner",
        ),
    )

    # Invariant 8: Inferences/assumptions must be clearly distinguishable from user hard constraints
    assert agent_assumption.source != user_constraint.source
    assert agent_assumption.strength != user_constraint.strength
    assert agent_assumption.is_hard is False
    assert agent_assumption.is_assumption is True
    assert user_constraint.is_hard is True
    assert user_constraint.is_assumption is False
    assert agent_assumption.source == ConstraintSource.AGENT_INFERENCE
    assert user_constraint.source == ConstraintSource.USER


def test_agent_inference_cannot_masquerade_as_hard_constraint():
    """Invariant 8: An AGENT_INFERENCE cannot be declared with HARD authority."""
    with pytest.raises(ValidationError) as exc_info:
        Constraint(
            id="c-illegal-agent-hard",
            name="agent_imposed_restriction",
            description="Agent claims user cannot edit README",
            strength=ConstraintStrength.HARD,
            provenance=ConstraintProvenance(
                source=ConstraintSource.AGENT_INFERENCE,
                source_text="Agent decided this restriction without user directive",
            ),
        )

    # Ensure the domain error or validation message explains the authority violation
    assert "AGENT_INFERENCE cannot be declared with HARD strength" in str(exc_info.value)


def test_empty_identifier_or_name_rejected():
    """Constraints must have non-empty stable IDs and names."""
    provenance = ConstraintProvenance(source=ConstraintSource.POLICY)

    with pytest.raises(ValidationError):
        Constraint(
            id="   ",
            name="valid_name",
            description="Description",
            strength=ConstraintStrength.SOFT,
            provenance=provenance,
        )

    with pytest.raises(ValidationError):
        Constraint(
            id="c-valid",
            name="",
            description="Description",
            strength=ConstraintStrength.SOFT,
            provenance=provenance,
        )


def test_constraint_immutability():
    """Constraint models are frozen; direct attribute mutation is prohibited."""
    constraint = Constraint(
        id="c-frozen",
        name="frozen_check",
        description="Check immutability",
        strength=ConstraintStrength.SOFT,
        provenance=ConstraintProvenance(source=ConstraintSource.POLICY),
    )

    with pytest.raises(ValidationError):
        constraint.status = ConstraintStatus.REVOKED  # type: ignore[misc]


def test_constraint_serialization_round_trip():
    """A constraint serializes to JSON and deserializes identically."""
    original = Constraint(
        id="c-serial-1",
        name="serialization_test",
        description="Round trip serialization test",
        strength=ConstraintStrength.HARD,
        status=ConstraintStatus.ACTIVE,
        provenance=ConstraintProvenance(
            source=ConstraintSource.REPOSITORY,
            source_location="pyproject.toml:L15",
            source_text="dependencies requirement",
            author="repo_policy",
            metadata={"rule_id": 42},
        ),
        scope=ConstraintScope(
            target_type="filesystem",
            paths=["src/"],
            tools=["edit_file"],
            actions=["write"],
            selectors={"env": "prod"},
            description="Production source files",
        ),
        relations=ConstraintRelation(
            conflicts_with=["c-other"],
            metadata={"tagged_by": "guard"},
        ),
    )

    json_str = original.model_dump_json()
    reconstructed = Constraint.model_validate_json(json_str)

    assert reconstructed == original
    assert reconstructed.id == original.id
    assert reconstructed.provenance.source == ConstraintSource.REPOSITORY
    assert reconstructed.scope.selectors == {"env": "prod"}
    assert reconstructed.relations.conflicts_with == ["c-other"]
