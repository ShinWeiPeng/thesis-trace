"""Fail-closed libclang evidence for C/C++ type and state ownership."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from check_architecture import Diagnostic, dependency_violation
from libclang_toolchain_contract import ToolchainProviderError
from source_sets import classify_path


SOURCE_SUFFIXES = {".c", ".cc", ".cpp"}
HEADER_SUFFIXES = {".h", ".hh", ".hpp"}
C_LANGUAGES = {"c", "c++", "cpp"}
_ROOT_ITEMS_CACHE: dict[
    int,
    tuple[
        dict[str, list[Path]],
        tuple[tuple[str, tuple[str, ...]], ...],
    ],
] = {}


@dataclass
class AstEvidence:
    mode: str = "not-run"
    covered_files: set[Path] = field(default_factory=set)
    includes: list[tuple[Path, Path, int]] = field(default_factory=list)
    catalog_only_generated_state: list[dict[str, str]] = field(default_factory=list)
    toolchain: dict[str, str] = field(default_factory=dict)
    translation_units: list[dict[str, Any]] = field(default_factory=list)
    worker_count: int = 1


@lru_cache(maxsize=None)
def _resolved(raw_path: str) -> Path:
    return Path(raw_path).resolve()


def _inside(path: Path, root: Path) -> bool:
    try:
        _resolved(str(path)).relative_to(_resolved(str(root)))
        return True
    except ValueError:
        return False


@lru_cache(maxsize=None)
def _relative_strings(raw_path: str, raw_root: str) -> str:
    return Path(
        os.path.relpath(
            str(_resolved(raw_path)),
            str(_resolved(raw_root)),
        )
    ).as_posix()


def _relative(path: Path, root: Path) -> str:
    return _relative_strings(str(path), str(root))


def _roots(
    project_root: Path,
    modules: dict[str, dict[str, Any]],
) -> dict[str, list[Path]]:
    return {
        module_id: [
            (project_root / str(raw)).resolve()
            for raw in module.get("paths", [])
        ]
        for module_id, module in modules.items()
    }


@lru_cache(maxsize=None)
def _owner_from_roots(
    raw_path: str,
    root_items: tuple[tuple[str, tuple[str, ...]], ...],
) -> str | None:
    path = _resolved(raw_path)
    matches: list[tuple[int, str]] = []
    for module_id, raw_candidates in root_items:
        for raw_candidate in raw_candidates:
            candidate = _resolved(raw_candidate)
            if _inside(path, candidate):
                matches.append((len(candidate.parts), module_id))
    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][1]


def _owner(path: Path, roots: dict[str, list[Path]]) -> str | None:
    cache_key = id(roots)
    cached = _ROOT_ITEMS_CACHE.get(cache_key)
    if cached is None or cached[0] is not roots:
        root_items = tuple(
            (module_id, tuple(str(candidate) for candidate in candidates))
            for module_id, candidates in sorted(roots.items())
        )
        _ROOT_ITEMS_CACHE[cache_key] = (roots, root_items)
    else:
        root_items = cached[1]
    return _owner_from_roots(str(path), root_items)


def _governed_files(
    roots: dict[str, list[Path]],
    suffixes: set[str],
) -> set[Path]:
    result: set[Path] = set()
    for candidates in roots.values():
        for candidate in candidates:
            if candidate.is_file() and candidate.suffix.lower() in suffixes:
                result.add(candidate.resolve())
            elif candidate.is_dir():
                result.update(
                    path.resolve()
                    for path in candidate.rglob("*")
                    if path.is_file() and path.suffix.lower() in suffixes
                )
    return result


def _load_compilation_database(
    path: Path,
    project_root: Path,
    diagnostics: list[Diagnostic],
) -> list[dict[str, Any]]:
    if not path.is_file():
        diagnostics.append(
            Diagnostic(
                "CAST002",
                "MUST",
                str(path),
                "required compilation database does not exist",
                True,
            )
        )
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        diagnostics.append(
            Diagnostic(
                "CAST002",
                "MUST",
                str(path),
                f"invalid compilation database: {exc}",
                True,
            )
        )
        return []
    if not isinstance(raw, list):
        diagnostics.append(
            Diagnostic(
                "CAST002",
                "MUST",
                str(path),
                "compilation database must contain a JSON list",
                True,
            )
        )
        return []
    entries: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or not isinstance(item.get("file"), str):
            diagnostics.append(
                Diagnostic(
                    "CAST002",
                    "MUST",
                    f"{path}[{index}]",
                    "entry requires a source file",
                    True,
                )
            )
            continue
        directory = Path(str(item.get("directory", project_root)))
        if not directory.is_absolute():
            directory = project_root / directory
        source = Path(item["file"])
        if not source.is_absolute():
            source = directory / source
        item = dict(item)
        item["_directory"] = directory.resolve()
        item["_source"] = source.resolve()
        entries.append(item)
    return entries


def _command_arguments(entry: dict[str, Any]) -> list[str]:
    raw_arguments = entry.get("arguments")
    if isinstance(raw_arguments, list) and all(
        isinstance(item, str) for item in raw_arguments
    ):
        return list(raw_arguments)
    command = entry.get("command")
    if not isinstance(command, str):
        return []
    return shlex.split(command, posix=os.name != "nt")


def _strip_outer_quotes(value: str) -> str:
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in {"'", '"'}
    ):
        return value[1:-1]
    return value


def _gcc_implicit_include_arguments(
    compiler: Path | None,
    target_triple: str,
    *,
    cplusplus: bool,
) -> list[str]:
    """Reify GCC driver implicit headers for libclang's explicit parse API."""
    if compiler is None or not compiler.is_file() or target_triple == "native":
        return []
    root = compiler.parent.parent
    gcc_versions = sorted(
        (root / "lib" / "gcc" / target_triple).glob("*"),
        reverse=True,
    )
    cxx_versions = sorted(
        (root / target_triple / "include" / "c++").glob("*"),
        reverse=True,
    )
    candidates: list[Path] = []
    if cplusplus and cxx_versions:
        cxx = cxx_versions[0]
        candidates.extend([cxx, cxx / target_triple, cxx / "backward"])
    if gcc_versions:
        gcc = gcc_versions[0]
        candidates.extend([gcc / "include", gcc / "include-fixed"])
    candidates.extend(
        [
            root / target_triple / "sys-include",
            root / target_triple / "include",
        ]
    )
    arguments: list[str] = []
    for candidate in candidates:
        if candidate.is_dir():
            arguments.extend(["-isystem", str(candidate)])
    return arguments


