#!/usr/bin/env python3
"""Analyze C/C++ dependencies, public contracts, and configured source symbols."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ast_analyzer import analyze_ast
from check_architecture import (
    BANNED_AI_APPROVERS,
    Diagnostic,
    ManifestError,
    dependency_violation,
    exit_code,
    load_yaml,
    render_text,
    validate_manifest,
)
from source_sets import classify_path


SOURCE_SUFFIXES = {".c", ".h", ".cc", ".cpp", ".hh", ".hpp"}
INCLUDE_PATTERN = re.compile(r'^\s*#\s*include\s*"([^"]+)"')
SYSTEM_INCLUDE_PATTERN = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]')


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _relative_display(path: Path, root: Path) -> str:
    """Return a stable relative path even when Windows mixes 8.3 and long names."""
    resolved = path.resolve()
    if os.name == "nt":
        for ancestor in (resolved.parent, *resolved.parents):
            try:
                if os.path.samefile(ancestor, root):
                    return resolved.relative_to(ancestor).as_posix()
            except OSError:
                continue
    return Path(os.path.relpath(str(path), str(root))).as_posix()


def _module_roots(project_root: Path, modules: dict[str, dict[str, Any]]) -> dict[str, list[Path]]:
    return {
        module_id: [(project_root / str(item)).resolve() for item in module.get("paths", [])]
        for module_id, module in modules.items()
    }


def _owner(path: Path, roots: dict[str, list[Path]]) -> str | None:
    candidates: list[tuple[int, str]] = []
    for module_id, module_roots in roots.items():
        for root in module_roots:
            if _inside(path, root):
                candidates.append((len(root.parts), module_id))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _source_files(
    project_root: Path,
    roots: dict[str, list[Path]],
    compile_commands: Path | None,
) -> tuple[list[Path], str, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    if compile_commands and compile_commands.is_file():
        try:
            entries = json.loads(compile_commands.read_text(encoding="utf-8"))
            files = []
            for entry in entries:
                if not isinstance(entry, dict) or "file" not in entry:
                    continue
                candidate = Path(str(entry["file"]))
                if not candidate.is_absolute():
                    candidate = Path(str(entry.get("directory", project_root))) / candidate
                candidate = candidate.resolve()
                if candidate.suffix.lower() in SOURCE_SUFFIXES and _inside(candidate, project_root):
                    files.append(candidate)
            return sorted(set(files)), "compile_commands+lexical", diagnostics
        except (OSError, json.JSONDecodeError) as exc:
            diagnostics.append(Diagnostic("CTOOL001", "MUST", str(compile_commands), f"invalid compile_commands.json: {exc}", True))
            return [], "compile_commands+lexical", diagnostics
    files: set[Path] = set()
    for module_roots in roots.values():
        for root in module_roots:
            if root.is_dir():
                files.update(path.resolve() for path in root.rglob("*") if path.suffix.lower() in SOURCE_SUFFIXES)
    return sorted(files), "lexical", diagnostics


def _resolve_include(
    include: str,
    source: Path,
    project_root: Path,
    known_files: list[Path],
) -> Path | None:
    direct = (source.parent / include).resolve()
    if direct.is_file() and _inside(direct, project_root):
        return direct
    root_relative = (project_root / include).resolve()
    if root_relative.is_file() and _inside(root_relative, project_root):
        return root_relative
    normalized = Path(include).as_posix()
    matches = [path for path in known_files if path.as_posix().endswith("/" + normalized)]
    return matches[0] if len(matches) == 1 else None


def _cycle(graph: dict[str, set[str]]) -> list[str] | None:
    active: list[str] = []
    done: set[str] = set()

    def visit(node: str) -> list[str] | None:
        if node in active:
            index = active.index(node)
            return active[index:] + [node]
        if node in done:
            return None
        active.append(node)
        for target in sorted(graph.get(node, set())):
            found = visit(target)
            if found:
                return found
        active.pop()
        done.add(node)
        return None

    for node in sorted(graph):
        found = visit(node)
        if found:
            return found
    return None


def _configured_forbidden_source_symbols(
    config: dict[str, Any],
    diagnostics: list[Diagnostic],
) -> list[str]:
    if "forbidden_source_symbols" not in config:
        return []
    raw = config["forbidden_source_symbols"]
    if not isinstance(raw, list) or any(
        not isinstance(item, str) or not item.strip() for item in raw
    ):
        diagnostics.append(
            Diagnostic(
                "CTOOL003",
                "MUST",
                "c_analyzer.forbidden_source_symbols",
                "must be a list of non-empty strings",
                True,
            )
        )
        return []
    return list(dict.fromkeys(item.strip() for item in raw))


def _identifier_occurrences(content: str, forbidden: set[str]) -> list[tuple[int, str]]:
    """Return exact forbidden identifiers outside comments and literals."""
    occurrences: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    index = 0
    line = 1
    state = "code"
    length = len(content)
    while index < length:
        char = content[index]
        following = content[index + 1] if index + 1 < length else ""
        if state == "code":
            if char == "/" and following == "/":
                state = "line_comment"
                index += 2
                continue
            if char == "/" and following == "*":
                state = "block_comment"
                index += 2
                continue
            if char == '"':
                state = "string"
                index += 1
                continue
            if char == "'":
                state = "character"
                index += 1
                continue
            if char == "_" or char.isalpha():
                end = index + 1
                while end < length and (content[end] == "_" or content[end].isalnum()):
                    end += 1
                identifier = content[index:end]
                key = (line, identifier)
                if identifier in forbidden and key not in seen:
                    occurrences.append(key)
                    seen.add(key)
                index = end
                continue
        elif state == "line_comment":
            if char == "\n":
                state = "code"
        elif state == "block_comment":
            if char == "*" and following == "/":
                state = "code"
                index += 2
                continue
        elif state in {"string", "character"}:
            if char == "\\":
                if following == "\n":
                    line += 1
                index += 2
                continue
            if (state == "string" and char == '"') or (
                state == "character" and char == "'"
            ):
                state = "code"
        if char == "\n":
            line += 1
        index += 1
    return occurrences


def _configured_string_list(
    value: Any,
    diagnostics: list[Diagnostic],
    location: str,
) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        diagnostics.append(
            Diagnostic(
                "CTOOL004",
                "MUST",
                location,
                "must be a list of non-empty strings",
                True,
            )
        )
        return []
    return list(dict.fromkeys(item.strip() for item in value))


def _functional_boundary(
    config: dict[str, Any],
    diagnostics: list[Diagnostic],
) -> tuple[str, list[str], list[str]]:
    boundary = config.get("functional_boundary")
    if not isinstance(boundary, dict):
        diagnostics.append(
            Diagnostic(
                "CTOOL004",
                "MUST",
                "c_analyzer.functional_boundary",
                "schema 2.1.0/2.2.0 requires a functional-boundary mapping",
                True,
            )
        )
        return "invalid", [], []
    status = boundary.get("status")
    if status not in {"configured", "not-applicable"}:
        diagnostics.append(
            Diagnostic(
                "CTOOL004",
                "MUST",
                "c_analyzer.functional_boundary.status",
                "must be configured or not-applicable",
                True,
            )
        )
        return "invalid", [], []
    rationale = boundary.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        diagnostics.append(
            Diagnostic(
                "CTOOL004",
                "MUST",
                "c_analyzer.functional_boundary.rationale",
                "must be a non-empty explanation",
                True,
            )
        )
    includes = _configured_string_list(
        boundary.get("forbidden_includes", []),
        diagnostics,
        "c_analyzer.functional_boundary.forbidden_includes",
    )
    symbols = _configured_string_list(
        boundary.get("forbidden_symbols", []),
        diagnostics,
        "c_analyzer.functional_boundary.forbidden_symbols",
    )
    if status == "configured" and not includes and not symbols:
        diagnostics.append(
            Diagnostic(
                "CTOOL004",
                "MUST",
                "c_analyzer.functional_boundary",
                "configured boundaries require at least one include or symbol marker",
                True,
            )
        )
    return str(status), includes, symbols


def _normalize_c_type(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\n", " ")).strip()


def _record_fields(body: str) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = []
    body = re.sub(r"\b(public|private|protected)\s*:", "", body)
    for statement in body.split(";"):
        declaration = _normalize_c_type(statement)
        if not declaration or declaration.startswith("#"):
            continue
        function_pointer = re.match(
            r"(?P<returns>.+?)\s*\(\s*\*\s*(?P<name>[A-Za-z_]\w*)\s*\)"
            r"\s*\((?P<params>.*)\)$",
            declaration,
        )
        if function_pointer:
            fields.append(
                {
                    "name": function_pointer.group("name"),
                    "type": _normalize_c_type(
                        f"{function_pointer.group('returns')} (*)"
                        f"({function_pointer.group('params')})"
                    ),
                }
            )
            continue
        if "(" in declaration:
            continue
        match = re.match(
            r"(?P<type>.+?[\s*])(?P<name>[A-Za-z_]\w*)"
            r"(?P<array>\s*\[[^\]]*\])?(?:\s*:\s*\d+)?$",
            declaration,
        )
        if match:
            field_type = _normalize_c_type(
                match.group("type") + (match.group("array") or "")
            )
            fields.append({"name": match.group("name"), "type": field_type})
    return fields


def _discover_named_types(content: str, relative_path: str) -> list[dict[str, Any]]:
    """Discover common C/C++ declarations; unsupported syntax fails by omission."""
    cleaned = re.sub(r"/\*.*?\*/|//[^\n]*", "", content, flags=re.DOTALL)
    declarations: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    record_pattern = re.compile(
        r"\b(?P<prefix>typedef\s+)?(?P<kind>struct|union|enum|class)"
        r"(?:\s+(?P<tag>[A-Za-z_]\w*))?\s*\{(?P<body>.*?)\}"
        r"\s*(?P<alias>[A-Za-z_]\w*)?\s*;",
        re.DOTALL,
    )
    for match in record_pattern.finditer(cleaned):
        occupied.append(match.span())
        kind = match.group("kind")
        tag = match.group("tag")
        alias = match.group("alias")
        body = match.group("body")
        shape: dict[str, Any]
        if kind == "enum":
            values = []
            for raw in body.split(","):
                value = raw.split("=", 1)[0].strip()
                if re.fullmatch(r"[A-Za-z_]\w*", value):
                    values.append(value)
            shape = {"values": values}
        else:
            shape = {"fields": _record_fields(body)}
        primary = tag or alias
        if primary:
            declarations.append(
                {
                    "path": relative_path,
                    "symbol": primary,
                    "kind": kind,
                    **shape,
                }
            )
        if tag and alias and alias != tag:
            declarations.append(
                {
                    "path": relative_path,
                    "symbol": alias,
                    "kind": "alias",
                    "target": f"{kind} {tag}",
                }
            )

    function_pointer_pattern = re.compile(
        r"\btypedef\s+(?P<returns>[^;()]+?)\s*"
        r"\(\s*\*\s*(?P<name>[A-Za-z_]\w*)\s*\)\s*"
        r"\((?P<params>[^;]*)\)\s*;"
    )
    for match in function_pointer_pattern.finditer(cleaned):
        declarations.append(
            {
                "path": relative_path,
                "symbol": match.group("name"),
                "kind": "function-pointer",
                "signature": {
                    "returns": _normalize_c_type(match.group("returns")),
                    "parameters": [
                        _normalize_c_type(value)
                        for value in match.group("params").split(",")
                        if _normalize_c_type(value) and value.strip() != "void"
                    ],
                },
            }
        )
        occupied.append(match.span())

    alias_pattern = re.compile(
        r"\b(?:typedef\s+(?P<target>[^;{}()]+?)\s+(?P<name>[A-Za-z_]\w*)"
        r"|using\s+(?P<using_name>[A-Za-z_]\w*)\s*=\s*(?P<using_target>[^;]+));"
    )
    for match in alias_pattern.finditer(cleaned):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        declarations.append(
            {
                "path": relative_path,
                "symbol": match.group("name") or match.group("using_name"),
                "kind": "alias",
                "target": _normalize_c_type(
                    match.group("target") or match.group("using_target")
                ),
            }
        )
    return declarations


def _is_excluded(relative_path: str, exclusions: list[dict[str, Any]]) -> bool:
    path = Path(relative_path)
    for item in exclusions:
        pattern = str(item.get("path", ""))
        if pattern and (path.match(pattern) or relative_path.startswith(pattern.rstrip("*"))):
            return True
    return False


def _compare_type_catalog(
    manifest: dict[str, Any],
    source_contents: dict[Path, str],
    project_root: Path,
    diagnostics: list[Diagnostic],
) -> set[str]:
    exclusions = [
        item for item in manifest.get("type_exclusions", []) if isinstance(item, dict)
    ]
    discovered: dict[tuple[str, str], dict[str, Any]] = {}
    excluded_symbols: set[str] = set()
    for source, content in source_contents.items():
        relative = _relative_display(source, project_root)
        declarations = _discover_named_types(content, relative)
        classification, _ = classify_path(manifest, relative)
        if classification == "generated-production" or _is_excluded(relative, exclusions):
            excluded_symbols.update(str(item["symbol"]) for item in declarations)
            continue
        for declaration in declarations:
            key = (str(declaration["path"]), str(declaration["symbol"]))
            discovered[key] = declaration

    catalog = {
        (
            str(item.get("declaration", {}).get("path", "")),
            str(item.get("declaration", {}).get("symbol", "")),
        ): item
        for item in manifest.get("types", [])
        if isinstance(item, dict)
        and str(item.get("language", "")).lower() in {"c", "c++", "cpp"}
    }
    for key, declaration in discovered.items():
        if key not in catalog:
            diagnostics.append(
                Diagnostic(
                    "CTYPE001",
                    "MUST",
                    f"{key[0]}:{key[1]}",
                    "named C/C++ type is missing from the schema 2.1.0/2.2.0 catalog",
                )
            )
            continue
        item = catalog[key]
        expected = item.get("declaration", {})
        if expected.get("kind") != declaration.get("kind"):
            diagnostics.append(
                Diagnostic(
                    "CTYPE003",
                    "MUST",
                    f"{key[0]}:{key[1]}",
                    f"catalog kind {expected.get('kind')!r} does not match source {declaration.get('kind')!r}",
                )
            )
        if declaration.get("kind") in {"struct", "union", "class"}:
            actual_fields = [
                (field.get("name"), _normalize_c_type(str(field.get("type", ""))))
                for field in declaration.get("fields", [])
            ]
            catalog_fields = [
                (field.get("name"), _normalize_c_type(str(field.get("type", ""))))
                for field in item.get("fields", [])
                if isinstance(field, dict)
            ]
            if actual_fields != catalog_fields:
                diagnostics.append(
                    Diagnostic(
                        "CTYPE003",
                        "MUST",
                        f"{key[0]}:{key[1]}",
                        f"catalog fields {catalog_fields!r} do not match source {actual_fields!r}",
                    )
                )
        if declaration.get("kind") == "enum" and item.get("values") != declaration.get("values"):
            diagnostics.append(
                Diagnostic(
                    "CTYPE003",
                    "MUST",
                    f"{key[0]}:{key[1]}",
                    "catalog enum values do not match source",
                )
            )
        if declaration.get("kind") == "alias" and _normalize_c_type(
            str(item.get("target", ""))
        ) != declaration.get("target"):
            diagnostics.append(
                Diagnostic(
                    "CTYPE003",
                    "MUST",
                    f"{key[0]}:{key[1]}",
                    "catalog alias target does not match source",
                )
            )
    for key in sorted(set(catalog).difference(discovered)):
        diagnostics.append(
            Diagnostic(
                "CTYPE002",
                "MUST",
                f"{key[0]}:{key[1]}",
                "cataloged C/C++ type declaration is missing from source",
            )
        )
    return excluded_symbols


def _excluded_type_symbols(
    manifest: dict[str, Any],
    source_contents: dict[Path, str],
    project_root: Path,
) -> set[str]:
    exclusions = [
        item for item in manifest.get("type_exclusions", []) if isinstance(item, dict)
    ]
    symbols: set[str] = set()
    for source, content in source_contents.items():
        relative = _relative_display(source, project_root)
        classification, _ = classify_path(manifest, relative)
        if classification == "generated-production" or _is_excluded(relative, exclusions):
            symbols.update(
                str(item["symbol"])
                for item in _discover_named_types(content, relative)
            )
    return symbols


def _apply_dispositions(
    diagnostics: list[Diagnostic],
    manifest: dict[str, Any],
    manifest_path: Path,
    baseline_path: Path | None,
) -> None:
    baseline: set[tuple[str, str]] = set()
    if baseline_path and baseline_path.is_file():
        try:
            for entry in load_yaml(baseline_path).get("violations", []):
                if isinstance(entry, dict):
                    baseline.add((str(entry.get("rule_id")), str(entry.get("location"))))
        except ManifestError:
            pass
    exceptions = []
    for item in manifest.get("adr_exceptions", []):
        if not isinstance(item, dict) or item.get("status") != "accepted":
            continue
        approver = set(re.findall(r"[a-z]+", str(item.get("approved_by", "")).lower()))
        adr = manifest_path.parent / str(item.get("adr", ""))
        if not approver.intersection(BANNED_AI_APPROVERS) and item.get("approval_reference") and adr.is_file():
            exceptions.append(item)
    for diagnostic in diagnostics:
        if diagnostic.configuration:
            continue
        if (diagnostic.rule_id, diagnostic.location) in baseline:
            diagnostic.disposition = "baseline"
            continue
        for item in exceptions:
            if diagnostic.rule_id == item.get("rule_id") and diagnostic.location.startswith(str(item.get("scope", ""))):
                diagnostic.disposition = f"adr:{item.get('adr')}"
                break


def analyze(
    manifest: dict[str, Any],
    manifest_path: Path,
    project_root: Path,
    baseline_path: Path | None = None,
    evidence_out: dict[str, Any] | None = None,
) -> tuple[list[Diagnostic], str]:
    diagnostics = validate_manifest(manifest, manifest_path, baseline_path)
    if exit_code(diagnostics) == 2:
        return diagnostics, "not-run"
    modules = {
        str(item["id"]): item
        for item in manifest.get("modules", [])
        if isinstance(item, dict) and item.get("id")
    }
    roots = _module_roots(project_root, modules)
    config = manifest.get("c_analyzer", {}) if isinstance(manifest.get("c_analyzer", {}), dict) else {}
    forbidden_source_symbols = _configured_forbidden_source_symbols(config, diagnostics)
    boundary_status, functional_includes, functional_symbols = _functional_boundary(
        config, diagnostics
    )
    ast_config = config.get("ast", {}) if isinstance(config.get("ast"), dict) else {}
    compile_commands_value = ast_config.get("compilation_database")
    compile_commands = project_root / str(compile_commands_value) if compile_commands_value else None
    files, _, tool_diagnostics = _source_files(project_root, roots, compile_commands)
    diagnostics.extend(tool_diagnostics)
    for source in files:
        relative = _relative_display(source, project_root)
        classification, _ = classify_path(manifest, relative)
        if classification not in {"production", "generated-production"}:
            diagnostics.append(
                Diagnostic(
                    "SRC006",
                    "MUST",
                    relative,
                    "production compilation database may contain only production or generated-production sources",
                    True,
                )
            )
    known_files = sorted(set(files) | {path.resolve() for paths in roots.values() for root in paths if root.is_dir() for path in root.rglob("*") if path.suffix.lower() in SOURCE_SUFFIXES})

    source_contents: dict[Path, str] = {}
    for source in known_files:
        classification, _ = classify_path(
            manifest, _relative_display(source, project_root)
        )
        if classification not in {"production", "generated-production"}:
            continue
        try:
            source_contents[source] = source.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            diagnostics.append(Diagnostic("CTOOL002", "MUST", str(source), f"cannot read source: {exc}", True))
    l3_source_exists = any(
        modules.get(str(_owner(source, roots)), {}).get("level") == "L3+"
        for source in known_files
    )
    if l3_source_exists and boundary_status == "not-applicable":
        diagnostics.append(
            Diagnostic(
                "CTOOL004",
                "MUST",
                "c_analyzer.functional_boundary.status",
                "C/C++ L3+ sources require configured functional-boundary markers",
                True,
            )
        )
    ast_evidence = analyze_ast(manifest, project_root, diagnostics)
    mode = ast_evidence.mode
    if evidence_out is not None:
        evidence_out["toolchain"] = ast_evidence.toolchain
        evidence_out["covered_files"] = sorted(
            _relative_display(path, project_root)
            for path in ast_evidence.covered_files
        )
        evidence_out["translation_units"] = ast_evidence.translation_units
        evidence_out["worker_count"] = ast_evidence.worker_count
    excluded_symbols = _excluded_type_symbols(
        manifest, source_contents, project_root
    )
    forbidden_set = set(forbidden_source_symbols)
    if forbidden_set:
        for source in known_files:
            content = source_contents.get(source)
            if content is None:
                continue
            for line_number, symbol in _identifier_occurrences(content, forbidden_set):
                diagnostics.append(
                    Diagnostic(
                        "CSRC001",
                        "MUST",
                        f"{_relative_display(source, project_root)}:{line_number}",
                        f"forbidden source symbol: {symbol}",
                    )
                )

    ports = [item for item in manifest.get("ports", []) if isinstance(item, dict)]
    port_owner_by_implementation: dict[str, set[str]] = {}
    for port in ports:
        for adapter in port.get("implemented_by", []):
            port_owner_by_implementation.setdefault(str(adapter), set()).add(str(port.get("owner")))

    actual_graph: dict[str, set[str]] = {module_id: set() for module_id in modules}
    seen_edges: set[tuple[str, str, str]] = set()
    include_edges = ast_evidence.includes
    if not include_edges:
        for source in files:
            content = source_contents.get(source)
            if content is None:
                continue
            for line_number, line in enumerate(content.splitlines(), 1):
                match = INCLUDE_PATTERN.match(line)
                if not match:
                    continue
                target_file = _resolve_include(
                    match.group(1), source, project_root, known_files
                )
                if target_file is not None:
                    include_edges.append((source, target_file, line_number))
    for source, target_file, line_number in include_edges:
        source_owner = _owner(source, roots)
        if source_owner is None:
            continue
        target_owner = _owner(target_file, roots)
        if target_owner is None or target_owner == source_owner:
            continue
        location = f"{_relative_display(source, project_root)}:{line_number}"
        edge_key = (source_owner, target_owner, location)
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        actual_graph[source_owner].add(target_owner)
        if target_owner not in modules[source_owner].get("depends_on", []):
            diagnostics.append(Diagnostic("CDEP001", "MUST", location, f"actual include edge {source_owner}->{target_owner} is not declared"))
        violation = dependency_violation(modules[source_owner], modules[target_owner], port_owner_by_implementation)
        if violation:
            diagnostics.append(Diagnostic(violation[0], "MUST", location, violation[1]))

    for source, content in source_contents.items():
        owner_id = _owner(source, roots)
        if owner_id is None or modules[owner_id].get("level") not in {"L0", "L1", "L2"}:
            continue
        for line_number, line in enumerate(content.splitlines(), 1):
            location = f"{_relative_display(source, project_root)}:{line_number}"
            include_match = SYSTEM_INCLUDE_PATTERN.match(line)
            if include_match and any(
                token in include_match.group(1) for token in functional_includes
            ):
                diagnostics.append(
                    Diagnostic(
                        "CFUN001",
                        "MUST",
                        location,
                        f"external-technology include in functional source: {include_match.group(1)}",
                    )
                )
        for line_number, symbol in _identifier_occurrences(
            content, set(functional_symbols)
        ):
            diagnostics.append(
                Diagnostic(
                    "CFUN002",
                    "MUST",
                    f"{_relative_display(source, project_root)}:{line_number}",
                    f"external-technology symbol in functional source: {symbol}",
                )
            )

    found_cycle = _cycle(actual_graph)
    if found_cycle:
        diagnostics.append(Diagnostic("CDEP002", "MUST", "->".join(found_cycle), "actual C/C++ include cycle is forbidden"))

    forbidden_includes = [str(item) for item in config.get("forbidden_public_includes", [])]
    forbidden_symbols = [str(item) for item in config.get("forbidden_public_symbols", [])]
    for module_id, module in modules.items():
        if manifest.get("schema_version") in {"2.1.0", "2.2.0"}:
            status = module.get("implementation_status")
            severity = "MUST" if status == "implemented" else "SHOULD"
            for module_path in module.get("paths", []):
                resolved_module_path = project_root / str(module_path)
                if not resolved_module_path.exists():
                    diagnostics.append(
                        Diagnostic(
                            "CSYM001",
                            severity,
                            str(module_path),
                            f"{status} module path does not exist",
                        )
                    )
            for field in ("entrypoints", "public_symbols"):
                for entry in module.get(field, []):
                    if not isinstance(entry, dict):
                        continue
                    relative_path = str(entry.get("path", ""))
                    source_path = project_root / relative_path
                    if source_path.suffix.lower() not in SOURCE_SUFFIXES:
                        continue
                    location = f"{module_id}.{field}:{relative_path}"
                    if not source_path.is_file():
                        diagnostics.append(
                            Diagnostic("CSYM002", severity, location, f"{status} C/C++ symbol file does not exist")
                        )
                        continue
                    symbol = str(entry.get("symbol", ""))
                    content = source_path.read_text(encoding="utf-8", errors="replace")
                    lexical_symbol = symbol.rsplit("::", 1)[-1]
                    if not re.search(rf"\b{re.escape(lexical_symbol)}\b", content):
                        diagnostics.append(
                            Diagnostic("CSYM003", severity, location, f"symbol {symbol!r} was not found")
                        )
        if module.get("level") not in {"L0", "L1", "L2"}:
            continue
        public_patterns = list(module.get("public_headers", []))
        if manifest.get("schema_version") in {"2.1.0", "2.2.0"}:
            public_patterns.extend(
                str(entry.get("path"))
                for entry in module.get("public_symbols", [])
                if isinstance(entry, dict) and Path(str(entry.get("path", ""))).suffix.lower() in {".h", ".hh", ".hpp"}
            )
        for pattern in public_patterns:
            for header in project_root.glob(str(pattern)):
                if not header.is_file():
                    continue
                lines = header.read_text(encoding="utf-8", errors="replace").splitlines()
                for line_number, line in enumerate(lines, 1):
                    location = f"{_relative_display(header, project_root)}:{line_number}"
                    include_match = INCLUDE_PATTERN.match(line)
                    if include_match and any(token in include_match.group(1) for token in forbidden_includes):
                        diagnostics.append(Diagnostic("CLEAK001", "MUST", location, f"framework include leaks through public contract: {include_match.group(1)}"))
                    for symbol in forbidden_symbols:
                        if re.search(rf"\b{re.escape(symbol)}\b", line):
                            diagnostics.append(Diagnostic("CLEAK002", "MUST", location, f"framework symbol leaks through public contract: {symbol}"))
                    for symbol in excluded_symbols:
                        if re.search(rf"\b{re.escape(symbol)}\b", line):
                            diagnostics.append(
                                Diagnostic(
                                    "CTYPE004",
                                    "MUST",
                                    location,
                                    f"excluded vendor/generated type leaks through functional contract: {symbol}",
                                )
                            )

    c_diagnostics = [item for item in diagnostics if item.rule_id.startswith("C") or item.rule_id in {"DEP001", "DEP002", "DEP003"}]
    _apply_dispositions(c_diagnostics, manifest, manifest_path, baseline_path)
    return diagnostics, mode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    try:
        manifest = load_yaml(args.manifest)
        diagnostics, mode = analyze(manifest, args.manifest, args.project_root.resolve(), args.baseline)
    except ManifestError as exc:
        diagnostics = [Diagnostic("CTOOL000", "MUST", str(args.manifest), str(exc), True)]
        mode = "not-run"
    if args.format == "json":
        print(json.dumps({"analysis_mode": mode, "exit_code": exit_code(diagnostics), "diagnostics": [asdict(item) for item in diagnostics]}, indent=2))
    else:
        print(f"analysis_mode={mode}")
        print(render_text(diagnostics))
    return exit_code(diagnostics)


if __name__ == "__main__":
    print(
        "ERROR: direct legacy CLI removed; use architecture_cli.py gate instead.",
        file=sys.stderr,
    )
    raise SystemExit(2)
