# DEC-107 native evidence enablement (development only)

SPEC-0001 r103 selects Linux perf/ftrace; execution was renewed with
`開始執行`. This first slice establishes capture capability, not parser CPU/RSS
acceptance. No production imports, architecture entries or accepted budgets change.

## Boundary Design Table

| Interaction | Producer | Consumer | Parent | Producer contract | Consumer contract | Mapping owner | State accessed | Allowed edges | Forbidden edges |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Bounded command | test operator | perf / fixed synthetic child | diagnostic CLI | executable + argv, time/byte limits | foreground command | CLI | private process group and files | test CLI → local OS | product → perf; system-wide capture |
| Capture evidence | perf | test operator | diagnostic CLI | original perf.data and export | complete bounded files | CLI | unique local run directory | CLI → local evidence | network upload; production DB |
| Evaluation | diagnostic CLI | governed validation runner | operator | run-ID/monotonic events + action results | profile-bound enablement flow | runner | immutable result bundle | test logs → capability verdict | app logs → resource PASS |

## Type Ownership Matrix

No production named types or project-type references. Primitive argv/list/dict,
Path, Popen and file handles remain private development representations. The CLI
owns diagnostic metadata; the installed validation runner owns verdicts. No ABI,
wire or persistent product schema changes.

## State Object Ownership Matrix

| State | Owner | Lifetime / authority | Escape / storage |
| --- | --- | --- | --- |
| Process group / open output file | bounded command runner | one invocation; runner alone signals and reaps its own group | private local handle; no global PID registry |
| Native artifact / action metadata | diagnostic CLI | one create-only run; operator reads | local evidence only |
| Domain jobs / snapshots / retries | existing Research | unchanged | not accessible to diagnostic |

## Edges, mappings and assurance

Existing production edges and parent mappings are unchanged. All Python additions
are in `backend/tests/**`, the manifest's development source set. The separate
`validation/extraction-native.yaml` is test configuration, not a release profile.
It binds the current manifest and accepted functional-compatibility profile solely
for enablement; it cannot expand that profile to performance assurance.

The declared seam is the DEC-107 bounded local native-command/evidence boundary.
Host tests exercise timeout, output cap and process cleanup through that boundary;
they do not substitute for a successful perf capture. No product algorithm changes.
No scheduler, priority, concurrency, cgroup, kernel or security-policy changes.

## Capture scope and safety

Before touching Docker, record only a newly spawned fixed Python computation for
0.2 seconds, with user-space task-clock sampling at 99 Hz and eight ring pages.
No `-a`, existing PID attachment, stack capture, network, secrets, debug download,
sudo, setcap or sysctl. Preserve raw trace and bounded text export. Each command
has a five-second watchdog and a 1 MiB file-size hard limit; stdout/stderr have a
64 KiB acceptance cap. SIGTERM then SIGKILL are limited to the runner-created
process group, followed by wait and a group-existence check. Never overwrite runs.
These are diagnostic safety ceilings, not product resource acceptance thresholds.

Permission denial or missing export blocks native enablement. Do not claim that
functional fixtures, a valid profile or executable discovery proves capture.
Actual parser tracing and calibrated resource criteria follow only after this
capability checkpoint succeeds. No final ALG-0035 or release approval is inferred.

## One explicitly approved administrator retry

After the unprivileged run was denied, the Owner answered `允許。` to one scoped
administrator perf capture, without permanent privilege or kernel changes.
`native_admin_probe.py` is a development-only operator wrapper; it itself runs as
UID 1000. Only fixed installed timeout/prlimit/perf commands run via sudo -n.
perf records to stdout, already opened by the ordinary user in a create-only run,
so no arbitrary root-owned output path or subsequent privileged export is needed.
The fixed Python workload is started via setpriv as UID/GID 1000, empty groups,
empty capability bounding/inheritable/ambient sets and no-new-privileges.
No repository code executes as root. The ordinary-user wrapper owns files and
command handles; no production type/state/port/edge/mapping changes.

Root timeout sends INT after five seconds and KILL one second later; prlimit
enforces a 1 MiB hard file limit. perf has its own 1 MiB limit, eight ring pages,
99 Hz sampling and the existing 0.2-second fixed workload. An unprivileged outer
wait detects watchdog failure but must not broaden cleanup to unrelated PIDs.
Cleanup requires the command supervisor to exit and its process group to disappear;
incomplete native lifecycle or trace loss remains a separate evidence limitation.
One capture only; exports do not open new kernel tracing events. Exact argv and
file hashes are retained. `validation/extraction-native-admin.yaml` is a separate
enablement profile; the original denied run/profile remain unchanged.
