#!/usr/bin/env bash
# Export Streamlit Community Cloud dependencies to app/requirements.txt from
# pyproject.toml.
#
# Installs [project].dependencies plus the [project.optional-dependencies].viz
# extra. The local package is included from the repository root so the app can
# import darb_solar when Streamlit builds from app/.
#
# Usage:
#   ./scripts/export_streamlit_requirements.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUTPUT="${PROJECT_ROOT}/app/requirements.txt"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "error: required command not found: $1" >&2
    exit 1
  }
}

require_cmd uv

cd "${PROJECT_ROOT}"
mkdir -p "$(dirname "${OUTPUT}")"

HEADER="# Streamlit Community Cloud dependencies (auto-generated).
# Regenerate with:
#   ./scripts/export_streamlit_requirements.sh
#
# Source: [project].dependencies + [project.optional-dependencies].viz in
# pyproject.toml.
# The local package is installed from the repository root because the app
# entrypoint lives in app/.
-e ..
"

BODY="$(uv export \
  --frozen \
  --no-dev \
  --extra viz \
  --no-emit-project \
  --no-header \
  --no-annotate \
  --no-hashes)"

printf '%b%s\n' "${HEADER}" "${BODY}" > "${OUTPUT}"
printf 'Wrote %s\n' "${OUTPUT}"
