from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_wave1_platform import (
    ContractViolation,
    validate_access_contract,
    validate_all,
    validate_no_sensitive_material,
    validate_standalone_secret_override,
)


class AccessContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads((ROOT / "infra/cloudflare/access-contract.yaml").read_text(encoding="utf-8"))

    def test_canonical_contract_is_valid(self) -> None:
        validate_access_contract(self.contract)

    def test_provider_identity_key_includes_provider_type(self) -> None:
        self.assertEqual(self.contract["provider_identity_key"], ["provider_id", "provider_type", "provider_subject"])

    def test_production_database_roles_are_separate_and_least_privilege(self) -> None:
        sql = (ROOT / "infra/postgres/production-roles.sql").read_text(encoding="utf-8").upper()
        for role in ("THESIS_TRACE_MIGRATION", "THESIS_TRACE_API", "THESIS_TRACE_COLLECTOR"):
            self.assertIn(role, sql)
        self.assertIn("NOBYPASSRLS", sql)
        self.assertIn("REVOKE CREATE ON SCHEMA PUBLIC", sql)
        self.assertNotIn("GRANT CREATE ON DATABASE THESIS_TRACE TO THESIS_TRACE_API", sql)
        self.assertNotIn("GRANT CREATE ON DATABASE THESIS_TRACE TO THESIS_TRACE_COLLECTOR", sql)
        self.assertNotIn("ALTER DEFAULT PRIVILEGES", sql)

        grants = (ROOT / "infra/postgres/run-production-migrations.py").read_text(encoding="utf-8").upper()
        self.assertIn("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA ACCESS,RESEARCH", grants)
        self.assertIn("REVOKE CREATE,TEMP ON DATABASE", grants)
        self.assertNotIn("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES", grants)
        self.assertNotIn("UPDATE,DELETE ON ACCESS.SECURITY_AUDIT_EVENTS", grants)
        self.assertNotIn("UPDATE,DELETE ON RESEARCH.AUDIT_EVENTS", grants)

    def test_runtime_composition_uses_read_only_schema_compatibility_probe(self) -> None:
        composition = (ROOT / "backend/src/thesis_trace/bootstrap/application.py").read_text(encoding="utf-8")
        self.assertIn("verify_schema_compatibility(database_url_provider)", composition)
        self.assertNotIn("bootstrap_schema(", composition)

    def test_architecture_gate_runs_after_its_python_and_typescript_dependencies(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        architecture_gate = workflow.index("name: Validate development architecture")
        self.assertLess(workflow.index("name: Install architecture dependencies"), architecture_gate)
        self.assertLess(workflow.index("name: Install frontend dependencies"), architecture_gate)

    def test_standalone_compose_uses_root_owned_file_secrets(self) -> None:
        validate_standalone_secret_override(ROOT)

    def test_bypass_is_rejected(self) -> None:
        invalid = deepcopy(self.contract)
        invalid["forbidden_actions"] = ["everyone"]
        with self.assertRaises(ContractViolation):
            validate_access_contract(invalid)

    def test_partial_path_is_rejected(self) -> None:
        invalid = deepcopy(self.contract)
        invalid["application"]["path_coverage"] = ["/api/*"]
        with self.assertRaises(ContractViolation):
            validate_access_contract(invalid)

    def test_normal_session_must_be_eight_hours(self) -> None:
        invalid = deepcopy(self.contract)
        invalid["policies"]["normal_google"]["session_minutes"] = 481
        with self.assertRaises(ContractViolation):
            validate_access_contract(invalid)

    def test_unsafe_human_selectors_are_rejected(self) -> None:
        for selector in ("everyone", "email_domain", "magic_link", "service_token_human", "bypass"):
            with self.subTest(selector=selector):
                invalid = deepcopy(self.contract)
                invalid["policies"]["normal_google"]["selector"] = selector
                with self.assertRaises(ContractViolation):
                    validate_access_contract(invalid)

    def test_recovery_must_be_disabled_and_bounded(self) -> None:
        invalid = deepcopy(self.contract)
        invalid["policies"]["owner_recovery"]["enabled_by_default"] = True
        with self.assertRaises(ContractViolation):
            validate_access_contract(invalid)
        invalid = deepcopy(self.contract)
        invalid["policies"]["owner_recovery"]["session_minutes"] = 31
        with self.assertRaises(ContractViolation):
            validate_access_contract(invalid)

    def test_full_platform_contract(self) -> None:
        validate_all(ROOT)

    def test_security_redaction_canaries_are_rejected(self) -> None:
        for canary in (
            "owner@real.example",
            "-----BEGIN PRIVATE KEY-----",
            "eyJhbGciOiJSUzI1NiJ9.payload.signature",
        ):
            with self.subTest(canary=canary):
                with self.assertRaises(ContractViolation):
                    validate_no_sensitive_material(canary)

    def test_documentation_hostname_is_not_treated_as_identity(self) -> None:
        validate_no_sensitive_material("thesis-trace.example.invalid")


if __name__ == "__main__":
    unittest.main()
