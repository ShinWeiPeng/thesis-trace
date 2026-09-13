"""Throwaway container identity/counter preflight. Never executes perf or sudo."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

from docker_extraction_probe import IMAGE
from run_extraction_ipc_probe import call


def snapshot(container: dict, project: str) -> dict:
    container_id = container["Id"]
    if not re.fullmatch(r"[0-9a-f]{64}", container_id):
        raise RuntimeError("invalid full container identity")
    config = container["Config"]
    settings = container["HostConfig"]
    if (
        config["Labels"]["com.docker.compose.project"] != project
        or container["Image"] != IMAGE
        or config["User"] != "65532:65532"
        or settings["NetworkMode"] != "none"
        or not settings["ReadonlyRootfs"]
        or settings["Privileged"]
        or settings["CapDrop"] != ["ALL"]
        or settings["SecurityOpt"] != ["no-new-privileges:true"]
        or settings["Memory"] != 134217728
        or settings["MemorySwap"] != 134217728
        or settings["PidsLimit"] != 16
        or settings["NanoCpus"] != 1000000000
    ):
        raise RuntimeError("unexpected diagnostic container settings")
    pid = container["State"]["Pid"]
    if not container["State"]["Running"] or type(pid) is not int or pid <= 1:
        raise RuntimeError("container is not running with a valid PID")
    proc = Path("/proc") / str(pid)
    membership = (proc / "cgroup").read_text().strip()
    expected = f"0::/system.slice/docker-{container_id}.scope"
    if membership != expected:
        raise RuntimeError("PID cgroup does not match the exact new Docker scope")
    group = Path("/sys/fs/cgroup") / membership.removeprefix("0::/")
    counters = {}
    for name in (
        "cgroup.procs",
        "cgroup.events",
        "memory.current",
        "memory.peak",
        "memory.max",
        "memory.swap.max",
        "memory.events.local",
        "pids.current",
        "pids.max",
        "cpu.stat",
        "cpu.max",
    ):
        try:
            with (group / name).open("rb") as stream:
                content = stream.read(4097)
            if len(content) > 4096:
                raise RuntimeError("counter file exceeded preflight size bound")
            counters[name] = {"raw": content.decode("ascii"), "available": True}
        except (FileNotFoundError, PermissionError) as error:
            counters[name] = {"available": False, "error": type(error).__name__}
    if not counters["cgroup.procs"]["available"]:
        raise RuntimeError("exact cgroup process inventory unavailable")
    pids = sorted(set(int(p) for p in counters["cgroup.procs"]["raw"].split()))
    if pid not in pids or not 1 <= len(pids) <= 16:
        raise RuntimeError("unexpected process inventory")
    processes = []
    for member in pids:
        path = Path("/proc") / str(member)
        stat = (path / "stat").read_text()
        tail = stat.rsplit(")", 1)[1].split()
        if (path / "cgroup").read_text().strip() != expected:
            raise RuntimeError("process identity changed during preflight")
        processes.append(
            {
                "pid": member,
                "comm": (path / "comm").read_text().strip(),
                "ppid": int(tail[1]),
                "start_ticks": int(tail[19]),
            }
        )
    return {
        "service": config["Labels"]["com.docker.compose.service"],
        "container_id": container_id,
        "init_pid": pid,
        "cgroup": str(group),
        "processes": processes,
        "counters": counters,
        "settings_checked": True,
        "monotonic_ns": time.monotonic_ns(),
    }


def run(library: Path, report: Path) -> bool:
    root = Path(__file__).resolve().parent
    project = "tt-resource-preflight-" + uuid.uuid4().hex[:16]
    env = {
        "PATH": os.environ["PATH"],
        "TT_IPC_ROOT": str(root),
        "TT_IPC_LIBRARY": str(library),
        "TT_IPC_RECYCLE": "no",
    }
    compose = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-p",
        project,
        "-f",
        str(root / "extraction-ipc.compose.yaml"),
    ]
    selected = f"label=com.docker.compose.project={project}"
    inventory = [
        ["docker", "ps", "-aq", "--filter", selected],
        ["docker", "volume", "ls", "-q", "--filter", selected],
    ]
    for command in inventory:
        if call(command, env).strip():
            raise RuntimeError("refuse reusing a project")
    result = {
        "prototype_only": True,
        "native_capture_executed": False,
        "resource_acceptance": "NOT_RUN",
        "project": project,
        "image": IMAGE,
        "snapshots": [],
        "cleanup_verified": False,
        "error": None,
        "files": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (
                Path(__file__),
                root / "extraction-ipc.compose.yaml",
                root / "extraction_ipc_probe.py",
            )
        },
    }
    try:
        call([*compose, "config", "--quiet"], env)
        call([*compose, "up", "-d", "--no-build", "--pull", "never"], env)
        ids = call([*compose, "ps", "-aq"], env).decode().split()
        if len(ids) != 2 or not all(re.fullmatch(r"[0-9a-f]{64}", i) for i in ids):
            raise RuntimeError("expected exactly two diagnostic services")
        # Startup can momentarily have only init. Wait within a bounded window
        # for both init and the pre-existing supervisor, without sending work.
        deadline = time.monotonic() + 10
        while True:
            values = json.loads(call(["docker", "inspect", *ids], env))
            snapshots = [snapshot(c, project) for c in values]
            if all(len(s["processes"]) >= 2 for s in snapshots):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("supervisor identity was not observable")
            time.sleep(0.1)
        result["snapshots"] = snapshots
        result["counter_files_available"] = all(
            c["available"] for s in snapshots for c in s["counters"].values()
        )
        if not result["counter_files_available"]:
            raise RuntimeError("required counter file unavailable")
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {str(error)[:300]}"
    finally:
        try:
            call([*compose, "down", "--volumes", "--timeout", "2"], env)
            result["cleanup_verified"] = all(
                not call(c, env).strip() for c in inventory
            )
        except Exception as error:
            result["cleanup_error"] = f"{type(error).__name__}: {str(error)[:300]}"
        with report.open("x", encoding="utf-8") as output:
            json.dump(result, output, indent=2)
    ok = result["error"] is None and result["cleanup_verified"]
    print(
        json.dumps(
            {
                "preflight_complete": ok,
                "native_capture_executed": False,
                "cleanup_verified": result["cleanup_verified"],
                "report": str(report),
                "error": result["error"],
            }
        )
    )
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    library = args.library.resolve(strict=True)
    if not (library / "pypdf/__init__.py").is_file():
        parser.error("existing isolated pypdf installation is required")
    if args.report.exists() or not args.report.parent.is_dir():
        parser.error("report must be a new file in an existing local directory")
    if (
        not args.run
        and input("PROTOTYPE: [1] offline identity preflight [q] quit: ") != "1"
    ):
        return
    raise SystemExit(0 if run(library, args.report) else 2)


if __name__ == "__main__":
    main()
