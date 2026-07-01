-- One-time setup for darb-solar on a local Postgres 16 instance.
-- Run as a superuser (typically postgres):
--
--   /Library/PostgreSQL/16/bin/psql -U postgres -h localhost \
--     -f scripts/setup_native_postgres.sql

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'darb_solar') THEN
        CREATE ROLE darb_solar LOGIN PASSWORD 'darb_solar';
    END IF;
END
$$;

SELECT format(
    'CREATE DATABASE %I OWNER darb_solar',
    'darb_solar'
)
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'darb_solar')
\gexec

GRANT ALL PRIVILEGES ON DATABASE darb_solar TO darb_solar;
