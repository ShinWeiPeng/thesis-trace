# DEC-107 parser-container resource preparation (development only)

Question: can future native resource evidence be bound to exactly the disposable
parser container and its descendants, without tracing the application or host?
This slice prepares selectors and workloads; it does not execute perf or sudo.
SPEC-0001 r103 remains unchanged. The prior one-capture authorization is consumed.

## Boundary Design Table

| Interaction | Producer | Consumer | Parent | Producer contract | Consumer contract | Mapping owner | State accessed | Allowed edges | Forbidden edges |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Temporary service setup | operator | existing offline Compose prototype | preflight CLI | exact random project and pinned image | two bounded services | CLI | its project/container/volume handles | CLI → Docker | parser/client → Docker; product Compose edits |
| Process identity | Docker inspect + Linux procfs | operator | preflight CLI | init PID, full container ID, start ticks, cgroup path | exact matching identity tuple | CLI | read-only identity files | CLI → own container proc/cgroup | guessed PID; scanning unrelated processes |
| Resource availability | kernel cgroup v2 files | operator | preflight CLI | bounded raw counter snapshots | capability inventory, not resource PASS | CLI | own container cgroup only | CLI → read-only kernel counters | writes to cgroup/sysctl; logs substituting native trace |
| Cleanup | operator | Docker | preflight CLI | exact project label | no remaining project objects | CLI | its temporary containers/volume | CLI → exact project down | prune; original data deletion |

## Type and State Ownership Matrices

No production types, project-type references, ABI, protocol or database changes.
Development primitive dict/list/Path values are private diagnostic representations.

| State | Owner | Lifetime and authority | Consumers / escape |
| --- | --- | --- | --- |
| Project ID, container IDs, init PID/start ticks | preflight operator | one run, read/refresh by operator only | create-only local report; never reused as future trace authorization |
| Raw kernel-file snapshots | kernel; operator owns copies | read-only bounded snapshots | diagnostic capability report, not claimed measurements |
| Command handles, cleanup result | preflight operator | one run, scoped to its project | report only |
| Research jobs/snapshots/retries | existing Research | unchanged | never connected to preflight |

Actual production dependencies, parent mappings, manifest and generated views stay
unchanged. The development CLI uses existing Compose and diagnostic helpers.
Only operator → Docker and operator → procfs/cgroup edges are added to the test
workflow; no product Flow, runtime allocation or accepted algorithm is changed.
The existing functional-only profile is not extended to performance assurance.

## Preflight operation

Create one random `tt-resource-preflight-*` project using the existing two-service
Compose file, existing pinned image and pypdf 6.18.0. Both services remain offline,
UID 65532, read-only, cap-drop ALL, no-new-privileges, no secrets/Docker socket,
128 MiB memory, no additional swap, 16 PIDs and one CPU quota per service.
Do not send parsing/fault requests. Read init and supervisor identity, exact
cgroup membership, limits and availability of kernel counters, then remove only
this project's containers and tmpfs IPC volume. No package/image download.

The preflight report must separate topology availability from native resource
acceptance. PIDs/start times are historical evidence, never reusable selectors.
Each eventual capture must reacquire and revalidate container ID, PID start ticks,
cgroup membership and image/settings immediately before attachment; a changed
generation, exited PID or missing path blocks capture, never widens scope.

## Approved bounded capture batch

Owner answered `允許` on 2026-09-10 to this eight-capture batch. This is a
permission-only continuation of SPEC-0001 r103, not approval of ALG-0035 or
production resource budgets. The earlier single enablement capture is separate.

| Case | Existing workload | Expected application outcome | Native evidence needed |
| --- | --- | --- | --- |
| html | synthetic visible paragraph | readable; no verified facts | child creation/exit, CPU evidence |
| pdf | existing synthetic two-page PDF | readable with page 2 missing-text warning | child creation/exit, CPU evidence |
| memory | existing child address-space fault | memory_limit; supervisor retained | child exit + cgroup resource snapshots |
| cpu | existing busy-loop fault | child_terminated | task-clock / exit, bounded observation |
| wall | existing child sleep fault | wall_limit | lifecycle / elapsed monotonic window; no requirement for idle CPU samples |
| output | existing output-overflow fault | output_limit | child termination and survivor identity |
| service-oom | existing guarded 128 MiB cgroup fault | unavailable; next HTML readable in new generation | separate pre-fault and post-restart scoped captures; no continuity claim across restart gap |

