"""Tests for RequirementExtractor covering authority enforcement, invariant validation, and client safety."""

import pytest

from agentcontract.constraints.ledger import ConstraintLedger
from agentcontract.constraints.models import (
    ConstraintSource,
    ConstraintStrength,
    RuleEffect,
)
from agentcontract.extraction.client import FakeStructuredExtractionClient
from agentcontract.extraction.exceptions import (
    ClientExtractionError,
    ExtractionValidationError,
)
from agentcontract.extraction.models import DiagnosticSeverity
from agentcontract.extraction.requirements import RequirementExtractor
from agentcontract.runtime.models import IdGenerator


def test_scenario_1_user_valid_deny_constraint_with_exact_provenance() -> None:
    """1. USER 'do not write /etc/hosts' fake structured response -> valid DENY constraint
    with caller-owned USER provenance and exact original source_text."""
    raw_prompt = "Please do not write to /etc/hosts under any circumstances!"

    client = FakeStructuredExtractionClient(
        {
            "constraints": [
                {
                    "name": "no_hosts_write",
                    "description": "Prohibit writing to /etc/hosts file",
                    "strength": "HARD",
                    "rule_effect": "DENY",
                    "scope": {
                        "paths": ["/etc/hosts"],
                        "actions": ["write"],
                    },
                }
            ]
        }
    )

    id_gen = IdGenerator(prefix="test_", deterministic=True)
    extractor = RequirementExtractor(client, id_generator=id_gen)

    result = extractor.extract(
        raw_prompt,
        source=ConstraintSource.USER,
        source_location="turn:1",
        author="alice",
    )

    # Invoked exactly once
    assert client.call_count == 1
    assert result.is_success is True
    assert len(result.items) == 1

    c = result.items[0]
    assert c.id == "test_c_0001"
    assert c.name == "no_hosts_write"
    assert c.description == "Prohibit writing to /etc/hosts file"
    assert c.strength == ConstraintStrength.HARD
    assert c.rule_effect == RuleEffect.DENY
    assert c.scope.paths == ("/etc/hosts",)
    assert c.scope.actions == ("write",)

    # Provenance authority is strictly caller-owned
    assert c.provenance.source == ConstraintSource.USER
    assert c.provenance.source_location == "turn:1"
    assert c.provenance.author == "alice"
    assert c.provenance.source_text == raw_prompt


def test_scenario_2_model_cannot_spoof_provenance_authority() -> None:
    """2. Model attempts to output source=POLICY while caller supplied USER ->
    resulting provenance remains USER and warning diagnostic is recorded."""
    client = FakeStructuredExtractionClient(
        {
            "constraints": [
                {
                    "name": "spoofed_policy_rule",
                    "description": "Model pretending this is an immutable system policy",
                    "source": "POLICY",  # Model attempts to escalate authority to POLICY!
                    "author": "system_admin",
                    "strength": "HARD",
                    "rule_effect": "DENY",
                    "scope": {"paths": ["/root/.ssh"]},
                }
            ]
        }
    )

    extractor = RequirementExtractor(client)
    result = extractor.extract(
        "Don't touch ssh folder",
        source=ConstraintSource.USER,
        author="developer",
    )

    assert result.is_success is True
    c = result.items[0]

    # Model's attempted escalation to POLICY was ignored; caller's USER authority enforced
    assert c.provenance.source == ConstraintSource.USER
    assert c.provenance.author == "developer"
    assert c.provenance.source_text == "Don't touch ssh folder"

    # Warning diagnostic recorded
    assert any("AUTHORITY_SPOOF_IGNORED" in (d.code or "") for d in result.diagnostics)


