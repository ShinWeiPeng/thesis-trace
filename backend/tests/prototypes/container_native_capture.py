"""Test-only, one bounded PID-scoped perf capture; never run this module as root."""

import hashlib
import json
import os
from pathlib import Path
import re
import select
import subprocess
import time

from container_resource_preflight import snapshot


def valid_enable_ack(value: bytes) -> bool:
    # The installed perf 7.0.14 writes the C string terminator too. Accept the
    # documented line and this observed encoding, not arbitrary trailing bytes.
    return value in (b"ack\n", b"ack\n\x00")


def capture_argv(pids: list[int], directory: Path) -> list[str]:
    if not pids or len(pids) > 16 or any(type(p) is not int or p <= 1 for p in pids):
        raise ValueError("invalid scoped process list")
    return [
        "/usr/bin/sudo",
        "-n",
        "/usr/bin/timeout",
        "--signal=INT",
        "--kill-after=1s",
        "14s",
        "/usr/bin/prlimit",
        "--fsize=4194304:4194304",
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
        "4M",
        "-m",
        "8",
        "-F",
        "99",
        "-e",
        "task-clock:u",
        "-s",
        "-p",
        ",".join(map(str, sorted(set(pids)))),
        "-D",
        "-1",
        f"--control=fifo:{directory / 'ctl'},{directory / 'ack'}",
        "-o",
        "-",
    ]


def group_gone(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def export_trace(trace: Path, target: Path, raw: bool) -> dict:
    argv = [
        "/usr/bin/prlimit",
        "--fsize=4194304:4194304",
        "--",
        "/usr/bin/perf",
        "script",
        "--ns",
        "-i",
        str(trace),
    ]
    if raw:
        argv.append("-D")
    with target.open("xb") as output:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "DEBUGINFOD_URLS": ""},
            start_new_session=True,
        )
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, 9)  # Our ordinary-user export group only.
            process.wait(timeout=1)
    text = target.read_text(errors="replace")
    return {
        "argv": argv,
        "exit_code": process.returncode,
        "complete": process.returncode == 0 and 0 < target.stat().st_size < 4194304,
        "cleanup": group_gone(process.pid),
        "lost_records": bool(
            re.search(r"PERF_RECORD_LOST|LOST_SAMPLES|lost [1-9][0-9]*", text)
        ),
        "exit_records": text.count("PERF_RECORD_EXIT"),
        "fork_records": text.count("PERF_RECORD_FORK"),
        "task_clock_samples": text.count("task-clock:u:"),
    }


def capture(
    directory: Path,
    container: dict,
    project: str,
    run_id: str,
    workload: list[str],
    env: dict,
    content: bytes,
) -> dict:
    if os.getuid() != 1000 or os.geteuid() != 1000:
        raise RuntimeError("operator must remain ordinary UID 1000")
    directory.mkdir(mode=0o700)
    result = {
        "run_id": run_id,
        "ready": False,
        "cleanup": False,
        "error": None,
        "response": None,
    }
    descriptors = []
    process = None
    try:
        for name in ("ctl", "ack"):
            os.mkfifo(directory / name, mode=0o600)
            descriptors.append(os.open(directory / name, os.O_RDWR | os.O_NONBLOCK))
        before = snapshot(container, project)
        # Recheck every existing process/start tick immediately before attachment.
        verified = snapshot(container, project)
        if before["processes"] != verified["processes"] or len(before["processes"]) < 2:
            raise RuntimeError("scoped process identity changed before attachment")
        result["before"] = verified
        argv = capture_argv([p["pid"] for p in verified["processes"]], directory)
        result["argv"] = argv
        started = time.monotonic()
        result["record_start_ns"] = time.monotonic_ns()
        with (
            (directory / "perf.data").open("xb") as data,
            (directory / "record.txt").open("xb") as errors,
        ):
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=data,
                stderr=errors,
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "DEBUGINFOD_URLS": ""},
                start_new_session=True,
            )
            try:
                os.write(descriptors[0], b"enable\n")
                if not select.select([descriptors[1]], [], [], 3)[0]:
                    raise RuntimeError("native enable acknowledgement missing")
                ack = os.read(descriptors[1], 128)
                result["enable_ack"] = ack.decode(errors="replace")
                if not valid_enable_ack(ack) or process.poll() is not None:
                    raise RuntimeError("native collector not ready")
                result["workload_start_ns"] = time.monotonic_ns()
                with (
                    (directory / "response.json").open("xb") as response,
                    (directory / "client.txt").open("xb") as client_errors,
                ):
                    completed = subprocess.run(
                        workload,
                        env=env,
                        input=content,
                        stdout=response,
                        stderr=client_errors,
                        timeout=8,
                    )
                result["workload_end_ns"] = time.monotonic_ns()
                result["workload_exit"] = completed.returncode
                if (
                    completed.returncode != 0
                    or (directory / "response.json").stat().st_size > 65536
                ):
                    raise RuntimeError("workload response unavailable or oversized")
                result["response"] = json.loads(
                    (directory / "response.json").read_bytes()
                )
                try:
                    after = snapshot(container, project)
                    if (
                        after["init_pid"] != before["init_pid"]
                        or after["processes"] != before["processes"]
                    ):
                        raise RuntimeError(
                            "original container process generation no longer available"
                        )
                    result["after"] = after
                except (OSError, RuntimeError) as error:
                    result["after_unavailable"] = str(error)[:250]
            finally:
                # The root watchdog is the cleanup authority even after exceptions.
                os.write(descriptors[0], b"stop\n")
                process.wait(timeout=max(0.1, 15 - (time.monotonic() - started)))
        result["record_end_ns"] = time.monotonic_ns()
        result["record_exit"] = process.returncode
        result["cleanup"] = group_gone(process.pid)
        trace = directory / "perf.data"
        result["trace_bytes"] = trace.stat().st_size
        result["trace_sha256"] = hashlib.sha256(trace.read_bytes()).hexdigest()
        if (
            process.returncode != 0
            or not result["cleanup"]
            or not 0 < trace.stat().st_size < 4194304
        ):
            raise RuntimeError("native recording incomplete or watchdog expired")
        result["export"] = export_trace(trace, directory / "export.txt", False)
        result["raw_export"] = export_trace(trace, directory / "raw-export.txt", True)
        result["cleanup"] = result["cleanup"] and all(
            result[k]["cleanup"] for k in ("export", "raw_export")
        )
        result["ready"] = (
            result["cleanup"]
            and all(
                result[k]["complete"] and not result[k]["lost_records"]
                for k in ("export", "raw_export")
            )
            and result["raw_export"]["exit_records"] > 0
        )
        if not result["ready"]:
            raise RuntimeError("native export/lifecycle/loss coverage incomplete")
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {str(error)[:300]}"
    finally:
        if process is not None:
            result["cleanup"] = group_gone(process.pid) and all(
                result[k]["cleanup"] for k in ("export", "raw_export") if k in result
            )
        else:
            result["cleanup"] = True
        for descriptor in descriptors:
            os.close(descriptor)
        for name in ("ctl", "ack"):
            path = directory / name
            if path.exists():
                path.unlink()  # Only this capture's owned named pipes, never evidence.
        with (directory / "capture.json").open("x") as report:
            json.dump(result, report, indent=2)
    return result
