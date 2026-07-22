#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=setup/common.sh
source "${SCRIPT_DIR}/common.sh"
preflight

gcloud services enable monitoring.googleapis.com --project="${PROJECT_ID}" >/dev/null

assistant_url="$(gcloud run services describe "${ASSISTANT_SERVICE_NAME}" \
  --region="${REGION}" --project="${PROJECT_ID}" --format='value(status.url)')"
assistant_host="${assistant_url#https://}"

if ! gcloud monitoring uptime list-configs --project="${PROJECT_ID}" \
    --format='value(displayName)' | grep -Fxq 'Productivity Assistant hosted liveness'; then
  gcloud monitoring uptime create 'Productivity Assistant hosted liveness' \
    --project="${PROJECT_ID}" --resource-type=uptime-url \
    --resource-labels="host=${assistant_host},project_id=${PROJECT_ID}" \
    --protocol=https --path=/health --period=1 --timeout=10 --validate-ssl=true
fi

create_threshold_policy() {
  local display="$1" condition="$2" filter="$3" aggregation="$4" threshold="$5"
  if gcloud monitoring policies list --project="${PROJECT_ID}" \
      --format='value(displayName)' | grep -Fxq "${display}"; then
    return
  fi
  gcloud monitoring policies create --project="${PROJECT_ID}" \
    --display-name="${display}" --condition-display-name="${condition}" \
    --condition-filter="${filter}" --aggregation="${aggregation}" \
    --duration=300s --if="> ${threshold}" --trigger-count=1 \
    --combiner=OR \
    --documentation="Hackathon deployment alert for ${PROJECT_ID}. Inspect service and dependency logs before rollback."
}

create_threshold_policy \
  'Productivity Assistant 5xx rate' 'Cloud Run 5xx responses' \
  "resource.type=\"cloud_run_revision\" AND resource.label.\"service_name\"=\"${ASSISTANT_SERVICE_NAME}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.label.\"response_code_class\"=\"5xx\"" \
  '{"alignmentPeriod":"300s","perSeriesAligner":"ALIGN_RATE","crossSeriesReducer":"REDUCE_SUM"}' 0

create_threshold_policy \
  'Productivity Assistant p95 latency' 'Cloud Run p95 latency above 2s' \
  "resource.type=\"cloud_run_revision\" AND resource.label.\"service_name\"=\"${ASSISTANT_SERVICE_NAME}\" AND metric.type=\"run.googleapis.com/request_latencies\"" \
  '{"alignmentPeriod":"300s","perSeriesAligner":"ALIGN_PERCENTILE_95","crossSeriesReducer":"REDUCE_MAX"}' 2000

create_threshold_policy \
  'Productivity AlloyDB connection high-water mark' 'AlloyDB connections above 80' \
  'resource.type="alloydb.googleapis.com/Instance" AND metric.type="alloydb.googleapis.com/instance/postgres/total_connections"' \
  '{"alignmentPeriod":"300s","perSeriesAligner":"ALIGN_MAX","crossSeriesReducer":"REDUCE_MAX"}' 80

for metric in startup_failures toolbox_authorization_failures mcp_failures bigquery_errors; do
  if gcloud logging metrics describe "productivity_${metric}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    continue
  fi
  case "${metric}" in
    startup_failures)
      filter='resource.type="cloud_run_revision" textPayload:"STARTUP TCP probe failed"'
      ;;
    toolbox_authorization_failures)
      filter="resource.type=\"cloud_run_revision\" resource.labels.service_name=\"${TOOLBOX_SERVICE_NAME}\" httpRequest.status>=401 httpRequest.status<404"
      ;;
    mcp_failures)
      filter="resource.type=\"cloud_run_revision\" resource.labels.service_name=\"${ASSISTANT_SERVICE_NAME}\" severity>=ERROR (textPayload:MCP OR jsonPayload.message:MCP)"
      ;;
    bigquery_errors)
      filter="resource.type=\"cloud_run_revision\" resource.labels.service_name=\"${ASSISTANT_SERVICE_NAME}\" severity>=ERROR (textPayload:BigQuery OR jsonPayload.message:BigQuery)"
      ;;
  esac
  gcloud logging metrics create "productivity_${metric}" --project="${PROJECT_ID}" \
    --description="Productivity deployment ${metric//_/ }" --log-filter="${filter}"
done

echo "[OK] Monitoring checks and error metrics configured."
