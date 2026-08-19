"""Fail-closed TypeScript/TSX compiler-API source conformance analyzer."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from source_sets import classify_path


SUPPORTED_SUFFIXES = {".ts", ".tsx"}


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


def _owner_for(relative: str, modules: list[dict[str, Any]]) -> tuple[str | None, list[str]]:
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


def _compiler_result(project_root: Path, files: list[str]) -> tuple[dict[str, Any] | None, str | None]:
    node = shutil.which("node")
    compiler = project_root / "frontend" / "node_modules" / "typescript"
    bridge = Path(__file__).with_name("typescript_ast_bridge.cjs")
    if node is None:
        return None, "Node.js is required for governed TypeScript source"
    if not (compiler / "lib" / "typescript.js").is_file():
        return None, "frontend/node_modules/typescript compiler API is required"
    if not bridge.is_file():
        return None, "maintained TypeScript compiler-API bridge is missing"
    request = json.dumps({"project_root": str(project_root), "files": files})
    try:
        process = subprocess.run(
            [node, str(bridge), str(compiler)],
            input=request,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, f"cannot execute TypeScript compiler API: {error}"
    if process.returncode != 0:
        message = process.stderr.strip().splitlines()[-1] if process.stderr.strip() else "unknown compiler bridge failure"
        return None, f"TypeScript compiler API failed: {message}"
    try:
        result = json.loads(process.stdout)
    except json.JSONDecodeError:
        return None, "TypeScript compiler API returned malformed evidence"
    if not isinstance(result, dict) or not isinstance(result.get("files"), list):
        return None, "TypeScript compiler API returned incomplete evidence"
    return result, None


def analyze_typescript(
    manifest: dict[str, Any], project_root: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    modules = [item for item in manifest.get("modules", []) if isinstance(item, dict)]
    files: dict[str, Path] = {}
    owners: dict[str, str] = {}
    for module in modules:
        for path in _module_files(project_root, module):
            if path.suffix.casefold() not in SUPPORTED_SUFFIXES:
                continue
            relative = path.relative_to(project_root).as_posix()
            classification, _ = classify_path(manifest, relative)
            if classification == "production":
                files[relative] = path
    if not files:
        return diagnostics, {"mode": "not-applicable", "analyzed_files": [], "type_count": 0}

    governed_files: list[str] = []
    for relative in sorted(files):
        owner, candidates = _owner_for(relative, modules)
        if owner is None:
            diagnostics.append(
                _diagnostic(
                    "TSOWN001",
                    relative,
                    "TypeScript source must map to exactly one most-specific module"
                    + (f"; candidates: {', '.join(candidates)}" if candidates else ""),
                    configuration=True,
                )
            )
        else:
            owners[relative] = owner
            governed_files.append(relative)

    result, failure = _compiler_result(project_root, governed_files)
    if failure is not None:
        diagnostics.append(_diagnostic("TSAST001", "typescript_analyzer", failure, configuration=True))
        return diagnostics, {"mode": "not-run", "analyzed_files": [], "type_count": 0}
    assert result is not None

    catalog = {
        (str(item.get("declaration", {}).get("path")), str(item.get("declaration", {}).get("symbol"))): item
        for item in manifest.get("types", [])
        if isinstance(item, dict) and item.get("language") == "typescript"
    }
    discovered: set[tuple[str, str]] = set()
    analyzed_files: list[str] = []
    failed_files: set[str] = set()
    symbols: dict[str, set[str]] = {}
    for raw_file in result["files"]:
        if not isinstance(raw_file, dict):
            diagnostics.append(_diagnostic("TSAST001", "typescript_analyzer", "malformed file evidence", configuration=True))
            continue
        relative = str(raw_file.get("path", ""))
        errors = raw_file.get("errors", [])
        if not isinstance(errors, list):
            errors = ["malformed parse diagnostics"]
        if errors:
            failed_files.add(relative)
            diagnostics.extend(
                _diagnostic("TSAST002", relative, f"cannot form TypeScript AST: {error}", configuration=True)
                for error in errors
            )
            continue
        analyzed_files.append(relative)
        symbols[relative] = {str(value) for value in raw_file.get("symbols", [])}
        for declaration in raw_file.get("types", []):
            if not isinstance(declaration, dict) or not declaration.get("symbol"):
                diagnostics.append(_diagnostic("TSAST001", relative, "malformed type evidence", configuration=True))
                continue
            symbol = str(declaration["symbol"])
            key = (relative, symbol)
            discovered.add(key)
            item = catalog.get(key)
            if item is None:
                diagnostics.append(_diagnostic("TSTYPE001", f"{relative}:{symbol}", "uncataloged production TypeScript type"))
            elif str(item.get("owner")) != owners.get(relative):
                diagnostics.append(_diagnostic("TSTYPE003", f"{relative}:{symbol}", "TypeScript Type Catalog owner does not match source owner"))

    for key in sorted(set(catalog).difference(discovered)):
        if key[0] not in failed_files:
            diagnostics.append(_diagnostic("TSTYPE002", f"{key[0]}:{key[1]}", "stale TypeScript Type Catalog entry"))

    for module in modules:
        for item in module.get("public_symbols", []):
            if not isinstance(item, dict):
                continue
            relative = str(item.get("path", ""))
            if Path(relative).suffix.casefold() not in SUPPORTED_SUFFIXES or relative in failed_files:
                continue
            symbol = str(item.get("symbol", ""))
            if symbol not in symbols.get(relative, set()):
                diagnostics.append(
                    _diagnostic("TSSYM001", f"{relative}:{symbol}", "declared public symbol is missing from TypeScript AST")
                )

    return diagnostics, {
        "mode": "typescript-compiler-api",
        "analyzed_files": sorted(analyzed_files),
        "type_count": len(discovered),
        "typescript_version": str(result.get("version", "unknown")),
    }
