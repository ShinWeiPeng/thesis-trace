from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
import hashlib
import uuid
from typing import Any, Callable, Iterator, Protocol

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, insert as pg_insert

from thesis_trace.modules.portfolio.contracts import (
    CanonicalTrade,
    CompanyActionAllocation,
    CompanyActionRecord,
    CostProfileSnapshot,
    HoldingSnapshot,
    OfficialSecuritySnapshot,
    PortfolioRecord,
    TradeAllocation,
    TradeCorrectionRecord,
    TradeRecord,
    TradeSide,
)
from thesis_trace.platform.database import DatabaseUrlProvider, create_database_engine, database_connection


_METADATA = sa.MetaData()
_CURRENT_STATE = sa.Table(
    "current_state", _METADATA,
    sa.Column("owner_user_id", sa.Text, primary_key=True), sa.Column("version", sa.Integer),
    sa.Column("cash", sa.Numeric), sa.Column("cash_as_of", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)), schema="portfolio",
)
_HOLDINGS = sa.Table(
    "holdings", _METADATA,
    sa.Column("owner_user_id", sa.Text, primary_key=True), sa.Column("bucket_id", sa.Text, primary_key=True),
    sa.Column("security_id", sa.Text, primary_key=True), sa.Column("quantity", sa.Numeric),
    sa.Column("official_close", sa.Numeric), sa.Column("official_industry", sa.Text),
    sa.Column("themes", ARRAY(sa.Text)), sa.Column("price_date", sa.Date),
    sa.Column("price_source", sa.Text), sa.Column("industry_source", sa.Text),
    sa.Column("classification_effective_at", sa.DateTime(timezone=True)),
    sa.Column("theme_snapshot_version", sa.Integer), sa.Column("theme_source", sa.Text),
    sa.Column("theme_effective_at", sa.DateTime(timezone=True)), schema="portfolio",
)
_OFFICIAL_SECURITIES = sa.Table(
    "official_security_snapshots", _METADATA,
    sa.Column("owner_user_id", sa.Text, primary_key=True), sa.Column("security_id", sa.Text, primary_key=True),
    sa.Column("official_close", sa.Numeric), sa.Column("price_date", sa.Date),
    sa.Column("price_source", sa.Text), sa.Column("official_industry", sa.Text),
    sa.Column("industry_source", sa.Text), sa.Column("classification_effective_at", sa.DateTime(timezone=True)),
    sa.Column("themes", ARRAY(sa.Text)), sa.Column("theme_snapshot_version", sa.Integer),
    sa.Column("theme_source", sa.Text), sa.Column("theme_effective_at", sa.DateTime(timezone=True)),
    sa.Column("policy_version", sa.Text), schema="portfolio",
)
_COST_PROFILES = sa.Table(
    "cost_profiles", _METADATA,
    sa.Column("owner_user_id", sa.Text), sa.Column("version", sa.Integer),
    sa.Column("buy_rate", sa.Numeric), sa.Column("minimum_buy_fee", sa.Numeric),
    sa.Column("sell_rate", sa.Numeric), sa.Column("minimum_sell_fee", sa.Numeric),
    sa.Column("tax_rate", sa.Numeric), sa.Column("effective_at", sa.DateTime(timezone=True)),
    sa.Column("policy_version", sa.Text), schema="portfolio",
)
_CASH_VERSIONS = sa.Table(
    "investable_cash_versions", _METADATA,
    sa.Column("owner_user_id", sa.Text), sa.Column("portfolio_version", sa.Integer),
    sa.Column("cash", sa.Numeric), sa.Column("as_of", sa.DateTime(timezone=True)),
    sa.Column("recorded_at", sa.DateTime(timezone=True)), schema="portfolio",
)
_TRADES = sa.Table(
    "trades", _METADATA,
    sa.Column("owner_user_id", sa.Text), sa.Column("trade_id", sa.Text),
    sa.Column("version", sa.Integer), sa.Column("fingerprint", sa.Text),
    sa.Column("source_kind", sa.Text), sa.Column("source_row_id", sa.Text),
    sa.Column("broker_reference", sa.Text), sa.Column("security_id", sa.Text),
    sa.Column("side", sa.Text), sa.Column("quantity", sa.Integer),
    sa.Column("price", sa.Numeric), sa.Column("fees", sa.Numeric), sa.Column("tax", sa.Numeric),
    sa.Column("executed_at", sa.DateTime(timezone=True)),
    sa.Column("confirmed_at", sa.DateTime(timezone=True)), sa.Column("reason", sa.Text),
    sa.Column("policy_version", sa.Text), schema="portfolio",
)
_TRADE_ALLOCATIONS = sa.Table(
    "trade_allocations", _METADATA,
    sa.Column("owner_user_id", sa.Text), sa.Column("trade_id", sa.Text),
    sa.Column("trade_version", sa.Integer), sa.Column("bucket_id", sa.Text),
    sa.Column("quantity", sa.Integer), schema="portfolio",
)
_CORRECTIONS = sa.Table(
    "trade_corrections", _METADATA,
    sa.Column("owner_user_id", sa.Text), sa.Column("correction_id", sa.Text),
    sa.Column("version", sa.Integer), sa.Column("original_trade_id", sa.Text),
    sa.Column("original_trade_version", sa.Integer),
    sa.Column("confirmed_at", sa.DateTime(timezone=True)), sa.Column("reason", sa.Text),
    sa.Column("policy_version", sa.Text), schema="portfolio",
)
_CORRECTION_ALLOCATIONS = sa.Table(
    "correction_allocations", _METADATA,
    sa.Column("owner_user_id", sa.Text), sa.Column("correction_id", sa.Text),
    sa.Column("correction_version", sa.Integer), sa.Column("bucket_id", sa.Text),
    sa.Column("quantity", sa.Integer), schema="portfolio",
)
_COMPANY_ACTIONS = sa.Table(
    "company_actions", _METADATA,
    sa.Column("owner_user_id", sa.Text), sa.Column("action_id", sa.Text),
    sa.Column("version", sa.Integer), sa.Column("security_id", sa.Text),
    sa.Column("action_kind", sa.Text), sa.Column("pre_action_shares", sa.Integer),
    sa.Column("confirmed_post_action_shares", sa.Integer), sa.Column("cash_in_lieu", sa.Numeric),
    sa.Column("remainder_order", ARRAY(sa.Text)), sa.Column("allocation_policy_version", sa.Text),
    sa.Column("confirmed_at", sa.DateTime(timezone=True)), sa.Column("reason", sa.Text),
    sa.Column("policy_version", sa.Text), schema="portfolio",
)
_COMPANY_ACTION_ALLOCATIONS = sa.Table(
    "company_action_allocations", _METADATA,
    sa.Column("owner_user_id", sa.Text), sa.Column("action_id", sa.Text),
    sa.Column("action_version", sa.Integer), sa.Column("bucket_id", sa.Text),
    sa.Column("shares", sa.Integer), sa.Column("cash", sa.Numeric), schema="portfolio",
)
_VERSION_HISTORY = sa.Table(
    "version_history", _METADATA,
    sa.Column("owner_user_id", sa.Text), sa.Column("version", sa.Integer),
    sa.Column("action", sa.Text), sa.Column("recorded_at", sa.DateTime(timezone=True)),
    schema="portfolio",
)
_AUDIT_EVENTS = sa.Table(
    "audit_events", _METADATA,
    sa.Column("event_id", sa.Uuid), sa.Column("owner_user_id", sa.Text),
    sa.Column("portfolio_version", sa.Integer), sa.Column("action", sa.Text),
    sa.Column("reason", sa.Text), sa.Column("occurred_at", sa.DateTime(timezone=True)),
    sa.Column("before_version", sa.Integer), sa.Column("after_version", sa.Integer),
    sa.Column("correlation_id", sa.Text), sa.Column("causation_id", sa.Text),
    sa.Column("policy_version", sa.Text), sa.Column("build_version", sa.Text), schema="portfolio",
)
_COMMAND_RECEIPTS = sa.Table(
    "command_receipts", _METADATA,
    sa.Column("actor_user_id", sa.Text), sa.Column("idempotency_key", sa.Text),
    sa.Column("command_digest", sa.Text), sa.Column("portfolio_version", sa.Integer),
    schema="portfolio",
)


