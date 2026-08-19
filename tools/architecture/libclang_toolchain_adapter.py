#!/usr/bin/env python3
"""Official Espressif libclang installer and offline verifier."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform as host_platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from libclang_toolchain_contract import (
    LibclangToolchainEvidence,
    ToolchainProviderError,
)


LOCK_SCHEMA = "governed-libclang-toolchain-lock/2"
RECEIPT_SCHEMA = "governed-libclang-toolchain-receipt/1"
RECEIPT_NAME = "receipt.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required(mapping: dict[str, Any], key: str, location: str) -> Any:
    value = mapping.get(key)
    if value in (None, ""):
        raise ToolchainProviderError(
            "CAST002", f"{location}.{key}", "required toolchain lock field is missing"
        )
    return value


def _platform_key() -> str:
    machine = host_platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        architecture = "x86_64"
    else:
        raise ToolchainProviderError(
            "CAST002",
            "toolchain.platform",
            f"unsupported host architecture: {machine or 'unknown'}",
        )
    if sys.platform == "win32":
        return f"windows-{architecture}"
    if sys.platform.startswith("linux"):
        return f"linux-{architecture}"
    raise ToolchainProviderError(
        "CAST002", "toolchain.platform", f"unsupported host operating system: {sys.platform}"
    )


def _cache_root(provider: dict[str, Any]) -> Path:
    override = os.environ.get("GOVERNED_TOOLCHAIN_CACHE")
    if override:
        root = Path(override)
        if not root.is_absolute():
            raise ToolchainProviderError(
                "CAST002",
                "GOVERNED_TOOLCHAIN_CACHE",
                "cache override must be an absolute path",
            )
        return root / "espressif" / "esp-clang-libs" / str(provider["version"])
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise ToolchainProviderError(
                "CAST002", "LOCALAPPDATA", "LOCALAPPDATA is required on Windows"
            )
        return (
            Path(local)
            / "CodexToolchains"
            / "espressif"
            / "esp-clang-libs"
            / str(provider["version"])
        )
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return (
        base
        / "codex-toolchains"
        / "espressif"
        / "esp-clang-libs"
        / str(provider["version"])
    )


def _load_lock(lock_path: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    try:
        document = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ToolchainProviderError("CAST002", str(lock_path), str(exc)) from exc
    if not isinstance(document, dict) or document.get("schema") != LOCK_SCHEMA:
        raise ToolchainProviderError(
            "CAST002", str(lock_path), f"expected lock schema {LOCK_SCHEMA}"
        )
    provider = document.get("libclang_provider")
    if not isinstance(provider, dict):
        raise ToolchainProviderError(
            "CAST002", "libclang_provider", "provider mapping is required"
        )
    for key in ("id", "version", "binding", "target_triple", "artifacts"):
        _required(provider, key, "libclang_provider")
    if provider["id"] != "espressif-esp-clang-libs":
        raise ToolchainProviderError(
            "CAST002", "libclang_provider.id", "unsupported libclang provider"
        )
    binding = provider["binding"]
    if not isinstance(binding, dict) or binding.get("package") != "clang":
        raise ToolchainProviderError(
            "CAST002", "libclang_provider.binding", "binding package must be clang"
        )
    _required(binding, "version", "libclang_provider.binding")
    platform_key = _platform_key()
    artifacts = provider["artifacts"]
    artifact = artifacts.get(platform_key) if isinstance(artifacts, dict) else None
    if not isinstance(artifact, dict):
        raise ToolchainProviderError(
            "CAST002",
            "libclang_provider.artifacts",
            f"no official artifact is locked for {platform_key}",
        )
    for key in ("url", "archive_sha256", "library_path", "library_sha256"):
        value = str(_required(artifact, key, f"artifacts.{platform_key}"))
        if key.endswith("sha256") and (
            len(value) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in value)
        ):
            raise ToolchainProviderError(
                "CAST002", f"artifacts.{platform_key}.{key}", "invalid SHA-256"
            )
    library_path = PurePosixPath(str(artifact["library_path"]))
    if library_path.is_absolute() or ".." in library_path.parts:
        raise ToolchainProviderError(
            "CAST002",
            f"artifacts.{platform_key}.library_path",
            "library path must be a safe archive-relative path",
        )
    return provider, artifact, platform_key


def _safe_extract(archive: Path, destination: Path) -> None:
    try:
        with tarfile.open(archive, mode="r:xz") as bundle:
            members = bundle.getmembers()
            destination_root = destination.resolve()
            for member in members:
                if "\\" in member.name:
                    raise ToolchainProviderError(
                        "CAST002", member.name, "unsafe archive path separator"
                    )
                relative = PurePosixPath(member.name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ToolchainProviderError(
                        "CAST002", member.name, "unsafe archive path"
                    )
                target = destination.joinpath(*relative.parts)
                try:
                    target.resolve().relative_to(destination_root)
                except ValueError as exc:
                    raise ToolchainProviderError(
                        "CAST002", member.name, "archive path escapes destination"
                    ) from exc
                if member.issym() or member.islnk():
                    if not member.linkname or "\\" in member.linkname:
                        raise ToolchainProviderError(
                            "CAST002", member.name, "unsafe archive link target"
                        )
                    link_target = PurePosixPath(member.linkname)
                    if link_target.is_absolute() or ".." in link_target.parts:
                        raise ToolchainProviderError(
                            "CAST002", member.name, "unsafe archive link target"
                        )
                    continue
                if not (member.isdir() or member.isfile()):
                    raise ToolchainProviderError(
                        "CAST002", member.name, "special archive entry is forbidden"
                    )
            for member in members:
                if member.issym() or member.islnk():
                    continue
                target = destination.joinpath(*PurePosixPath(member.name).parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise ToolchainProviderError(
                        "CAST002", member.name, "archive member cannot be read"
                    )
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except (OSError, tarfile.TarError) as exc:
        raise ToolchainProviderError("CAST002", str(archive), str(exc)) from exc


def _binding_version(expected: str) -> str:
    try:
        actual = importlib.metadata.version("clang")
    except importlib.metadata.PackageNotFoundError as exc:
        raise ToolchainProviderError(
            "CAST001", "python-binding", f"clang=={expected} is required"
        ) from exc
    if actual != expected:
        raise ToolchainProviderError(
            "CAST001",
            "python-binding",
            f"clang binding version mismatch: expected {expected}, got {actual}",
        )
    return actual


def _clang_version(cindex: Any) -> str:
    function = cindex.conf.lib.clang_getClangVersion
    function.restype = cindex._CXString
    return str(cindex._CXString.from_result(function()))


def _probe(cindex: Any, target: str) -> str:
    index = cindex.Index.create()
    try:
        native = index.parse(
            "provider-native-probe.c",
            args=["-x", "c", "-std=c11"],
            unsaved_files=[
                ("provider-native-probe.c", "int provider_native_probe(void) { return 0; }\n")
            ],
        )
    except Exception as exc:
        raise ToolchainProviderError(
            "CAST001", "native-host", f"native AST capability probe failed: {exc}"
        ) from exc
    native_errors = [
        str(item.spelling)
        for item in native.diagnostics
        if item.severity >= cindex.Diagnostic.Error
    ]
    if native_errors:
        raise ToolchainProviderError(
            "CAST001",
            "native-host",
            f"native AST capability probe failed: {'; '.join(native_errors)}",
        )
    fixtures = (
        ("provider-probe.c", "int provider_probe(void) { return 0; }\n"),
        (
            "provider-inline-asm.c",
            "void provider_probe_asm(void) { __asm__ volatile(\"memw\" ::: \"memory\"); }\n",
        ),
    )
    for filename, source in fixtures:
        try:
            unit = index.parse(
                filename,
                args=[f"--target={target}", "-x", "c", "-std=c11"],
                unsaved_files=[(filename, source)],
            )
        except Exception as exc:
            raise ToolchainProviderError(
                "CAST001", target, f"Xtensa capability probe failed: {exc}"
            ) from exc
        errors = [
            str(item.spelling)
            for item in unit.diagnostics
            if item.severity >= cindex.Diagnostic.Error
        ]
        if errors:
            raise ToolchainProviderError(
                "CAST001",
                target,
                f"Xtensa capability probe failed for {filename}: {'; '.join(errors)}",
            )
    return _clang_version(cindex)


class EspressifLibclangToolchainAdapter:
    def verify(
        self, lock_path: Path, *, bind_library: bool = True
    ) -> LibclangToolchainEvidence:
        provider, artifact, platform_key = _load_lock(lock_path.resolve())
        cache = _cache_root(provider)
        receipt_path = cache / RECEIPT_NAME
        library_path = cache.joinpath(
            *PurePosixPath(str(artifact["library_path"])).parts
        )
        if not receipt_path.is_file() or not library_path.is_file():
            raise ToolchainProviderError(
                "CAST002",
                str(cache),
                "toolchain cache is absent or incomplete; run toolchain install",
            )
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolchainProviderError("CAST002", str(receipt_path), str(exc)) from exc
        expected_receipt = {
            "schema": RECEIPT_SCHEMA,
            "provider": str(provider["id"]),
            "provider_version": str(provider["version"]),
            "binding_version": str(provider["binding"]["version"]),
            "platform": platform_key,
            "archive_sha256": str(artifact["archive_sha256"]).lower(),
            "library_path": str(PurePosixPath(str(artifact["library_path"]))),
            "library_sha256": str(artifact["library_sha256"]).lower(),
            "target_triple": str(provider["target_triple"]),
        }
        for key, value in expected_receipt.items():
            if receipt.get(key) != value:
                raise ToolchainProviderError(
                    "CAST002", f"{receipt_path}:{key}", "receipt does not match the lock"
                )
        actual_library_hash = _sha256(library_path)
        if actual_library_hash != expected_receipt["library_sha256"]:
            raise ToolchainProviderError(
                "CAST001", str(library_path), "libclang shared-library hash mismatch"
            )
        binding_version = _binding_version(expected_receipt["binding_version"])
        clang_version = str(receipt.get("clang_version", ""))
        if bind_library:
            try:
                from clang import cindex
            except (ImportError, OSError) as exc:
                raise ToolchainProviderError("CAST001", "python-binding", str(exc)) from exc
            try:
                cindex.Config.set_library_file(str(library_path))
            except Exception as exc:
                raise ToolchainProviderError(
                    "CAST001", str(library_path), f"cannot bind libclang: {exc}"
                ) from exc
            clang_version = _probe(cindex, expected_receipt["target_triple"])
            if "20.1.1" not in clang_version:
                raise ToolchainProviderError(
                    "CAST001",
                    str(library_path),
                    f"unexpected native clang version: {clang_version}",
                )
            if receipt.get("clang_version") != clang_version:
                raise ToolchainProviderError(
                    "CAST002",
                    f"{receipt_path}:clang_version",
                    "receipt native clang version does not match the loaded library",
                )
        return LibclangToolchainEvidence(
            provider=expected_receipt["provider"],
            provider_version=expected_receipt["provider_version"],
            binding_version=binding_version,
            platform=platform_key,
            library_path=library_path.resolve(),
            archive_sha256=expected_receipt["archive_sha256"],
            library_sha256=actual_library_hash,
            target_triple=expected_receipt["target_triple"],
            clang_version=clang_version,
            receipt_path=receipt_path.resolve(),
        )

    def install(self, lock_path: Path) -> LibclangToolchainEvidence:
        provider, artifact, platform_key = _load_lock(lock_path.resolve())
        cache = _cache_root(provider)
        if cache.exists():
            return self.verify(lock_path, bind_library=False)
        cache.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f".{cache.name}-", dir=str(cache.parent)
        ) as temporary:
            workspace = Path(temporary)
            archive = workspace / "provider.tar.xz"
            try:
                urllib.request.urlretrieve(str(artifact["url"]), archive)
            except (OSError, ValueError) as exc:
                raise ToolchainProviderError(
                    "CAST001", str(artifact["url"]), f"provider download failed: {exc}"
                ) from exc
            archive_hash = _sha256(archive)
            if archive_hash != str(artifact["archive_sha256"]).lower():
                raise ToolchainProviderError(
                    "CAST001", str(archive), "provider archive hash mismatch"
                )
            payload = workspace / "payload"
            payload.mkdir()
            _safe_extract(archive, payload)
            library = payload.joinpath(
                *PurePosixPath(str(artifact["library_path"])).parts
            )
            if not library.is_file():
                raise ToolchainProviderError(
                    "CAST002", str(library), "locked library is absent from the archive"
                )
            library_hash = _sha256(library)
            if library_hash != str(artifact["library_sha256"]).lower():
                raise ToolchainProviderError(
                    "CAST001", str(library), "extracted library hash mismatch"
                )
            binding_version = _binding_version(str(provider["binding"]["version"]))
            try:
                from clang import cindex

                cindex.Config.set_library_file(str(library))
                clang_version = _probe(cindex, str(provider["target_triple"]))
            except ToolchainProviderError:
                raise
            except Exception as exc:
                raise ToolchainProviderError(
                    "CAST001", str(library), f"cannot validate libclang: {exc}"
                ) from exc
            if "20.1.1" not in clang_version:
                raise ToolchainProviderError(
                    "CAST001", str(library), f"unexpected native clang version: {clang_version}"
                )
            receipt = {
                "schema": RECEIPT_SCHEMA,
                "provider": str(provider["id"]),
                "provider_version": str(provider["version"]),
                "binding_version": binding_version,
                "platform": platform_key,
                "archive_sha256": archive_hash,
                "library_path": str(PurePosixPath(str(artifact["library_path"]))),
                "library_sha256": library_hash,
                "target_triple": str(provider["target_triple"]),
                "clang_version": clang_version,
                "installed_at": datetime.now(timezone.utc).isoformat(),
            }
            (payload / RECEIPT_NAME).write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            try:
                payload.replace(cache)
            except OSError as exc:
                raise ToolchainProviderError(
                    "CAST002", str(cache), f"atomic cache installation failed: {exc}"
                ) from exc
        return self.verify(lock_path, bind_library=False)
