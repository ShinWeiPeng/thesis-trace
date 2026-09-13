from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_portfolio_persistence_uses_normalized_tables_without_process_global_binding() -> None:
    source = (ROOT / "src/thesis_trace/adapters/postgres_portfolio/adapter.py").read_text()

    assert "ContextVar" not in source
    assert "portfolio.portfolios" not in source
    assert "portfolio.record_versions" not in source
    assert "portfolio.current_state" in source
    assert "portfolio.trades" in source
    assert "create_database_engine" in source
    assert '"""SELECT' not in source
    assert '"""INSERT' not in source


def test_normalized_portfolio_schema_is_owned_by_alembic() -> None:
    migration = (
        ROOT.parent / "infra/postgres/alembic/versions/0015_normalized_thesis_portfolio.py"
    ).read_text()

    assert '"current_state"' in migration
    assert '"trade_corrections"' in migration
    assert '"company_actions"' in migration
    assert "official_close" in migration
    assert "portfolio_current_state_cash_nonnegative" in migration
    assert "portfolio_correction_original_trade_fk" in migration
    assert 'op.drop_table("portfolios", schema="portfolio")' in migration
    assert "NO FORCE ROW LEVEL SECURITY" in migration
    assert "ENABLE TRIGGER" in migration
