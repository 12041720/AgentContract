"""Tests validating benchmark scenario integrity, uniqueness, and ground-truth references."""

import pytest

from agentcontract.benchmark.scenarios import (
    ALL_STANDARD_SCENARIOS,
    get_standard_scenarios,
)


def test_standard_scenarios_volume_and_uniqueness() -> None:
    scenarios = get_standard_scenarios()
    assert len(scenarios) >= 12

    # All scenario IDs must be strictly unique
    ids = [s.scenario_id for s in scenarios]
    assert len(ids) == len(set(ids)), f"Duplicate scenario IDs found: {ids}"


def test_scenario_ground_truth_references_resolve() -> None:
    for scen in get_standard_scenarios():
        available_claim_ids = {c.claim_id for c in scen.completion_claims}
        for gt_claim_id in scen.ground_truth_supported_claims:
            assert gt_claim_id in available_claim_ids, (
                f"Scenario '{scen.scenario_id}' ground truth supported claim '{gt_claim_id}' "
                f"does not match any claim in completion_claims: {available_claim_ids}"
            )


def test_scenario_fields_validity() -> None:
    for scen in get_standard_scenarios():
        assert scen.scenario_id.strip() != ""
        assert scen.title.strip() != ""
        assert scen.description.strip() != ""
        assert len(scen.tags) > 0


def test_coverage_of_required_scenario_classes() -> None:
    all_scenarios = get_standard_scenarios()
    scen_by_id = {s.scenario_id: s for s in all_scenarios}

    # 1. Hard forbidden file write
    assert "scen_01_forbidden_write" in scen_by_id
    assert scen_by_id["scen_01_forbidden_write"].total_violating_actions >= 1

    # 2. Soft preference warning
    assert "scen_02_soft_warning" in scen_by_id
    assert any(c.strength.value == "SOFT" for c in scen_by_id["scen_02_soft_warning"].initial_constraints)

    # 3. Hidden post-action side effect
    assert "scen_03_post_action_violation" in scen_by_id
    assert "post_guard" in scen_by_id["scen_03_post_action_violation"].tags

    # 4. Failed tool reported as success
    assert "scen_04_failed_tool_false_claim" in scen_by_id

    # 5. Tests claimed passed without evidence
    assert "scen_05_tests_passed_no_evidence" in scen_by_id

    # 6. File claimed created without evidence
    assert "scen_06_file_exists_no_evidence" in scen_by_id

    # 7. Stale file-state observation followed by newer state
    assert "scen_07_stale_file_state" in scen_by_id
    assert len(scen_by_id["scen_07_stale_file_state"].scripted_actions) >= 2

    # 8. Ambiguous repeated tool executions
    assert "scen_08_ambiguous_repeated_calls" in scen_by_id
    assert len(scen_by_id["scen_08_ambiguous_repeated_calls"].scripted_actions) >= 2

    # 9. Timeout / cancelled execution
    assert "scen_09_timeout_execution" in scen_by_id
    assert "timeout" in scen_by_id["scen_09_timeout_execution"].tags

    # 10. REQUIRE / PREFER compliance behavior
    assert "scen_10_require_compliance" in scen_by_id
    assert any(c.rule_effect.value == "REQUIRE" for c in scen_by_id["scen_10_require_compliance"].initial_constraints)

    # 11. Unrelated constraint that should not block
    assert "scen_11_unrelated_constraint" in scen_by_id
    assert scen_by_id["scen_11_unrelated_constraint"].expected_task_success is True

    # 12. Clean successful task that should remain successful
    assert "scen_12_clean_successful_task" in scen_by_id
    assert scen_by_id["scen_12_clean_successful_task"].expected_task_success is True
