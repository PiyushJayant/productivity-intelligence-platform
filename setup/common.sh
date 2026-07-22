#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -x "${REPO_ROOT}/.venv/Scripts/python.exe" ]]; then
  PYTHON_BIN="${REPO_ROOT}/.venv/Scripts/python.exe"
elif [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
else
  PYTHON_BIN="python"
fi
if command -v bq.cmd >/dev/null 2>&1; then
  BQ_BIN="bq.cmd"
else
  BQ_BIN="bq"
fi

if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-cohort-1-track-1}"
REGION="${REGION:-us-central1}"
VERTEX_LOCATION="${GOOGLE_CLOUD_LOCATION:-global}"
MODEL="${MODEL:-gemini-2.5-flash}"
APP_MODE="${APP_MODE:-full}"
ASSISTANT_SERVICE_NAME="${ASSISTANT_SERVICE_NAME:-productivity-assistant}"
TOOLBOX_SERVICE_NAME="${TOOLBOX_SERVICE_NAME:-mcp-toolbox}"
MIGRATION_JOB_NAME="${MIGRATION_JOB_NAME:-productivity-migrate}"
AR_REPO="${AR_REPO:-productivity-services}"
VPC_NETWORK="${VPC_NETWORK:-productivity-vpc}"
VPC_SUBNET="${VPC_SUBNET:-productivity-us-central1}"
VPC_SUBNET_RANGE="${VPC_SUBNET_RANGE:-10.20.0.0/24}"
PSA_RANGE_NAME="${PSA_RANGE_NAME:-productivity-private-services}"
ALLOYDB_REGION="${ALLOYDB_REGION:-${REGION}}"
ALLOYDB_CLUSTER="${ALLOYDB_CLUSTER:-productivity-cluster}"
ALLOYDB_INSTANCE="${ALLOYDB_INSTANCE:-productivity-instance}"
ALLOYDB_DATABASE="${ALLOYDB_DATABASE:-postgres}"
ADMIN_DB_USER="${ADMIN_DB_USER:-postgres}"
ALLOYDB_USER="${ALLOYDB_USER:-productivity_app}"
ANALYTICS_DB_USER="${ANALYTICS_DB_USER:-productivity_analytics}"
BIGQUERY_CONNECTION_ID="${BIGQUERY_CONNECTION_ID:-productivity_alloydb}"
ASSISTANT_SA_NAME="${ASSISTANT_SA_NAME:-productivity-assistant}"
TOOLBOX_SA_NAME="${TOOLBOX_SA_NAME:-productivity-toolbox}"
MIGRATION_SA_NAME="${MIGRATION_SA_NAME:-productivity-migrate}"
ASSISTANT_SA="${ASSISTANT_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
TOOLBOX_SA="${TOOLBOX_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
MIGRATION_SA="${MIGRATION_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
ADMIN_DB_SECRET="${ADMIN_DB_SECRET:-alloydb-admin-password}"
APP_DB_SECRET="${APP_DB_SECRET:-alloydb-app-password}"
ANALYTICS_DB_SECRET="${ANALYTICS_DB_SECRET:-alloydb-analytics-password}"
BUDGET_AMOUNT="${BUDGET_AMOUNT:-5000INR}"
BUDGET_NAME="${BUDGET_NAME:-Productivity Assistant Hackathon Budget}"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Error: required command '$1' was not found." >&2
    exit 1
  }
}

preflight() {
  require_command gcloud
  require_command "${BQ_BIN}"
  require_command curl

  [[ "${PROJECT_ID}" != *"your-project"* && "${PROJECT_ID}" != "cohort-1-hackhathon" ]] || {
    echo "Error: GOOGLE_CLOUD_PROJECT is a placeholder or obsolete project." >&2
    exit 1
  }
  [[ "${APP_MODE}" == "full" || "${APP_MODE}" == "prototype" ]] || {
    echo "Error: APP_MODE must be full or prototype." >&2
    exit 1
  }

  gcloud projects describe "${PROJECT_ID}" --format='value(projectId)' >/dev/null
  local billing
  billing="$(gcloud billing projects describe "${PROJECT_ID}" --format='value(billingEnabled)')"
  [[ "${billing,,}" == "true" ]] || {
    echo "Error: billing is not enabled for ${PROJECT_ID}." >&2
    exit 1
  }

  local active_project
  active_project="$(gcloud config get-value project 2>/dev/null || true)"
  [[ "${active_project}" == "${PROJECT_ID}" ]] || {
    echo "Error: active gcloud project '${active_project}' differs from '${PROJECT_ID}'." >&2
    echo "Run: gcloud config set project ${PROJECT_ID}" >&2
    exit 1
  }
}

secret_version() {
  gcloud secrets versions list "$1" --project="${PROJECT_ID}" \
    --filter='state=ENABLED' --sort-by='~createTime' --limit=1 \
    --format='value(name.basename())'
}

ensure_secret() {
  local name="$1"
  if ! gcloud secrets describe "${name}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud secrets create "${name}" --replication-policy=automatic --project="${PROJECT_ID}"
  fi
  if [[ -z "$(secret_version "${name}")" ]]; then
    require_command openssl
    openssl rand -base64 36 | tr -d '\r\n/=+' | \
      gcloud secrets versions add "${name}" --data-file=- --project="${PROJECT_ID}" >/dev/null
  fi
}
