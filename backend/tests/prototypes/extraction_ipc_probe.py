"""THROWAWAY socket experiment; never import from production. See IPC-DESIGN.md."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid

PROTOCOL = "tt-extraction-probe-v1"
SOCKET = "/ipc/extraction.sock"
INPUT_LIMIT = 2_000_000
OUTPUT_LIMIT = 16_384
KINDS = frozenset(
    {
        "html",
        "pdf",
        "pdf-plain",
        "memory",
        "cpu",
        "wall",
        "output",
        "service-oom",
        "wrong-id",
        "wrong-hash",
        "bad-json",
        "nested-json",
        "bad-utf8",
        "surrogate-text",
        "oversize-reply",
        "false-verified",
        "late-reply",
        "isolation",
    }
)


def strict_json(raw: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"), object_pairs_hook=unique
        )
    except RecursionError as error:
        raise ValueError("JSON nesting rejected") from error
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def remaining(connection: socket.socket, deadline: float) -> None:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("attempt expired")
    connection.settimeout(seconds)


def receive(connection: socket.socket, length: int, deadline: float) -> bytes:
    data = bytearray()
    while len(data) < length:
        remaining(connection, deadline)
        part = connection.recv(min(4096, length - len(data)))
        if not part:
            raise EOFError("incomplete frame")
        data.extend(part)
    return bytes(data)


def frame(connection: socket.socket, maximum: int, deadline: float) -> bytes:
    length = struct.unpack("!I", receive(connection, 4, deadline))[0]
    if length < 2 or length > maximum:
        raise ValueError("frame size rejected before allocation")
    return receive(connection, length, deadline)


def send_frame(connection: socket.socket, value: dict, deadline: float) -> None:
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    if len(raw) > OUTPUT_LIMIT:
        raise ValueError("outgoing frame exceeds limit")
    remaining(connection, deadline)
    connection.sendall(struct.pack("!I", len(raw)) + raw)


def check_request(value: dict) -> None:
    if set(value) != {"protocol", "request_id", "sha256", "kind", "length"}:
        raise ValueError("request shape")
    if value["protocol"] != PROTOCOL or value["kind"] not in KINDS:
        raise ValueError("unsupported diagnostic request")
    for key, size in (("request_id", 32), ("sha256", 64)):
        if not isinstance(value[key], str) or not re.fullmatch(
            f"[0-9a-f]{{{size}}}", value[key]
        ):
            raise ValueError("invalid request binding")
    if type(value["length"]) is not int or not 0 <= value["length"] <= INPUT_LIMIT:
        raise ValueError("input limit")


def check_reply(value: dict, request: dict) -> dict:
    if set(value) != {"protocol", "request_id", "sha256", "generation", "result"}:
        raise ValueError("response shape")
    if any(value[k] != request[k] for k in ("protocol", "request_id", "sha256")):
        raise ValueError("response binding mismatch")
    if not isinstance(value["generation"], str) or not re.fullmatch(
        "[0-9a-f]{32}", value["generation"]
    ):
        raise ValueError("invalid generation")
    result = value["result"]
    if not isinstance(result, dict) or not isinstance(result.get("status"), str):
        raise ValueError("invalid result")
    if result["status"] in {"readable", "no_text"}:
        if set(result) != {
            "status",
            "fragments",
            "selection_incomplete",
            "total_pages",
            "pages_without_text",
            "published_at",
            "observed_at",
            "document_verified",
        }:
            raise ValueError("extraction shape")
        if result["document_verified"] is not False or any(
            result[k] is not None for k in ("published_at", "observed_at")
        ):
            raise ValueError("unverified dates/facts cannot be promoted")
        fragments = result["fragments"]
        if not isinstance(fragments, list) or len(fragments) > 8:
            raise ValueError("fragment count")
        for item in fragments:
            if not isinstance(item, dict) or set(item) != {
                "locator",
                "text",
                "truncated",
            }:
                raise ValueError("fragment shape")
            if (
                type(item["truncated"]) is not bool
                or not isinstance(item["text"], str)
                or not 1 <= len(item["text"]) <= 2000
            ):
                raise ValueError("fragment value")
            item["text"].encode("utf-8", errors="strict")
            if (
                not isinstance(item["locator"], str)
                or len(item["locator"]) > 80
                or not re.fullmatch(
                    r"(?:pdf-page:[1-9][0-9]*|html-line:[1-9][0-9]*:(?:p|h1|h2|h3|tr))",
                    item["locator"],
                )
            ):
                raise ValueError("fragment locator")
        if sum(len(f["text"]) for f in fragments) > 4000 or bool(fragments) != (
            result["status"] == "readable"
        ):
            raise ValueError("fragment coverage")
        total, missing = result["total_pages"], result["pages_without_text"]
        if total is not None and (type(total) is not int or not 1 <= total <= 40):
            raise ValueError("page count")
        if (
            not isinstance(missing, list)
            or any(
                type(n) is not int or total is None or not 1 <= n <= total
                for n in missing
            )
            or missing != sorted(set(missing))
        ):
            raise ValueError("missing page shape")
        if type(result["selection_incomplete"]) is not bool or (
            (missing or any(f["truncated"] for f in fragments))
            and not result["selection_incomplete"]
        ):
            raise ValueError("missing coverage warning")
    elif result["status"] in {
        "input_limit",
        "page_limit",
        "encrypted",
        "memory_limit",
        "wall_limit",
        "output_limit",
        "parser_failure",
        "invalid_encoding",
        "child_terminated",
        "launch_failed",
        "invalid_output",
    }:
        if set(result) - {"status", "error_kind"}:
            raise ValueError("unexpected error fields")
        if "error_kind" in result and (
            not isinstance(result["error_kind"], str) or len(result["error_kind"]) > 80
        ):
            raise ValueError("error detail limit")
        if "error_kind" in result:
            result["error_kind"].encode("utf-8", errors="strict")
    elif result["status"] == "isolated":
        if set(result) != {
            "status",
            "uid",
            "docker_socket_absent",
            "secrets_absent",
            "interfaces",
        }:
            raise ValueError("audit shape")
        if result != {
            "status": "isolated",
            "uid": 65532,
            "docker_socket_absent": True,
            "secrets_absent": True,
            "interfaces": ["lo"],
        }:
            raise ValueError("audit mismatch")
    else:
        raise ValueError("unknown status")
    return value


def isolation() -> dict:
    return {
        "status": "isolated",
        "uid": os.getuid(),
        "docker_socket_absent": not Path("/var/run/docker.sock").exists(),
        "secrets_absent": not Path("/run/secrets").exists(),
        "interfaces": sorted(p.name for p in Path("/sys/class/net").iterdir()),
    }


def parse_child(content: bytes, kind: str) -> dict:
    output = bytearray()
    limit = None
    with tempfile.TemporaryFile() as source:
        source.write(content)
        source.seek(0)
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                "/probe.py",
                "--child",
                kind,
                "--memory-mib",
                "128",
            ],
            stdin=source,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={},
            close_fds=True,
            start_new_session=True,
        )
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                deadline = time.monotonic() + 5
                while selector.get_map():
                    delay = deadline - time.monotonic()
                    if delay <= 0:
                        limit = "wall_limit"
                        break
                    for key, _ in selector.select(delay):
                        part = os.read(
                            key.fd, min(4096, OUTPUT_LIMIT + 1 - len(output))
                        )
                        if not part:
                            selector.unregister(key.fileobj)
                            continue
                        output.extend(part)
                        if len(output) > OUTPUT_LIMIT:
                            limit = "output_limit"
                            break
                    if limit:
                        break
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            code = process.wait(timeout=2)
            process.stdout.close()
    marker = b"PROTOTYPE_CHILD_READY\n"
    if not output.startswith(marker):
        return {"status": "launch_failed"}
    if limit:
        return {"status": limit}
    if code:
        return {"status": "child_terminated"}
    try:
        return strict_json(output.removeprefix(marker))
    except (ValueError, UnicodeError):
        return {"status": "invalid_output"}


def serve(recycle: bool) -> None:
    os.umask(0o177)
    path = Path(SOCKET)
    if path.exists():
        if not stat.S_ISSOCK(path.lstat().st_mode):
            raise ValueError("refuse replacing a non-socket")
        path.unlink()
    generation = uuid.uuid4().hex
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(SOCKET)
        listener.listen(1)
        while True:
            connection, _ = listener.accept()
            with connection:
                try:
                    _, uid, _ = struct.unpack(
                        "3i",
                        connection.getsockopt(
                            socket.SOL_SOCKET, socket.SO_PEERCRED, 12
                        ),
                    )
                    if uid != 65532:
                        raise ValueError("unexpected local peer")
                    deadline = time.monotonic() + 8
                    request = strict_json(frame(connection, 1024, deadline))
                    check_request(request)
                    content = receive(connection, request["length"], deadline)
                    remaining(connection, deadline)
                    if (
                        connection.recv(1)
                        or hashlib.sha256(content).hexdigest() != request["sha256"]
                    ):
                        raise ValueError("payload length/hash mismatch")
                    kind = request["kind"]
                    if kind == "service-oom":
                        if (
                            os.getuid() != 65532
                            or not Path("/.dockerenv").exists()
                            or Path("/sys/fs/cgroup/memory.max").read_text().strip()
                            != "134217728"
                        ):
                            raise ValueError(
                                "OOM injection requires the diagnostic cgroup"
                            )
                        bytearray(2 * 1024**3)
                        raise ValueError("OOM fixture unexpectedly survived")
                    if kind == "late-reply":
                        time.sleep(2)
                    parsed_kind = (
                        kind
                        if kind
                        in {
                            "html",
                            "pdf",
                            "pdf-plain",
                            "memory",
                            "cpu",
                            "wall",
                            "output",
                        }
                        else "html"
                    )
                    result = (
                        isolation()
                        if kind == "isolation"
                        else parse_child(content, parsed_kind)
                    )
                    reply = {
                        k: request[k] for k in ("protocol", "request_id", "sha256")
                    }
                    reply.update(generation=generation, result=result)
                    if kind == "wrong-id":
                        reply["request_id"] = "0" * 32
                    if kind == "wrong-hash":
                        reply["sha256"] = "0" * 64
                    if kind == "false-verified":
                        reply["result"]["document_verified"] = True
                    if kind == "surrogate-text":
                        reply["result"]["fragments"][0]["text"] = "\ud800"
                    if kind == "bad-json":
                        connection.sendall(struct.pack("!I", 2) + b"{{")
                    elif kind == "nested-json":
                        nested = b'{"x":' + b"[" * 1200 + b"0" + b"]" * 1200 + b"}"
                        connection.sendall(struct.pack("!I", len(nested)) + nested)
                    elif kind == "bad-utf8":
                        connection.sendall(struct.pack("!I", 2) + b"\xff\xff")
                    elif kind == "surrogate-text":
                        escaped = json.dumps(reply, ensure_ascii=True).encode()
                        connection.sendall(struct.pack("!I", len(escaped)) + escaped)
                    elif kind == "oversize-reply":
                        connection.sendall(struct.pack("!I", OUTPUT_LIMIT + 1))
                    else:
                        if (
                            len(json.dumps(reply, ensure_ascii=False).encode())
                            > OUTPUT_LIMIT
                        ):
                            reply["result"] = {"status": "output_limit"}
                        send_frame(connection, reply, deadline)
                except (OSError, EOFError, ValueError, TypeError):
                    # Never persist request content or turn an invalid request into success.
                    pass
            if recycle:
                return


def request_source(content: bytes, kind: str, wire_fault: str | None) -> dict:
    if len(content) > INPUT_LIMIT:
        return {"status": "input_limit", "sent": False}
    request = {
        "protocol": PROTOCOL,
        "request_id": uuid.uuid4().hex,
        "sha256": hashlib.sha256(content).hexdigest(),
        "kind": kind,
        "length": len(content),
    }
    if wire_fault == "wrong-input-hash":
        request["sha256"] = "0" * 64
    check_request(request)
    deadline = time.monotonic() + 20
    connection = None
    while time.monotonic() < deadline:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            remaining(connection, deadline)
            connection.connect(SOCKET)
            break
        except (FileNotFoundError, ConnectionRefusedError):
            connection.close()
            connection = None
            time.sleep(0.05)
    if connection is None:
        return {"status": "unavailable", "sent": False}
    with connection:
        try:
            deadline = time.monotonic() + (0.3 if kind == "late-reply" else 10)
            raw = json.dumps(request).encode()
            if wire_fault == "oversize-header":
                raw = struct.pack("!I", 1025)
            elif wire_fault == "duplicate-key":
                raw = b'{"kind":"html","kind":"pdf"}'
                raw = struct.pack("!I", len(raw)) + raw
            else:
                raw = struct.pack("!I", len(raw)) + raw
            remaining(connection, deadline)
            if wire_fault == "partial":
                connection.sendall(raw + content[:1])
            elif wire_fault == "fragmented":
                for byte in raw:
                    remaining(connection, deadline)
                    connection.sendall(bytes([byte]))
                connection.sendall(content)
            else:
                connection.sendall(
                    raw + content + (b"x" if wire_fault == "trailing-input" else b"")
                )
            connection.shutdown(socket.SHUT_WR)
            value = check_reply(
                strict_json(frame(connection, OUTPUT_LIMIT, deadline)), request
            )
            remaining(connection, deadline)
            if connection.recv(1):
                raise ValueError("trailing response bytes")
            return {"status": value["result"]["status"], "sent": True, **value}
        except (ValueError, UnicodeError):
            return {"status": "protocol_rejected", "sent": True}
        except TimeoutError:
            return {"status": "attempt_timeout", "sent": True}
        except (OSError, EOFError):
            return {"status": "unavailable", "sent": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--recycle", choices=["yes", "no"], default="no")
    parser.add_argument("--idle", action="store_true")
    parser.add_argument("--client", choices=sorted(KINDS))
    parser.add_argument(
        "--wire-fault",
        choices=[
            "oversize-header",
            "duplicate-key",
            "partial",
            "fragmented",
            "wrong-input-hash",
            "trailing-input",
        ],
    )
    args = parser.parse_args()
    os.environ.clear()
    if args.serve:
        serve(args.recycle == "yes")
    elif args.idle:
        while True:
            time.sleep(60)
    elif args.client:
        content = sys.stdin.buffer.read(INPUT_LIMIT + 1)
        result = request_source(content, args.client, args.wire_fault)
        result["client_isolation"] = isolation()
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
