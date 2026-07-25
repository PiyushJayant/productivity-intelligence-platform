#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=setup/common.sh
source "${SCRIPT_DIR}/common.sh"
preflight

if [[ "${ENABLE_MONITORING}" != "true" ]]; then
  echo "[SKIP] Monitoring is disabled in .env."
  exit 0
fi

gcloud services enable monitoring.googleapis.com --project="${PROJECT_ID}" >/dev/null

assistant_url="$(gcloud run services describe "${ASSISTANT_SERVICE_NAME}" \
  --region="${REGION}" --project="${PROJECT_ID}" --format='value(status.url)')"
assistant_host="${assistant_url#https://}"

if [[ "${ENABLE_UPTIME_CHECK}" == "true" ]]; then
  if ! gcloud monitoring uptime list-configs --project="${PROJECT_ID}" \
      --format='value(displayName)' | \
      grep -Fxq 'Productivity Intelligence hosted liveness'; then
    gcloud monitoring uptime create 'Productivity Intelligence hosted liveness' \
      --project="${PROJECT_ID}" --resource-type=uptime-url \
      --resource-labels="host=${assistant_host},project_id=${PROJECT_ID}" \
      --protocol=https --path=/health --period="${UPTIME_CHECK_PERIOD}" \
      --timeout=10 --validate-ssl=true
  fi
else
  while IFS= read -r uptime; do
    [[ -z "${uptime}" ]] || gcloud monitoring uptime delete "${uptime}" \
      --project="${PROJECT_ID}" --quiet
  done < <(gcloud monitoring uptime list-configs --project="${PROJECT_ID}" \
    --format=json | "${PYTHON_BIN}" -c \
    "import json,sys; [print(x['name']) for x in json.load(sys.stdin) if x.get('displayName') == 'Productivity Intelligence hosted liveness']")
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
    --documentation="Productivity Intelligence Platform alert for ${PROJECT_ID}. Inspect service and dependency logs before rollback."
}

create_threshold_policy \
  'Productivity Intelligence 5xx rate' 'Cloud Run 5xx responses' \
  "resource.type=\"cloud_run_revision\" AND resource.label.\"service_name\"=\"${ASSISTANT_SERVICE_NAME}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.label.\"response_code_class\"=\"5xx\"" \
  "{\"alignmentPeriod\":\"${MONITORING_ALIGNMENT_SECONDS}s\",\"perSeriesAligner\":\"ALIGN_RATE\",\"crossSeriesReducer\":\"REDUCE_SUM\"}" \
  "${MONITORING_5XX_RATE_THRESHOLD}"

create_threshold_policy \
  'Productivity Intelligence p95 latency' 'Cloud Run p95 latency above 2s' \
  "resource.type=\"cloud_run_revision\" AND resource.label.\"service_name\"=\"${ASSISTANT_SERVICE_NAME}\" AND metric.type=\"run.googleapis.com/request_latencies\"" \
  "{\"alignmentPeriod\":\"${MONITORING_ALIGNMENT_SECONDS}s\",\"perSeriesAligner\":\"ALIGN_PERCENTILE_95\",\"crossSeriesReducer\":\"REDUCE_MAX\"}" \
  "${MONITORING_P95_LATENCY_MS}"

create_threshold_policy \
  'Productivity Intelligence AlloyDB connections' \
  "AlloyDB connections above ${MONITORING_ALLOYDB_CONNECTION_THRESHOLD}" \
  'resource.type="alloydb.googleapis.com/Instance" AND metric.type="alloydb.googleapis.com/instance/postgres/total_connections"' \
  "{\"alignmentPeriod\":\"${MONITORING_ALIGNMENT_SECONDS}s\",\"perSeriesAligner\":\"ALIGN_MAX\",\"crossSeriesReducer\":\"REDUCE_MAX\"}" \
  "${MONITORING_ALLOYDB_CONNECTION_THRESHOLD}"

for metric in startup_failures toolbox_authorization_failures mcp_failures bigquery_errors; do
  if [[ "${ENABLE_LOG_METRICS}" != "true" ]]; then
    gcloud logging metrics delete "productivity_${metric}" --project="${PROJECT_ID}" \
      --quiet >/dev/null 2>&1 || true
    continue
  fi
  if ! gcloud logging metrics describe "productivity_${metric}" \
      --project="${PROJECT_ID}" >/dev/null 2>&1; then
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
  fi
done

exclusion_name="productivity-health-success"
if [[ "${EXCLUDE_HEALTH_CHECK_LOGS}" == "true" ]]; then
  exclusion_filter="resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${ASSISTANT_SERVICE_NAME}\" AND httpRequest.status<400 AND (httpRequest.requestUrl:\"/health\" OR httpRequest.requestUrl:\"/healthz\" OR httpRequest.requestUrl:\"/readyz\")"
  if gcloud logging sinks describe _Default --project="${PROJECT_ID}" \
      --format='value(exclusions.name)' | grep -Fq "${exclusion_name}"; then
    gcloud logging sinks update _Default --project="${PROJECT_ID}" \
      --update-exclusion="name=${exclusion_name},filter=${exclusion_filter}"
  else
    gcloud logging sinks update _Default --project="${PROJECT_ID}" \
      --add-exclusion="name=${exclusion_name},description=Exclude successful productivity health requests,filter=${exclusion_filter}"
  fi
else
  gcloud logging sinks update _Default --project="${PROJECT_ID}" \
    --remove-exclusions="${exclusion_name}" >/dev/null 2>&1 || true
fi

echo "[OK] Monitoring checks and error metrics configured."
