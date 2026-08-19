# ALG-0001: Evidence admission, canonicalization, and deduplication
## Metadata
- Status: proposed
- Owner module: research
- Product feature: Evidence intake and source-of-record deduplication
- Flow IDs: evidence-intake-flow
- Related ADRs: architecture adoption ADR
- Source paths: planned under `backend/src/thesis_trace/modules/research`
- Test and benchmark paths: planned under `backend/tests/research`
- Supersedes: none
## Problem and observable success
Accept approved URLs and produce one canonical source record per URL/content/lineage identity while preserving every retrieval attempt.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are submitted URL, source category, bytes, headers, publisher and observed times. Output is admitted/rejected plus canonical record, immutable snapshot hash, lineage and duplicate link. URLs and hashes must be non-empty; unparseable or unsafe responses fail closed.
## Constraints and quantitative acceptance thresholds
No duplicate source-of-record for the same normalized URL or SHA-256 content; redirects and aliases retain lineage; SSRF controls are mandatory.
## Candidate methods and comparative evidence
Candidates: raw-URL uniqueness; normalized URL plus content hash and lineage. The latter is selected because raw URLs miss aliases and content reuse; database uniqueness and fixture evidence are required.
## Selected method and reasons for rejecting alternatives
Normalize scheme/host/default port/path/query using an allowlisted rule set, fetch through the restricted adapter, hash exact stored bytes, and resolve URL-key then content/lineage-key in one transaction. Raw-URL-only dedup is rejected.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Reject unsupported scheme/host or unsafe redirect. `url_key=SHA256(normalized_url)` and `content_key=SHA256(bytes)`. Existing URL key wins; otherwise an existing content key becomes the canonical record and the new URL becomes lineage; otherwise create. Concurrent ties are settled by database uniqueness and reread.
## Parameters, calibration, versioning, and compatibility
Version normalization, fetch limits, redirect limit, MIME allowlist and hash algorithm; never reinterpret old keys in place.
## Time and space complexity and resource budgets
URL work is O(length); hashing is O(bytes), streamed with bounded response size and memory.
## Errors, degradation, fallback, and forbidden behavior
Timeouts retry; permanent unsafe/invalid responses fail. Never accept AI search text as source of record or silently truncate hashed content.
## Validation cases and evidence
Golden fixtures cover aliases, redirects, same/different content, concurrent duplicates, malformed URLs and SSRF targets. Property tests require normalization idempotence; PostgreSQL integration proves uniqueness/outbox atomicity.
## Risks and monitoring
Normalization changes can merge distinct resources; monitor collision/alias rates and fetch failures.
## Human approval
Pending non-AI owner approval.
