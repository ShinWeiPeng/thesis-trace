# Throwaway source extraction probe

This is development-only diagnostic code for ALG-0035. It is not imported by
production and must not be promoted into the collector without the accepted
algorithm, ownership catalogs, design gate, contract tests and runtime evidence.

See the [question, environment, run commands, evidence and limitations](../../../architecture/design/source-extraction-prototype-20260909.md).

The interactive selector offers synthetic boundary cases or two explicit public
MediaTek URLs. It never connects to a database or AI provider. Source bytes exist
only during the bounded operation; optional reports contain small previews and
diagnostic metadata, not source documents. The subprocess has no project/home or
secrets mount and no external network. Run only after the applicable local
namespace capability and permission checks.

The prototype and its uncommitted development files remain local pending any
separate authorization to capture them on a throwaway branch. Do not run the old
acceptance fixture or reset an existing database to use this probe.

## Regression checks

The 2026-09-10 repair preserves root-level HTML headings/paragraphs and reports
PDF pages without extracted text. Successful parse results include `total_pages`
(`null` for HTML) and one-based `pages_without_text`. Any such PDF page makes
`selection_incomplete=true`, including an apparently blank page: this is a
conservative text-coverage warning, not an image/OCR classification. A mixed PDF
can still return `readable` fragments while explicitly reporting missing pages.
`document_verified` remains false in all cases; text extraction does not verify
facts or prove that a text-bearing page contains no additional image content.

After selecting an isolated library and granting the same namespace permission
used for the probe, run from the repository root (replace the example path):

```bash
THESIS_TRACE_EXTRACTION_PROTOTYPE_LIBRARY=/path/to/isolated/site-packages backend/.venv/bin/python -m pytest backend/tests/prototypes/test_source_extraction_probe.py backend/tests/test_source_fetch.py -q
```

These tests exercise the actual `run_isolated(bytes, kind, library, memory_mib)`
boundary, not a replacement parser. PDF fixtures are synthetic parser edge cases,
never company evidence. No package is installed by the tests. Without the explicit
library setting, the prototype tests report SKIP, not PASS. With the setting,
missing libraries or denied child launch fail the tests rather than silently
skipping them. Run `--case all` separately for the existing 14 boundary cases.

Remaining limitations include non-unique HTML line/tag locators for blocks on the
same line, bounded excerpts that may omit context, unapproved ALG-0035 production
policy, unavailable nested namespace capability in the checked backend container,
and an out-of-date formal runtime-profile manifest binding. These regression
checks do not resolve those limitations or constitute product/runtime acceptance.

## Independent Docker diagnostic (DEC-106)

Question: can a fresh, offline Docker container parse bounded document bytes and
be removed after normal completion, CPU exhaustion, OOM, output overflow or a
stalled parse, without changing the existing application containers?

Run from the repository root with the already installed isolated library:

```bash
backend/.venv/bin/python backend/tests/prototypes/docker_extraction_probe.py --library /tmp/thesis-trace-extraction-prototype.H66cBJ/venv/lib/python3.14/site-packages
```

Select `1` for isolation or `2` for all diagnostic cases. Add `--case all` for an
unattended run and `--report <new-path>` for create-only diagnostic JSON. Requires
explicit Docker execution permission, the locally available image pinned inside
the script, and pypdf 6.18.0. There is no image pull or package installation. If
the temporary library has disappeared, stop and provision it through a separately
authorized step; do not silently substitute another parser.

This is deliberately a **one-document/one-container operator experiment**, not a
production client or persistent Compose service. The host operator invokes the
Docker CLI; the parser receives only stdin bytes and emits a bounded diagnostic
result. The collector never receives a Docker socket or Docker-control authority.
The only mounts are two development scripts and the pypdf package, all read-only.
Container settings: no network, UID 65532, all capabilities dropped,
no-new-privileges, default seccomp configuration retained, read-only root, no
container logging, 128 MiB memory and swap-total limit, 8 PIDs, one CPU quota.
The parser additionally uses the existing RLIMIT controls. All numeric settings
are experimental, not approved product budgets or performance acceptance.

