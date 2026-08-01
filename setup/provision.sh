#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=setup/common.sh
source "${SCRIPT_DIR}/common.sh"

require_phase5
preflight

APIS=(
  alloydb.googleapis.com
  aiplatform.googleapis.com
  artifactregistry.googleapis.com
  bigquery.googleapis.com
  bigqueryconnection.googleapis.com
  billingbudgets.googleapis.com
  accesscontextmanager.googleapis.com
  cloudbuild.googleapis.com
  cloudkms.googleapis.com
  cloudscheduler.googleapis.com
  compute.googleapis.com
  iam.googleapis.com
  identitytoolkit.googleapis.com
  monitoring.googleapis.com
  run.googleapis.com
  secretmanager.googleapis.com
  servicenetworking.googleapis.com
  serviceusage.googleapis.com
)
gcloud services enable "${APIS[@]}" --project="${PROJECT_ID}"
"${SCRIPT_DIR}/security_setup.sh"

BILLING_ACCOUNT="$(gcloud billing projects describe "${PROJECT_ID}" \
  --format='value(billingAccountName.basename())')"
IFS=',' read -r -a budget_thresholds <<<"${BUDGET_THRESHOLDS}"
budget_resource="$(gcloud billing budgets list --billing-account="${BILLING_ACCOUNT}" \
  --format=json | "${PYTHON_BIN}" -c \
  'import json,sys; target=sys.argv[1]; print(next((item["name"] for item in json.load(sys.stdin) if item.get("displayName") == target), ""))' \
  "${BUDGET_NAME}")"
if [[ -z "${budget_resource}" ]]; then
  threshold_args=()
  for threshold in "${budget_thresholds[@]}"; do
    threshold_args+=(--threshold-rule="percent=${threshold}")
  done
  gcloud billing budgets create --billing-account="${BILLING_ACCOUNT}" \
    --display-name="${BUDGET_NAME}" --budget-amount="${BUDGET_AMOUNT}" \
    --filter-projects="projects/${PROJECT_ID}" \
    "${threshold_args[@]}"
else
  threshold_args=(--clear-threshold-rules)
  for threshold in "${budget_thresholds[@]}"; do
    threshold_args+=(--add-threshold-rule="percent=${threshold}")
  done
  gcloud billing budgets update "${budget_resource##*/}" \
    --billing-account="${BILLING_ACCOUNT}" \
    --budget-amount="${BUDGET_AMOUNT}" \
    --filter-projects="projects/${PROJECT_ID}" \
    "${threshold_args[@]}"
fi

ensure_service_account() {
  local name="$1" display="$2"
  if ! gcloud iam service-accounts describe "${name}@${PROJECT_ID}.iam.gserviceaccount.com" \
      --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud iam service-accounts create "${name}" --display-name="${display}" \
      --project="${PROJECT_ID}"
  fi
}

grant_project_role() {
  local account="$1" role="$2"
  if grep -Fq "${role}"$'\t'"serviceAccount:${account}" <<<"${PROJECT_IAM:-}"; then
    return
  fi
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${account}" --role="${role}" \
    --condition=None --quiet >/dev/null
}

ensure_service_account "${ASSISTANT_SA_NAME}" "Productivity Intelligence runtime"
ensure_service_account "${TOOLBOX_SA_NAME}" "Productivity Intelligence Toolbox"
ensure_service_account "${MIGRATION_SA_NAME}" "Productivity Intelligence migrations"
ensure_service_account "${LIFECYCLE_SA_NAME}" "Productivity Intelligence lifecycle"
ensure_service_account "${SCHEDULER_SA_NAME}" "Productivity Intelligence scheduler"
DEPLOYER_ACCOUNT="$(gcloud config get-value account 2>/dev/null)"
if [[ "${DEPLOYER_ACCOUNT}" == *".gserviceaccount.com" ]]; then
  DEPLOYER_MEMBER="serviceAccount:${DEPLOYER_ACCOUNT}"
else
  DEPLOYER_MEMBER="user:${DEPLOYER_ACCOUNT}"
fi
gcloud iam service-accounts add-iam-policy-binding "${ASSISTANT_SA}" \
  --project="${PROJECT_ID}" --member="${DEPLOYER_MEMBER}" \
  --role=roles/iam.serviceAccountTokenCreator --quiet >/dev/null
gcloud iam service-accounts add-iam-policy-binding "${SCHEDULER_SA}" \
  --project="${PROJECT_ID}" --member="${DEPLOYER_MEMBER}" \
  --role=roles/iam.serviceAccountUser --quiet >/dev/null
