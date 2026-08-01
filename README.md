# Productivity Intelligence Platform

> Cloud resources are suspended by default. Development phases 0–4 and the
> separately billing-gated Phase 5 workflow are documented in
> [docs/IMPLEMENTATION_PHASES.md](docs/IMPLEMENTATION_PHASES.md).

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
   +-- analytics agent -> deterministic, parameterized BigQuery tool
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
python -m setup.phase3_validate
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

Phase 5 deployment requires Google Cloud Identity Platform. Create the first user and put
that user's Identity Platform UID in `BOOTSTRAP_IDP_SUBJECT` before
provisioning. Production must use `AUTH_MODE=identity_platform`;
`AUTH_MODE=disabled` is restricted to local/demo development and is rejected
for `ENVIRONMENT=production`.

Clients send `Authorization: Bearer <Identity Platform ID token>`. The assistant
verifies the token and resolves an active AlloyDB membership before application
routes run. The database role is authoritative; stale token role claims cannot
retain access after demotion or revocation. `/healthz` and `/readyz` remain
public and do not expose identity or credential details.

Tenant owners and administrators use the authenticated membership contract at
`/api/tenant/members`. Tenant and actor IDs always come from the verified server
context. Revocation is soft, requires `confirm=true`, and cannot remove the last
owner. These administration tools are not exposed to an AI agent.

Set `IDENTITY_BEFORE_CREATE_URL` to a deployed Identity Platform `beforeCreate`
blocking function before running `phase5.sh identity` with controlled
registration enabled. The identity setup also enforces the configured password
length and complexity policy. An empty hook URL is reported as not enforced and
cloud application fails closed; the offline plan never claims signup is blocked.

Run phases independently:

```bash
./setup/phase5.sh plan
./setup/phase5.sh identity
./setup/phase5.sh provision
./setup/phase5.sh build
./setup/phase5.sh migrate
./setup/phase5.sh deploy
./setup/phase5.sh verify
./setup/phase5.sh promote
./setup/deploy.sh cost-status
```

Delivery/resilience plans are safe offline. Their live counterparts remain
billing-gated and additionally enforce bounded query cost or action-specific DR
confirmation:

```bash
./setup/phase5.sh monitoring-plan
./setup/phase5.sh dr-plan
# Only during an approved Phase 5 window:
./setup/phase5.sh load
./setup/phase5.sh monitoring-validate
./setup/phase5.sh dr-ha
./setup/phase5.sh dr-pitr
./setup/phase5.sh dr-cleanup
```

Run the load contract once with `LOAD_TEST_FIXTURE_EVENTS=1000000` and again
with `10000000`. HA and PITR are separate evidence records; PITR always restores
to the configured `-dr-restore` cluster and never overwrites the source.

Or run the complete workflow:

```bash
./setup/phase5.sh full
```

Set `SEED_DEMO=true` in `.env` for idempotent shared synthetic records. Shell
overrides are intentionally unsupported because `.env` is the SOT.

Federated analytics is bounded by `ANALYTICS_MAX_RANGE_DAYS`,
`ANALYTICS_QUERY_TIMEOUT_SECONDS`, and `ANALYTICS_MAX_BYTES_BILLED`. When
`ENABLE_ALLOYDB_READ_POOL=true`, `ANALYTICS_ALLOYDB_INSTANCE` must name the
configured read pool and lifecycle commands manage both instances. VPC Service
Controls remains opt-in and defaults to `VPC_SC_MODE=dry-run`; enforced mode
also requires `VPC_SC_ENFORCEMENT_ACK=I_ACKNOWLEDGE_VPC_SC_LOCKOUT_RISK`.

The full workflow:

1. Validates the complete configuration contract, project access, and billing.
2. Enables APIs and creates least-privilege service identities.
3. Synchronizes `.env` credentials to Secret Manager.
4. Creates private networking, Artifact Registry, and profile-sized AlloyDB.
5. Applies image cleanup policies and builds only missing full-Git-SHA images.
6. Runs the schema migration and embedding smoke test through a Cloud Run Job.
7. Deploys IAM-protected Toolbox with Direct VPC egress.
8. Creates the encrypted AlloyDB federation connection, rollback-compatible
   views, and the bounded `get_productivity_trends_v2` procedure.
9. Deploys an assistant candidate with no production traffic.
10. Optionally deploys IAM-protected lifecycle jobs and Cloud Scheduler triggers.
11. Verifies IAM, liveness, mode-specific readiness, and a synthetic end-to-end
    CRUD, semantic-search, calendar, analytics, and final-response smoke suite.
12. Promotes the candidate and applies configured monitoring and log exclusions.

Rollback requires an explicit prior revision:

```bash
./setup/phase5.sh rollback productivity-intelligence-00001-abc
```

