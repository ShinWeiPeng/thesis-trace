"""Validate schema 2.1.0/2.2.0 named-type ownership and semantic boundaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from check_architecture import (
    Diagnostic,
    _diag,
    _is_nonempty_string,
    dependency_violation,
)


TYPE_KINDS = {
    "struct",
    "union",
    "enum",
    "class",
    "alias",
    "function-pointer",
    "protocol",
    "interface",
}
VISIBILITIES = {"private", "module-public", "cross-module"}
SEMANTIC_KINDS = {
    "domain-identity",
    "domain-value",
    "command",
    "query",
    "event-payload",
    "port",
    "runtime-state",
    "configuration",
    "policy",
    "descriptor",
    "adapter-binding",
    "composition-mapping",
    "wire-representation",
    "storage-representation",
    "framework-type",
    "private-helper",
}
FIELD_ROLES = {
    "domain-identity",
    "domain-value",
    "contract-control",
    "policy",
    "configuration",
    "runtime-state",
    "adapter-binding",
    "framework-handle",
    "wire-representation",
    "storage-representation",
    "metadata",
}
MUTABILITIES = {"immutable", "owner-mutable", "shared-mutable"}
EXTERNAL_FIELD_ROLES = {
    "adapter-binding",
    "framework-handle",
    "wire-representation",
    "storage-representation",
}
RECORD_KINDS = {"struct", "union", "class"}


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


def _string_refs(
    value: Any,
    known: dict[str, Any],
    diagnostics: list[Diagnostic],
    rule: str,
    location: str,
) -> list[str]:
    result: list[str] = []
    for index, item in enumerate(_list(value, diagnostics, rule, location)):
        item_location = f"{location}[{index}]"
        if not _is_nonempty_string(item):
            _diag(
                diagnostics,
                rule,
                item_location,
                "must be a non-empty module id",
                configuration=True,
            )
        elif str(item) not in known:
            _diag(diagnostics, rule, item_location, f"unknown module {item!r}")
        else:
            result.append(str(item))
    return result


def validate_type_catalog(
    data: dict[str, Any],
    manifest_path: Path,
) -> list[Diagnostic]:
    """Validate the declared catalog; source completeness is language-analyzer work."""
    del manifest_path
    diagnostics: list[Diagnostic] = []
    modules = {
        str(item.get("id")): item
        for item in data.get("modules", [])
        if isinstance(item, dict) and _is_nonempty_string(item.get("id"))
    }
    raw_types = _list(data.get("types"), diagnostics, "TYP001", "types")
    known_type_ids = {
        str(item.get("id"))
        for item in raw_types
        if isinstance(item, dict) and _is_nonempty_string(item.get("id"))
    }
    type_owners = {
        str(item.get("id")): str(item.get("owner", ""))
        for item in raw_types
        if isinstance(item, dict) and _is_nonempty_string(item.get("id"))
    }
    port_owner_by_implementation: dict[str, set[str]] = {}
    for port in data.get("ports", []):
        if not isinstance(port, dict):
            continue
        for adapter in port.get("implemented_by", []):
            port_owner_by_implementation.setdefault(str(adapter), set()).add(
                str(port.get("owner"))
            )
    type_ids: set[str] = set()
    declarations: set[tuple[str, str]] = set()

    for index, raw_type in enumerate(raw_types):
        location = f"types[{index}]"
        item = _mapping(raw_type, diagnostics, "TYP001", location)
        type_id = item.get("id")
        if not _is_nonempty_string(type_id):
            _diag(
                diagnostics,
                "TYP001",
                f"{location}.id",
                "must be a non-empty stable id",
                configuration=True,
            )
            type_id = location
        type_id = str(type_id)
        if type_id in type_ids:
            _diag(diagnostics, "TYP001", type_id, "duplicate type id", configuration=True)
        type_ids.add(type_id)

        owner_id = str(item.get("owner", ""))
        owner = modules.get(owner_id)
        if owner is None:
            _diag(diagnostics, "TYP002", f"{type_id}.owner", "must reference a module")
            owner = {}
        if not _is_nonempty_string(item.get("language")):
            _diag(
                diagnostics,
                "TYP001",
                f"{type_id}.language",
                "must be non-empty",
                configuration=True,
            )
        declaration = _mapping(
            item.get("declaration"),
            diagnostics,
            "TYP003",
            f"{type_id}.declaration",
        )
        path = str(declaration.get("path", ""))
        symbol = str(declaration.get("symbol", ""))
        kind = declaration.get("kind")
        if not _is_nonempty_string(path) or Path(path).is_absolute() or path.startswith("../"):
            _diag(
                diagnostics,
                "TYP003",
                f"{type_id}.declaration.path",
                "must be a project-relative path",
                configuration=True,
            )
        elif owner and not _owned_path(path, owner):
            _diag(
                diagnostics,
                "TYP002",
                f"{type_id}.declaration.path",
                f"path is not owned by module {owner_id!r}",
            )
        if not _is_nonempty_string(symbol):
            _diag(
                diagnostics,
                "TYP003",
                f"{type_id}.declaration.symbol",
                "must be non-empty",
                configuration=True,
            )
        declaration_key = (path, symbol)
        if declaration_key in declarations:
            _diag(
                diagnostics,
                "TYP003",
                f"{type_id}.declaration",
                "duplicate declaration path and symbol",
                configuration=True,
            )
        declarations.add(declaration_key)
        if kind not in TYPE_KINDS:
            _diag(
                diagnostics,
                "TYP003",
                f"{type_id}.declaration.kind",
                f"must be one of {sorted(TYPE_KINDS)}",
                configuration=True,
            )

        visibility = item.get("visibility")
        semantic_kind = item.get("semantic_kind")
        if visibility not in VISIBILITIES:
            _diag(
                diagnostics,
                "TYP001",
                f"{type_id}.visibility",
                f"must be one of {sorted(VISIBILITIES)}",
                configuration=True,
            )
        if semantic_kind not in SEMANTIC_KINDS:
            _diag(
                diagnostics,
                "TYP001",
                f"{type_id}.semantic_kind",
                f"must be one of {sorted(SEMANTIC_KINDS)}",
                configuration=True,
            )
        for field_name in ("description", "lifetime"):
            if not _is_nonempty_string(item.get(field_name)):
                _diag(
                    diagnostics,
                    "TYP001",
                    f"{type_id}.{field_name}",
                    "must be non-empty",
                    configuration=True,
                )
        mutability = item.get("mutability")
        if mutability not in MUTABILITIES:
            _diag(
                diagnostics,
                "TYP001",
                f"{type_id}.mutability",
                f"must be one of {sorted(MUTABILITIES)}",
                configuration=True,
            )
        authorities = _string_refs(
            item.get("mutation_authority"),
            modules,
            diagnostics,
            "TYP005",
            f"{type_id}.mutation_authority",
        )
        consumers = _string_refs(
            item.get("consumers"),
            modules,
            diagnostics,
            "TYP005",
            f"{type_id}.consumers",
        )
        references: list[str] = []
        for reference_index, reference in enumerate(
            _list(
                item.get("references"),
                diagnostics,
                "TYP006",
                f"{type_id}.references",
            )
        ):
            reference_location = f"{type_id}.references[{reference_index}]"
            if not _is_nonempty_string(reference):
                _diag(
                    diagnostics,
                    "TYP006",
                    reference_location,
                    "must be a non-empty Type Catalog id",
                    configuration=True,
                )
            elif str(reference) not in known_type_ids:
                _diag(
                    diagnostics,
                    "TYP006",
                    reference_location,
                    f"unknown type reference {reference!r}",
                )
            else:
                references.append(str(reference))
        for reference in references:
            target_owner = type_owners.get(reference, "")
            if not owner or not target_owner or target_owner == owner_id:
                continue
            if target_owner not in owner.get("depends_on", []):
                _diag(
                    diagnostics,
                    "TYP006",
                    f"{type_id}.references",
                    f"type reference creates undeclared dependency {owner_id}->{target_owner}",
                )
            violation = dependency_violation(
                owner,
                modules.get(target_owner, {}),
                port_owner_by_implementation,
            )
            if violation:
                _diag(
                    diagnostics,
                    "TYP006",
                    f"{type_id}.references",
                    violation[1],
                )
        if mutability == "immutable" and authorities:
            _diag(
                diagnostics,
                "TYP005",
                f"{type_id}.mutation_authority",
                "immutable types cannot declare mutation authority",
            )
        if mutability == "owner-mutable" and authorities != [owner_id]:
            _diag(
                diagnostics,
                "TYP005",
                f"{type_id}.mutation_authority",
                "owner-mutable types require exactly the owner module",
            )
        if semantic_kind in {"runtime-state", "private-helper"}:
            if visibility != "private":
                _diag(
                    diagnostics,
                    "TYP004",
                    f"{type_id}.visibility",
                    f"{semantic_kind} must be private",
                )
            if any(consumer != owner_id for consumer in consumers):
                _diag(
                    diagnostics,
                    "TYP005",
                    f"{type_id}.consumers",
                    f"{semantic_kind} cannot have external consumers",
                )

        fields = _list(item.get("fields"), diagnostics, "TYP003", f"{type_id}.fields")
        roles: set[str] = set()
        field_names: set[str] = set()
        for field_index, raw_field in enumerate(fields):
            field_location = f"{type_id}.fields[{field_index}]"
            field = _mapping(raw_field, diagnostics, "TYP003", field_location)
            name = field.get("name")
            if not _is_nonempty_string(name) or not _is_nonempty_string(field.get("type")):
                _diag(
                    diagnostics,
                    "TYP003",
                    field_location,
                    "requires non-empty name and type",
                    configuration=True,
                )
            elif str(name) in field_names:
                _diag(
                    diagnostics,
                    "TYP003",
                    f"{field_location}.name",
                    f"duplicate field {name!r}",
                    configuration=True,
                )
            else:
                field_names.add(str(name))
            role = field.get("role")
            if role not in FIELD_ROLES:
                _diag(
                    diagnostics,
                    "TYP003",
                    f"{field_location}.role",
                    f"must be one of {sorted(FIELD_ROLES)}",
                    configuration=True,
                )
            else:
                roles.add(str(role))
            if not _is_nonempty_string(field.get("meaning")):
                _diag(
                    diagnostics,
                    "TYP003",
                    f"{field_location}.meaning",
                    "must be non-empty",
                    configuration=True,
                )

        if kind in RECORD_KINDS and "fields" not in item:
            _diag(
                diagnostics,
                "TYP003",
                f"{type_id}.fields",
                "record types must declare fields, including an empty list",
                configuration=True,
            )
        if kind == "enum":
            values = _list(
                item.get("values"),
                diagnostics,
                "TYP003",
                f"{type_id}.values",
            )
            if not values or any(not _is_nonempty_string(value) for value in values):
                _diag(
                    diagnostics,
                    "TYP003",
                    f"{type_id}.values",
                    "enum values must be a non-empty string list",
                    configuration=True,
                )
        if kind == "alias" and not _is_nonempty_string(item.get("target")):
            _diag(
                diagnostics,
                "TYP003",
                f"{type_id}.target",
                "alias requires a target",
                configuration=True,
            )
        if kind == "function-pointer":
            signature = _mapping(
                item.get("signature"),
                diagnostics,
                "TYP003",
                f"{type_id}.signature",
            )
            if not _is_nonempty_string(signature.get("returns")):
                _diag(
                    diagnostics,
                    "TYP003",
                    f"{type_id}.signature.returns",
                    "must be non-empty",
                    configuration=True,
                )
            _list(
                signature.get("parameters"),
                diagnostics,
                "TYP003",
                f"{type_id}.signature.parameters",
            )

        owner_level = owner.get("level")
        if (
            visibility in {"module-public", "cross-module"}
            and owner_level in {"L0", "L1", "L2"}
            and roles.intersection(EXTERNAL_FIELD_ROLES)
        ):
            _diag(
                diagnostics,
                "TYP004",
                type_id,
                "functional public types cannot expose adapter, framework, wire, or storage fields",
            )
        if roles.intersection({"adapter-binding", "framework-handle"}):
            allowed_mapping = (
                semantic_kind == "adapter-binding"
                and owner_level == "L3+"
                and visibility == "private"
            ) or (
                semantic_kind == "composition-mapping"
                and owner_level == "L0"
                and owner.get("role") == "composition"
                and visibility == "private"
            )
            if not allowed_mapping:
                _diag(
                    diagnostics,
                    "TYP004",
                    type_id,
                    "adapter/framework fields require a private L3+ binding or private L0 composition mapping",
                )

    raw_exclusions = _list(
        data.get("type_exclusions"),
        diagnostics,
        "TYP007",
        "type_exclusions",
    )
    seen_paths: set[str] = set()
    for index, raw_exclusion in enumerate(raw_exclusions):
        location = f"type_exclusions[{index}]"
        exclusion = _mapping(raw_exclusion, diagnostics, "TYP007", location)
        owner_id = str(exclusion.get("owner", ""))
        owner = modules.get(owner_id)
        path = str(exclusion.get("path", ""))
        if owner is None or owner.get("level") != "L3+":
            _diag(
                diagnostics,
                "TYP007",
                f"{location}.owner",
                "type exclusions must belong to an L3+ module",
            )
        elif not _owned_path(path.rstrip("*").rstrip("/"), owner):
            _diag(
                diagnostics,
                "TYP007",
                f"{location}.path",
                "excluded path must be owned by the declared module",
            )
        if not _is_nonempty_string(path) or Path(path).is_absolute() or path.startswith("../"):
            _diag(
                diagnostics,
                "TYP007",
                f"{location}.path",
                "must be a project-relative path or prefix glob",
                configuration=True,
            )
        elif path in seen_paths:
            _diag(
                diagnostics,
                "TYP007",
                f"{location}.path",
                "duplicate exclusion path",
                configuration=True,
            )
        seen_paths.add(path)
        if exclusion.get("classification") not in {"vendor", "generated"}:
            _diag(
                diagnostics,
                "TYP007",
                f"{location}.classification",
                "must be vendor or generated",
                configuration=True,
            )
        for key in ("source", "reason"):
            if not _is_nonempty_string(exclusion.get(key)):
                _diag(
                    diagnostics,
                    "TYP007",
                    f"{location}.{key}",
                    "must be non-empty",
                    configuration=True,
                )

    return diagnostics
