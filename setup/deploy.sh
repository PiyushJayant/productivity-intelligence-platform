#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=setup/common.sh
source "${SCRIPT_DIR}/common.sh"

ACTION="${1:-full}"
if [[ "${ACTION}" != "suspend" && "${ACTION}" != "cost-status" ]]; then
  require_phase5
fi
BUILD_TAG_FILE="${REPO_ROOT}/.deploy-build-tag"
if [[ "${ACTION}" == "build" || "${ACTION}" == "full" ]]; then
  BUILD_TAG="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
elif [[ "${ACTION}" =~ ^(toolbox|migrate|assistant|lifecycle|privacy|privacy-erase|deploy)$ ]]; then
  if [[ -f "${BUILD_TAG_FILE}" ]]; then
    BUILD_TAG="$(<"${BUILD_TAG_FILE}")"
  else
    echo "Error: no successful build tag found. Run '$0 build' first." >&2
    exit 1
  fi
else
  BUILD_TAG="not-required"
fi
IMAGE_ROOT="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}"
ASSISTANT_IMAGE="${IMAGE_ROOT}/${ASSISTANT_SERVICE_NAME}:${BUILD_TAG}"
TOOLBOX_IMAGE="${IMAGE_ROOT}/${TOOLBOX_SERVICE_NAME}:${BUILD_TAG}"
MIGRATION_IMAGE="${IMAGE_ROOT}/${MIGRATION_JOB_NAME}:${BUILD_TAG}"

image_exists() {
  gcloud artifacts docker images describe "$1" --project="${PROJECT_ID}" \
    >/dev/null 2>&1
}

build_image() {
  local image="$1" config="$2"
  if [[ "${SKIP_EXISTING_IMAGES}" == "true" ]] && image_exists "${image}"; then
    echo "[SKIP] Existing immutable image: ${image}"
    return
  fi
  gcloud builds submit "${REPO_ROOT}" --project="${PROJECT_ID}" \
    --config="${config}" --substitutions="_IMAGE_URI=${image}"
}

build_images() {
  build_image "${TOOLBOX_IMAGE}" "${REPO_ROOT}/cloudbuild.toolbox.yaml"
  build_image "${ASSISTANT_IMAGE}" "${REPO_ROOT}/cloudbuild.assistant.yaml"
  build_image "${MIGRATION_IMAGE}" "${REPO_ROOT}/cloudbuild.migrate.yaml"
  printf '%s\n' "${BUILD_TAG}" >"${BUILD_TAG_FILE}"
}

deploy_toolbox() {
  local app_secret_version
  app_secret_version="$(secret_version "${APP_DB_SECRET}")"
  [[ -n "${app_secret_version}" ]] || {
    echo "Error: ${APP_DB_SECRET} has no enabled version." >&2
    exit 1
  }

  gcloud run deploy "${TOOLBOX_SERVICE_NAME}" --image="${TOOLBOX_IMAGE}" \
    --region="${REGION}" --project="${PROJECT_ID}" --platform=managed \
    --service-account="${TOOLBOX_SA}" --no-allow-unauthenticated --port=5000 \
    --cpu="${TOOLBOX_CPU}" --memory="${TOOLBOX_MEMORY}" \
    --min="${TOOLBOX_MIN_INSTANCES}" --max="${TOOLBOX_MAX_INSTANCES}" \
    --concurrency="${TOOLBOX_CONCURRENCY}" --timeout="${TOOLBOX_TIMEOUT}" \
    --cpu-throttling --labels="${RESOURCE_LABELS}" \
    --network="${VPC_NETWORK}" --subnet="${VPC_SUBNET}" \
    --vpc-egress=private-ranges-only \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},ALLOYDB_REGION=${ALLOYDB_REGION},ALLOYDB_CLUSTER=${ALLOYDB_CLUSTER},ALLOYDB_INSTANCE=${ALLOYDB_INSTANCE},ALLOYDB_IP_TYPE=${ALLOYDB_IP_TYPE},ALLOYDB_DATABASE=${ALLOYDB_DATABASE},ALLOYDB_USER=${ALLOYDB_USER},EMBEDDING_MODEL=${EMBEDDING_MODEL},DEFAULT_PAGE_SIZE=${DEFAULT_PAGE_SIZE},DEFAULT_TIMEZONE=${DEFAULT_TIMEZONE}" \
    --set-secrets="ALLOYDB_PASSWORD=${APP_DB_SECRET}:${app_secret_version}"

  gcloud run services add-iam-policy-binding "${TOOLBOX_SERVICE_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --member="serviceAccount:${ASSISTANT_SA}" --role=roles/run.invoker --quiet
}

