#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd
import stat
import sys
from typing import Any


class SecretFileViolation(RuntimeError):
    pass


_CONSUMER_FILE_AUTHORITY = {
    "postgres": (70, "0440"),
    "api": (65532, "0440"),
    "collector": (65532, "0440"),
    "migration": (65532, "0440"),
    "cloudflared": (65532, "0440"),
    "origin-gateway": (0, "0400"),
}


def _octal_mode(value: Any, field: str) -> int:
    if not isinstance(value, str) or len(value) != 4 or not value.isdigit():
        raise SecretFileViolation(f"{field} must be a four-digit octal string")
    try:
        return int(value, 8)
    except ValueError:
        raise SecretFileViolation(f"{field} must be a four-digit octal string") from None


def validate_policy(
    policy: dict[str, Any],
    *,
    expected_consumers: dict[str, str] | None = None,
) -> None:
    if set(policy) != {
        "contract_version", "root_owner_uid", "root_directory_mode", "lifecycle_inventory", "files"
    }:
        raise SecretFileViolation("secret file policy contains unknown authority")
    if policy.get("contract_version") != 1:
        raise SecretFileViolation("unsupported secret file policy version")
    if policy.get("root_owner_uid") != 0:
        raise SecretFileViolation("production secret root must be owned by uid 0")
    if policy.get("root_directory_mode") != "0711":
        raise SecretFileViolation("production secret root mode must be 0711")
    if policy.get("lifecycle_inventory") != {
        "owner_uid": 0,
        "group_gid": 0,
        "mode": "0400",
        "max_bytes": 65536,
    }:
        raise SecretFileViolation("lifecycle inventory must be root-only and bounded")
    files = policy.get("files")
    if not isinstance(files, dict) or not files:
        raise SecretFileViolation("production secret policy needs a non-empty file inventory")
    if expected_consumers is not None and set(files) != set(expected_consumers):
        raise SecretFileViolation("secret file policy inventory differs from the Compose contract")

    for name, definition in files.items():
        if not isinstance(name, str) or not name or "/" in name:
            raise SecretFileViolation("secret policy names must be simple path components")
        if not isinstance(definition, dict) or set(definition) != {
            "owner_uid", "group_gid", "mode", "consumer"
        }:
            raise SecretFileViolation(f"secret policy entry contains unknown authority: {name}")
        if definition.get("owner_uid") != 0:
            raise SecretFileViolation(f"secret must be root-owned: {name}")
        consumer = definition.get("consumer")
        if expected_consumers is not None and consumer != expected_consumers.get(name):
            raise SecretFileViolation(f"secret consumer mismatch: {name}")
        authority = _CONSUMER_FILE_AUTHORITY.get(consumer)
        if authority is None:
            raise SecretFileViolation(f"unknown secret consumer: {name}")
        expected_gid, expected_mode = authority
        if definition.get("group_gid") != expected_gid or definition.get("mode") != expected_mode:
            raise SecretFileViolation(f"secret group/mode differs from runtime authority: {name}")


def _utc_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SecretFileViolation(f"invalid UTC lifecycle timestamp: {field}")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise SecretFileViolation(f"invalid UTC lifecycle timestamp: {field}") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise SecretFileViolation(f"invalid UTC lifecycle timestamp: {field}")
    return parsed