def _parse_arguments(
    entry: dict[str, Any],
    target_triple: str,
) -> list[str]:
    """Keep semantic compiler arguments and discard build-output arguments."""
    original = _command_arguments(entry)
    compiler = Path(_strip_outer_quotes(original[0])).resolve() if original else None
    if original:
        original = original[1:]
    source = Path(entry["_source"]).resolve()
    result: list[str] = []
    takes_value = {"-I", "-isystem", "-iquote", "-include", "-D", "-U", "-x"}
    skip_value = {"-o", "-MF", "-MT", "-MQ", "-MJ"}
    index = 0
    while index < len(original):
        argument = _strip_outer_quotes(original[index])
        if argument in skip_value:
            index += 2
            continue
        if argument in {"-c", "-MMD", "-MD", "-MP", "-MM", "-M"}:
            index += 1
            continue
        candidate = Path(argument.strip('"'))
        if candidate.is_absolute() and candidate.resolve() == source:
            index += 1
            continue
        if argument.strip('"') == str(entry.get("file", "")):
            index += 1
            continue
        if argument in takes_value:
            if index + 1 < len(original):
                result.extend(
                    [argument, _strip_outer_quotes(original[index + 1])]
                )
            index += 2
            continue
        if argument.startswith(
            (
                "-I",
                "-D",
                "-U",
                "-std=",
                "--target=",
                "-isystem",
                "-iquote",
                "-include",
                "-fshort-enums",
                "-fshort-wchar",
                "-funsigned-char",
                "-fsigned-char",
                "-m",
            )
        ):
            if argument.startswith("--specs="):
                index += 1
                continue
            result.append(argument)
        index += 1
    if target_triple != "native" and not any(
        argument.startswith("--target=") for argument in result
    ):
        result.append(f"--target={target_triple}")
    if (
        target_triple != "native"
        and compiler is not None
        and compiler.is_file()
        and any(
            token in compiler.name.lower()
            for token in ("gcc", "g++", "cc", "c++")
        )
        and not any(argument.startswith("--gcc-toolchain=") for argument in result)
    ):
        result.append(f"--gcc-toolchain={compiler.parent.parent}")
        result.extend(
            _gcc_implicit_include_arguments(
                compiler,
                target_triple,
                cplusplus=source.suffix.lower() in {".cc", ".cpp", ".cxx"},
            )
        )
    return result


