#!/usr/bin/env bash
# Export Cloud Run runtime dependencies to requirements.txt from pyproject.toml.
#
# Installs [project].dependencies plus the [dependency-groups].cloudrun group.
# Viz extras and dev groups are excluded so the Cloud Run image stays lean.
#
# Usage:
#   ./scripts/export_cloudrun_requirements.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUTPUT="${PROJECT_ROOT}/requirements.txt"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "error: required command not found: $1" >&2
    exit 1
  }
}

require_cmd uv

cd "${PROJECT_ROOT}"

HEADER="# Cloud Run runtime dependencies (auto-generated).
# Regenerate with:
#   ./scripts/export_cloudrun_requirements.sh
#
# Source: [project].dependencies + [dependency-groups].cloudrun in pyproject.toml
# (excludes viz extras and dev groups).
"

BODY="$(uv export \
  --frozen \
  --no-dev \
  --group cloudrun \
  --no-emit-project \
  --no-header \
  --no-annotate \
  --no-hashes)"

printf '%b%s\n' "${HEADER}" "${BODY}" > "${OUTPUT}"
printf 'Wrote %s\n' "${OUTPUT}"