PROJECT_IAM="$(gcloud projects get-iam-policy "${PROJECT_ID}" --flatten='bindings[].members' \
  --format='value(bindings.role,bindings.members)')"

if gcloud iam roles describe "${LIFECYCLE_ROLE_ID}" --project="${PROJECT_ID}" \
    >/dev/null 2>&1; then
  gcloud iam roles update "${LIFECYCLE_ROLE_ID}" --project="${PROJECT_ID}" \
    --title="Productivity AlloyDB lifecycle" \
    --description="Start and stop only the configured productivity AlloyDB instance" \
    --permissions=alloydb.instances.get,alloydb.instances.update \
    --stage=GA >/dev/null
else
  gcloud iam roles create "${LIFECYCLE_ROLE_ID}" --project="${PROJECT_ID}" \
    --title="Productivity AlloyDB lifecycle" \
    --description="Start and stop only the configured productivity AlloyDB instance" \
    --permissions=alloydb.instances.get,alloydb.instances.update \
    --stage=GA >/dev/null
fi

for role in roles/aiplatform.user roles/mcp.toolUser roles/bigquery.jobUser \
  roles/bigquery.dataViewer roles/bigquery.connectionUser roles/logging.logWriter \
  roles/serviceusage.serviceUsageConsumer; do
  grant_project_role "${ASSISTANT_SA}" "${role}"
done
for role in roles/alloydb.client roles/logging.logWriter; do
  grant_project_role "${TOOLBOX_SA}" "${role}"
  grant_project_role "${MIGRATION_SA}" "${role}"
done
for role in "projects/${PROJECT_ID}/roles/${LIFECYCLE_ROLE_ID}" roles/logging.logWriter; do
  grant_project_role "${LIFECYCLE_SA}" "${role}"
done

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
BUILD_SERVICE_ACCOUNT="$(gcloud builds get-default-service-account \
  --project="${PROJECT_ID}")"
grant_project_role "${BUILD_SERVICE_ACCOUNT}" roles/cloudbuild.builds.builder
ALLOYDB_SERVICE_AGENT="service-${PROJECT_NUMBER}@gcp-sa-alloydb.iam.gserviceaccount.com"
gcloud beta services identity create --service=alloydb.googleapis.com \
  --project="${PROJECT_ID}" >/dev/null
grant_project_role "${ALLOYDB_SERVICE_AGENT}" roles/aiplatform.user

ensure_secret_from_env "${ADMIN_DB_SECRET}" "${ADMIN_DB_PASSWORD}"
ensure_secret_from_env "${APP_DB_SECRET}" "${APP_DB_PASSWORD}"
ensure_secret_from_env "${ANALYTICS_DB_SECRET}" "${ANALYTICS_DB_PASSWORD}"
ensure_secret_from_env "${PSEUDONYMIZATION_SECRET}" "${PSEUDONYMIZATION_KEY}"

gcloud secrets add-iam-policy-binding "${APP_DB_SECRET}" --project="${PROJECT_ID}" \
  --member="serviceAccount:${TOOLBOX_SA}" --role=roles/secretmanager.secretAccessor \
  --condition=None --quiet >/dev/null
for secret in "${ADMIN_DB_SECRET}" "${APP_DB_SECRET}" "${ANALYTICS_DB_SECRET}"; do
  gcloud secrets add-iam-policy-binding "${secret}" --project="${PROJECT_ID}" \
    --member="serviceAccount:${MIGRATION_SA}" --role=roles/secretmanager.secretAccessor \
    --condition=None --quiet >/dev/null
done
gcloud secrets add-iam-policy-binding "${PSEUDONYMIZATION_SECRET}" \
  --project="${PROJECT_ID}" --member="serviceAccount:${ASSISTANT_SA}" \
  --role=roles/secretmanager.secretAccessor --condition=None --quiet >/dev/null
gcloud secrets add-iam-policy-binding "${PSEUDONYMIZATION_SECRET}" \
  --project="${PROJECT_ID}" --member="serviceAccount:${MIGRATION_SA}" \
  --role=roles/secretmanager.secretAccessor --condition=None --quiet >/dev/null

if ! gcloud compute networks describe "${VPC_NETWORK}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud compute networks create "${VPC_NETWORK}" --subnet-mode=custom \
    --project="${PROJECT_ID}"
fi
if ! gcloud compute networks subnets describe "${VPC_SUBNET}" --region="${REGION}" \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud compute networks subnets create "${VPC_SUBNET}" --network="${VPC_NETWORK}" \
    --range="${VPC_SUBNET_RANGE}" --region="${REGION}" --project="${PROJECT_ID}"