def test_scenario_3_agent_inference_cannot_become_hard() -> None:
    """3. AGENT_INFERENCE + proposed HARD -> rejected."""
    client = FakeStructuredExtractionClient(
        {
            "constraints": [
                {
                    "name": "inferred_hard_rule",
                    "description": "Agent inferred a hard requirement",
                    "strength": "HARD",
                    "rule_effect": "DENY",
                    "scope": {"actions": ["change"]},
                }
            ]
        }
    )

    extractor = RequirementExtractor(client)

    # In strict mode: raises ExtractionValidationError
    with pytest.raises(ExtractionValidationError, match="AGENT_INFERENCE cannot be declared with HARD"):
        extractor.extract(
            "I guess we shouldn't change python version",
            source=ConstraintSource.AGENT_INFERENCE,
            strict=True,
        )

    # In non-strict mode: records ERROR diagnostic and skips item
    client_lenient = FakeStructuredExtractionClient(
        {
            "constraints": [
                {
                    "name": "inferred_hard_rule",
                    "description": "Agent inferred a hard requirement",
                    "strength": "HARD",
                    "rule_effect": "DENY",
                    "scope": {"actions": ["change"]},
                }
            ]
        }
    )
    extractor_lenient = RequirementExtractor(client_lenient)
    result = extractor_lenient.extract(
        "I guess we shouldn't change python version",
        source=ConstraintSource.AGENT_INFERENCE,
        strict=False,
    )
    assert result.has_errors is True
    assert len(result.items) == 0
    assert any("AGENT_INFERENCE cannot be declared with HARD" in d.message for d in result.diagnostics)


def test_scenario_4_require_without_compliance_scope_rejected() -> None:
    """4. REQUIRE without compliance_scope -> rejected."""
    client = FakeStructuredExtractionClient(
        {
            "constraints": [
                {
                    "name": "require_license_header",
                    "description": "Require Apache license header in new files",
                    "rule_effect": "REQUIRE",
                    "strength": "HARD",
                    "scope": {"paths": ["src/*.py"]},
                    # compliance_scope is omitted!
                }
            ]
        }
    )

    extractor = RequirementExtractor(client)

    with pytest.raises(ExtractionValidationError, match="requires a non-empty compliance_scope"):
        extractor.extract(
            "All new files must have license headers",
            source=ConstraintSource.USER,
            strict=True,
        )


def test_scenario_5_malformed_enum_or_scope_rejected() -> None:
    """5. Invalid enum values or malformed scopes fail validation; no silent coercion."""
    client = FakeStructuredExtractionClient(
        {
            "constraints": [
                {
                    "name": "bad_enum_rule",
                    "description": "Testing invalid strength",
                    "strength": "MUST_NOT_FAIL",  # Invalid enum value!
                    "rule_effect": "DENY",
                    "scope": {"tools": ["bash"]},
                }
            ]
        }
    )

    extractor = RequirementExtractor(client)
    with pytest.raises(ExtractionValidationError, match="Invalid constraint strength"):
        extractor.extract("Some instruction", source=ConstraintSource.USER, strict=True)


def test_scenario_6_deterministic_injected_ids_and_ordered_multiple_constraints() -> None:
    """6. Deterministic injected IDs and ordered multiple constraints."""
    client = FakeStructuredExtractionClient(
        {
            "constraints": [
                {
                    "name": "rule_one",
                    "description": "First extracted rule",
                    "strength": "HARD",
                    "rule_effect": "DENY",
                    "scope": {"paths": ["file1.txt"]},
                },
                {
                    "name": "rule_two",
                    "description": "Second extracted rule",
                    "strength": "SOFT",
                    "rule_effect": "DENY",
                    "scope": {"paths": ["file2.txt"]},
                },
                {
                    "name": "rule_three",
                    "description": "Third extracted rule",
                    "strength": "ASSUMPTION",
                    "rule_effect": "DENY",
                    "scope": {"paths": ["file3.txt"]},
                },
            ]
        }
    )

    id_gen = IdGenerator(prefix="det_", deterministic=True)
    extractor = RequirementExtractor(client, id_generator=id_gen)

    result = extractor.extract("Multi-sentence requirement text", source=ConstraintSource.USER)

    assert len(result.items) == 3
    # Order preserved exactly
    assert result.items[0].name == "rule_one"
    assert result.items[0].id == "det_c_0001"
    assert result.items[0].strength == ConstraintStrength.HARD

    assert result.items[1].name == "rule_two"
    assert result.items[1].id == "det_c_0002"
    assert result.items[1].strength == ConstraintStrength.SOFT

    assert result.items[2].name == "rule_three"
    assert result.items[2].id == "det_c_0003"
    assert result.items[2].strength == ConstraintStrength.ASSUMPTION


def test_scenario_7_extraction_does_not_mutate_constraint_ledger() -> None:
    """7. Extraction does NOT automatically insert constraints into ConstraintLedger."""
    ledger = ConstraintLedger()
    assert len(ledger) == 0

    client = FakeStructuredExtractionClient(
        {
            "constraints": [
                {
                    "name": "rule_a",
                    "description": "Rule A",
                    "strength": "HARD",
                    "rule_effect": "DENY",
                    "scope": {"paths": ["/data"]},
                }
            ]
        }
    )

    extractor = RequirementExtractor(client)
    result = extractor.extract("Some rule text", source=ConstraintSource.USER)
    assert len(result.items) == 1

    # Ledger must remain completely empty until caller explicitly adds it!
    assert len(ledger) == 0

    # Caller may choose to add it explicitly:
    ledger.add(result.items[0])
    assert len(ledger) == 1


