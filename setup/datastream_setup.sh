#!/usr/bin/env bash
# Explicitly gated Datastream lifecycle. Provision never creates or starts a stream.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=setup/common.sh
source "${SCRIPT_DIR}/common.sh"

ACTION="${1:-status}"

require_cdc_host() {
  [[ "${DATASTREAM_DB_HOST}" != replace-* && "${DATASTREAM_DB_HOST}" != localhost ]] || {
    echo "DATASTREAM_DB_HOST must be the approved private AlloyDB endpoint" >&2
    exit 1
  }
}

verify_activation_evidence() {
  [[ "${CDC_TRIGGER_EVIDENCE_PATH}" != replace-* ]] || {
    echo "CDC trigger evidence path is not configured" >&2; exit 1;
  }
  [[ "${CDC_TRIGGER_EVIDENCE_SHA256}" =~ ^[0-9a-f]{64}$ ]] || {
    echo "CDC trigger evidence SHA-256 is invalid" >&2; exit 1;
  }
  "${PYTHON_BIN}" "${SCRIPT_DIR}/evaluate_cdc_trigger.py" verify \
    "${CDC_TRIGGER_EVIDENCE_PATH}" \
    --expected-sha256="${CDC_TRIGGER_EVIDENCE_SHA256}"
}

provision() {
  [[ "${CDC_PROVISION_ACK}" == "I_ACKNOWLEDGE_CDC_PROVISIONING_COST" ]] || {
    echo "CDC provisioning requires its separate acknowledgment" >&2; exit 1;
  }
  require_cdc_host
  gcloud services enable datastream.googleapis.com --project="${PROJECT_ID}" >/dev/null
  ensure_secret_from_env "${CDC_DB_SECRET}" "${CDC_DB_PASSWORD}"
  local secret_version secret_resource project_number datastream_agent
  secret_version="$(secret_version "${CDC_DB_SECRET}")"
  [[ "${secret_version}" =~ ^[0-9]+$ ]] || { echo "CDC secret version must be numeric" >&2; exit 1; }
  secret_resource="projects/${PROJECT_ID}/secrets/${CDC_DB_SECRET}/versions/${secret_version}"
  project_number="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
  datastream_agent="service-${project_number}@gcp-sa-datastream.iam.gserviceaccount.com"
  gcloud secrets add-iam-policy-binding "${CDC_DB_SECRET}" --project="${PROJECT_ID}" \
    --member="serviceAccount:${datastream_agent}" --role=roles/secretmanager.secretAccessor >/dev/null

  gcloud datastream private-connections describe "${DATASTREAM_PRIVATE_CONNECTION}" \
    --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}" >/dev/null 2>&1 ||
    gcloud datastream private-connections create "${DATASTREAM_PRIVATE_CONNECTION}" \
      --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}" \
      --display-name="${DATASTREAM_PRIVATE_CONNECTION}" \
      --vpc="projects/${PROJECT_ID}/global/networks/${VPC_NETWORK}" \
      --subnet="${DATASTREAM_PEERING_CIDR}" --endpoint-mode=regional

  gcloud datastream connection-profiles describe "${DATASTREAM_SOURCE_PROFILE}" \
    --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}" >/dev/null 2>&1 ||
    gcloud datastream connection-profiles create "${DATASTREAM_SOURCE_PROFILE}" \
      --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}" \
      --display-name="${DATASTREAM_SOURCE_PROFILE}" --type=postgresql \
      --postgresql-hostname="${DATASTREAM_DB_HOST}" \
      --postgresql-port="${DATASTREAM_DB_PORT}" \
      --postgresql-username="${CDC_DB_USER}" \
      --postgresql-secret-manager-stored-password="${secret_resource}" \
      --postgresql-database="${ALLOYDB_DATABASE}" \
      --private-connection="${DATASTREAM_PRIVATE_CONNECTION}" \
      --endpoint-mode=regional --project="${PROJECT_ID}"
  gcloud datastream connection-profiles describe "${DATASTREAM_DESTINATION_PROFILE}" \
    --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}" >/dev/null 2>&1 ||
    gcloud datastream connection-profiles create "${DATASTREAM_DESTINATION_PROFILE}" \
      --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}" \
      --display-name="${DATASTREAM_DESTINATION_PROFILE}" --type=bigquery \
      --endpoint-mode=regional
  echo "[OK] CDC connectivity provisioned. No publication, slot, stream, or backfill was created."
}

