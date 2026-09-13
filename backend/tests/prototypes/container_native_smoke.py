"""Eight-attempt offline container diagnostic batch; no product acceptance claim."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from container_native_capture import capture
from container_resource_preflight import snapshot
from docker_extraction_probe import IMAGE, text_pdf


def matches_response(value: dict, kind: str, expected: str, content: bytes) -> bool:
    if value.get("status") != expected or value.get("client_isolation") != {
        "status": "isolated",
        "uid": 65532,
        "docker_socket_absent": True,
        "secrets_absent": True,
        "interfaces": ["lo"],
    }:
        return False
    if expected != "readable":
        return True
    result = value.get("result", {})
    text = "SYNTHETIC text page" if kind == "pdf-plain" else "Visible evidence"
    return (
        value.get("sha256") == hashlib.sha256(content).hexdigest()
        and result.get("document_verified") is False
        and [f.get("text") for f in result.get("fragments", [])] == [text]
        and (
            kind != "pdf-plain"
            or (
                result.get("pages_without_text") == [2]
                and result.get("selection_incomplete") is True
            )
        )
    )


def run(output: Path, library: Path) -> int:
    if os.getuid() != 1000 or os.geteuid() != 1000:
        raise RuntimeError("operator must remain UID 1000")
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    root = Path(__file__).resolve().parent
    run_id = uuid.uuid4().hex
    project = "tt-native-smoke-" + run_id[:16]
    env = {
        "PATH": "/usr/bin:/bin",
        "LC_ALL": "C",
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
    inventory = [
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ],
        [
            "docker",
            "volume",
            "ls",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ],
    ]
    start = time.monotonic()
    deadline = start + 300
    events = [
        f"VAL_SESSION_BEGIN run={run_id} scenario=container-native-smoke observer=gpt t_ms=0 seq=1"
    ]
    result = {
        "run_id": run_id,
        "project": project,
        "image": IMAGE,
        "records": [],
        "attempts": 0,
        "cleanup_verified": False,
        "error": None,
        "scope": "diagnostic-smoke-only; no resource or release acceptance",
        "permission": "Owner 允許: at most 8 captures, <=15s each including kill grace; <=300s batch; <=32MiB raw",
        "source_hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (
                Path(__file__),
                root / "container_native_capture.py",
                root / "container_resource_preflight.py",
                root / "extraction_ipc_probe.py",
                root / "source_extraction_probe.py",
                root / "extraction-ipc.compose.yaml",
            )
        },
    }

    def event(name):
        events.append(
            f"VAL_EVENT name={name} t_ms={int((time.monotonic() - start) * 1000)} seq={len(events) + 1}"
        )

    def call(argv, timeout=8, cleanup=False):
        remaining = deadline - time.monotonic() - (0 if cleanup else 35)
        if remaining <= 0:
            raise RuntimeError("batch deadline reserve reached")
        completed = subprocess.run(
            argv, env=env, capture_output=True, timeout=min(timeout, remaining)
        )
        if completed.returncode:
            raise RuntimeError(completed.stderr.decode(errors="replace")[:300])
        return completed.stdout

    def parser_state(container_id):
        value = json.loads(call(["docker", "inspect", container_id]))[0]
        identity = snapshot(value, project)
        if len(identity["processes"]) < 2:
            raise RuntimeError("supervisor not yet observable")
        return value

    created = False
    try:
        event("batch_requested")
        for command in inventory:
            if call(command).strip():
                raise RuntimeError("refuse existing project")
        call([*compose, "config", "--quiet"])
        created = True
        call([*compose, "up", "-d", "--no-build", "--pull", "never"], timeout=20)
        ids = call([*compose, "ps", "-aq"]).decode().split()
        if len(ids) != 2 or not all(re.fullmatch("[0-9a-f]{64}", i) for i in ids):
            raise RuntimeError("expected exactly two new containers")
        containers = json.loads(call(["docker", "inspect", *ids]))
        for value in containers:
            snapshot(value, project)
            service = value["Config"]["Labels"]["com.docker.compose.service"]
            allowed = {"/ipc-probe.py", "/ipc"} | (
                {"/probe.py", "/library/pypdf"} if service == "parser" else set()
            )
            if {m["Destination"] for m in value["Mounts"]} != allowed or any(
                m["RW"]
                for m in value["Mounts"]
                if m["Type"] == "bind" or service == "client"
            ):
                raise RuntimeError("unexpected mounts")
        parser_id = next(
            c["Id"]
            for c in containers
            if c["Config"]["Labels"]["com.docker.compose.service"] == "parser"
        )
        volumes = call(inventory[1]).decode().split()
        volume = json.loads(call(["docker", "volume", "inspect", *volumes]))
        if len(volume) != 1 or volume[0]["Options"] != {
            "type": "tmpfs",
            "device": "tmpfs",
            "o": "size=1048576,uid=65532,gid=65532,mode=0770",
        }:
            raise RuntimeError("unexpected IPC volume")
        sys.path.insert(0, str(library))
        cases = [
            ("html", "readable", b"<p>Visible evidence</p>"),
            ("pdf-plain", "readable", text_pdf()),
            ("memory", "memory_limit", b""),
            ("cpu", "child_terminated", b""),
            ("wall", "wall_limit", b""),
            ("output", "output_limit", b""),
            ("service-oom", "unavailable", b""),
            ("html", "readable", b"<p>Visible evidence</p>"),
        ]
        generation = None
        prior_init = None
        for index, (kind, expected, content) in enumerate(cases, 1):
            if result["attempts"] >= 8 or time.monotonic() + 35 >= deadline - 35:
                raise RuntimeError("capture budget exhausted")
            readiness_end = time.monotonic() + 5
            while True:
                try:
                    container = parser_state(parser_id)
                    if index == 8 and container["State"]["Pid"] == prior_init:
                        raise RuntimeError("waiting for new parser generation")
                    break
                except (RuntimeError, OSError):
                    if time.monotonic() >= readiness_end:
                        raise
                    time.sleep(0.1)
            result["attempts"] += 1  # Failed launches consume an attempt too.
            workload = [
                *compose,
                "exec",
                "-T",
                "client",
                "python",
                "-I",
                "-B",
                "/ipc-probe.py",
                "--client",
                kind,
            ]
            record = capture(
                output / f"{index:02d}-{kind}",
                container,
                project,
                run_id,
                workload,
                env,
                content,
            )
            record["case"] = kind
            record["expected"] = expected
            record["matches_expected"] = matches_response(
                record["response"] or {}, kind, expected, content
            )
            result["records"].append(record)
            print(
                json.dumps(
                    {
                        "attempt": index,
                        "case": kind,
                        "native_ready": record["ready"],
                        "matches_expected": record["matches_expected"],
                        "error": record["error"],
                    }
                ),
                flush=True,
            )
            if (
                not record["ready"]
                or not record["cleanup"]
                or not record["matches_expected"]
            ):
                raise RuntimeError("diagnostic case incomplete; no recapture")
            response = record["response"]
            if index < 7:
                if generation and response.get("generation") != generation:
                    raise RuntimeError("unexpected supervisor replacement")
                generation = response.get("generation")
                if not record.get("after"):
                    raise RuntimeError("survivor identity missing")
            if index == 7:
                prior_init = container["State"]["Pid"]
            if index == 8:
                if (
                    response.get("generation") == generation
                    or container["RestartCount"] < 1
                ):
                    raise RuntimeError("recovery generation not proven")
            event(f"case_{index}_covered")
        event("diagnostics_covered")
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {str(error)[:300]}"
    finally:
        try:
            if created:
                call(
                    [*compose, "down", "--volumes", "--timeout", "2"],
                    timeout=15,
                    cleanup=True,
                )
            result["cleanup_verified"] = all(
                not call(c, cleanup=True).strip() for c in inventory
            ) and all(r["cleanup"] for r in result["records"])
            if result["cleanup_verified"]:
                event("cleanup_confirmed")
        except Exception as error:
            result["cleanup_error"] = str(error)[:300]
        result["elapsed_seconds"] = time.monotonic() - start
        result["raw_trace_bytes"] = sum(
            p.stat().st_size for p in output.glob("*/perf.data")
        )
        result["complete"] = (
            result["error"] is None
            and result["cleanup_verified"]
            and result["attempts"] == 8
        )
        elapsed = int(result["elapsed_seconds"] * 1000)
        reason = "complete" if result["complete"] else "blocked"
        events.append(
            f"VAL_SESSION_END run={run_id} reason={reason} records={len(events) + 1} dropped=0 duration_ms={elapsed} t_ms={elapsed} seq={len(events) + 1}"
        )
        (output / "events.log").write_text("\n".join(events) + "\n")
        (output / "batch.json").write_text(json.dumps(result, indent=2) + "\n")
        print(
            json.dumps(
                {
                    k: result[k]
                    for k in (
                        "run_id",
                        "attempts",
                        "complete",
                        "cleanup_verified",
                        "elapsed_seconds",
                        "raw_trace_bytes",
                        "error",
                    )
                }
            ),
            flush=True,
        )
    return 0 if result["complete"] else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("run", "cleanup-check"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--library", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    output = args.output.resolve()
    if not output.is_relative_to(root / ".codex/evidence/on-device"):
        parser.error("output must be under local native evidence")
    if args.operation == "cleanup-check":
        return (
            0
            if json.loads((output / "batch.json").read_text()).get("cleanup_verified")
            is True
            else 2
        )
    if not args.library or not (args.library / "pypdf/__init__.py").is_file():
        parser.error("existing pypdf library is required; never install implicitly")
    return run(output, args.library.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
