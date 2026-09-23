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
    FrozenDict,
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
    assert isinstance(constraint.scope.paths, tuple)


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


def test_deep_immutability_of_nested_collections():
    """Blocker 2 regression test: all nested collections must be structurally immutable."""
    constraint = Constraint(
        id="c-deep-immut",
        name="deep_immutable",
        description="Deep immutability test",
        strength=ConstraintStrength.HARD,
        provenance=ConstraintProvenance(
            source=ConstraintSource.USER,
            metadata={"priority": "high", "nested": {"sub_key": [1, 2, 3]}},
        ),
        scope=ConstraintScope(
            paths=["src/", "tests/"],
            tools=["edit", "run"],
            actions=["modify"],
            selectors={"branch": "main", "tags": {"env": "prod"}},
        ),
        relations=ConstraintRelation(
            conflicts_with=["c-other-1", "c-other-2"],
            metadata={"rev_policy": "strict"},
        ),
    )

    # 1. Scope sequence collections are tuples (no in-place append or mutation)
    assert isinstance(constraint.scope.paths, tuple)
    assert isinstance(constraint.scope.tools, tuple)
    assert isinstance(constraint.scope.actions, tuple)
    with pytest.raises(AttributeError):
        constraint.scope.paths.append("malicious.py")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        constraint.scope.tools.append("drop_db")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        constraint.scope.actions.append("delete")  # type: ignore[attr-defined]

    # 2. Relation conflicts_with is a tuple
    assert isinstance(constraint.relations.conflicts_with, tuple)
    with pytest.raises(AttributeError):
        constraint.relations.conflicts_with.append("c-evil")  # type: ignore[attr-defined]

    # 3. Provenance metadata is an immutable FrozenDict
    assert isinstance(constraint.provenance.metadata, FrozenDict)
    with pytest.raises(TypeError):
        constraint.provenance.metadata["tamper"] = True
    with pytest.raises(TypeError):
        constraint.provenance.metadata.pop("priority")
    with pytest.raises(TypeError):
        constraint.provenance.metadata.clear()
    with pytest.raises(TypeError):
        constraint.provenance.metadata.update({"tamper": True})

    # 4. Nested dicts and lists inside metadata are deeply frozen
    nested_dict = constraint.provenance.metadata["nested"]
    assert isinstance(nested_dict, FrozenDict)
    with pytest.raises(TypeError):
        nested_dict["new_key"] = "tampered"
    assert isinstance(nested_dict["sub_key"], tuple)
    with pytest.raises(AttributeError):
        nested_dict["sub_key"].append(999)  # type: ignore[attr-defined]

    # 5. Scope selectors are deeply frozen
    assert isinstance(constraint.scope.selectors, FrozenDict)
    with pytest.raises(TypeError):
        constraint.scope.selectors["branch"] = "hacked"
    assert isinstance(constraint.scope.selectors["tags"], FrozenDict)
    with pytest.raises(TypeError):
        constraint.scope.selectors["tags"]["env"] = "staging"

    # 6. Relation metadata is deeply frozen
    assert isinstance(constraint.relations.metadata, FrozenDict)
    with pytest.raises(TypeError):
        constraint.relations.metadata["rev_policy"] = "relaxed"


def test_external_reference_isolation():
    """Mutating external objects passed into models does not affect the models."""
    raw_paths = ["a.py", "b.py"]
    raw_meta = {"key": "original", "sub": {"count": 1}}

    c = Constraint(
        id="c-isol",
        name="isolation_check",
        description="Isolation check",
        strength=ConstraintStrength.SOFT,
        provenance=ConstraintProvenance(
            source=ConstraintSource.POLICY,
            metadata=raw_meta,
        ),
        scope=ConstraintScope(paths=raw_paths),
    )

    # Mutate the external inputs
    raw_paths.append("evil.py")
    raw_meta["key"] = "modified"
    raw_meta["sub"]["count"] = 999

    # Assert internal model data was untouched
    assert c.scope.paths == ("a.py", "b.py")
    assert c.provenance.metadata["key"] == "original"
    assert c.provenance.metadata["sub"]["count"] == 1


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
    assert reconstructed.relations.conflicts_with == ("c-other",)
    assert isinstance(reconstructed.scope.selectors, FrozenDict)
    assert isinstance(reconstructed.relations.conflicts_with, tuple)
