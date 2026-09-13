from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from typing import Any, Protocol

from thesis_trace.modules.access.account_administration.contracts import AccountSummary
from thesis_trace.modules.access.confirmation_challenge.service import (
    ConfirmationService,
)
from thesis_trace.modules.access.contracts import AuthenticatedActor, Role


class AccessConfirmationService:
    """Parent facade: no child challenge object escapes Access."""

    def __init__(self, confirmations: ConfirmationService) -> None:
        self._confirmations = confirmations

    @staticmethod
    def _validate(actor: AuthenticatedActor, payload: str) -> None:
        if actor.role is not Role.OWNER:
            raise PermissionError("resource_unavailable")
        if not isinstance(payload, str) or len(payload.encode("utf-8")) > 262144:
            raise ValueError("invalid_confirmation_payload")

    def preview(
        self,
        actor: AuthenticatedActor,
        *,
        action: str,
        target: str,
        version: int,
        payload: str,
        impact: str,
    ) -> tuple[str, datetime]:
        self._validate(actor, payload)
        token, challenge = self._confirmations.preview(
            actor.actor_id,
            action,
            target,
            version,
            json.loads(payload),
            {"consequences": impact},
        )
        return token, challenge.expires_at

    def consume(
        self,
        actor: AuthenticatedActor,
        *,
        token: str,
        action: str,
        version: int,
        payload: str,
        reason: str,
    ) -> tuple[str, datetime]:
        self._validate(actor, payload)
        challenge = self._confirmations.confirm(
            token, actor.actor_id, action, version, json.loads(payload), reason
        )
        return challenge.challenge_id, challenge.expires_at


@dataclass(frozen=True, slots=True)
class AccountActionPreview:
    challenge_token: str
    expires_at: datetime
    target_version: int
    impact_summary: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ConfirmedAccountAction:
    challenge_id: str
    accepted: bool = True


class AccountActionUnitOfWork(Protocol):
    def list_account_summaries(self) -> list[AccountSummary]: ...
    def execute_confirmed_action(
        self,
        *,
        token: str,
        actor_id: str,
        action_type: str,
        target_version: int,
        payload: dict[str, Any],
        reason: str,
        now: datetime,
    ) -> tuple[str, AccountSummary | None]: ...


class AccountActionService:
    """Access-parent policy and atomic account-action orchestration."""

    def __init__(
        self,
        repository: AccountActionUnitOfWork,
        confirmations: ConfirmationService,
        *,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._repository, self._confirmations, self._clock = (
            repository,
            confirmations,
            clock,
        )

    @staticmethod
    def _authorize(actor: AuthenticatedActor, *, owner_only: bool = False) -> None:
        allowed = {Role.OWNER} if owner_only else {Role.OWNER, Role.ADMIN}
        if actor.role not in allowed:
            raise PermissionError("resource_unavailable")

    def list_accounts(self, actor: AuthenticatedActor) -> list[dict[str, Any]]:
        self._authorize(actor)
        return [asdict(item) for item in self._repository.list_account_summaries()]

    def get_account(self, actor: AuthenticatedActor, user_id: str) -> dict[str, Any]:
        self._authorize(actor)
        item = next(
            (
                value
                for value in self._repository.list_account_summaries()
                if value.user_id == user_id
            ),
            None,
        )
        if item is None:
            raise LookupError("resource_unavailable")
        return asdict(item)

    def preview(
        self,
        actor: AuthenticatedActor,
        *,
        action_type: str,
        target_id: str,
        target_version: int,
        payload: dict[str, Any],
    ) -> AccountActionPreview:
        self._authorize(actor, owner_only=True)
        summary = self._impact_summary(action_type, target_id, target_version, payload)
        token, challenge = self._confirmations.preview(
            actor.actor_id,
            action_type,
            target_id,
            target_version,
            payload,
            summary,
        )
        return AccountActionPreview(
            token, challenge.expires_at, challenge.target_version, summary
        )

    def confirm(
        self,
        actor: AuthenticatedActor,
        *,
        token: str,
        action_type: str,
        target_version: int,
        payload: dict[str, Any],
        reason: str,
    ) -> tuple[ConfirmedAccountAction, AccountSummary | None]:
        self._authorize(actor, owner_only=True)
        challenge_id, result = self._repository.execute_confirmed_action(
            token=token,
            actor_id=actor.actor_id,
            action_type=action_type,
            target_version=target_version,
            payload=payload,
            reason=reason,
            now=self._clock(),
        )
        return ConfirmedAccountAction(challenge_id), result

    def _impact_summary(
        self, action: str, target_id: str, version: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if action == "create_account":
            required = {
                "role",
                "provider_id",
                "provider_type",
                "provider_subject",
                "email_fact",
            }
            if target_id != "new_account" or version != 1 or set(payload) != required:
                raise LookupError("resource_unavailable")
            role = Role(payload["role"]).value
            return {
                "subject": "New account",
                "action_label": "Create account",
                "before": {"status": "absent"},
                "after": {
                    "role": role,
                    "status": "active",
                    "identity_provider": str(payload["provider_type"]),
                },
                "consequences": [
                    "Consumes one active-account slot",
                    "Grants role capabilities",
                ],
                "confirmation_verb": "CREATE",
            }
        current = next(
            (
                item
                for item in self._repository.list_account_summaries()
                if item.user_id == target_id
            ),
            None,
        )
        if current is None or current.version != version:
            raise LookupError("resource_unavailable")
        before = {
            "role": current.role.value,
            "status": current.status,
            "identity_provider": current.masked_identity,
        }
        after = dict(before)
        if action == "change_role" and set(payload) == {"role"}:
            after["role"] = Role(payload["role"]).value
            label, verb = "Change account role", "CHANGE ROLE"
        elif (
            action == "change_status"
            and set(payload) == {"status"}
            and payload["status"] in {"active", "disabled"}
        ):
            after["status"] = str(payload["status"])
            label, verb = "Change account status", "CHANGE STATUS"
        elif action == "add_identity" and set(payload) == {
            "provider_id",
            "provider_type",
            "provider_subject",
            "email_fact",
        }:
            after["identity_provider"] = str(payload["provider_type"])
            label, verb = "Add account identity", "ADD IDENTITY"
        elif action == "disable_identity" and set(payload) == {
            "provider_id",
            "provider_type",
            "provider_subject",
        }:
            after["identity_provider"] = "disabled"
            label, verb = "Disable account identity", "DISABLE IDENTITY"
        elif action == "replace_identity" and set(payload) == {
            "old_provider_id",
            "old_provider_type",
            "old_provider_subject",
            "provider_id",
            "provider_type",
            "provider_subject",
            "email_fact",
        }:
            after["identity_provider"] = str(payload["provider_type"])
            label, verb = "Replace account identity", "REPLACE IDENTITY"
        else:
            raise LookupError("resource_unavailable")
        return {
            "subject": f"Account • {target_id[-4:]}",
            "action_label": label,
            "before": before,
            "after": after,
            "consequences": [
                "Invalidates existing sessions",
                "Changes future sign-in authorization",
            ],
            "confirmation_verb": verb,
        }
