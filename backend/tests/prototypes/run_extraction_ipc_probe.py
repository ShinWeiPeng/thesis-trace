"""THROWAWAY operator harness: two offline containers, no product/DB integration.

See IPC-DESIGN.md. Creates only its random Compose project and cleans it on exit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from docker_extraction_probe import IMAGE, text_pdf


def call(argv: list[str], env: dict, content: bytes | None = None) -> bytes:
    completed = subprocess.run(
        argv,
        env=env,
        input=content,
        capture_output=True,
        check=False,
        timeout=40,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.decode(errors="replace")[:1500])
    return completed.stdout


def run(
    library: Path, recycle: bool, report: Path | None, adversarial: bool = False
) -> bool:
    root = Path(__file__).resolve().parent
    project = "tt-ipc-probe-" + uuid.uuid4().hex[:16]
    env = {
        "PATH": os.environ["PATH"],
        "TT_IPC_ROOT": str(root),
        "TT_IPC_LIBRARY": str(library),
        "TT_IPC_RECYCLE": "yes" if recycle else "no",
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
    project_filter = f"label=com.docker.compose.project={project}"
    for command in (
        ["docker", "ps", "-aq", "--filter", project_filter],
        ["docker", "volume", "ls", "-q", "--filter", project_filter],
    ):
        if call(command, env).strip():
            raise RuntimeError("refuse reusing a Compose project")
    healthy = b"<p>Visible evidence</p>"
    fixtures = [("html", healthy, None, "readable")]
    if recycle:
        fixtures *= 6
    elif adversarial:
        fixtures += [
            (kind, healthy, None, "protocol_rejected")
            for kind in ("bad-utf8", "nested-json", "surrogate-text")
        ]
    else:
        fixtures += [
            ("isolation", b"", None, "isolated"),
            ("html", healthy, "fragmented", "readable"),
            ("pdf-plain", text_pdf(), None, "readable"),
            ("html", b"<p>\xff</p>", None, "invalid_encoding"),
            ("html", b"x" * 2_000_001, None, "input_limit"),
            ("html", healthy, "oversize-header", "unavailable"),
            ("html", healthy, "duplicate-key", "unavailable"),
            ("html", healthy, "partial", "unavailable"),
            ("html", healthy, "wrong-input-hash", "unavailable"),
            ("html", healthy, "trailing-input", "unavailable"),
            ("wrong-id", healthy, None, "protocol_rejected"),
            ("wrong-hash", healthy, None, "protocol_rejected"),
            ("bad-json", healthy, None, "protocol_rejected"),
            ("bad-utf8", healthy, None, "protocol_rejected"),
            ("nested-json", healthy, None, "protocol_rejected"),
            ("surrogate-text", healthy, None, "protocol_rejected"),
            ("oversize-reply", healthy, None, "protocol_rejected"),
            ("false-verified", healthy, None, "protocol_rejected"),
            ("late-reply", healthy, None, "attempt_timeout"),
            ("memory", b"", None, "memory_limit"),
            ("cpu", b"", None, "child_terminated"),
            ("wall", b"", None, "wall_limit"),
            ("output", b"", None, "output_limit"),
            ("service-oom", b"", None, "unavailable"),
        ]
    records, settings = [], []
    cleanup = False
    failure = None
    try:
        call([*compose, "config", "--quiet"], env)
        call([*compose, "up", "-d", "--no-build", "--pull", "never"], env)
        ids = call([*compose, "ps", "-aq"], env).decode().split()
        if len(ids) != 2:
            raise RuntimeError("expected exactly the two diagnostic services")
        for container in json.loads(call(["docker", "inspect", *ids], env)):
            config = container["HostConfig"]
            service = container["Config"]["Labels"]["com.docker.compose.service"]
            mounts = container["Mounts"]
            destinations = {m["Destination"] for m in mounts}
            expected_mounts = {"/ipc-probe.py", "/ipc"}
            expected_tmpfs = {}
            if service == "parser":
                expected_mounts |= {"/probe.py", "/library/pypdf"}
                expected_tmpfs = {"/tmp": "size=8388608,uid=65532,gid=65532,mode=0700"}
            valid = (
                container["Image"] == IMAGE
                and config["NetworkMode"] == "none"
                and config["ReadonlyRootfs"]
                and not config["Privileged"]
                and config["CapDrop"] == ["ALL"]
                and config["SecurityOpt"] == ["no-new-privileges:true"]
                and config["Memory"] == config["MemorySwap"] == 128 * 1024**2
                and config["PidsLimit"] == 16
                and config["NanoCpus"] == 1_000_000_000
                and container["Config"]["User"] == "65532:65532"
                and destinations == expected_mounts
                and (config.get("Tmpfs") or {}) == expected_tmpfs
                and all(
                    not m["RW"]
                    for m in mounts
                    if m["Type"] == "bind" or service == "client"
                )
            )
            settings.append(
                {
                    "service": service,
                    "matches_expected": valid,
                    "destinations": sorted(destinations),
                    "tmpfs": config.get("Tmpfs") or {},
                }
            )
            if not valid:
                raise RuntimeError(f"unexpected isolation settings: {service}")
        volumes = (
            call(["docker", "volume", "ls", "-q", "--filter", project_filter], env)
            .decode()
            .split()
        )
        volume = json.loads(call(["docker", "volume", "inspect", *volumes], env))
        if len(volume) != 1 or volume[0]["Options"] != {
            "type": "tmpfs",
            "device": "tmpfs",
            "o": "size=1048576,uid=65532,gid=65532,mode=0770",
        }:
            raise RuntimeError("IPC volume is not the bounded tmpfs")
        parser_id = call([*compose, "ps", "-q", "parser"], env).decode().strip()

        def attempt(kind, content, fault, expected, recovery=False):
            argv = [
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
            if fault:
                argv += ["--wire-fault", fault]
            started = time.monotonic()
            value = json.loads(call(argv, env, content))
            passed = value["status"] == expected
            passed = passed and value["client_isolation"] == {
                "status": "isolated",
                "uid": 65532,
                "docker_socket_absent": True,
                "secrets_absent": True,
                "interfaces": ["lo"],
            }
            if expected == "readable":
                required = (
                    "SYNTHETIC text page" if kind == "pdf-plain" else "Visible evidence"
                )
                passed = passed and [
                    f["text"] for f in value["result"]["fragments"]
                ] == [required]
                passed = (
                    passed and value["sha256"] == hashlib.sha256(content).hexdigest()
                )
                passed = passed and value["result"]["document_verified"] is False
                if kind == "pdf-plain":
                    passed = passed and value["result"]["pages_without_text"] == [2]
                    passed = passed and value["result"]["selection_incomplete"] is True
            if expected == "input_limit":
                passed = passed and not value["sent"]
            restart = json.loads(
                call(
                    [
                        "docker",
                        "inspect",
                        "--format",
                        "{{json .RestartCount}}",
                        parser_id,
                    ],
                    env,
                )
            )
            record = {
                "case": kind,
                "wire_fault": fault,
                "recovery": recovery,
                "expected": expected,
                "observed": value["status"],
                "matches_expected": bool(passed),
                "generation": value.get("generation"),
                "restart_count": restart,
                "request_id": value.get("request_id"),
                "sent": value["sent"],
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
            records.append(record)
            print(json.dumps(record), flush=True)
            return record

        for kind, content, fault, expected in fixtures:
            before = records[-1]["generation"] if records else None
            record = attempt(kind, content, fault, expected)
            if not record["matches_expected"]:
                raise RuntimeError("diagnostic expectation failed")
            if recycle and before and record["generation"] == before:
                raise RuntimeError("per-document recycle did not change generation")
            if expected not in {"readable", "isolated"}:
                recovered = attempt("html", healthy, None, "readable", recovery=True)
                if not recovered["matches_expected"]:
                    raise RuntimeError("service did not recover")
                if kind == "service-oom" and (
                    recovered["generation"] == before or recovered["restart_count"] < 1
                ):
                    raise RuntimeError("service restart was not observed")
    except BaseException as error:
        failure = type(error).__name__ + ": " + str(error)[:300]
        raise
    finally:
        try:
            call([*compose, "down", "--volumes", "--timeout", "2"], env)
            cleanup = not call(
                ["docker", "ps", "-aq", "--filter", project_filter], env
            ).strip()
            cleanup = (
                cleanup
                and not call(
                    ["docker", "volume", "ls", "-q", "--filter", project_filter], env
                ).strip()
            )
        finally:
            if report:
                with report.open("x", encoding="utf-8") as output:
                    json.dump(
                        {
                            "prototype_only": True,
                            "formal_acceptance": False,
                            "project": project,
                            "recycle_each_document": recycle,
                            "image": IMAGE,
                            "settings": settings,
                            "records": records,
                            "cleanup_verified": cleanup,
                            "execution_error": failure,
                            "files": {
                                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (
                                    Path(__file__),
                                    root / "extraction_ipc_probe.py",
                                    root / "extraction-ipc.compose.yaml",
                                    root / "source_extraction_probe.py",
                                )
                            },
                        },
                        output,
                        ensure_ascii=False,
                        indent=2,
                    )
    return cleanup and all(r["matches_expected"] for r in records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--case", choices=["all", "recycle", "adversarial"])
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    library = args.library.resolve(strict=True)
    sys.path.insert(0, str(library))
    import pypdf

    if pypdf.__version__ != "6.18.0":
        parser.error("requires the previously selected pypdf 6.18.0")
    if args.report and args.report.exists():
        parser.error("choose a new create-only report path")
    if args.case is None:
        choice = input(
            "THROWAWAY IPC: [1] faults + recovery [2] recycle each document [q] quit: "
        )
        if choice not in {"1", "2"}:
            return
        args.case = "all" if choice == "1" else "recycle"
    if not run(
        library, args.case == "recycle", args.report, args.case == "adversarial"
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
