"""THROWAWAY: can isolated extraction return readable, bounded source fragments?

Not production, not a valuation source, and not resource/SLO acceptance evidence.
Run with --library pointing to an isolated site-packages directory. No database.
Default is an interactive case selector; --case all runs the diagnostic cases.
Only --case sources fetches the two explicit public MediaTek URLs below.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time


def child(kind: str, memory_mib: int) -> None:
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (memory_mib * 1024**2,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
    resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))
    sys.path.insert(0, "/library")
    print("PROTOTYPE_CHILD_READY", flush=True)
    content = sys.stdin.buffer.read(2_000_001)
    if len(content) > 2_000_000:
        print(json.dumps({"status": "input_limit"}))
        return
    try:
        if kind == "cpu":
            while True:
                pass
        if kind == "wall":
            time.sleep(60)
        if kind == "memory":
            bytearray(2 * 1024**3)
        if kind == "output":
            while True:
                sys.stdout.write("x" * 4096)
                sys.stdout.flush()
        if kind == "isolation":
            import socket

            with socket.socket() as connection:
                connection.settimeout(0.2)
                denied = connection.connect_ex(("192.0.2.1", 443)) != 0
            print(
                json.dumps(
                    {
                        "status": "isolated",
                        "egress_denied": denied,
                        "home_absent": not Path("/home").exists(),
                        "secrets_absent": not Path("/run/secrets").exists(),
                        "env_keys": sorted(os.environ),
                    }
                )
            )
            return
        blocks = []
        total_pages = None
        pages_without_text = []
        if kind == "html":
            from html.parser import HTMLParser

            class BodyBlocks(HTMLParser):
                def __init__(self):
                    super().__init__(convert_charrefs=True)
                    self.stack = []
                    self.parts = []
                    self.start_line = 0
                    self.block_tag = None

                def handle_starttag(self, tag, attrs):
                    hidden = any(
                        k == "hidden" or (k == "aria-hidden" and v == "true")
                        for k, v in attrs
                    )
                    excluded = tag in {
                        "script",
                        "style",
                        "nav",
                        "header",
                        "footer",
                        "aside",
                        "head",
                        "noscript",
                        "template",
                    }
                    skip = hidden or excluded or bool(self.stack and self.stack[-1][1])
                    if tag not in {"br", "hr", "img", "input", "meta", "link", "wbr"}:
                        self.stack.append((tag, bool(skip)))
                    if not skip:
                        if self.block_tag is None and tag in {
                            "p",
                            "h1",
                            "h2",
                            "h3",
                            "tr",
                        }:
                            self.block_tag, self.start_line = tag, self.getpos()[0]
                            self.parts = []
                        if tag in {"br", "td", "th"}:
                            self.parts.append("\t" if tag in {"td", "th"} else "\n")

                def handle_endtag(self, tag):
                    if tag == self.block_tag:
                        value = " ".join("".join(self.parts).split())
                        if value:
                            blocks.append((f"html-line:{self.start_line}:{tag}", value))
                        self.parts, self.block_tag = [], None
                    for index in range(len(self.stack) - 1, -1, -1):
                        if self.stack[index][0] == tag:
                            del self.stack[index:]
                            break

                def handle_data(self, data):
                    if self.block_tag and not (self.stack and self.stack[-1][1]):
                        self.parts.append(data)

            text = content.decode("utf-8-sig", errors="strict")
            if "\x00" in text or "\ufffd" in text:
                raise UnicodeError("ambiguous text")
            parser = BodyBlocks()
            parser.feed(text)
            parser.close()
        elif kind in {"pdf", "pdf-compact", "pdf-plain"}:
            from pypdf import PdfReader

            if not content.startswith(b"%PDF-"):
                raise ValueError("not PDF")
            reader = PdfReader(io.BytesIO(content), strict=True)
            if reader.is_encrypted:
                print(json.dumps({"status": "encrypted"}))
                return
            total_pages = len(reader.pages)
            if total_pages > 40:
                print(json.dumps({"status": "page_limit"}))
                return
            for number, page in enumerate(reader.pages, 1):
                if page.get_contents() is None:
                    pages_without_text.append(number)
                    continue
                # All decompression is inside the disposable resource-limited child.
                mode = "plain" if kind == "pdf-plain" else "layout"
                value = page.extract_text(extraction_mode=mode).strip()
                if kind == "pdf-compact":
                    value = "\n".join(
                        " ".join(line.split()) for line in value.splitlines()
                    )
                if value:
                    blocks.append((f"pdf-page:{number}", value))
                else:
                    # No extracted text is not proof that the page is blank.
                    # Report the gap without guessing image/OCR semantics.
                    pages_without_text.append(number)
        else:
            raise ValueError("unknown kind")
        fragments = []
        remaining = 4000
        for locator, value in blocks[:8]:
            fragment_limit = 2000 if kind in {"pdf-compact", "pdf-plain"} else 1000
            fragment = value[: min(fragment_limit, remaining)]
            if not fragment:
                break
            fragments.append(
                {
                    "locator": locator,
                    "text": fragment,
                    "truncated": len(fragment) < len(value),
                }
            )
            remaining -= len(fragment)
        print(
            json.dumps(
                {
                    "status": "readable" if fragments else "no_text",
                    "fragments": fragments,
                    "selection_incomplete": len(fragments) != len(blocks)
                    or any(f["truncated"] for f in fragments)
                    or bool(pages_without_text),
                    "total_pages": total_pages,
                    "pages_without_text": pages_without_text,
                    "published_at": None,
                    "observed_at": None,
                    "document_verified": False,
                },
                ensure_ascii=False,
            )
        )
    except MemoryError:
        print('{"status":"memory_limit"}')
    except UnicodeError:
        print('{"status":"invalid_encoding"}')
    except Exception as error:
        print(
            json.dumps({"status": "parser_failure", "error_kind": type(error).__name__})
        )


def run_isolated(content: bytes, kind: str, library: Path, memory_mib: int) -> dict:
    argv = [
        "bwrap",
        "--unshare-all",
        "--unshare-user",
        "--disable-userns",
        "--die-with-parent",
        "--cap-drop",
        "ALL",
        "--ro-bind",
        "/usr",
        "/usr",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/lib64",
        "/lib64",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--clearenv",
        "--ro-bind",
        str(library),
        "/library",
        "--ro-bind",
        str(Path(__file__).resolve()),
        "/probe.py",
        "--chdir",
        "/",
        "/usr/bin/python3",
        "-I",
        "-B",
        "/probe.py",
        "--child",
        kind,
        "--memory-mib",
        str(memory_mib),
    ]
    output = bytearray()
    status = None
    with tempfile.TemporaryFile() as source:
        source.write(content)
        source.seek(0)
        process = subprocess.Popen(
            argv,
            stdin=source,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={"PATH": "/usr/bin:/bin"},
            close_fds=True,
        )
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                deadline = time.monotonic() + 5
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        status = "wall_limit"
                        break
                    for key, _ in selector.select(remaining):
                        part = os.read(key.fd, 4096)
                        if not part:
                            selector.unregister(key.fileobj)
                            continue
                        output.extend(part)
                        if len(output) > 16_384:
                            status = "output_limit"
                            break
                    if status:
                        break
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            returncode = process.wait(timeout=2)
            process.stdout.close()
    ready = output.startswith(b"PROTOTYPE_CHILD_READY\n")
    if ready:
        output = output.removeprefix(b"PROTOTYPE_CHILD_READY\n")
    if not ready:
        result = {"status": "launch_failed", "exit": returncode}
    elif status:
        result = {"status": status}
    elif returncode:
        result = {"status": "child_terminated", "exit": returncode}
    else:
        try:
            result = json.loads(output)
        except ValueError:
            result = {"status": "invalid_output"}
    result.update(
        raw_sha256=hashlib.sha256(content).hexdigest(),
        input_bytes=len(content),
        memory_mib_candidate=memory_mib,
        child_reaped=True,
        child_ready=ready,
    )
    return result


def cases(library: Path):
    sys.path.insert(0, str(library))
    from pypdf import PdfWriter

    blank = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(blank)
    encrypted = io.BytesIO()
    writer.encrypt("prototype-only")
    writer.write(encrypted)
    yield (
        "html",
        b"<body><nav><p>ignore</p></nav><p>Visible <b>evidence</b><script>BAD</script></p></body>",
        "readable",
    )
    yield "html", b"<p>\xff</p>", "invalid_encoding"
    yield "html", b"<script>only script</script>", "no_text"
    yield "pdf", b"%PDF-1.7\nbroken", "parser_failure"
    yield "pdf", blank.getvalue(), "no_text"
    yield "pdf", encrypted.getvalue(), "encrypted"
    many_pages = PdfWriter()
    for _ in range(41):
        many_pages.add_blank_page(width=72, height=72)
    many_output = io.BytesIO()
    many_pages.write(many_output)
    yield "pdf", many_output.getvalue(), "page_limit"
    # Synthetic compressed-stream fault, never evidence about a real company.
    import zlib
    from pypdf.generic import EncodedStreamObject, NameObject

    compressor = zlib.compressobj()
    compressed = bytearray()
    for _ in range(256):
        compressed.extend(compressor.compress(b" " * 1024**2))
    compressed.extend(compressor.flush())
    fault = PdfWriter()
    page = fault.add_blank_page(width=72, height=72)
    stream = EncodedStreamObject()
    # Fixture construction only: these bytes are already Flate-encoded.
    stream._data = bytes(compressed)
    stream[NameObject("/Filter")] = NameObject("/FlateDecode")
    page[NameObject("/Contents")] = fault._add_object(stream)
    fault_output = io.BytesIO()
    fault.write(fault_output)
    yield "pdf", fault_output.getvalue(), "memory_limit"
    yield "html", b"x" * 2_000_001, "input_limit"
    yield "isolation", b"", "isolated"
    yield "memory", b"", "memory_limit"
    yield "cpu", b"", "child_terminated"
    yield "wall", b"", "wall_limit"
    yield "output", b"", "output_limit"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child")
    parser.add_argument("--library", type=Path)
    parser.add_argument("--case", choices=["all", "sources"])
    parser.add_argument(
        "--report", type=Path, help="create-only diagnostic JSON, not source documents"
    )
    parser.add_argument("--memory-mib", type=int, choices=[64, 128, 256], default=128)
    args = parser.parse_args()
    if args.child:
        child(args.child, args.memory_mib)
        return
    if not args.library or not (args.library / "pypdf").is_dir():
        parser.error("--library must name the isolated pypdf site-packages directory")
    records = []
    if args.case is None:
        choice = input(
            "THROWAWAY prototype: [1] boundary cases [2] real public sources [q] quit: "
        )
        if choice not in {"1", "2"}:
            return
        args.case = "all" if choice == "1" else "sources"
    if args.case == "all":
        for kind, content, expected in cases(args.library):
            result = run_isolated(content, kind, args.library, args.memory_mib)
            matches = (
                result["status"] == expected
                and result["child_ready"]
                and result["child_reaped"]
            )
            if kind == "isolation":
                matches = (
                    matches
                    and all(
                        result.get(k)
                        for k in ("egress_denied", "home_absent", "secrets_absent")
                    )
                    and set(result.get("env_keys", [])) <= {"LC_CTYPE", "PWD"}
                )
            if kind == "cpu":
                matches = matches and result.get("exit") == 137
            if kind == "html" and expected == "readable":
                matches = matches and [
                    f["text"] for f in result.get("fragments", [])
                ] == ["Visible evidence"]
            record = {
                "case": kind,
                "expected": expected,
                "matches_expected": matches,
                **result,
            }
            records.append(record)
            print(json.dumps(record, ensure_ascii=False))
    else:
        from thesis_trace.platform.source_fetch import RestrictedHttpSourceFetcher

        urls = [
            "https://www.mediatek.com/investor-relations/financial-information",
            "https://www.mediatek.com/hubfs/MediaTek%20Assets/Pdfs/Monthly%20Reports/2026/Monthly%20Sales%20Revenue%20July,%202026.pdf",
        ]
        for url in urls:
            try:
                source = RestrictedHttpSourceFetcher().fetch(url)
            except Exception as error:
                record = {
                    "url": url,
                    "status": "fetch_failed",
                    "code": getattr(error, "failure_code", type(error).__name__),
                }
                records.append(record)
                print(json.dumps(record))
                continue
            kind = "pdf" if source.content.startswith(b"%PDF-") else "html"
            result = run_isolated(source.content, kind, args.library, args.memory_mib)
            if kind == "pdf":
                compact = run_isolated(
                    source.content, "pdf-compact", args.library, args.memory_mib
                )
                markers = [
                    "July 2026",
                    "Unit: NT$ million",
                    "48,475",
                    "not been audited",
                ]
                for candidate in (result, compact):
                    joined = "\n".join(
                        f["text"] for f in candidate.get("fragments", [])
                    )
                    candidate["fixture_marker_coverage"] = {
                        m: m in joined for m in markers
                    }
                result["compact_comparison"] = {
                    k: v for k, v in compact.items() if k != "fragments"
                }
                result["compact_comparison"]["extracted_characters"] = sum(
                    len(f["text"]) for f in compact.get("fragments", [])
                )
                plain = run_isolated(
                    source.content, "pdf-plain", args.library, args.memory_mib
                )
                joined = "\n".join(f["text"] for f in plain.get("fragments", []))
                plain["fixture_marker_coverage"] = {m: m in joined for m in markers}
                plain["audit_note_preview"] = (
                    joined[
                        max(0, joined.find("audited") - 60) : joined.find("audited")
                        + 10
                    ]
                    if "audited" in joined
                    else None
                )
                result["plain_comparison"] = {
                    k: v for k, v in plain.items() if k != "fragments"
                }
            # Retain only brief preview + counts in the diagnostic transcript.
            for fragment in result.get("fragments", []):
                fragment["extracted_characters"] = len(fragment["text"])
                fragment["text"] = fragment["text"][:100]
            record = {
                "url": source.canonical_url,
                "retrieved_at": source.retrieved_at,
                "prototype_only": True,
                **result,
            }
            records.append(record)
            print(json.dumps(record, ensure_ascii=False))
    if args.report:
        with args.report.open("x", encoding="utf-8") as report:
            json.dump(
                {
                    "prototype_only": True,
                    "script_sha256": hashlib.sha256(
                        Path(__file__).read_bytes()
                    ).hexdigest(),
                    "python": sys.version.split()[0],
                    "records": records,
                },
                report,
                ensure_ascii=False,
                indent=2,
            )
    if args.case == "all" and not all(r["matches_expected"] for r in records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
