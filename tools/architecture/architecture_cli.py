#!/usr/bin/env python3
"""Single public command-line interface for architecture governance."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import yaml

from check_architecture import (
    Diagnostic,
    ManifestError,
    load_yaml,
    validate_manifest,
)
from governance_adoption import (
    apply_baseline,
    compare_adoption_documents,
    readiness_status,
    validate_adoption,
    write_adoption_documents,
)
from python_analyzer import analyze_python
from typescript_analyzer import analyze_typescript
from libclang_toolchain_adapter import EspressifLibclangToolchainAdapter
from libclang_toolchain_contract import ToolchainProviderError


PHASES = ("design", "development", "release")


def _as_dict(item: Any) -> dict[str, Any]:
    if is_dataclass(item):
        return asdict(item)
    return dict(item)


def _load_optional(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return load_yaml(path)


def _exit_code(diagnostics: list[dict[str, Any]]) -> int:
    active = [item for item in diagnostics if item.get("disposition") == "active"]
    if any(item.get("configuration") for item in active):
        return 2
    if any(item.get("severity") == "MUST" for item in active):
        return 1
    return 0


def run_gate(
    *,
    phase: str,
    manifest_path: Path,
    adoption_path: Path | None,
    baseline_path: Path | None,
    previous_baseline_path: Path | None,
    check_adoption_docs: bool = True,
) -> tuple[int, dict[str, Any]]:
    if phase not in PHASES:
        raise ValueError(f"unsupported gate phase: {phase}")
    manifest = load_yaml(manifest_path)
    project_root = manifest_path.resolve().parent.parent
    diagnostics = [
        _as_dict(item)
        for item in validate_manifest(
            manifest,
            manifest_path,
            None,
            None,
            check_docs=phase != "design",
        )
    ]
    analyzers: dict[str, Any] = {}
    adoption = _load_optional(adoption_path) if phase != "design" else None
    if phase != "design":
        diagnostics.extend(validate_adoption(manifest, adoption))
        typescript_diagnostics, typescript_evidence = analyze_typescript(manifest, project_root)
        diagnostics.extend(typescript_diagnostics)
        analyzers["typescript"] = typescript_evidence
        python_diagnostics, python_evidence = analyze_python(manifest, project_root)
        diagnostics.extend(
            item
            for item in python_diagnostics
            if not (
                item.get("rule_id") == "SRCAN001"
                and Path(str(item.get("location", ""))).suffix.casefold() in {".ts", ".tsx"}
            )
        )
        analyzers["python"] = python_evidence
        c_config = manifest.get("c_analyzer", {}).get("ast", {})
        if c_config.get("status") == "required":
            from c_analyzer import analyze

            c_evidence: dict[str, Any] = {}
            c_diagnostics, mode = analyze(
                manifest, manifest_path, project_root, None, c_evidence
            )
            diagnostics.extend(_as_dict(item) for item in c_diagnostics)
            analyzers["c-cpp"] = {"mode": mode, **c_evidence}
        baseline = _load_optional(baseline_path)
        previous = _load_optional(previous_baseline_path)
        diagnostics.extend(
            apply_baseline(
                diagnostics,
                baseline,
                previous,
                phase=phase,
                expected_schema_version=manifest.get("schema_version"),
            )
        )
    code = _exit_code(diagnostics)
    status = readiness_status(diagnostics, phase=phase)
    evidence = {
        "schema_version": manifest.get("schema_version"),
        "phase": phase,
        "gate_result": "PASS" if code == 0 else "BLOCKED",
        "readiness_status": status,
        "exit_code": code,
        "manifest": str(manifest_path),
        "tool_host": {
            "operating_system": sys.platform,
            "python_version": ".".join(map(str, sys.version_info[:3])),
        },
        "analyzers": analyzers,
        "diagnostics": diagnostics,
    }
    if (
        phase != "design"
        and check_adoption_docs
        and adoption is not None
    ):
        adoption_diagnostics = compare_adoption_documents(
            manifest_path,
            manifest,
            adoption,
            _load_optional(baseline_path),
            evidence,
        )
        diagnostics.extend(adoption_diagnostics)
        code = _exit_code(diagnostics)
        evidence["exit_code"] = code
        evidence["gate_result"] = "PASS" if code == 0 else "BLOCKED"
        evidence["readiness_status"] = readiness_status(
            diagnostics, phase=phase
        )
    return code, evidence


def _gate_command(args: argparse.Namespace) -> int:
    try:
        code, evidence = run_gate(
            phase=args.phase,
            manifest_path=args.manifest,
            adoption_path=args.adoption,
            baseline_path=args.baseline,
            previous_baseline_path=args.previous_baseline,
        )
    except (ManifestError, OSError, ValueError, yaml.YAMLError) as exc:
        code = 2
        evidence = {
            "schema_version": "2.2.0",
            "phase": args.phase,
            "gate_result": "BLOCKED",
            "readiness_status": "BLOCKED",
            "exit_code": code,
            "diagnostics": [
                {
                    "rule_id": "TOOL002",
                    "severity": "MUST",
                    "location": str(args.manifest),
                    "message": str(exc),
                    "configuration": True,
                    "disposition": "active",
                }
            ],
        }
    if args.format == "json":
        print(json.dumps(evidence, indent=2, ensure_ascii=False))
    else:
        for item in evidence["diagnostics"]:
            disposition = (
                ""
                if item.get("disposition") == "active"
                else f" [{item.get('disposition')}]"
            )
            print(
                f"{item.get('severity')} {item.get('rule_id')} "
                f"{item.get('location')}: {item.get('message')}{disposition}"
            )
        print(
            f"{evidence['gate_result']}: {evidence['readiness_status']} "
            f"(phase={args.phase}, exit={code})"
        )
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return code


def _bootstrap_command(args: argparse.Namespace) -> int:
    from bootstrap_project import bootstrap

    try:
        written = bootstrap(args.project_root, args.spec)
    except (FileExistsError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for path in written:
        print(path)
    return 0


def _render_command(args: argparse.Namespace) -> int:
    from render_architecture import write_documents

    try:
        manifest = load_yaml(args.manifest)
        adoption = load_yaml(args.adoption)
        baseline = _load_optional(args.baseline)
        _, evidence = run_gate(
            phase="development",
            manifest_path=args.manifest,
            adoption_path=args.adoption,
            baseline_path=args.baseline,
            previous_baseline_path=None,
            check_adoption_docs=False,
        )
        blockers = [
            item
            for item in evidence["diagnostics"]
            if item.get("disposition") == "active"
            and item.get("severity") == "MUST"
            and not str(item.get("rule_id", "")).startswith("DOC")
        ]
        if blockers:
            summary = "; ".join(
                f"{item.get('rule_id')} {item.get('location')}"
                for item in blockers[:5]
            )
            raise ValueError(
                "refusing to render from invalid authoritative inputs: " + summary
            )
        written = write_documents(manifest, args.manifest)
        written.extend(
            write_adoption_documents(
                args.manifest, manifest, adoption, baseline, evidence
            )
        )
    except (ManifestError, FileExistsError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for path in written:
        print(path)
    return 0


def _toolchain_command(args: argparse.Namespace) -> int:
    adapter = EspressifLibclangToolchainAdapter()
    try:
        evidence = (
            adapter.install(args.lock)
            if args.toolchain_command == "install"
            else adapter.verify(args.lock)
        )
    except ToolchainProviderError as exc:
        print(
            f"BLOCKED {exc.rule_id} {exc.location}: {exc.message}",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(evidence.to_dict(), indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    gate = commands.add_parser("gate", help="run one governed phase gate")
    gate.add_argument("--phase", choices=PHASES, required=True)
    gate.add_argument("--manifest", type=Path, default=Path("architecture/manifest.yaml"))
    gate.add_argument(
        "--adoption", type=Path, default=Path("architecture/adoption.yaml")
    )
    gate.add_argument(
        "--baseline", type=Path, default=Path("architecture/baseline.yaml")
    )
    gate.add_argument("--previous-baseline", type=Path)
    gate.add_argument("--format", choices=("text", "json"), default="text")
    gate.add_argument("--evidence", type=Path)
    gate.set_defaults(handler=_gate_command)

    bootstrap_parser = commands.add_parser("bootstrap", help="bootstrap governance")
    bootstrap_parser.add_argument("--project-root", required=True, type=Path)
    bootstrap_parser.add_argument("--spec", required=True, type=Path)
    bootstrap_parser.set_defaults(handler=_bootstrap_command)
    render_parser = commands.add_parser(
        "render", help="write deterministic generated governance documents"
    )
    render_parser.add_argument(
        "--manifest", type=Path, default=Path("architecture/manifest.yaml")
    )
    render_parser.add_argument(
        "--adoption", type=Path, default=Path("architecture/adoption.yaml")
    )
    render_parser.add_argument("--baseline", type=Path)
    render_parser.set_defaults(handler=_render_command)
    toolchain_parser = commands.add_parser(
        "toolchain", help="install or verify a lock-pinned native toolchain"
    )
    toolchain_commands = toolchain_parser.add_subparsers(
        dest="toolchain_command", required=True
    )
    for operation in ("install", "verify"):
        operation_parser = toolchain_commands.add_parser(operation)
        operation_parser.add_argument(
            "--lock", type=Path, default=Path("architecture/toolchain-lock.yaml")
        )
        operation_parser.set_defaults(handler=_toolchain_command)
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
