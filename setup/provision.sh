#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=setup/common.sh
source "${SCRIPT_DIR}/common.sh"

preflight

APIS=(
  alloydb.googleapis.com
  aiplatform.googleapis.com
  artifactregistry.googleapis.com
  bigquery.googleapis.com
  bigqueryconnection.googleapis.com
  billingbudgets.googleapis.com
  cloudbuild.googleapis.com
  compute.googleapis.com
  iam.googleapis.com
  monitoring.googleapis.com
  run.googleapis.com
  secretmanager.googleapis.com
  servicenetworking.googleapis.com
  serviceusage.googleapis.com
)
gcloud services enable "${APIS[@]}" --project="${PROJECT_ID}"

BILLING_ACCOUNT="$(gcloud billing projects describe "${PROJECT_ID}" \
  --format='value(billingAccountName.basename())')"
if ! gcloud billing budgets list --billing-account="${BILLING_ACCOUNT}" \
    --filter="displayName='${BUDGET_NAME}'" --format='value(name)' | grep -q .; then
  gcloud billing budgets create --billing-account="${BILLING_ACCOUNT}" \
    --display-name="${BUDGET_NAME}" --budget-amount="${BUDGET_AMOUNT}" \
    --filter-projects="projects/${PROJECT_ID}" \
    --threshold-rule=percent=0.50 --threshold-rule=percent=0.90 \
    --threshold-rule=percent=1.00
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

ensure_service_account "${ASSISTANT_SA_NAME}" "Productivity Assistant runtime"
ensure_service_account "${TOOLBOX_SA_NAME}" "Productivity Toolbox runtime"
ensure_service_account "${MIGRATION_SA_NAME}" "Productivity database migrations"
DEPLOYER_ACCOUNT="$(gcloud config get-value account 2>/dev/null)"
if [[ "${DEPLOYER_ACCOUNT}" == *".gserviceaccount.com" ]]; then
  DEPLOYER_MEMBER="serviceAccount:${DEPLOYER_ACCOUNT}"
else
  DEPLOYER_MEMBER="user:${DEPLOYER_ACCOUNT}"
fi
gcloud iam service-accounts add-iam-policy-binding "${ASSISTANT_SA}" \
  --project="${PROJECT_ID}" --member="${DEPLOYER_MEMBER}" \
  --role=roles/iam.serviceAccountTokenCreator --quiet >/dev/null
PROJECT_IAM="$(gcloud projects get-iam-policy "${PROJECT_ID}" --flatten='bindings[].members' \
  --format='value(bindings.role,bindings.members)')"

for role in roles/aiplatform.user roles/mcp.toolUser roles/bigquery.jobUser \
  roles/bigquery.dataViewer roles/bigquery.connectionUser roles/logging.logWriter \
  roles/serviceusage.serviceUsageConsumer; do
  grant_project_role "${ASSISTANT_SA}" "${role}"
done
for role in roles/alloydb.client roles/logging.logWriter; do
  grant_project_role "${TOOLBOX_SA}" "${role}"
  grant_project_role "${MIGRATION_SA}" "${role}"
done

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
ALLOYDB_SERVICE_AGENT="service-${PROJECT_NUMBER}@gcp-sa-alloydb.iam.gserviceaccount.com"
grant_project_role "${ALLOYDB_SERVICE_AGENT}" roles/aiplatform.user

ensure_secret "${ADMIN_DB_SECRET}"
ensure_secret "${APP_DB_SECRET}"
ensure_secret "${ANALYTICS_DB_SECRET}"

gcloud secrets add-iam-policy-binding "${APP_DB_SECRET}" --project="${PROJECT_ID}" \
  --member="serviceAccount:${TOOLBOX_SA}" --role=roles/secretmanager.secretAccessor \
  --condition=None --quiet >/dev/null
for secret in "${ADMIN_DB_SECRET}" "${APP_DB_SECRET}" "${ANALYTICS_DB_SECRET}"; do
  gcloud secrets add-iam-policy-binding "${secret}" --project="${PROJECT_ID}" \
    --member="serviceAccount:${MIGRATION_SA}" --role=roles/secretmanager.secretAccessor \
    --condition=None --quiet >/dev/null
done

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
    --location="${REGION}" --description="Productivity Assistant images" \
    --project="${PROJECT_ID}"
fi

if ! gcloud alloydb clusters describe "${ALLOYDB_CLUSTER}" --region="${REGION}" \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
  flags_file="$(mktemp)"
  chmod 600 "${flags_file}"
  trap 'rm -f "${flags_file}"' EXIT
  admin_password="$(gcloud secrets versions access "$(secret_version "${ADMIN_DB_SECRET}")" \
    --secret="${ADMIN_DB_SECRET}" --project="${PROJECT_ID}")"
  printf '%s\n' "--password: ${admin_password}" >"${flags_file}"
  unset admin_password
  gcloud alloydb clusters create "${ALLOYDB_CLUSTER}" --region="${REGION}" \
    --network="projects/${PROJECT_ID}/global/networks/${VPC_NETWORK}" \
    --allocated-ip-range-name="${PSA_RANGE_NAME}" --project="${PROJECT_ID}" \
    --flags-file="${flags_file}"
  rm -f "${flags_file}"
  trap - EXIT
fi
if ! gcloud alloydb instances describe "${ALLOYDB_INSTANCE}" \
    --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud alloydb instances create "${ALLOYDB_INSTANCE}" \
    --cluster="${ALLOYDB_CLUSTER}" --region="${REGION}" --instance-type=PRIMARY \
    --cpu-count=2 --project="${PROJECT_ID}"
fi

echo "[OK] Infrastructure provisioned in ${PROJECT_ID}/${REGION}"