def _normal_type(value: str) -> str:
    value = re.sub(r"\b(const|volatile|restrict)\b", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _cursor_path(cursor: Any) -> Path | None:
    location = getattr(cursor, "location", None)
    file = getattr(location, "file", None)
    if file is None:
        return None
    return _resolved(str(file))


def _cursor_line(cursor: Any) -> int:
    return int(getattr(getattr(cursor, "location", None), "line", 0) or 0)


def _walk(
    cursor: Any,
    project_root: Path,
    ancestors: tuple[Any, ...] = (),
) -> Iterable[tuple[Any, tuple[Any, ...]]]:
    path = _cursor_path(cursor)
    if path is not None and not _inside(path, project_root):
        return
    yield cursor, ancestors
    for child in cursor.get_children():
        yield from _walk(child, project_root, (*ancestors, cursor))


def _declaration_kind(cursor: Any, cindex: Any) -> tuple[str | None, Any]:
    kind = cursor.kind
    if kind == cindex.CursorKind.STRUCT_DECL:
        return "struct", cursor
    if kind == cindex.CursorKind.UNION_DECL:
        return "union", cursor
    if kind == cindex.CursorKind.ENUM_DECL:
        return "enum", cursor
    if kind == cindex.CursorKind.CLASS_DECL:
        return "class", cursor
    if kind in {
        cindex.CursorKind.TYPEDEF_DECL,
        getattr(cindex.CursorKind, "TYPE_ALIAS_DECL", cindex.CursorKind.TYPEDEF_DECL),
    }:
        underlying = cursor.underlying_typedef_type
        canonical = underlying.get_canonical()
        if canonical.kind == cindex.TypeKind.POINTER:
            pointee = canonical.get_pointee()
            if pointee.kind in {
                cindex.TypeKind.FUNCTIONPROTO,
                cindex.TypeKind.FUNCTIONNOPROTO,
            }:
                return "function-pointer", cursor
        declaration = underlying.get_declaration()
        if declaration and not declaration.spelling:
            if declaration.kind == cindex.CursorKind.STRUCT_DECL:
                return "struct", declaration
            if declaration.kind == cindex.CursorKind.UNION_DECL:
                return "union", declaration
            if declaration.kind == cindex.CursorKind.ENUM_DECL:
                return "enum", declaration
        return "alias", cursor
    return None, cursor


def _type_shape(symbol_cursor: Any, shape_cursor: Any, kind: str, cindex: Any) -> dict[str, Any]:
    if kind in {"struct", "union", "class"}:
        return {
            "fields": [
                {
                    "name": child.spelling,
                    "type": _normal_type(child.type.spelling),
                }
                for child in shape_cursor.get_children()
                if child.kind == cindex.CursorKind.FIELD_DECL
            ]
        }
    if kind == "enum":
        return {
            "values": [
                child.spelling
                for child in shape_cursor.get_children()
                if child.kind == cindex.CursorKind.ENUM_CONSTANT_DECL
            ]
        }
    if kind == "alias":
        return {"target": _normal_type(symbol_cursor.underlying_typedef_type.spelling)}
    if kind == "function-pointer":
        function = symbol_cursor.underlying_typedef_type.get_canonical().get_pointee()
        return {
            "signature": {
                "returns": _normal_type(function.get_result().spelling),
                "parameters": [
                    _normal_type(argument.spelling)
                    for argument in function.argument_types()
                ],
            }
        }
    return {}


def _type_declarations(
    cursors: list[Any],
    project_root: Path,
    cindex: Any,
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, tuple[str, str]]]:
    declarations: dict[tuple[str, str], dict[str, Any]] = {}
    usr_to_key: dict[str, tuple[str, str]] = {}
    for cursor in cursors:
        path = _cursor_path(cursor)
        if path is None or not _inside(path, project_root):
            continue
        kind, shape_cursor = _declaration_kind(cursor, cindex)
        if (
            kind is None
            or not cursor.spelling
            or cursor.spelling.startswith("(unnamed ")
            or not cursor.is_definition()
        ):
            continue
        key = (_relative(path, project_root), cursor.spelling)
        declarations[key] = {
            "path": key[0],
            "symbol": key[1],
            "kind": kind,
            **_type_shape(cursor, shape_cursor, kind, cindex),
        }
        usr = cursor.get_usr()
        if usr:
            usr_to_key[usr] = key
        shape_usr = shape_cursor.get_usr()
        if shape_usr:
            usr_to_key[shape_usr] = key
    return declarations, usr_to_key


def _catalog_type_checks(
    manifest: dict[str, Any],
    declarations: dict[tuple[str, str], dict[str, Any]],
    project_root: Path,
    diagnostics: list[Diagnostic],
) -> dict[str, dict[str, Any]]:
    exclusions = [
        str(item.get("path", ""))
        for item in manifest.get("type_exclusions", [])
        if isinstance(item, dict)
    ]

    def excluded(path: str) -> bool:
        classification, _ = classify_path(manifest, path)
        if classification != "production":
            return True
        candidate = Path(path)
        return any(
            pattern
            and (
                candidate.match(pattern)
                or path.startswith(pattern.rstrip("*").rstrip("/"))
            )
            for pattern in exclusions
        )

    governed = {
        key: value for key, value in declarations.items() if not excluded(key[0])
    }
    catalog = {
        (
            str(item.get("declaration", {}).get("path", "")),
            str(item.get("declaration", {}).get("symbol", "")),
        ): item
        for item in manifest.get("types", [])
        if isinstance(item, dict)
        and str(item.get("language", "")).lower() in C_LANGUAGES
    }
    for key, declaration in governed.items():
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
        expected = catalog[key]
        if expected.get("declaration", {}).get("kind") != declaration["kind"]:
            diagnostics.append(
                Diagnostic(
                    "CTYPE003",
                    "MUST",
                    f"{key[0]}:{key[1]}",
                    "catalog kind does not match the AST declaration",
                )
            )
            continue
        if declaration["kind"] in {"struct", "union", "class"}:
            actual = [
                (item["name"], item["type"])
                for item in declaration.get("fields", [])
            ]
            declared = [
                (
                    str(item.get("name")),
                    _normal_type(str(item.get("type", ""))),
                )
                for item in expected.get("fields", [])
                if isinstance(item, dict)
            ]
            if actual != declared:
                diagnostics.append(
                    Diagnostic(
                        "CTYPE003",
                        "MUST",
                        f"{key[0]}:{key[1]}",
                        f"catalog fields {declared!r} do not match AST fields {actual!r}",
                    )
                )
        elif declaration["kind"] == "enum" and expected.get("values") != declaration.get("values"):
            diagnostics.append(
                Diagnostic(
                    "CTYPE003",
                    "MUST",
                    f"{key[0]}:{key[1]}",
                    "catalog enum values do not match the AST declaration",
                )
            )
        elif declaration["kind"] == "alias" and _normal_type(
            str(expected.get("target", ""))
        ) != declaration.get("target"):
            diagnostics.append(
                Diagnostic(
                    "CTYPE003",
                    "MUST",
                    f"{key[0]}:{key[1]}",
                    "catalog alias target does not match the AST declaration",
                )
            )
    for key in sorted(set(catalog).difference(governed)):
        diagnostics.append(
            Diagnostic(
                "CTYPE002",
                "MUST",
                f"{key[0]}:{key[1]}",
                "cataloged C/C++ type declaration is missing from AST evidence",
            )
        )
    return {
        str(item.get("id")): item
        for item in catalog.values()
        if isinstance(item, dict)
    }


