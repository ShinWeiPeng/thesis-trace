from __future__ import annotations

import json
import importlib.util
from pathlib import Path

import pytest

from thesis_trace.modules.research.anomaly_assessment.qualification import (
    load_qualification_cases,
    evaluate_offline_qualification,
)
DATASET = Path(__file__).parent / "fixtures" / "anomaly-qualification-v1.json"
RUNNER = Path(__file__).parents[2] / "scripts" / "run_anomaly_qualification.py"
_runner_spec = importlib.util.spec_from_file_location("run_anomaly_qualification", RUNNER)
assert _runner_spec is not None and _runner_spec.loader is not None
_runner = importlib.util.module_from_spec(_runner_spec)
_runner_spec.loader.exec_module(_runner)
validate_ai_contracts = _runner.validate_ai_contracts


def test_versioned_100_case_dataset_passes_every_zero_tolerance_gate() -> None:
    cases = load_qualification_cases(DATASET)
    result = evaluate_offline_qualification(cases)

    assert result.passed is True
    assert result.dataset_version == "anomaly-qualification-v1"
    assert result.versions is not None
    assert result.versions.policy_version == "anomaly-policy-v1"
    assert result.versions.provider_model_version == "prevalidated-candidate-fixture-v1"
    assert result.total_cases == 100
    assert result.hard_positive_passes == 40
    assert result.false_hard_count == 0
    assert result.auxiliary_label_passes == 100
    assert result.company_count >= 10
    assert result.industry_count >= 5
    assert result.failure_case_ids == ()
    assert validate_ai_contracts(cases) == ()
    assert result.category_counts == (
        ("single_a_positive", 20),
        ("independent_b_positive", 20),
        ("insufficient_negative", 20),
        ("lineage_conflict_negative", 15),
        ("critic_failure_negative", 15),
        ("market_novel_negative", 10),
    )


def test_missing_case_wrong_label_or_false_hard_blocks_qualification(tmp_path: Path) -> None:
    payload = json.loads(DATASET.read_text(encoding="utf-8"))
    payload["cases"] = payload["cases"][:-1]
    short_path = tmp_path / "short.json"
    short_path.write_text(json.dumps(payload), encoding="utf-8")
    assert evaluate_offline_qualification(load_qualification_cases(short_path)).passed is False

    payload = json.loads(DATASET.read_text(encoding="utf-8"))
    payload["cases"][40]["expected_class"] = "would_be_hard"
    wrong_path = tmp_path / "wrong.json"
    wrong_path.write_text(json.dumps(payload), encoding="utf-8")
    result = evaluate_offline_qualification(load_qualification_cases(wrong_path))
    assert result.passed is False
    assert "NEG-001" in result.failure_case_ids

    payload = json.loads(DATASET.read_text(encoding="utf-8"))
    payload["cases"][0]["auxiliary_label"] = "critic_timeout"
    wrong_label_path = tmp_path / "wrong-label.json"
    wrong_label_path.write_text(json.dumps(payload), encoding="utf-8")
    result = evaluate_offline_qualification(load_qualification_cases(wrong_label_path))
    assert result.passed is False
    assert "A-001" in result.failure_case_ids


def test_dataset_loader_rejects_coerced_boolean_and_unknown_fields(tmp_path: Path) -> None:
    for mutate in (
        lambda payload: payload["cases"][0].__setitem__("critic_passed", "false"),
        lambda payload: payload["cases"][0].__setitem__("unexpected", True),
    ):
        payload = json.loads(DATASET.read_text(encoding="utf-8"))
        mutate(payload)
        malformed = tmp_path / f"malformed-{len(list(tmp_path.iterdir()))}.json"
        malformed.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="invalid_qualification_dataset"):
            load_qualification_cases(malformed)


def test_versioned_critic_fixture_drift_fails_the_exact_contract_cases(tmp_path: Path) -> None:
    payload = json.loads(DATASET.read_text(encoding="utf-8"))
    payload["validation_fixtures"]["subject_failure"]["verdict"] = "PASS"
    payload["validation_fixtures"]["subject_failure"]["subject_matches"] = True
    drifted = tmp_path / "drifted-critic.json"
    drifted.write_text(json.dumps(payload), encoding="utf-8")

    failures = validate_ai_contracts(load_qualification_cases(drifted))

    assert failures == ("CRI-010", "CRI-011", "CRI-012")
