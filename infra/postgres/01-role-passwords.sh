#!/bin/sh
set -eu
export API_DATABASE_PASSWORD="$(tr -d '\r\n' < /run/secrets/api_database_password)"
export COLLECTOR_DATABASE_PASSWORD="$(tr -d '\r\n' < /run/secrets/collector_database_password)"
export MIGRATION_DATABASE_PASSWORD="$(tr -d '\r\n' < /run/secrets/migration_database_password)"
psql --no-psqlrc --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv api_password API_DATABASE_PASSWORD
\getenv collector_password COLLECTOR_DATABASE_PASSWORD
\getenv migration_password MIGRATION_DATABASE_PASSWORD
ALTER ROLE thesis_trace_api PASSWORD :'api_password';
ALTER ROLE thesis_trace_collector PASSWORD :'collector_password';
ALTER ROLE thesis_trace_migration PASSWORD :'migration_password';
SQL
