from __future__ import annotations
from thesis_trace.modules.access.identity_registry.contracts import AccessAccount, VerifiedPrincipal
from thesis_trace.modules.access.identity_registry.ports import AccountRepositoryPort

class IdentityRegistry:
    def __init__(self, repository: AccountRepositoryPort) -> None: self._repository = repository
    def resolve(self, principal: VerifiedPrincipal) -> AccessAccount:
        identity = principal.identity
        if not identity.provider_id or not identity.provider_type or not identity.subject:
            raise PermissionError("access_denied")
        mapping = self._repository.find_mapping(identity)
        if mapping is None or not mapping.enabled: raise PermissionError("access_denied")
        account = self._repository.get_account(mapping.user_id)
        if account is None or account.status != "active": raise PermissionError("access_denied")
        return account
