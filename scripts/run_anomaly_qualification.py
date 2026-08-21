#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from thesis_trace.modules.research.anomaly_assessment.qualification import (
    evaluate_offline_qualification,
    load_qualification_cases,
)
from thesis_trace.application.ai_ports import (
    AnalysisSource,
    validate_anomaly_candidate,
    validate_critic_pass,
)


def validate_ai_contracts(cases) -> tuple[str, ...]:
    failures: list[str] = []
    for case in cases:
        sources = tuple(
            AnalysisSource(
                source_snapshot_id=source.source_snapshot_id,
                publisher_identity=source.publisher_identity,
                source_tier_facts=(
                    source.authoritative_first_party,
                    source.formal_record,
                    source.editorial_responsibility,
                    source.attributed_author,
                    source.verifiable_primary_evidence,
                ),
                underlying_evidence_id=source.underlying_evidence_id,
                canonical_url=f"https://qualification.invalid/{source.source_snapshot_id}",
                excerpt=f"Versioned qualification evidence for {case.case_id}",
                retrieved_at="2026-08-21T00:00:00Z",
                published_at="2026-08-20T00:00:00Z",
                observed_at=None,
            )
            for source in case.sources
        )
        actual_critic_passed = False
        try:
            validate_anomaly_candidate(case.candidate_json, sources=sources)
            if case.critic_json is not None:
                actual_critic_passed = validate_critic_pass(case.critic_json)
        except ValueError:
            actual_critic_passed = False
        if actual_critic_passed is not case.critic_passed:
            failures.append(case.case_id)
    return tuple(failures)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    dataset = root / "backend/tests/fixtures/anomaly-qualification-v1.json"
    cases = load_qualification_cases(dataset)
    result = evaluate_offline_qualification(cases)
    contract_failures = validate_ai_contracts(cases)
    output = asdict(result)
    output["ai_contract_failure_case_ids"] = contract_failures
    output["passed"] = result.passed and not contract_failures
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
