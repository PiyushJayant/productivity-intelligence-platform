#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Error: ${ENV_FILE} is required." >&2
  echo "Copy .env.example to .env and set every value before running deployment commands." >&2
  exit 1
fi

# .env is the sole source of operator-controlled deployment configuration.
set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

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

REQUIRED_CONFIG=(
  GOOGLE_CLOUD_PROJECT GOOGLE_CLOUD_LOCATION REGION GOOGLE_GENAI_USE_VERTEXAI
  MODEL EMBEDDING_MODEL EMBEDDING_DIMENSIONS APP_MODE COST_PROFILE
  ENVIRONMENT RESOURCE_LABELS BIGQUERY_MCP_URL
  ASSISTANT_SERVICE_NAME TOOLBOX_SERVICE_NAME MIGRATION_JOB_NAME
  LIFECYCLE_JOB_NAME AR_REPO
  VPC_NETWORK VPC_SUBNET VPC_SUBNET_RANGE PSA_RANGE_NAME
  ALLOYDB_REGION ALLOYDB_CLUSTER ALLOYDB_INSTANCE ALLOYDB_MACHINE_TYPE
  ALLOYDB_AVAILABILITY_TYPE ALLOYDB_DATABASE ADMIN_DB_USER ALLOYDB_USER
  ANALYTICS_DB_USER ALLOYDB_IP_TYPE ALLOYDB_ACTIVATION_POLICY
  ALLOYDB_ESTIMATED_HOURLY_USD
  TOOLBOX_URL TOOLBOX_AUDIENCE BIGQUERY_DATASET BIGQUERY_CONNECTION_ID
  ASSISTANT_SA_NAME TOOLBOX_SA_NAME MIGRATION_SA_NAME LIFECYCLE_SA_NAME
  SCHEDULER_SA_NAME LIFECYCLE_ROLE_ID
  ADMIN_DB_SECRET APP_DB_SECRET ANALYTICS_DB_SECRET
  ADMIN_DB_PASSWORD APP_DB_PASSWORD ANALYTICS_DB_PASSWORD
  ASSISTANT_MIN_INSTANCES ASSISTANT_MAX_INSTANCES ASSISTANT_CPU
  ASSISTANT_MEMORY ASSISTANT_CONCURRENCY ASSISTANT_TIMEOUT
  TOOLBOX_MIN_INSTANCES TOOLBOX_MAX_INSTANCES TOOLBOX_CPU TOOLBOX_MEMORY
  TOOLBOX_CONCURRENCY TOOLBOX_TIMEOUT MIGRATION_CPU MIGRATION_MEMORY
  MIGRATION_TIMEOUT SEED_DEMO
  ROUTER_MAX_OUTPUT_TOKENS ROUTER_THINKING_BUDGET
  SPECIALIST_MAX_OUTPUT_TOKENS SPECIALIST_THINKING_BUDGET
  ANALYTICS_MAX_OUTPUT_TOKENS ANALYTICS_THINKING_BUDGET
  AGENT_CONTEXT_MAX_EVENTS MODEL_TEMPERATURE
  DEFAULT_TIMEZONE DEFAULT_PAGE_SIZE LOG_LEVEL STRUCTURED_LOGGING
  ENABLE_REQUEST_LOGGING REQUEST_ID_HEADER
  SKIP_EXISTING_IMAGES ARTIFACT_KEEP_COUNT ARTIFACT_RETENTION_DAYS
  ENABLE_MONITORING ENABLE_UPTIME_CHECK UPTIME_CHECK_PERIOD
  ENABLE_LOG_METRICS EXCLUDE_HEALTH_CHECK_LOGS ALLOW_ALLOYDB_RESIZE
  MONITORING_ALIGNMENT_SECONDS MONITORING_5XX_RATE_THRESHOLD
  MONITORING_P95_LATENCY_MS MONITORING_ALLOYDB_CONNECTION_THRESHOLD
  BUDGET_AMOUNT BUDGET_NAME BUDGET_THRESHOLDS
  AUTO_SUSPEND_AFTER_DEPLOY ALLOYDB_STATE_TIMEOUT_SECONDS
  ENABLE_SCHEDULED_LIFECYCLE LIFECYCLE_RESUME_CRON LIFECYCLE_SUSPEND_CRON
  LIFECYCLE_TIMEZONE
)