run_migration() {
  local admin_version app_version analytics_version privacy_version cdc_version instance_uri
  admin_version="$(secret_version "${ADMIN_DB_SECRET}")"
  app_version="$(secret_version "${APP_DB_SECRET}")"
  analytics_version="$(secret_version "${ANALYTICS_DB_SECRET}")"
  privacy_version="$(secret_version "${PRIVACY_DB_SECRET}")"
  cdc_version="$(secret_version "${CDC_DB_SECRET}")"
  instance_uri="projects/${PROJECT_ID}/locations/${REGION}/clusters/${ALLOYDB_CLUSTER}/instances/${ALLOYDB_INSTANCE}"

  gcloud run jobs deploy "${MIGRATION_JOB_NAME}" --image="${MIGRATION_IMAGE}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --service-account="${MIGRATION_SA}" --network="${VPC_NETWORK}" \
    --subnet="${VPC_SUBNET}" --vpc-egress=private-ranges-only \
    --cpu="${MIGRATION_CPU}" --memory="${MIGRATION_MEMORY}" \
    --labels="${RESOURCE_LABELS}" \
    --command=python --args=-m,setup.migrate \
    --set-env-vars="ALLOYDB_INSTANCE_URI=${instance_uri},ALLOYDB_DATABASE=${ALLOYDB_DATABASE},ADMIN_DB_USER=${ADMIN_DB_USER},ALLOYDB_USER=${ALLOYDB_USER},ANALYTICS_DB_USER=${ANALYTICS_DB_USER},PRIVACY_DB_USER=${PRIVACY_DB_USER},CDC_DB_USER=${CDC_DB_USER},EMBEDDING_MODEL=${EMBEDDING_MODEL},EMBEDDING_DIMENSIONS=${EMBEDDING_DIMENSIONS},SEED_DEMO=${SEED_DEMO},AUTH_MODE=${AUTH_MODE},IDENTITY_PLATFORM_PROJECT_ID=${IDENTITY_PLATFORM_PROJECT_ID},DEFAULT_TENANT_ID=${DEFAULT_TENANT_ID},DEMO_SUBJECT_ID=${DEMO_SUBJECT_ID},BOOTSTRAP_IDP_SUBJECT=${BOOTSTRAP_IDP_SUBJECT},ANALYTICS_QUERY_TIMEOUT_SECONDS=${ANALYTICS_QUERY_TIMEOUT_SECONDS},DATASTREAM_PUBLICATION=${DATASTREAM_PUBLICATION},DATASTREAM_REPLICATION_SLOT=${DATASTREAM_REPLICATION_SLOT},DATASTREAM_SOURCE_SCHEMA=${DATASTREAM_SOURCE_SCHEMA},DATASTREAM_SOURCE_TABLE=${DATASTREAM_SOURCE_TABLE}" \
    --set-secrets="ADMIN_DB_PASSWORD=${ADMIN_DB_SECRET}:${admin_version},APP_DB_PASSWORD=${APP_DB_SECRET}:${app_version},ANALYTICS_DB_PASSWORD=${ANALYTICS_DB_SECRET}:${analytics_version},PRIVACY_DB_PASSWORD=${PRIVACY_DB_SECRET}:${privacy_version},CDC_DB_PASSWORD=${CDC_DB_SECRET}:${cdc_version}" \
    --max-retries=0 --task-timeout="${MIGRATION_TIMEOUT}s"
  gcloud run jobs execute "${MIGRATION_JOB_NAME}" --region="${REGION}" \
    --project="${PROJECT_ID}" --wait
}

ensure_scheduler_job() {
  local scheduler_job="$1" run_job="$2" schedule="$3" timezone="${4:-${LIFECYCLE_TIMEZONE}}"
  local run_uri="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${run_job}:run"
  local -a shared_args=(
    "--location=${REGION}"
    "--project=${PROJECT_ID}"
    "--schedule=${schedule}"
    "--time-zone=${timezone}"
    "--uri=${run_uri}"
    "--http-method=POST"
    "--message-body={}"
    "--oauth-service-account-email=${SCHEDULER_SA}"
    "--oauth-token-scope=https://www.googleapis.com/auth/cloud-platform"
    "--max-retry-attempts=2"
    "--attempt-deadline=60s"
  )
  if gcloud scheduler jobs describe "${scheduler_job}" --location="${REGION}" \
      --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud scheduler jobs update http "${scheduler_job}" "${shared_args[@]}" \
      --update-headers=Content-Type=application/json
  else
    gcloud scheduler jobs create http "${scheduler_job}" "${shared_args[@]}" \
      --headers=Content-Type=application/json
  fi
}