The operator caps captured output at 16,384 bytes plus one overflow-detection
byte, distinguishes parser-ready from launcher failure, and allows five seconds
after readiness (ten seconds for launch). Docker control operations each have a
ten-second timeout. Source bytes use an unnamed temporary file that is closed on
return; no document file is committed or written to the diagnostic report.
Cleanup only removes containers carrying the exact per-case random label and
checks that none remain. No broad `prune`, existing-service restart, or database
reset is used. The OOM injection refuses execution outside the selected 128 MiB
diagnostic container.

Scope/ownership: both harnesses remain in the manifest's existing `development`
source set. No production named type, state object, port, dependency or parent
mapping changes. The operator owns temporary input/output and container cleanup;
the disposable child owns parse-local memory. Research retains all durable job,
snapshot and retry authority. No production file imports either harness.

Remaining gaps: persistent Compose IPC, collector admission and response
validation, service restart after faults, concurrency, operator/daemon death,
release-equivalent packaging and native resource calibration are **not** proven.
Fault recovery here means creating a fresh container, not restarting a persistent
parser service. If the operator is forcibly killed or Docker becomes unavailable,
cleanup cannot be guaranteed: inspect the exact `thesis-trace.extraction-prototype`
label and resolve its run before removal. Do not promote this operator-controlled
protocol into production. Synthetic documents only test parsing boundaries and
are never MediaTek financial evidence. ALG-0035 remains proposed.

The local run report is
`build/extraction-prototype/docker-20260910-rCTWE9/report.md`; it separates the
initial 64 MiB failure from the subsequent 128 MiB diagnostic results. Formal
Cloudflare/runtime acceptance, working-bundle policy, and Git status are unchanged.

## Two-container local IPC experiment

The next development-only experiment uses a client with no Docker API access and
a parser supervisor, joined only by a private Unix socket. See
[IPC-DESIGN.md](IPC-DESIGN.md) for ownership, bounds, alternatives and exclusions.

```bash
backend/.venv/bin/python backend/tests/prototypes/run_extraction_ipc_probe.py --library /tmp/thesis-trace-extraction-prototype.H66cBJ/venv/lib/python3.14/site-packages
```

Choose `1` for framed-message faults and recovery, or `2` to compare per-document
container recycling. Noninteractive choices are `--case all`, `--case recycle`,
and `--case adversarial`. `--report <new-path>` keeps a create-only diagnostic
record. The harness creates an exact random Compose project using
`extraction-ipc.compose.yaml`, then removes only that project's containers and
1 MiB tmpfs-backed IPC volume. It does not use the product Compose configuration.
Do not start this file manually as a permanent service: it contains deliberate
fault-injection commands and is not approved for production.

The final run has 46 matching request/recovery observations; a separate six-call
recycling experiment observed six different generations. Earlier setup failures
and the invalid-Unicode failure are retained, not counted as passing runs.
The invalid Unicode reply now returns `protocol_rejected` instead of crashing
the client while printing. Results and limitations are recorded in
`build/extraction-prototype/ipc-20260910-SxVMVa/report.md`.

Ordinary child faults retained the supervisor generation; service OOM changed
the generation and increased Docker's restart count. These are logical recovery
observations, not scheduler/resource calibration. A production protocol, local
native evidence provider/profile and ALG-0035 approval are still pending. No
new demo webpage was created; ADR-0010 requires the actual product UI after its
implementation gates pass.

## Local native enablement (DEC-107)

The Owner selected `perf-ftrace` and renewed SPEC-0001 r103 execution. The separate
[native profile](../../../validation/extraction-native.yaml) and
[boundary design](NATIVE-DESIGN.md) now exist. This is only tool enablement, not
parser resource calibration or final performance assurance. The formal Cloudflare
profile and architecture manifest are unchanged.

The permission-approved non-root probe on 2026-09-10 was blocked by Linux:
`task-clock:u` could not open with `perf_event_paranoid=4`. The native execution
environment has no effective capabilities; tracefs is not readable by this user.
The action exited 2, the governed evaluator reports **BLOCKED**, and cleanup was
confirmed. This is not a parser failure. No administrator capture, sysctl change,
setcap, package installation, Docker run, AI call or database operation occurred.

