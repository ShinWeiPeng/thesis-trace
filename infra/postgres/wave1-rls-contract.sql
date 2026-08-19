-- CI-only executable contract. Backend migrations remain the production schema authority.
DO $$ BEGIN
  CREATE ROLE wave1_api_runtime NOLOGIN NOBYPASSRLS;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE SCHEMA IF NOT EXISTS wave1_contract;
CREATE TABLE IF NOT EXISTS wave1_contract.tenant_records (
  record_id uuid PRIMARY KEY,
  owner_user_id uuid NOT NULL,
  value text NOT NULL
);
CREATE TABLE IF NOT EXISTS wave1_contract.security_audit (
  audit_id uuid PRIMARY KEY,
  actor_user_id uuid NOT NULL,
  action text NOT NULL,
  reason text NOT NULL,
  occurred_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE wave1_contract.tenant_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE wave1_contract.tenant_records FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON wave1_contract.tenant_records;
CREATE POLICY tenant_scope ON wave1_contract.tenant_records
  USING (owner_user_id::text = current_setting('thesis_trace.user_id', true))
  WITH CHECK (owner_user_id::text = current_setting('thesis_trace.user_id', true));

REVOKE ALL ON SCHEMA wave1_contract FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA wave1_contract FROM PUBLIC;
GRANT USAGE ON SCHEMA wave1_contract TO wave1_api_runtime;
GRANT SELECT, INSERT, UPDATE ON wave1_contract.tenant_records TO wave1_api_runtime;
GRANT SELECT, INSERT ON wave1_contract.security_audit TO wave1_api_runtime;