class _SecurityContext(Protocol):
    user_id: str
    role: Any
    ownership_scope: str


class _Connection:
    """Small SQLAlchemy/driver bridge for a caller-owned atomic transaction."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def execute(self, statement: Any, parameters: tuple[Any, ...] | None = None) -> Any:
        if isinstance(statement, str):
            return self._connection.exec_driver_sql(statement, parameters or ())
        return self._connection.execute(statement)


class PostgresPortfolioStore:
    """SQLAlchemy-backed normalized Portfolio repository with append-only history."""

    def __init__(
        self,
        database_url_provider: DatabaseUrlProvider,
        *,
        security_context_provider: Callable[[], _SecurityContext | None],
        transaction_connection: Any | None = None,
        build_version: str = "test-build",
    ) -> None:
        self._database_url_provider = database_url_provider
        self._security_context_provider = security_context_provider
        self._transaction_connection = transaction_connection
        self._build_version = build_version
        self._engine = create_database_engine(database_url_provider) if transaction_connection is None else None

    @contextmanager
    def _connection(self) -> Iterator[_Connection]:
        context = self._security_context_provider()
        if context is None:
            raise PermissionError("missing_security_context")
        if self._transaction_connection is not None:
            yield _Connection(self._transaction_connection)
            return
        assert self._engine is not None
        with database_connection(self._engine) as raw_connection:
            connection = _Connection(raw_connection)
            connection.execute("SELECT set_config('app.user_id',%s,true)", (context.user_id,))
            connection.execute("SELECT set_config('app.role',%s,true)", (context.role.value,))
            connection.execute("SELECT set_config('app.request_id',%s,true)", (context.ownership_scope,))
            yield connection

    def for_transaction(self, connection: Any) -> PostgresPortfolioStore:
        """Return an immutable request-scoped binding to the caller-owned transaction."""
        return PostgresPortfolioStore(
            self._database_url_provider,
            security_context_provider=self._security_context_provider,
            transaction_connection=connection,
            build_version=self._build_version,
        )

    @staticmethod
    def _lock_key(value: str) -> int:
        return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big", signed=True)

    @staticmethod
    def _load(connection: _Connection, actor_id: str, *, for_share: bool = False) -> PortfolioRecord | None:
        current_query = sa.select(
            _CURRENT_STATE.c.version, _CURRENT_STATE.c.cash, _CURRENT_STATE.c.cash_as_of,
            _CURRENT_STATE.c.updated_at,
        ).where(_CURRENT_STATE.c.owner_user_id == actor_id)
        current = connection.execute(current_query.with_for_update(read=True) if for_share else current_query).fetchone()
        if current is None:
            return None
        profile_row = connection.execute(sa.select(
            _COST_PROFILES.c.version, _COST_PROFILES.c.buy_rate,
            _COST_PROFILES.c.minimum_buy_fee, _COST_PROFILES.c.sell_rate,
            _COST_PROFILES.c.minimum_sell_fee, _COST_PROFILES.c.tax_rate,
            _COST_PROFILES.c.effective_at, _COST_PROFILES.c.policy_version,
        ).where(_COST_PROFILES.c.owner_user_id == actor_id).order_by(
            _COST_PROFILES.c.version.desc(),
        ).limit(1)).fetchone()
        profile = None if profile_row is None else CostProfileSnapshot(
            int(profile_row[0]), Decimal(profile_row[1]), Decimal(profile_row[2]),
            Decimal(profile_row[3]), Decimal(profile_row[4]), Decimal(profile_row[5]),
            profile_row[6], str(profile_row[7]),
        )
        holdings = tuple(
            HoldingSnapshot(
                str(row[0]), str(row[1]), Decimal(row[2]), Decimal(row[3]), str(row[4]),
                tuple(row[5]), row[6], str(row[7]), str(row[8]), row[9], int(row[10]),
                str(row[11]), row[12],
            )
            for row in connection.execute(sa.select(
                _HOLDINGS.c.bucket_id, _HOLDINGS.c.security_id, _HOLDINGS.c.quantity,
                _HOLDINGS.c.official_close, _HOLDINGS.c.official_industry, _HOLDINGS.c.themes,
                _HOLDINGS.c.price_date, _HOLDINGS.c.price_source, _HOLDINGS.c.industry_source,
                _HOLDINGS.c.classification_effective_at, _HOLDINGS.c.theme_snapshot_version,
                _HOLDINGS.c.theme_source, _HOLDINGS.c.theme_effective_at,
            ).where(_HOLDINGS.c.owner_user_id == actor_id).order_by(
                _HOLDINGS.c.bucket_id, _HOLDINGS.c.security_id,
            )).fetchall()
        )
        trades = []
        for row in connection.execute(sa.select(
            _TRADES.c.trade_id, _TRADES.c.version, _TRADES.c.fingerprint,
            _TRADES.c.source_kind, _TRADES.c.source_row_id, _TRADES.c.broker_reference,
            _TRADES.c.security_id, _TRADES.c.side, _TRADES.c.quantity, _TRADES.c.price,
            _TRADES.c.fees, _TRADES.c.tax, _TRADES.c.executed_at, _TRADES.c.confirmed_at,
            _TRADES.c.reason, _TRADES.c.policy_version,
        ).where(_TRADES.c.owner_user_id == actor_id).order_by(
            _TRADES.c.version, _TRADES.c.trade_id,
        )).fetchall():
            allocations = tuple(
                TradeAllocation(str(item[0]), int(item[1]))
                for item in connection.execute(sa.select(
                    _TRADE_ALLOCATIONS.c.bucket_id, _TRADE_ALLOCATIONS.c.quantity,
                ).where(
                    _TRADE_ALLOCATIONS.c.owner_user_id == actor_id,
                    _TRADE_ALLOCATIONS.c.trade_id == row[0],
                    _TRADE_ALLOCATIONS.c.trade_version == row[1],
                ).order_by(_TRADE_ALLOCATIONS.c.bucket_id)).fetchall()
            )
            trade = CanonicalTrade(
                str(row[3]), str(row[4]), None if row[5] is None else str(row[5]), str(row[6]),
                TradeSide(str(row[7])), int(row[8]), Decimal(row[9]), Decimal(row[10]),
                Decimal(row[11]), row[12],
            )
            trades.append(TradeRecord(
                str(row[0]), int(row[1]), str(row[2]), trade, allocations, row[13],
                str(row[14]), str(row[15]),
            ))
        corrections = []
        for row in connection.execute(sa.select(
            _CORRECTIONS.c.correction_id, _CORRECTIONS.c.version,
            _CORRECTIONS.c.original_trade_id, _CORRECTIONS.c.confirmed_at,
            _CORRECTIONS.c.reason, _CORRECTIONS.c.policy_version,
        ).where(_CORRECTIONS.c.owner_user_id == actor_id).order_by(
            _CORRECTIONS.c.version, _CORRECTIONS.c.correction_id,
        )).fetchall():
            allocations = tuple(
                TradeAllocation(str(item[0]), int(item[1]))
                for item in connection.execute(sa.select(
                    _CORRECTION_ALLOCATIONS.c.bucket_id, _CORRECTION_ALLOCATIONS.c.quantity,
                ).where(
                    _CORRECTION_ALLOCATIONS.c.owner_user_id == actor_id,
                    _CORRECTION_ALLOCATIONS.c.correction_id == row[0],
                    _CORRECTION_ALLOCATIONS.c.correction_version == row[1],
                ).order_by(_CORRECTION_ALLOCATIONS.c.bucket_id)).fetchall()
            )
            corrections.append(TradeCorrectionRecord(
                str(row[0]), int(row[1]), str(row[2]), allocations, row[3], str(row[4]), str(row[5]),
            ))
        company_actions = []
        for row in connection.execute(sa.select(
            _COMPANY_ACTIONS.c.action_id, _COMPANY_ACTIONS.c.version,
            _COMPANY_ACTIONS.c.security_id, _COMPANY_ACTIONS.c.action_kind,
            _COMPANY_ACTIONS.c.pre_action_shares,
            _COMPANY_ACTIONS.c.confirmed_post_action_shares,
            _COMPANY_ACTIONS.c.cash_in_lieu, _COMPANY_ACTIONS.c.remainder_order,
            _COMPANY_ACTIONS.c.allocation_policy_version, _COMPANY_ACTIONS.c.confirmed_at,
            _COMPANY_ACTIONS.c.reason, _COMPANY_ACTIONS.c.policy_version,
        ).where(_COMPANY_ACTIONS.c.owner_user_id == actor_id).order_by(
            _COMPANY_ACTIONS.c.version, _COMPANY_ACTIONS.c.action_id,
        )).fetchall():
            allocation_rows = connection.execute(sa.select(
                _COMPANY_ACTION_ALLOCATIONS.c.bucket_id,
                _COMPANY_ACTION_ALLOCATIONS.c.shares,
                _COMPANY_ACTION_ALLOCATIONS.c.cash,
            ).where(
                _COMPANY_ACTION_ALLOCATIONS.c.owner_user_id == actor_id,
                _COMPANY_ACTION_ALLOCATIONS.c.action_id == row[0],
                _COMPANY_ACTION_ALLOCATIONS.c.action_version == row[1],
            ).order_by(_COMPANY_ACTION_ALLOCATIONS.c.bucket_id)).fetchall()
            allocation = CompanyActionAllocation(
                {str(item[0]): int(item[1]) for item in allocation_rows},
                {str(item[0]): Decimal(item[2]) for item in allocation_rows},
                tuple(row[7]),
                str(row[8]),
            )
            company_actions.append(CompanyActionRecord(
                str(row[0]), int(row[1]), str(row[2]), str(row[3]), int(row[4]), int(row[5]),
                Decimal(row[6]), allocation, row[9], str(row[10]), str(row[11]),
            ))
        return PortfolioRecord(
            actor_id, int(current[0]), profile, Decimal(current[1]), current[2], holdings,
            tuple(trades), current[3], tuple(corrections), tuple(company_actions),
        )

    def get(self, actor_id: str) -> PortfolioRecord | None:
        with self._connection() as connection:
            return self._load(connection, actor_id)

    def get_for_validation(self, actor_id: str) -> PortfolioRecord | None:
        with self._connection() as connection:
            return self._load(connection, actor_id, for_share=True)

    def get_official_security(self, actor_id: str, security_id: str) -> OfficialSecuritySnapshot | None:
        with self._connection() as connection:
            row = connection.execute(sa.select(
                _OFFICIAL_SECURITIES.c.official_close, _OFFICIAL_SECURITIES.c.price_date,
                _OFFICIAL_SECURITIES.c.price_source, _OFFICIAL_SECURITIES.c.official_industry,
                _OFFICIAL_SECURITIES.c.industry_source,
                _OFFICIAL_SECURITIES.c.classification_effective_at, _OFFICIAL_SECURITIES.c.themes,
                _OFFICIAL_SECURITIES.c.theme_snapshot_version, _OFFICIAL_SECURITIES.c.theme_source,
                _OFFICIAL_SECURITIES.c.theme_effective_at, _OFFICIAL_SECURITIES.c.policy_version,
            ).where(
                _OFFICIAL_SECURITIES.c.owner_user_id == actor_id,
                _OFFICIAL_SECURITIES.c.security_id == security_id,
            )).fetchone()
        if row is None:
            return None
        return OfficialSecuritySnapshot(
            security_id, Decimal(row[0]), row[1], str(row[2]), str(row[3]), str(row[4]),
            row[5], tuple(row[6]), int(row[7]), str(row[8]), row[9], str(row[10]),
        )

    def save_official_security(self, actor_id: str, snapshot: OfficialSecuritySnapshot) -> None:
        """Persist a server-ingested official market/classification snapshot."""
        with self._connection() as connection:
            values = {
                "owner_user_id": actor_id, "security_id": snapshot.security_id,
                "official_close": snapshot.official_close, "price_date": snapshot.price_date,
                "price_source": snapshot.price_source, "official_industry": snapshot.official_industry,
                "industry_source": snapshot.industry_source,
                "classification_effective_at": snapshot.classification_effective_at,
                "themes": list(snapshot.themes), "theme_snapshot_version": snapshot.theme_snapshot_version,
                "theme_source": snapshot.theme_source, "theme_effective_at": snapshot.theme_effective_at,
                "policy_version": snapshot.policy_version,
            }
            statement = pg_insert(_OFFICIAL_SECURITIES).values(**values)
            connection.execute(statement.on_conflict_do_update(
                index_elements=[_OFFICIAL_SECURITIES.c.owner_user_id, _OFFICIAL_SECURITIES.c.security_id],
                set_={key: getattr(statement.excluded, key) for key in values if key not in {"owner_user_id", "security_id"}},
            ))

    def save_official_security_for_test(self, actor_id: str, snapshot: OfficialSecuritySnapshot) -> None:
        self.save_official_security(actor_id, snapshot)

    @staticmethod
    def _insert_history(connection: _Connection, actor_id: str, record: PortfolioRecord) -> None:
        if record.cost_profile is not None:
            value = record.cost_profile
            connection.execute(pg_insert(_COST_PROFILES).values(
                owner_user_id=actor_id, version=value.version, buy_rate=value.buy_rate,
                minimum_buy_fee=value.minimum_buy_fee, sell_rate=value.sell_rate,
                minimum_sell_fee=value.minimum_sell_fee, tax_rate=value.tax_rate,
                effective_at=value.effective_at, policy_version=value.policy_version,
            ).on_conflict_do_nothing())
        connection.execute(pg_insert(_CASH_VERSIONS).values(
            owner_user_id=actor_id, portfolio_version=record.version, cash=record.cash,
            as_of=record.cash_as_of, recorded_at=record.updated_at,
        ).on_conflict_do_nothing())
        for value in record.trades:
            connection.execute(pg_insert(_TRADES).values(
                owner_user_id=actor_id, trade_id=value.trade_id, version=value.version,
                fingerprint=value.fingerprint, source_kind=value.trade.source_kind,
                source_row_id=value.trade.source_row_id,
                broker_reference=value.trade.broker_reference,
                security_id=value.trade.security_id, side=value.trade.side.value,
                quantity=value.trade.quantity, price=value.trade.price, fees=value.trade.fees,
                tax=value.trade.tax, executed_at=value.trade.executed_at,
                confirmed_at=value.confirmed_at, reason=value.reason,
                policy_version=value.policy_version,
            ).on_conflict_do_nothing())
            for allocation in value.allocations:
                connection.execute(pg_insert(_TRADE_ALLOCATIONS).values(
                    owner_user_id=actor_id, trade_id=value.trade_id,
                    trade_version=value.version, bucket_id=allocation.bucket_id,
                    quantity=allocation.quantity,
                ).on_conflict_do_nothing())
        for value in record.corrections:
            original_trade_version = max(
                trade.version for trade in record.trades
                if trade.trade_id == value.original_trade_id
            )
            connection.execute(pg_insert(_CORRECTIONS).values(
                owner_user_id=actor_id, correction_id=value.correction_id,
                version=value.version, original_trade_id=value.original_trade_id,
                original_trade_version=original_trade_version, confirmed_at=value.confirmed_at,
                reason=value.reason, policy_version=value.policy_version,
            ).on_conflict_do_nothing())
            for allocation in value.reversed_allocations:
                connection.execute(pg_insert(_CORRECTION_ALLOCATIONS).values(
                    owner_user_id=actor_id, correction_id=value.correction_id,
                    correction_version=value.version, bucket_id=allocation.bucket_id,
                    quantity=allocation.quantity,
                ).on_conflict_do_nothing())
        for value in record.company_actions:
            connection.execute(pg_insert(_COMPANY_ACTIONS).values(
                owner_user_id=actor_id, action_id=value.action_id, version=value.version,
                security_id=value.security_id, action_kind=value.action_kind,
                pre_action_shares=value.pre_action_shares,
                confirmed_post_action_shares=value.confirmed_post_action_shares,
                cash_in_lieu=value.cash_in_lieu,
                remainder_order=list(value.allocation.remainder_order),
                allocation_policy_version=value.allocation.policy_version,
                confirmed_at=value.confirmed_at, reason=value.reason,
                policy_version=value.policy_version,
            ).on_conflict_do_nothing())
            for bucket_id in set(value.allocation.shares) | set(value.allocation.cash):
                connection.execute(pg_insert(_COMPANY_ACTION_ALLOCATIONS).values(
                    owner_user_id=actor_id, action_id=value.action_id,
                    action_version=value.version, bucket_id=bucket_id,
                    shares=value.allocation.shares.get(bucket_id, 0),
                    cash=value.allocation.cash.get(bucket_id, Decimal(0)),
                ).on_conflict_do_nothing())

    def commit(
        self,
        *,
        actor_id: str,
        idempotency_key: str,
        command_digest: str,
        expected_version: int,
        record: PortfolioRecord,
        action: str,
        reason: str,
    ) -> PortfolioRecord:
        context = self._security_context_provider()
        if context is None or context.user_id != actor_id or record.owner_user_id != actor_id:
            raise PermissionError("resource_unavailable")
        with self._connection() as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                (self._lock_key(f"{actor_id}:{idempotency_key}"),),
            )
            receipt = connection.execute(sa.select(
                _COMMAND_RECEIPTS.c.command_digest,
            ).where(
                _COMMAND_RECEIPTS.c.actor_user_id == actor_id,
                _COMMAND_RECEIPTS.c.idempotency_key == idempotency_key,
            )).fetchone()
            if receipt is not None:
                if receipt[0] != command_digest:
                    raise ValueError("idempotency_conflict")
                replay = self._load(connection, actor_id)
                if replay is None:
                    raise LookupError("resource_unavailable")
                return replay
            current = connection.execute(sa.select(_CURRENT_STATE.c.version).where(
                _CURRENT_STATE.c.owner_user_id == actor_id,
            ).with_for_update()).fetchone()
            current_version = 0 if current is None else int(current[0])
            if current_version != expected_version:
                raise ValueError("version_conflict")
            current_insert = pg_insert(_CURRENT_STATE).values(
                owner_user_id=actor_id, version=record.version, cash=record.cash,
                cash_as_of=record.cash_as_of, updated_at=record.updated_at,
            )
            connection.execute(current_insert.on_conflict_do_update(
                index_elements=[_CURRENT_STATE.c.owner_user_id],
                set_={"version": current_insert.excluded.version, "cash": current_insert.excluded.cash,
                      "cash_as_of": current_insert.excluded.cash_as_of,
                      "updated_at": current_insert.excluded.updated_at},
            ))
            connection.execute(sa.delete(_HOLDINGS).where(_HOLDINGS.c.owner_user_id == actor_id))
            for value in record.holdings:
                connection.execute(sa.insert(_HOLDINGS).values(
                    owner_user_id=actor_id, bucket_id=value.bucket_id, security_id=value.security_id,
                    quantity=value.quantity, official_close=value.official_close,
                    official_industry=value.official_industry, themes=list(value.themes),
                    price_date=value.price_date, price_source=value.price_source,
                    industry_source=value.industry_source,
                    classification_effective_at=value.classification_effective_at,
                    theme_snapshot_version=value.theme_snapshot_version, theme_source=value.theme_source,
                    theme_effective_at=value.theme_effective_at,
                ))
            self._insert_history(connection, actor_id, record)
            connection.execute(sa.insert(_VERSION_HISTORY).values(
                owner_user_id=actor_id, version=record.version, action=action,
                recorded_at=record.updated_at,
            ))
            connection.execute(sa.insert(_AUDIT_EVENTS).values(
                event_id=uuid.uuid4(), owner_user_id=actor_id,
                portfolio_version=record.version, action=action, reason=reason,
                occurred_at=record.updated_at, before_version=expected_version,
                after_version=record.version, correlation_id=idempotency_key,
                causation_id=command_digest, policy_version="portfolio-record-v1",
                build_version=self._build_version,
            ))
            connection.execute(sa.insert(_COMMAND_RECEIPTS).values(
                actor_user_id=actor_id, idempotency_key=idempotency_key,
                command_digest=command_digest, portfolio_version=record.version,
            ))
            return record

    def delete_all_for_test(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """TRUNCATE portfolio.command_receipts,portfolio.audit_events,
                portfolio.company_action_allocations,portfolio.company_actions,
                portfolio.correction_allocations,portfolio.trade_corrections,
                portfolio.trade_allocations,portfolio.trades,portfolio.holdings,
                portfolio.investable_cash_versions,portfolio.cost_profiles,
                portfolio.version_history,portfolio.current_state,
                portfolio.official_security_snapshots"""
            )

    def count_versions(self, actor_id: str) -> int:
        with self._connection() as connection:
            return int(connection.execute(
                sa.select(sa.func.count()).select_from(_VERSION_HISTORY).where(
                    _VERSION_HISTORY.c.owner_user_id == actor_id,
                ),
            ).fetchone()[0])
