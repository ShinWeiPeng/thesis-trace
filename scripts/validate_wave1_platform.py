#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from validate_production_secret_files import SecretFileViolation, validate_policy


class ContractViolation(RuntimeError):
    pass


REQUIRED_FORBIDDEN = {
    "bypass", "everyone", "email_domain", "any_valid_identity", "magic_link", "service_token_human"
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractViolation(message)


def load_json_yaml(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractViolation(f"invalid machine-readable contract: {path}") from error
    require(isinstance(value, dict), f"contract root must be an object: {path}")
    return value


def validate_access_contract(contract: dict[str, Any]) -> None:
    require(set(contract) == {
        "contract_version", "application", "forbidden_actions", "provisioning_order", "policies",
        "provider_identity_key", "email_identity_merge",
    }, "Access contract contains unknown top-level authority")
    application = contract.get("application", {})
    require(contract.get("contract_version") == 1, "unsupported Access contract version")
    require(application.get("type") == "self_hosted", "Access application must be self-hosted")
    require(application.get("hostname_ref") == "THESIS_TRACE_PUBLIC_HOSTNAME", "hostname must be a non-secret reference")
    require(application.get("path_coverage") == "all", "Access must cover the complete hostname and all paths")
    require(application.get("default_action") == "deny", "Access must deny by default")
    require(application.get("single_application") is True, "exactly one Access application is required")
    require(set(contract.get("forbidden_actions", [])) == REQUIRED_FORBIDDEN, "all unsafe Access actions must be forbidden")
    require(contract.get("provisioning_order") == ["access_application", "named_tunnel_public_hostname_route"],
            "Access protection must be provisioned before the tunnel hostname route")
    require(contract.get("provider_identity_key") == ["provider_id", "provider_type", "provider_subject"], "provider identity key is incomplete")
    require(contract.get("email_identity_merge") is False, "same-email provider identities must not merge")

    policies = contract.get("policies", {})
    require(set(policies) == {"normal_google", "owner_recovery"}, "only normal and recovery policies are allowed")
    normal = policies["normal_google"]
    require(set(normal) == {
        "enabled", "provider", "identity_facts_ref", "selector", "mfa_required", "session_minutes"
    }, "normal policy contains unknown authority")
    require(normal.get("enabled") is True and normal.get("provider") == "google", "normal policy must use Google")
    require(normal.get("selector") == "exact_identity_facts", "normal policy must use exact irreversible identity facts")
    require(str(normal.get("identity_facts_ref", "")).startswith("secret://"), "normal identity facts must be referenced")
    require(normal.get("mfa_required") is True, "normal policy must require MFA")
    require(normal.get("session_minutes") == 480, "normal Access session must be exactly eight hours")

    recovery = policies["owner_recovery"]
    require(set(recovery) == {
        "enabled_by_default", "visible_in_normal_login", "activation", "provider", "identity_fact_ref",
        "principal_count", "mfa_every_login", "session_minutes", "maps_to_existing_owner",
        "privilege_elevation", "first_use_audit", "shutdown_action_item",
    }, "recovery policy contains unknown authority")
    require(recovery.get("enabled_by_default") is False, "recovery must be disabled by default")
    require(recovery.get("visible_in_normal_login") is False, "recovery must not appear in normal login")
    require(recovery.get("activation") == "manual_cloudflare_management_only", "recovery activation must be manual")
    require(recovery.get("provider") == "cloudflare_account", "recovery must use the Cloudflare account provider")
    require(str(recovery.get("identity_fact_ref", "")).startswith("secret://"), "recovery identity must be referenced")
    require(recovery.get("principal_count") == 1, "recovery must name exactly one provider identity")
    require(recovery.get("mfa_every_login") is True, "recovery must require MFA every login")
    require(isinstance(recovery.get("session_minutes"), int) and 0 < recovery["session_minutes"] <= 30,
            "recovery session must be at most thirty minutes")
    require(recovery.get("maps_to_existing_owner") is True and recovery.get("privilege_elevation") is False,
            "recovery must map to the existing Owner without elevation")
    require(recovery.get("first_use_audit") is True and recovery.get("shutdown_action_item") == "safety_locked",
            "recovery first use must create immutable security work")


def compose_model(root: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["docker", "compose", "-f", str(root / "compose.yaml"), "config", "--format", "json"],
        cwd=root, text=True, capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise ContractViolation(f"Compose parser failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def normalized_names(values: list[Any]) -> set[str]:
    names: set[str] = set()
    for value in values:
        names.add(value if isinstance(value, str) else str(value.get("source", value.get("target", ""))))
    return names


def validate_compose(root: Path, secret_contract: dict[str, Any]) -> None:
    model = compose_model(root)
    services = model.get("services", {})
    required = {"migration", "api", "collector", "web", "postgres", "origin-gateway", "cloudflared"}
    require(required <= set(services), "Compose is missing a Wave 1 process")
    expected_networks = {
        "migration": {"data"}, "api": {"edge-app", "data"}, "collector": {"data"}, "web": {"edge-app"},
        "postgres": {"data"}, "origin-gateway": {"edge-app", "origin"},
        "cloudflared": {"origin", "tunnel-egress"},
    }
    for name in required:
        service = services[name]
        require(not service.get("ports"), f"{name} must not publish host ports")
        require(service.get("network_mode") != "host", f"{name} must not use host networking")
        require(service.get("privileged") is not True, f"{name} must not be privileged")
        mounts = json.dumps(service.get("volumes", []), sort_keys=True)
        require("docker.sock" not in mounts, f"{name} must not mount the Docker socket")
        require(set(service.get("networks", {})) == expected_networks[name], f"{name} has invalid network membership")
        environment = service.get("environment", {})
        for key, value in environment.items():
            looks_secret = any(marker in key.upper() for marker in ("PASSWORD", "TOKEN", "SECRET", "CREDENTIAL", "IDENTIT", "ISSUER", "AUDIENCE", "DATABASE_URL"))
            require(not looks_secret or key.endswith("_FILE"), f"{name}.{key} must be a file reference")
            if key.endswith("_FILE"):
                require(str(value).startswith("/run/secrets/"), f"{name}.{key} must point to a mounted secret")
    for name in ("origin-gateway", "cloudflared"):
        require("ALL" in services[name].get("cap_drop", []), f"{name} must drop all Linux capabilities")

    networks = model.get("networks", {})
    require(networks.get("edge-app", {}).get("internal") is True, "edge application network must be internal")
    require(networks.get("data", {}).get("internal") is True, "data network must be internal")
    require(networks.get("origin", {}).get("internal") is True, "origin network must be internal")
    require(networks.get("tunnel-egress", {}).get("internal") is not True, "cloudflared needs the sole egress network")

    require(secret_contract.get("delivery") == "root_owned_read_only_files", "secret delivery contract is unsafe")
    require(secret_contract.get("direct_secret_environment_values") is False, "direct secret environment values are forbidden")
    allowed = secret_contract.get("services", {})
    for name in required:
        actual = normalized_names(services[name].get("secrets", []))
        require(actual == set(allowed.get(name, [])), f"{name} secret scope differs from canonical manifest")


def validate_tunnel_and_caddy(root: Path) -> None:
    tunnel = (root / "infra/cloudflare/tunnel-config.yaml").read_text(encoding="utf-8")
    require("tunnel: thesis-trace-named-tunnel" in tunnel, "a named tunnel is required")
    require("credentials-file: /run/secrets/tunnel_credentials" in tunnel, "tunnel credential must be file mounted")
    require("service: https://origin-gateway:8443" in tunnel, "tunnel may target only local Caddy HTTPS")
    require("noTLSVerify: false" in tunnel and "caPool: /run/configs/origin_ca.pem" in tunnel,
            "origin TLS verification and pinned CA are required")
    require(tunnel.rstrip().endswith("- service: http_status:404"), "tunnel needs a terminal 404 rule")
    forbidden = ("ssh://", "tcp://", "postgres", "docker.sock", "noTLSVerify: true")
    require(not any(value in tunnel for value in forbidden), "tunnel contains a forbidden route or TLS bypass")

    caddy = (root / "infra/caddy/Caddyfile").read_text(encoding="utf-8")
    require("tls /run/secrets/origin_tls_cert /run/secrets/origin_tls_key" in caddy, "Caddy origin TLS is required")
    upstreams = set(re.findall(r"reverse_proxy\s+([^\s]+)", caddy))
    require(upstreams == {"api:8000", "web:8080"}, "Caddy may route only Web and API")
    require("admin off" in caddy and "Cache-Control \"no-store\"" in caddy, "Caddy hardening is incomplete")


def validate_standalone_secret_override(root: Path) -> None:
    override = load_json_yaml(root / "infra/compose.production.yaml")
    require(set(override) == {"secrets", "configs"}, "production Compose override contains unknown authority")

    secret_contract = load_json_yaml(root / "infra/secrets/manifest.yaml")
    expected_secrets = {
        secret
        for service_secrets in secret_contract.get("services", {}).values()
        for secret in service_secrets
    }
    secrets = override.get("secrets", {})
    require(set(secrets) == expected_secrets, "production Compose override secret inventory differs from the canonical manifest")
    prefix = "${THESIS_TRACE_SECRETS_DIR:?THESIS_TRACE_SECRETS_DIR is required}/"
    for name, definition in secrets.items():
        require(
            definition == {"external": False, "file": f"{prefix}{name}"},
            f"production secret {name} must use its root-owned file reference",
        )

    require(
        override.get("configs") == {
            "origin_ca": {"external": False, "file": f"{prefix}origin_ca.pem"}
        },
        "origin CA must use its pinned root-owned file reference",
    )


def validate_secret_file_policy(root: Path, secret_contract: dict[str, Any]) -> None:
    expected_consumers: dict[str, str] = {}
    for consumer, names in secret_contract.get("services", {}).items():
        for name in names:
            require(name not in expected_consumers, f"secret has multiple consumers: {name}")
            expected_consumers[name] = consumer
    expected_consumers["origin_ca.pem"] = "cloudflared"
    try:
        validate_policy(
            load_json_yaml(root / "infra/secrets/file-policy.yaml"),
            expected_consumers=expected_consumers,
        )
    except SecretFileViolation as error:
        raise ContractViolation(str(error)) from None


def validate_no_sensitive_material(text: str) -> None:
    real_email = re.compile(r"\b[A-Z0-9._%+-]+@(?![^\s]*\.invalid\b)[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
    require(real_email.search(text) is None, "platform contract contains a real email identity")
    require("BEGIN PRIVATE KEY" not in text and "eyJ" not in text, "platform contract contains credential material")


def validate_redaction_and_live_boundary(root: Path) -> None:
    paths = [
        root / "infra/cloudflare/access-contract.yaml", root / "infra/cloudflare/tunnel-config.yaml",
        root / "infra/secrets/manifest.yaml", root / "compose.yaml",
    ]
    validate_no_sensitive_material("\n".join(path.read_text(encoding="utf-8") for path in paths))
    evidence = load_json_yaml(root / "infra/cloudflare/live-evidence.yaml")
    require(evidence.get("status") == "BLOCKED" and len(evidence.get("required", [])) >= 5,
            "live Cloudflare/VM evidence must remain explicitly BLOCKED")


def validate_rls_contract(root: Path) -> None:
    sql = (root / "infra/postgres/wave1-rls-contract.sql").read_text(encoding="utf-8").upper()
    for clause in ("NOBYPASSRLS", "ENABLE ROW LEVEL SECURITY", "FORCE ROW LEVEL SECURITY", "CURRENT_SETTING", "REVOKE ALL"):
        require(clause in sql, f"RLS contract is missing {clause}")
    require("GRANT UPDATE ON WAVE1_CONTRACT.SECURITY_AUDIT" not in sql, "audit rows must be append-only")

    production = (root / "infra/postgres/production-roles.sql").read_text(encoding="utf-8").upper()
    for role in ("THESIS_TRACE_MIGRATION", "THESIS_TRACE_API", "THESIS_TRACE_COLLECTOR"):
        require(role in production, f"production database role is missing: {role}")
    require(production.count("NOBYPASSRLS") >= 3, "all production roles must be NOBYPASSRLS")
    require("ALTER DATABASE THESIS_TRACE OWNER TO THESIS_TRACE_MIGRATION" in production, "migration role must own the database")
    require("GRANT CREATE ON DATABASE THESIS_TRACE TO THESIS_TRACE_API" not in production, "API runtime must not receive DDL")
    require("GRANT CREATE ON DATABASE THESIS_TRACE TO THESIS_TRACE_COLLECTOR" not in production, "collector runtime must not receive DDL")


def validate_all(root: Path) -> None:
    validate_access_contract(load_json_yaml(root / "infra/cloudflare/access-contract.yaml"))
    schema = load_json_yaml(root / "infra/cloudflare/access-contract.schema.json")
    require(schema.get("additionalProperties") is False, "Access schema must reject unknown top-level fields")
    secrets = load_json_yaml(root / "infra/secrets/manifest.yaml")
    validate_compose(root, secrets)
    validate_standalone_secret_override(root)
    validate_secret_file_policy(root, secrets)
    validate_tunnel_and_caddy(root)
    validate_redaction_and_live_boundary(root)
    validate_rls_contract(root)


if __name__ == "__main__":
    try:
        validate_all(Path(__file__).resolve().parents[1])
    except ContractViolation as error:
        print(f"Wave 1 platform contract FAILED: {error}", file=sys.stderr)
        raise SystemExit(1)
    print("Wave 1 platform contract passed; live Cloudflare/VM evidence remains BLOCKED")
