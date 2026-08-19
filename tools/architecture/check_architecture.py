#!/usr/bin/env python3
"""Validate the language-independent modular event architecture manifest."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError:  # pragma: no cover - exercised by deployment environments
    print("ERROR TOOL001: PyYAML is required (pinned version: 6.0.3).", file=sys.stderr)
    raise SystemExit(2)


STANDARD_VERSION = "2.2.0"
SCHEMA_VERSION = "2.2.0"
SUPPORTED_STANDARD_VERSIONS = {"2.1.0", STANDARD_VERSION}
SUPPORTED_SCHEMA_VERSIONS = {"2.1.0", SCHEMA_VERSION}
DESCRIPTION_STANDARD_VERSION = "1.1.0"
DESCRIPTION_SCHEMA_VERSION = "1.1.0"
LEGACY_STANDARD_VERSION = "1.0.0"
LEGACY_SCHEMA_VERSION = "1.0.0"
CORE_ENVELOPE = {
    "event_type",
    "source",
    "correlation_id",
    "stream_id",
    "sequence",
    "payload",
}
CORE_LIFECYCLE = {"received", "validated", "processing", "succeeded", "failed"}
ROLE_BY_LEVEL = {
    "L0": {"composition", "orchestration"},
    "L1": {"domain"},
    "L2": {"component"},
    "L3+": {"adapter", "technical"},
}
BANNED_AI_APPROVERS = {"ai", "assistant", "chatgpt", "codex", "gpt", "model", "openai"}


@dataclass
class Diagnostic:
    rule_id: str
    severity: str
    location: str
    message: str
    configuration: bool = False
    disposition: str = "active"


class ManifestError(Exception):
    pass


def analyze_realtime_profile(*args: Any, **kwargs: Any) -> Any:
    """Expose the manifest-validation-owned scheduling analysis seam."""
    from realtime_analysis import analyze_realtime_profile as analyze

    return analyze(*args, **kwargs)


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestError(f"cannot read YAML {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"YAML root must be a mapping: {path}")
    return data


def _diag(
    diagnostics: list[Diagnostic],
    rule_id: str,
    location: str,
    message: str,
    *,
    severity: str = "MUST",
    configuration: bool = False,
) -> None:
    diagnostics.append(Diagnostic(rule_id, severity, location, message, configuration))


def _required_mapping(
    data: dict[str, Any], key: str, diagnostics: list[Diagnostic]
) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        _diag(diagnostics, "SCH001", key, "must be a mapping", configuration=True)
        return {}
    return value


def _required_list(
    data: dict[str, Any], key: str, diagnostics: list[Diagnostic]
) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        _diag(diagnostics, "SCH002", key, "must be a list", configuration=True)
        return []
    return value


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_version(data: dict[str, Any], key: str, expected: str, diagnostics: list[Diagnostic]) -> None:
    value = data.get(key)
    if value != expected:
        _diag(
            diagnostics,
            "VER001",
            key,
            f"must be pinned to {expected!r}; got {value!r}",
            configuration=True,
        )


def _find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        if node in visiting:
            index = stack.index(node)
            return stack[index:] + [node]
        if node in visited:
            return None
        visiting.add(node)
        stack.append(node)
        for target in sorted(graph.get(node, set())):
            cycle = visit(target)
            if cycle:
                return cycle
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return None

    for candidate in sorted(graph):
        cycle = visit(candidate)
        if cycle:
            return cycle
    return None


def dependency_violation(
    source: dict[str, Any],
    target: dict[str, Any],
    port_owner_by_implementation: dict[str, set[str]],
) -> tuple[str, str] | None:
    source_level = source.get("level")
    target_level = target.get("level")
    source_role = source.get("role")

    if source_level in {"L0", "L1", "L2"} and source_level == target_level:
        return "DEP001", "L0-L2 sibling modules must be coordinated by their parent"

    if source_role == "composition":
        return None
    if source_level == "L0" and target_level != "L1":
        return "DEP002", "L0 orchestration may depend only on L1 public contracts"
    if source_level == "L1":
        if target_level != "L2" or target.get("parent") != source.get("id"):
            return "DEP002", "L1 may depend only on its child L2 public contracts"
    if source_level == "L2":
        return "DEP002", "L2 functional components must not depend on other module implementations"
    if source_level == "L3+" and target_level in {"L0", "L1", "L2"}:
        allowed_owners = port_owner_by_implementation.get(str(source.get("id")), set())
        if target.get("id") not in allowed_owners:
            return "DEP003", "L3+ may depend upward only on a public port it implements"
    return None


def _validate_manifest_v1_0(
    data: dict[str, Any],
    manifest_path: Path,
    baseline_path: Path | None = None,
    previous_baseline_path: Path | None = None,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    _check_version(data, "standard_version", LEGACY_STANDARD_VERSION, diagnostics)
    _check_version(data, "schema_version", LEGACY_SCHEMA_VERSION, diagnostics)

    project = _required_mapping(data, "project", diagnostics)
    if not _is_nonempty_string(project.get("name")):
        _diag(diagnostics, "SCH003", "project.name", "must be a non-empty string", configuration=True)

    raw_modules = _required_list(data, "modules", diagnostics)
    raw_ports = _required_list(data, "ports", diagnostics)
    raw_events = _required_list(data, "events", diagnostics)
    raw_exceptions = _required_list(data, "adr_exceptions", diagnostics)

    modules: dict[str, dict[str, Any]] = {}
    all_paths: dict[str, str] = {}
    for index, raw in enumerate(raw_modules):
        location = f"modules[{index}]"
        if not isinstance(raw, dict):
            _diag(diagnostics, "SCH004", location, "must be a mapping", configuration=True)
            continue
        module_id = raw.get("id")
        if not _is_nonempty_string(module_id):
            _diag(diagnostics, "SCH005", f"{location}.id", "must be a non-empty string", configuration=True)
            continue
        module_id = str(module_id)
        if module_id in modules:
            _diag(diagnostics, "SCH006", module_id, "duplicate module id", configuration=True)
            continue
        modules[module_id] = raw
        level = raw.get("level")
        role = raw.get("role")
        if level not in ROLE_BY_LEVEL:
            _diag(diagnostics, "LVL001", module_id, f"invalid level {level!r}", configuration=True)
        elif role not in ROLE_BY_LEVEL[level]:
            _diag(diagnostics, "LVL002", module_id, f"role {role!r} is invalid for {level}")
        if not _is_nonempty_string(raw.get("responsibility")):
            _diag(diagnostics, "MOD001", module_id, "responsibility must be non-empty", configuration=True)
        paths = raw.get("paths")
        if not isinstance(paths, list) or not paths or not all(_is_nonempty_string(item) for item in paths):
            _diag(diagnostics, "MOD002", module_id, "paths must contain project-relative strings", configuration=True)
        else:
            for path in paths:
                normalized = Path(str(path)).as_posix().rstrip("/")
                if Path(str(path)).is_absolute() or normalized.startswith("../"):
                    _diag(diagnostics, "MOD003", module_id, f"path must be project-relative: {path}", configuration=True)
                if normalized in all_paths:
                    _diag(diagnostics, "MOD004", normalized, f"path is also owned by {all_paths[normalized]}")
                all_paths[normalized] = module_id
        for list_key in ("depends_on", "implements_ports"):
            if not isinstance(raw.get(list_key), list):
                _diag(diagnostics, "SCH007", f"{module_id}.{list_key}", "must be a list", configuration=True)

    for module_id, module in modules.items():
        level = module.get("level")
        parent = module.get("parent")
        if level == "L1":
            if parent not in modules or modules.get(parent, {}).get("level") != "L0":
                _diag(diagnostics, "LVL003", module_id, "L1 parent must reference an L0 module")
        elif level == "L2":
            if parent not in modules or modules.get(parent, {}).get("level") != "L1":
                _diag(diagnostics, "LVL003", module_id, "L2 parent must reference an L1 module")
        elif parent is not None:
            _diag(diagnostics, "LVL004", module_id, "L0 and L3+ parent must be null", severity="SHOULD")

    ports: dict[str, dict[str, Any]] = {}
    port_owner_by_implementation: dict[str, set[str]] = {}
    output_count: dict[str, int] = {}
    allowed_port_kinds = {"command", "query", "event", "error", "dependency"}
    for index, raw in enumerate(raw_ports):
        location = f"ports[{index}]"
        if not isinstance(raw, dict):
            _diag(diagnostics, "SCH008", location, "must be a mapping", configuration=True)
            continue
        port_id = raw.get("id")
        if not _is_nonempty_string(port_id):
            _diag(diagnostics, "SCH009", f"{location}.id", "must be a non-empty string", configuration=True)
            continue
        port_id = str(port_id)
        if port_id in ports:
            _diag(diagnostics, "SCH010", port_id, "duplicate port id", configuration=True)
            continue
        ports[port_id] = raw
        owner = raw.get("owner")
        if owner not in modules:
            _diag(diagnostics, "PRT001", port_id, "owner must reference a module", configuration=True)
        if raw.get("direction") not in {"input", "output"}:
            _diag(diagnostics, "PRT002", port_id, "direction must be input or output", configuration=True)
        if raw.get("kind") not in allowed_port_kinds:
            _diag(diagnostics, "PRT003", port_id, "invalid port kind", configuration=True)
        if not _is_nonempty_string(raw.get("contract")):
            _diag(diagnostics, "PRT004", port_id, "contract must be a project-relative path", configuration=True)
        implemented_by = raw.get("implemented_by")
        if not isinstance(implemented_by, list):
            _diag(diagnostics, "SCH011", f"{port_id}.implemented_by", "must be a list", configuration=True)
            implemented_by = []
        for adapter in implemented_by:
            if adapter not in modules or modules.get(adapter, {}).get("level") != "L3+":
                _diag(diagnostics, "PRT005", port_id, f"implementation {adapter!r} must be an L3+ module")
            elif owner in modules:
                port_owner_by_implementation.setdefault(str(adapter), set()).add(str(owner))
        if raw.get("direction") == "output" and raw.get("kind") in {"event", "error"} and owner in modules:
            output_count[str(owner)] = output_count.get(str(owner), 0) + 1

    for owner, count in output_count.items():
        if modules[owner].get("level") in {"L0", "L1", "L2"} and count > 1:
            _diag(diagnostics, "PRT006", owner, "functional module must expose one event/error output sink")

    graph: dict[str, set[str]] = {module_id: set() for module_id in modules}
    for module_id, module in modules.items():
        for target_id in module.get("depends_on", []):
            if target_id not in modules:
                _diag(diagnostics, "DEP000", module_id, f"unknown dependency {target_id!r}", configuration=True)
                continue
            graph[module_id].add(str(target_id))
            violation = dependency_violation(module, modules[str(target_id)], port_owner_by_implementation)
            if violation:
                _diag(diagnostics, violation[0], f"{module_id}->{target_id}", violation[1])
    cycle = _find_cycle(graph)
    if cycle:
        _diag(diagnostics, "DEP004", "->".join(cycle), "module dependency cycle is forbidden")

    for module_id, module in modules.items():
        declared_ports = set(str(item) for item in module.get("implements_ports", []))
        actual_ports = {port_id for port_id, port in ports.items() if module_id in port.get("implemented_by", [])}
        if declared_ports != actual_ports:
            _diag(
                diagnostics,
                "PRT007",
                module_id,
                f"implements_ports mismatch: declared={sorted(declared_ports)}, actual={sorted(actual_ports)}",
                configuration=True,
            )

    events: set[str] = set()
    for index, raw in enumerate(raw_events):
        location = f"events[{index}]"
        if not isinstance(raw, dict):
            _diag(diagnostics, "SCH012", location, "must be a mapping", configuration=True)
            continue
        event_id = raw.get("id")
        if not _is_nonempty_string(event_id):
            _diag(diagnostics, "SCH013", f"{location}.id", "must be a non-empty string", configuration=True)
            continue
        event_id = str(event_id)
        if event_id in events:
            _diag(diagnostics, "SCH014", event_id, "duplicate event id", configuration=True)
            continue
        events.add(event_id)
        owner = raw.get("owner")
        output_port = raw.get("output_port")
        if owner not in modules:
            _diag(diagnostics, "EVT001", event_id, "owner must reference a module", configuration=True)
        if output_port not in ports:
            _diag(diagnostics, "EVT002", event_id, "output_port must reference a port", configuration=True)
        else:
            port = ports[str(output_port)]
            if port.get("owner") != owner or port.get("direction") != "output":
                _diag(diagnostics, "EVT003", event_id, "output_port must be an output owned by the event owner")
        envelope = raw.get("envelope")
        if not isinstance(envelope, list):
            _diag(diagnostics, "EVT004", event_id, "envelope must be a list", configuration=True)
        else:
            missing = CORE_ENVELOPE.difference(str(item) for item in envelope)
            if missing:
                _diag(diagnostics, "EVT004", event_id, f"missing envelope fields: {sorted(missing)}")
        lifecycle = raw.get("lifecycle")
        if not isinstance(lifecycle, list):
            _diag(diagnostics, "EVT005", event_id, "lifecycle must be a list", configuration=True)
        else:
            missing = CORE_LIFECYCLE.difference(str(item) for item in lifecycle)
            if missing:
                _diag(diagnostics, "EVT005", event_id, f"missing lifecycle states: {sorted(missing)}")
        delivery = raw.get("delivery")
        if delivery not in {"at-most-once", "at-least-once"}:
            _diag(diagnostics, "EVT006", event_id, "delivery must be at-most-once or at-least-once", configuration=True)
        if delivery == "at-least-once" and not _is_nonempty_string(raw.get("idempotency")):
            _diag(diagnostics, "EVT007", event_id, "at-least-once requires an idempotency strategy")

    valid_exceptions: list[dict[str, Any]] = []
    manifest_dir = manifest_path.parent
    for index, raw in enumerate(raw_exceptions):
        location = f"adr_exceptions[{index}]"
        if not isinstance(raw, dict):
            _diag(diagnostics, "ADR001", location, "must be a mapping", configuration=True)
            continue
        required = ("rule_id", "scope", "adr", "status", "approved_by", "approval_reference")
        if any(not _is_nonempty_string(raw.get(key)) for key in required):
            _diag(diagnostics, "ADR001", location, "accepted exception requires rule, scope, ADR, approver, and approval reference")
            continue
        if raw.get("status") != "accepted":
            _diag(diagnostics, "ADR002", location, "only accepted ADRs can suppress a MUST rule")
            continue
        approver_words = set(re.findall(r"[a-z]+", str(raw.get("approved_by", "")).lower()))
        if approver_words.intersection(BANNED_AI_APPROVERS):
            _diag(diagnostics, "ADR003", location, "AI systems cannot approve their own architecture exception")
            continue
        adr_path = manifest_dir / str(raw["adr"])
        if not adr_path.is_file():
            _diag(diagnostics, "ADR004", location, f"ADR file does not exist: {raw['adr']}")
            continue
        valid_exceptions.append(raw)

    baseline_entries: set[tuple[str, str]] = set()
    if baseline_path is not None:
        try:
            baseline = load_yaml(baseline_path)
            if baseline.get("schema_version") != LEGACY_SCHEMA_VERSION:
                _diag(diagnostics, "BAS001", str(baseline_path), "baseline schema version mismatch", configuration=True)
            violations = baseline.get("violations")
            if not isinstance(violations, list):
                _diag(diagnostics, "BAS002", str(baseline_path), "violations must be a list", configuration=True)
            else:
                for entry in violations:
                    if isinstance(entry, dict) and _is_nonempty_string(entry.get("rule_id")) and _is_nonempty_string(entry.get("location")):
                        baseline_entries.add((str(entry["rule_id"]), str(entry["location"])))
                    else:
                        _diag(diagnostics, "BAS003", str(baseline_path), "invalid baseline entry", configuration=True)
        except ManifestError as exc:
            _diag(diagnostics, "BAS000", str(baseline_path), str(exc), configuration=True)

    if previous_baseline_path is not None:
        previous_entries: set[tuple[str, str]] = set()
        try:
            previous = load_yaml(previous_baseline_path)
            for entry in previous.get("violations", []):
                if isinstance(entry, dict) and _is_nonempty_string(entry.get("rule_id")) and _is_nonempty_string(entry.get("location")):
                    previous_entries.add((str(entry["rule_id"]), str(entry["location"])))
            for rule_id, location in sorted(baseline_entries.difference(previous_entries)):
                _diag(diagnostics, "BAS004", f"{rule_id}:{location}", "baseline growth is forbidden; fix the violation or obtain a user-approved ADR")
        except ManifestError as exc:
            _diag(diagnostics, "BAS000", str(previous_baseline_path), str(exc), configuration=True)

    protected_rules = {"ADR001", "ADR002", "ADR003", "ADR004", "BAS000", "BAS001", "BAS002", "BAS003", "BAS004"}
    for diagnostic in diagnostics:
        if diagnostic.configuration or diagnostic.rule_id in protected_rules:
            continue
        if (diagnostic.rule_id, diagnostic.location) in baseline_entries:
            diagnostic.disposition = "baseline"
            continue
        for exception in valid_exceptions:
            scope = str(exception["scope"])
            if diagnostic.rule_id == exception["rule_id"] and diagnostic.location.startswith(scope):
                diagnostic.disposition = f"adr:{exception['adr']}"
                break
    return diagnostics


def validate_manifest(
    data: dict[str, Any],
    manifest_path: Path,
    baseline_path: Path | None = None,
    previous_baseline_path: Path | None = None,
    *,
    check_docs: bool = False,
) -> list[Diagnostic]:
    """Validate an exact supported public schema/standard version pair."""
    schema_version = data.get("schema_version")
    standard_version = data.get("standard_version")
    if schema_version in SUPPORTED_SCHEMA_VERSIONS:
        from schema_v2 import validate_manifest_v2

        return validate_manifest_v2(
            data,
            manifest_path,
            baseline_path,
            previous_baseline_path,
            check_docs=check_docs,
        )
    diagnostics: list[Diagnostic] = []
    _diag(
        diagnostics,
        "VER002",
        "schema_version",
        (
            f"unsupported schema version {schema_version!r}; supported: "
            f"{sorted(SUPPORTED_SCHEMA_VERSIONS)!r}"
        ),
        configuration=True,
    )
    if standard_version not in SUPPORTED_STANDARD_VERSIONS:
        _diag(
            diagnostics,
            "VER003",
            "standard_version",
            (
                f"unsupported standard version {standard_version!r}; supported: "
                f"{sorted(SUPPORTED_STANDARD_VERSIONS)!r}"
            ),
            configuration=True,
        )
    return diagnostics


def exit_code(diagnostics: Iterable[Diagnostic]) -> int:
    diagnostics = list(diagnostics)
    if any(item.configuration and item.disposition == "active" for item in diagnostics):
        return 2
    if any(item.severity == "MUST" and item.disposition == "active" for item in diagnostics):
        return 1
    return 0


def render_text(diagnostics: list[Diagnostic]) -> str:
    if not diagnostics:
        return "PASS: no architecture diagnostics"
    lines: list[str] = []
    for item in diagnostics:
        disposition = "" if item.disposition == "active" else f" [{item.disposition}]"
        lines.append(f"{item.severity} {item.rule_id} {item.location}: {item.message}{disposition}")
    code = exit_code(diagnostics)
    lines.append("PASS" if code == 0 else ("FAIL" if code == 1 else "ERROR"))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--previous-baseline", type=Path)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    try:
        data = load_yaml(args.manifest)
        diagnostics = validate_manifest(
            data,
            args.manifest,
            args.baseline,
            args.previous_baseline,
            check_docs=True,
        )
    except ManifestError as exc:
        diagnostics = [Diagnostic("TOOL002", "MUST", str(args.manifest), str(exc), True)]
    if args.format == "json":
        print(json.dumps({"exit_code": exit_code(diagnostics), "diagnostics": [asdict(item) for item in diagnostics]}, indent=2))
    else:
        print(render_text(diagnostics))
    return exit_code(diagnostics)


if __name__ == "__main__":
    print(
        "ERROR: direct legacy CLI removed; use architecture_cli.py gate instead.",
        file=sys.stderr,
    )
    raise SystemExit(2)
