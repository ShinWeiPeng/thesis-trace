"""Schema 1.1 description, navigation, and flow validation."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from check_architecture import (
    BANNED_AI_APPROVERS,
    LEGACY_SCHEMA_VERSION,
    LEGACY_STANDARD_VERSION,
    DESCRIPTION_SCHEMA_VERSION,
    DESCRIPTION_STANDARD_VERSION,
    Diagnostic,
    ManifestError,
    _diag,
    _is_nonempty_string,
    _validate_manifest_v1_0,
    load_yaml,
)


ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
ANALYZED_SUFFIXES = {".c", ".h", ".cc", ".cpp", ".hh", ".hpp", ".py", ".ts", ".tsx"}
PROTECTED_RULES = {
    "ADR001",
    "ADR002",
    "ADR003",
    "ADR004",
    "BAS000",
    "BAS001",
    "BAS002",
    "BAS003",
    "BAS004",
}


def _placeholder(value: Any) -> bool:
    return not _is_nonempty_string(value) or "TODO" in str(value).upper()


def _mapping(value: Any, diagnostics: list[Diagnostic], rule: str, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _diag(diagnostics, rule, location, "must be a mapping", configuration=True)
        return {}
    return value


def _list(value: Any, diagnostics: list[Diagnostic], rule: str, location: str) -> list[Any]:
    if not isinstance(value, list):
        _diag(diagnostics, rule, location, "must be a list", configuration=True)
        return []
    return value


def _string_list(value: Any, diagnostics: list[Diagnostic], rule: str, location: str) -> list[str]:
    values = _list(value, diagnostics, rule, location)
    if not all(_is_nonempty_string(item) for item in values):
        _diag(diagnostics, rule, location, "must contain only non-empty strings", configuration=True)
    return [str(item) for item in values if _is_nonempty_string(item)]


def _symbol_entries(
    module_id: str,
    field: str,
    value: Any,
    status: str,
    diagnostics: list[Diagnostic],
) -> list[dict[str, Any]]:
    entries = _list(value, diagnostics, "SYM001", f"{module_id}.{field}")
    if not entries:
        _diag(diagnostics, "SYM002", f"{module_id}.{field}", "must declare at least one code symbol")
    parsed: list[dict[str, Any]] = []
    for index, raw in enumerate(entries):
        location = f"{module_id}.{field}[{index}]"
        entry = _mapping(raw, diagnostics, "SYM001", location)
        for key in ("path", "symbol", "kind"):
            if not _is_nonempty_string(entry.get(key)):
                _diag(diagnostics, "SYM001", f"{location}.{key}", "must be a non-empty string", configuration=True)
            elif status == "implemented" and _placeholder(entry.get(key)):
                _diag(diagnostics, "SYM003", f"{location}.{key}", "implemented module cannot contain a TODO symbol placeholder")
        declared_path = Path(str(entry.get("path", "")))
        if declared_path.is_absolute() or ".." in declared_path.parts:
            _diag(diagnostics, "SYM005", f"{location}.path", "must be a project-relative path without parent traversal", configuration=True)
        parsed.append(entry)
    return parsed


def _check_declared_path(
    project_root: Path,
    declared: Any,
    location: str,
    status: str,
    rule: str,
    diagnostics: list[Diagnostic],
) -> None:
    if not _is_nonempty_string(declared):
        return
    relative = Path(str(declared))
    if relative.is_absolute() or ".." in relative.parts:
        return
    if not (project_root / relative).exists():
        severity = "SHOULD" if status == "planned" else "MUST"
        _diag(diagnostics, rule, location, f"declared path does not exist: {declared}", severity=severity)


def _apply_governance(
    diagnostics: list[Diagnostic],
    data: dict[str, Any],
    manifest_path: Path,
    baseline_path: Path | None,
    previous_baseline_path: Path | None,
) -> None:
    valid_exceptions: list[dict[str, Any]] = []
    for raw in data.get("adr_exceptions", []):
        if not isinstance(raw, dict) or raw.get("status") != "accepted":
            continue
        approver_words = set(re.findall(r"[a-z]+", str(raw.get("approved_by", "")).lower()))
        adr_path = manifest_path.parent / str(raw.get("adr", ""))
        if (
            _is_nonempty_string(raw.get("rule_id"))
            and _is_nonempty_string(raw.get("scope"))
            and _is_nonempty_string(raw.get("approval_reference"))
            and not approver_words.intersection(BANNED_AI_APPROVERS)
            and adr_path.is_file()
        ):
            valid_exceptions.append(raw)

    baseline_entries: set[tuple[str, str]] = set()
    if baseline_path is not None:
        try:
            baseline = load_yaml(baseline_path)
            if baseline.get("schema_version") != DESCRIPTION_SCHEMA_VERSION:
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
                _diag(diagnostics, "BAS004", f"{rule_id}:{location}", "baseline growth is forbidden")
        except ManifestError as exc:
            _diag(diagnostics, "BAS000", str(previous_baseline_path), str(exc), configuration=True)

    for diagnostic in diagnostics:
        if diagnostic.configuration or diagnostic.rule_id in PROTECTED_RULES or diagnostic.disposition != "active":
            continue
        if (diagnostic.rule_id, diagnostic.location) in baseline_entries:
            diagnostic.disposition = "baseline"
            continue
        for exception in valid_exceptions:
            if diagnostic.rule_id == exception["rule_id"] and diagnostic.location.startswith(str(exception["scope"])):
                diagnostic.disposition = f"adr:{exception['adr']}"
                break


def validate_description_manifest(
    data: dict[str, Any],
    manifest_path: Path,
    baseline_path: Path | None = None,
    previous_baseline_path: Path | None = None,
    *,
    check_docs: bool = False,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    project_root = manifest_path.parent.parent
    if data.get("standard_version") != DESCRIPTION_STANDARD_VERSION:
        _diag(diagnostics, "VER001", "standard_version", f"must equal {DESCRIPTION_STANDARD_VERSION!r}", configuration=True)
    if data.get("schema_version") != DESCRIPTION_SCHEMA_VERSION:
        _diag(diagnostics, "VER001", "schema_version", f"must equal {DESCRIPTION_SCHEMA_VERSION!r}", configuration=True)

    project = _mapping(data.get("project"), diagnostics, "SCH001", "project")
    if not _is_nonempty_string(project.get("documentation_language")):
        _diag(diagnostics, "DESC001", "project.documentation_language", "must be a non-empty language tag", configuration=True)

    raw_modules = _list(data.get("modules"), diagnostics, "SCH002", "modules")
    raw_ports = _list(data.get("ports"), diagnostics, "SCH002", "ports")
    raw_events = _list(data.get("events"), diagnostics, "SCH002", "events")
    raw_flows = _list(data.get("flows"), diagnostics, "SCH002", "flows")

    projected = copy.deepcopy(data)
    projected["standard_version"] = LEGACY_STANDARD_VERSION
    projected["schema_version"] = LEGACY_SCHEMA_VERSION
    for raw in projected.get("modules", []):
        if isinstance(raw, dict):
            description = raw.get("description") if isinstance(raw.get("description"), dict) else {}
            raw["responsibility"] = description.get("purpose", "missing description purpose")
    base = _validate_manifest_v1_0(projected, manifest_path)
    diagnostics.extend(base)

    modules = {str(raw.get("id")): raw for raw in raw_modules if isinstance(raw, dict) and _is_nonempty_string(raw.get("id"))}
    ports = {str(raw.get("id")): raw for raw in raw_ports if isinstance(raw, dict) and _is_nonempty_string(raw.get("id"))}
    events = {str(raw.get("id")): raw for raw in raw_events if isinstance(raw, dict) and _is_nonempty_string(raw.get("id"))}

    for module_id, module in modules.items():
        if not ID_PATTERN.fullmatch(module_id):
            _diag(diagnostics, "DESC002", module_id, "id must use lowercase letters, digits, dots, underscores, or hyphens", configuration=True)
        if "responsibility" in module:
            _diag(diagnostics, "DESC003", module_id, "schema 1.1 replaces responsibility with description.purpose")
        status = module.get("implementation_status")
        if status not in {"planned", "implemented"}:
            _diag(diagnostics, "DESC004", f"{module_id}.implementation_status", "must be planned or implemented", configuration=True)
            status = "planned"
        description = _mapping(module.get("description"), diagnostics, "DESC005", f"{module_id}.description")
        purpose = description.get("purpose")
        if not _is_nonempty_string(purpose):
            _diag(diagnostics, "DESC006", f"{module_id}.description.purpose", "must be non-empty", configuration=True)
        elif status == "implemented" and _placeholder(purpose):
            _diag(diagnostics, "DESC007", f"{module_id}.description.purpose", "implemented module cannot contain TODO text")

        input_ports = _string_list(description.get("input_ports"), diagnostics, "DESC008", f"{module_id}.description.input_ports")
        output_ports = _string_list(description.get("output_ports"), diagnostics, "DESC008", f"{module_id}.description.output_ports")
        emitted_events = _string_list(description.get("emitted_events"), diagnostics, "DESC008", f"{module_id}.description.emitted_events")
        for port_id in input_ports:
            if port_id not in ports or ports[port_id].get("owner") != module_id or ports[port_id].get("direction") != "input":
                _diag(diagnostics, "REF001", f"{module_id}.description.input_ports", f"invalid owned input port {port_id!r}")
        for port_id in output_ports:
            if port_id not in ports or ports[port_id].get("owner") != module_id or ports[port_id].get("direction") != "output":
                _diag(diagnostics, "REF002", f"{module_id}.description.output_ports", f"invalid owned output port {port_id!r}")
        for event_id in emitted_events:
            if event_id not in events or events[event_id].get("owner") != module_id:
                _diag(diagnostics, "REF003", f"{module_id}.description.emitted_events", f"invalid owned event {event_id!r}")

        states = _list(description.get("owned_state"), diagnostics, "DESC009", f"{module_id}.description.owned_state")
        for index, raw_state in enumerate(states):
            state = _mapping(raw_state, diagnostics, "DESC009", f"{module_id}.description.owned_state[{index}]")
            if not _is_nonempty_string(state.get("name")) or not _is_nonempty_string(state.get("description")):
                _diag(diagnostics, "DESC009", f"{module_id}.description.owned_state[{index}]", "requires name and description", configuration=True)

        effects = _list(description.get("side_effects"), diagnostics, "DESC010", f"{module_id}.description.side_effects")
        for index, raw_effect in enumerate(effects):
            effect = _mapping(raw_effect, diagnostics, "DESC010", f"{module_id}.description.side_effects[{index}]")
            if not _is_nonempty_string(effect.get("description")):
                _diag(diagnostics, "DESC010", f"{module_id}.description.side_effects[{index}].description", "must be non-empty", configuration=True)
            via_port = effect.get("via_port")
            if via_port is not None and via_port not in ports:
                _diag(diagnostics, "REF004", f"{module_id}.description.side_effects[{index}].via_port", f"unknown port {via_port!r}")

        errors = _list(description.get("errors"), diagnostics, "DESC011", f"{module_id}.description.errors")
        for index, raw_error in enumerate(errors):
            error = _mapping(raw_error, diagnostics, "DESC011", f"{module_id}.description.errors[{index}]")
            for key in ("id", "condition", "event", "handling"):
                if not _is_nonempty_string(error.get(key)):
                    _diag(diagnostics, "DESC011", f"{module_id}.description.errors[{index}].{key}", "must be non-empty", configuration=True)
            if _is_nonempty_string(error.get("event")) and error["event"] not in events:
                _diag(diagnostics, "REF005", f"{module_id}.description.errors[{index}].event", f"unknown event {error['event']!r}")
        _string_list(description.get("invariants"), diagnostics, "DESC012", f"{module_id}.description.invariants")

        entrypoints = _symbol_entries(module_id, "entrypoints", module.get("entrypoints"), str(status), diagnostics)
        public_symbols = _symbol_entries(module_id, "public_symbols", module.get("public_symbols"), str(status), diagnostics)
        for path_index, declared in enumerate(module.get("paths", [])):
            _check_declared_path(project_root, declared, f"{module_id}.paths[{path_index}]", str(status), "PATH001", diagnostics)
        for field, entries in (("entrypoints", entrypoints), ("public_symbols", public_symbols)):
            for symbol_index, entry in enumerate(entries):
                _check_declared_path(
                    project_root,
                    entry.get("path"),
                    f"{module_id}.{field}[{symbol_index}].path",
                    str(status),
                    "PATH002",
                    diagnostics,
                )
        suffixes = {Path(str(entry.get("path", ""))).suffix.lower() for entry in entrypoints + public_symbols}
        if suffixes and not suffixes.issubset(ANALYZED_SUFFIXES):
            _diag(diagnostics, "SYM004", module_id, "one or more symbols have no installed language analyzer", severity="SHOULD")

    for port_id, port in ports.items():
        description = _mapping(port.get("description"), diagnostics, "PRD001", f"{port_id}.description")
        owner_status = modules.get(str(port.get("owner")), {}).get("implementation_status")
        for key in ("purpose", "data"):
            if not _is_nonempty_string(description.get(key)):
                _diag(diagnostics, "PRD002", f"{port_id}.description.{key}", "must be non-empty", configuration=True)
            elif owner_status == "implemented" and _placeholder(description.get(key)):
                _diag(diagnostics, "PRD006", f"{port_id}.description.{key}", "implemented port cannot contain TODO text")
        if description.get("timing") not in {"sync", "async"}:
            _diag(diagnostics, "PRD003", f"{port_id}.description.timing", "must be sync or async", configuration=True)
        rejections = _list(description.get("immediate_rejections"), diagnostics, "PRD004", f"{port_id}.description.immediate_rejections")
        for index, raw_rejection in enumerate(rejections):
            rejection = _mapping(raw_rejection, diagnostics, "PRD004", f"{port_id}.description.immediate_rejections[{index}]")
            if not _is_nonempty_string(rejection.get("code")) or not _is_nonempty_string(rejection.get("condition")):
                _diag(diagnostics, "PRD004", f"{port_id}.description.immediate_rejections[{index}]", "requires code and condition", configuration=True)
        symbols = _string_list(port.get("symbols"), diagnostics, "PRD005", f"{port_id}.symbols")
        owner = modules.get(str(port.get("owner")), {})
        owner_symbols = {str(item.get("symbol")) for item in owner.get("public_symbols", []) if isinstance(item, dict)}
        for symbol in symbols:
            if symbol not in owner_symbols:
                _diag(diagnostics, "REF006", f"{port_id}.symbols", f"symbol {symbol!r} is not declared by the owner module")

    for event_id, event in events.items():
        description = _mapping(event.get("description"), diagnostics, "EVD001", f"{event_id}.description")
        owner_status = modules.get(str(event.get("owner")), {}).get("implementation_status")
        for key in ("purpose", "emitted_when"):
            if not _is_nonempty_string(description.get(key)):
                _diag(diagnostics, "EVD002", f"{event_id}.description.{key}", "must be non-empty", configuration=True)
            elif owner_status == "implemented" and _placeholder(description.get(key)):
                _diag(diagnostics, "EVD005", f"{event_id}.description.{key}", "implemented event cannot contain TODO text")
        fields = _list(description.get("payload_fields"), diagnostics, "EVD003", f"{event_id}.description.payload_fields")
        for index, raw_field in enumerate(fields):
            field = _mapping(raw_field, diagnostics, "EVD003", f"{event_id}.description.payload_fields[{index}]")
            if any(not _is_nonempty_string(field.get(key)) for key in ("name", "type", "meaning")):
                _diag(diagnostics, "EVD003", f"{event_id}.description.payload_fields[{index}]", "requires name, type, and meaning", configuration=True)
        consumers = _string_list(description.get("intended_consumers"), diagnostics, "EVD004", f"{event_id}.description.intended_consumers")
        for consumer in consumers:
            if consumer not in modules:
                _diag(diagnostics, "REF007", f"{event_id}.description.intended_consumers", f"unknown module {consumer!r}")

    referenced: set[str] = set()
    flow_ids: set[str] = set()
    for index, raw_flow in enumerate(raw_flows):
        location = f"flows[{index}]"
        flow = _mapping(raw_flow, diagnostics, "FLW001", location)
        flow_id = flow.get("id")
        if not _is_nonempty_string(flow_id) or not ID_PATTERN.fullmatch(str(flow_id)):
            _diag(diagnostics, "FLW001", f"{location}.id", "must be a stable lowercase id", configuration=True)
            flow_id = location
        if str(flow_id) in flow_ids:
            _diag(diagnostics, "FLW002", str(flow_id), "duplicate flow id", configuration=True)
        flow_ids.add(str(flow_id))
        owner = modules.get(str(flow.get("owner")))
        if owner is None or owner.get("level") not in {"L0", "L1"}:
            _diag(diagnostics, "FLW003", str(flow_id), "flow owner must be an L0 or L1 module")
        if not _is_nonempty_string(flow.get("description")):
            _diag(diagnostics, "FLW004", f"{flow_id}.description", "must be non-empty", configuration=True)
        trigger = _mapping(flow.get("trigger"), diagnostics, "FLW005", f"{flow_id}.trigger")
        kind = trigger.get("kind")
        ref = trigger.get("ref")
        if kind not in {"command", "event", "condition"}:
            _diag(diagnostics, "FLW005", f"{flow_id}.trigger.kind", "must be command, event, or condition", configuration=True)
        if not _is_nonempty_string(ref) or not _is_nonempty_string(trigger.get("description")):
            _diag(diagnostics, "FLW005", f"{flow_id}.trigger", "requires ref and description", configuration=True)
        elif kind == "command" and ref not in ports:
            _diag(diagnostics, "REF008", f"{flow_id}.trigger.ref", f"unknown command port {ref!r}")
        elif kind == "event" and ref not in events:
            _diag(diagnostics, "REF008", f"{flow_id}.trigger.ref", f"unknown event {ref!r}")
        referenced.add(str(ref))

        steps = _list(flow.get("steps"), diagnostics, "FLW006", f"{flow_id}.steps")
        orders: list[int] = []
        for step_index, raw_step in enumerate(steps):
            step = _mapping(raw_step, diagnostics, "FLW006", f"{flow_id}.steps[{step_index}]")
            order = step.get("order")
            if not isinstance(order, int):
                _diag(diagnostics, "FLW007", f"{flow_id}.steps[{step_index}].order", "must be an integer", configuration=True)
            else:
                orders.append(order)
            if step.get("module") not in modules:
                _diag(diagnostics, "REF009", f"{flow_id}.steps[{step_index}].module", f"unknown module {step.get('module')!r}")
            if not _is_nonempty_string(step.get("action")):
                _diag(diagnostics, "FLW008", f"{flow_id}.steps[{step_index}].action", "must be non-empty", configuration=True)
            for key in ("receives", "emits"):
                refs = _string_list(step.get(key), diagnostics, "FLW009", f"{flow_id}.steps[{step_index}].{key}")
                for item in refs:
                    if item not in ports and item not in events:
                        _diag(diagnostics, "REF010", f"{flow_id}.steps[{step_index}].{key}", f"unknown port or event {item!r}")
                    referenced.add(item)
            _string_list(step.get("state_changes"), diagnostics, "FLW010", f"{flow_id}.steps[{step_index}].state_changes")
            _string_list(step.get("side_effects"), diagnostics, "FLW010", f"{flow_id}.steps[{step_index}].side_effects")
        if orders != list(range(1, len(steps) + 1)):
            _diag(diagnostics, "FLW011", f"{flow_id}.steps", "step order must be unique and contiguous starting at 1")

        success = _mapping(flow.get("success"), diagnostics, "FLW012", f"{flow_id}.success")
        if not _is_nonempty_string(success.get("result")):
            _diag(diagnostics, "FLW012", f"{flow_id}.success.result", "must be non-empty", configuration=True)
        for event_ref in _string_list(success.get("events"), diagnostics, "FLW012", f"{flow_id}.success.events"):
            if event_ref not in events:
                _diag(diagnostics, "REF011", f"{flow_id}.success.events", f"unknown event {event_ref!r}")
            referenced.add(event_ref)
        for error_index, raw_error in enumerate(_list(flow.get("errors"), diagnostics, "FLW013", f"{flow_id}.errors")):
            error = _mapping(raw_error, diagnostics, "FLW013", f"{flow_id}.errors[{error_index}]")
            for key in ("condition", "event", "handling"):
                if not _is_nonempty_string(error.get(key)):
                    _diag(diagnostics, "FLW013", f"{flow_id}.errors[{error_index}].{key}", "must be non-empty", configuration=True)
            if _is_nonempty_string(error.get("event")) and error["event"] not in events:
                _diag(diagnostics, "REF012", f"{flow_id}.errors[{error_index}].event", f"unknown event {error['event']!r}")
            referenced.add(str(error.get("event")))

    for port_id, port in ports.items():
        if port.get("kind") == "command" and port.get("direction") == "input" and port_id not in referenced:
            _diag(diagnostics, "FLW014", port_id, "public command is not referenced by a flow", severity="SHOULD")
    for event_id in events:
        if event_id not in referenced:
            _diag(diagnostics, "FLW015", event_id, "event is not referenced by a flow", severity="SHOULD")

    if check_docs and not any(item.configuration and item.disposition == "active" for item in diagnostics):
        from render_architecture import compare_documents

        for rule_id, location, message in compare_documents(data, manifest_path):
            _diag(diagnostics, rule_id, location, message)

    _apply_governance(diagnostics, data, manifest_path, baseline_path, previous_baseline_path)
    return diagnostics
