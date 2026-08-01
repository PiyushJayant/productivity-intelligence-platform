#!/usr/bin/env bash
# Phase 2 enterprise encryption and service-perimeter provisioning.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=setup/common.sh
source "${SCRIPT_DIR}/common.sh"
require_phase5

if [[ "${ENABLE_CMEK}" == "true" ]]; then
  PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" \
    --format='value(projectNumber)')"
  gcloud beta services identity create --service=alloydb.googleapis.com \
    --project="${PROJECT_ID}" >/dev/null
  gcloud beta services identity create --service=secretmanager.googleapis.com \
    --project="${PROJECT_ID}" >/dev/null
  "${BQ_BIN}" show --encryption_service_account \
    --project_id="${PROJECT_ID}" >/dev/null
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
  PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" \
    --format='value(projectNumber)')"
  restricted_services="alloydb.googleapis.com,bigquery.googleapis.com,secretmanager.googleapis.com"
  if [[ "${VPC_SC_MODE}" == "dry-run" ]]; then
    if gcloud access-context-manager perimeters describe "${SERVICE_PERIMETER_NAME}" \
        --policy="${ACCESS_POLICY_ID}" >/dev/null 2>&1; then
      gcloud access-context-manager perimeters dry-run update \
        "${SERVICE_PERIMETER_NAME}" --policy="${ACCESS_POLICY_ID}" \
        --add-resources="projects/${PROJECT_NUMBER}" \
        --add-restricted-services="${restricted_services}"
    else
      gcloud access-context-manager perimeters dry-run create \
        "${SERVICE_PERIMETER_NAME}" --policy="${ACCESS_POLICY_ID}" \
        --perimeter-title="${SERVICE_PERIMETER_NAME}" \
        --perimeter-resources="projects/${PROJECT_NUMBER}" \
        --perimeter-restricted-services="${restricted_services}"
    fi
  else
    [[ "${VPC_SC_ENFORCEMENT_ACK}" == "I_ACKNOWLEDGE_VPC_SC_LOCKOUT_RISK" ]] || {
      echo "VPC-SC enforcement acknowledgement is missing" >&2
      exit 1
    }
    if gcloud access-context-manager perimeters describe "${SERVICE_PERIMETER_NAME}" \
        --policy="${ACCESS_POLICY_ID}" >/dev/null 2>&1; then
      gcloud access-context-manager perimeters update "${SERVICE_PERIMETER_NAME}" \
        --policy="${ACCESS_POLICY_ID}" \
        --set-resources="projects/${PROJECT_NUMBER}" \
        --set-restricted-services="${restricted_services}"
    else
      gcloud access-context-manager perimeters create "${SERVICE_PERIMETER_NAME}" \
        --title="${SERVICE_PERIMETER_NAME}" \
        --resources="projects/${PROJECT_NUMBER}" \
        --restricted-services="${restricted_services}" \
        --policy="${ACCESS_POLICY_ID}"
    fi
  fi
fi

echo "[OK] Requested enterprise security controls are configured"
