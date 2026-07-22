#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_command gcloud
require_command openssl
preflight

secret_file="$(mktemp)"
flags_file="$(mktemp)"
cleanup() {
  rm -f "${secret_file}" "${flags_file}"
}
trap cleanup EXIT

openssl rand -base64 36 | tr -d '\r\n/=+' >"${secret_file}"
version_path="$(gcloud secrets versions add "${ADMIN_DB_SECRET}" \
  --data-file="${secret_file}" --project="${PROJECT_ID}" --format='value(name)')"
printf '%s\n' "--password: $(<"${secret_file}")" >"${flags_file}"

gcloud alloydb users set-password "${ADMIN_DB_USER}" \
  --cluster="${ALLOYDB_CLUSTER}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --flags-file="${flags_file}" \
  --quiet >/dev/null

printf 'Rotated %s to numeric version %s.\n' \
  "${ADMIN_DB_SECRET}" "${version_path##*/}"

for secret_name in "${APP_DB_SECRET}" "${ANALYTICS_DB_SECRET}"; do
  openssl rand -base64 36 | tr -d '\r\n/=+' >"${secret_file}"
  version_path="$(gcloud secrets versions add "${secret_name}" \
    --data-file="${secret_file}" --project="${PROJECT_ID}" --format='value(name)')"
  printf 'Rotated %s to numeric version %s.\n' \
    "${secret_name}" "${version_path##*/}"
done
