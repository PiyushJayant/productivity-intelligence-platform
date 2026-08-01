#!/usr/bin/env bash
# Phase 1 enterprise encryption and service-perimeter provisioning.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=setup/common.sh
source "${SCRIPT_DIR}/common.sh"
require_phase5

if [[ "${ENABLE_CMEK}" == "true" ]]; then
  gcloud kms keyrings describe "${KMS_KEYRING}" --location="${REGION}" \
    --project="${PROJECT_ID}" >/dev/null 2>&1 ||
    gcloud kms keyrings create "${KMS_KEYRING}" --location="${REGION}" \
      --project="${PROJECT_ID}"
  for key in "${KMS_ALLOYDB_KEY}" "${KMS_BIGQUERY_KEY}" "${KMS_SECRET_KEY}"; do
    gcloud kms keys describe "${key}" --keyring="${KMS_KEYRING}" \
      --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1 ||
      gcloud kms keys create "${key}" --keyring="${KMS_KEYRING}" \
        --location="${REGION}" --purpose=encryption \
        --rotation-period="${KMS_ROTATION_PERIOD}" \
        --next-rotation-time="$(date -u -d '+91 days' +%Y-%m-%dT%H:%M:%SZ)" \
        --project="${PROJECT_ID}"
  done
  declare -A key_members=(
    ["${KMS_ALLOYDB_KEY}"]="service-${PROJECT_NUMBER}@gcp-sa-alloydb.iam.gserviceaccount.com"
    ["${KMS_BIGQUERY_KEY}"]="bq-${PROJECT_NUMBER}@bigquery-encryption.iam.gserviceaccount.com"
    ["${KMS_SECRET_KEY}"]="service-${PROJECT_NUMBER}@gcp-sa-secretmanager.iam.gserviceaccount.com"
  )
  for key in "${!key_members[@]}"; do
    gcloud kms keys add-iam-policy-binding "${key}" \
      --keyring="${KMS_KEYRING}" --location="${REGION}" \
      --member="serviceAccount:${key_members[${key}]}" \
      --role=roles/cloudkms.cryptoKeyEncrypterDecrypter \
      --project="${PROJECT_ID}" --quiet
  done
fi

if [[ "${ENABLE_VPC_SC}" == "true" ]]; then
  [[ -n "${ACCESS_POLICY_ID:-}" ]] || {
    echo "ACCESS_POLICY_ID is required when ENABLE_VPC_SC=true" >&2
    exit 1
  }
  perimeter="${ACCESS_POLICY_ID}/servicePerimeters/${SERVICE_PERIMETER_NAME}"
  gcloud access-context-manager perimeters describe "${perimeter}" \
    --policy="${ACCESS_POLICY_ID}" >/dev/null 2>&1 ||
    gcloud access-context-manager perimeters create "${SERVICE_PERIMETER_NAME}" \
      --title="${SERVICE_PERIMETER_NAME}" \
      --resources="projects/${PROJECT_NUMBER}" \
      --restricted-services="alloydb.googleapis.com,bigquery.googleapis.com,secretmanager.googleapis.com" \
      --policy="${ACCESS_POLICY_ID}"
fi

echo "[OK] Requested enterprise security controls are configured"
