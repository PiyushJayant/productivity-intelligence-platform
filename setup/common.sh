#!/usr/bin/env bash
# This file is sourced by deployment scripts; exported helpers and derived
# identity variables are intentionally consumed by those callers.
# shellcheck disable=SC2034
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
  AUTH_MODE IDENTITY_PLATFORM_PROJECT_ID IDENTITY_TENANT_CLAIM
  IDENTITY_ROLE_CLAIM DEFAULT_TENANT_ID DEMO_SUBJECT_ID
  AUTH_CLOCK_SKEW_SECONDS BOOTSTRAP_IDP_SUBJECT
  IDENTITY_CONTROLLED_REGISTRATION IDENTITY_PASSWORD_MIN_LENGTH
  IDENTITY_PASSWORD_MAX_LENGTH
  ASSISTANT_SERVICE_NAME TOOLBOX_SERVICE_NAME MIGRATION_JOB_NAME
  LIFECYCLE_JOB_NAME PRIVACY_JOB_NAME AR_REPO
  VPC_NETWORK VPC_SUBNET VPC_SUBNET_RANGE PSA_RANGE_NAME
  ALLOYDB_REGION ALLOYDB_CLUSTER ALLOYDB_INSTANCE ALLOYDB_MACHINE_TYPE
  ALLOYDB_AVAILABILITY_TYPE ALLOYDB_DATABASE ADMIN_DB_USER ALLOYDB_USER
  ANALYTICS_DB_USER PRIVACY_DB_USER CDC_DB_USER ALLOYDB_IP_TYPE ALLOYDB_ACTIVATION_POLICY
  ALLOYDB_ESTIMATED_HOURLY_USD
  TOOLBOX_URL TOOLBOX_AUDIENCE BIGQUERY_DATASET BIGQUERY_CONNECTION_ID
  BIGQUERY_ANALYTICS_PROCEDURE ANALYTICS_BACKEND BIGQUERY_NATIVE_TVF
  ANALYTICS_RETRY_ATTEMPTS ANALYTICS_RETRY_BASE_SECONDS
  ANALYTICS_RETRY_MAX_SECONDS PSEUDONYMIZATION_KEY PRIVACY_RETENTION_DAYS
  TAXONOMY_VERSION PRIVACY_BATCH_SIZE PRIVACY_MAX_BATCHES ENABLE_SCHEDULED_PRIVACY
  PRIVACY_RETENTION_CRON PRIVACY_TIMEZONE
  LOAD_TEST_TENANT_ID LOAD_TEST_SUBJECT_ID LOAD_TEST_CONCURRENCY
  LOAD_TEST_SAMPLES LOAD_TEST_RANGE_DAYS LOAD_TEST_QUERY_TIMEOUT_SECONDS
  LOAD_TEST_P95_LIMIT_SECONDS LOAD_TEST_P99_LIMIT_SECONDS
  LOAD_TEST_MAX_ERROR_RATE_PERCENT LOAD_TEST_FIXTURE_EVENTS
  LOAD_TEST_MAX_BYTES_BILLED
  DR_RESTORE_CLUSTER DR_RESTORE_INSTANCE
  DR_RTO_TARGET_SECONDS DR_RPO_TARGET_SECONDS DR_CONFIRM
  ASSISTANT_SA_NAME TOOLBOX_SA_NAME MIGRATION_SA_NAME LIFECYCLE_SA_NAME
  PRIVACY_SA_NAME SCHEDULER_SA_NAME LIFECYCLE_ROLE_ID
  ADMIN_DB_SECRET APP_DB_SECRET ANALYTICS_DB_SECRET PRIVACY_DB_SECRET CDC_DB_SECRET
  PSEUDONYMIZATION_SECRET
  ADMIN_DB_PASSWORD APP_DB_PASSWORD ANALYTICS_DB_PASSWORD PRIVACY_DB_PASSWORD
  CDC_DB_PASSWORD
  ASSISTANT_MIN_INSTANCES ASSISTANT_MAX_INSTANCES ASSISTANT_CPU
  ASSISTANT_MEMORY ASSISTANT_CONCURRENCY ASSISTANT_TIMEOUT
  TOOLBOX_MIN_INSTANCES TOOLBOX_MAX_INSTANCES TOOLBOX_CPU TOOLBOX_MEMORY
  TOOLBOX_CONCURRENCY TOOLBOX_TIMEOUT MIGRATION_CPU MIGRATION_MEMORY
  MIGRATION_TIMEOUT SEED_DEMO
  ROUTER_MAX_OUTPUT_TOKENS ROUTER_THINKING_BUDGET
  SPECIALIST_MAX_OUTPUT_TOKENS SPECIALIST_THINKING_BUDGET
  ANALYTICS_MAX_OUTPUT_TOKENS ANALYTICS_THINKING_BUDGET
  ANALYTICS_MAX_RANGE_DAYS ANALYTICS_QUERY_TIMEOUT_SECONDS
  ANALYTICS_MAX_BYTES_BILLED
  AGENT_CONTEXT_MAX_EVENTS MODEL_TEMPERATURE
  DEFAULT_TIMEZONE DEFAULT_PAGE_SIZE LOG_LEVEL STRUCTURED_LOGGING
  ENABLE_REQUEST_LOGGING REQUEST_ID_HEADER
  SKIP_EXISTING_IMAGES ARTIFACT_KEEP_COUNT ARTIFACT_RETENTION_DAYS
  ENABLE_MONITORING ENABLE_UPTIME_CHECK UPTIME_CHECK_PERIOD
  ENABLE_LOG_METRICS EXCLUDE_HEALTH_CHECK_LOGS ALLOW_ALLOYDB_RESIZE
  MONITORING_ALIGNMENT_SECONDS MONITORING_5XX_RATE_THRESHOLD
  MONITORING_P95_LATENCY_MS MONITORING_ALLOYDB_CONNECTION_THRESHOLD
  MONITORING_ALLOYDB_CPU_THRESHOLD MONITORING_REQUIRE_NOTIFICATION_CHANNELS
  BUDGET_AMOUNT BUDGET_NAME BUDGET_THRESHOLDS
  AUTO_SUSPEND_AFTER_DEPLOY ALLOYDB_STATE_TIMEOUT_SECONDS
  ENABLE_SCHEDULED_LIFECYCLE LIFECYCLE_RESUME_CRON LIFECYCLE_SUSPEND_CRON
  LIFECYCLE_TIMEZONE
  ENABLE_ALLOYDB_READ_POOL ALLOYDB_READ_POOL ALLOYDB_READ_POOL_NODE_COUNT
  ALLOYDB_READ_POOL_MACHINE_TYPE ANALYTICS_ALLOYDB_INSTANCE
  ENABLE_CMEK KMS_KEYRING KMS_ALLOYDB_KEY KMS_BIGQUERY_KEY KMS_SECRET_KEY
  KMS_ROTATION_PERIOD ENABLE_VPC_SC SERVICE_PERIMETER_NAME VPC_SC_MODE
  VPC_SC_ENFORCEMENT_ACK
  ENABLE_DATASTREAM DATASTREAM_LOCATION DATASTREAM_STREAM
  DATASTREAM_SOURCE_PROFILE DATASTREAM_DESTINATION_PROFILE
  DATASTREAM_PRIVATE_CONNECTION DATASTREAM_PEERING_CIDR DATASTREAM_DB_HOST
  DATASTREAM_DB_PORT DATASTREAM_PUBLICATION DATASTREAM_REPLICATION_SLOT
  DATASTREAM_SOURCE_SCHEMA DATASTREAM_SOURCE_TABLE
  DATASTREAM_DATA_FRESHNESS_SECONDS BIGQUERY_NATIVE_TABLE
  CDC_TRIGGER_EVIDENCE_PATH CDC_TRIGGER_EVIDENCE_SHA256
  CDC_RECONCILIATION_EVIDENCE_PATH CDC_RECONCILIATION_EVIDENCE_SHA256
  CDC_PROVISION_ACK CDC_START_ACK
  ENABLE_BILLABLE_PHASE BILLING_ACK
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
PRIVACY_SA="${PRIVACY_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_SA="${SCHEDULER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Error: required command '$1' was not found." >&2
    exit 1
  }
}