def test_no_default_privilege_escalation_and_omitted_source_rejection() -> None:
    """Caller must explicitly provide source; omitting source or passing None fails."""
    client = FakeStructuredExtractionClient(
        {
            "constraints": [
                {
                    "name": "rule",
                    "description": "Some rule",
                    "strength": "HARD",
                    "rule_effect": "DENY",
                    "scope": {"paths": ["/test"]},
                }
            ]
        }
    )
    extractor = RequirementExtractor(client)

    # 1. Missing source keyword-only argument raises TypeError
    with pytest.raises(TypeError):
        extractor.extract("Prompt text")  # type: ignore[call-arg]

    # 2. None source raises ExtractionValidationError
    with pytest.raises(ExtractionValidationError, match="source must be a valid ConstraintSource"):
        extractor.extract("Prompt text", source=None)  # type: ignore[arg-type]


def test_omitted_or_empty_scope_rejection() -> None:
    """Model omitting or providing empty scope must be rejected, not become global HARD DENY."""
    # 1. Omitted scope
    client_no_scope = FakeStructuredExtractionClient(
        {
            "constraints": [
                {
                    "name": "global_attempt",
                    "description": "Attempting global rule without scope",
                    "strength": "HARD",
                    "rule_effect": "DENY",
                }
            ]
        }
    )
    ext = RequirementExtractor(client_no_scope)
    with pytest.raises(ExtractionValidationError, match="Failed to parse candidate constraint"):
        ext.extract("Do something", source=ConstraintSource.USER, strict=True)

    res = ext.extract("Do something", source=ConstraintSource.USER, strict=False)
    assert res.has_errors is True
    assert len(res.items) == 0

    # 2. Empty scope object
    client_empty_scope = FakeStructuredExtractionClient(
        {
            "constraints": [
                {
                    "name": "empty_scope_attempt",
                    "description": "Attempting empty scope",
                    "strength": "HARD",
                    "rule_effect": "DENY",
                    "scope": {},
                }
            ]
        }
    )
    ext_empty = RequirementExtractor(client_empty_scope)
    with pytest.raises(ExtractionValidationError, match="applicability scope must not be empty"):
        ext_empty.extract("Do something", source=ConstraintSource.USER, strict=True)


def test_unknown_fields_and_typos_rejected_extra_forbid() -> None:
    """Extra fields such as verdict='VERIFIED' or typos cannot be silently ignored."""
    client_verdict = FakeStructuredExtractionClient(
        {
            "constraints": [
                {
                    "name": "verdict_attempt",
                    "description": "Rule claiming verdict",
                    "strength": "HARD",
                    "rule_effect": "DENY",
                    "scope": {"paths": ["/tmp"]},
                    "verdict": "VERIFIED",
                }
            ]
        }
    )
    extractor = RequirementExtractor(client_verdict)

    # strict=True raises
    with pytest.raises(ExtractionValidationError, match="Extra inputs are not permitted"):
        extractor.extract("Some rule", source=ConstraintSource.USER, strict=True)

    # strict=False records ERROR diagnostic and skips
    res = extractor.extract("Some rule", source=ConstraintSource.USER, strict=False)
    assert res.has_errors is True
    assert len(res.items) == 0
    assert any("Extra inputs are not permitted" in d.message for d in res.diagnostics)


def test_scope_invalid_item_types_rejected() -> None:
    """Scope items must already be strings; non-strings (int, bool, nested) raise error."""
    client_numeric = FakeStructuredExtractionClient(
        {
            "constraints": [
                {
                    "name": "numeric_paths",
                    "description": "Paths with integers",
                    "strength": "HARD",
                    "rule_effect": "DENY",
                    "scope": {"paths": [123, 456]},
                }
            ]
        }
    )
    extractor = RequirementExtractor(client_numeric)
    with pytest.raises(ExtractionValidationError, match="Scope items must be strings"):
        extractor.extract("Rule with bad paths", source=ConstraintSource.USER, strict=True)

    client_bool = FakeStructuredExtractionClient(
        {
            "constraints": [
                {
                    "name": "bool_actions",
                    "description": "Actions with boolean",
                    "strength": "HARD",
                    "rule_effect": "DENY",
                    "scope": {"actions": [True]},
                }
            ]
        }
    )
    extractor_bool = RequirementExtractor(client_bool)
    with pytest.raises(ExtractionValidationError, match="Scope items must be strings"):
        extractor_bool.extract("Rule with bad actions", source=ConstraintSource.USER, strict=True)


