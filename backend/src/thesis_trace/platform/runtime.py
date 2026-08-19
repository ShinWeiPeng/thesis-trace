from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


class SecretProvider(Protocol):
    """Resolve a secret only at the point of use."""

    def __call__(self) -> str: ...


class FileSecretProvider:
    """A non-secret process-scoped reference to a runtime-owned secret file."""

    __slots__ = ("_path",)

    def __init__(self, path: Path) -> None:
        self._path = path

    def __call__(self) -> str:
        value = self._path.read_text(encoding="utf-8").strip()
        if not value:
            raise RuntimeError("required secret file is empty")
        return value

    def __repr__(self) -> str:
        return f"{type(self).__name__}(file_reference=<redacted>)"


def required_setting(name: str) -> str:
    file_name = os.environ.get(f"{name}_FILE")
    value = Path(file_name).read_text(encoding="utf-8").strip() if file_name else os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"required setting is missing: {name}")
    return value


def required_secret_provider(name: str) -> SecretProvider:
    file_name = os.environ.get(f"{name}_FILE", "").strip()
    if not file_name:
        raise RuntimeError(f"required secret file reference is missing: {name}_FILE")
    return FileSecretProvider(Path(file_name))