deploy_lifecycle_automation() {
  local action job_name scheduler_job additional_instances=""
  if [[ "${ENABLE_SCHEDULED_LIFECYCLE}" != "true" ]]; then
    for action in resume suspend; do
      scheduler_job="${LIFECYCLE_JOB_NAME}-${action}"
      gcloud scheduler jobs delete "${scheduler_job}" --location="${REGION}" \
        --project="${PROJECT_ID}" --quiet >/dev/null 2>&1 || true
      gcloud run jobs delete "${scheduler_job}" --region="${REGION}" \
        --project="${PROJECT_ID}" --quiet >/dev/null 2>&1 || true
    done
    echo "[SKIP] Scheduled lifecycle automation is disabled in .env."
    return
  fi

  if [[ "${ENABLE_ALLOYDB_READ_POOL}" == "true" ]]; then
    additional_instances="${ALLOYDB_READ_POOL}"
  fi

  for action in resume suspend; do
    job_name="${LIFECYCLE_JOB_NAME}-${action}"
    gcloud run jobs deploy "${job_name}" --image="${MIGRATION_IMAGE}" \
      --region="${REGION}" --project="${PROJECT_ID}" \
      --service-account="${LIFECYCLE_SA}" --command=python \
      --args="-m,setup.lifecycle,--action=${action}" \
      --cpu=1 --memory=512Mi --max-retries=1 --task-timeout=300s \
      --labels="${RESOURCE_LABELS}" \
      --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},ALLOYDB_REGION=${ALLOYDB_REGION},ALLOYDB_CLUSTER=${ALLOYDB_CLUSTER},ALLOYDB_INSTANCE=${ALLOYDB_INSTANCE},ALLOYDB_ADDITIONAL_INSTANCES=${additional_instances}"
    gcloud run jobs add-iam-policy-binding "${job_name}" --region="${REGION}" \
      --project="${PROJECT_ID}" --member="serviceAccount:${SCHEDULER_SA}" \
      --role=roles/run.invoker --quiet >/dev/null
  done
  ensure_scheduler_job "${LIFECYCLE_JOB_NAME}-resume" \
    "${LIFECYCLE_JOB_NAME}-resume" "${LIFECYCLE_RESUME_CRON}"
  ensure_scheduler_job "${LIFECYCLE_JOB_NAME}-suspend" \
    "${LIFECYCLE_JOB_NAME}-suspend" "${LIFECYCLE_SUSPEND_CRON}"
  echo "[OK] Scheduled AlloyDB lifecycle automation configured."
}

deploy_privacy_job() {
  local privacy_version pseudonymization_version instance_uri scheduler_job
  privacy_version="$(secret_version "${PRIVACY_DB_SECRET}")"
  pseudonymization_version="$(secret_version "${PSEUDONYMIZATION_SECRET}")"
  instance_uri="projects/${PROJECT_ID}/locations/${REGION}/clusters/${ALLOYDB_CLUSTER}/instances/${ALLOYDB_INSTANCE}"
  scheduler_job="${PRIVACY_JOB_NAME}-retention"
  [[ -n "${privacy_version}" && -n "${pseudonymization_version}" ]] || {
    echo "Error: privacy job secrets have no enabled numeric version." >&2
    exit 1
  }
  gcloud run jobs deploy "${PRIVACY_JOB_NAME}" --image="${MIGRATION_IMAGE}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --service-account="${PRIVACY_SA}" --network="${VPC_NETWORK}" \
    --subnet="${VPC_SUBNET}" --vpc-egress=private-ranges-only \
    --command=python --args="-m,setup.privacy_job,retention" \
    --cpu=1 --memory=512Mi --max-retries=1 --task-timeout=900s \
    --labels="${RESOURCE_LABELS}" \
    --set-env-vars="ALLOYDB_INSTANCE_URI=${instance_uri},ALLOYDB_DATABASE=${ALLOYDB_DATABASE},PRIVACY_DB_USER=${PRIVACY_DB_USER},PRIVACY_RETENTION_DAYS=${PRIVACY_RETENTION_DAYS},PRIVACY_BATCH_SIZE=${PRIVACY_BATCH_SIZE},PRIVACY_MAX_BATCHES=${PRIVACY_MAX_BATCHES}" \
    --set-secrets="PRIVACY_DB_PASSWORD=${PRIVACY_DB_SECRET}:${privacy_version},PSEUDONYMIZATION_KEY=${PSEUDONYMIZATION_SECRET}:${pseudonymization_version}"
  gcloud run jobs add-iam-policy-binding "${PRIVACY_JOB_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --member="serviceAccount:${SCHEDULER_SA}" --role=roles/run.invoker \
    --quiet >/dev/null
  if [[ "${ENABLE_SCHEDULED_PRIVACY}" == "true" ]]; then
    ensure_scheduler_job "${scheduler_job}" "${PRIVACY_JOB_NAME}" \
      "${PRIVACY_RETENTION_CRON}" "${PRIVACY_TIMEZONE}"
  else
    gcloud scheduler jobs delete "${scheduler_job}" --location="${REGION}" \
      --project="${PROJECT_ID}" --quiet >/dev/null 2>&1 || true
    echo "[SKIP] Scheduled privacy retention is disabled in .env."
  fi
}

