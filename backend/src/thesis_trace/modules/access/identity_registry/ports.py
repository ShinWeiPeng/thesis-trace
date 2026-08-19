from __future__ import annotations
from typing import Protocol
from thesis_trace.modules.access.identity_registry.contracts import AccessAccount, ProviderIdentity, ProviderIdentityMapping

class AccountRepositoryPort(Protocol):
    def find_mapping(self, identity: ProviderIdentity) -> ProviderIdentityMapping | None: ...
    def get_account(self, user_id: str) -> AccessAccount | None: ...