def validate_lifecycle_inventory(
    inventory: dict[str, Any],
    policy: dict[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    if set(inventory) != {"contract_version", "secrets"} or inventory.get("contract_version") != 1:
        raise SecretFileViolation("invalid lifecycle inventory contract")
    records = inventory.get("secrets")
    files = policy.get("files")
    if not isinstance(records, dict) or not isinstance(files, dict) or set(records) != set(files):
        raise SecretFileViolation("lifecycle inventory differs from the secret policy")
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        raise SecretFileViolation("lifecycle validation clock must be timezone-aware")
    required_fields = {
        "owner_uid", "consumer", "created_at", "last_rotated_at", "expires_at",
        "revoked_at", "audit_reference",
    }
    for name, record in records.items():
        expected = files[name]
        if not isinstance(record, dict) or set(record) != required_fields:
            raise SecretFileViolation(f"lifecycle record contains missing or unknown fields: {name}")
        if record.get("owner_uid") != expected.get("owner_uid") or record.get("consumer") != expected.get("consumer"):
            raise SecretFileViolation(f"lifecycle authority mismatch: {name}")
        reference = record.get("audit_reference")
        if not isinstance(reference, str) or not reference.strip() or len(reference) > 128 or "\n" in reference:
            raise SecretFileViolation(f"invalid lifecycle audit reference: {name}")
        created_at = _utc_timestamp(record.get("created_at"), f"{name}.created_at")
        rotated_at = _utc_timestamp(record.get("last_rotated_at"), f"{name}.last_rotated_at")
        expires_at = _utc_timestamp(record.get("expires_at"), f"{name}.expires_at")
        if created_at > rotated_at or rotated_at > current_time or expires_at <= current_time:
            raise SecretFileViolation(f"secret lifecycle is stale or inconsistent: {name}")
        if record.get("revoked_at") is not None:
            _utc_timestamp(record.get("revoked_at"), f"{name}.revoked_at")
            raise SecretFileViolation(f"secret is revoked: {name}")


def validate_ordinary_user_groups(
    user_uid: int,
    group_gids: set[int],
    policy: dict[str, Any],
) -> None:
    if user_uid == 0:
        raise SecretFileViolation("ordinary deployment user must not be root")
    readable_service_groups = {
        definition["group_gid"]
        for definition in policy.get("files", {}).values()
        if _octal_mode(definition.get("mode"), "secret.mode") & 0o040
    }
    if group_gids & readable_service_groups:
        raise SecretFileViolation("ordinary deployment user belongs to a secret-readable service group")


def load_lifecycle_inventory(
    path: Path,
    policy: dict[str, Any],
    *,
    trusted_ancestor: Path = Path("/"),
    now: datetime | None = None,
) -> None:
    metadata_policy = policy.get("lifecycle_inventory")
    if not isinstance(metadata_policy, dict):
        raise SecretFileViolation("lifecycle inventory metadata policy is missing")
    owner_uid = metadata_policy.get("owner_uid")
    group_gid = metadata_policy.get("group_gid")
    expected_mode = _octal_mode(metadata_policy.get("mode"), "lifecycle_inventory.mode")
    max_bytes = metadata_policy.get("max_bytes")
    if not isinstance(owner_uid, int) or not isinstance(group_gid, int):
        raise SecretFileViolation("lifecycle inventory owner/group policy is invalid")
    if not isinstance(max_bytes, int) or max_bytes <= 0 or max_bytes > 65536:
        raise SecretFileViolation("lifecycle inventory size limit is invalid")

    path = Path(os.path.abspath(path))
    directory_descriptor = _open_directory_chain(path.parent, trusted_ancestor, owner_uid)
    file_descriptor: int | None = None
    try:
        file_descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_descriptor)
        metadata = os.fstat(file_descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SecretFileViolation("lifecycle inventory is not a regular file")
        if metadata.st_uid != owner_uid or metadata.st_gid != group_gid:
            raise SecretFileViolation("lifecycle inventory owner/group mismatch")
        if stat.S_IMODE(metadata.st_mode) != expected_mode:
            raise SecretFileViolation("lifecycle inventory mode mismatch")
        if metadata.st_size <= 0 or metadata.st_size > max_bytes:
            raise SecretFileViolation("lifecycle inventory is empty or oversized")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(file_descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != metadata.st_size or len(payload) > max_bytes:
            raise SecretFileViolation("lifecycle inventory changed or exceeded its bound")
        try:
            inventory = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SecretFileViolation("lifecycle inventory is not valid UTF-8 JSON") from None
        if not isinstance(inventory, dict):
            raise SecretFileViolation("lifecycle inventory root must be an object")
        validate_lifecycle_inventory(inventory, policy, now=now)
    except OSError:
        raise SecretFileViolation("lifecycle inventory is missing, inaccessible, or symlinked") from None
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        os.close(directory_descriptor)


def _open_directory_chain(root: Path, trusted_ancestor: Path, owner_uid: int) -> int:
    root = Path(os.path.abspath(root))
    trusted_ancestor = Path(os.path.abspath(trusted_ancestor))
    try:
        relative = root.relative_to(trusted_ancestor)
    except ValueError:
        raise SecretFileViolation("secret root must be below the trusted ancestor") from None

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(trusted_ancestor, flags)
    try:
        for component in relative.parts:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
            metadata = os.fstat(descriptor)
            if metadata.st_uid != owner_uid:
                raise SecretFileViolation(f"directory owner mismatch: {component}")
            if stat.S_IMODE(metadata.st_mode) & 0o022:
                raise SecretFileViolation(f"directory must not be group/world writable: {component}")
        return descriptor
    except OSError:
        os.close(descriptor)
        raise SecretFileViolation("secret directory chain is missing, inaccessible, or contains a symlink") from None
    except Exception:
        os.close(descriptor)
        raise


def validate_secret_tree(
    root: Path,
    policy: dict[str, Any],
    *,
    trusted_ancestor: Path = Path("/"),
) -> None:
    owner_uid = policy.get("root_owner_uid")
    if not isinstance(owner_uid, int):
        raise SecretFileViolation("root_owner_uid must be an integer")
    root_mode = _octal_mode(policy.get("root_directory_mode"), "root_directory_mode")
    files = policy.get("files")
    if not isinstance(files, dict) or not files:
        raise SecretFileViolation("files must be a non-empty object")

    descriptor = _open_directory_chain(root, trusted_ancestor, owner_uid)
    try:
        metadata = os.fstat(descriptor)
        if stat.S_IMODE(metadata.st_mode) != root_mode:
            raise SecretFileViolation("secret root directory mode mismatch")

        actual_names = set(os.listdir(descriptor))
        expected_names = set(files)
        if actual_names != expected_names:
            raise SecretFileViolation("secret root inventory differs from policy")

        for name, expected in files.items():
            if not isinstance(name, str) or not name or "/" in name:
                raise SecretFileViolation("secret file names must be simple path components")
            if not isinstance(expected, dict):
                raise SecretFileViolation(f"invalid policy for {name}")
            file_descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
            try:
                file_metadata = os.fstat(file_descriptor)
                if not stat.S_ISREG(file_metadata.st_mode):
                    raise SecretFileViolation(f"secret is not a regular file: {name}")
                if file_metadata.st_uid != expected.get("owner_uid"):
                    raise SecretFileViolation(f"secret owner mismatch: {name}")
                if file_metadata.st_gid != expected.get("group_gid"):
                    raise SecretFileViolation(f"secret group mismatch: {name}")
                expected_mode = _octal_mode(expected.get("mode"), f"{name}.mode")
                if stat.S_IMODE(file_metadata.st_mode) != expected_mode:
                    raise SecretFileViolation(f"secret mode mismatch: {name}")
                if file_metadata.st_size == 0:
                    raise SecretFileViolation(f"secret must not be empty: {name}")
            finally:
                os.close(file_descriptor)
    except OSError as error:
        raise SecretFileViolation(f"secret metadata check failed: {error.filename or root}") from None
    finally:
        os.close(descriptor)


def _load_policy(path: Path) -> dict[str, Any]:
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise SecretFileViolation(f"invalid secret file policy: {path}") from None
    if not isinstance(policy, dict):
        raise SecretFileViolation("secret file policy root must be an object")
    return policy


def main(argv: list[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Validate production secret file metadata without reading values.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--ordinary-user", required=True)
    parser.add_argument(
        "--policy",
        type=Path,
        default=project_root / "infra/secrets/file-policy.yaml",
    )
    arguments = parser.parse_args(argv)
    try:
        policy = _load_policy(arguments.policy)
        validate_policy(policy)
        try:
            ordinary_user = pwd.getpwnam(arguments.ordinary_user)
        except KeyError:
            raise SecretFileViolation("ordinary deployment user does not exist") from None
        sudo_user = os.environ.get("SUDO_USER")
        if sudo_user and sudo_user != arguments.ordinary_user:
            raise SecretFileViolation("ordinary deployment user differs from SUDO_USER")
        validate_ordinary_user_groups(
            ordinary_user.pw_uid,
            set(os.getgrouplist(ordinary_user.pw_name, ordinary_user.pw_gid)),
            policy,
        )
        load_lifecycle_inventory(arguments.inventory, policy)
        validate_secret_tree(arguments.root, policy)
    except SecretFileViolation as error:
        print(f"production secret preflight FAILED: {error}", file=sys.stderr)
        return 1
    print("production secret preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