Local evidence: `.codex/evidence/on-device/native-enablement-20260910-a1/`.
`capture.json` preserves exact argv, exit codes, source/trace hashes and cleanup;
`record.txt` preserves the original permission error; `evaluation/result.json`
is the runner-owned verdict. The zero-byte `perf.data` is not a usable trace.

The three `fixtures/native-enable-*.log` files are **synthetic evaluator tests**,
not runtime evidence. Their expected PASS / FAIL / BLOCKED results are kept under
`build/extraction-prototype/native-validator-20260910/` and must never be supplied
as real acceptance prerequisites. Host-only command-boundary tests run with:

```bash
python3 -m pytest -q backend/tests/prototypes/test_native_extraction_probe.py
```

Capture output directories are create-only. Do not rerun the fixed `a1` action,
erase the failed run, or change its bound profile snapshot. A future approved run
needs a fresh reviewed action/profile snapshot with a distinct output path.
Administrator tracing requires separate explicit permission and a scoped command;
do not run the complete project or test helper as root. A sudo policy query alone
does not authorize or prove successful privileged capture. Keep test wiring out
of release. Operator hard-kill/host failure recovery is not established here.

### Approved administrator capability retry

The Owner subsequently approved **one** bounded administrator perf capture.
The ordinary-user `native_admin_probe.py` wrapper invoked only installed
timeout/prlimit/perf binaries through sudo. The fixed 0.2-second workload was
dropped to UID/GID 1000 with empty capability sets and no-new-privileges;
neither the application nor this repository's helper ran as root.

The separate `validation/extraction-native-admin.yaml` profile's enablement run
passed. Evidence lives at
`.codex/evidence/on-device/native-admin-enablement-20260910-a1/`:
8,412-byte raw trace, 20 user-space task-clock samples, native workload EXIT record,
ordinary-user exports, confirmed supervisor-group cleanup and runner PASS.
No lost-record marker was observed in the bounded raw export; this is not a
quantitative loss/resource assurance claim. `perf_event_paranoid` stayed 4 and
the perf executable gained no file capabilities. The original denied run remains.

The single administrator capture authorization is consumed. Do not rerun this
create-only profile or infer authorization for container/system-wide tracing.
Actual parser-container CPU/memory/lifecycle scenarios, their scoped capture
permissions and resource/sample contracts remain outstanding. This toolchain
enablement PASS is not parser acceptance, ALG-0035 approval or SPEC completion.
See `build/extraction-prototype/native-admin-validator-20260910/report.md`.

### Parser-container selector preflight

[CONTAINER-RESOURCE-PLAN.md](CONTAINER-RESOURCE-PLAN.md) records the next bounded
resource-diagnostic batch and its still-pending native permission. To check only
the offline container identities and readable kernel counter files:

```bash
python3 backend/tests/prototypes/container_resource_preflight.py --library /tmp/thesis-trace-extraction-prototype.H66cBJ/venv/lib/python3.14/site-packages --report build/extraction-prototype/container-resource-preflight-20260910/new-run.json
```

Choose `1`, or add `--run` for the same noninteractive check. The report path must
be new and its parent directory must exist. This command never invokes perf/sudo,
downloads packages/images or sends parsing/fault requests. It starts only a unique
two-service offline project, checks exact container/PID/start-time/cgroup identity
and the existing resource controls, reads bounded kernel-file snapshots, then
removes only its containers and ephemeral IPC volume. No production data changes.

The first 2026-09-10 preflight completed with all 11 selected kernel files readable
for each service and verified project cleanup. Report:
`build/extraction-prototype/container-resource-preflight-20260910/first.json`.
Its PIDs are historical and already exited: never feed them to perf. A future
capture must resolve and revalidate a fresh identity immediately before use.
Counter availability/configuration is not CPU/memory acceptance, and cgroup memory
accounting must not be labeled process RSS. Seventeen existing regression tests
and the development architecture gate passed; no new native capture ran.
