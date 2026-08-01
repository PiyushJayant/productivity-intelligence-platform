#!/usr/bin/env bash
# Sole entry point for billing-dependent deployment, migration and cloud tests.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=setup/common.sh
source "${SCRIPT_DIR}/common.sh"

require_phase5_acknowledgement() {
  [[ "${ENABLE_BILLABLE_PHASE}" == "true" ]] || {
    echo "Phase 5 disabled: set ENABLE_BILLABLE_PHASE=true in .env." >&2
    exit 1
  }
  [[ "${BILLING_ACK}" == "I_ACKNOWLEDGE_GCP_CHARGES" ]] || {
    echo "Phase 5 disabled: explicit BILLING_ACK is required." >&2
    exit 1
  }
  local enabled
  enabled="$(gcloud billing projects describe "${PROJECT_ID}" \
    --format='value(billingEnabled)' 2>/dev/null || true)"
  [[ "${enabled}" == "True" || "${enabled}" == "true" ]] || {
    echo "Phase 5 stopped: billing is not enabled for ${PROJECT_ID}." >&2
    exit 1
  }
  local active_project
  active_project="$(gcloud config get-value project 2>/dev/null || true)"
  [[ "${active_project}" == "${PROJECT_ID}" ]] || {
    echo "Phase 5 stopped: active gcloud project '${active_project}' differs from '${PROJECT_ID}'." >&2
    exit 1
  }
  export PHASE5_ACTIVE=true
}

ACTION="${1:-help}"
case "${ACTION}" in
  help)
    cat <<'EOF'
Usage: setup/phase5.sh ACTION
  plan       print validated configuration without cloud mutation
  identity   configure and validate Identity Platform
  provision  provision networking, data and security resources
  build      build immutable images
  migrate    run authenticated database migrations
  deploy     deploy candidate revisions without bypassing checks
  verify     run authenticated cloud smoke tests
  promote    promote the verified candidate to 100 percent traffic
  rollback   send 100 percent traffic to an explicit prior revision
  security   provision enabled CMEK and VPC-SC controls
  privacy    deploy the disabled-by-default privacy maintenance job
  privacy-erase REQUEST_UUID  execute one confirmed erasure request
  native     provision native BigQuery v3 contracts (CDC prerequisite)
  cdc        provision the disabled-by-default Datastream CDC resources
  load       run the bounded authenticated analytics load contract
  monitoring-plan  validate the monitoring contract without cloud mutation
  monitoring-validate  compare deployed monitoring inventory to the contract
  dr-plan    validate the HA/PITR drill contract without cloud mutation
  dr-ha      execute an approved HA failover drill
  dr-pitr    execute an approved out-of-place PITR drill
  dr-cleanup delete the explicitly named PITR restore cluster
  full       identity, provision, build, migrate, deploy and verify

All cloud-changing or authenticated actions can incur GCP charges and require both:
  ENABLE_BILLABLE_PHASE=true
  BILLING_ACK=I_ACKNOWLEDGE_GCP_CHARGES
EOF
    ;;
  plan)
    validate_config
    "${PYTHON_BIN}" "${SCRIPT_DIR}/identity_setup.py"
    echo "[PLAN] project=${PROJECT_ID} region=${REGION} backend=${ANALYTICS_BACKEND}"
    echo "[PLAN] no cloud mutation performed"
    ;;
  monitoring-plan)
    "${SCRIPT_DIR}/monitoring.sh" plan
    ;;
  dr-plan)
    "${SCRIPT_DIR}/dr_drill.sh" plan
    ;;
  identity|provision|build|migrate|deploy|verify|promote|rollback|security|privacy|privacy-erase|native|cdc|load|monitoring-validate|dr-ha|dr-pitr|dr-cleanup|full)
    require_command gcloud
    require_phase5_acknowledgement
    case "${ACTION}" in
      identity) "${PYTHON_BIN}" "${SCRIPT_DIR}/identity_setup.py" --apply ;;
      provision) "${SCRIPT_DIR}/provision.sh" ;;
      build) "${SCRIPT_DIR}/deploy.sh" build ;;
      migrate) "${SCRIPT_DIR}/deploy.sh" migrate ;;
      deploy) "${SCRIPT_DIR}/deploy.sh" deploy ;;
      verify) "${SCRIPT_DIR}/deploy.sh" verify ;;
      promote) "${SCRIPT_DIR}/deploy.sh" promote ;;
      rollback)
        [[ -n "${2:-}" ]] || { echo "rollback requires a revision" >&2; exit 2; }
        "${SCRIPT_DIR}/deploy.sh" rollback "$2"
        ;;
      security) "${SCRIPT_DIR}/security_setup.sh" ;;
      privacy) "${SCRIPT_DIR}/deploy.sh" privacy ;;
      privacy-erase)
        [[ -n "${2:-}" ]] || { echo "privacy-erase requires a request UUID" >&2; exit 2; }
        "${SCRIPT_DIR}/deploy.sh" privacy-erase "$2"
        ;;
      native) "${PYTHON_BIN}" "${SCRIPT_DIR}/native_bigquery_setup.py" ;;
      cdc) "${SCRIPT_DIR}/datastream_setup.sh" ;;
      load) "${PYTHON_BIN}" "${SCRIPT_DIR}/load_test.py" --execute ;;
      monitoring-validate)
        (cd "${REPO_ROOT}" && "${PYTHON_BIN}" -m setup.observability_inventory)
        ;;
      dr-ha) "${SCRIPT_DIR}/dr_drill.sh" ha-failover ;;
      dr-pitr) "${SCRIPT_DIR}/dr_drill.sh" pitr-restore ;;
      dr-cleanup) "${SCRIPT_DIR}/dr_drill.sh" cleanup-restore ;;
      full)
        "${PYTHON_BIN}" "${SCRIPT_DIR}/identity_setup.py" --apply
        "${SCRIPT_DIR}/deploy.sh" full
        ;;
    esac
    ;;
  *)
    echo "Unknown Phase 5 action: ${ACTION}" >&2
    exit 2
    ;;
esac
