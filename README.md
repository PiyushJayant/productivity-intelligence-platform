# Productivity Intelligence Platform

A configurable Google ADK work-orchestration platform for synthetic tasks, semantic
notes, calendar events, and live productivity analytics on Google Cloud.

> This is a public demonstration application. Do not enter personal, confidential,
> regulated, or production data. The assistant is public for judging; its MCP
> Toolbox data plane is protected by Cloud Run IAM.

## Architecture

```text
Public user
   |
   v
Cloud Run: productivity-intelligence
   |-- task / notes / calendar agents
   |      |  refreshable Cloud Run ID token
   |      v
   |   Cloud Run: productivity-toolbox (IAM protected)
   |      |  Direct VPC egress
   |      v
   |   AlloyDB: tasks, notes, events, vector embeddings
   |
   +-- analytics agent -> hosted BigQuery MCP
                              |
                              v
                         BigQuery live views
                              |
                              v
                         EXTERNAL_QUERY -> AlloyDB
```

The assistant, Toolbox, migration job, lifecycle jobs, and scheduler have
separate service accounts. The
git-ignored `.env` is the single source of truth for every operator-controlled
application, infrastructure, cost, monitoring, and secret value. Provisioning
mirrors the three database passwords into Secret Manager. Cloud Run receives only
numerically pinned secret references, never plaintext password variables.

## Prerequisites

- A billing-enabled Google Cloud project.
- Permissions to administer IAM, AlloyDB, Cloud Run, networking, Secret Manager,
  BigQuery, Artifact Registry, Cloud Build, Monitoring, and billing budgets.
- `gcloud`, `bq`, `curl`, Git, Bash, and Python 3.11.
- The active gcloud project must exactly match `GOOGLE_CLOUD_PROJECT`.

Create the one local environment file:

```bash
gcloud auth login
gcloud auth application-default login
python setup/init_env.py --project YOUR_PROJECT_ID
gcloud config set project YOUR_PROJECT_ID
```

Review every value in `.env` before provisioning. `.env.example` is documentation
and a template, not a runtime source. The initializer generates independent random
passwords and applies restrictive file permissions on POSIX systems. Never commit,
upload, print, or share `.env`.

Preflight fails on missing values, placeholders, invalid profiles, unsafe scaling,
project mismatch, or disabled billing.

## Cost profiles

`COST_PROFILE` selects validated safety constraints:

- `demo`: zonal AlloyDB, zero minimum and exactly one maximum Cloud Run instance
  for both services. The default `c4a-highmem-1` database is for demos and
  development, not a production SLA.
- `lean`: requires at least two AlloyDB vCPUs and permits independently configured
  Cloud Run scaling without requiring regional availability.
- `production`: requires at least two AlloyDB vCPUs and regional availability.

The default template creates an INR 1,000 project budget with 25%, 50%, 75%, 90%, and
100% thresholds. Budgets alert but do not cap spending. Resource sizes, estimates,
limits, retention, generation budgets, and monitoring toggles remain configurable
in `.env`.

## Local validation

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

ruff check .
mypy main.py productivity_intelligence setup/bigquery_setup.py setup/migrate.py \
  setup/init_env.py setup/lifecycle.py setup/evaluate_contracts.py setup/smoke_test.py
