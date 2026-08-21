-- Production bootstrap authority. Passwords are assigned from Compose secrets by 01-role-passwords.sh.
CREATE ROLE thesis_trace_migration LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
CREATE ROLE thesis_trace_api LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
CREATE ROLE thesis_trace_collector LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
CREATE ROLE thesis_trace_ai_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;

ALTER DATABASE thesis_trace OWNER TO thesis_trace_migration;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE thesis_trace TO thesis_trace_migration, thesis_trace_api, thesis_trace_collector, thesis_trace_ai_worker;
