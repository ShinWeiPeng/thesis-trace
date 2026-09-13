"""THROWAWAY DEC-106: can a fresh offline Docker container bound one parse?

Operator-only harness, NOT a collector adapter or a persistent Compose service.
No downloads, database, AI calls, Docker socket mount, or production imports.
The operator uses Docker; the parser only receives document bytes via stdin.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid


IMAGE = "sha256:9bc91c201c9a44439f9ab887f84fbcd191a20d180e76b758bd79ee7cf6e923ad"
READY = b"PROTOTYPE_CHILD_READY\n"
LABEL = "thesis-trace.extraction-prototype"


def audit_child(oom: bool) -> None:
    if oom and (
        os.getuid() != 65532
        or not Path("/.dockerenv").is_file()
        or Path("/sys/fs/cgroup/memory.max").read_text().strip() != "134217728"
    ):
        raise SystemExit("OOM fixture requires the 128 MiB diagnostic container")
    print(READY.decode().strip(), flush=True)
    if oom:
        # Deliberately exceed the container's 128 MiB cgroup, not host memory.
        bytearray(2 * 1024**3)
        raise SystemExit("cgroup limit was not enforced")
    import pypdf

    with socket.socket() as connection:
        connection.settimeout(0.2)
        denied = connection.connect_ex(("192.0.2.1", 443)) != 0
    status = Path("/proc/self/status").read_text()
    fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
    readonly = False
    try:
        with open("/prototype-write-probe", "x"):
            pass
    except OSError as error:
        readonly = error.errno == errno.EROFS
    print(
        json.dumps(
            {
                "status": "isolated",
                "egress_denied": denied,
                "interfaces": sorted(p.name for p in Path("/sys/class/net").iterdir()),
                "uid": os.getuid(),
                "cap_eff": fields["CapEff"].strip(),
                "no_new_privs": fields["NoNewPrivs"].strip(),
                "seccomp": fields["Seccomp"].strip(),
                "root_readonly": readonly,
                "secrets_absent": not Path("/run/secrets").exists(),
                "docker_socket_absent": not Path("/var/run/docker.sock").exists(),
                "env_keys": sorted(os.environ),
                "python": sys.version.split()[0],
                "pypdf": pypdf.__version__,
            }
        )
    )


def docker(*args: str) -> str:
    return subprocess.run(
        ["docker", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()


def run_container(content: bytes, kind: str, library: Path) -> dict:
    if len(content) > 2_000_001:
        raise ValueError("diagnostic payload exceeds the single-byte overflow case")
    token = uuid.uuid4().hex
    name = f"tt-extraction-probe-{token}"
    root = Path(__file__).resolve().parent
    child_args = (
        ["/docker-probe.py", "--audit-child"] + (["--oom"] if kind == "oom" else [])
        if kind in {"isolation", "oom"}
        else ["/probe.py", "--child", kind, "--memory-mib", "128"]
    )
    launch = "import os,sys;os.execve(sys.executable,[sys.executable,'-I','-B',*sys.argv[1:]],{})"
    argv = [
        "create",
        "--name",
        name,
        "--label",
        f"{LABEL}={token}",
        "--pull",
        "never",
        "-i",
        "--network",
        "none",
        "--read-only",
        "--user",
        "65532:65532",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        "128m",
        "--memory-swap",
        "128m",
        "--pids-limit",
        "8",
        "--cpus",
        "1",
        "--log-driver",
        "none",
        "--entrypoint",
        "python",
    ]
    for source, target in (
        (root / "source_extraction_probe.py", "/probe.py"),
        (root / "docker_extraction_probe.py", "/docker-probe.py"),
        (library / "pypdf", "/library/pypdf"),
    ):
        source = source.resolve(strict=True)
        if "," in str(source):
            raise ValueError("comma in diagnostic bind path")
        argv += ["--mount", f"type=bind,src={source},dst={target},readonly"]
    # Audit imports only the one explicitly mounted parser package.
    if kind in {"isolation", "oom"}:
        launch = (
            "import os,sys;os.execve(sys.executable,[sys.executable,'-I','-B','-c',"
            "\"import sys,runpy;sys.path.insert(0,'/library');"
            "sys.argv=sys.argv[1:];runpy.run_path(sys.argv[0],run_name='__main__')\","
            "*sys.argv[1:]],{})"
        )
    argv += [IMAGE, "-I", "-B", "-c", launch, *child_args]
    output = bytearray()
    limit = None
    ready = False
    cleaned = False
    state = {}
    settings_ok = False
    started = time.monotonic()
    try:
        container_id = docker(*argv)
        inspected = json.loads(docker("inspect", container_id))[0]
        config = inspected["HostConfig"]
        settings_ok = (
            inspected["Image"] == IMAGE
            and inspected["Config"]["User"] == "65532:65532"
            and config["NetworkMode"] == "none"
            and config["ReadonlyRootfs"]
            and not config["Privileged"]
            and config["CapDrop"] == ["ALL"]
            and config["SecurityOpt"] == ["no-new-privileges"]
            and config["Memory"] == config["MemorySwap"] == 128 * 1024**2
            and config["PidsLimit"] == 8
            and config["NanoCpus"] == 1_000_000_000
            and len(inspected["Mounts"]) == 3
            and all(m["Type"] == "bind" and not m["RW"] for m in inspected["Mounts"])
            and {m["Destination"] for m in inspected["Mounts"]}
            == {"/probe.py", "/docker-probe.py", "/library/pypdf"}
        )
        if not settings_ok:
            raise RuntimeError(
                "container configuration differs from diagnostic boundary"
            )
        with tempfile.TemporaryFile() as source:
            source.write(content)
            source.seek(0)
            process = subprocess.Popen(
                ["docker", "start", "-a", "-i", container_id],
                stdin=source,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    deadline = time.monotonic() + 10
                    while selector.get_map():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            limit = "wall_limit" if ready else "launch_timeout"
                            break
                        for key, _ in selector.select(remaining):
                            part = os.read(key.fd, min(4096, 16_385 - len(output)))
                            if not part:
                                selector.unregister(key.fileobj)
                                continue
                            output.extend(part)
                            if not ready and output.startswith(READY):
                                ready = True
                                deadline = time.monotonic() + 5
                            if len(output) > 16_384:
                                limit = "output_limit"
                                break
                        if limit:
                            break
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
                process.stdout.close()
        state = json.loads(
            docker("inspect", "--format", "{{json .State}}", container_id)
        )
        if state["Running"]:
            docker("kill", container_id)
            docker("wait", container_id)
            state = json.loads(
                docker("inspect", "--format", "{{json .State}}", container_id)
            )
    finally:
        # Resolve the unique label before deleting anything, including after a
        # create timeout. Never stop or prune an existing application container.
        owned = docker("ps", "-aq", "--filter", f"label={LABEL}={token}").splitlines()
        for owned_id in owned:
            docker("rm", "-f", owned_id)
        cleaned = not docker("ps", "-aq", "--filter", f"label={LABEL}={token}")
        if not cleaned:
            raise RuntimeError(f"cleanup incomplete: {name}")
    if not ready:
        result = {"status": "launch_failed"}
    elif limit:
        result = {"status": limit}
    elif state.get("OOMKilled"):
        result = {"status": "container_oom"}
    elif state.get("ExitCode"):
        result = {"status": "child_terminated"}
    else:
        try:
            result = json.loads(output.removeprefix(READY))
            if not isinstance(result, dict):
                raise ValueError("non-object diagnostic result")
        except ValueError:
            result = {"status": "invalid_output"}
    return {
        **result,
        "case": kind,
        "child_ready": ready,
        "container_removed": cleaned,
        "settings_verified": settings_ok,
        "container_exit": state.get("ExitCode"),
        "oom_killed": state.get("OOMKilled"),
        "raw_sha256": hashlib.sha256(content).hexdigest(),
        "input_bytes": len(content),
        "captured_bytes": len(output),
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def matches(result: dict, expected: str) -> bool:
    ok = (
        result["status"] == expected
        and result["child_ready"]
        and result["settings_verified"]
        and result["container_removed"]
    )
    if expected == "isolated":
        ok = (
            ok
            and all(
                result.get(k)
                for k in (
                    "egress_denied",
                    "root_readonly",
                    "secrets_absent",
                    "docker_socket_absent",
                )
            )
            and result.get("interfaces") == ["lo"]
            and result.get("uid") == 65532
        )
        ok = ok and result.get("cap_eff") == "0000000000000000"
        ok = ok and result.get("no_new_privs") == "1" and result.get("seccomp") == "2"
        ok = ok and set(result.get("env_keys", [])) <= {"LC_CTYPE"}
        ok = ok and result.get("pypdf") == "6.18.0"
    if result["case"] == "cpu":
        ok = ok and result["container_exit"] == 137 and not result["oom_killed"]
    if result["case"] == "oom":
        ok = ok and result["container_exit"] == 137 and result["oom_killed"]
    if result["case"] == "html" and expected == "readable":
        ok = ok and [f["text"] for f in result.get("fragments", [])] == [
            "Visible evidence"
        ]
    if result["case"] == "pdf-plain" and expected == "readable":
        ok = ok and [f["text"] for f in result.get("fragments", [])] == [
            "SYNTHETIC text page"
        ]
        ok = ok and result.get("total_pages") == 2
        ok = ok and result.get("pages_without_text") == [2]
        ok = ok and result.get("selection_incomplete") is True
        ok = ok and result.get("document_verified") is False
    return bool(ok)


def text_pdf() -> bytes:
    # A visible-text page plus a blank page: engineering fixture, not company data.
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 100 Td (SYNTHETIC text page) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_blank_page(width=200, height=200)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path)
    parser.add_argument("--case", choices=["all", "isolation"])
    parser.add_argument("--report", type=Path, help="create-only diagnostic JSON")
    parser.add_argument("--audit-child", action="store_true")
    parser.add_argument("--oom", action="store_true")
    args = parser.parse_args()
    if args.audit_child:
        audit_child(args.oom)
        return
    if not args.library or not (args.library / "pypdf").is_dir():
        parser.error("--library must contain the previously installed pypdf 6.18.0")
    if args.report and args.report.exists():
        parser.error("report already exists; choose a new path")
    if args.case is None:
        choice = input(
            "THROWAWAY Docker: [1] isolation [2] all faults + recovery [q] quit: "
        )
        if choice not in {"1", "2"}:
            return
        args.case = "isolation" if choice == "1" else "all"
    from source_extraction_probe import cases

    fixtures = [("isolation", b"", "isolated")]
    if args.case == "all":
        fixtures = list(cases(args.library)) + [
            ("pdf-plain", text_pdf(), "readable"),
            ("html", (("<p>" + "😀" * 1000 + "</p>") * 4).encode(), "output_limit"),
            ("oom", b"", "container_oom"),
            ("html", b"<p>Visible evidence</p>", "readable"),
        ]
    records = []
    try:
        for kind, content, expected in fixtures:
            result = run_container(content, kind, args.library)
            result.update(expected=expected, matches_expected=matches(result, expected))
            records.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        if args.report:
            with args.report.open("x", encoding="utf-8") as report:
                json.dump(
                    {
                        "prototype_only": True,
                        "formal_acceptance": False,
                        "parameters_are_diagnostic_only": True,
                        "parameters": {
                            "parser_address_space_mib": 128,
                            "container_memory_mib": 128,
                            "container_cpu_quota": 1,
                            "parser_cpu_seconds": 2,
                            "after_ready_wait_seconds": 5,
                            "launch_wait_seconds": 10,
                            "max_output_bytes": 16384,
                            "overflow_detection_bytes": 1,
                        },
                        "image": IMAGE,
                        "python_host": sys.version.split()[0],
                        "script_sha256": hashlib.sha256(
                            Path(__file__).read_bytes()
                        ).hexdigest(),
                        "parser_sha256": hashlib.sha256(
                            Path(__file__)
                            .with_name("source_extraction_probe.py")
                            .read_bytes()
                        ).hexdigest(),
                        "expected_cases": len(fixtures),
                        "records": records,
                    },
                    report,
                    ensure_ascii=False,
                    indent=2,
                )
    if not all(r["matches_expected"] for r in records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
