"""Validate and resolve schema 2.1.0/2.2.0 logical source classifications."""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import Any

from check_architecture import Diagnostic, _diag, _is_nonempty_string


CLASSIFICATIONS = {
    "production",
    "generated-production",
    "development",
    "derived-documentation",
    "build-output",
}
CATALOG_CLASSIFICATIONS = {"production"}
NON_PRODUCTION_CLASSIFICATIONS = CLASSIFICATIONS - CATALOG_CLASSIFICATIONS


def _normalize(raw: str) -> str | None:
    value = raw.replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or (path.parts and ":" in path.parts[0])
    ):
        return None
    return path.as_posix()


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatchcase(path, pattern) for pattern in patterns)


def validate_source_sets(data: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    raw_sets = data.get("source_sets")
    if not isinstance(raw_sets, list) or not raw_sets:
        _diag(diagnostics, "SRC001", "source_sets", "must be a non-empty list", configuration=True)
        return diagnostics

    seen_ids: set[str] = set()
    seen_classes: set[str] = set()
    modules = {
        str(item.get("id")): item
        for item in data.get("modules", [])
        if isinstance(item, dict) and _is_nonempty_string(item.get("id"))
    }
    for index, item in enumerate(raw_sets):
        location = f"source_sets[{index}]"
        if not isinstance(item, dict):
            _diag(diagnostics, "SRC001", location, "must be a mapping", configuration=True)
            continue
        identifier = item.get("id")
        classification = item.get("classification")
        if not _is_nonempty_string(identifier):
            _diag(diagnostics, "SRC001", f"{location}.id", "must be non-empty", configuration=True)
        elif str(identifier) in seen_ids:
            _diag(diagnostics, "SRC001", f"{location}.id", "duplicate source-set id", configuration=True)
        else:
            seen_ids.add(str(identifier))
        if classification not in CLASSIFICATIONS:
            _diag(
                diagnostics,
                "SRC001",
                f"{location}.classification",
                f"must be one of {sorted(CLASSIFICATIONS)}",
                configuration=True,
            )
        else:
            seen_classes.add(str(classification))
        for key, required in (("include", True), ("exclude", False)):
            patterns = item.get(key)
            if not isinstance(patterns, list) or (required and not patterns):
                _diag(
                    diagnostics,
                    "SRC001",
                    f"{location}.{key}",
                    "must be a non-empty list" if required else "must be a list",
                    configuration=True,
                )
                continue
            for pattern_index, raw_pattern in enumerate(patterns):
                if not _is_nonempty_string(raw_pattern) or _normalize(str(raw_pattern)) is None:
                    _diag(
                        diagnostics,
                        "SRC002",
                        f"{location}.{key}[{pattern_index}]",
                        "must be a project-relative glob without parent traversal",
                        configuration=True,
                    )
        if not _is_nonempty_string(item.get("purpose")):
            _diag(diagnostics, "SRC001", f"{location}.purpose", "must be non-empty", configuration=True)
        if not _is_nonempty_string(item.get("provenance")):
            _diag(diagnostics, "SRC001", f"{location}.provenance", "must be non-empty", configuration=True)
        if classification == "generated-production":
            owner = modules.get(str(item.get("owner", "")))
            if owner is None or owner.get("level") != "L3+":
                _diag(
                    diagnostics,
                    "SRC003",
                    f"{location}.owner",
                    "generated-production requires an L3+ owner",
                )
            if not _is_nonempty_string(item.get("generator")):
                _diag(
                    diagnostics,
                    "SRC003",
                    f"{location}.generator",
                    "generated-production requires generator provenance",
                    configuration=True,
                )
    for classification in sorted({"production"}.difference(seen_classes)):
        _diag(
            diagnostics,
            "SRC001",
            "source_sets",
            f"must declare a {classification} source set",
            configuration=True,
        )
    return diagnostics


def classify_path(data: dict[str, Any], raw_path: str) -> tuple[str | None, dict[str, Any] | None]:
    normalized = _normalize(raw_path)
    if normalized is None:
        return None, None
    matches: list[dict[str, Any]] = []
    for item in data.get("source_sets", []):
        if not isinstance(item, dict):
            continue
        includes = [str(value) for value in item.get("include", []) if _is_nonempty_string(value)]
        excludes = [str(value) for value in item.get("exclude", []) if _is_nonempty_string(value)]
        if _matches(normalized, includes) and not _matches(normalized, excludes):
            matches.append(item)
    if len(matches) != 1:
        return None, None
    return str(matches[0].get("classification")), matches[0]


def validate_manifest_source_paths(data: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    references: list[tuple[str, str]] = []
    for module in data.get("modules", []):
        if not isinstance(module, dict):
            continue
        module_id = str(module.get("id", ""))
        references.extend((f"{module_id}.paths", str(path)) for path in module.get("paths", []))
        for key in ("entrypoints", "public_symbols"):
            for item in module.get(key, []):
                if isinstance(item, dict):
                    references.append((f"{module_id}.{key}", str(item.get("path", ""))))
    for catalog_name in ("types", "state_objects"):
        for item in data.get(catalog_name, []):
            if isinstance(item, dict) and isinstance(item.get("declaration"), dict):
                references.append(
                    (
                        f"{catalog_name}:{item.get('id', '')}",
                        str(item["declaration"].get("path", "")),
                    )
                )
    for location, path in references:
        classification, _ = classify_path(data, path)
        if classification is None:
            _diag(
                diagnostics,
                "SRC004",
                f"{location}:{path}",
                "path must match exactly one source set",
                configuration=True,
            )
        elif classification != "production":
            _diag(
                diagnostics,
                "SRC005",
                f"{location}:{path}",
                f"formal architecture declaration cannot use {classification!r} source",
            )
    return diagnostics
