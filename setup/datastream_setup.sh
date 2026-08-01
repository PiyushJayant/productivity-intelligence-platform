#!/usr/bin/env bash
# Phase 4 CDC provisioning. Requires connectivity details already in .env.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=setup/common.sh
source "${SCRIPT_DIR}/common.sh"
require_phase5

[[ "${ENABLE_DATASTREAM}" == "true" ]] || {
  echo "ENABLE_DATASTREAM=false; CDC provisioning intentionally skipped."
  exit 0
}
required=(DATASTREAM_PRIVATE_CONNECTION DATASTREAM_DB_HOST DATASTREAM_DB_PORT)
for name in "${required[@]}"; do
  [[ -n "${!name:-}" ]] || { echo "${name} is required for CDC" >&2; exit 1; }
done

gcloud datastream connection-profiles describe "${DATASTREAM_SOURCE_PROFILE}" \
  --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}" >/dev/null 2>&1 ||
  gcloud datastream connection-profiles create postgresql \
    "${DATASTREAM_SOURCE_PROFILE}" --location="${DATASTREAM_LOCATION}" \
    --hostname="${DATASTREAM_DB_HOST}" --port="${DATASTREAM_DB_PORT}" \
    --username="${ANALYTICS_DB_USER}" \
    --password="$(gcloud secrets versions access "$(secret_version "${ANALYTICS_DB_SECRET}")" \
      --secret="${ANALYTICS_DB_SECRET}" --project="${PROJECT_ID}")" \
    --database="${ALLOYDB_DATABASE}" --project="${PROJECT_ID}"

gcloud datastream connection-profiles describe "${DATASTREAM_DESTINATION_PROFILE}" \
  --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}" >/dev/null 2>&1 ||
  gcloud datastream connection-profiles create bigquery \
    "${DATASTREAM_DESTINATION_PROFILE}" --location="${DATASTREAM_LOCATION}" \
    --project="${PROJECT_ID}"

gcloud datastream streams describe "${DATASTREAM_STREAM}" \
  --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}" >/dev/null 2>&1 ||
  gcloud datastream streams create "${DATASTREAM_STREAM}" \
    --location="${DATASTREAM_LOCATION}" \
    --source="${DATASTREAM_SOURCE_PROFILE}" \
    --destination="${DATASTREAM_DESTINATION_PROFILE}" \
    --backfill-all --display-name="${DATASTREAM_STREAM}" \
    --project="${PROJECT_ID}"

echo "[OK] CDC stream created; start it only after validation and change approval"