## Suspend and resume

AlloyDB is the primary idle-cost driver. Suspend the complete request-driven
runtime whenever a demo is not in use:

```bash
./setup/deploy.sh suspend
./setup/deploy.sh cost-status
```

Suspension removes public assistant invocation, pauses lifecycle schedulers,
removes the hosted uptime probe, enforces zero minimum Cloud Run instances, and
stops AlloyDB instance compute. The cluster, backups, container images, logs,
secrets, and BigQuery metadata remain retained and may incur storage charges;
use complete cleanup when a literal zero-resource project is required.

Resume restores the configured scaling, public invocation, schedulers, monitoring,
and AlloyDB before testing or judging:

```bash
./setup/phase5.sh deploy
./setup/phase5.sh verify
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
./setup/phase5.sh deploy
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
  "tomorrow", "Friday", and "in two weeks", preserves task times as exact
  timezone-aware deadlines, and controls analytics day boundaries.
- `AGENT_CONTEXT_MAX_EVENTS` bounds specialist context. Compaction keeps the
  latest real user turn and relevant tool exchange while removing duplicated ADK
  transfer narration.
- `DEFAULT_PAGE_SIZE` caps database list results before they enter the model
  context.
- Demo defaults disable thinking for routing and CRUD while retaining a small
  analytics budget.
- Agents retry transient Vertex AI 429 and 5xx responses with bounded backoff.
- A shared presentation contract requires a final user-visible response after
  every tool call and rejects exposed ADK event, trace, and function-call metadata.
- A deterministic pre-tool guard blocks task, note, and event deletion until the
  current conversation confirms the exact IDs; prompt compliance alone is not
  treated as an authorization boundary.
- Multi-record updates and deletes use atomic bulk tools instead of repeated
  model/tool round trips.
- Responses use consistent Markdown headings and tables across every specialist.
- `/healthz` reports process liveness without dependency details.
- `/readyz` reports expected, loaded, and missing agents and returns 503 until
  required capabilities are available.
- Structured model-usage telemetry records only agent names and token counts; it
  never logs prompt or response bodies.

Cloud Run reserves the public `/healthz` path. Hosted verification uses ADK's
equivalent `/health` route; `/healthz` remains available inside the container.

## Agent evaluation

`tests/eval_cases.json` contains generic task, note, calendar, and analytics
scenarios plus regressions derived from a 44-event production session. It covers
routing, expected and forbidden tool use, combined date/time resolution,
ambiguous time and reporting-period clarification, note-content fidelity,
response structure, and confirmation before destructive operations.

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

AlloyDB stores typed tasks, notes, and events. Tasks preserve both a typed due
date and an optional exact timezone-aware deadline. Task status changes maintain
`updated_at` and `completed_at`. Notes use the configured `EMBEDDING_MODEL` and
`EMBEDDING_DIMENSIONS` through `google_ml.embedding` and exact cosine search.
An append-only activity ledger records only entity IDs, event types, priority,
synthetic-test markers, and timestamps—never titles, descriptions, tags, or note
content. This preserves aggregate analytics after operational records are deleted.
Synthetic deployment checks are excluded from user analytics.

BigQuery dataset, connection, and procedure names come from `.env`. Unscoped
`task_summary` and `daily_activity` views are removed during setup. Runtime
analytics calls the versioned, tenant-scoped `get_productivity_trends_v2`
procedure. It validates the requested range, embeds canonical date and
server-injected tenant boundaries in the PostgreSQL statement, filters the
activity ledger before aggregation, and returns only bounded results through
`EXTERNAL_QUERY`. Day boundaries use
`DEFAULT_TIMEZONE`; `ANALYTICS_MAX_RANGE_DAYS` and
`ANALYTICS_QUERY_TIMEOUT_SECONDS` provide application guardrails.

The model cannot author SQL: the analytics agent exposes one domain tool with
typed date and grain parameters. Tenant and subject IDs come only from verified
request context. Toolbox bound parameters remove both fields from model-visible
tool schemas, and every SQL operation checks active membership. A dedicated
AlloyDB read pool and native BigQuery CDC remain scale-triggered production
upgrades rather than default demo costs. See the architecture ADRs in `docs`.

## Security and operations

- Toolbox never allows unauthenticated invocation.
- The assistant supplies refreshable Google-signed ID tokens to Toolbox.
- BigQuery client credentials refresh through Application Default Credentials.
- Secret values originate in the local SOT and are synchronized to Secret Manager;
  deployments resolve numeric versions.
- Runtime identities have no Cloud Build or Artifact Registry administration.
- Delete requests require explicit conversational confirmation.
- Delete confirmation is revalidated immediately before tool execution against
  recent real user messages and the exact requested IDs.
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