start() {
  [[ "${ENABLE_DATASTREAM}" == "true" ]] || { echo "ENABLE_DATASTREAM must be true" >&2; exit 1; }
  [[ "${CDC_START_ACK}" == "I_ACKNOWLEDGE_CDC_ACTIVATION_COST" ]] || {
    echo "CDC activation requires its separate acknowledgment" >&2; exit 1;
  }
  verify_activation_evidence
  require_cdc_host
  local temporary_directory stream_created=false activation_complete=false
  temporary_directory="$(mktemp -d)"
  rollback_incomplete_activation() {
    local exit_code="$?"
    if [[ "${activation_complete}" != "true" ]]; then
      if [[ "${stream_created}" == "true" ]]; then
        gcloud datastream streams delete "${DATASTREAM_STREAM}" --quiet \
          --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}" || true
        gcloud run jobs execute "${MIGRATION_JOB_NAME}" --region="${REGION}" \
          --project="${PROJECT_ID}" --wait \
          --args="-m,setup.cdc_database,cleanup" >/dev/null 2>&1 || true
      fi
    fi
    rm -rf -- "${temporary_directory}"
    return "${exit_code}"
  }
  trap rollback_incomplete_activation EXIT
  "${PYTHON_BIN}" "${SCRIPT_DIR}/cdc_contract.py" --output-dir="${temporary_directory}"

  # Database publication/slot preparation is run only after threshold evidence passes.
  gcloud run jobs execute "${MIGRATION_JOB_NAME}" --region="${REGION}" \
    --project="${PROJECT_ID}" --wait \
    --args="-m,setup.cdc_database,prepare" >/dev/null
  if ! gcloud datastream streams describe "${DATASTREAM_STREAM}" \
    --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    stream_created=true
    gcloud datastream streams create "${DATASTREAM_STREAM}" \
      --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}" \
      --source="${DATASTREAM_SOURCE_PROFILE}" \
      --destination="${DATASTREAM_DESTINATION_PROFILE}" \
      --display-name="${DATASTREAM_STREAM}" \
      --endpoint-mode=regional \
      --postgresql-source-config="${temporary_directory}/source.json" \
      --bigquery-destination-config="${temporary_directory}/destination.json" \
      --rule-sets="${temporary_directory}/rules.json" --backfill-all
  fi
  local state
  state="$(gcloud datastream streams describe "${DATASTREAM_STREAM}" \
    --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}" --format='value(state)')"
  [[ "${state}" == "CREATED" || "${state}" == "PAUSED" ]] || {
    echo "Refusing activation from unexpected Datastream state: ${state}" >&2
    if [[ "${stream_created}" == "true" ]]; then
      gcloud datastream streams delete "${DATASTREAM_STREAM}" --quiet \
        --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}" || true
    fi
    exit 1
  }
  gcloud datastream streams update "${DATASTREAM_STREAM}" --state=running \
    --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}"
  activation_complete=true
  echo "[OK] CDC activated from measured, verified threshold evidence."
}

case "${ACTION}" in
  plan) "${PYTHON_BIN}" "${SCRIPT_DIR}/cdc_contract.py" ;;
  provision) require_phase5; provision ;;
  start) require_phase5; start ;;
  pause)
    require_phase5
    gcloud datastream streams update "${DATASTREAM_STREAM}" --state=paused \
      --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}"
    echo "[WARN] A paused stream can retain WAL; monitor and clean up deliberately."
    ;;
  status)
    gcloud datastream streams describe "${DATASTREAM_STREAM}" \
      --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}"
    ;;
  *) echo "Usage: $0 plan|provision|start|pause|status" >&2; exit 2 ;;
esac
