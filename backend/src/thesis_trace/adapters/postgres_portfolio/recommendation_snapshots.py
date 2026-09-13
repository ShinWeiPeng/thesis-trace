"""Private normalized mapping of Portfolio-owned, sealed analytical snapshots."""

from dataclasses import asdict
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

from thesis_trace.modules.portfolio.contracts import (
    CostProfileSnapshot,
    DcaSelection,
    ExposureSnapshot,
    HoldingSnapshot,
    OfficialSecuritySnapshot,
    PortfolioRecommendationSnapshot,
    PortfolioSnapshot,
)


def _tables() -> tuple[sa.Table, sa.Table, sa.Table]:
    metadata = sa.MetaData()
    header = sa.Table(
        "recommendation_snapshots",
        metadata,
        *(
            sa.Column(name, sa.Text)
            for name in (
                "owner_user_id",
                "snapshot_id",
                "cost_policy_version",
                "target_security_id",
                "target_price_source",
                "target_official_industry",
                "target_industry_source",
                "target_theme_source",
                "target_policy_version",
                "exposure_policy_version",
                "sizing_policy_version",
                "post_exposure_policy_version",
            )
        ),
        *(
            sa.Column(name, sa.Numeric)
            for name in (
                "cash",
                "base_amount",
                "buy_price",
                "cost_buy_rate",
                "cost_minimum_buy_fee",
                "cost_sell_rate",
                "cost_minimum_sell_fee",
                "cost_tax_rate",
                "target_official_close",
                "nav",
                "multiplier",
                "post_nav",
                "purchase_outflow",
                "acquired_quantity",
            )
        ),
        *(
            sa.Column(name, sa.Integer)
            for name in (
                "portfolio_version",
                "cost_version",
                "target_theme_snapshot_version",
                "holding_count",
                "exposure_count",
            )
        ),
        *(
            sa.Column(name, sa.DateTime(timezone=True))
            for name in (
                "cash_as_of",
                "created_at",
                "cost_effective_at",
                "target_classification_effective_at",
                "target_theme_effective_at",
            )
        ),
        *(
            sa.Column(name, ARRAY(sa.Text))
            for name in (
                "target_themes",
                "exposure_reasons",
                "sizing_reasons",
                "post_exposure_reasons",
            )
        ),
        sa.Column("target_price_date", sa.Date),
        sa.Column("feasible", sa.Boolean),
        sa.Column("post_feasible", sa.Boolean),
        sa.Column("evaluated", ARRAY(sa.Numeric)),
        schema="portfolio",
    )
    holdings = sa.Table(
        "recommendation_holdings",
        metadata,
        *(
            sa.Column(name, sa.Text)
            for name in (
                "owner_user_id",
                "snapshot_id",
                "bucket_id",
                "security_id",
                "official_industry",
                "price_source",
                "industry_source",
                "theme_source",
            )
        ),
        sa.Column("ordinal", sa.Integer),
        sa.Column("quantity", sa.Numeric),
        sa.Column("official_close", sa.Numeric),
        sa.Column("themes", ARRAY(sa.Text)),
        sa.Column("price_date", sa.Date),
        sa.Column("classification_effective_at", sa.DateTime(timezone=True)),
        sa.Column("theme_snapshot_version", sa.Integer),
        sa.Column("theme_effective_at", sa.DateTime(timezone=True)),
        schema="portfolio",
    )
    exposures = sa.Table(
        "recommendation_exposures",
        metadata,
        *(
            sa.Column(name, sa.Text)
            for name in ("owner_user_id", "snapshot_id", "kind", "exposure_key")
        ),
        sa.Column("ratio", sa.Numeric),
        schema="portfolio",
    )
    return header, holdings, exposures