def _referenced_type_usrs(type_value: Any, cindex: Any) -> set[str]:
    result: set[str] = set()
    seen: set[tuple[int, str]] = set()

    def visit(current: Any) -> None:
        key = (current.kind, current.spelling)
        if key in seen:
            return
        seen.add(key)
        declaration = current.get_declaration()
        if declaration:
            usr = declaration.get_usr()
            if usr:
                result.add(usr)
        if current.kind == cindex.TypeKind.POINTER:
            visit(current.get_pointee())
        elif current.kind in {
            cindex.TypeKind.CONSTANTARRAY,
            cindex.TypeKind.INCOMPLETEARRAY,
            cindex.TypeKind.VARIABLEARRAY,
        }:
            visit(current.element_type)
        elif current.kind in {
            cindex.TypeKind.FUNCTIONPROTO,
            cindex.TypeKind.FUNCTIONNOPROTO,
        }:
            visit(current.get_result())
            if current.kind == cindex.TypeKind.FUNCTIONPROTO:
                for argument in current.argument_types():
                    visit(argument)
        canonical = current.get_canonical()
        canonical_key = (canonical.kind, canonical.spelling)
        if canonical_key != key:
            visit(canonical)

    visit(type_value)
    return result


def _type_dependency_checks(
    cursors: list[Any],
    usr_to_key: dict[str, tuple[str, str]],
    manifest: dict[str, Any],
    project_root: Path,
    roots: dict[str, list[Path]],
    diagnostics: list[Diagnostic],
    cindex: Any,
) -> None:
    modules = {
        str(item.get("id")): item
        for item in manifest.get("modules", [])
        if isinstance(item, dict) and item.get("id")
    }
    catalog_by_key = {
        (
            str(item.get("declaration", {}).get("path", "")),
            str(item.get("declaration", {}).get("symbol", "")),
        ): item
        for item in manifest.get("types", [])
        if isinstance(item, dict)
    }
    port_owners: dict[str, set[str]] = {}
    for port in manifest.get("ports", []):
        if not isinstance(port, dict):
            continue
        for adapter in port.get("implemented_by", []):
            port_owners.setdefault(str(adapter), set()).add(str(port.get("owner")))
    declaration_kinds = {
        cindex.CursorKind.FIELD_DECL,
        cindex.CursorKind.PARM_DECL,
        cindex.CursorKind.VAR_DECL,
        cindex.CursorKind.FUNCTION_DECL,
        cindex.CursorKind.TYPEDEF_DECL,
    }
    seen: set[tuple[str, str, str, int]] = set()
    for cursor in cursors:
        if cursor.kind not in declaration_kinds:
            continue
        path = _cursor_path(cursor)
        if path is None or not _inside(path, project_root):
            continue
        source_owner = _owner(path, roots)
        if source_owner not in modules:
            continue
        types = [cursor.type]
        if cursor.kind == cindex.CursorKind.FUNCTION_DECL:
            types.append(cursor.result_type)
        for type_value in types:
            for usr in _referenced_type_usrs(type_value, cindex):
                key = usr_to_key.get(usr)
                target = catalog_by_key.get(key) if key else None
                if not target:
                    continue
                target_owner = str(target.get("owner", ""))
                if not target_owner or target_owner == source_owner:
                    continue
                edge = (source_owner, target_owner, str(path), _cursor_line(cursor))
                if edge in seen:
                    continue
                seen.add(edge)
                location = f"{_relative(path, project_root)}:{_cursor_line(cursor)}"
                if target_owner not in modules[source_owner].get("depends_on", []):
                    diagnostics.append(
                        Diagnostic(
                            "CTYPE005",
                            "MUST",
                            location,
                            f"actual type reference creates undeclared dependency {source_owner}->{target_owner}",
                        )
                    )
                violation = dependency_violation(
                    modules[source_owner],
                    modules.get(target_owner, {}),
                    port_owners,
                )
                if violation:
                    diagnostics.append(
                        Diagnostic("CTYPE005", "MUST", location, violation[1])
                    )


def _storage_name(cursor: Any, cindex: Any) -> str:
    tokens = " ".join(token.spelling for token in cursor.get_tokens())
    if "_Thread_local" in tokens or "thread_local" in tokens or "__thread" in tokens:
        return "thread-local"
    if cursor.storage_class == cindex.StorageClass.STATIC:
        return "file-static"
    return "external-linkage"


