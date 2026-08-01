#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=setup/common.sh
source "${SCRIPT_DIR}/../setup/common.sh"
preflight

cat <<EOF
This will delete the Productivity Intelligence Platform resources from:
  Project: ${PROJECT_ID}
  Region:  ${REGION}
  Cloud Run services: ${ASSISTANT_SERVICE_NAME}, ${TOOLBOX_SERVICE_NAME}
  Cloud Run jobs: ${MIGRATION_JOB_NAME}, ${LIFECYCLE_JOB_NAME}-resume, ${LIFECYCLE_JOB_NAME}-suspend, ${PRIVACY_JOB_NAME}
  AlloyDB cluster: ${ALLOYDB_CLUSTER}
  BigQuery dataset/connection: ${BIGQUERY_DATASET}, ${BIGQUERY_CONNECTION_ID}
  Artifact Registry: ${AR_REPO}
  Secrets: ${ADMIN_DB_SECRET}, ${APP_DB_SECRET}, ${ANALYTICS_DB_SECRET}, ${PRIVACY_DB_SECRET}, ${CDC_DB_SECRET}, ${PSEUDONYMIZATION_SECRET}
  Optional CDC stream/profile/private connection: ${DATASTREAM_STREAM}, ${DATASTREAM_SOURCE_PROFILE}, ${DATASTREAM_DESTINATION_PROFILE}, ${DATASTREAM_PRIVATE_CONNECTION}
  Optional KMS key ring: ${KMS_KEYRING}
  Runtime service accounts: ${ASSISTANT_SA}, ${TOOLBOX_SA}, ${MIGRATION_SA}, ${LIFECYCLE_SA}, ${PRIVACY_SA}, ${SCHEDULER_SA}
  Monitoring: Productivity Intelligence policies, uptime check, and log metrics
  Billing budget: ${BUDGET_NAME}
  Network: ${VPC_NETWORK}/${VPC_SUBNET}
EOF
read -r -p "Type the project ID to confirm: " confirmation
[[ "${confirmation}" == "${PROJECT_ID}" ]] || {
  echo "Cleanup cancelled."
  exit 1
}

gcloud run services delete "${ASSISTANT_SERVICE_NAME}" --region="${REGION}" \
  --project="${PROJECT_ID}" --quiet 2>/dev/null || true
gcloud run services delete "${TOOLBOX_SERVICE_NAME}" --region="${REGION}" \
  --project="${PROJECT_ID}" --quiet 2>/dev/null || true
gcloud run jobs delete "${MIGRATION_JOB_NAME}" --region="${REGION}" \
  --project="${PROJECT_ID}" --quiet 2>/dev/null || true
for action in resume suspend; do
  gcloud scheduler jobs delete "${LIFECYCLE_JOB_NAME}-${action}" \
    --location="${REGION}" --project="${PROJECT_ID}" --quiet 2>/dev/null || true
  gcloud run jobs delete "${LIFECYCLE_JOB_NAME}-${action}" --region="${REGION}" \
    --project="${PROJECT_ID}" --quiet 2>/dev/null || true
done
gcloud scheduler jobs delete "${PRIVACY_JOB_NAME}-retention" \
  --location="${REGION}" --project="${PROJECT_ID}" --quiet 2>/dev/null || true
gcloud run jobs delete "${PRIVACY_JOB_NAME}" --region="${REGION}" \
  --project="${PROJECT_ID}" --quiet 2>/dev/null || true

while IFS= read -r policy; do
  [[ -z "${policy}" ]] || gcloud monitoring policies delete "${policy}" \
    --project="${PROJECT_ID}" --quiet 2>/dev/null || true
done < <(gcloud monitoring policies list --project="${PROJECT_ID}" \
  --filter='displayName:"Productivity Intelligence"' \
  --format='value(name)' 2>/dev/null)

while IFS= read -r uptime; do
  [[ -z "${uptime}" ]] || gcloud monitoring uptime delete "${uptime}" \
    --project="${PROJECT_ID}" --quiet 2>/dev/null || true
done < <(gcloud monitoring uptime list-configs --project="${PROJECT_ID}" \
  --filter='displayName="Productivity Intelligence hosted liveness"' \
  --format='value(name)' 2>/dev/null)

for metric in startup_failures toolbox_authorization_failures mcp_failures bigquery_errors; do
  gcloud logging metrics delete "productivity_${metric}" --project="${PROJECT_ID}" \
    --quiet 2>/dev/null || true
done
gcloud logging sinks update _Default --project="${PROJECT_ID}" \
  --remove-exclusions=productivity-health-success >/dev/null 2>&1 || true

"${BQ_BIN}" rm -r -f -d "${PROJECT_ID}:${BIGQUERY_DATASET}" 2>/dev/null || true
"${BQ_BIN}" rm -f --connection --location="${REGION}" \
  "${PROJECT_ID}.${REGION}.${BIGQUERY_CONNECTION_ID}" 2>/dev/null || true
gcloud datastream streams delete "${DATASTREAM_STREAM}" \
  --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}" \
  --quiet 2>/dev/null || true
for profile in "${DATASTREAM_SOURCE_PROFILE}" "${DATASTREAM_DESTINATION_PROFILE}"; do
  gcloud datastream connection-profiles delete "${profile}" \
    --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}" \
    --quiet 2>/dev/null || true