fi
if ! gcloud compute addresses describe "${PSA_RANGE_NAME}" --global \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud compute addresses create "${PSA_RANGE_NAME}" --global \
    --purpose=VPC_PEERING --prefix-length=16 --network="${VPC_NETWORK}" \
    --project="${PROJECT_ID}"
fi
if ! gcloud services vpc-peerings list --network="${VPC_NETWORK}" \
    --project="${PROJECT_ID}" --format='value(service)' | \
    grep -qx 'servicenetworking.googleapis.com'; then
  gcloud services vpc-peerings connect --service=servicenetworking.googleapis.com \
    --ranges="${PSA_RANGE_NAME}" --network="${VPC_NETWORK}" \
    --project="${PROJECT_ID}"
fi

if ! gcloud artifacts repositories describe "${AR_REPO}" --location="${REGION}" \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${AR_REPO}" --repository-format=docker \
    --location="${REGION}" --description="Productivity Intelligence Platform images" \
    --labels="${RESOURCE_LABELS}" \
    --project="${PROJECT_ID}"
fi
cleanup_policy_file="$(mktemp)"
trap 'rm -f "${cleanup_policy_file}"' EXIT
cat >"${cleanup_policy_file}" <<EOF
[
  {
    "name": "delete-old-images",
    "action": {"type": "Delete"},
    "condition": {"tagState": "any", "olderThan": "${ARTIFACT_RETENTION_DAYS}d"}
  },
  {
    "name": "keep-recent-images",
    "action": {"type": "Keep"},
    "mostRecentVersions": {"keepCount": ${ARTIFACT_KEEP_COUNT}}
  }
]
EOF
gcloud artifacts repositories set-cleanup-policies "${AR_REPO}" \
  --location="${REGION}" --project="${PROJECT_ID}" \
  --policy="${cleanup_policy_file}" --no-dry-run
rm -f "${cleanup_policy_file}"
trap - EXIT

if ! gcloud alloydb clusters describe "${ALLOYDB_CLUSTER}" --region="${REGION}" \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
  flags_file="$(mktemp)"
  chmod 600 "${flags_file}"
  trap 'rm -f "${flags_file}"' EXIT
  printf '%s\n' "--password: ${ADMIN_DB_PASSWORD}" >"${flags_file}"
  cluster_args=(
    "${ALLOYDB_CLUSTER}" "--region=${REGION}"
    "--network=projects/${PROJECT_ID}/global/networks/${VPC_NETWORK}"
    "--allocated-ip-range-name=${PSA_RANGE_NAME}" "--project=${PROJECT_ID}"
    "--flags-file=${flags_file}"
  )
  if [[ "${ENABLE_CMEK}" == "true" ]]; then
    cluster_args+=(
      "--kms-key=projects/${PROJECT_ID}/locations/${REGION}/keyRings/${KMS_KEYRING}/cryptoKeys/${KMS_ALLOYDB_KEY}"
    )
  fi
  gcloud alloydb clusters create "${cluster_args[@]}"
  rm -f "${flags_file}"
  trap - EXIT
fi
if ! gcloud alloydb instances describe "${ALLOYDB_INSTANCE}" \
    --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud alloydb instances create "${ALLOYDB_INSTANCE}" \
    --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" --instance-type=PRIMARY \
    --availability-type="${ALLOYDB_AVAILABILITY_TYPE}" \
    --machine-type="${ALLOYDB_MACHINE_TYPE}" \
    --project="${PROJECT_ID}"
  if [[ "${ALLOYDB_ACTIVATION_POLICY}" == "NEVER" ]]; then
    gcloud alloydb instances update "${ALLOYDB_INSTANCE}" \
      --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
      --activation-policy=NEVER --project="${PROJECT_ID}" --quiet
  fi
