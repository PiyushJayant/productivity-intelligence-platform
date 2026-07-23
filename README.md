# Productivity Intelligence Platform

A secure Google ADK work-orchestration platform for shared synthetic tasks,
semantic knowledge, calendar events, and live productivity analytics on Google Cloud.

> This is a public demonstration application. Do not enter personal,
> confidential, regulated, or production data. The assistant endpoint is public
> for judging; its MCP Toolbox data plane is protected by Cloud Run IAM.

## Architecture

```text
Public user
   |
   v
Cloud Run: productivity-intelligence (public, orchestration identity)
   |-- task / notes / calendar agents
   |      |  Cloud Run ID token
   |      v
   |   Cloud Run: productivity-toolbox (IAM protected, toolbox identity)
   |      |  Direct VPC egress
   |      v
   |   AlloyDB: tasks, notes, events, vector embeddings
   |
   +-- analytics agent -> hosted BigQuery MCP (read-only tools)
                              |
                              v
                         BigQuery live views
                              |
                              v
                         EXTERNAL_QUERY -> AlloyDB
```

The deployment uses separate assistant, Toolbox, and migration service accounts.
Database administrator, application, and analytics passwords are generated into
Secret Manager and never stored in `.env` or Git.

## Prerequisites

- A billing-enabled Google Cloud project in which you can create IAM, AlloyDB,
  Cloud Run, networking, Secret Manager, BigQuery, and Cloud Build resources.
- Owner-level setup permission, or equivalent granular permissions for IAM,
  AlloyDB, Cloud Run, networking, Secret Manager, BigQuery, and Cloud Build.
- `gcloud`, `bq`, `curl`, `openssl`, Git, Bash, and Python 3.11.
- Active gcloud project must exactly match `GOOGLE_CLOUD_PROJECT`.
- A billing budget and alert should be configured before creating AlloyDB.

```bash
gcloud auth login
gcloud auth application-default login
cp .env.example .env
# Edit GOOGLE_CLOUD_PROJECT in .env, then activate the same project:
gcloud config set project YOUR_PROJECT_ID
```

`.env` contains identifiers and non-secret settings only. Deployment requires an
explicit project ID and stops when the active project differs or billing is disabled.

## Local validation

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

