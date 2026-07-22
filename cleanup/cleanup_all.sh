#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=setup/common.sh
source "${SCRIPT_DIR}/../setup/common.sh"
preflight

cat <<EOF
This will delete the Productivity Assistant resources from:
  Project: ${PROJECT_ID}
  Region:  ${REGION}
  Cloud Run services: ${ASSISTANT_SERVICE_NAME}, ${TOOLBOX_SERVICE_NAME}
  Cloud Run job: ${MIGRATION_JOB_NAME}
  AlloyDB cluster: ${ALLOYDB_CLUSTER}
  BigQuery dataset/connection: productivity_analytics, ${BIGQUERY_CONNECTION_ID}
  Artifact Registry: ${AR_REPO}
  Secrets: ${ADMIN_DB_SECRET}, ${APP_DB_SECRET}, ${ANALYTICS_DB_SECRET}
  Network: ${VPC_NETWORK}/${VPC_SUBNET}
EOF
read -r -p "Type the project ID to confirm: " confirmation
[[ "${confirmation}" == "${PROJECT_ID}" ]] || {
  echo "Cleanup cancelled."
  exit 1
}

gcloud run services delete "${ASSISTANT_SERVICE_NAME}" --region="${REGION}" \
  --project="${PROJECT_ID}" --quiet 2>/dev/null || true
gcloud run services delete "${TOOLBOX_SERVICE_NAME}" --region="${REGION}" \
  --project="${PROJECT_ID}" --quiet 2>/dev/null || true
gcloud run jobs delete "${MIGRATION_JOB_NAME}" --region="${REGION}" \
  --project="${PROJECT_ID}" --quiet 2>/dev/null || true
"${BQ_BIN}" rm -r -f -d "${PROJECT_ID}:productivity_analytics" 2>/dev/null || true
"${BQ_BIN}" rm -f --connection --location="${REGION}" \
  "${PROJECT_ID}.${REGION}.${BIGQUERY_CONNECTION_ID}" 2>/dev/null || true
gcloud alloydb clusters delete "${ALLOYDB_CLUSTER}" --region="${REGION}" \
  --project="${PROJECT_ID}" --force --quiet 2>/dev/null || true
gcloud artifacts repositories delete "${AR_REPO}" --location="${REGION}" \
  --project="${PROJECT_ID}" --quiet 2>/dev/null || true
for secret in "${ADMIN_DB_SECRET}" "${APP_DB_SECRET}" "${ANALYTICS_DB_SECRET}"; do
  gcloud secrets delete "${secret}" --project="${PROJECT_ID}" --quiet 2>/dev/null || true
done
gcloud services vpc-peerings delete --service=servicenetworking.googleapis.com \
  --network="${VPC_NETWORK}" --project="${PROJECT_ID}" --quiet 2>/dev/null || true
gcloud compute addresses delete "${PSA_RANGE_NAME}" --global \
  --project="${PROJECT_ID}" --quiet 2>/dev/null || true
gcloud compute networks subnets delete "${VPC_SUBNET}" --region="${REGION}" \
  --project="${PROJECT_ID}" --quiet 2>/dev/null || true
gcloud compute networks delete "${VPC_NETWORK}" --project="${PROJECT_ID}" \
  --quiet 2>/dev/null || true

echo "[OK] Productivity Assistant resources removed. Cloud deletion is not recoverable."