execute_privacy_erasure() {
  local request_id="${1:-}" confirmation
  [[ "${request_id}" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$ ]] || {
    echo "Error: privacy-erase requires a canonical request UUID." >&2
    exit 2
  }
  read -r -p "Type ERASE_REQUEST_${request_id} to execute the irreversible erasure: " confirmation
  [[ "${confirmation}" == "ERASE_REQUEST_${request_id}" ]] || {
    echo "Privacy erasure cancelled." >&2
    exit 1
  }
  gcloud run jobs execute "${PRIVACY_JOB_NAME}" --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --args="-m,setup.privacy_job,erase,--request-id=${request_id}" --wait
}

ensure_bigquery_connection() {
  local payload response password_file token resource connection_url
  local connection_exists="false"
  if "${BQ_BIN}" show --connection --location="${REGION}" \
      --project_id="${PROJECT_ID}" "${BIGQUERY_CONNECTION_ID}" >/dev/null 2>&1; then
    connection_exists="true"
  fi
  payload="$(mktemp)"
  response="$(mktemp)"
  password_file="$(mktemp)"
  trap 'rm -f "${payload}" "${response}" "${password_file}"' RETURN
  chmod 600 "${payload}" "${response}" "${password_file}"
  gcloud secrets versions access \
    "$(secret_version "${ANALYTICS_DB_SECRET}")" --secret="${ANALYTICS_DB_SECRET}" \
    --project="${PROJECT_ID}" --out-file="${password_file}" >/dev/null
  resource="//alloydb.googleapis.com/projects/${PROJECT_ID}/locations/${REGION}/clusters/${ALLOYDB_CLUSTER}/instances/${ANALYTICS_ALLOYDB_INSTANCE}"
  "${PYTHON_BIN}" - "${payload}" "${resource}" "${ALLOYDB_DATABASE}" \
      "${ANALYTICS_DB_USER}" "${password_file}" <<'PY'
import json, sys
path, resource, database, username, password_path = sys.argv[1:]
with open(password_path, encoding="utf-8") as secret_stream:
    password = secret_stream.read()
with open(path, "w", encoding="utf-8") as stream:
    json.dump({
        "friendlyName": "Productivity AlloyDB live analytics",
        "configuration": {
            "connectorId": "google-alloydb",
            "asset": {"database": database, "googleCloudResource": resource},
            "authentication": {"usernamePassword": {
                "username": username, "password": {"plaintext": password}
            }},
        },
    }, stream)
PY
  token="$(gcloud auth print-access-token)"
  connection_url="https://bigqueryconnection.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/connections"
  if [[ "${connection_exists}" == "true" ]]; then
    curl -fsS -X PATCH \
      "${connection_url}/${BIGQUERY_CONNECTION_ID}?updateMask=friendlyName,configuration" \
      -H "Authorization: Bearer ${token}" -H 'Content-Type: application/json' \
      --data-binary "@${payload}" >"${response}"
  else
    curl -fsS -X POST \
      "${connection_url}?connectionId=${BIGQUERY_CONNECTION_ID}" \
      -H "Authorization: Bearer ${token}" -H 'Content-Type: application/json' \
      --data-binary "@${payload}" >"${response}"
  fi
  unset token

  local connection_sa
  connection_sa="$("${PYTHON_BIN}" - "${response}" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print(data.get("configuration", {}).get("authentication", {}).get("serviceAccount", ""))
PY
)"
  [[ -n "${connection_sa}" ]] || {
    echo "Error: BigQuery connection response did not contain a service account." >&2
    exit 1
  }
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${connection_sa}" --role=roles/alloydb.client \
    --condition=None --quiet >/dev/null
}

