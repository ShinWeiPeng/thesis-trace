"""One explicitly approved, fixed administrator perf capability capture only."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from native_extraction_probe import run_bounded


def capture_argv() -> list[str]:
    return [
        "/usr/bin/sudo",
        "-n",
        "/usr/bin/timeout",
        "--signal=INT",
        "--kill-after=1s",
        "5s",
        "/usr/bin/prlimit",
        "--fsize=1048576:1048576",
        "--",
        "/usr/bin/perf",
        "record",
        "--no-buildid",
        "--no-buildid-cache",
        "--no-buildid-mmap",
        "--no-bpf-event",
        "--clockid",
        "mono",
        "--max-size",
        "1M",
        "-m",
        "8",
        "-F",
        "99",
        "-e",
        "task-clock:u",
        "-o",
        "-",
        "--",
        "/usr/bin/setpriv",
        "--reuid=1000",
        "--regid=1000",
        "--clear-groups",
        "--bounding-set=-all",
        "--inh-caps=-all",
        "--ambient-caps=-all",
        "--no-new-privs",
        "/usr/bin/python3",
        "-I",
        "-c",
        "import os,time; assert os.getuid()==os.geteuid()==1000; "
        "end=time.monotonic()+0.2\nwhile time.monotonic()<end: pass",
    ]


def capture(output: Path) -> int:
    if os.getuid() != 1000 or os.geteuid() != 1000:
        raise RuntimeError("operator wrapper must run as ordinary UID 1000, not root")
    output.mkdir(parents=True, exist_ok=False)
    run_id = uuid.uuid4().hex
    start = time.monotonic()
    events = [
        f"VAL_SESSION_BEGIN run={run_id} scenario=local-native-enablement observer=gpt t_ms=0 seq=1"
    ]

    def event(name: str) -> None:
        events.append(
            f"VAL_EVENT name={name} t_ms={int((time.monotonic() - start) * 1000)} seq={len(events) + 1}"
        )

    event("capture_requested")
    argv = capture_argv()
    trace = output / "perf.data"
    with trace.open("xb") as data, (output / "record.txt").open("xb") as errors:
        command = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=data,
            stderr=errors,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            start_new_session=True,
        )
        try:
            command.wait(timeout=8)
            timed_out = False
        except subprocess.TimeoutExpired:
            # Do not signal privileged or unrelated processes from the user wrapper.
            # The separately privileged timeout is the termination authority.
            timed_out = True
    try:
        os.killpg(command.pid, 0)
        cleanup = False
    except ProcessLookupError:
        cleanup = True
    except PermissionError:
        cleanup = False
    record = {
        "argv": argv,
        "exit_code": command.returncode,
        "timed_out": timed_out,
        "cleanup_confirmed": cleanup,
        "supervisor_pid": command.pid,
    }
    ready = (
        command.returncode == 0
        and not timed_out
        and cleanup
        and 0 < trace.stat().st_size < 1048576
        and (output / "record.txt").stat().st_size < 65536
    )
    export = None
    if ready:
        event("native_recorded")
        export = run_bounded(
            ["/usr/bin/perf", "script", "--ns", "-i", str(trace)],
            output / "export.txt",
            5,
        )
        ready = (
            export["exit_code"] == 0
            and not export["timed_out"]
            and not export["output_exceeded"]
            and export["cleanup_confirmed"]
            and "task-clock:u:" in export["output"]
        )
        cleanup = cleanup and export["cleanup_confirmed"]
        if ready:
            event("native_exported")
    if cleanup:
        event("cleanup_confirmed")
    elapsed = int((time.monotonic() - start) * 1000)
    events.append(
        f"VAL_SESSION_END run={run_id} reason={'complete' if ready else 'blocked'} records={len(events) + 1} dropped=0 duration_ms={elapsed} t_ms={elapsed} seq={len(events) + 1}"
    )
    (output / "events.log").write_text("\n".join(events) + "\n", encoding="utf-8")
    report = {
        "run_id": run_id,
        "scope": "native-tool-enablement-only",
        "capture_ready": ready,
        "cleanup_confirmed": cleanup,
        "record": record,
        "export": export,
        "permission": {
            "actor": "Owner",
            "answer": "允許。",
            "scope": "one bounded administrator perf capture; no sysctl/setcap/permanent privileges",
        },
        "operator_uid": os.getuid(),
        "workload_uid": 1000,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
        "trace_bytes": trace.stat().st_size,
        "perf_event_paranoid": Path("/proc/sys/kernel/perf_event_paranoid")
        .read_text()
        .strip(),
    }
    (output / "capture.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "run_id": run_id,
                "capture_ready": ready,
                "cleanup_confirmed": cleanup,
                "output": str(output),
            }
        )
    )
    return 0 if ready and cleanup else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("capture", "cleanup-check"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    output = args.output.resolve()
    if not output.is_relative_to(root / ".codex/evidence/on-device"):
        parser.error("output must be within the local native evidence directory")
    if args.operation == "cleanup-check":
        report = json.loads((output / "capture.json").read_text())
        return 0 if report.get("cleanup_confirmed") is True else 2
    return capture(output)


if __name__ == "__main__":
    raise SystemExit(main())
