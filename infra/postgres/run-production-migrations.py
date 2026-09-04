"""One-shot production migration entrypoint; never used by API or collector roles."""
import psycopg
from psycopg import sql

from thesis_trace.platform.postgres import bootstrap_schema
from thesis_trace.platform.runtime import required_secret_provider


def apply_runtime_grants(connection: psycopg.Connection) -> None:
    database_name = connection.execute("SELECT current_database()").fetchone()[0]
    connection.execute(
        sql.SQL("REVOKE CREATE,TEMP ON DATABASE {} FROM thesis_trace_api,thesis_trace_collector,thesis_trace_ai_worker")
        .format(sql.Identifier(database_name))
    )
    connection.execute("REVOKE ALL PRIVILEGES ON SCHEMA access,research,workflow,thesis,portfolio,platform,public FROM thesis_trace_api,thesis_trace_collector,thesis_trace_ai_worker")
    connection.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA access,research,workflow,thesis,portfolio,platform FROM thesis_trace_api,thesis_trace_collector,thesis_trace_ai_worker")
    connection.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA access,research,workflow,thesis,portfolio,platform FROM thesis_trace_api,thesis_trace_collector,thesis_trace_ai_worker")
    connection.execute("GRANT USAGE ON SCHEMA access,research,workflow,thesis,portfolio,platform TO thesis_trace_api")
    connection.execute("GRANT SELECT ON research.schema_migrations TO thesis_trace_api")
    connection.execute("GRANT SELECT ON platform.alembic_version TO thesis_trace_api")
    connection.execute("GRANT SELECT,INSERT,UPDATE ON access.users,access.identities,access.sessions,access.confirmation_challenges TO thesis_trace_api")
    connection.execute("GRANT SELECT ON access.account_capacity TO thesis_trace_api")
    connection.execute("GRANT INSERT ON access.security_audit_events,access.workflow_outbox TO thesis_trace_api")
    connection.execute("GRANT SELECT,INSERT ON research.companies,research.evidence_intakes,research.idempotency_receipts TO thesis_trace_api")
    connection.execute("GRANT INSERT ON research.audit_events,research.collection_jobs TO thesis_trace_api")
    connection.execute("GRANT SELECT ON research.source_observations,research.source_snapshots,research.valuation_source_facts TO thesis_trace_api")
    connection.execute("GRANT SELECT,INSERT ON research.evidence_stage_versions TO thesis_trace_api")
    connection.execute("GRANT SELECT,INSERT ON research.anomaly_assessments TO thesis_trace_api")
    connection.execute("GRANT INSERT ON research.anomaly_analysis_jobs TO thesis_trace_api")
    connection.execute("GRANT SELECT,INSERT,UPDATE ON workflow.action_items TO thesis_trace_api")
    connection.execute("GRANT SELECT,INSERT ON workflow.action_priority_evaluations,workflow.audit_events TO thesis_trace_api")
    connection.execute("GRANT SELECT,INSERT ON workflow.creation_receipts,workflow.transition_receipts TO thesis_trace_api")
    connection.execute("GRANT SELECT,INSERT,UPDATE ON thesis.theses TO thesis_trace_api")
    connection.execute("GRANT SELECT,INSERT ON ALL TABLES IN SCHEMA thesis TO thesis_trace_api")
    connection.execute("GRANT SELECT,INSERT ON portfolio.audit_events,portfolio.command_receipts TO thesis_trace_api")
    connection.execute("GRANT SELECT,INSERT,UPDATE ON portfolio.official_security_snapshots TO thesis_trace_api")
    connection.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON portfolio.current_state,portfolio.holdings TO thesis_trace_api")
    connection.execute(
        "GRANT SELECT,INSERT ON portfolio.cost_profiles,portfolio.investable_cash_versions,portfolio.trades,"
        "portfolio.trade_allocations,portfolio.trade_corrections,portfolio.correction_allocations,"
        "portfolio.company_actions,portfolio.company_action_allocations,portfolio.version_history TO thesis_trace_api"
    )
    connection.execute("GRANT USAGE ON SCHEMA research,platform TO thesis_trace_collector")
    connection.execute("GRANT SELECT ON research.schema_migrations TO thesis_trace_collector")
    connection.execute("GRANT SELECT ON platform.alembic_version TO thesis_trace_collector")
    connection.execute("GRANT SELECT ON research.companies TO thesis_trace_collector")
    connection.execute("GRANT SELECT,UPDATE ON research.evidence_intakes TO thesis_trace_collector")
    connection.execute("GRANT SELECT,UPDATE ON research.collection_jobs TO thesis_trace_collector")
    connection.execute(
        """GRANT SELECT,INSERT ON research.canonical_sources,research.source_snapshots,
        research.source_observations,research.valuation_source_facts TO thesis_trace_collector"""
    )
    connection.execute("GRANT USAGE ON SCHEMA research,platform TO thesis_trace_ai_worker")
    connection.execute("GRANT SELECT ON research.schema_migrations TO thesis_trace_ai_worker")
    connection.execute("GRANT SELECT ON platform.alembic_version TO thesis_trace_ai_worker")
    connection.execute(
        "GRANT SELECT ON research.evidence_intakes,research.source_snapshots,"
        "research.anomaly_assessments TO thesis_trace_ai_worker"
    )
    connection.execute(
        "GRANT SELECT,UPDATE ON research.anomaly_analysis_jobs TO thesis_trace_ai_worker"
    )
    connection.execute("GRANT UPDATE ON research.anomaly_assessments TO thesis_trace_ai_worker")
    connection.execute("GRANT INSERT ON research.audit_events TO thesis_trace_ai_worker")


def run_production_migrations() -> None:
    provider = required_secret_provider("THESIS_TRACE_DATABASE_URL")
    bootstrap_schema(provider)

    with psycopg.connect(provider()) as connection:
        apply_runtime_grants(connection)


if __name__ == "__main__":
    run_production_migrations()