deploy_assistant() {
  local toolbox_url pseudonymization_version
  local -a traffic_args=(--tag=candidate)
  toolbox_url="$(gcloud run services describe "${TOOLBOX_SERVICE_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" --format='value(status.url)')"
  [[ "${toolbox_url}" == https://* ]] || {
    echo "Error: deployed Toolbox URL is invalid." >&2
    exit 1
  }
  pseudonymization_version="$(secret_version "${PSEUDONYMIZATION_SECRET}")"
  [[ "${pseudonymization_version}" =~ ^[0-9]+$ ]] || {
    echo "Error: no numeric pseudonymization secret version is available." >&2
    exit 1
  }

  if gcloud run services describe "${ASSISTANT_SERVICE_NAME}" \
      --region="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    traffic_args+=(--no-traffic)
  fi

  gcloud run deploy "${ASSISTANT_SERVICE_NAME}" --image="${ASSISTANT_IMAGE}" \
    --region="${REGION}" --project="${PROJECT_ID}" --platform=managed \
    --service-account="${ASSISTANT_SA}" --allow-unauthenticated \
    --cpu="${ASSISTANT_CPU}" --memory="${ASSISTANT_MEMORY}" \
    --min="${ASSISTANT_MIN_INSTANCES}" --max="${ASSISTANT_MAX_INSTANCES}" \
    --concurrency="${ASSISTANT_CONCURRENCY}" --timeout="${ASSISTANT_TIMEOUT}" \
    --cpu-throttling --labels="${RESOURCE_LABELS}" \
    "${traffic_args[@]}" \
    --set-env-vars="APP_MODE=${APP_MODE},GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${VERTEX_LOCATION},REGION=${REGION},GOOGLE_GENAI_USE_VERTEXAI=${GOOGLE_GENAI_USE_VERTEXAI},MODEL=${MODEL},EMBEDDING_MODEL=${EMBEDDING_MODEL},TOOLBOX_URL=${toolbox_url},TOOLBOX_AUDIENCE=${toolbox_url},BIGQUERY_MCP_URL=${BIGQUERY_MCP_URL},BIGQUERY_DATASET=${BIGQUERY_DATASET},BIGQUERY_CONNECTION_ID=${BIGQUERY_CONNECTION_ID},BIGQUERY_ANALYTICS_PROCEDURE=${BIGQUERY_ANALYTICS_PROCEDURE},ANALYTICS_BACKEND=${ANALYTICS_BACKEND},BIGQUERY_NATIVE_TVF=${BIGQUERY_NATIVE_TVF},ANALYTICS_RETRY_ATTEMPTS=${ANALYTICS_RETRY_ATTEMPTS},ANALYTICS_RETRY_BASE_SECONDS=${ANALYTICS_RETRY_BASE_SECONDS},ANALYTICS_RETRY_MAX_SECONDS=${ANALYTICS_RETRY_MAX_SECONDS},PRIVACY_RETENTION_DAYS=${PRIVACY_RETENTION_DAYS},TAXONOMY_VERSION=${TAXONOMY_VERSION},ROUTER_MAX_OUTPUT_TOKENS=${ROUTER_MAX_OUTPUT_TOKENS},ROUTER_THINKING_BUDGET=${ROUTER_THINKING_BUDGET},SPECIALIST_MAX_OUTPUT_TOKENS=${SPECIALIST_MAX_OUTPUT_TOKENS},SPECIALIST_THINKING_BUDGET=${SPECIALIST_THINKING_BUDGET},ANALYTICS_MAX_OUTPUT_TOKENS=${ANALYTICS_MAX_OUTPUT_TOKENS},ANALYTICS_THINKING_BUDGET=${ANALYTICS_THINKING_BUDGET},ANALYTICS_MAX_RANGE_DAYS=${ANALYTICS_MAX_RANGE_DAYS},ANALYTICS_QUERY_TIMEOUT_SECONDS=${ANALYTICS_QUERY_TIMEOUT_SECONDS},ANALYTICS_MAX_BYTES_BILLED=${ANALYTICS_MAX_BYTES_BILLED},AGENT_CONTEXT_MAX_EVENTS=${AGENT_CONTEXT_MAX_EVENTS},MODEL_TEMPERATURE=${MODEL_TEMPERATURE},DEFAULT_TIMEZONE=${DEFAULT_TIMEZONE},DEFAULT_PAGE_SIZE=${DEFAULT_PAGE_SIZE},LOG_LEVEL=${LOG_LEVEL},STRUCTURED_LOGGING=${STRUCTURED_LOGGING},ENABLE_REQUEST_LOGGING=${ENABLE_REQUEST_LOGGING},REQUEST_ID_HEADER=${REQUEST_ID_HEADER},AUTH_MODE=${AUTH_MODE},IDENTITY_PLATFORM_PROJECT_ID=${IDENTITY_PLATFORM_PROJECT_ID},IDENTITY_PLATFORM_TENANT_ID=${IDENTITY_PLATFORM_TENANT_ID:-},IDENTITY_TENANT_CLAIM=${IDENTITY_TENANT_CLAIM},IDENTITY_ROLE_CLAIM=${IDENTITY_ROLE_CLAIM},DEFAULT_TENANT_ID=${DEFAULT_TENANT_ID},DEMO_SUBJECT_ID=${DEMO_SUBJECT_ID},AUTH_CLOCK_SKEW_SECONDS=${AUTH_CLOCK_SKEW_SECONDS}" \
    --set-secrets="PSEUDONYMIZATION_KEY=${PSEUDONYMIZATION_SECRET}:${pseudonymization_version}"
}

setup_analytics() {
  GOOGLE_CLOUD_PROJECT="${PROJECT_ID}" REGION="${REGION}" \
    BIGQUERY_DATASET="${BIGQUERY_DATASET}" \
    BIGQUERY_CONNECTION_ID="${BIGQUERY_CONNECTION_ID}" \
    BIGQUERY_ANALYTICS_PROCEDURE="${BIGQUERY_ANALYTICS_PROCEDURE}" \
    ANALYTICS_MAX_RANGE_DAYS="${ANALYTICS_MAX_RANGE_DAYS}" \
    DEFAULT_TIMEZONE="${DEFAULT_TIMEZONE}" \
    "${PYTHON_BIN}" "${SCRIPT_DIR}/bigquery_setup.py"
}

alloydb_details() {
  local instance="${1:-${ALLOYDB_INSTANCE}}"
  gcloud alloydb instances describe "${instance}" \
    --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" --project="${PROJECT_ID}" \
    --format='value(state,activationPolicy,machineConfig.machineType,availabilityType)'
}

wait_for_alloydb_state() {
  local instance="$1" expected="$2" elapsed=0 state=""
  while (( elapsed < ALLOYDB_STATE_TIMEOUT_SECONDS )); do
    state="$(gcloud alloydb instances describe "${instance}" \
      --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" --project="${PROJECT_ID}" \
      --format='value(state)' 2>/dev/null || true)"
    [[ "${state}" == "${expected}" ]] && return
    sleep 10
    elapsed=$((elapsed + 10))
  done
  echo "Error: AlloyDB ${instance} did not reach ${expected} within ${ALLOYDB_STATE_TIMEOUT_SECONDS}s." >&2
  exit 1
}

resume_alloydb() {
  local instance state activation _machine _availability
  local -a instances=("${ALLOYDB_INSTANCE}")
  [[ "${ENABLE_ALLOYDB_READ_POOL}" == "true" ]] && instances+=("${ALLOYDB_READ_POOL}")
  for instance in "${instances[@]}"; do
    read -r state activation _machine _availability < <(alloydb_details "${instance}")
    if [[ "${state}" == "READY" && "${activation}" == "ALWAYS" ]]; then
      echo "[OK] AlloyDB ${instance} is already running."
      continue
    fi
    gcloud alloydb instances update "${instance}" \
      --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
      --project="${PROJECT_ID}" --activation-policy=ALWAYS --quiet
    wait_for_alloydb_state "${instance}" READY
    echo "[OK] AlloyDB ${instance} resumed."
  done
}

suspend_alloydb() {
  local instance state activation _machine _availability confirmation
  local -a instances=("${ALLOYDB_INSTANCE}")
  if [[ "${COST_PROFILE}" == "production" ]]; then
    read -r -p "Type ${PROJECT_ID} to suspend the production database: " confirmation
    [[ "${confirmation}" == "${PROJECT_ID}" ]] || {
      echo "Suspension cancelled."
      exit 1
    }
  fi
  if [[ "${ALLOYDB_READ_POOL}" != "${ALLOYDB_INSTANCE}" ]] &&
      gcloud alloydb instances describe "${ALLOYDB_READ_POOL}" \
        --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
        --project="${PROJECT_ID}" >/dev/null 2>&1; then
    instances+=("${ALLOYDB_READ_POOL}")
  fi
  for instance in "${instances[@]}"; do
    read -r state activation _machine _availability < <(alloydb_details "${instance}")
    if [[ "${state}" == "STOPPED" || "${activation}" == "NEVER" ]]; then
      echo "[OK] AlloyDB ${instance} is already suspended."
      continue
    fi
    gcloud alloydb instances update "${instance}" \
      --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
      --project="${PROJECT_ID}" --activation-policy=NEVER --quiet
    wait_for_alloydb_state "${instance}" STOPPED
    echo "[OK] AlloyDB ${instance} suspended; instance compute billing is stopped."
  done
}

set_service_min_instances() {
  local service="$1" desired="$2" maximum="$3" current
  current="$(gcloud run services describe "${service}" --region="${REGION}" \
    --project="${PROJECT_ID}" --format=json | "${PYTHON_BIN}" -c \
    "import json,sys; d=json.load(sys.stdin); root=d.get('metadata',{}).get('annotations',{}); rev=d.get('spec',{}).get('template',{}).get('metadata',{}).get('annotations',{}); print(root.get('run.googleapis.com/minScale',rev.get('autoscaling.knative.dev/minScale','0')))")"
  [[ "${current}" == "${desired}" ]] && return
  gcloud run services update "${service}" --region="${REGION}" \
    --project="${PROJECT_ID}" --min="${desired}" --max="${maximum}" --quiet
}

remove_assistant_public_access() {
  gcloud run services remove-iam-policy-binding "${ASSISTANT_SERVICE_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" --member=allUsers \
    --role=roles/run.invoker --quiet >/dev/null 2>&1 || true
}

restore_assistant_public_access() {
  gcloud run services add-iam-policy-binding "${ASSISTANT_SERVICE_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" --member=allUsers \
    --role=roles/run.invoker --quiet >/dev/null
}

set_schedulers_state() {
  local action="$1" scheduler_job
  shift
  for scheduler_job in "$@"; do
    if gcloud scheduler jobs describe "${scheduler_job}" --location="${REGION}" \
        --project="${PROJECT_ID}" >/dev/null 2>&1; then
      gcloud scheduler jobs "${action}" "${scheduler_job}" --location="${REGION}" \
        --project="${PROJECT_ID}" --quiet >/dev/null
    fi
  done
}

remove_hosted_uptime_check() {
  local uptime
  while IFS= read -r uptime; do
    [[ -z "${uptime}" ]] || gcloud monitoring uptime delete "${uptime}" \
      --project="${PROJECT_ID}" --quiet >/dev/null
  done < <(gcloud monitoring uptime list-configs --project="${PROJECT_ID}" \
    --format=json | "${PYTHON_BIN}" -c \
    "import json,sys; [print(x['name']) for x in json.load(sys.stdin) if x.get('displayName') == 'Productivity Intelligence hosted liveness']")
}

suspend_application() {
  remove_assistant_public_access
  set_schedulers_state pause "${LIFECYCLE_JOB_NAME}-resume" \
    "${LIFECYCLE_JOB_NAME}-suspend" "${PRIVACY_JOB_NAME}-retention"
  remove_hosted_uptime_check
  set_service_min_instances \
    "${ASSISTANT_SERVICE_NAME}" 0 "${ASSISTANT_MAX_INSTANCES}"
  set_service_min_instances \
    "${TOOLBOX_SERVICE_NAME}" 0 "${TOOLBOX_MAX_INSTANCES}"
  suspend_alloydb
  echo "[OK] Application quiesced: public invocation disabled and compute scaled to zero."
  echo "[INFO] Retained databases, backups, images, logs, and secrets may still incur storage charges."
}

resume_application() {
  resume_alloydb
  set_service_min_instances \
    "${TOOLBOX_SERVICE_NAME}" "${TOOLBOX_MIN_INSTANCES}" "${TOOLBOX_MAX_INSTANCES}"
  set_service_min_instances \
    "${ASSISTANT_SERVICE_NAME}" "${ASSISTANT_MIN_INSTANCES}" "${ASSISTANT_MAX_INSTANCES}"
  restore_assistant_public_access
  if [[ "${ENABLE_SCHEDULED_LIFECYCLE}" == "true" ]]; then
    set_schedulers_state resume "${LIFECYCLE_JOB_NAME}-resume" \
      "${LIFECYCLE_JOB_NAME}-suspend"
  fi
  if [[ "${ENABLE_SCHEDULED_PRIVACY}" == "true" ]]; then
    set_schedulers_state resume "${PRIVACY_JOB_NAME}-retention"
  fi
  if [[ "${ENABLE_MONITORING}" == "true" ]]; then
    "${SCRIPT_DIR}/monitoring.sh"
  fi
  echo "[OK] Application resumed and public invocation restored."
}

cost_status() {
  local state activation machine availability monthly
  read -r state activation machine availability < <(alloydb_details)
  monthly="$("${PYTHON_BIN}" -c \
    "print(f'{float(\"${ALLOYDB_ESTIMATED_HOURLY_USD}\") * 730:.2f}')")"
  cat <<EOF
Cost profile: ${COST_PROFILE}
Project: ${PROJECT_ID}
AlloyDB: state=${state}, activation=${activation}, machine=${machine}, availability=${availability}
Configured running estimate: USD ${ALLOYDB_ESTIMATED_HOURLY_USD}/hour (USD ${monthly}/730-hour month)
Cloud Run bounds: assistant ${ASSISTANT_MIN_INSTANCES}-${ASSISTANT_MAX_INSTANCES}, toolbox ${TOOLBOX_MIN_INSTANCES}-${TOOLBOX_MAX_INSTANCES}
EOF
}

verify_candidate() {
  local toolbox_url assistant_url unauth_status identity_token
  toolbox_url="$(gcloud run services describe "${TOOLBOX_SERVICE_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" --format='value(status.url)')"
  unauth_status="$(curl -sS -o /dev/null -w '%{http_code}' "${toolbox_url}" || true)"
  [[ "${unauth_status}" == "401" || "${unauth_status}" == "403" ]] || {
    echo "Error: Toolbox accepted unauthenticated traffic (HTTP ${unauth_status})." >&2
    exit 1
  }
  identity_token="$(gcloud auth print-identity-token \
    --impersonate-service-account="${ASSISTANT_SA}" --audiences="${toolbox_url}")"
  curl -fsS -H "Authorization: Bearer ${identity_token}" "${toolbox_url}" >/dev/null
  unset identity_token

  assistant_url="$(gcloud run services describe "${ASSISTANT_SERVICE_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" --format=json | \
    "${PYTHON_BIN}" -c "import json,sys; d=json.load(sys.stdin); print(next(x['url'] for x in d['status']['traffic'] if x.get('tag')=='candidate'))")"
  local health_status readiness_file
  health_status="$(curl -sS -o /dev/null -w '%{http_code}' "${assistant_url}/healthz")"
  if [[ "${health_status}" == "404" ]]; then
    # Google Front End reserves exact /healthz on run.app services.
    curl -fsS "${assistant_url}/health" >/dev/null
  elif [[ "${health_status}" != "200" ]]; then
    echo "Error: candidate liveness failed with HTTP ${health_status}." >&2
    exit 1
  fi
  readiness_file="$(mktemp)"
  trap 'rm -f "${readiness_file}"' RETURN
  curl -fsS "${assistant_url}/readyz" >"${readiness_file}"
  "${PYTHON_BIN}" - "${readiness_file}" "${APP_MODE}" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
expected = (
    ["analytics_agent"]
    if sys.argv[2] == "prototype"
    else ["analytics_agent", "calendar_agent", "notes_agent", "task_agent"]
)
if not data.get("ready") or sorted(data.get("loaded_agents", [])) != expected:
    raise SystemExit(f"candidate readiness mismatch: {data}")
PY
  if [[ "${APP_MODE}" == "full" ]]; then
    local -a assistant_smoke_arg=()
    if [[ "${AUTH_MODE}" == "disabled" ]]; then
      assistant_smoke_arg=("--assistant-url=${assistant_url}")
    else
      echo "[SKIP] Conversational smoke requires an end-user Identity Platform token."
    fi
    "${PYTHON_BIN}" "${SCRIPT_DIR}/smoke_test.py" \
      --project="${PROJECT_ID}" --region="${REGION}" \
      --toolbox-url="${toolbox_url}" --service-account="${ASSISTANT_SA}" \
      "${assistant_smoke_arg[@]}" --dataset="${BIGQUERY_DATASET}" \
      --connection="${BIGQUERY_CONNECTION_ID}" \
      --timezone="${DEFAULT_TIMEZONE}" --auth-mode="${AUTH_MODE}" \
      --identity-project="${IDENTITY_PLATFORM_PROJECT_ID}" \
      --bootstrap-subject="${BOOTSTRAP_IDP_SUBJECT}" \
      --tenant-id="${DEFAULT_TENANT_ID}" \
      --demo-subject-id="${DEMO_SUBJECT_ID}"
  else
    echo "[SKIP] CRUD smoke checks are unavailable in prototype mode."
  fi
  echo "[OK] Candidate verified: ${assistant_url}"
}

promote() {
  gcloud run services update-traffic "${ASSISTANT_SERVICE_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" --to-tags=candidate=100
  gcloud run services describe "${ASSISTANT_SERVICE_NAME}" --region="${REGION}" \
    --project="${PROJECT_ID}" --format='value(status.url)'
}

rollback() {
  local revision="${2:-}"
  [[ -n "${revision}" ]] || {
    echo "Usage: $0 rollback REVISION" >&2
    exit 1
  }
  gcloud run services update-traffic "${ASSISTANT_SERVICE_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --to-revisions="${revision}=100"
}

if [[ "${ACTION}" == "suspend" || "${ACTION}" == "cost-status" ]]; then
  preflight_project_access
else
  preflight
fi
case "${ACTION}" in
  preflight) ;;
  provision) "${SCRIPT_DIR}/provision.sh" ;;
  build) build_images ;;
  resume) resume_application ;;
  suspend) suspend_application ;;
  cost-status) cost_status ;;
  migrate) resume_alloydb; run_migration ;;
  lifecycle) deploy_lifecycle_automation ;;
  privacy) deploy_privacy_job ;;
  privacy-erase) execute_privacy_erasure "${2:-}" ;;
  toolbox) deploy_toolbox ;;
  assistant) deploy_assistant ;;
  analytics) ensure_bigquery_connection; setup_analytics ;;
  deploy)
    resume_alloydb
    run_migration
    deploy_toolbox
    ensure_bigquery_connection
    setup_analytics
    deploy_assistant
    deploy_lifecycle_automation
    deploy_privacy_job
    ;;
  verify) setup_analytics; verify_candidate ;;
  promote) promote ;;
  rollback) rollback "${2:-}" ;;
  full)
    "${SCRIPT_DIR}/provision.sh"
    build_images
    resume_alloydb
    run_migration
    deploy_toolbox
    ensure_bigquery_connection
    setup_analytics
    deploy_assistant
    deploy_lifecycle_automation
    deploy_privacy_job
    verify_candidate
    promote
    if [[ "${ENABLE_MONITORING}" == "true" ]]; then
      "${SCRIPT_DIR}/monitoring.sh"
    fi
    if [[ "${AUTO_SUSPEND_AFTER_DEPLOY}" == "true" ]]; then
      suspend_application
    fi
    ;;
  *)
    echo "Usage: $0 [preflight|provision|build|resume|suspend|cost-status|toolbox|migrate|analytics|assistant|lifecycle|privacy|privacy-erase|deploy|verify|promote|rollback|full]" >&2
    exit 1
    ;;
esac
