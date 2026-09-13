# DEC-106 local IPC experiment (development only)

Question: can a client without Docker authority exchange bounded document bytes
with an offline parser service, reject mismatched/untrusted replies, and recover
after parser-process or service failure? No production source or formal protocol
is changed. SPEC-0001 r100 / DEC-106 authorizes this experiment, not adoption.

## Scope and alternatives

The existing one-document Docker harness proves operator-controlled cleanup but
requires the operator to create each container. This experiment compares that
baseline with a long-lived socket supervisor and fresh, bounded parser children.
A `--recycle` experiment also exits the supervisor after each request to observe
Docker restart behavior. Neither is a selected production winner. The client
never uses Docker APIs; only the outer diagnostic operator runs Compose.

Both services use the existing pinned image, UID 65532, no network, no secrets,
no Docker socket, read-only root, dropped capabilities and no-new-privileges.
A private 1 MiB tmpfs-backed volume carries only the Unix socket; the client
mounts it read-only. A parser-private 8 MiB tmpfs carries unnamed input files.
No source bytes, response fragments or restart counters are persisted to a DB.
The terminal harness only retains bounded diagnostic metadata.

## Boundary Design Table (not a production catalog)

| Interaction | Producer | Consumer | Parent | Producer contract | Consumer contract | Mapping owner | State accessed | Allowed edges | Forbidden edges |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Diagnostic request | client fixture | parser supervisor | operator harness | bounded bytes + request identity | strict local frame | client/supervisor boundary | one in-flight request | client → local socket | client → Docker / DB |
| Parse attempt | supervisor | disposable child | supervisor | bytes, allowlisted kind | existing probe child arguments | supervisor | attempt-local input/output | child → read-only parser library | child → DB / external network |
| Candidate reply | supervisor | client | operator harness | bounded framed JSON | checked identity/hash/shape | client validator | attempt-local response | client → checked value | reply → durable job/snapshot mutation |
| Service lifecycle | Docker runtime | diagnostic service | operator harness | restart policy | fresh service generation | operator only | test containers/volume | operator → own Compose project | collector → Docker API |

## Type Ownership Matrix

No new production named type, Port, Event, or project-type reference. The
development functions use stdlib primitive bytes/dict/socket/process values.
Wire dictionaries are private to the prototype and have no ABI/storage impact.
Request ID/hash/kind/length are client-owned immutable per-call values. Generation
is supervisor-owned immutable per-process metadata. Result is untrusted input
until the client validates identity, shape, limits and the never-verified flag.

## State Object Ownership Matrix

| State | Owner | Lifetime / mutation | Readers / writers | Escape / storage |
| --- | --- | --- | --- | --- |
| Socket, current request, input FD, child handle | supervisor | one server/attempt | supervisor only | private locals; child gets stdin only |
| Partial frame and reply buffer | client | one attempt | client only | bounded local values, no cross-attempt reuse |
| Container IDs, run ID, results | operator harness | one diagnostic run | harness only | create-only diagnostic report |
| Durable jobs, snapshots, retry state | existing Research | unchanged | existing owner only | never connected to this prototype |

No mutable file-scope state, thread-local, global registry or address-passed
production object is introduced. Constants are immutable scalar settings.

## Actual/intended edges and parent mappings

Actual production stays: Research → evidence_collection → demand-owned fetch/job
ports; adapters implement those ports. New files match the existing `development`
source set (`backend/tests/**`), not production catalogs. The manifest, accepted
ADRs, generated views, production dependency graph and DB migrations remain
unchanged. Operator → Compose; fixture client → socket; supervisor → existing
development child. No production module imports the harnesses.

## Experimental framing and failure behavior

Four-byte network-order length followed by strict JSON header (≤1,024 bytes),
then exact document bytes (≤2,000,000). JSON rejects duplicate keys. Reply is a
four-byte length followed by JSON (≤16,384 bytes), bound to request ID and raw
content SHA-256. No automatic retry after sending any request bytes. A new attempt
gets a new connection/ID; late replies on an abandoned connection cannot satisfy
it. Startup connection attempts may wait within a fixed diagnostic window.
Socket reads/writes use one absolute per-attempt limit, not per-byte renewal.

One accepted connection at a time; no application queue or pool. Child uses the
existing resource limits, closed inherited FDs/environment and a five-second
parent wait. Fault-injection verbs are development-only and cannot be added to
the product API. Service OOM injection checks its cgroup before allocation.

## Flow / execution / evolution impact

Production Flow impact is N/A: no entrypoint or consumer is rewired. Experimental
flow is request → frame admission → child → validated response, with explicit
unavailable/protocol/resource failures. Additional cost is framing/copying,
child creation, optional container restart and backoff. Payload buffers and IPC
storage are bounded; quantitative reserve, concurrency behavior and release build
equivalence remain unresolved. Model assurance for production is **BLOCKED**.
No real-time, performance-winner, CPU/RSS calibration or formal runtime claim.

Adding a parser format would affect the existing probe child and allowlist;
changing IPC would affect only development client/supervisor/harness/config.
Adding production retries or durable commits requires Research contracts and a
new exact manifest design, not mutation authority in this client.

## Verification scope

Use executable host integration experiments for frame length/encoding/identity,
readable HTML/PDF, partial/abandoned requests, child wall/CPU/output limits,
service OOM/restart and successful next request. Record service generation and
Docker restart count separately. Inspect both containers for no network/secrets/
Docker access and verify exact project cleanup. Ordinary integration evidence is
not native scheduler/resource acceptance. Formal local validation enablement and
release acceptance remain separate from the Cloudflare profile.

ALG-0035 approval, exact production catalogs, local runtime profile, context-
complete extraction and browser integration remain prerequisites for user-facing
product testing. Operator death, malicious parser code execution, multi-client
fairness and daemon failure are not claimed safe by this experiment.
