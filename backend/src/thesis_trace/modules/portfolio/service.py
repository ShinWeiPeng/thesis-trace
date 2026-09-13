from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from collections.abc import Callable
import uuid

from thesis_trace.modules.portfolio.contracts import (
    ConfirmTradeCommand,
    ConfirmTradeCorrectionCommand,
    ConfirmCompanyActionCommand,
    CompanyActionPreview,
    CompanyActionRecord,
    CostProfileSnapshot,
    HoldingSnapshot,
    OfficialSecuritySnapshot,
    PortfolioActorContext,
    PortfolioRecord,
    PortfolioRecommendationSnapshot,
    PortfolioSnapshot,
    PreviewTradeCommand,
    SaveCostProfileCommand,
    SaveInvestableCashCommand,
    TradePreview,
    TradeRecord,
    TradeCorrectionPreview,
    TradeCorrectionRecord,
    TradeSide,
)
from thesis_trace.modules.portfolio.policy import (
    aggregate_exposure,
    select_dca_multiplier,
)
from thesis_trace.modules.portfolio.ports import PortfolioStorePort
from thesis_trace.modules.portfolio.trades import (
    allocate_company_action,
    canonical_trade_fingerprint,
    validate_allocations,
)


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(type(value).__name__)


def _digest(value: object) -> str:
    encoded = json.dumps(
        asdict(value),
        default=_json_default,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return sha256(encoded.encode()).hexdigest()


def _required(value: str, code: str = "invalid_request") -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _rate(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError("invalid_cost_profile")
    return value


class PortfolioService:
    def __init__(
        self,
        store: PortfolioStorePort,
        *,
        trade_id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        correction_id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        company_action_id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._store = store
        self._trade_id_factory = trade_id_factory
        self._correction_id_factory = correction_id_factory
        self._company_action_id_factory = company_action_id_factory

    def with_store(self, store: PortfolioStorePort) -> PortfolioService:
        """Bind the same policies and deterministic factories to a request-scoped store."""
        return PortfolioService(
            store,
            trade_id_factory=self._trade_id_factory,
            correction_id_factory=self._correction_id_factory,
            company_action_id_factory=self._company_action_id_factory,
        )

    @staticmethod
    def _authorize(actor: PortfolioActorContext) -> None:
        if not actor.actor_id or not actor.may_manage_portfolio:
            raise PermissionError("resource_unavailable")

    def get(self, actor: PortfolioActorContext) -> PortfolioRecord:
        self._authorize(actor)
        record = self._store.get(actor.actor_id)
        if record is None:
            raise LookupError("resource_unavailable")
        return record

    def get_recommendation_snapshot(
        self, actor: PortfolioActorContext, snapshot_id: str
    ) -> PortfolioRecommendationSnapshot | None:
        self._authorize(actor)
        return self._store.get_recommendation_snapshot(actor.actor_id, snapshot_id)

    def prepare_recommendation_snapshot(
        self,
        actor: PortfolioActorContext,
        *,
        snapshot_id: str,
        expected_version: int,
        cost_profile_version: int,
        security_id: str,
        base_amount: Decimal,
        buy_price: Decimal,
        raw_ceiling: Decimal,
        now: datetime,
    ) -> PortfolioRecommendationSnapshot:
        """Evaluate all Owner buckets without changing holdings or reserving cash."""
        current = self.get(actor)
        if type(expected_version) is not int or current.version != expected_version:
            raise ValueError("version_conflict")
        if not snapshot_id.strip() or now.utcoffset() is None:
            raise ValueError("invalid_recommendation_snapshot")
        if current.cost_profile is None or current.cash_as_of is None:
            raise ValueError("portfolio_prerequisites_missing")
        if (
            type(cost_profile_version) is not int
            or current.cost_profile.version != cost_profile_version
        ):
            raise ValueError("cost_profile_version_conflict")
        if (
            current.cost_profile.effective_at.utcoffset() is None
            or current.cost_profile.effective_at > now
        ):
            raise ValueError("cost_profile_not_effective")
        if current.cash_as_of.utcoffset() is None or current.cash_as_of > now:
            raise ValueError("invalid_cash")
        portfolio = PortfolioSnapshot(
            current.version,
            current.cash,
            self._refresh_official_holdings(actor.actor_id, current.holdings, now),
        )
        target = self._official_security(actor.actor_id, security_id, now)
        exposure = aggregate_exposure(portfolio)
        sizing = select_dca_multiplier(
            base_amount=base_amount,
            raw_ceiling=raw_ceiling,
            portfolio=portfolio,
            security_id=target.security_id,
            official_close=target.official_close,
            buy_price=buy_price,
            cost_profile=current.cost_profile,
            official_industry=target.official_industry,
            themes=target.themes,
            price_date=target.price_date,
            price_source=target.price_source,
            industry_source=target.industry_source,
            classification_effective_at=target.classification_effective_at,
            theme_snapshot_version=target.theme_snapshot_version,
            theme_source=target.theme_source,
            theme_effective_at=target.theme_effective_at,
        )
        if sizing.multiplier == 0:
            sizing = replace(
                sizing,
                post_exposure=exposure,
                purchase_outflow=Decimal(0),
                acquired_quantity=Decimal(0),
            )
        return PortfolioRecommendationSnapshot(
            snapshot_id,
            portfolio,
            current.cost_profile,
            exposure,
            sizing,
            now,
            target,
            base_amount,
            buy_price,
            current.cash_as_of,
        )

    def save_cost_profile(
        self, command: SaveCostProfileCommand, *, now: datetime
    ) -> PortfolioRecord:
        self._authorize(command.actor)
        current = self._store.get(command.actor.actor_id)
        profile = CostProfileSnapshot(
            version=1
            if current is None or current.cost_profile is None
            else current.cost_profile.version + 1,
            buy_rate=_rate(command.buy_rate),
            minimum_buy_fee=_rate(command.minimum_buy_fee),
            sell_rate=_rate(command.sell_rate),
            minimum_sell_fee=_rate(command.minimum_sell_fee),
            tax_rate=_rate(command.tax_rate),
            effective_at=command.effective_at,
        )
        record = PortfolioRecord(
            owner_user_id=command.actor.actor_id,
            version=command.expected_version + 1,
            cost_profile=profile,
            cash=Decimal(0) if current is None else current.cash,
            cash_as_of=None if current is None else current.cash_as_of,
            holdings=() if current is None else current.holdings,
            trades=() if current is None else current.trades,
            updated_at=now,
            corrections=() if current is None else current.corrections,
            company_actions=() if current is None else current.company_actions,
        )
        return self._commit(command, record, "cost_profile_saved")

    def save_investable_cash(
        self, command: SaveInvestableCashCommand, *, now: datetime
    ) -> PortfolioRecord:
        current = self.get(command.actor)
        if (
            not command.cash.is_finite()
            or command.cash < 0
            or command.as_of.tzinfo is None
        ):
            raise ValueError("invalid_cash")
        record = replace(
            current,
            version=command.expected_version + 1,
            cash=command.cash,
            cash_as_of=command.as_of,
            updated_at=now,
        )
        return self._commit(command, record, "investable_cash_saved")

    def preview_trade(
        self, command: PreviewTradeCommand, *, now: datetime | None = None
    ) -> TradePreview:
        evaluation_time = now or datetime.now(timezone.utc)
        current = self.get(command.actor)
        if current.version != command.expected_version:
            raise ValueError("version_conflict")
        if current.cost_profile is None or current.cash_as_of is None:
            raise ValueError("portfolio_prerequisites_missing")
        validate_allocations(
            command.trade,
            command.allocations,
            available_by_bucket=command.available_by_bucket,
            allowed_bucket_ids=command.allowed_bucket_ids,
        )
        fingerprint = canonical_trade_fingerprint(command.trade)
        post_cash = current.cash
        holdings = list(
            self._refresh_official_holdings(
                command.actor.actor_id, current.holdings, evaluation_time
            )
        )
        official = self._official_security(
            command.actor.actor_id, command.trade.security_id, evaluation_time
        )
        current_snapshot = PortfolioSnapshot(
            current.version, current.cash, tuple(holdings)
        )
        current_exposure = aggregate_exposure(current_snapshot)
        notional = command.trade.price * Decimal(command.trade.quantity)
        total_cost = notional + command.trade.fees + command.trade.tax
        if command.trade.side is TradeSide.BUY:
            if total_cost > current.cash:
                raise ValueError("insufficient_cash")
            post_cash -= total_cost
        else:
            post_cash += notional - command.trade.fees - command.trade.tax
        for allocation in command.allocations:
            delta = Decimal(allocation.quantity) * (
                Decimal(1) if command.trade.side is TradeSide.BUY else Decimal(-1)
            )
            index = next(
                (
                    index
                    for index, value in enumerate(holdings)
                    if value.bucket_id == allocation.bucket_id
                    and value.security_id == command.trade.security_id
                ),
                None,
            )
            if index is None:
                if delta < 0:
                    raise ValueError("bucket_oversell")
                holdings.append(
                    HoldingSnapshot(
                        allocation.bucket_id,
                        command.trade.security_id,
                        delta,
                        official.official_close,
                        official.official_industry,
                        official.themes,
                        official.price_date,
                        official.price_source,
                        official.industry_source,
                        official.classification_effective_at,
                        official.theme_snapshot_version,
                        official.theme_source,
                        official.theme_effective_at,
                    )
                )
            else:
                updated = holdings[index].quantity + delta
                if updated < 0:
                    raise ValueError("bucket_oversell")
                holdings[index] = replace(
                    holdings[index],
                    quantity=updated,
                    official_close=official.official_close,
                    official_industry=official.official_industry,
                    themes=official.themes,
                    price_date=official.price_date,
                    price_source=official.price_source,
                    industry_source=official.industry_source,
                    classification_effective_at=official.classification_effective_at,
                    theme_snapshot_version=official.theme_snapshot_version,
                    theme_source=official.theme_source,
                    theme_effective_at=official.theme_effective_at,
                )
        post = PortfolioSnapshot(
            current.version + 1,
            post_cash,
            tuple(value for value in holdings if value.quantity > 0),
        )
        exposure = aggregate_exposure(post)
        if command.trade.side is TradeSide.BUY and not exposure.feasible:
            raise ValueError("risk_cap")
        if (
            command.trade.side is TradeSide.SELL
            and not self._sell_reduces_or_preserves_breaches(current_exposure, exposure)
        ):
            raise ValueError("risk_cap")
        preview_body = {
            "expected_version": current.version,
            "fingerprint": fingerprint,
            "allocations": [asdict(value) for value in command.allocations],
            "post_cash": str(post.cash),
            "exposure": asdict(exposure),
        }
        preview_digest = sha256(
            json.dumps(
                preview_body,
                default=_json_default,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return TradePreview(
            current.version,
            fingerprint,
            preview_digest,
            command.trade,
            command.allocations,
            post,
            exposure,
            official,
        )

    def _official_security(
        self,
        actor_id: str,
        security_id: str,
        evaluation_time: datetime,
    ) -> OfficialSecuritySnapshot:
        snapshot = self._store.get_official_security(actor_id, security_id)
        if snapshot is None:
            raise ValueError("official_security_missing")
        if (
            snapshot.security_id != security_id
            or not snapshot.official_close.is_finite()
            or snapshot.official_close <= 0
            or not snapshot.price_source.strip()
            or not snapshot.official_industry.strip()
            or not snapshot.industry_source.strip()
            or snapshot.classification_effective_at.tzinfo is None
            or snapshot.theme_snapshot_version < 1
            or not snapshot.theme_source.strip()
            or snapshot.theme_effective_at.tzinfo is None
            or evaluation_time.tzinfo is None
            or snapshot.price_date > evaluation_time.date()
            or (evaluation_time.date() - snapshot.price_date).days > 7
        ):
            raise ValueError("official_security_invalid")
        return snapshot

    def _refresh_official_holdings(
        self,
        actor_id: str,
        holdings: tuple[HoldingSnapshot, ...],
        evaluation_time: datetime,
    ) -> tuple[HoldingSnapshot, ...]:
        facts: dict[str, OfficialSecuritySnapshot] = {}
        refreshed: list[HoldingSnapshot] = []
        for holding in holdings:
            fact = facts.setdefault(
                holding.security_id,
                self._official_security(actor_id, holding.security_id, evaluation_time),
            )
            refreshed.append(
                replace(
                    holding,
                    official_close=fact.official_close,
                    official_industry=fact.official_industry,
                    themes=fact.themes,
                    price_date=fact.price_date,
                    price_source=fact.price_source,
                    industry_source=fact.industry_source,
                    classification_effective_at=fact.classification_effective_at,
                    theme_snapshot_version=fact.theme_snapshot_version,
                    theme_source=fact.theme_source,
                    theme_effective_at=fact.theme_effective_at,
                )
            )
        return tuple(refreshed)

    @staticmethod
    def _sell_reduces_or_preserves_breaches(before, after) -> bool:
        for prefix, before_values, after_values in (
            (
                "security_cap_exceeded:",
                before.security_exposure,
                after.security_exposure,
            ),
            (
                "industry_cap_exceeded:",
                before.industry_exposure,
                after.industry_exposure,
            ),
            ("theme_cap_exceeded:", before.theme_exposure, after.theme_exposure),
        ):
            breached_after = {
                reason.removeprefix(prefix)
                for reason in after.reasons
                if reason.startswith(prefix)
            }
            for key in breached_after:
                if key not in before_values or after_values[key] > before_values[key]:
                    return False
        return True

    def confirm_trade(
        self, command: ConfirmTradeCommand, *, now: datetime
    ) -> PortfolioRecord:
        current = self.get(command.actor)
        if current.version != command.preview.expected_portfolio_version:
            raise ValueError("version_conflict")
        if not command.confirmation_id:
            raise PermissionError("confirmation_required")
        if (
            canonical_trade_fingerprint(command.preview.trade)
            != command.preview.fingerprint
        ):
            raise ValueError("preview_mismatch")
        if any(
            value.fingerprint == command.preview.fingerprint for value in current.trades
        ):
            raise ValueError("duplicate_trade")
        trade_record = TradeRecord(
            trade_id=self._trade_id_factory(),
            version=1,
            fingerprint=command.preview.fingerprint,
            trade=command.preview.trade,
            allocations=command.preview.allocations,
            confirmed_at=now,
            reason=_required(command.reason, "reason_required"),
        )
        changed = replace(
            current,
            version=current.version + 1,
            cash=command.preview.post_portfolio.cash,
            holdings=command.preview.post_portfolio.holdings,
            trades=current.trades + (trade_record,),
            updated_at=now,
        )
        return self._commit(command, changed, "trade_confirmed")

    def preview_correction(
        self,
        actor: PortfolioActorContext,
        *,
        expected_version: int,
        original_trade_id: str,
        now: datetime,
    ) -> TradeCorrectionPreview:
        current = self.get(actor)
        if current.version != expected_version:
            raise ValueError("version_conflict")
        if any(
            value.original_trade_id == original_trade_id
            for value in current.corrections
        ):
            raise ValueError("trade_already_corrected")
        original = next(
            (value for value in current.trades if value.trade_id == original_trade_id),
            None,
        )
        if original is None:
            raise LookupError("resource_unavailable")
        if current.trades[-1].trade_id != original_trade_id or any(
            value.confirmed_at >= original.confirmed_at
            for value in current.company_actions
        ):
            raise ValueError("correction_requires_reconciliation")
        holdings = list(
            self._refresh_official_holdings(actor.actor_id, current.holdings, now)
        )
        cash = current.cash
        notional = original.trade.price * Decimal(original.trade.quantity)
        if original.trade.side is TradeSide.BUY:
            cash += notional + original.trade.fees + original.trade.tax
        else:
            cash -= notional - original.trade.fees - original.trade.tax
            if cash < 0:
                raise ValueError("correction_cash_conflict")
        fact = self._official_security(actor.actor_id, original.trade.security_id, now)
        for allocation in original.allocations:
            delta = Decimal(allocation.quantity) * (
                Decimal(-1) if original.trade.side is TradeSide.BUY else Decimal(1)
            )
            index = next(
                (
                    index
                    for index, value in enumerate(holdings)
                    if value.bucket_id == allocation.bucket_id
                    and value.security_id == original.trade.security_id
                ),
                None,
            )
            if index is None:
                if delta < 0:
                    raise ValueError("correction_holding_conflict")
                holdings.append(
                    HoldingSnapshot(
                        allocation.bucket_id,
                        original.trade.security_id,
                        delta,
                        fact.official_close,
                        fact.official_industry,
                        fact.themes,
                        fact.price_date,
                        fact.price_source,
                        fact.industry_source,
                        fact.classification_effective_at,
                        fact.theme_snapshot_version,
                        fact.theme_source,
                        fact.theme_effective_at,
                    )
                )
            else:
                changed = holdings[index].quantity + delta
                if changed < 0:
                    raise ValueError("correction_holding_conflict")
                holdings[index] = replace(holdings[index], quantity=changed)
        post = PortfolioSnapshot(
            current.version + 1,
            cash,
            tuple(value for value in holdings if value.quantity > 0),
        )
        exposure = aggregate_exposure(post)
        digest = sha256(
            json.dumps(
                {
                    "expected_version": current.version,
                    "original_trade_id": original_trade_id,
                    "post_cash": str(cash),
                    "holdings": [asdict(value) for value in post.holdings],
                },
                default=_json_default,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return TradeCorrectionPreview(
            current.version, original_trade_id, digest, post, exposure
        )

    def confirm_correction(
        self,
        command: ConfirmTradeCorrectionCommand,
        *,
        now: datetime,
    ) -> PortfolioRecord:
        current = self.get(command.actor)
        if current.version != command.preview.expected_portfolio_version:
            raise ValueError("version_conflict")
        if not command.confirmation_id:
            raise PermissionError("confirmation_required")
        if any(
            value.original_trade_id == command.preview.original_trade_id
            for value in current.corrections
        ):
            raise ValueError("trade_already_corrected")
        original = next(
            (
                value
                for value in current.trades
                if value.trade_id == command.preview.original_trade_id
            ),
            None,
        )
        if original is None:
            raise LookupError("resource_unavailable")
        correction = TradeCorrectionRecord(
            self._correction_id_factory(),
            1,
            original.trade_id,
            original.allocations,
            now,
            _required(command.reason, "reason_required"),
        )
        changed = replace(
            current,
            version=current.version + 1,
            cash=command.preview.post_portfolio.cash,
            holdings=command.preview.post_portfolio.holdings,
            corrections=current.corrections + (correction,),
            updated_at=now,
        )
        return self._commit(command, changed, "trade_corrected")

    def preview_company_action(
        self,
        actor: PortfolioActorContext,
        *,
        expected_version: int,
        security_id: str,
        action_kind: str,
        confirmed_post_action_shares: int,
        cash_in_lieu: Decimal,
        now: datetime,
    ) -> CompanyActionPreview:
        current = self.get(actor)
        if current.version != expected_version:
            raise ValueError("version_conflict")
        if action_kind not in {"split", "capital_reduction", "stock_dividend"}:
            raise ValueError("invalid_company_action")
        holdings = list(
            self._refresh_official_holdings(actor.actor_id, current.holdings, now)
        )
        relevant = [value for value in holdings if value.security_id == security_id]
        if not relevant or any(
            value.quantity != value.quantity.to_integral_value() for value in relevant
        ):
            raise ValueError("invalid_company_action")
        pre = {value.bucket_id: int(value.quantity) for value in relevant}
        allocation = allocate_company_action(
            pre_action_quantities=pre,
            confirmed_post_action_shares=confirmed_post_action_shares,
            cash_in_lieu=cash_in_lieu,
        )
        for index, holding in enumerate(holdings):
            if holding.security_id == security_id:
                holdings[index] = replace(
                    holding, quantity=Decimal(allocation.shares[holding.bucket_id])
                )
        post = PortfolioSnapshot(
            current.version + 1,
            current.cash + cash_in_lieu,
            tuple(value for value in holdings if value.quantity > 0),
        )
        exposure = aggregate_exposure(post)
        digest = sha256(
            json.dumps(
                {
                    "expected_version": current.version,
                    "security_id": security_id,
                    "action_kind": action_kind,
                    "post_shares": confirmed_post_action_shares,
                    "cash_in_lieu": str(cash_in_lieu),
                    "allocation": asdict(allocation),
                },
                default=_json_default,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return CompanyActionPreview(
            current.version,
            security_id,
            action_kind,
            confirmed_post_action_shares,
            cash_in_lieu,
            allocation,
            digest,
            post,
            exposure,
        )

    def confirm_company_action(
        self,
        command: ConfirmCompanyActionCommand,
        *,
        now: datetime,
    ) -> PortfolioRecord:
        current = self.get(command.actor)
        if current.version != command.preview.expected_portfolio_version:
            raise ValueError("version_conflict")
        if not command.confirmation_id:
            raise PermissionError("confirmation_required")
        action = CompanyActionRecord(
            self._company_action_id_factory(),
            1,
            command.preview.security_id,
            command.preview.action_kind,
            sum(
                int(value.quantity)
                for value in current.holdings
                if value.security_id == command.preview.security_id
            ),
            command.preview.confirmed_post_action_shares,
            command.preview.cash_in_lieu,
            command.preview.allocation,
            now,
            _required(command.reason, "reason_required"),
        )
        changed = replace(
            current,
            version=current.version + 1,
            cash=command.preview.post_portfolio.cash,
            holdings=command.preview.post_portfolio.holdings,
            company_actions=current.company_actions + (action,),
            updated_at=now,
        )
        return self._commit(command, changed, "company_action_confirmed")

    def _commit(self, command, record: PortfolioRecord, action: str) -> PortfolioRecord:
        expected_version = (
            command.expected_version
            if hasattr(command, "expected_version")
            else command.preview.expected_portfolio_version
        )
        return self._store.commit(
            actor_id=command.actor.actor_id,
            idempotency_key=_required(command.idempotency_key),
            command_digest=_digest(command),
            expected_version=expected_version,
            record=record,
            action=action,
            reason=_required(command.reason, "reason_required"),
        )