require_phase5() {
  if [[ "${PHASE5_ACTIVE:-false}" != "true" ||
        "${ENABLE_BILLABLE_PHASE:-false}" != "true" ||
        "${BILLING_ACK:-}" != "I_ACKNOWLEDGE_GCP_CHARGES" ]]; then
    echo "Error: this command may activate billable GCP resources." >&2
    echo "Run it only through setup/phase5.sh after explicit billing approval." >&2
    exit 1
  fi
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
  [[ "${ANALYTICS_BACKEND}" == "federated" ||
      "${ANALYTICS_BACKEND}" == "native" ]] || {
    echo "Error: ANALYTICS_BACKEND must be federated or native." >&2
    exit 1
  }
  if [[ "${ANALYTICS_BACKEND}" == "native" &&
        "${ENABLE_DATASTREAM}" != "true" ]]; then
    echo "Error: native analytics requires ENABLE_DATASTREAM=true." >&2
    exit 1
  fi
  if [[ "${ANALYTICS_BACKEND}" == "native" ]]; then
    [[ "${CDC_RECONCILIATION_EVIDENCE_PATH}" != replace-* &&
       "${CDC_RECONCILIATION_EVIDENCE_SHA256}" =~ ^[0-9a-f]{64}$ ]] || {
      echo "Error: native analytics requires approved reconciliation evidence." >&2
      exit 1
    }
    "${PYTHON_BIN}" "${SCRIPT_DIR}/cdc_reconcile.py" verify \
      "${CDC_RECONCILIATION_EVIDENCE_PATH}" \
      --expected-sha256="${CDC_RECONCILIATION_EVIDENCE_SHA256}" || exit 1
  fi
  if [[ "${ENABLE_DATASTREAM}" == "true" ]]; then
    [[ "${ENABLE_MONITORING}" == "true" ]] || {
      echo "Error: ENABLE_DATASTREAM=true requires monitoring." >&2
      exit 1
    }
    [[ "${CDC_START_ACK}" == "I_ACKNOWLEDGE_CDC_ACTIVATION_COST" ]] || {
      echo "Error: ENABLE_DATASTREAM=true requires CDC_START_ACK." >&2
      exit 1
    }
    [[ "${CDC_TRIGGER_EVIDENCE_PATH}" != replace-* &&
       "${CDC_TRIGGER_EVIDENCE_SHA256}" =~ ^[0-9a-f]{64}$ ]] || {
      echo "Error: ENABLE_DATASTREAM=true requires approved CDC evidence." >&2
      exit 1
    }
  fi
  [[ "${AUTH_MODE}" == "identity_platform" || "${AUTH_MODE}" == "disabled" ]] || {
    echo "Error: AUTH_MODE must be identity_platform or disabled." >&2
    return 1
  }
  if [[ "${ENVIRONMENT}" == "production" && "${AUTH_MODE}" != "identity_platform" ]]; then
    echo "Error: production requires AUTH_MODE=identity_platform." >&2
    return 1
  fi
  local uuid_pattern='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$'
  [[ "${DEFAULT_TENANT_ID}" =~ ${uuid_pattern} ]] || {
    echo "Error: DEFAULT_TENANT_ID must be a canonical UUID." >&2
    return 1
  }
  [[ "${DEMO_SUBJECT_ID}" =~ ${uuid_pattern} ]] || {
    echo "Error: DEMO_SUBJECT_ID must be a canonical UUID." >&2
    return 1
  }
  [[ "${LOAD_TEST_TENANT_ID}" =~ ${uuid_pattern} &&
      "${LOAD_TEST_SUBJECT_ID}" =~ ${uuid_pattern} ]] || {
    echo "Error: load-test identities must be canonical UUIDs." >&2
    return 1
  }
  [[ "${DR_RESTORE_CLUSTER}" != "${ALLOYDB_CLUSTER}" &&
      "${DR_RESTORE_CLUSTER}" == *-dr-restore ]] || {
    echo "Error: DR restore cluster must be isolated and end in -dr-restore." >&2
    return 1
  }
  [[ "${DR_RESTORE_CLUSTER}" =~ ^[a-z][a-z0-9-]{0,61}[a-z0-9]$ &&
      "${DR_RESTORE_INSTANCE}" =~ ^[a-z][a-z0-9-]{0,61}[a-z0-9]$ ]] || {
    echo "Error: DR restore resource IDs are invalid." >&2
    return 1
  }
  "${PYTHON_BIN}" -c \
    'import os; p95=float(os.environ["LOAD_TEST_P95_LIMIT_SECONDS"]); p99=float(os.environ["LOAD_TEST_P99_LIMIT_SECONDS"]); errors=float(os.environ["LOAD_TEST_MAX_ERROR_RATE_PERCENT"]); assert 0 < p95 <= p99 and 0 <= errors <= 100' || {
    echo "Error: load-test latency or error-rate limits are invalid." >&2
    return 1
  }
  [[ "${LOAD_TEST_FIXTURE_EVENTS}" == "1000000" ||
      "${LOAD_TEST_FIXTURE_EVENTS}" == "10000000" ]] || {
    echo "Error: LOAD_TEST_FIXTURE_EVENTS must be 1000000 or 10000000." >&2
    return 1
  }
  if [[ "${AUTH_MODE}" == "identity_platform" &&
        "${BOOTSTRAP_IDP_SUBJECT}" == replace-* ]]; then
    echo "Error: BOOTSTRAP_IDP_SUBJECT is still a placeholder." >&2
    return 1
  fi
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
      ENABLE_REQUEST_LOGGING ENABLE_SCHEDULED_LIFECYCLE \
      ENABLE_ALLOYDB_READ_POOL ENABLE_CMEK ENABLE_VPC_SC ENABLE_DATASTREAM \
      ENABLE_BILLABLE_PHASE IDENTITY_CONTROLLED_REGISTRATION \
      MONITORING_REQUIRE_NOTIFICATION_CHANNELS ENABLE_SCHEDULED_PRIVACY; do
    require_boolean "${boolean_name}"
  done

  local integer_name
  for integer_name in ASSISTANT_MIN_INSTANCES ASSISTANT_MAX_INSTANCES \
      ASSISTANT_CPU ASSISTANT_CONCURRENCY ASSISTANT_TIMEOUT \
      TOOLBOX_MIN_INSTANCES TOOLBOX_MAX_INSTANCES TOOLBOX_CPU \
      TOOLBOX_CONCURRENCY TOOLBOX_TIMEOUT MIGRATION_CPU MIGRATION_TIMEOUT \
      ROUTER_MAX_OUTPUT_TOKENS SPECIALIST_MAX_OUTPUT_TOKENS \
      ANALYTICS_MAX_OUTPUT_TOKENS ARTIFACT_KEEP_COUNT \
      ANALYTICS_MAX_RANGE_DAYS ANALYTICS_QUERY_TIMEOUT_SECONDS \
      ANALYTICS_MAX_BYTES_BILLED \
      LOAD_TEST_CONCURRENCY LOAD_TEST_SAMPLES LOAD_TEST_RANGE_DAYS \
      LOAD_TEST_QUERY_TIMEOUT_SECONDS LOAD_TEST_FIXTURE_EVENTS \
      LOAD_TEST_MAX_BYTES_BILLED \
      DR_RTO_TARGET_SECONDS DR_RPO_TARGET_SECONDS \
      PRIVACY_BATCH_SIZE PRIVACY_MAX_BATCHES \
      DATASTREAM_DB_PORT DATASTREAM_DATA_FRESHNESS_SECONDS \
      ARTIFACT_RETENTION_DAYS ALLOYDB_STATE_TIMEOUT_SECONDS EMBEDDING_DIMENSIONS \
      MONITORING_ALIGNMENT_SECONDS MONITORING_5XX_RATE_THRESHOLD \
      MONITORING_P95_LATENCY_MS MONITORING_ALLOYDB_CONNECTION_THRESHOLD \
      MONITORING_ALLOYDB_CPU_THRESHOLD \
      UPTIME_CHECK_PERIOD DEFAULT_PAGE_SIZE AGENT_CONTEXT_MAX_EVENTS \
      IDENTITY_PASSWORD_MIN_LENGTH IDENTITY_PASSWORD_MAX_LENGTH; do
    require_nonnegative_integer "${integer_name}"
  done

  require_nonnegative_integer "ALLOYDB_READ_POOL_NODE_COUNT"
  [[ "${ALLOYDB_READ_POOL_NODE_COUNT}" -ge 1 ]] || {
    echo "Error: ALLOYDB_READ_POOL_NODE_COUNT must be greater than zero." >&2
    exit 1
  }
  [[ "${MONITORING_ALLOYDB_CPU_THRESHOLD}" -le 100 ]] || {
    echo "Error: MONITORING_ALLOYDB_CPU_THRESHOLD must not exceed 100." >&2
    return 1
  }

  if [[ "${ENABLE_ALLOYDB_READ_POOL}" == "true" ]]; then
    [[ "${ANALYTICS_ALLOYDB_INSTANCE}" == "${ALLOYDB_READ_POOL}" ]] || {
      echo "Error: analytics must target ALLOYDB_READ_POOL when read isolation is enabled." >&2
      exit 1
    }
  else
    [[ "${ANALYTICS_ALLOYDB_INSTANCE}" == "${ALLOYDB_INSTANCE}" ]] || {
      echo "Error: analytics must target ALLOYDB_INSTANCE when the read pool is disabled." >&2
      exit 1
    }
  fi

  [[ "${VPC_SC_MODE}" == "dry-run" || "${VPC_SC_MODE}" == "enforced" ]] || {
    echo "Error: VPC_SC_MODE must be dry-run or enforced." >&2
    exit 1
  }
  if [[ "${ENABLE_VPC_SC}" == "true" && "${VPC_SC_MODE}" == "enforced" &&
        "${VPC_SC_ENFORCEMENT_ACK}" != "I_ACKNOWLEDGE_VPC_SC_LOCKOUT_RISK" ]]; then
    echo "Error: enforced VPC-SC requires explicit lockout-risk acknowledgement." >&2
    exit 1
  fi

  [[ "${IDENTITY_PASSWORD_MIN_LENGTH}" -ge 6 &&
      "${IDENTITY_PASSWORD_MIN_LENGTH}" -le 30 &&
      "${IDENTITY_PASSWORD_MAX_LENGTH}" -ge "${IDENTITY_PASSWORD_MIN_LENGTH}" &&
      "${IDENTITY_PASSWORD_MAX_LENGTH}" -le 4096 ]] || {
    echo "Error: Identity password length bounds are invalid." >&2
    exit 1
  }

  local positive_name
  for positive_name in ASSISTANT_MAX_INSTANCES ASSISTANT_CPU \
      ASSISTANT_CONCURRENCY ASSISTANT_TIMEOUT TOOLBOX_MAX_INSTANCES TOOLBOX_CPU \
      TOOLBOX_CONCURRENCY TOOLBOX_TIMEOUT MIGRATION_CPU MIGRATION_TIMEOUT \
      ROUTER_MAX_OUTPUT_TOKENS SPECIALIST_MAX_OUTPUT_TOKENS \
      ANALYTICS_MAX_OUTPUT_TOKENS ARTIFACT_KEEP_COUNT ARTIFACT_RETENTION_DAYS \
      ANALYTICS_MAX_RANGE_DAYS ANALYTICS_QUERY_TIMEOUT_SECONDS \
      ANALYTICS_MAX_BYTES_BILLED \
      LOAD_TEST_MAX_BYTES_BILLED \
      ALLOYDB_STATE_TIMEOUT_SECONDS EMBEDDING_DIMENSIONS \
      MONITORING_ALIGNMENT_SECONDS MONITORING_P95_LATENCY_MS \
      MONITORING_ALLOYDB_CONNECTION_THRESHOLD UPTIME_CHECK_PERIOD \
      DEFAULT_PAGE_SIZE AGENT_CONTEXT_MAX_EVENTS PRIVACY_BATCH_SIZE \
      PRIVACY_MAX_BATCHES DATASTREAM_DB_PORT DATASTREAM_DATA_FRESHNESS_SECONDS; do
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
      "${#ANALYTICS_DB_PASSWORD}" -ge 24 &&
      "${#PRIVACY_DB_PASSWORD}" -ge 24 && "${#CDC_DB_PASSWORD}" -ge 24 ]] || {
    echo "Error: every database password in ${ENV_FILE} must contain at least 24 characters." >&2
    exit 1
  }
  [[ "${ADMIN_DB_USER}" =~ ^[a-z][a-z0-9_]{0,62}$ &&
      "${ALLOYDB_USER}" =~ ^[a-z][a-z0-9_]{0,62}$ &&
      "${ANALYTICS_DB_USER}" =~ ^[a-z][a-z0-9_]{0,62}$ &&
      "${PRIVACY_DB_USER}" =~ ^[a-z][a-z0-9_]{0,62}$ &&
      "${CDC_DB_USER}" =~ ^[a-z][a-z0-9_]{0,62}$ &&
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
      "${BIGQUERY_CONNECTION_ID}" =~ ^[A-Za-z0-9_]+$ &&
      "${BIGQUERY_ANALYTICS_PROCEDURE}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || {
    echo "Error: BigQuery dataset, connection, or procedure identifier is invalid." >&2
    exit 1
  }
  [[ "${ADMIN_DB_USER}" != "${ALLOYDB_USER}" &&
      "${ADMIN_DB_USER}" != "${ANALYTICS_DB_USER}" &&
      "${ALLOYDB_USER}" != "${ANALYTICS_DB_USER}" &&
      "${PRIVACY_DB_USER}" != "${ADMIN_DB_USER}" &&
      "${PRIVACY_DB_USER}" != "${ALLOYDB_USER}" &&
      "${PRIVACY_DB_USER}" != "${ANALYTICS_DB_USER}" &&
      "${CDC_DB_USER}" != "${ADMIN_DB_USER}" &&
      "${CDC_DB_USER}" != "${ALLOYDB_USER}" &&
      "${CDC_DB_USER}" != "${ANALYTICS_DB_USER}" &&
      "${CDC_DB_USER}" != "${PRIVACY_DB_USER}" ]] || {
    echo "Error: all database principals must be distinct." >&2
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
  [[ "${PRIVACY_TIMEZONE}" == "UTC" ||
      "${PRIVACY_TIMEZONE}" =~ ^[A-Za-z_]+/[A-Za-z0-9_+-]+$ ]] || {
    echo "Error: PRIVACY_TIMEZONE must be a valid IANA timezone." >&2
    exit 1
  }
  [[ "${DATASTREAM_LOCATION}" == "${REGION}" ]] || {
    echo "Error: DATASTREAM_LOCATION must match REGION." >&2
    exit 1
  }
  "${PYTHON_BIN}" -c \
    'import ipaddress,os; network=ipaddress.ip_network(os.environ["DATASTREAM_PEERING_CIDR"], strict=True); assert network.version == 4 and network.prefixlen == 29 and network.is_private' || {
    echo "Error: DATASTREAM_PEERING_CIDR must be a canonical private IPv4 /29." >&2
    exit 1
  }
  [[ "${DATASTREAM_DATA_FRESHNESS_SECONDS}" -ge 60 &&
      "${DATASTREAM_DATA_FRESHNESS_SECONDS}" -le 86400 ]] || {
    echo "Error: DATASTREAM_DATA_FRESHNESS_SECONDS must be 60..86400." >&2
    exit 1
  }
  for cdc_identifier in CDC_DB_USER DATASTREAM_PUBLICATION \
      DATASTREAM_REPLICATION_SLOT DATASTREAM_SOURCE_SCHEMA \
      DATASTREAM_SOURCE_TABLE BIGQUERY_NATIVE_TABLE; do
    [[ "${!cdc_identifier}" =~ ^[a-z][a-z0-9_]{0,62}$ ]] || {
      echo "Error: ${cdc_identifier} must be a lowercase SQL identifier." >&2
      exit 1
    }
  done
  [[ "${CDC_PROVISION_ACK}" == "NOT_ACKNOWLEDGED" ||
      "${CDC_PROVISION_ACK}" == "I_ACKNOWLEDGE_CDC_PROVISIONING_COST" ]] || {
    echo "Error: CDC_PROVISION_ACK has an unsupported value." >&2
    exit 1
  }
  [[ "${CDC_START_ACK}" == "NOT_ACKNOWLEDGED" ||
      "${CDC_START_ACK}" == "I_ACKNOWLEDGE_CDC_ACTIVATION_COST" ]] || {
    echo "Error: CDC_START_ACK has an unsupported value." >&2
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
      "${ANALYTICS_DB_PASSWORD}" != *"change-me"* &&
      "${PRIVACY_DB_PASSWORD}" != *"change-me"* &&
      "${CDC_DB_PASSWORD}" != *"change-me"* &&
      "${PSEUDONYMIZATION_KEY}" != *"change-me"* &&
      "${#PSEUDONYMIZATION_KEY}" -ge 32 ]] || {
    echo "Error: replace all password/key placeholders in ${ENV_FILE}." >&2
    exit 1
  }
  [[ "${ADMIN_DB_PASSWORD}" != "${APP_DB_PASSWORD}" &&
      "${ADMIN_DB_PASSWORD}" != "${ANALYTICS_DB_PASSWORD}" &&
      "${APP_DB_PASSWORD}" != "${ANALYTICS_DB_PASSWORD}" &&
      "${PRIVACY_DB_PASSWORD}" != "${ADMIN_DB_PASSWORD}" &&
      "${PRIVACY_DB_PASSWORD}" != "${APP_DB_PASSWORD}" &&
      "${PRIVACY_DB_PASSWORD}" != "${ANALYTICS_DB_PASSWORD}" &&
      "${CDC_DB_PASSWORD}" != "${ADMIN_DB_PASSWORD}" &&
      "${CDC_DB_PASSWORD}" != "${APP_DB_PASSWORD}" &&
      "${CDC_DB_PASSWORD}" != "${ANALYTICS_DB_PASSWORD}" &&
      "${CDC_DB_PASSWORD}" != "${PRIVACY_DB_PASSWORD}" ]] || {
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
      [[ "${MONITORING_REQUIRE_NOTIFICATION_CHANNELS}" == "true" &&
          -n "${MONITORING_NOTIFICATION_CHANNELS:-}" ]] || {
        echo "Error: production requires configured monitoring notification channels." >&2
        exit 1
      }
      ;;
  esac
}

preflight() {
  validate_config
  preflight_project_access
  local billing
  billing="$(gcloud billing projects describe "${PROJECT_ID}" --format='value(billingEnabled)')"
  [[ "${billing,,}" == "true" ]] || {
    echo "Error: billing is not enabled for ${PROJECT_ID}." >&2
    exit 1
  }
}

preflight_project_access() {
  require_command gcloud
  gcloud projects describe "${PROJECT_ID}" --format='value(projectId)' >/dev/null
  local active_project
  active_project="$(gcloud config get-value project 2>/dev/null || true)"
  [[ "${active_project}" == "${PROJECT_ID}" ]] || {
    echo "Error: active gcloud project '${active_project}' differs from '${PROJECT_ID}'." >&2
    echo "Run: gcloud config set project ${PROJECT_ID}" >&2
    exit 1
  }
  require_command "${BQ_BIN}"
  require_command curl
}

secret_version() {
  gcloud secrets versions list "$1" --project="${PROJECT_ID}" \
    --filter='state=ENABLED' --sort-by='~createTime' --limit=1 \
    --format='value(name.basename())'
}

ensure_secret_from_env() {
  local name="$1" value="$2" current="" version=""
  if ! gcloud secrets describe "${name}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    if [[ "${ENABLE_CMEK}" == "true" ]]; then
      local kms_key
      kms_key="projects/${PROJECT_ID}/locations/${REGION}/keyRings/${KMS_KEYRING}/cryptoKeys/${KMS_SECRET_KEY}"
      gcloud secrets create "${name}" --replication-policy=user-managed \
        --locations="${REGION}" --kms-key-name="${kms_key}" \
        --project="${PROJECT_ID}"
    else
      gcloud secrets create "${name}" --replication-policy=automatic \
        --project="${PROJECT_ID}"
    fi
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
