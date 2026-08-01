#!/usr/bin/env bash
# Auditable AlloyDB HA and PITR tooling. Plan is offline; execution is Phase 5-only.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=setup/common.sh
source "${SCRIPT_DIR}/common.sh"

ACTION="${1:-plan}"

validate_restore_target() {
  [[ "${DR_RESTORE_CLUSTER}" != "${ALLOYDB_CLUSTER}" &&
      "${DR_RESTORE_CLUSTER}" == *-dr-restore ]] || {
    echo "Restore target must differ from source and end in -dr-restore." >&2
    exit 1
  }
}

case "${ACTION}" in
  plan)
    "${PYTHON_BIN}" "${SCRIPT_DIR}/dr_contract.py"
    ;;
  evidence)
    "${PYTHON_BIN}" "${SCRIPT_DIR}/dr_contract.py" --result
    ;;
  ha-failover)
    require_phase5
    [[ "${ALLOYDB_AVAILABILITY_TYPE}" == "REGIONAL" ]] || {
      echo "HA failover requires a REGIONAL primary instance." >&2; exit 1;
    }
    [[ "${DR_CONFIRM:-}" == "HA_FAILOVER_APPROVED" ]] || {
      echo "DR_CONFIRM=HA_FAILOVER_APPROVED is required." >&2; exit 1;
    }
    started="$(date +%s)"
    gcloud alloydb instances failover "${ALLOYDB_INSTANCE}" \
      --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
      --project="${PROJECT_ID}" --quiet
    completed="$(date +%s)"
    echo "{\"schema_version\":1,\"evidence_type\":\"ha_failover\",\"rto_seconds\":$((completed-started)),\"operator_verification_required\":true,\"measured_at\":\"$(date -u +%FT%TZ)\"}"
    ;;
  pitr-restore)
    require_phase5
    validate_restore_target
    [[ -n "${DR_PITR_TIMESTAMP}" ]] || {
      echo "DR_PITR_TIMESTAMP must be set in .env." >&2; exit 1;
    }
    [[ "${DR_CONFIRM:-}" == "OUT_OF_PLACE_PITR_APPROVED" ]] || {
      echo "DR_CONFIRM=OUT_OF_PLACE_PITR_APPROVED is required." >&2; exit 1;
    }
    if gcloud alloydb clusters describe "${DR_RESTORE_CLUSTER}" \
        --region="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
      echo "Restore target already exists; refusing to overwrite it." >&2
      exit 1
    fi
    started="$(date +%s)"
    gcloud alloydb clusters restore "${DR_RESTORE_CLUSTER}" \
      --source-cluster="${ALLOYDB_CLUSTER}" \
      --point-in-time="${DR_PITR_TIMESTAMP}" \
      --network="${VPC_NETWORK}" --region="${REGION}" \
      --project="${PROJECT_ID}" --quiet
    gcloud alloydb instances create "${DR_RESTORE_INSTANCE}" \
      --cluster="${DR_RESTORE_CLUSTER}" --instance-type=PRIMARY \
      --machine-type="${ALLOYDB_MACHINE_TYPE}" --availability-type=ZONAL \
      --region="${REGION}" --project="${PROJECT_ID}" --quiet
    completed="$(date +%s)"
    echo "{\"schema_version\":1,\"evidence_type\":\"pitr_restore\",\"rto_seconds\":$((completed-started)),\"rpo_requires_marker_verification\":true,\"restore_cluster\":\"${DR_RESTORE_CLUSTER}\",\"measured_at\":\"$(date -u +%FT%TZ)\"}"
    ;;
  cleanup-restore)
    require_phase5
    validate_restore_target
    [[ "${DR_CONFIRM:-}" == "DELETE_RESTORE_APPROVED" ]] || {
      echo "DR_CONFIRM=DELETE_RESTORE_APPROVED is required." >&2; exit 1;
    }
    gcloud alloydb clusters delete "${DR_RESTORE_CLUSTER}" \
      --region="${REGION}" --project="${PROJECT_ID}" --quiet
    echo "[OK] Deleted isolated DR restore cluster ${DR_RESTORE_CLUSTER}."
    ;;
  *)
    echo "Usage: setup/dr_drill.sh plan|evidence|ha-failover|pitr-restore|cleanup-restore" >&2
    exit 2
    ;;
esac
