#!/usr/bin/env bash
# Create the darb_solar role and database on a local Postgres instance.
#
# Usage:
#   PGPASSWORD='your-postgres-password' ./scripts/setup_native_postgres.sh
#
# Or run psql interactively (it will prompt for the postgres password):
#   ./scripts/setup_native_postgres.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PSQL="${PSQL:-/Library/PostgreSQL/16/bin/psql}"
ROLE_SQL="${ROOT}/scripts/setup_native_postgres.sql"
SCHEMA_SQL="${ROOT}/scripts/setup_schema.sql"

if [[ ! -x "${PSQL}" ]]; then
    PSQL="$(command -v psql)"
fi

if [[ ! -x "${PSQL}" ]]; then
    echo "psql not found. Set PSQL to your Postgres bin path." >&2
    exit 1
fi

"${PSQL}" -U postgres -h localhost -p 5432 -f "${ROLE_SQL}"
"${PSQL}" -U postgres -h localhost -p 5432 -d darb_solar -f "${SCHEMA_SQL}"

echo "Native Postgres ready. Database URL:"
echo "  postgresql+psycopg://darb_solar:darb_solar@localhost:5432/darb_solar"