def _append(
    connection: Any, actor_id: str, snapshot: PortfolioRecommendationSnapshot
) -> None:
    header, holdings, exposures = _tables()
    identity = dict(owner_user_id=actor_id, snapshot_id=snapshot.snapshot_id)
    exposure_rows = [
        dict(**identity, kind=kind, exposure_key=key, ratio=value)
        for kind, values in (
            ("security", snapshot.exposure.security_exposure),
            ("industry", snapshot.exposure.industry_exposure),
            ("theme", snapshot.exposure.theme_exposure),
        )
        for key, value in sorted(values.items())
    ]
    projected = snapshot.sizing.post_exposure
    if projected is not None:
        exposure_rows.extend(
            dict(**identity, kind=kind, exposure_key=key, ratio=value)
            for kind, values in (
                ("post_security", projected.security_exposure),
                ("post_industry", projected.industry_exposure),
                ("post_theme", projected.theme_exposure),
            )
            for key, value in sorted(values.items())
        )
    connection.execute(
        header.insert().values(
            **identity,
            portfolio_version=snapshot.portfolio.version,
            cash=snapshot.portfolio.cash,
            cash_as_of=snapshot.cash_as_of,
            created_at=snapshot.created_at,
            base_amount=snapshot.base_amount,
            buy_price=snapshot.buy_price,
            **{f"cost_{key}": value for key, value in asdict(snapshot.cost).items()},
            **{
                f"target_{key}": value for key, value in asdict(snapshot.target).items()
            },
            nav=snapshot.exposure.nav,
            feasible=snapshot.exposure.feasible,
            exposure_reasons=list(snapshot.exposure.reasons),
            exposure_policy_version=snapshot.exposure.policy_version,
            multiplier=snapshot.sizing.multiplier,
            sizing_reasons=list(snapshot.sizing.reasons),
            evaluated=list(snapshot.sizing.evaluated),
            sizing_policy_version=snapshot.sizing.policy_version,
            post_nav=None if projected is None else projected.nav,
            post_feasible=None if projected is None else projected.feasible,
            post_exposure_reasons=None
            if projected is None
            else list(projected.reasons),
            post_exposure_policy_version=None
            if projected is None
            else projected.policy_version,
            purchase_outflow=snapshot.sizing.purchase_outflow,
            acquired_quantity=snapshot.sizing.acquired_quantity,
            holding_count=len(snapshot.portfolio.holdings),
            exposure_count=len(exposure_rows),
        )
    )
    for ordinal, holding in enumerate(snapshot.portfolio.holdings):
        connection.execute(
            holdings.insert().values(**identity, ordinal=ordinal, **asdict(holding))
        )
    for row in exposure_rows:
        connection.execute(exposures.insert().values(**row))


def _get(
    connection: Any, actor_id: str, snapshot_id: str
) -> PortfolioRecommendationSnapshot | None:
    header, holdings, exposures = _tables()
    row = (
        connection.execute(
            sa.select(header).where(
                header.c.owner_user_id == actor_id, header.c.snapshot_id == snapshot_id
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    holding_values = tuple(
        HoldingSnapshot(
            **{
                key: tuple(value) if key == "themes" else value
                for key, value in item.items()
                if key not in ("owner_user_id", "snapshot_id", "ordinal")
            }
        )
        for item in connection.execute(
            sa.select(holdings)
            .where(
                holdings.c.owner_user_id == actor_id,
                holdings.c.snapshot_id == snapshot_id,
            )
            .order_by(holdings.c.ordinal)
        ).mappings()
    )
    ratios = {
        kind: {}
        for kind in (
            "security",
            "industry",
            "theme",
            "post_security",
            "post_industry",
            "post_theme",
        )
    }
    for item in connection.execute(
        sa.select(exposures).where(
            exposures.c.owner_user_id == actor_id,
            exposures.c.snapshot_id == snapshot_id,
        )
    ).mappings():
        ratios[item["kind"]][item["exposure_key"]] = item["ratio"]
    if (
        len(holding_values) != row["holding_count"]
        or sum(len(values) for values in ratios.values()) != row["exposure_count"]
    ):
        raise ValueError("recommendation_snapshot_incomplete")
    return PortfolioRecommendationSnapshot(
        snapshot_id,
        PortfolioSnapshot(row["portfolio_version"], row["cash"], holding_values),
        CostProfileSnapshot(
            **{
                key.removeprefix("cost_"): value
                for key, value in row.items()
                if key.startswith("cost_")
            }
        ),
        ExposureSnapshot(
            row["nav"],
            ratios["security"],
            ratios["industry"],
            ratios["theme"],
            row["feasible"],
            tuple(row["exposure_reasons"]),
            row["exposure_policy_version"],
        ),
        DcaSelection(
            row["multiplier"],
            tuple(row["sizing_reasons"]),
            tuple(row["evaluated"]),
            row["sizing_policy_version"],
            None
            if row["post_nav"] is None
            else ExposureSnapshot(
                row["post_nav"],
                ratios["post_security"],
                ratios["post_industry"],
                ratios["post_theme"],
                row["post_feasible"],
                tuple(row["post_exposure_reasons"]),
                row["post_exposure_policy_version"],
            ),
            row["purchase_outflow"],
            row["acquired_quantity"],
        ),
        row["created_at"],
        OfficialSecuritySnapshot(
            **{
                key.removeprefix("target_"): tuple(value)
                if key == "target_themes"
                else value
                for key, value in row.items()
                if key.startswith("target_")
            }
        ),
        row["base_amount"],
        row["buy_price"],
        row["cash_as_of"],
    )
