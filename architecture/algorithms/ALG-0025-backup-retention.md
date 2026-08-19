# ALG-0025: Backup retention and restore readiness
## Metadata
- Status: proposed
- Owner module: notification
- Product feature: Encrypted B2 backup lifecycle
- Flow IDs: backup-maintenance-flow
- Related ADRs: none
- Source paths: planned platform backup adapter
- Test and benchmark paths: planned backup/restore validation
- Supersedes: none
## Problem and observable success
Select daily/monthly restore points, apply retention/Object Lock and fail readiness when restoration cannot be proven.
## Inputs, outputs, units, ranges, and data-quality assumptions
Inputs are successful encrypted backup manifests, dates, hashes, lock/retention metadata and monthly restore evidence; output keep/delete eligibility and readiness.
## Constraints and quantitative acceptance thresholds
Keep 30 daily and 12 monthly; new objects lock 30 days; monthly drill must retrieve offline key, verify fingerprint, decrypt and restore isolated DB.
## Candidate methods and comparative evidence
Candidates: age-only deletion; calendar buckets with immutable manifests. Bucket selection is chosen to satisfy both retention classes deterministically.
## Selected method and reasons for rejecting alternatives
Choose newest successful backup per Asia/Taipei calendar day/month, union newest 30 daily and 12 monthly, and delete only when outside union and Object Lock permits.
## Exact behavior, formula or pseudocode, boundaries, and tie-breaking
Tie selects later completed valid manifest, then stable ID. Readiness PASS only if latest scheduled drill verifies key/hash/decrypt/restore/query checks; any failure creates safety-locked item and readiness FAIL.
## Parameters, calibration, versioning, and compatibility
Timezone, counts, lock days, encryption/manifest versions are explicit.
## Time and space complexity and resource budgets
O(backups log backups), bounded metadata.
## Errors, degradation, fallback, and forbidden behavior
Never upload plaintext, delete locked objects, or claim readiness from upload alone.
## Validation cases and evidence
Calendar/month boundaries, missing days, lock refusal, corrupt key/ciphertext and isolated restore drill.
## Risks and monitoring
Single offline recovery copy remains a declared irreducible risk.
## Human approval
Pending non-AI owner approval.
