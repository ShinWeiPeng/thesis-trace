# ALG-0001: Evidence admission, canonicalization, and deduplication
## Metadata
- Status: accepted
- Owner module: evidence_collection
- Product feature: Evidence intake and source-of-record deduplication
- Flow IDs: owner_evidence_intake
- Related ADRs: architecture adoption ADR
- Source paths: `backend/src/thesis_trace/platform/source_fetch.py`, `backend/src/thesis_trace/platform/postgres.py`
- Test and benchmark paths: `backend/tests/test_source_fetch.py`, `backend/tests/test_postgres_store.py`
- Supersedes: none
## Problem and observable success
Accept approved URLs and produce one canonical source record per URL/content/lineage identity while preserving every retrieval attempt.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are submitted URL, source category, bytes, headers, publisher and observed times. Output is admitted/rejected plus canonical record, immutable snapshot hash, lineage and duplicate link. URLs and hashes must be non-empty; unparseable or unsafe responses fail closed.
## Constraints and quantitative acceptance thresholds
No duplicate canonical-source identity for the same normalization-policy version and normalized URL, and no duplicate immutable snapshot for the same SHA-256 content; redirects and aliases retain lineage; SSRF controls are mandatory.
## Candidate methods and comparative evidence
Candidates: raw-URL uniqueness; normalized URL plus content hash and lineage. The latter is selected because raw URLs miss aliases and content reuse; database uniqueness and fixture evidence are required.
## Selected method and reasons for rejecting alternatives
Under `url-normalization-v1`, require approved HTTPS, lowercase the hostname, remove explicit `:443` and fragments, and map an empty path to `/`; preserve every non-empty path byte representation and the complete query spelling, duplicate parameters, and ordering. Fetch through the restricted adapter, hash exact stored bytes, and resolve the versioned URL identity then the global content snapshot in one transaction. Raw-URL-only and aggressive path/query normalization are rejected because they respectively miss safe aliases or risk merging distinct resources.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Reject unsupported scheme/host or unsafe redirect. `url_key=(normalization_policy_version,canonical_url)` and `content_key=SHA256(bytes)`. Existing versioned URL identity wins; otherwise reuse an existing content snapshot and create a new version-bound canonical-source identity, or create both when content is new. Each observation retains its submitted URL and version-bound canonical source. Advisory locks plus database uniqueness settle concurrent ties.
## Parameters, calibration, versioning, and compatibility
Persist the normalization version on the canonical-source identity and the snapshot that first materializes content. Migration 0005 backfills pre-versioned identities and snapshots as `url-normalization-legacy`, preserving their literal historical keys without claiming v1 semantics. A future normalization rule requires a new version plus an explicit migration or coexistence policy; never reinterpret old keys in place. Fetch limits, redirect limit, MIME allowlist, and hash algorithm remain separately versioned implementation parameters.
## Time and space complexity and resource budgets
URL work is O(length); hashing is O(bytes), streamed with bounded response size and memory.
## Errors, degradation, fallback, and forbidden behavior
Timeouts retry; permanent unsafe/invalid responses fail. Never accept AI search text as source of record or silently truncate hashed content.
## Validation cases and evidence
Golden fixtures cover aliases, redirects, preserved non-empty path/query spelling, normalization idempotence, same/different content, concurrent duplicates, malformed URLs, and SSRF targets. PostgreSQL integration proves version-bound URL coexistence, global content-hash uniqueness, provenance policy binding, migration registration, and outbox atomicity. The bounded adapter regression suite runs with `backend/.venv/bin/python -m pytest -q backend/tests/test_source_fetch.py`; database evidence runs with `THESIS_TRACE_TEST_DATABASE_URL=<test-url> backend/.venv/bin/python -m pytest -q backend/tests/test_postgres_store.py`.
## Risks and monitoring
Normalization changes can merge distinct resources; monitor collision/alias rates and fetch failures.
## Human approval
- Approver: project owner
- Approval date: 2026-08-20
- Approval reference: `codex://threads/01a0197a-d1c9-7b83-a660-6613830f44a1`
