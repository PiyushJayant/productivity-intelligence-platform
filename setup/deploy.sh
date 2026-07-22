#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=setup/common.sh
source "${SCRIPT_DIR}/common.sh"

ACTION="${1:-full}"
SEED_DEMO="${SEED_DEMO:-false}"
BUILD_TAG_FILE="${REPO_ROOT}/.deploy-build-tag"
if [[ -n "${BUILD_TAG:-}" ]]; then
  BUILD_TAG="${BUILD_TAG}"
elif [[ "${ACTION}" == "build" || "${ACTION}" == "full" ]]; then
  BUILD_TAG="$(git -C "${REPO_ROOT}" rev-parse --short=12 HEAD)-$(date -u +%Y%m%d%H%M%S)"
elif [[ -f "${BUILD_TAG_FILE}" ]]; then
  BUILD_TAG="$(<"${BUILD_TAG_FILE}")"
else
  echo "Error: no successful build tag found. Run '$0 build' first." >&2
  exit 1
fi
IMAGE_ROOT="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}"
ASSISTANT_IMAGE="${IMAGE_ROOT}/${ASSISTANT_SERVICE_NAME}:${BUILD_TAG}"
TOOLBOX_IMAGE="${IMAGE_ROOT}/${TOOLBOX_SERVICE_NAME}:${BUILD_TAG}"
MIGRATION_IMAGE="${IMAGE_ROOT}/${MIGRATION_JOB_NAME}:${BUILD_TAG}"

build_images() {
  gcloud builds submit "${REPO_ROOT}" --project="${PROJECT_ID}" \
    --config="${REPO_ROOT}/cloudbuild.toolbox.yaml" \
    --substitutions="_IMAGE_URI=${TOOLBOX_IMAGE}"
  gcloud builds submit "${REPO_ROOT}" --project="${PROJECT_ID}" \
    --config="${REPO_ROOT}/cloudbuild.assistant.yaml" \
    --substitutions="_IMAGE_URI=${ASSISTANT_IMAGE}"
  gcloud builds submit "${REPO_ROOT}" --project="${PROJECT_ID}" \
    --config="${REPO_ROOT}/cloudbuild.migrate.yaml" \
    --substitutions="_IMAGE_URI=${MIGRATION_IMAGE}"
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
    --network="${VPC_NETWORK}" --subnet="${VPC_SUBNET}" \
    --vpc-egress=private-ranges-only \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},ALLOYDB_REGION=${ALLOYDB_REGION},ALLOYDB_CLUSTER=${ALLOYDB_CLUSTER},ALLOYDB_INSTANCE=${ALLOYDB_INSTANCE},ALLOYDB_IP_TYPE=private,ALLOYDB_DATABASE=${ALLOYDB_DATABASE},ALLOYDB_USER=${ALLOYDB_USER}" \
    --set-secrets="ALLOYDB_PASSWORD=${APP_DB_SECRET}:${app_secret_version}"

  gcloud run services add-iam-policy-binding "${TOOLBOX_SERVICE_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --member="serviceAccount:${ASSISTANT_SA}" --role=roles/run.invoker --quiet
}

run_migration() {
  local admin_version app_version analytics_version instance_uri
  admin_version="$(secret_version "${ADMIN_DB_SECRET}")"
  app_version="$(secret_version "${APP_DB_SECRET}")"
  analytics_version="$(secret_version "${ANALYTICS_DB_SECRET}")"
  instance_uri="projects/${PROJECT_ID}/locations/${REGION}/clusters/${ALLOYDB_CLUSTER}/instances/${ALLOYDB_INSTANCE}"

  gcloud run jobs deploy "${MIGRATION_JOB_NAME}" --image="${MIGRATION_IMAGE}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --service-account="${MIGRATION_SA}" --network="${VPC_NETWORK}" \
    --subnet="${VPC_SUBNET}" --vpc-egress=private-ranges-only \
    --set-env-vars="ALLOYDB_INSTANCE_URI=${instance_uri},ALLOYDB_DATABASE=${ALLOYDB_DATABASE},SEED_DEMO=${SEED_DEMO}" \
    --set-secrets="ADMIN_DB_PASSWORD=${ADMIN_DB_SECRET}:${admin_version},APP_DB_PASSWORD=${APP_DB_SECRET}:${app_version},ANALYTICS_DB_PASSWORD=${ANALYTICS_DB_SECRET}:${analytics_version}" \
    --max-retries=0 --task-timeout=15m
  gcloud run jobs execute "${MIGRATION_JOB_NAME}" --region="${REGION}" \
    --project="${PROJECT_ID}" --wait
}