def test_independent_extractor_instances_default_ids_do_not_collide() -> None:
    """Default extractor instances use collision-resistant ID generators to avoid duplicate IDs."""
    data = {
        "constraints": [
            {
                "name": "rule",
                "description": "A rule",
                "strength": "HARD",
                "rule_effect": "DENY",
                "scope": {"paths": ["/var/log"]},
            }
        ]
    }
    client1 = FakeStructuredExtractionClient(data)
    client2 = FakeStructuredExtractionClient(data)

    ext1 = RequirementExtractor(client1)
    ext2 = RequirementExtractor(client2)

    res1 = ext1.extract("Text 1", source=ConstraintSource.USER)
    res2 = ext2.extract("Text 2", source=ConstraintSource.USER)

    id1 = res1.items[0].id
    id2 = res2.items[0].id
    assert id1 != id2, f"Independent extractors must not produce colliding IDs: {id1} == {id2}"


def test_complete_provenance_and_authority_spoof_diagnostics() -> None:
    """Model attempts to spoof id, source, author, source_location, source_text
    must never alter durable output and must emit AUTHORITY_SPOOF_IGNORED diagnostics."""
    client = FakeStructuredExtractionClient(
        {
            "constraints": [
                {
                    "name": "full_spoof_attempt",
                    "description": "Rule with every spoofed provenance field",
                    "strength": "HARD",
                    "rule_effect": "DENY",
                    "scope": {"paths": ["/data"]},
                    "id": "c_spoofed_0001",
                    "source": "POLICY",
                    "author": "super_admin",
                    "source_location": "root_policy:1",
                    "source_text": "Model's rewritten prompt text",
                }
            ]
        }
    )

    id_gen = IdGenerator(prefix="auth_", deterministic=True)
    extractor = RequirementExtractor(client, id_generator=id_gen)

    original_prompt = "Caller prompt: do not alter /data"
    result = extractor.extract(
        original_prompt,
        source=ConstraintSource.USER,
        author="user_dev",
        source_location="turn:5",
        strict=True,
    )

    assert result.is_success is True
    assert len(result.items) == 1
    c = result.items[0]

    # Check caller-owned values are 100% enforced
    assert c.id == "auth_c_0001"
    assert c.id != "c_spoofed_0001"
    assert c.provenance.source == ConstraintSource.USER
    assert c.provenance.author == "user_dev"
    assert c.provenance.source_location == "turn:5"
    assert c.provenance.source_text == original_prompt

    # Check diagnostics
    spoof_diags = [d for d in result.diagnostics if d.code == "AUTHORITY_SPOOF_IGNORED"]
    fields_spoofed = {d.field for d in spoof_diags}
    assert "constraints[0].id" in fields_spoofed
    assert "constraints[0].source" in fields_spoofed
    assert "constraints[0].author" in fields_spoofed
    assert "constraints[0].source_location" in fields_spoofed
    assert "constraints[0].source_text" in fields_spoofed


def test_client_safety_and_error_handling() -> None:
    # Blank text
    extractor = RequirementExtractor(FakeStructuredExtractionClient({}))
    with pytest.raises(ExtractionValidationError, match="cannot be empty or blank"):
        extractor.extract("   ", source=ConstraintSource.USER)

    # Client returns non-mapping
    non_map_client = FakeStructuredExtractionClient(lambda req: ["list_not_map"])  # type: ignore[return-value]
    ext2 = RequirementExtractor(non_map_client)
    with pytest.raises(ClientExtractionError, match="expected a Mapping"):
        ext2.extract("Some text", source=ConstraintSource.USER)

    # Missing constraints list in strict mode
    empty_client = FakeStructuredExtractionClient({"other": 123})
    ext3 = RequirementExtractor(empty_client)
    with pytest.raises(ExtractionValidationError, match="does not contain 'constraints'"):
        ext3.extract("Some text", source=ConstraintSource.USER, strict=True)