def _mutable_global(cursor: Any, cindex: Any) -> bool:
    if cursor.kind != cindex.CursorKind.VAR_DECL:
        return False
    parent = cursor.semantic_parent
    if parent is None or parent.kind != cindex.CursorKind.TRANSLATION_UNIT:
        return False
    if cursor.storage_class == cindex.StorageClass.EXTERN:
        return False
    canonical = cursor.type.get_canonical()
    if canonical.is_const_qualified():
        return False
    if canonical.kind in {
        cindex.TypeKind.CONSTANTARRAY,
        cindex.TypeKind.INCOMPLETEARRAY,
        cindex.TypeKind.VARIABLEARRAY,
    } and canonical.element_type.is_const_qualified():
        return False
    return True


def _assignment_write(reference: Any, ancestors: tuple[Any, ...], cindex: Any) -> tuple[bool, bool]:
    """Return (write, address_escape) using conservative AST ancestry."""
    for ancestor in reversed(ancestors):
        if ancestor.kind in {
            cindex.CursorKind.UNARY_OPERATOR,
            cindex.CursorKind.COMPOUND_ASSIGNMENT_OPERATOR,
        }:
            tokens = [token.spelling for token in ancestor.get_tokens()]
            if ancestor.kind == cindex.CursorKind.COMPOUND_ASSIGNMENT_OPERATOR:
                return True, False
            if any(token in {"++", "--"} for token in tokens):
                return True, False
            if "&" in tokens:
                return True, True
        if ancestor.kind == cindex.CursorKind.BINARY_OPERATOR:
            children = list(ancestor.get_children())
            tokens = [token.spelling for token in ancestor.get_tokens()]
            has_assignment = any(
                token in {"=", "+=", "-=", "*=", "/=", "%=", "|=", "&=", "^=", "<<=", ">>="}
                for token in tokens
            )
            if has_assignment and children:
                first = children[0].extent
                offset = int(getattr(reference.location, "offset", 0) or 0)
                start = int(getattr(first.start, "offset", 0) or 0)
                end = int(getattr(first.end, "offset", 0) or 0)
                if start <= offset <= end:
                    return True, False
            return False, False
        if ancestor.kind == cindex.CursorKind.CALL_EXPR:
            canonical = reference.type.get_canonical()
            if canonical.kind in {
                cindex.TypeKind.POINTER,
                cindex.TypeKind.CONSTANTARRAY,
                cindex.TypeKind.INCOMPLETEARRAY,
                cindex.TypeKind.VARIABLEARRAY,
            }:
                return True, True
            return False, False
        if ancestor.kind in {
            cindex.CursorKind.COMPOUND_STMT,
            cindex.CursorKind.RETURN_STMT,
            cindex.CursorKind.IF_STMT,
        }:
            break
    return False, False