At most **eight** native captures: one per first six rows, two for service-oom
and its healthy recovery. Each capture ≤15 seconds including a 1-second kill grace,
each original trace ≤4 MiB, cumulative original traces ≤32 MiB. Total batch
wall-clock safety ceiling 5 minutes including service startup and cleanup.
These ceilings bound diagnostic risk, not accepted production budgets or SLOs.
No automatic retry/recapture beyond eight; a failure retains partial evidence and
stops the affected dependent claim. No blanket root/sudo authorization is inferred.

The precise capture argv, native normalization and runtime smoke profile must
validate before any capture, after this selector preflight. Request native permission
for the bounded batch once, not once per test. Only installed trace/watchdog tools
may run privileged; repository/application code stays unprivileged. Never grant
the collector a Docker socket, change perf_event_paranoid, setcap, seccomp or
tracefs permissions. No whole-system `-a` fallback.

## Evidence semantics and limits

- `memory.current`/`memory.peak` concern cgroup-accounted memory, not process RSS.
  `memory.max` is a configured limit, not a proof that peak never exceeded it.
  Read-only fresh-cgroup baselines avoid resetting counters. Kernel documentation
  explicitly allows temporary excursions over memory.max; do not invent a zero-
  overshoot product acceptance threshold.
- `/proc/PID/cgroup` and cgroup.procs bind identity; resource snapshots need the
  same run ID and monotonic windows as native traces. A missing/replaced cgroup
  during restart must remain missing, not silently replaced by a later one.
- perf PID attachment must cover already existing supervisor tasks as well as
  later descendants; attaching only to container init can miss an existing child.
- Kernel counters are supplemental native-source artifacts, not application logs.
  No resource criterion gets PASS from a configured cap, a missing sample or a
  functional response alone. No mean/percentile/RSS/SLO or production-winner claim.
- Formal resource metric/sample contracts and ALG-0035 remain unapproved. This
  batch is diagnostic smoke/calibration input only, not release acceptance.

Primary references: [Linux cgroup v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)
and [perf-record](https://man7.org/linux/man-pages/man1/perf-record.1.html).

## Execution wiring (test-only, before source)

`container_native_smoke.py` owns the batch, its eight-attempt counter, 300-second
deadline, exact Compose handles, child-process handles and create-only artifacts.
`container_native_capture.py` owns one capture and FIFO handles until cleanup.
Both are development-source CLI helpers, not product modules. Their only new
edge is batch → capture helper → installed perf/timeout and read-only cgroup
files. No public named types, project type references, storage or wire changes;
primitive dict/list/Path values and handles stay private to this test composition.
The boundary table above applies with the batch CLI replacing the preflight CLI.
Only the fixed installed timeout/prlimit/perf argv uses sudo; no repository code
runs as root. All existing parser PIDs are revalidated immediately before attach;
perf inherits future children. No system-wide or cgroup-wide CPU selector.

The local perf manual documents `--control=fifo:ctl,ack`, `enable`, `stop` and
`ack\n`. Start disabled (`-D -1`), await enable acknowledgement before submitting
work. Stop after response; a privileged 14-second timeout plus 1-second kill
grace is independent of the operator. Raw trace stdout is an ordinary-user-owned
preopened file, hard-limited to 4 MiB. Exports are unprivileged, bounded separately.
Counter snapshots bracket workload and share the run ID and CLOCK_MONOTONIC;
old cgroup disappearance at OOM is retained, not rebound to the new generation.
Eight attempts are a ceiling, not a requirement to continue after unsafe cleanup.

`validation/extraction-container-smoke.yaml` governs only request → diagnostic
case coverage → cleanup, with actual traces retained and checked before emitting
coverage. It does not define native metric thresholds, RSS, percentiles or formal
acceptance. Existing functional-only architecture and profiles remain unchanged.

## First batch disposition (2026-09-10)

Batch `636d9816e98441be8e3ec3cc85696b9f` used **one** capture and stopped before
submitting the first HTML request. Installed perf returned `ack\n\0`, while the
wrapper required exactly `ack\n`. Native recording was started, so the failed
attempt counts against the allowance. Seven captures were not used; they are not
an automatic new eight-capture allowance. Batch duration 0.9105 seconds, raw trace
12,204 bytes; exact test project and trace processes were cleaned up.

The runtime runner verdict remains BLOCKED. A host regression reproduced the
exact acknowledgement rejection, then passed after accepting only the documented
line and observed single-NUL encoding. Unexpected trailing bytes still reject.
No post-fix native replay has occurred. Do not reuse the consumed `a1` output
path/profile action. A complete fresh eight-case rerun requires renewed batch
permission and a new create-only path/profile binding; preserve the first bundle.
