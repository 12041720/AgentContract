"""Tests for constraint domain models, FrozenDict immutability, and invariants."""

from collections.abc import Mapping
from types import MappingProxyType
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
    RuleEffect,
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


# --- Round 2 Blocker 1 Regression Tests: FrozenDict True Immutability ---

def test_frozendict_item_assignment_prohibited():
    """FrozenDict does not support item assignment or item deletion."""
    fd = FrozenDict({"a": 1, "b": 2})
    assert isinstance(fd, Mapping)
    assert not isinstance(fd, dict)

    with pytest.raises(TypeError):
        fd["a"] = 10  # type: ignore[index]

    with pytest.raises(TypeError):
        fd["c"] = 3  # type: ignore[index]

    with pytest.raises(TypeError):
        del fd["a"]  # type: ignore[attr-defined]


def test_frozendict_in_place_union_prohibited():
    """FrozenDict does not support in-place union (|=)."""
    fd = FrozenDict({"a": 1})
    with pytest.raises(TypeError):
        fd |= {"b": 2}  # type: ignore[operator]


def test_frozendict_absence_and_inapplicability_of_mutable_dict_operations():
    """FrozenDict does not have mutable dict methods, and dict base-class methods cannot apply."""
    fd = FrozenDict({"a": 1, "b": 2})

    for mut_attr in ("pop", "update", "clear", "setdefault", "popitem"):
        assert not hasattr(fd, mut_attr)
        with pytest.raises(AttributeError):
            getattr(fd, mut_attr)()

    # Base-class dict methods cannot apply to FrozenDict
    with pytest.raises(TypeError):
        dict.__setitem__(fd, "c", 3)  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        dict.update(fd, {"c": 3})  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        dict.clear(fd)  # type: ignore[arg-type]


def test_frozendict_nested_mapping_and_list_freezing():
    """Nested mappings and lists are recursively converted to FrozenDict and tuples."""
    raw = {
        "level1": {
            "level2_list": [1, 2, {"level3_key": "val"}],
            "level2_set": {10, 20},
        }
    }
    fd = FrozenDict(raw)

    assert isinstance(fd["level1"], FrozenDict)
    assert isinstance(fd["level1"]["level2_list"], tuple)
    assert isinstance(fd["level1"]["level2_list"][2], FrozenDict)
    assert isinstance(fd["level1"]["level2_set"], frozenset)

    with pytest.raises(TypeError):
        fd["level1"]["level2_list"][2]["level3_key"] = "tampered"  # type: ignore[index]


def test_frozendict_external_input_mutation_isolation():
    """Mutating the external dict/list passed to FrozenDict does not mutate the FrozenDict."""
    raw_sub = {"count": 1}
    raw_list = [10, 20]
    raw = {"sub": raw_sub, "items": raw_list, "key": "orig"}

    fd = FrozenDict(raw)

    # In-place mutate the external inputs
    raw["key"] = "hacked"
    raw_sub["count"] = 999
    raw_list.append(30)

    # Verify FrozenDict was isolated
    assert fd["key"] == "orig"
    assert fd["sub"]["count"] == 1
    assert fd["items"] == (10, 20)


def test_frozendict_backing_store_is_immutable():
    """Round 3 Blocker 1 regression test: FrozenDict._data is an immutable MappingProxyType.

    Proves that direct attribute access to `_data` on a standalone FrozenDict or
    through a Constraint domain model cannot alter recorded contents.
    """
    fd = FrozenDict({"a": 1, "nested": {"sub": "orig"}})

    # 1. Backing store is MappingProxyType
    assert isinstance(fd._data, MappingProxyType)
    assert not isinstance(fd._data, dict)

    # 2. Direct attribute assignment to _data is prohibited
    with pytest.raises(TypeError):
        fd._data["a"] = 999  # type: ignore[index]

    with pytest.raises(TypeError):
        fd._data["new_key"] = "tampered"  # type: ignore[index]

    with pytest.raises(TypeError):
        del fd._data["a"]  # type: ignore[attr-defined]

    # 3. In-place union or dict base methods on _data are prohibited
    with pytest.raises(TypeError):
        fd._data |= {"b": 2}  # type: ignore[operator]

    with pytest.raises(TypeError):
        dict.__setitem__(fd._data, "a", 999)  # type: ignore[arg-type]

    # 4. Nested backing store is also MappingProxyType
    nested_fd = fd["nested"]
    assert isinstance(nested_fd, FrozenDict)
    assert isinstance(nested_fd._data, MappingProxyType)
    with pytest.raises(TypeError):
        nested_fd._data["sub"] = "tampered"  # type: ignore[index]

    # 5. Direct access through domain model (e.g. constraint.provenance.metadata._data)
    constraint = Constraint(
        id="c-backing-test",
        name="backing_test",
        description="Test backing store immutability",
        strength=ConstraintStrength.HARD,
        provenance=ConstraintProvenance(
            source=ConstraintSource.USER,
            metadata={"recorded_key": "recorded_val"},
        ),
    )
    assert isinstance(constraint.provenance.metadata._data, MappingProxyType)
    with pytest.raises(TypeError):
        constraint.provenance.metadata._data["tampered"] = True  # type: ignore[index]