def _state_checks(
    cursors_with_ancestors: list[tuple[Any, tuple[Any, ...]]],
    manifest: dict[str, Any],
    project_root: Path,
    roots: dict[str, list[Path]],
    diagnostics: list[Diagnostic],
    cindex: Any,
    evidence: AstEvidence,
) -> None:
    catalog = {
        (
            str(item.get("declaration", {}).get("path", "")),
            str(item.get("declaration", {}).get("symbol", "")),
        ): item
        for item in manifest.get("state_objects", [])
        if isinstance(item, dict)
        and str(item.get("language", "")).lower() in C_LANGUAGES
    }
    catalog_by_symbol = {
        str(item.get("declaration", {}).get("symbol", "")): item
        for item in catalog.values()
    }
    discovered: dict[tuple[str, str], Any] = {}
    usr_to_item: dict[str, dict[str, Any]] = {}
    for cursor, _ in cursors_with_ancestors:
        path = _cursor_path(cursor)
        if path is None or not _inside(path, project_root):
            continue
        classification, _ = classify_path(
            manifest, _relative(path, project_root)
        )
        if classification not in {"production", "generated-production"}:
            continue
        if _mutable_global(cursor, cindex):
            key = (_relative(path, project_root), cursor.spelling)
            discovered[key] = cursor
            item = catalog.get(key)
            if item is None:
                classification, source_set = classify_path(manifest, key[0])
                if classification == "generated-production" and source_set is not None:
                    owner = str(source_set.get("owner", ""))
                    item = {
                        "id": f"catalog-only:{key[0]}:{key[1]}",
                        "owner": owner,
                        "visibility": "module-public",
                        "read_authority": [owner],
                        "write_authority": [owner],
                    }
                    evidence.catalog_only_generated_state.append(
                        {"path": key[0], "symbol": key[1], "owner": owner}
                    )
                    diagnostics.append(
                        Diagnostic(
                            "CSTATE007",
                            "INFO",
                            f"{key[0]}:{key[1]}",
                            f"catalog-only generated state owned by {owner!r}",
                        )
                    )
                    usr = cursor.get_usr()
                    if usr:
                        usr_to_item[usr] = item
                    continue
                diagnostics.append(
                    Diagnostic(
                        "CSTATE001",
                        "MUST",
                        f"{key[0]}:{key[1]}",
                        "mutable static-storage object is missing from state_objects",
                    )
                )
                continue
            usr = cursor.get_usr()
            if usr:
                usr_to_item[usr] = item
            actual_owner = _owner(path, roots)
            expected_owner = str(item.get("owner", ""))
            expected_storage = str(item.get("declaration", {}).get("storage", ""))
            actual_storage = _storage_name(cursor, cindex)
            if actual_owner != expected_owner or actual_storage != expected_storage:
                diagnostics.append(
                    Diagnostic(
                        "CSTATE002",
                        "MUST",
                        f"{key[0]}:{key[1]}",
                        f"AST owner/storage {actual_owner!r}/{actual_storage!r} does not match catalog {expected_owner!r}/{expected_storage!r}",
                    )
                )
            if _normal_type(cursor.type.spelling) != _normal_type(str(item.get("type", ""))):
                diagnostics.append(
                    Diagnostic(
                        "CSTATE002",
                        "MUST",
                        f"{key[0]}:{key[1]}",
                        f"AST type {cursor.type.spelling!r} does not match catalog {item.get('type')!r}",
                    )
                )
    for key in sorted(set(catalog).difference(discovered)):
        diagnostics.append(
            Diagnostic(
                "CSTATE001",
                "MUST",
                f"{key[0]}:{key[1]}",
                "cataloged state object is missing from AST definitions",
            )
        )

    type_catalog = {
        str(item.get("id")): item
        for item in manifest.get("types", [])
        if isinstance(item, dict)
    }
    private_runtime_symbols = {
        str(item.get("declaration", {}).get("symbol"))
        for item in type_catalog.values()
        if item.get("visibility") == "private"
        and item.get("semantic_kind") in {"runtime-state", "private-helper"}
    }
    modules = {
        str(item.get("id")): item
        for item in manifest.get("modules", [])
        if isinstance(item, dict) and item.get("id")
    }
    for type_id, item in type_catalog.items():
        if (
            item.get("visibility") != "private"
            or item.get("semantic_kind") not in {"runtime-state", "private-helper"}
        ):
            continue
        owner = modules.get(str(item.get("owner")), {})
        declaration_path = str(item.get("declaration", {}).get("path", ""))
        if any(
            Path(declaration_path).match(str(pattern))
            for pattern in owner.get("public_headers", [])
        ):
            diagnostics.append(
                Diagnostic(
                    "CSTATE005",
                    "MUST",
                    f"{declaration_path}:{item.get('declaration', {}).get('symbol', '')}",
                    f"private runtime type {type_id!r} is defined in a public contract header",
                )
            )
    seen: set[tuple[str, str, int, str]] = set()
    for cursor, ancestors in cursors_with_ancestors:
        path = _cursor_path(cursor)
        if path is None or not _inside(path, project_root):
            continue
        classification, _ = classify_path(
            manifest, _relative(path, project_root)
        )
        if classification not in {"production", "generated-production"}:
            continue
        source_owner = _owner(path, roots)
        if source_owner is None:
            continue
        if cursor.kind == cindex.CursorKind.DECL_REF_EXPR:
            referenced = cursor.referenced
            if referenced is None or referenced.kind != cindex.CursorKind.VAR_DECL:
                continue
            item = usr_to_item.get(referenced.get_usr())
            if item is None:
                continue
            write, escape = _assignment_write(cursor, ancestors, cindex)
            rule = "CSTATE004" if write else "CSTATE003"
            authorities = (
                item.get("write_authority", [])
                if write
                else item.get("read_authority", [])
            )
            if source_owner not in authorities:
                key = (rule, _relative(path, project_root), _cursor_line(cursor), cursor.spelling)
                if key not in seen:
                    diagnostics.append(
                        Diagnostic(
                            rule,
                            "MUST",
                            f"{key[1]}:{key[2]}",
                            f"module {source_owner!r} is not authorized to {'write or escape' if write else 'read'} state object {item.get('id')!r}",
                        )
                    )
                    seen.add(key)
            if escape and item.get("visibility") == "private":
                diagnostics.append(
                    Diagnostic(
                        "CSTATE005",
                        "MUST",
                        f"{_relative(path, project_root)}:{_cursor_line(cursor)}",
                        f"private state object {item.get('id')!r} escapes through an address or mutable pointer",
                    )
                )
        elif cursor.kind == cindex.CursorKind.VAR_DECL and cursor.storage_class == cindex.StorageClass.EXTERN:
            referenced = cursor.get_definition()
            item = (
                usr_to_item.get(referenced.get_usr())
                if referenced
                else usr_to_item.get(cursor.get_usr())
            )
            item = item or catalog_by_symbol.get(cursor.spelling)
            if item is None:
                key = (
                    "CSTATE001",
                    _relative(path, project_root),
                    _cursor_line(cursor),
                    cursor.spelling,
                )
                if key not in seen:
                    diagnostics.append(
                        Diagnostic(
                            "CSTATE001",
                            "MUST",
                            f"{key[1]}:{key[2]}",
                            f"extern object {cursor.spelling!r} is missing from state_objects",
                        )
                    )
                    seen.add(key)
            if item and item.get("visibility") == "private":
                diagnostics.append(
                    Diagnostic(
                        "CSTATE005",
                        "MUST",
                        f"{_relative(path, project_root)}:{_cursor_line(cursor)}",
                        f"private state object {item.get('id')!r} is exposed through extern",
                    )
                )
        elif cursor.kind == cindex.CursorKind.MEMBER_REF_EXPR:
            field = cursor.referenced
            parent_type = field.semantic_parent if field is not None else None
            type_name = str(getattr(parent_type, "spelling", ""))
            if type_name in private_runtime_symbols:
                declaration_path = _cursor_path(parent_type)
                target_owner = _owner(declaration_path, roots) if declaration_path else None
                if target_owner and target_owner != source_owner:
                    diagnostics.append(
                        Diagnostic(
                            "CSTATE006",
                            "MUST",
                            f"{_relative(path, project_root)}:{_cursor_line(cursor)}",
                            f"module {source_owner!r} dereferences private runtime type owned by {target_owner!r}",
                        )
                    )


