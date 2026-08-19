#!/usr/bin/env python3
"""Demand-owned contract for a pinned native libclang provider."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class LibclangToolchainEvidence:
    provider: str
    provider_version: str
    binding_version: str
    platform: str
    library_path: Path
    archive_sha256: str
    library_sha256: str
    target_triple: str
    clang_version: str
    receipt_path: Path

    def to_dict(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}


class ToolchainProviderError(RuntimeError):
    def __init__(self, rule_id: str, location: str, message: str) -> None:
        super().__init__(message)
        self.rule_id = rule_id
        self.location = location
        self.message = message


class LibclangToolchainPort(Protocol):
    def install(self, lock_path: Path) -> LibclangToolchainEvidence:
        """Install an absent immutable cache and return verified evidence."""

    def verify(
        self, lock_path: Path, *, bind_library: bool = True
    ) -> LibclangToolchainEvidence:
        """Verify an existing cache without network access."""
