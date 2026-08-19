"""Validate pre-code boundary design and parent mapping declarations."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from check_architecture import Diagnostic, _diag, _is_nonempty_string


ID_PATTERN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
EDGE_PATTERN = re.compile(
    r"(?P<source>[a-z0-9]+(?:[._-][a-z0-9]+)*)"
    r"->(?P<target>[a-z0-9]+(?:[._-][a-z0-9]+)*)"
)


def _list(
    value: Any,
    diagnostics: list[Diagnostic],
    location: str,
) -> list[Any]:
    if not isinstance(value, list):
        _diag(
            diagnostics,
            "BND001",
            location,
            "must be a list",
            configuration=True,
        )
        return []
    return value


def _module_ref(
    value: Any,
    modules: dict[str, dict[str, Any]],
    diagnostics: list[Diagnostic],
    location: str,
    *,
    optional: bool = False,
) -> str | None:
    if optional and value is None:
        return None
    if not _is_nonempty_string(value) or str(value) not in modules:
        _diag(diagnostics, "BND002", location, "must reference a module")
        return None
    return str(value)


def _parent_of(module_id: str, modules: dict[str, dict[str, Any]]) -> str | None:
    value = modules[module_id].get("parent")
    return str(value) if _is_nonempty_string(value) else None


def validate_boundary_catalog(
    data: dict[str, Any],
    manifest_path: Path,
) -> list[Diagnostic]:
    """Validate machine-readable Boundary Design Table rows."""
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
    states = {
        str(item.get("id")): item
        for item in data.get("state_objects", [])
        if isinstance(item, dict) and _is_nonempty_string(item.get("id"))
    }
    rows = _list(data.get("boundary_mappings"), diagnostics, "boundary_mappings")
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        location = f"boundary_mappings[{index}]"
        if not isinstance(raw, dict):
            _diag(
                diagnostics,
                "BND001",
                location,
                "must be a mapping",
                configuration=True,
            )
            continue
        row_id = raw.get("id")
        if (
            not _is_nonempty_string(row_id)
            or not ID_PATTERN.fullmatch(str(row_id))
        ):
            _diag(
                diagnostics,
                "BND001",
                f"{location}.id",
                "must be a stable lowercase id",
                configuration=True,
            )
            row_id = location
        row_id = str(row_id)
        if row_id in seen:
            _diag(
                diagnostics,
                "BND001",
                row_id,
                "duplicate boundary mapping id",
                configuration=True,
            )
        seen.add(row_id)
        if not _is_nonempty_string(raw.get("interaction")):
            _diag(
                diagnostics,
                "BND001",
                f"{row_id}.interaction",
                "must describe the cross-module behavior",
                configuration=True,
            )
        producer = _module_ref(
            raw.get("producer"), modules, diagnostics, f"{row_id}.producer"
        )
        consumer = _module_ref(
            raw.get("consumer"), modules, diagnostics, f"{row_id}.consumer"
        )
        parent = _module_ref(
            raw.get("parent"), modules, diagnostics, f"{row_id}.parent"
        )
        mapping_owner = _module_ref(
            raw.get("mapping_owner"),
            modules,
            diagnostics,
            f"{row_id}.mapping_owner",
            optional=True,
        )
        if producer and consumer and producer == consumer:
            _diag(
                diagnostics,
                "BND002",
                row_id,
                "boundary producer and consumer must be different modules",
            )
        if producer and consumer and parent:
            producer_parent = _parent_of(producer, modules)
            consumer_parent = _parent_of(consumer, modules)
            siblings = producer_parent == parent and consumer_parent == parent
            producer_child = consumer == parent and producer_parent == parent
            consumer_child = producer == parent and consumer_parent == parent
            if not (siblings or producer_child or consumer_child):
                _diag(
                    diagnostics,
                    "BND002",
                    f"{row_id}.parent",
                    "must coordinate two children or participate as their parent",
                )

        contract_ids: list[str] = []
        for field in ("producer_contract", "consumer_contract"):
            contract = raw.get(field)
            if contract is None:
                continue
            if not _is_nonempty_string(contract) or str(contract) not in types:
                _diag(
                    diagnostics,
                    "BND003",
                    f"{row_id}.{field}",
                    "must reference a Type Catalog id or be null",
                )
            else:
                contract_ids.append(str(contract))
        producer_contract = raw.get("producer_contract")
        consumer_contract = raw.get("consumer_contract")
        if producer and producer_contract in types:
            if types[str(producer_contract)].get("owner") != producer:
                _diag(
                    diagnostics,
                    "BND003",
                    f"{row_id}.producer_contract",
                    "producer contract must be owned by the producer",
                )
        if consumer and consumer_contract in types:
            contract_owner = str(types[str(consumer_contract)].get("owner", ""))
            direct_reuse = (
                producer_contract is not None
                and consumer_contract == producer_contract
            )
            if direct_reuse and contract_owner != consumer:
                if contract_owner not in modules[consumer].get("depends_on", []):
                    _diag(
                        diagnostics,
                        "BND003",
                        f"{row_id}.consumer_contract",
                        f"direct contract reuse requires declared dependency {consumer}->{contract_owner}",
                    )
            elif not direct_reuse and contract_owner != consumer:
                _diag(
                    diagnostics,
                    "BND003",
                    f"{row_id}.consumer_contract",
                    "a distinct consumer contract must be owned by the consumer",
                )
        needs_mapping = (
            producer_contract is not None
            and consumer_contract is not None
            and producer_contract != consumer_contract
        )
        if needs_mapping and mapping_owner != parent:
            _diag(
                diagnostics,
                "BND004",
                f"{row_id}.mapping_owner",
                "distinct sibling contracts require their parent as mapping owner",
            )
        if not needs_mapping and mapping_owner is not None and mapping_owner != parent:
            _diag(
                diagnostics,
                "BND004",
                f"{row_id}.mapping_owner",
                "mapping may be owned only by the coordinating parent",
            )

        state_refs = _list(
            raw.get("state_objects"),
            diagnostics,
            f"{row_id}.state_objects",
        )
        for state_index, state_ref in enumerate(state_refs):
            if not _is_nonempty_string(state_ref) or str(state_ref) not in states:
                _diag(
                    diagnostics,
                    "BND005",
                    f"{row_id}.state_objects[{state_index}]",
                    "must reference a state_objects id",
                )

        allowed: set[tuple[str, str]] = set()
        forbidden: set[tuple[str, str]] = set()
        for field, target in (
            ("allowed_edges", allowed),
            ("forbidden_edges", forbidden),
        ):
            for edge_index, raw_edge in enumerate(
                _list(raw.get(field), diagnostics, f"{row_id}.{field}")
            ):
                match = (
                    EDGE_PATTERN.fullmatch(str(raw_edge))
                    if _is_nonempty_string(raw_edge)
                    else None
                )
                if not match:
                    _diag(
                        diagnostics,
                        "BND006",
                        f"{row_id}.{field}[{edge_index}]",
                        "must use source->target module ids",
                        configuration=True,
                    )
                    continue
                edge = (match.group("source"), match.group("target"))
                if edge[0] not in modules or edge[1] not in modules:
                    _diag(
                        diagnostics,
                        "BND006",
                        f"{row_id}.{field}[{edge_index}]",
                        "edge references an unknown module",
                    )
                target.add(edge)
        for source, target in allowed:
            if source in modules and target in modules and target not in modules[source].get("depends_on", []):
                _diag(
                    diagnostics,
                    "BND006",
                    f"{row_id}.allowed_edges",
                    f"allowed edge {source}->{target} is absent from depends_on",
                )
        for source, target in forbidden:
            if source in modules and target in modules and target in modules[source].get("depends_on", []):
                _diag(
                    diagnostics,
                    "BND006",
                    f"{row_id}.forbidden_edges",
                    f"forbidden edge {source}->{target} is declared in depends_on",
                )
        if allowed.intersection(forbidden):
            _diag(
                diagnostics,
                "BND006",
                row_id,
                "the same edge cannot be both allowed and forbidden",
                configuration=True,
            )
        if contract_ids and producer and consumer and not raw.get("forbidden_edges"):
            _diag(
                diagnostics,
                "BND006",
                f"{row_id}.forbidden_edges",
                "typed sibling boundaries must declare forbidden direct edges",
                configuration=True,
            )

    return diagnostics