def analyze_ast(
    manifest: dict[str, Any],
    project_root: Path,
    diagnostics: list[Diagnostic],
) -> AstEvidence:
    """Append AST diagnostics and return coverage/include evidence."""
    evidence = AstEvidence()
    modules = {
        str(item.get("id")): item
        for item in manifest.get("modules", [])
        if isinstance(item, dict) and item.get("id")
    }
    roots = _roots(project_root, modules)
    governed_sources = {
        path
        for path in _governed_files(roots, SOURCE_SUFFIXES)
        if classify_path(manifest, _relative(path, project_root))[0]
        in {"production", "generated-production"}
    }
    governed_headers = {
        path
        for path in _governed_files(roots, HEADER_SUFFIXES)
        if classify_path(manifest, _relative(path, project_root))[0]
        in {"production", "generated-production"}
    }
    ast = manifest.get("c_analyzer", {}).get("ast", {})
    status = ast.get("status") if isinstance(ast, dict) else None
    if not governed_sources:
        if status != "not-applicable":
            diagnostics.append(
                Diagnostic(
                    "CAST001",
                    "MUST",
                    "c_analyzer.ast.status",
                    "projects without governed C/C++ translation units must declare AST not-applicable",
                    True,
                )
            )
        evidence.mode = "not-applicable"
        return evidence
    if status != "required":
        diagnostics.append(
            Diagnostic(
                "CAST001",
                "MUST",
                "c_analyzer.ast.status",
                "governed C/C++ translation units require libclang AST analysis",
                True,
            )
        )
        return evidence
    try:
        from libclang_toolchain_adapter import EspressifLibclangToolchainAdapter

        toolchain = EspressifLibclangToolchainAdapter().verify(
            project_root / "architecture" / "toolchain-lock.yaml"
        )
        evidence.toolchain = toolchain.to_dict()
    except ToolchainProviderError as exc:
        diagnostics.append(
            Diagnostic(
                exc.rule_id,
                "MUST",
                exc.location,
                exc.message,
                True,
            )
        )
        return evidence
    except (ImportError, OSError) as exc:
        diagnostics.append(
            Diagnostic("CAST001", "MUST", "libclang-provider", str(exc), True)
        )
        return evidence
    try:
        from clang import cindex
    except (ImportError, OSError) as exc:
        diagnostics.append(
            Diagnostic(
                "CAST001",
                "MUST",
                "libclang",
                f"clang==20.1.5 binding is required: {exc}",
                True,
            )
        )
        return evidence

    database = project_root / str(ast.get("compilation_database", ""))
    entries = _load_compilation_database(database, project_root, diagnostics)
    if not entries:
        return evidence
    entries_by_source = {
        Path(entry["_source"]).resolve(): entry
        for entry in entries
        if Path(entry["_source"]).suffix.lower() in SOURCE_SUFFIXES
    }
    missing_sources = sorted(governed_sources.difference(entries_by_source))
    for source in missing_sources:
        diagnostics.append(
            Diagnostic(
                "CAST003",
                "MUST",
                _relative(source, project_root),
                "governed translation unit is missing from the compilation database",
                True,
            )
        )
    if missing_sources:
        return evidence

    target_triple = str(ast.get("target_triple"))
    all_cursors_with_ancestors: list[tuple[Any, tuple[Any, ...]]] = []
    all_cursors: list[Any] = []
    retained_translation_units: list[Any] = []
    # Includes are collected through get_includes(); materializing every macro and
    # preprocessing cursor multiplies Arduino/ESP-IDF parse cost without adding
    # type, state, dependency, or function-body evidence.
    options = 0
    ordered_sources = sorted(governed_sources)
    configured_workers = ast.get("worker_count")
    try:
        worker_count = (
            int(configured_workers)
            if configured_workers is not None
            else 1
        )
    except (TypeError, ValueError):
        worker_count = 0
    if worker_count < 1 or worker_count > 16:
        diagnostics.append(
            Diagnostic(
                "CAST002",
                "MUST",
                "c_analyzer.ast.worker_count",
                "worker_count must be an integer from 1 through 16",
                True,
            )
        )
        return evidence
    evidence.worker_count = min(worker_count, len(ordered_sources))
    source_positions = {
        source: index + 1 for index, source in enumerate(ordered_sources)
    }

    def parse_source(source: Path) -> dict[str, Any]:
        started = time.perf_counter()
        timing: dict[str, Any] = {
            "source": _relative(source, project_root),
            "status": "started",
        }
        if os.environ.get("GOVERNANCE_PROGRESS") == "1":
            print(
                f"AST start {source_positions[source]}/{len(ordered_sources)} "
                f"{timing['source']}",
                file=sys.stderr,
                flush=True,
            )
        entry = entries_by_source[source]
        arguments = _parse_arguments(entry, target_triple)
        parse_started = time.perf_counter()
        local_diagnostics: list[Diagnostic] = []
        try:
            translation_unit = cindex.Index.create().parse(
                str(source), args=arguments, options=options
            )
        except Exception as exc:  # libclang raises binding-specific exceptions
            timing["status"] = "parse-failed"
            timing["parse_seconds"] = round(time.perf_counter() - parse_started, 6)
            timing["total_seconds"] = round(time.perf_counter() - started, 6)
            local_diagnostics.append(
                Diagnostic(
                    "CAST003",
                    "MUST",
                    _relative(source, project_root),
                    f"libclang could not parse translation unit: {exc}",
                    True,
                )
            )
            if os.environ.get("GOVERNANCE_PROGRESS") == "1":
                print(
                    f"AST fail {source_positions[source]}/{len(ordered_sources)} "
                    f"{timing['source']} parse-failed",
                    file=sys.stderr,
                    flush=True,
                )
            return {
                "timing": timing,
                "diagnostics": local_diagnostics,
                "covered_files": set(),
                "includes": [],
                "walked": [],
                "translation_unit": None,
            }
        timing["parse_seconds"] = round(time.perf_counter() - parse_started, 6)
        errors = [
            item
            for item in translation_unit.diagnostics
            if item.severity >= cindex.Diagnostic.Error
        ]
        if errors:
            timing["status"] = "diagnostic-failed"
            timing["total_seconds"] = round(time.perf_counter() - started, 6)
            for item in errors:
                location = item.location
                location_path = (
                    _relative(Path(str(location.file)), project_root)
                    if location.file and _inside(Path(str(location.file)), project_root)
                    else _relative(source, project_root)
                )
                local_diagnostics.append(
                    Diagnostic(
                        "CAST003",
                        "MUST",
                        f"{location_path}:{location.line}",
                        str(item.spelling),
                        True,
                    )
                )
            if os.environ.get("GOVERNANCE_PROGRESS") == "1":
                print(
                    f"AST fail {source_positions[source]}/{len(ordered_sources)} "
                    f"{timing['source']} diagnostic-failed",
                    file=sys.stderr,
                    flush=True,
                )
            return {
                "timing": timing,
                "diagnostics": local_diagnostics,
                "covered_files": set(),
                "includes": [],
                "walked": [],
                "translation_unit": translation_unit,
            }
        includes_started = time.perf_counter()
        covered_files = {source}
        include_edges: list[tuple[Path, Path, int]] = []
        for inclusion in translation_unit.get_includes():
            included = Path(str(inclusion.include)).resolve()
            if _inside(included, project_root):
                covered_files.add(included)
                including = (
                    Path(str(inclusion.source)).resolve()
                    if inclusion.source
                    else source
                )
                include_edges.append(
                    (including, included, int(inclusion.location.line))
                )
        timing["includes_seconds"] = round(
            time.perf_counter() - includes_started, 6
        )
        walk_started = time.perf_counter()
        walked = list(_walk(translation_unit.cursor, project_root))
        timing["walk_seconds"] = round(time.perf_counter() - walk_started, 6)
        timing["project_cursors"] = len(walked)
        for cursor, _ in walked:
            path = _cursor_path(cursor)
            if path is not None and _inside(path, project_root):
                covered_files.add(path)
        timing["status"] = "parsed"
        timing["total_seconds"] = round(time.perf_counter() - started, 6)
        if os.environ.get("GOVERNANCE_PROGRESS") == "1":
            print(
                f"AST done {source_positions[source]}/{len(ordered_sources)} "
                f"{timing['source']} {timing['total_seconds']:.3f}s",
                file=sys.stderr,
                flush=True,
            )
        return {
            "timing": timing,
            "diagnostics": local_diagnostics,
            "covered_files": covered_files,
            "includes": include_edges,
            "walked": walked,
            "translation_unit": translation_unit,
        }

    with ThreadPoolExecutor(max_workers=evidence.worker_count) as executor:
        results = list(executor.map(parse_source, ordered_sources))
    parse_failed = False
    for result in results:
        evidence.translation_units.append(result["timing"])
        diagnostics.extend(result["diagnostics"])
        evidence.covered_files.update(result["covered_files"])
        evidence.includes.extend(result["includes"])
        walked = result["walked"]
        all_cursors_with_ancestors.extend(walked)
        all_cursors.extend(cursor for cursor, _ in walked)
        if result["translation_unit"] is not None:
            retained_translation_units.append(result["translation_unit"])
        if result["timing"]["status"] != "parsed":
            parse_failed = True
    if parse_failed:
        return evidence
    missing_headers = sorted(governed_headers.difference(evidence.covered_files))
    for header in missing_headers:
        diagnostics.append(
            Diagnostic(
                "CAST003",
                "MUST",
                _relative(header, project_root),
                "governed header is not covered by any parsed translation unit",
                True,
            )
        )
    if missing_headers:
        return evidence

    declarations, usr_to_key = _type_declarations(
        all_cursors, project_root, cindex
    )
    _catalog_type_checks(manifest, declarations, project_root, diagnostics)
    _type_dependency_checks(
        all_cursors,
        usr_to_key,
        manifest,
        project_root,
        roots,
        diagnostics,
        cindex,
    )
    _state_checks(
        all_cursors_with_ancestors,
        manifest,
        project_root,
        roots,
        diagnostics,
        cindex,
        evidence,
    )
    evidence.mode = "libclang-ast"
    return evidence
