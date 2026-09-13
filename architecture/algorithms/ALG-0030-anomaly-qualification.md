# ALG-0030: Hard-anomaly qualification gate
## Metadata
- Status: accepted
- Owner module: anomaly_assessment
- Product feature: Offline and production-shadow enablement
- Flow IDs: anomaly-qualification-flow
- Related ADRs: ADR-0005
- Source paths: `backend/src/thesis_trace/modules/research/anomaly_assessment/qualification.py`
- Test and benchmark paths: `backend/tests/fixtures/anomaly-qualification-v1.json`, `backend/tests/test_anomaly_qualification.py`, `scripts/run_anomaly_qualification.py`; production shadow evidence remains pending
- Supersedes: none
## Problem and observable success
Prevent Hard notification enablement until deterministic offline accuracy and false-Hard-free production shadow evidence exist.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are dataset/version, 100 labeled cases, policy/prompt/model/critic/schema versions, shadow days/results and Owner activation; output qualified/not-qualified.
## Constraints and quantitative acceptance thresholds
Cases: 20 A positive, 20 two-independent-B positive, and 60 specified negatives; Hard positives 40/40, false Hard 0/60, auxiliary labels 100%; then 30 continuous days with zero false Hard.
## Candidate methods and comparative evidence
Candidates: aggregate accuracy; zero-tolerance stratified gates plus shadow reset. Zero tolerance is selected due to safety impact.
## Selected method and reasons for rejecting alternatives
Evaluate every version-bound case, then run shadow where would-be Hard has no formal notification effect.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Offline PASS iff all required counts/labels pass. Shadow counter starts only after offline PASS; any false Hard or material model/prompt/policy change resets to day zero and requires applicable offline rerun. After 30 full consecutive days, Owner must explicitly enable.
## Parameters, calibration, versioning, and compatibility
Dataset annotations, clocks, versions and evidence hashes are immutable.
## Time and space complexity and resource budgets
O(100 + shadow events); evidence retained per policy.
## Errors, degradation, fallback, and forbidden behavior
Missing/ambiguous label, interrupted evidence or unreviewed would-be Hard is not PASS; never auto-enable.
## Validation cases and evidence
Meta-tests verify composition counts, version binding, reset boundaries and zero production side effects.
## Risks and monitoring
Sparse real events may limit confidence despite elapsed days; report event count alongside duration.
## Human approval
- Approver: project owner
- Approval date: 2026-08-21
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
