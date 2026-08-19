from __future__ import annotations

from dataclasses import dataclass

from thesis_trace.modules.access.identity_registry.contracts import ProviderIdentity


@dataclass(frozen=True, slots=True)
class RecoveryPolicyConfiguration:
    """Fail-closed observation of the externally managed recovery policy."""

    approved_identity: ProviderIdentity
    policy_version: str
    enabled: bool
