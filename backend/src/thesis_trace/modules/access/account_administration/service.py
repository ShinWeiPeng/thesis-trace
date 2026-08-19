from __future__ import annotations
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role
class AccountAdministration:
    def __init__(self, repository): self._repository=repository
    def list_accounts(self, actor: AuthenticatedActor):
        if actor.role not in {Role.OWNER,Role.ADMIN}: raise PermissionError("resource_unavailable")
        return self._repository.list_account_summaries()
