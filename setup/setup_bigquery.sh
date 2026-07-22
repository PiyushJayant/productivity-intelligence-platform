#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=setup/common.sh
source "${SCRIPT_DIR}/common.sh"
preflight
GOOGLE_CLOUD_PROJECT="${PROJECT_ID}" REGION="${REGION}" \
  BIGQUERY_CONNECTION_ID="${BIGQUERY_CONNECTION_ID}" \
  python "${SCRIPT_DIR}/bigquery_setup.py"