ensure_bigquery_connection() {
  if "${BQ_BIN}" show --connection --location="${REGION}" \
      --project_id="${PROJECT_ID}" "${BIGQUERY_CONNECTION_ID}" >/dev/null 2>&1; then
    return
  fi

  local payload response password_file token resource
  payload="$(mktemp)"
  response="$(mktemp)"
  password_file="$(mktemp)"
  trap 'rm -f "${payload}" "${response}" "${password_file}"' RETURN
  chmod 600 "${payload}" "${response}" "${password_file}"
  gcloud secrets versions access \
    "$(secret_version "${ANALYTICS_DB_SECRET}")" --secret="${ANALYTICS_DB_SECRET}" \
    --project="${PROJECT_ID}" --out-file="${password_file}" >/dev/null
  resource="//alloydb.googleapis.com/projects/${PROJECT_ID}/locations/${REGION}/clusters/${ALLOYDB_CLUSTER}/instances/${ALLOYDB_INSTANCE}"
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
  curl -fsS -X POST \
    "https://bigqueryconnection.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/connections?connectionId=${BIGQUERY_CONNECTION_ID}" \
    -H "Authorization: Bearer ${token}" -H 'Content-Type: application/json' \
    --data-binary "@${payload}" >"${response}"
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
  local toolbox_url
  local -a traffic_args=(--tag=candidate)
  toolbox_url="$(gcloud run services describe "${TOOLBOX_SERVICE_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" --format='value(status.url)')"
  [[ "${toolbox_url}" == https://* ]] || {
    echo "Error: deployed Toolbox URL is invalid." >&2
    exit 1
  }

  if gcloud run services describe "${ASSISTANT_SERVICE_NAME}" \
      --region="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    traffic_args+=(--no-traffic)
  fi

  gcloud run deploy "${ASSISTANT_SERVICE_NAME}" --image="${ASSISTANT_IMAGE}" \
    --region="${REGION}" --project="${PROJECT_ID}" --platform=managed \
    --service-account="${ASSISTANT_SA}" --allow-unauthenticated \
    --memory=1Gi --timeout=300 "${traffic_args[@]}" \
    --set-env-vars="APP_MODE=${APP_MODE},GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${VERTEX_LOCATION},GOOGLE_GENAI_USE_VERTEXAI=true,MODEL=${MODEL},TOOLBOX_URL=${toolbox_url},TOOLBOX_AUDIENCE=${toolbox_url},BIGQUERY_CONNECTION_ID=${BIGQUERY_CONNECTION_ID}"
}

setup_analytics() {
  GOOGLE_CLOUD_PROJECT="${PROJECT_ID}" REGION="${REGION}" \
    BIGQUERY_CONNECTION_ID="${BIGQUERY_CONNECTION_ID}" \
    "${PYTHON_BIN}" "${SCRIPT_DIR}/bigquery_setup.py"
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
  "${PYTHON_BIN}" - "${readiness_file}" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
expected = ["analytics_agent", "calendar_agent", "notes_agent", "task_agent"]
if not data.get("ready") or sorted(data.get("loaded_agents", [])) != expected:
    raise SystemExit(f"candidate readiness mismatch: {data}")
PY
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

preflight
case "${ACTION}" in
  preflight) ;;
  provision) "${SCRIPT_DIR}/provision.sh" ;;
  build) build_images ;;
  migrate) run_migration ;;
  toolbox) deploy_toolbox ;;
  assistant) deploy_assistant ;;
  analytics) ensure_bigquery_connection; setup_analytics ;;
  deploy) run_migration; deploy_toolbox; ensure_bigquery_connection; setup_analytics; deploy_assistant ;;
  verify) setup_analytics; verify_candidate ;;
  promote) promote ;;
  rollback) rollback "$@" ;;
  full)
    "${SCRIPT_DIR}/provision.sh"
    build_images
    run_migration
    deploy_toolbox
    ensure_bigquery_connection
    setup_analytics
    deploy_assistant
    verify_candidate
    promote
    ;;
  *)
    echo "Usage: $0 [preflight|provision|build|toolbox|migrate|analytics|assistant|deploy|verify|promote|rollback]" >&2
    exit 1
    ;;
esac