done
gcloud datastream private-connections delete "${DATASTREAM_PRIVATE_CONNECTION}" \
  --location="${DATASTREAM_LOCATION}" --project="${PROJECT_ID}" \
  --quiet 2>/dev/null || true
gcloud alloydb clusters delete "${ALLOYDB_CLUSTER}" --region="${REGION}" \
  --project="${PROJECT_ID}" --force --quiet 2>/dev/null || true
gcloud artifacts repositories delete "${AR_REPO}" --location="${REGION}" \
  --project="${PROJECT_ID}" --quiet 2>/dev/null || true
for secret in "${ADMIN_DB_SECRET}" "${APP_DB_SECRET}" "${ANALYTICS_DB_SECRET}" \
    "${PRIVACY_DB_SECRET}" "${CDC_DB_SECRET}" "${PSEUDONYMIZATION_SECRET}"; do
  gcloud secrets delete "${secret}" --project="${PROJECT_ID}" --quiet 2>/dev/null || true
done
if [[ "${ENABLE_CMEK}" == "true" ]]; then
  for key in "${KMS_ALLOYDB_KEY}" "${KMS_BIGQUERY_KEY}" "${KMS_SECRET_KEY}"; do
    while IFS= read -r version; do
      [[ -z "${version}" ]] || gcloud kms keys versions destroy "${version}" \
        --key="${key}" --keyring="${KMS_KEYRING}" --location="${REGION}" \
        --project="${PROJECT_ID}" --quiet 2>/dev/null || true
    done < <(gcloud kms keys versions list --key="${key}" \
      --keyring="${KMS_KEYRING}" --location="${REGION}" \
      --project="${PROJECT_ID}" --filter='state=ENABLED' \
      --format='value(name.basename())' 2>/dev/null)
  done
  echo "[INFO] Empty Cloud KMS key/key-ring metadata is retained because Google Cloud does not permit deleting it."
fi

for role in roles/aiplatform.user roles/mcp.toolUser roles/bigquery.jobUser \
    roles/bigquery.dataViewer roles/bigquery.connectionUser roles/logging.logWriter \
    roles/serviceusage.serviceUsageConsumer; do
  gcloud projects remove-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${ASSISTANT_SA}" --role="${role}" --condition=None \
    --quiet >/dev/null 2>&1 || true
done
for account in "${TOOLBOX_SA}" "${MIGRATION_SA}" "${PRIVACY_SA}"; do
  for role in roles/alloydb.client roles/logging.logWriter; do
    gcloud projects remove-iam-policy-binding "${PROJECT_ID}" \
      --member="serviceAccount:${account}" --role="${role}" --condition=None \
      --quiet >/dev/null 2>&1 || true
  done
done
for role in "projects/${PROJECT_ID}/roles/${LIFECYCLE_ROLE_ID}" roles/logging.logWriter; do
  gcloud projects remove-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${LIFECYCLE_SA}" --role="${role}" --condition=None \
    --quiet >/dev/null 2>&1 || true
done
gcloud iam roles delete "${LIFECYCLE_ROLE_ID}" --project="${PROJECT_ID}" \
  --quiet >/dev/null 2>&1 || true
for service_account in "${ASSISTANT_SA}" "${TOOLBOX_SA}" "${MIGRATION_SA}" \
    "${LIFECYCLE_SA}" "${PRIVACY_SA}" "${SCHEDULER_SA}"; do
  gcloud iam service-accounts delete "${service_account}" --project="${PROJECT_ID}" \
    --quiet 2>/dev/null || true
done

project_number="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
gcloud projects remove-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:service-${project_number}@gcp-sa-alloydb.iam.gserviceaccount.com" \
  --role=roles/aiplatform.user --condition=None --quiet >/dev/null 2>&1 || true
gcloud projects remove-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:service-${project_number}@gcp-sa-bigqueryconnection.iam.gserviceaccount.com" \
  --role=roles/alloydb.client --condition=None --quiet >/dev/null 2>&1 || true

billing_account="$(gcloud billing projects describe "${PROJECT_ID}" \
  --format='value(billingAccountName.basename())' 2>/dev/null || true)"
if [[ -n "${billing_account}" ]]; then
  while IFS= read -r budget; do
    [[ -z "${budget}" ]] || gcloud billing budgets delete "${budget}" \
      --billing-account="${billing_account}" --quiet 2>/dev/null || true
  done < <(gcloud billing budgets list --billing-account="${billing_account}" \
    --format=json 2>/dev/null | "${PYTHON_BIN}" -c \
    'import json,sys; target=sys.argv[1]; print("\n".join(item["name"] for item in json.load(sys.stdin) if item.get("displayName") == target))' \
    "${BUDGET_NAME}")
fi

gcloud services vpc-peerings delete --service=servicenetworking.googleapis.com \
  --network="${VPC_NETWORK}" --project="${PROJECT_ID}" --quiet 2>/dev/null || true
gcloud compute addresses delete "${PSA_RANGE_NAME}" --global \
  --project="${PROJECT_ID}" --quiet 2>/dev/null || true
gcloud compute networks subnets delete "${VPC_SUBNET}" --region="${REGION}" \
  --project="${PROJECT_ID}" --quiet 2>/dev/null || true
gcloud compute networks delete "${VPC_NETWORK}" --project="${PROJECT_ID}" \
  --quiet 2>/dev/null || true

echo "[OK] Productivity Intelligence Platform resources removed. Cloud deletion is not recoverable."