pytest
python setup/evaluate_contracts.py
pip-audit -r requirements.txt
```

Container validation:

```bash
docker build -t productivity-intelligence:test .
docker build -f Dockerfile.toolbox -t productivity-toolbox:test .
docker build -f Dockerfile.migrate -t productivity-migrate:test .
```

For local agent development, start Toolbox and run `adk web .`. Private AlloyDB is
not normally reachable from an ordinary workstation.

## Deployment

Run phases independently:

```bash
./setup/deploy.sh preflight
./setup/deploy.sh provision
./setup/deploy.sh build
./setup/deploy.sh migrate
./setup/deploy.sh deploy
./setup/deploy.sh verify
./setup/deploy.sh promote
./setup/deploy.sh cost-status
```

Or run the complete workflow:

```bash
./setup/deploy.sh full
```

Set `SEED_DEMO=true` in `.env` for idempotent shared synthetic records. Shell
overrides are intentionally unsupported because `.env` is the SOT.

The full workflow:

1. Validates the complete configuration contract, project access, and billing.
2. Enables APIs and creates least-privilege service identities.
3. Synchronizes `.env` credentials to Secret Manager.
4. Creates private networking, Artifact Registry, and profile-sized AlloyDB.
5. Applies image cleanup policies and builds only missing full-Git-SHA images.
6. Runs the schema migration and embedding smoke test through a Cloud Run Job.
7. Deploys IAM-protected Toolbox with Direct VPC egress.
8. Creates the encrypted AlloyDB federation connection and live BigQuery views.
9. Deploys an assistant candidate with no production traffic.
10. Optionally deploys IAM-protected lifecycle jobs and Cloud Scheduler triggers.
11. Verifies IAM, liveness, mode-specific readiness, and a synthetic end-to-end
    CRUD, semantic-search, calendar, analytics, and final-response smoke suite.
12. Promotes the candidate and applies configured monitoring and log exclusions.

Rollback requires an explicit prior revision:

```bash
./setup/deploy.sh rollback productivity-intelligence-00001-abc
```

## Suspend and resume

AlloyDB is the primary idle-cost driver. Suspend instance compute whenever a demo
is not in use:

```bash
./setup/deploy.sh suspend
./setup/deploy.sh cost-status
```

The cluster retains data and backup configuration, but database-backed capabilities
are unavailable while suspended. Resume before testing or judging:

```bash
./setup/deploy.sh resume
./setup/deploy.sh verify
```

`AUTO_SUSPEND_AFTER_DEPLOY=true` verifies and promotes a full deployment before
suspending AlloyDB. Leave it `false` when the application must remain immediately
usable. Suspending a production profile requires typing the exact project ID.

Optional scheduled lifecycle automation is controlled entirely by `.env`:

```dotenv
ENABLE_SCHEDULED_LIFECYCLE=true
LIFECYCLE_RESUME_CRON="0 9 * * 1-5"
LIFECYCLE_SUSPEND_CRON="0 20 * * *"
LIFECYCLE_TIMEZONE=Asia/Kolkata
```

Apply or remove those jobs idempotently with:

```bash
./setup/deploy.sh lifecycle
```

The scheduler invokes private Cloud Run Jobs using OAuth. Those jobs can only
change the configured AlloyDB instance activation policy. Scheduled lifecycle
automation is rejected for the `production` cost profile.

## Runtime behavior

- `APP_MODE=full` requires task, notes, calendar, and analytics agents.
- `APP_MODE=prototype` requires only analytics.
- `MODEL` controls every agent model.
- Router, specialist, and analytics output-token and thinking budgets are
  independently configurable.
- `DEFAULT_TIMEZONE` controls deterministic resolution of phrases such as
  "tomorrow", "Friday", and "in two weeks".
- `DEFAULT_PAGE_SIZE` caps database list results before they enter the model
  context.
- Demo defaults disable thinking for routing and CRUD while retaining a small
  analytics budget.
- Agents retry transient Vertex AI 429 and 5xx responses with bounded backoff.
- A shared presentation contract requires a final user-visible response after
  every tool call and rejects exposed ADK event, trace, and function-call metadata.
- Responses use consistent Markdown headings and tables across every specialist.
- `/healthz` reports process liveness without dependency details.
- `/readyz` reports expected, loaded, and missing agents and returns 503 until
  required capabilities are available.

Cloud Run reserves the public `/healthz` path. Hosted verification uses ADK's
equivalent `/health` route; `/healthz` remains available inside the container.

## Agent evaluation

`tests/eval_cases.json` contains generic task, note, calendar, and analytics
scenarios. It covers routing, expected tool use, relative dates, response
structure, and confirmation before destructive operations.

The deterministic evaluation gate validates the manifest without calling a
model:

```bash
python setup/evaluate_contracts.py
```

Captured live results can be checked before promotion:

```bash
python setup/evaluate_contracts.py --results path/to/captured-results.json
```

Deployment smoke testing also verifies that semantic note search produces both
the expected tool call and a grounded final response without internal metadata.

## Data and analytics

AlloyDB stores typed tasks, notes, and events. Task status changes maintain
`updated_at` and `completed_at`. Notes use the configured `EMBEDDING_MODEL` and
`EMBEDDING_DIMENSIONS` through `google_ml.embedding` and exact cosine search.

BigQuery dataset and connection names come from `.env`. The `task_summary` and
`daily_activity` views aggregate inside AlloyDB before returning small result sets
through `EXTERNAL_QUERY`. Analytics tools are metadata and read-only SQL only.

## Security and operations

- Toolbox never allows unauthenticated invocation.
- The assistant supplies refreshable Google-signed ID tokens to Toolbox.
- Hosted BigQuery MCP access tokens refresh through ADC.
- Secret values originate in the local SOT and are synchronized to Secret Manager;
  deployments resolve numeric versions.
- Runtime identities have no Cloud Build or Artifact Registry administration.
- Delete requests require explicit conversational confirmation.
- Successful health requests can be excluded from stored logs.
- Request logs are structured JSON with a configurable correlation header,
  method, path, status, and latency. Bodies, query strings, credentials, and
  authentication headers are not logged by application middleware.
- Uptime checks and categorized log metrics are independently configurable.
- Artifact Registry keeps the configured number of recent images and deletes
  versions older than the configured retention period.

See `SECURITY.md` for dependency advisory exceptions.

## Cleanup

Use `suspend` for a reusable environment. For complete irreversible removal:

```bash
./cleanup/cleanup_all.sh
```

Cleanup prints every target and requires the exact project ID. It removes services,
migration and lifecycle jobs, scheduler triggers, analytics dataset and connection,
AlloyDB, images, secrets, runtime identities, monitoring, budget,
private-service peering, subnet, and VPC.
