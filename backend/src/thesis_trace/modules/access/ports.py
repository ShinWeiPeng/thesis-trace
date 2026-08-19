from __future__ import annotations
from contextlib import AbstractContextManager
from typing import Protocol, Any
from thesis_trace.modules.access.contracts import SecurityContext
class SecurityContextPort(Protocol):
    def transaction(self, context: SecurityContext) -> AbstractContextManager[Any]: ...