def test_deep_immutability_of_constraint_models():
    """All nested collections in Constraint are structurally immutable."""
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

    # 2. Relation conflicts_with is a tuple
    assert isinstance(constraint.relations.conflicts_with, tuple)
    with pytest.raises(AttributeError):
        constraint.relations.conflicts_with.append("c-evil")  # type: ignore[attr-defined]

    # 3. Provenance metadata is an immutable FrozenDict
    assert isinstance(constraint.provenance.metadata, FrozenDict)
    with pytest.raises(TypeError):
        constraint.provenance.metadata["tamper"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        constraint.provenance.metadata |= {"tamper": True}  # type: ignore[operator]
    with pytest.raises(TypeError):
        dict.__setitem__(constraint.provenance.metadata, "tamper", True)  # type: ignore[arg-type]

    # 4. Nested dicts inside metadata are deeply frozen
    nested_dict = constraint.provenance.metadata["nested"]
    assert isinstance(nested_dict, FrozenDict)
    with pytest.raises(TypeError):
        nested_dict["new_key"] = "tampered"  # type: ignore[index]
    assert isinstance(nested_dict["sub_key"], tuple)
    with pytest.raises(AttributeError):
        nested_dict["sub_key"].append(999)  # type: ignore[attr-defined]

    # 5. Scope selectors are deeply frozen
    assert isinstance(constraint.scope.selectors, FrozenDict)
    with pytest.raises(TypeError):
        constraint.scope.selectors["branch"] = "hacked"  # type: ignore[index]
    assert isinstance(constraint.scope.selectors["tags"], FrozenDict)
    with pytest.raises(TypeError):
        constraint.scope.selectors["tags"]["env"] = "staging"  # type: ignore[index]

    # 6. Relation metadata is deeply frozen
    assert isinstance(constraint.relations.metadata, FrozenDict)
    with pytest.raises(TypeError):
        constraint.relations.metadata["rev_policy"] = "relaxed"  # type: ignore[index]


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


def test_require_and_prefer_constraints_require_compliance_scope():
    """BLOCKER 2 (ROUND 2): REQUIRE and PREFER constraints must reject compliance_scope=None."""
    provenance = ConstraintProvenance(
        source=ConstraintSource.USER,
        source_location="turn:2",
        source_text="Requires test coverage",
        author="reviewer",
    )

    # 1. REQUIRE with compliance_scope=None -> raises ConstraintValidationError
    with pytest.raises(ValidationError) as exc_info:
        Constraint(
            id="c-req-invalid",
            name="require_test_coverage",
            description="All code must have tests",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.REQUIRE,
            provenance=provenance,
            scope=ConstraintScope(paths=["src/"]),
            compliance_scope=None,
        )
    assert "requires a non-None compliance_scope" in str(exc_info.value)

    # 2. PREFER with compliance_scope=None -> raises ConstraintValidationError
    with pytest.raises(ValidationError) as exc_info:
        Constraint(
            id="c-pref-invalid",
            name="prefer_type_hints",
            description="Prefer typed Python",
            strength=ConstraintStrength.SOFT,
            rule_effect=RuleEffect.PREFER,
            provenance=provenance,
            scope=ConstraintScope(paths=["src/"]),
            compliance_scope=None,
        )
    assert "requires a non-None compliance_scope" in str(exc_info.value)

    # 3. DENY with compliance_scope=None -> valid (backward compatibility for all pre-TASK-003 constraints)
    deny_constraint = Constraint(
        id="c-deny-valid",
        name="deny_rm_rf",
        description="Do not run rm -rf",
        strength=ConstraintStrength.HARD,
        rule_effect=RuleEffect.DENY,
        provenance=provenance,
        scope=ConstraintScope(tools=["rm"]),
        compliance_scope=None,
    )
    assert deny_constraint.rule_effect == RuleEffect.DENY
    assert deny_constraint.compliance_scope is None


def test_require_and_prefer_serialization_round_trip():
    """REQUIRE and PREFER constraints serialize to JSON and deserialize identically."""
    provenance = ConstraintProvenance(
        source=ConstraintSource.USER,
        source_location="turn:3",
        source_text="Must run in sandbox",
        author="user",
    )
    require_c = Constraint(
        id="c-req-sandbox",
        name="require_sandbox",
        description="Writes must be in sandbox",
        strength=ConstraintStrength.HARD,
        rule_effect=RuleEffect.REQUIRE,
        provenance=provenance,
        scope=ConstraintScope(actions=["write"]),
        compliance_scope=ConstraintScope(paths=["sandbox/"]),
    )
    req_json = require_c.model_dump_json()
    req_rebuilt = Constraint.model_validate_json(req_json)
    assert req_rebuilt == require_c
    assert req_rebuilt.rule_effect == RuleEffect.REQUIRE
    assert req_rebuilt.compliance_scope is not None
    assert req_rebuilt.compliance_scope.paths == ("sandbox/",)

    prefer_c = Constraint(
        id="c-pref-black",
        name="prefer_black",
        description="Prefer black formatter",
        strength=ConstraintStrength.SOFT,
        rule_effect=RuleEffect.PREFER,
        provenance=provenance,
        scope=ConstraintScope(paths=["src/"]),
        compliance_scope=ConstraintScope(tools=["black"]),
    )
    pref_json = prefer_c.model_dump_json()
    pref_rebuilt = Constraint.model_validate_json(pref_json)
    assert pref_rebuilt == prefer_c
    assert pref_rebuilt.rule_effect == RuleEffect.PREFER
    assert pref_rebuilt.compliance_scope is not None
    assert pref_rebuilt.compliance_scope.tools == ("black",)
