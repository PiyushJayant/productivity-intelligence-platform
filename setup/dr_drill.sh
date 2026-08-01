#!/usr/bin/env bash
# Explicitly approved AlloyDB failover/PITR drill; never invoked by normal CI.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=setup/common.sh
source "${SCRIPT_DIR}/common.sh"
require_phase5

ACTION="${1:-plan}"
case "${ACTION}" in
  plan)
    echo "DR target: ${PROJECT_ID}/${REGION}/${ALLOYDB_CLUSTER}/${ALLOYDB_INSTANCE}"
    echo "Operations: HA failover measurement, then isolated PITR clone validation."
    echo "No operation performed."
    ;;
  failover)
    [[ "${DR_CONFIRM:-}" == "FAILOVER_APPROVED" ]] || {
      echo "DR_CONFIRM=FAILOVER_APPROVED is required." >&2; exit 1;
    }
    started="$(date +%s)"
    gcloud alloydb instances failover "${ALLOYDB_INSTANCE}" \
      --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
      --project="${PROJECT_ID}" --quiet
    completed="$(date +%s)"
    echo "{\"operation\":\"failover\",\"rto_seconds\":$((completed-started)),\"measured_at\":\"$(date -u +%FT%TZ)\"}"
    ;;
  *)
    echo "Unknown drill action. PITR restore requires a separately named target and operator review." >&2
    exit 2
    ;;
esac
