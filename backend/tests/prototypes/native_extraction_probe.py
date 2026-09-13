"""Development-only, process-scoped native capture capability checkpoint."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid


def run_bounded(argv: list[str], output: Path, timeout: float) -> dict:
    """Run an explicit command, retain bounded output, and reap its own group."""
    started = time.monotonic()
    with output.open("xb") as stream:
        process = subprocess.Popen(
            ["prlimit", "--fsize=1048576:1048576", "--", *argv],
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            start_new_session=True,
        )
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(process.pid, sig)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            process.wait(timeout=2)
    try:
        os.killpg(process.pid, 0)
        cleanup = False
    except ProcessLookupError:
        cleanup = True
    with output.open("rb") as stream:
        captured = stream.read(65537)
    return {
        "argv": argv,
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "output_exceeded": len(captured) > 65536,
        "output": captured[:65536].decode("utf-8", errors="replace"),
        "cleanup_confirmed": cleanup,
        "elapsed_seconds": time.monotonic() - started,
    }


def capture(output: Path) -> int:
    output.mkdir(parents=True, exist_ok=False)
    run_id = uuid.uuid4().hex
    started = time.monotonic()
    events = [
        f"VAL_SESSION_BEGIN run={run_id} scenario=local-native-enablement "
        "observer=gpt t_ms=0 seq=1",
        "VAL_EVENT name=capture_requested t_ms=0 seq=2",
    ]

    def event(name: str) -> None:
        events.append(
            f"VAL_EVENT name={name} t_ms={int((time.monotonic() - started) * 1000)} "
            f"seq={len(events) + 1}"
        )

    trace = output / "perf.data"
    workload = "import time; end=time.monotonic()+0.2\nwhile time.monotonic()<end: pass"
    record = run_bounded(
        [
            "perf",
            "record",
            "--no-buildid",
            "--no-buildid-cache",
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
            str(trace),
            "--",
            "python3",
            "-I",
            "-c",
            workload,
        ],
        output / "record.txt",
        5,
    )

    def succeeded(result: dict) -> bool:
        return (
            result["exit_code"] == 0
            and not result["timed_out"]
            and not result["output_exceeded"]
            and result["cleanup_confirmed"]
        )

    export = None
    ready = succeeded(record) and trace.is_file() and 0 < trace.stat().st_size < 1048576
    if ready:
        event("native_recorded")
        export = run_bounded(
            ["perf", "script", "--ns", "-i", str(trace)], output / "export.txt", 5
        )
        ready = succeeded(export) and bool(export["output"].strip())
        if ready:
            event("native_exported")
    cleanup = record["cleanup_confirmed"] and (
        export is None or export["cleanup_confirmed"]
    )
    if cleanup:
        event("cleanup_confirmed")
    events.append(
        f"VAL_SESSION_END run={run_id} reason={'complete' if ready else 'blocked'} "
        f"records={len(events) + 1} dropped=0 "
        f"duration_ms={int((time.monotonic() - started) * 1000)} "
        f"t_ms={int((time.monotonic() - started) * 1000)} seq={len(events) + 1}"
    )
    (output / "events.log").write_text("\n".join(events) + "\n", encoding="utf-8")
    report = {
        "run_id": run_id,
        "scope": "native-tool-enablement-only",
        "capture_ready": ready,
        "cleanup_confirmed": cleanup,
        "record": record,
        "export": export,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest()
        if trace.exists()
        else None,
        "native_permission": "explicit-native-tool-approval-required",
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
        parser.error(
            "output must be under the project's local native evidence directory"
        )
    if args.operation == "cleanup-check":
        report = json.loads((output / "capture.json").read_text())
        return 0 if report.get("cleanup_confirmed") is True else 2
    return capture(output)


if __name__ == "__main__":
    raise SystemExit(main())
