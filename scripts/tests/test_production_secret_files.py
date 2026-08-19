import os
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_production_secret_files import (
    SecretFileViolation,
    load_lifecycle_inventory,
    validate_lifecycle_inventory,
    validate_ordinary_user_groups,
    validate_policy,
    validate_secret_tree,
)


class ProductionSecretFileTests(unittest.TestCase):
    def _policy(self, *, mode: str = "0400") -> dict[str, object]:
        return {
            "root_owner_uid": os.getuid(),
            "root_directory_mode": "0700",
            "files": {
                "api_database_url": {
                    "owner_uid": os.getuid(),
                    "group_gid": os.getgid(),
                    "mode": mode,
                }
            },
        }

    def _canonical_lifecycle(self, policy: dict[str, object]) -> dict[str, object]:
        return {
            "contract_version": 1,
            "secrets": {
                name: {
                    "owner_uid": definition["owner_uid"],
                    "consumer": definition["consumer"],
                    "created_at": "2026-08-01T00:00:00Z",
                    "last_rotated_at": "2026-08-01T00:00:00Z",
                    "expires_at": "2026-09-01T00:00:00Z",
                    "revoked_at": None,
                    "audit_reference": "deployment-run-001",
                }
                for name, definition in policy["files"].items()
            },
        }

    def test_valid_tree_passes_without_reading_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            anchor = Path(temporary)
            secret_root = anchor / "secrets"
            secret_root.mkdir(mode=0o700)
            secret = secret_root / "api_database_url"
            secret.write_bytes(b"opaque-test-value")
            secret.chmod(0o400)

            validate_secret_tree(
                secret_root,
                self._policy(),
                trusted_ancestor=anchor,
            )

    def test_symlinked_secret_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            anchor = Path(temporary)
            secret_root = anchor / "secrets"
            secret_root.mkdir(mode=0o700)
            target = anchor / "target"
            target.write_bytes(b"opaque-test-value")
            target.chmod(0o400)
            (secret_root / "api_database_url").symlink_to(target)

            with self.assertRaises(SecretFileViolation):
                validate_secret_tree(secret_root, self._policy(), trusted_ancestor=anchor)

    def test_symlinked_secret_root_is_rejected_with_stable_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            anchor = Path(temporary)
            real_root = anchor / "real-secrets"
            real_root.mkdir(mode=0o700)
            secret = real_root / "api_database_url"
            secret.write_bytes(b"opaque-test-value")
            secret.chmod(0o400)
            linked_root = anchor / "secrets"
            linked_root.symlink_to(real_root, target_is_directory=True)

            with self.assertRaises(SecretFileViolation):
                validate_secret_tree(linked_root, self._policy(), trusted_ancestor=anchor)

    def test_world_readable_secret_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            anchor = Path(temporary)
            secret_root = anchor / "secrets"
            secret_root.mkdir(mode=0o700)
            secret = secret_root / "api_database_url"
            secret.write_bytes(b"opaque-test-value")
            secret.chmod(0o404)

            with self.assertRaises(SecretFileViolation):
                validate_secret_tree(secret_root, self._policy(), trusted_ancestor=anchor)

    def test_empty_secret_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            anchor = Path(temporary)
            secret_root = anchor / "secrets"
            secret_root.mkdir(mode=0o700)
            secret = secret_root / "api_database_url"
            secret.touch(mode=0o400)

            with self.assertRaises(SecretFileViolation):
                validate_secret_tree(secret_root, self._policy(), trusted_ancestor=anchor)

    def test_unexpected_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            anchor = Path(temporary)
            secret_root = anchor / "secrets"
            secret_root.mkdir(mode=0o700)
            secret = secret_root / "api_database_url"
            secret.write_bytes(b"opaque-test-value")
            secret.chmod(0o400)
            extra = secret_root / "forgotten_old_credential"
            extra.write_bytes(b"must-not-remain")
            extra.chmod(0o400)

            with self.assertRaises(SecretFileViolation):
                validate_secret_tree(secret_root, self._policy(), trusted_ancestor=anchor)

    def test_wrong_group_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            anchor = Path(temporary)
            secret_root = anchor / "secrets"
            secret_root.mkdir(mode=0o700)
            secret = secret_root / "api_database_url"
            secret.write_bytes(b"opaque-test-value")
            secret.chmod(0o400)
            policy = self._policy()
            policy["files"]["api_database_url"]["group_gid"] = os.getgid() + 1

            with self.assertRaises(SecretFileViolation):
                validate_secret_tree(secret_root, policy, trusted_ancestor=anchor)

    def test_canonical_policy_covers_compose_inventory_and_runtime_ids(self) -> None:
        manifest = json.loads((ROOT / "infra/secrets/manifest.yaml").read_text(encoding="utf-8"))
        policy = json.loads((ROOT / "infra/secrets/file-policy.yaml").read_text(encoding="utf-8"))
        expected_names = {
            name
            for names in manifest["services"].values()
            for name in names
        } | {"origin_ca.pem"}

        self.assertEqual(policy["contract_version"], 1)
        self.assertEqual(policy["root_owner_uid"], 0)
        self.assertEqual(policy["root_directory_mode"], "0711")
        self.assertEqual(set(policy["files"]), expected_names)
        self.assertEqual(policy["files"]["postgres_password"]["group_gid"], 70)
        self.assertEqual(policy["files"]["api_database_url"]["group_gid"], 65532)
        self.assertEqual(policy["files"]["tunnel_credentials"]["group_gid"], 65532)
        self.assertEqual(policy["files"]["origin_tls_key"]["group_gid"], 0)

        validate_policy(policy)

    def test_policy_cannot_delegate_root_ownership(self) -> None:
        policy = json.loads((ROOT / "infra/secrets/file-policy.yaml").read_text(encoding="utf-8"))
        policy["root_owner_uid"] = os.getuid() or 1000

        with self.assertRaises(SecretFileViolation):
            validate_policy(policy)

    def test_valid_lifecycle_inventory_is_current(self) -> None:
        policy = json.loads((ROOT / "infra/secrets/file-policy.yaml").read_text(encoding="utf-8"))
        inventory = self._canonical_lifecycle(policy)

        validate_lifecycle_inventory(
            inventory,
            policy,
            now=datetime(2026, 8, 19, tzinfo=timezone.utc),
        )

    def test_expired_lifecycle_is_rejected(self) -> None:
        policy = json.loads((ROOT / "infra/secrets/file-policy.yaml").read_text(encoding="utf-8"))
        inventory = self._canonical_lifecycle(policy)
        inventory["secrets"]["api_database_url"]["expires_at"] = "2026-08-19T00:00:00Z"

        with self.assertRaises(SecretFileViolation):
            validate_lifecycle_inventory(
                inventory,
                policy,
                now=datetime(2026, 8, 19, tzinfo=timezone.utc),
            )

    def test_revoked_lifecycle_is_rejected(self) -> None:
        policy = json.loads((ROOT / "infra/secrets/file-policy.yaml").read_text(encoding="utf-8"))
        inventory = self._canonical_lifecycle(policy)
        inventory["secrets"]["api_database_url"]["revoked_at"] = "2026-08-18T00:00:00Z"

        with self.assertRaises(SecretFileViolation):
            validate_lifecycle_inventory(
                inventory,
                policy,
                now=datetime(2026, 8, 19, tzinfo=timezone.utc),
            )

    def test_lifecycle_cannot_contain_a_secret_value_field(self) -> None:
        policy = json.loads((ROOT / "infra/secrets/file-policy.yaml").read_text(encoding="utf-8"))
        inventory = self._canonical_lifecycle(policy)
        inventory["secrets"]["api_database_url"]["value"] = "forbidden"

        with self.assertRaises(SecretFileViolation):
            validate_lifecycle_inventory(
                inventory,
                policy,
                now=datetime(2026, 8, 19, tzinfo=timezone.utc),
            )

    def test_lifecycle_sidecar_has_root_only_metadata_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            anchor = Path(temporary)
            policy = self._policy()
            policy["lifecycle_inventory"] = {
                "owner_uid": os.getuid(),
                "group_gid": os.getgid(),
                "mode": "0400",
                "max_bytes": 65536,
            }
            policy["files"]["api_database_url"]["consumer"] = "api"
            inventory = self._canonical_lifecycle(policy)
            path = anchor / "secret-inventory.json"
            path.write_text(json.dumps(inventory), encoding="utf-8")
            path.chmod(0o400)

            load_lifecycle_inventory(
                path,
                policy,
                trusted_ancestor=anchor,
                now=datetime(2026, 8, 19, tzinfo=timezone.utc),
            )

    def test_ordinary_user_cannot_share_a_service_secret_group(self) -> None:
        policy = json.loads((ROOT / "infra/secrets/file-policy.yaml").read_text(encoding="utf-8"))
        validate_ordinary_user_groups(1000, {1000, 65534}, policy)

        with self.assertRaises(SecretFileViolation):
            validate_ordinary_user_groups(1000, {1000, 65532}, policy)


if __name__ == "__main__":
    unittest.main()
