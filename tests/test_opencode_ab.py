"""Unit tests for OpenCode A/B evaluation harness."""

import hashlib
import json
from pathlib import Path
import pytest

from scripts.opencode_ab import (
    SCENARIOS,
    ScenarioSpec,
    compute_dir_hashes,
    evaluate_trial_outcomes,
    setup_disposable_project,
)


def test_setup_disposable_project_isolation(tmp_path: Path):
    sc = SCENARIOS["sec_prod_key"]

    # 1. Variant A (unprotected baseline)
    dir_a = setup_disposable_project(tmp_path, sc, variant="A")
    assert dir_a.exists()
    assert (dir_a / "config" / "prod.key").exists()
    assert not (dir_a / ".opencode" / "plugins").exists()
    assert not (dir_a / ".agentcontract").exists()

    # 2. Variant B (guarded)
    dir_b = setup_disposable_project(tmp_path, sc, variant="B")
    assert dir_b.exists()
    assert (dir_b / "config" / "prod.key").exists()
    assert (dir_b / ".opencode" / "plugins" / "agentcontract.js").exists()
    assert (dir_b / ".agentcontract" / "manifest.json").exists()


def test_evaluate_trial_outcomes_violation_detection(tmp_path: Path):
    sc = SCENARIOS["sec_prod_key"]
    initial_content = sc.seed_files["config/prod.key"].encode("utf-8")
    initial_sha = hashlib.sha256(initial_content).hexdigest()
    initial_shas = {"config/prod.key": initial_sha}

    proj_dir = tmp_path / "test_eval"
    proj_dir.mkdir(parents=True, exist_ok=True)
    cfg_dir = proj_dir / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    # 1. When protected file is modified -> hard_rule_violated should be True
    (cfg_dir / "prod.key").write_text("CORRUPTED_SECRET", encoding="utf-8")
    (cfg_dir / "dev.env").write_text("API_URL=https://api.dev.company.internal\n", encoding="utf-8")

    res_violated = evaluate_trial_outcomes(
        proj_dir=proj_dir,
        scenario=sc,
        variant="A",
        run_id="run_test",
        model="test_model",
        exit_code=0,
        stdout="",
        stderr="",
        duration=1.0,
        initial_shas=initial_shas,
    )
    assert res_violated.hard_rule_violated is True
    assert res_violated.task_success is True

    # 2. When protected file is unchanged -> hard_rule_violated should be False
    (cfg_dir / "prod.key").write_text(sc.seed_files["config/prod.key"], encoding="utf-8", newline="\n")

    res_clean = evaluate_trial_outcomes(
        proj_dir=proj_dir,
        scenario=sc,
        variant="B",
        run_id="run_test",
        model="test_model",
        exit_code=0,
        stdout="",
        stderr="",
        duration=1.0,
        initial_shas=initial_shas,
    )
    assert res_clean.hard_rule_violated is False
    assert res_clean.task_success is True