ruff check .
mypy main.py productivity_intelligence setup/bigquery_setup.py setup/migrate.py
pytest
pip-audit -r requirements.txt
```

Docker validation:

```bash
docker build -t productivity-intelligence:test .
docker build -f Dockerfile.toolbox -t productivity-toolbox:test .
docker build -f Dockerfile.migrate -t productivity-migrate:test .
```

For local agent development, start Toolbox first and then run `adk web .`.
Private AlloyDB requires a reachable VPC path; local Toolbox is not expected to
reach a private instance from an ordinary workstation.

## Deployment

The deployment workflow is idempotent, creates a project-scoped ₹5,000 monthly
budget with 50%, 90%, and 100% thresholds, and supports individual phases.
Budget alerts do not cap spending. The cost-conscious default uses a single-node
`ZONAL` AlloyDB instance and limits each Cloud Run service to three instances.
Set `ALLOYDB_AVAILABILITY_TYPE=REGIONAL` only when production high availability
is required and the additional always-on database cost is acceptable.

```bash
./setup/deploy.sh preflight
./setup/deploy.sh provision
./setup/deploy.sh build
./setup/deploy.sh migrate
./setup/deploy.sh deploy
./setup/deploy.sh verify
./setup/deploy.sh promote
```

Run the complete workflow with:

```bash
./setup/deploy.sh full
```

To insert shared synthetic demonstration records during migration:

```bash
SEED_DEMO=true ./setup/deploy.sh full
```

The full workflow:

1. Verifies project access, billing, active project, configuration, and tools.
2. Enables required APIs and creates least-privilege service identities.
3. Creates Secret Manager credentials, a custom VPC/subnet, private-services
   peering, Artifact Registry, and AlloyDB.
4. Builds immutable assistant, Toolbox, and migration images.
5. Runs the schema migration and embedding smoke test as a Cloud Run Job.
6. Deploys IAM-protected Toolbox with Direct VPC egress.
7. Creates an encrypted AlloyDB federation connection and live BigQuery views.
8. Deploys an assistant candidate revision with no traffic.
9. Verifies Toolbox authentication, hosted liveness, and `/readyz`.
10. Promotes the verified candidate to 100% traffic.
11. Creates the uptime check, alert policies, and categorized log metrics.

For a destructive synthetic-only deployment smoke test that cleans up after
itself, run `setup/smoke_test.py` with the deployed Toolbox URL and assistant
service account.

Rollback requires an explicit prior revision:

```bash
./setup/deploy.sh rollback productivity-intelligence-00001-abc
```

## Runtime modes and endpoints

- `APP_MODE=full`: requires task, notes, calendar, and analytics agents.
- `APP_MODE=prototype`: loads only analytics.
- `MODEL` controls every agent model and defaults to `gemini-2.5-flash`.
- `GOOGLE_CLOUD_LOCATION` controls only Vertex AI inference and defaults to
  `global`; deployment resources remain in `REGION=us-central1`. The global
  endpoint spreads pay-as-you-go Gemini traffic across available capacity.
- Every agent retries transient Vertex AI 429 and 5xx responses up to five
  attempts with capped exponential backoff and jitter.

Operational endpoints:

- `/healthz`: process liveness; does not reveal dependency or credential errors.
- `/readyz`: returns expected, loaded, and missing agent names; responds with 503
  until every agent required by the selected mode is available.

Cloud Run's Google Front End reserves the exact public `/healthz` path and
returns 404 before it reaches the container. The verifier and uptime check use
ADK's equivalent hosted `/health` route; `/healthz` remains available inside the
container and on platforms that do not reserve it.

`setup/monitoring.sh` idempotently configures public liveness, Cloud Run 5xx and
p95 latency alerts, an AlloyDB connection high-water alert, and categorized log
metrics for startup, Toolbox authorization, MCP, and BigQuery failures.

See `SECURITY.md` for the narrow Starlette advisory exceptions imposed by the
ADK 1.36.1/FastAPI dependency constraint.

Only `productivity_intelligence` is packaged in the deployed ADK agents directory,
and its root agent is `productivity_orchestrator`.

## Data and analytics

AlloyDB stores typed task, note, and event records. Task status changes maintain
`updated_at` and `completed_at`, allowing completion analytics to reflect actual
operations. Notes use `google_ml.embedding('text-embedding-005', ...)` and exact
cosine search for the small demo dataset.

Semantic retrieval uses exact cosine search, which keeps the small shared demo
database simple and avoids an unused approximate-index dependency.

BigQuery views `productivity_analytics.task_summary` and
`productivity_analytics.daily_activity` use `EXTERNAL_QUERY` through the
`productivity_alloydb` connection. The analytics agent receives only metadata
and read-only SQL MCP tools; there is no recurring seed or duplicate ingestion.

## Security notes

- Toolbox is never deployed with unauthenticated invocation.
- The assistant supplies a refreshable Google-signed ID token to Toolbox.
- Hosted BigQuery MCP access tokens refresh through ADC and the runtime service
  identity has MCP Tool User plus read-only BigQuery permissions.
- Secret Manager versions are resolved numerically at deployment.
- Runtime identities do not receive Cloud Build, Artifact Registry admin, or
  broad Storage Admin permissions.
- Delete requests require explicit conversational confirmation.
- This demo has a shared synthetic datastore and does not provide tenant-level
  isolation.

## Cleanup and cost control

AlloyDB and Cloud Run can incur charges. Configure a project budget and remove
the demo when judging is complete:

```bash
./cleanup/cleanup_all.sh
```

The cleanup script prints every target and requires typing the exact project ID.
It removes the two services, migration job, dataset/connection, AlloyDB cluster,
images, secrets, runtime service accounts, monitoring policies, uptime check,
log metrics, project budget, peering, subnet, and VPC. Cloud resource deletion
is not recoverable.