else
  read -r current_availability current_machine current_activation < <(
    gcloud alloydb instances describe "${ALLOYDB_INSTANCE}" \
    --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" --project="${PROJECT_ID}" \
    --format='value(availabilityType,machineConfig.machineType,activationPolicy)'
  )
  if [[ "${current_machine}" != "${ALLOYDB_MACHINE_TYPE}" &&
      "${ALLOW_ALLOYDB_RESIZE}" != "true" ]]; then
    echo "Error: deployed AlloyDB machine '${current_machine}' differs from" >&2
    echo "'${ALLOYDB_MACHINE_TYPE}'. Set ALLOW_ALLOYDB_RESIZE=true in .env to resize." >&2
    exit 1
  fi
  if [[ "${current_availability}" != "${ALLOYDB_AVAILABILITY_TYPE}" ]]; then
    gcloud alloydb instances update "${ALLOYDB_INSTANCE}" \
      --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
      --availability-type="${ALLOYDB_AVAILABILITY_TYPE}" --project="${PROJECT_ID}" \
      --quiet
  fi
  if [[ "${current_machine}" != "${ALLOYDB_MACHINE_TYPE}" ]]; then
    gcloud alloydb instances update "${ALLOYDB_INSTANCE}" \
      --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
      --machine-type="${ALLOYDB_MACHINE_TYPE}" --project="${PROJECT_ID}" --quiet
  fi
  if [[ "${current_activation}" != "${ALLOYDB_ACTIVATION_POLICY}" ]]; then
    gcloud alloydb instances update "${ALLOYDB_INSTANCE}" \
      --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
      --activation-policy="${ALLOYDB_ACTIVATION_POLICY}" \
      --project="${PROJECT_ID}" --quiet
  fi
fi

if [[ "${ENABLE_ALLOYDB_READ_POOL}" == "true" ]]; then
  if ! gcloud alloydb instances describe "${ALLOYDB_READ_POOL}" \
      --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
      --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud alloydb instances create "${ALLOYDB_READ_POOL}" \
      --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
      --instance-type=READ_POOL \
      --read-pool-node-count="${ALLOYDB_READ_POOL_NODE_COUNT}" \
      --machine-type="${ALLOYDB_READ_POOL_MACHINE_TYPE}" \
      --project="${PROJECT_ID}"
  else
    read -r read_pool_machine read_pool_nodes read_pool_activation < <(
      gcloud alloydb instances describe "${ALLOYDB_READ_POOL}" \
        --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
        --project="${PROJECT_ID}" \
        --format='value(machineConfig.machineType,readPoolConfig.nodeCount,activationPolicy)'
    )
    if [[ ("${read_pool_machine}" != "${ALLOYDB_READ_POOL_MACHINE_TYPE}" ||
          "${read_pool_nodes}" != "${ALLOYDB_READ_POOL_NODE_COUNT}") &&
          "${ALLOW_ALLOYDB_RESIZE}" != "true" ]]; then
      echo "Error: deployed read-pool shape differs from .env." >&2
      echo "Set ALLOW_ALLOYDB_RESIZE=true to reconcile it explicitly." >&2
      exit 1
    fi
    if [[ "${read_pool_machine}" != "${ALLOYDB_READ_POOL_MACHINE_TYPE}" ||
          "${read_pool_nodes}" != "${ALLOYDB_READ_POOL_NODE_COUNT}" ]]; then
      gcloud alloydb instances update "${ALLOYDB_READ_POOL}" \
        --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
        --machine-type="${ALLOYDB_READ_POOL_MACHINE_TYPE}" \
        --read-pool-node-count="${ALLOYDB_READ_POOL_NODE_COUNT}" \
        --project="${PROJECT_ID}" --quiet
    fi
    if [[ "${read_pool_activation}" != "${ALLOYDB_ACTIVATION_POLICY}" ]]; then
      gcloud alloydb instances update "${ALLOYDB_READ_POOL}" \
        --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
        --activation-policy="${ALLOYDB_ACTIVATION_POLICY}" \
        --project="${PROJECT_ID}" --quiet
    fi
  fi
  if [[ "${ALLOYDB_ACTIVATION_POLICY}" == "NEVER" ]]; then
    gcloud alloydb instances update "${ALLOYDB_READ_POOL}" \
      --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
      --activation-policy=NEVER --project="${PROJECT_ID}" --quiet
  fi
elif gcloud alloydb instances describe "${ALLOYDB_READ_POOL}" \
    --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud alloydb instances update "${ALLOYDB_READ_POOL}" \
    --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
    --activation-policy=NEVER --project="${PROJECT_ID}" --quiet
  echo "[OK] Disabled AlloyDB read pool is explicitly suspended."
fi

admin_flags_file="$(mktemp)"
chmod 600 "${admin_flags_file}"
trap 'rm -f "${admin_flags_file}"' EXIT
printf '%s\n' "--password: ${ADMIN_DB_PASSWORD}" >"${admin_flags_file}"
gcloud alloydb users set-password "${ADMIN_DB_USER}" \
  --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
  --project="${PROJECT_ID}" --flags-file="${admin_flags_file}" >/dev/null
rm -f "${admin_flags_file}"
trap - EXIT

echo "[OK] Infrastructure provisioned in ${PROJECT_ID}/${REGION} (${COST_PROFILE})"
