"""Validate schema 2.1.0/2.2.0 state-object ownership and AST capability contracts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from check_architecture import Diagnostic, _diag, _is_nonempty_string


ID_PATTERN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
STORAGE_CLASSES = {"file-static", "external-linkage", "thread-local"}
VISIBILITIES = {"private", "module-public", "cross-module"}
MUTABILITIES = {"immutable", "owner-mutable", "shared-mutable"}
AST_STATUSES = {"required", "not-applicable"}
C_LANGUAGES = {"c", "c++", "cpp"}


def _list(
    value: Any,
    diagnostics: list[Diagnostic],
    rule: str,
    location: str,
) -> list[Any]:
    if not isinstance(value, list):
        _diag(diagnostics, rule, location, "must be a list", configuration=True)
        return []
    return value


def _mapping(
    value: Any,
    diagnostics: list[Diagnostic],
    rule: str,
    location: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        _diag(diagnostics, rule, location, "must be a mapping", configuration=True)
        return {}
    return value


def _owned_path(path: str, module: dict[str, Any]) -> bool:
    normalized = Path(path).as_posix().lstrip("./")
    for raw_root in module.get("paths", []):
        root = Path(str(raw_root)).as_posix().rstrip("/")
        if normalized == root or normalized.startswith(root + "/"):
            return True
    return False


def _module_refs(
    value: Any,
    modules: dict[str, dict[str, Any]],
    diagnostics: list[Diagnostic],
    location: str,
) -> list[str]:
    result: list[str] = []
    for index, raw in enumerate(_list(value, diagnostics, "STA004", location)):
        item_location = f"{location}[{index}]"
        if not _is_nonempty_string(raw):
            _diag(
                diagnostics,
                "STA004",
                item_location,
                "must be a non-empty module id",
                configuration=True,
            )
        elif str(raw) not in modules:
            _diag(diagnostics, "STA004", item_location, f"unknown module {raw!r}")
        elif str(raw) not in result:
            result.append(str(raw))
    return result


def validate_state_catalog(
    data: dict[str, Any],
    manifest_path: Path,
) -> list[Diagnostic]:
    """Validate declared state objects; source completeness is AST-analyzer work."""
    del manifest_path
    diagnostics: list[Diagnostic] = []
    modules = {
        str(item.get("id")): item
        for item in data.get("modules", [])
        if isinstance(item, dict) and _is_nonempty_string(item.get("id"))
    }
    types = {
        str(item.get("id")): item
        for item in data.get("types", [])
        if isinstance(item, dict) and _is_nonempty_string(item.get("id"))
    }
    type_symbols = {
        str(item.get("declaration", {}).get("symbol")): type_id
        for type_id, item in types.items()
        if isinstance(item.get("declaration"), dict)
        and _is_nonempty_string(item.get("declaration", {}).get("symbol"))
    }

    raw_objects = _list(
        data.get("state_objects"),
        diagnostics,
        "STA001",
        "state_objects",
    )
    objects: dict[str, dict[str, Any]] = {}
    declarations: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_objects):
        location = f"state_objects[{index}]"
        item = _mapping(raw, diagnostics, "STA001", location)
        object_id = item.get("id")
        if (
            not _is_nonempty_string(object_id)
            or not ID_PATTERN.fullmatch(str(object_id))
        ):
            _diag(
                diagnostics,
                "STA001",
                f"{location}.id",
                "must be a stable lowercase id",
                configuration=True,
            )
            object_id = location
        object_id = str(object_id)
        if object_id in objects:
            _diag(
                diagnostics,
                "STA001",
                object_id,
                "duplicate state-object id",
                configuration=True,
            )
        objects[object_id] = item

        owner_id = str(item.get("owner", ""))
        owner = modules.get(owner_id)
        if owner is None:
            _diag(diagnostics, "STA002", f"{object_id}.owner", "must reference a module")
            owner = {}
        language = str(item.get("language", "")).lower()
        if not _is_nonempty_string(item.get("language")):
            _diag(
                diagnostics,
                "STA001",
                f"{object_id}.language",
                "must be non-empty",
                configuration=True,
            )

        declaration = _mapping(
            item.get("declaration"),
            diagnostics,
            "STA002",
            f"{object_id}.declaration",
        )
        path = str(declaration.get("path", ""))
        symbol = str(declaration.get("symbol", ""))
        storage = declaration.get("storage")
        if (
            not _is_nonempty_string(path)
            or Path(path).is_absolute()
            or path.startswith("../")
        ):
            _diag(
                diagnostics,
                "STA002",
                f"{object_id}.declaration.path",
                "must be a project-relative path",
                configuration=True,
            )
        elif owner and not _owned_path(path, owner):
            _diag(
                diagnostics,
                "STA002",
                f"{object_id}.declaration.path",
                f"path is not owned by module {owner_id!r}",
            )
        if not _is_nonempty_string(symbol):
            _diag(
                diagnostics,
                "STA002",
                f"{object_id}.declaration.symbol",
                "must be non-empty",
                configuration=True,
            )
        key = (path, symbol)
        if key in declarations:
            _diag(
                diagnostics,
                "STA002",
                f"{object_id}.declaration",
                "duplicate declaration path and symbol",
                configuration=True,
            )
        declarations.add(key)
        if storage not in STORAGE_CLASSES:
            _diag(
                diagnostics,
                "STA002",
                f"{object_id}.declaration.storage",
                f"must be one of {sorted(STORAGE_CLASSES)}",
                configuration=True,
            )

        declared_type = item.get("type")
        if not _is_nonempty_string(declared_type):
            _diag(
                diagnostics,
                "STA003",
                f"{object_id}.type",
                "must be non-empty",
                configuration=True,
            )
        type_ref = item.get("type_ref")
        if type_ref is not None:
            if not _is_nonempty_string(type_ref) or str(type_ref) not in types:
                _diag(
                    diagnostics,
                    "STA003",
                    f"{object_id}.type_ref",
                    "must reference a Type Catalog id",
                )
            elif types[str(type_ref)].get("owner") != owner_id:
                target_owner = str(types[str(type_ref)].get("owner", ""))
                if target_owner not in owner.get("depends_on", []):
                    _diag(
                        diagnostics,
                        "STA003",
                        f"{object_id}.type_ref",
                        f"object owner {owner_id!r} has no dependency on type owner {target_owner!r}",
                    )
        elif str(declared_type) in type_symbols:
            _diag(
                diagnostics,
                "STA003",
                f"{object_id}.type_ref",
                f"project type {declared_type!r} requires type_ref",
                configuration=True,
            )

        visibility = item.get("visibility")
        mutability = item.get("mutability")
        if visibility not in VISIBILITIES:
            _diag(
                diagnostics,
                "STA001",
                f"{object_id}.visibility",
                f"must be one of {sorted(VISIBILITIES)}",
                configuration=True,
            )
        if not _is_nonempty_string(item.get("lifetime")):
            _diag(
                diagnostics,
                "STA001",
                f"{object_id}.lifetime",
                "must be non-empty",
                configuration=True,
            )
        if mutability not in MUTABILITIES:
            _diag(
                diagnostics,
                "STA001",
                f"{object_id}.mutability",
                f"must be one of {sorted(MUTABILITIES)}",
                configuration=True,
            )
        readers = _module_refs(
            item.get("read_authority"),
            modules,
            diagnostics,
            f"{object_id}.read_authority",
        )
        writers = _module_refs(
            item.get("write_authority"),
            modules,
            diagnostics,
            f"{object_id}.write_authority",
        )
        if owner_id in modules and owner_id not in readers:
            _diag(
                diagnostics,
                "STA004",
                f"{object_id}.read_authority",
                "the owner must have read authority",
            )
        if mutability == "immutable" and writers:
            _diag(
                diagnostics,
                "STA004",
                f"{object_id}.write_authority",
                "immutable objects cannot declare runtime writers",
            )
        if mutability == "owner-mutable" and writers != [owner_id]:
            _diag(
                diagnostics,
                "STA004",
                f"{object_id}.write_authority",
                "owner-mutable objects require exactly the owner module",
            )
        if visibility == "private" and (
            any(reader != owner_id for reader in readers)
            or any(writer != owner_id for writer in writers)
        ):
            _diag(
                diagnostics,
                "STA005",
                object_id,
                "private state cannot grant authority to another module",
            )
        if language in C_LANGUAGES and storage == "external-linkage" and visibility == "private":
            _diag(
                diagnostics,
                "STA005",
                object_id,
                "private C/C++ state must not have external linkage",
            )

    for module_id, module in modules.items():
        description = module.get("description")
        if not isinstance(description, dict):
            continue
        for index, raw_state in enumerate(description.get("owned_state", [])):
            location = f"{module_id}.description.owned_state[{index}]"
            if not isinstance(raw_state, dict):
                continue
            state_ref = raw_state.get("ref")
            if not _is_nonempty_string(state_ref):
                _diag(
                    diagnostics,
                    "STA006",
                    f"{location}.ref",
                    "owned-state descriptions must reference state_objects",
                    configuration=True,
                )
            elif str(state_ref) not in objects:
                _diag(
                    diagnostics,
                    "STA006",
                    f"{location}.ref",
                    f"unknown state object {state_ref!r}",
                )
            elif objects[str(state_ref)].get("owner") != module_id:
                _diag(
                    diagnostics,
                    "STA006",
                    f"{location}.ref",
                    "state object is owned by another module",
                )

    config = _mapping(
        data.get("c_analyzer"),
        diagnostics,
        "AST001",
        "c_analyzer",
    )
    ast = _mapping(
        config.get("ast"),
        diagnostics,
        "AST001",
        "c_analyzer.ast",
    )
    status = ast.get("status")
    if status not in AST_STATUSES:
        _diag(
            diagnostics,
            "AST001",
            "c_analyzer.ast.status",
            f"must be one of {sorted(AST_STATUSES)}",
            configuration=True,
        )
    if not _is_nonempty_string(ast.get("rationale")):
        _diag(
            diagnostics,
            "AST001",
            "c_analyzer.ast.rationale",
            "must be non-empty",
            configuration=True,
        )
    if status == "required":
        database = ast.get("compilation_database")
        if (
            not _is_nonempty_string(database)
            or Path(str(database)).is_absolute()
            or str(database).startswith("../")
        ):
            _diag(
                diagnostics,
                "AST002",
                "c_analyzer.ast.compilation_database",
                "must be a project-relative compilation database",
                configuration=True,
            )
        if not _is_nonempty_string(ast.get("target_triple")):
            _diag(
                diagnostics,
                "AST002",
                "c_analyzer.ast.target_triple",
                "must be non-empty when AST analysis is required",
                configuration=True,
            )

    return diagnostics
