"""Fail-closed Python AST source-conformance analyzer."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from source_sets import classify_path

SUPPORTED_CODE_SUFFIXES = {".py"}
KNOWN_CODE_SUFFIXES = {".py", ".c", ".h", ".cc", ".cpp", ".hh", ".hpp", ".rs", ".go", ".js", ".ts", ".java"}


def _diagnostic(
    rule_id: str,
    location: str,
    message: str,
    *,
    configuration: bool = False,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "severity": "MUST",
        "location": location,
        "message": message,
        "configuration": configuration,
        "disposition": "active",
    }


def _module_files(project_root: Path, module: dict[str, Any]) -> list[Path]:
    files: list[Path] = []
    for raw in module.get("paths", []):
        path = project_root / str(raw)
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(item for item in path.rglob("*") if item.is_file())
    return files


def _owner_for(
    relative: str, modules: list[dict[str, Any]]
) -> tuple[str | None, list[str]]:
    matches: list[tuple[int, str]] = []
    for module in modules:
        for raw in module.get("paths", []):
            prefix = str(raw).replace("\\", "/").rstrip("/")
            if relative == prefix or relative.startswith(prefix + "/"):
                matches.append((len(prefix), str(module.get("id"))))
    if not matches:
        return None, []
    longest = max(length for length, _ in matches)
    owners = sorted({owner for length, owner in matches if length == longest})
    return (owners[0] if len(owners) == 1 else None), owners


def _assignment_names(node: ast.AST) -> list[str]:
    targets: list[ast.AST] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
    result: list[str] = []
    for target in targets:
        if isinstance(target, ast.Name):
            result.append(target.id)
    return result


def _is_runtime_state(node: ast.AST, name: str) -> bool:
    if name.isupper():
        return False
    value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
    return isinstance(value, (ast.Dict, ast.List, ast.Set, ast.Call))


def analyze_python(
    manifest: dict[str, Any], project_root: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    config = manifest.get("python_analyzer")
    modules = [item for item in manifest.get("modules", []) if isinstance(item, dict)]
    files: dict[str, Path] = {}
    unsupported: set[str] = set()
    for module in modules:
        for path in _module_files(project_root, module):
            relative = path.relative_to(project_root).as_posix()
            classification, _ = classify_path(manifest, relative)
            if classification != "production":
                continue
            if path.suffix in SUPPORTED_CODE_SUFFIXES:
                files[relative] = path
            elif path.suffix in KNOWN_CODE_SUFFIXES and path.suffix not in {
                ".c",
                ".h",
                ".cc",
                ".cpp",
                ".hh",
                ".hpp",
            }:
                unsupported.add(relative)
    for relative in sorted(unsupported):
        diagnostics.append(
            _diagnostic(
                "SRCAN001",
                relative,
                "production code language has no installed analyzer",
                configuration=True,
            )
        )
    if not files:
        if isinstance(config, dict) and config.get("status") == "required":
            diagnostics.append(
                _diagnostic(
                    "PYAST001",
                    "python_analyzer",
                    "Python analysis is required but no governed Python source was found",
                    configuration=True,
                )
            )
        return diagnostics, {
            "mode": "not-run" if unsupported else "not-applicable",
            "analyzed_files": [],
        }
    if not isinstance(config, dict) or config.get("status") != "required":
        diagnostics.append(
            _diagnostic(
                "PYAST001",
                "python_analyzer",
                "governed Python source requires python_analyzer.status: required",
                configuration=True,
            )
        )
        return diagnostics, {"mode": "not-run", "analyzed_files": []}
    catalog = {
        (str(item.get("declaration", {}).get("path")), str(item.get("declaration", {}).get("symbol"))): item
        for item in manifest.get("types", [])
        if isinstance(item, dict) and item.get("language") == "python"
    }
    states = {
        (str(item.get("declaration", {}).get("path")), str(item.get("declaration", {}).get("symbol"))): item
        for item in manifest.get("state_objects", [])
        if isinstance(item, dict) and item.get("language") == "python"
    }
    discovered_types: set[tuple[str, str]] = set()
    discovered_states: set[tuple[str, str]] = set()
    trees: dict[str, ast.Module] = {}
    symbols: dict[str, set[str]] = {}
    owners: dict[str, str] = {}
    for relative, path in sorted(files.items()):
        owner, candidates = _owner_for(relative, modules)
        if owner is None:
            diagnostics.append(
                _diagnostic(
                    "PYOWN001",
                    relative,
                    "Python source must map to exactly one most-specific module"
                    + (f"; candidates: {', '.join(candidates)}" if candidates else ""),
                    configuration=True,
                )
            )
            continue
        owners[relative] = owner
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, UnicodeError, SyntaxError) as exc:
            diagnostics.append(
                _diagnostic("PYAST002", relative, f"cannot form Python AST: {exc}", configuration=True)
            )
            continue
        trees[relative] = tree
        symbols[relative] = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                key = (relative, node.name)
                discovered_types.add(key)
                item = catalog.get(key)
                if item is None:
                    diagnostics.append(
                        _diagnostic("PYTYPE001", f"{relative}:{node.name}", "uncataloged production Python type")
                    )
                elif str(item.get("owner")) != owner:
                    diagnostics.append(
                        _diagnostic("PYTYPE003", f"{relative}:{node.name}", "Python type catalog owner does not match source owner")
                    )
            for name in _assignment_names(node):
                if _is_runtime_state(node, name):
                    key = (relative, name)
                    discovered_states.add(key)
                    item = states.get(key)
                    if item is None:
                        diagnostics.append(
                            _diagnostic("PYSTATE001", f"{relative}:{name}", "uncataloged mutable module runtime state")
                        )
                    elif str(item.get("owner")) != owner:
                        diagnostics.append(
                            _diagnostic("PYSTATE002", f"{relative}:{name}", "Python state owner does not match source owner")
                        )
    for key in sorted(set(catalog).difference(discovered_types)):
        diagnostics.append(
            _diagnostic("PYTYPE002", f"{key[0]}:{key[1]}", "stale Python Type Catalog entry")
        )
    for key in sorted(set(states).difference(discovered_states)):
        diagnostics.append(
            _diagnostic("PYSTATE003", f"{key[0]}:{key[1]}", "stale Python State Catalog entry")
        )

    module_index = {str(item.get("id")): item for item in modules}
    file_owner_by_stem = {
        Path(relative).stem: owner for relative, owner in owners.items()
    }
    for relative, tree in trees.items():
        owner = owners[relative]
        allowed = set(module_index.get(owner, {}).get("depends_on", []))
        for node in tree.body:
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".", 1)[0]]
            for name in names:
                target = file_owner_by_stem.get(name)
                if target and target != owner and target not in allowed:
                    diagnostics.append(
                        _diagnostic(
                            "PYDEP001",
                            f"{relative}:{node.lineno}",
                            f"undeclared Python dependency {owner}->{target}",
                        )
                    )

    for module in modules:
        for kind in ("entrypoints", "public_symbols"):
            for item in module.get(kind, []):
                relative = str(item.get("path"))
                symbol = str(item.get("symbol"))
                if relative.endswith(".py") and symbol not in symbols.get(relative, set()):
                    diagnostics.append(
                        _diagnostic(
                            "PYSYM001",
                            f"{relative}:{symbol}",
                            f"declared {kind[:-1]} symbol is missing from Python AST",
                        )
                    )
    release_roots = 0
    for root in manifest.get("composition_roots", []):
        if not isinstance(root, dict):
            continue
        if root.get("kind") == "release":
            release_roots += 1
        relative = str(root.get("path"))
        symbol = str(root.get("symbol"))
        if relative.endswith(".py") and symbol not in symbols.get(relative, set()):
            diagnostics.append(
                _diagnostic(
                    "PYCMP001",
                    f"{relative}:{symbol}",
                    "composition-root symbol is missing from Python AST",
                )
            )
    if release_roots != 1:
        diagnostics.append(
            _diagnostic(
                "PYCMP002",
                "composition_roots",
                "exactly one release composition root is required",
                configuration=True,
            )
        )
    return diagnostics, {
        "mode": "python-ast",
        "analyzed_files": sorted(trees),
        "type_count": len(discovered_types),
        "state_count": len(discovered_states),
    }