for config_name in "${REQUIRED_CONFIG[@]}"; do
  if [[ -z "${!config_name:-}" ]]; then
    echo "Error: ${config_name} must be set in ${ENV_FILE}." >&2
    exit 1
  fi
done

PROJECT_ID="${GOOGLE_CLOUD_PROJECT}"
VERTEX_LOCATION="${GOOGLE_CLOUD_LOCATION}"
ASSISTANT_SA="${ASSISTANT_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
TOOLBOX_SA="${TOOLBOX_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
MIGRATION_SA="${MIGRATION_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
LIFECYCLE_SA="${LIFECYCLE_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_SA="${SCHEDULER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Error: required command '$1' was not found." >&2
    exit 1
  }
}

require_boolean() {
  local name="$1" value="${!1}"
  [[ "${value}" == "true" || "${value}" == "false" ]] || {
    echo "Error: ${name} must be true or false in ${ENV_FILE}." >&2
    exit 1
  }
}

require_nonnegative_integer() {
  local name="$1" value="${!1}"
  [[ "${value}" =~ ^[0-9]+$ ]] || {
    echo "Error: ${name} must be a non-negative integer in ${ENV_FILE}." >&2
    exit 1
  }
}

validate_config() {
  [[ "${PROJECT_ID}" != *"your-project"* && "${PROJECT_ID}" != *"change-me"* ]] || {
    echo "Error: set GOOGLE_CLOUD_PROJECT to a real billing-enabled project ID." >&2
    exit 1
  }
  [[ "${APP_MODE}" == "full" || "${APP_MODE}" == "prototype" ]] || {
    echo "Error: APP_MODE must be full or prototype." >&2
    exit 1
  }
  [[ "${COST_PROFILE}" == "demo" || "${COST_PROFILE}" == "lean" ||
      "${COST_PROFILE}" == "production" ]] || {
    echo "Error: COST_PROFILE must be demo, lean, or production." >&2
    exit 1
  }
  [[ "${ALLOYDB_AVAILABILITY_TYPE}" == "ZONAL" ||
      "${ALLOYDB_AVAILABILITY_TYPE}" == "REGIONAL" ]] || {
    echo "Error: ALLOYDB_AVAILABILITY_TYPE must be ZONAL or REGIONAL." >&2
    exit 1
  }
  [[ "${ALLOYDB_ACTIVATION_POLICY}" == "ALWAYS" ||
      "${ALLOYDB_ACTIVATION_POLICY}" == "NEVER" ]] || {
    echo "Error: ALLOYDB_ACTIVATION_POLICY must be ALWAYS or NEVER." >&2
    exit 1
  }
  [[ "${ALLOYDB_IP_TYPE}" == "private" ]] || {
    echo "Error: ALLOYDB_IP_TYPE must remain private for this deployment architecture." >&2
    exit 1
  }
  [[ "${ALLOYDB_REGION}" == "${REGION}" ]] || {
    echo "Error: ALLOYDB_REGION must match REGION for same-region private networking." >&2
    exit 1
  }
  [[ "${ASSISTANT_MEMORY}" =~ ^[1-9][0-9]*(Mi|Gi)$ &&
      "${TOOLBOX_MEMORY}" =~ ^[1-9][0-9]*(Mi|Gi)$ &&
      "${MIGRATION_MEMORY}" =~ ^[1-9][0-9]*(Mi|Gi)$ ]] || {
    echo "Error: Cloud Run memory values must use positive Mi or Gi units." >&2
    exit 1
  }
  [[ "${UPTIME_CHECK_PERIOD}" == "1" || "${UPTIME_CHECK_PERIOD}" == "5" ||
      "${UPTIME_CHECK_PERIOD}" == "10" || "${UPTIME_CHECK_PERIOD}" == "15" ]] || {
    echo "Error: UPTIME_CHECK_PERIOD must be 1, 5, 10, or 15 minutes." >&2
    exit 1
  }
  IFS=',' read -r -a configured_thresholds <<<"${BUDGET_THRESHOLDS}"
  [[ "${#configured_thresholds[@]}" -ge 1 ]] || {
    echo "Error: BUDGET_THRESHOLDS must contain at least one threshold." >&2
    exit 1
  }
  local configured_threshold
  for configured_threshold in "${configured_thresholds[@]}"; do
    [[ "${configured_threshold}" =~ ^0([.][0-9]+)?$ ||
        "${configured_threshold}" =~ ^1([.]0+)?$ ]] || {
      echo "Error: budget threshold '${configured_threshold}' must be between 0 and 1." >&2
      exit 1
    }
  done

  local boolean_name
  for boolean_name in GOOGLE_GENAI_USE_VERTEXAI SEED_DEMO SKIP_EXISTING_IMAGES \
      ENABLE_MONITORING ENABLE_UPTIME_CHECK ENABLE_LOG_METRICS ALLOW_ALLOYDB_RESIZE \
      EXCLUDE_HEALTH_CHECK_LOGS AUTO_SUSPEND_AFTER_DEPLOY STRUCTURED_LOGGING \
      ENABLE_REQUEST_LOGGING ENABLE_SCHEDULED_LIFECYCLE; do
    require_boolean "${boolean_name}"
  done

  local integer_name
  for integer_name in ASSISTANT_MIN_INSTANCES ASSISTANT_MAX_INSTANCES \
      ASSISTANT_CPU ASSISTANT_CONCURRENCY ASSISTANT_TIMEOUT \
      TOOLBOX_MIN_INSTANCES TOOLBOX_MAX_INSTANCES TOOLBOX_CPU \
      TOOLBOX_CONCURRENCY TOOLBOX_TIMEOUT MIGRATION_CPU MIGRATION_TIMEOUT \
      ROUTER_MAX_OUTPUT_TOKENS SPECIALIST_MAX_OUTPUT_TOKENS \
      ANALYTICS_MAX_OUTPUT_TOKENS ARTIFACT_KEEP_COUNT \
      ARTIFACT_RETENTION_DAYS ALLOYDB_STATE_TIMEOUT_SECONDS EMBEDDING_DIMENSIONS \
      MONITORING_ALIGNMENT_SECONDS MONITORING_5XX_RATE_THRESHOLD \
      MONITORING_P95_LATENCY_MS MONITORING_ALLOYDB_CONNECTION_THRESHOLD \
      UPTIME_CHECK_PERIOD DEFAULT_PAGE_SIZE AGENT_CONTEXT_MAX_EVENTS; do
    require_nonnegative_integer "${integer_name}"
  done

  local positive_name
  for positive_name in ASSISTANT_MAX_INSTANCES ASSISTANT_CPU \
      ASSISTANT_CONCURRENCY ASSISTANT_TIMEOUT TOOLBOX_MAX_INSTANCES TOOLBOX_CPU \
      TOOLBOX_CONCURRENCY TOOLBOX_TIMEOUT MIGRATION_CPU MIGRATION_TIMEOUT \
      ROUTER_MAX_OUTPUT_TOKENS SPECIALIST_MAX_OUTPUT_TOKENS \
      ANALYTICS_MAX_OUTPUT_TOKENS ARTIFACT_KEEP_COUNT ARTIFACT_RETENTION_DAYS \
      ALLOYDB_STATE_TIMEOUT_SECONDS EMBEDDING_DIMENSIONS \
      MONITORING_ALIGNMENT_SECONDS MONITORING_P95_LATENCY_MS \
      MONITORING_ALLOYDB_CONNECTION_THRESHOLD UPTIME_CHECK_PERIOD \
      DEFAULT_PAGE_SIZE AGENT_CONTEXT_MAX_EVENTS; do
    [[ "${!positive_name}" -ge 1 ]] || {
      echo "Error: ${positive_name} must be greater than zero." >&2
      exit 1
    }
  done

  [[ "${ASSISTANT_MAX_INSTANCES}" -ge 1 &&
      "${ASSISTANT_MIN_INSTANCES}" -le "${ASSISTANT_MAX_INSTANCES}" ]] || {
    echo "Error: assistant instance bounds are invalid." >&2
    exit 1
  }
  [[ "${TOOLBOX_MAX_INSTANCES}" -ge 1 &&
      "${TOOLBOX_MIN_INSTANCES}" -le "${TOOLBOX_MAX_INSTANCES}" ]] || {
    echo "Error: Toolbox instance bounds are invalid." >&2
    exit 1
  }
  [[ "${#ADMIN_DB_PASSWORD}" -ge 24 && "${#APP_DB_PASSWORD}" -ge 24 &&
      "${#ANALYTICS_DB_PASSWORD}" -ge 24 ]] || {
    echo "Error: every database password in ${ENV_FILE} must contain at least 24 characters." >&2
    exit 1
  }
  [[ "${ADMIN_DB_USER}" =~ ^[a-z][a-z0-9_]{0,62}$ &&
      "${ALLOYDB_USER}" =~ ^[a-z][a-z0-9_]{0,62}$ &&
      "${ANALYTICS_DB_USER}" =~ ^[a-z][a-z0-9_]{0,62}$ &&
      "${ALLOYDB_DATABASE}" =~ ^[a-z][a-z0-9_]{0,62}$ ]] || {
    echo "Error: database and user names must be lowercase PostgreSQL identifiers." >&2
    exit 1
  }
  [[ "${ADMIN_DB_USER}" == "postgres" ]] || {
    echo "Error: ADMIN_DB_USER must be the AlloyDB bootstrap administrator 'postgres'." >&2
    exit 1
  }
  [[ "${#BIGQUERY_DATASET}" -le 1024 &&
      "${BIGQUERY_DATASET}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ &&
      "${BIGQUERY_CONNECTION_ID}" =~ ^[A-Za-z0-9_]+$ ]] || {
    echo "Error: BigQuery dataset or connection identifier is invalid." >&2
    exit 1
  }
  [[ "${ADMIN_DB_USER}" != "${ALLOYDB_USER}" &&
      "${ADMIN_DB_USER}" != "${ANALYTICS_DB_USER}" &&
      "${ALLOYDB_USER}" != "${ANALYTICS_DB_USER}" ]] || {
    echo "Error: administrator, application, and analytics users must be distinct." >&2
    exit 1
  }
  [[ "${ALLOYDB_ESTIMATED_HOURLY_USD}" =~ ^[0-9]+([.][0-9]+)?$ &&
      "${MODEL_TEMPERATURE}" =~ ^[0-9]+([.][0-9]+)?$ ]] || {
    echo "Error: cost estimate and model temperature must be numeric." >&2
    exit 1
  }
  [[ "${EMBEDDING_MODEL}" =~ ^[A-Za-z0-9._@-]+$ &&
      "${EMBEDDING_DIMENSIONS}" -ge 1 ]] || {
    echo "Error: embedding model or dimensions are invalid." >&2
    exit 1
  }
  [[ "${DEFAULT_TIMEZONE}" == "UTC" ||
      "${DEFAULT_TIMEZONE}" =~ ^[A-Za-z_]+/[A-Za-z0-9_+-]+$ ]] || {
    echo "Error: DEFAULT_TIMEZONE must be UTC or an IANA timezone such as Asia/Kolkata." >&2
    exit 1
  }
  [[ "${LIFECYCLE_TIMEZONE}" == "UTC" ||
      "${LIFECYCLE_TIMEZONE}" =~ ^[A-Za-z_]+/[A-Za-z0-9_+-]+$ ]] || {
    echo "Error: LIFECYCLE_TIMEZONE must be a valid IANA timezone." >&2
    exit 1
  }
  [[ "${LIFECYCLE_RESUME_CRON}" != "${LIFECYCLE_SUSPEND_CRON}" ]] || {
    echo "Error: lifecycle resume and suspend schedules must differ." >&2
    exit 1
  }
  [[ "${LOG_LEVEL}" == "DEBUG" || "${LOG_LEVEL}" == "INFO" ||
      "${LOG_LEVEL}" == "WARNING" || "${LOG_LEVEL}" == "ERROR" ||
      "${LOG_LEVEL}" == "CRITICAL" ]] || {
    echo "Error: LOG_LEVEL is invalid." >&2
    exit 1
  }
  [[ "${REQUEST_ID_HEADER}" =~ ^[A-Za-z0-9-]+$ ]] || {
    echo "Error: REQUEST_ID_HEADER must be a valid HTTP header name." >&2
    exit 1
  }
  [[ "${LIFECYCLE_ROLE_ID}" =~ ^[A-Za-z][A-Za-z0-9_.]{2,63}$ ]] || {
    echo "Error: LIFECYCLE_ROLE_ID is not a valid custom IAM role ID." >&2
    exit 1
  }
  [[ "${ADMIN_DB_PASSWORD}" != *"change-me"* &&
      "${APP_DB_PASSWORD}" != *"change-me"* &&
      "${ANALYTICS_DB_PASSWORD}" != *"change-me"* ]] || {
    echo "Error: replace all database password placeholders in ${ENV_FILE}." >&2
    exit 1
  }
  [[ "${ADMIN_DB_PASSWORD}" != "${APP_DB_PASSWORD}" &&
      "${ADMIN_DB_PASSWORD}" != "${ANALYTICS_DB_PASSWORD}" &&
      "${APP_DB_PASSWORD}" != "${ANALYTICS_DB_PASSWORD}" ]] || {
    echo "Error: database passwords must be independent values." >&2
    exit 1
  }

  case "${COST_PROFILE}" in
    demo)
      [[ "${ALLOYDB_AVAILABILITY_TYPE}" == "ZONAL" ]] || {
        echo "Error: demo profile requires zonal AlloyDB." >&2
        exit 1
      }
      [[ "${ASSISTANT_MIN_INSTANCES}" == "0" &&
          "${TOOLBOX_MIN_INSTANCES}" == "0" &&
          "${ASSISTANT_MAX_INSTANCES}" == "1" &&
          "${TOOLBOX_MAX_INSTANCES}" == "1" ]] || {
        echo "Error: demo profile requires min=0 and max=1 for both Cloud Run services." >&2
        exit 1
      }
      ;;
    lean)
      [[ "${ALLOYDB_MACHINE_TYPE}" != "c4a-highmem-1" ]] || {
        echo "Error: lean profile requires an AlloyDB machine with at least two vCPUs." >&2
        exit 1
      }
      ;;
    production)
      [[ "${ALLOYDB_AVAILABILITY_TYPE}" == "REGIONAL" ]] || {
        echo "Error: production profile requires regional AlloyDB availability." >&2
        exit 1
      }
      [[ "${ALLOYDB_MACHINE_TYPE}" != "c4a-highmem-1" ]] || {
        echo "Error: production profile requires an AlloyDB machine with at least two vCPUs." >&2
        exit 1
      }
      [[ "${ENABLE_SCHEDULED_LIFECYCLE}" == "false" ]] || {
        echo "Error: scheduled lifecycle automation is disabled for production." >&2
        exit 1
      }
      ;;
  esac
}

preflight() {
  validate_config
  require_command gcloud
  require_command "${BQ_BIN}"
  require_command curl

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

ensure_secret_from_env() {
  local name="$1" value="$2" current="" version=""
  if ! gcloud secrets describe "${name}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud secrets create "${name}" --replication-policy=automatic --project="${PROJECT_ID}"
  fi
  version="$(secret_version "${name}")"
  if [[ -n "${version}" ]]; then
    current="$(gcloud secrets versions access "${version}" --secret="${name}" \
      --project="${PROJECT_ID}")"
  fi
  if [[ "${current}" != "${value}" ]]; then
    printf '%s' "${value}" | gcloud secrets versions add "${name}" --data-file=- \
      --project="${PROJECT_ID}" >/dev/null
  fi
}
