# Enterprise implementation phases

This repository contains the implementation path and offline scaffolding for
Phases 0–4. A phase is not considered production-validated until its listed
Phase 5 integration checks pass. Phase 5 is the only execution boundary for
operations that require billing.

## Phase 0 release baseline

- Reconcile and commit the complete local implementation.
- Run lint, type, unit, evaluation, dependency, secret, YAML, shell, and image
  build checks.
- Confirm the assistant image contains one ADK application and the migration
  image contains every ordered migration.
- Record validation evidence in `docs/RELEASE_READINESS.md`.

## Phase 1 — Identity and tenant ownership

- Identity Platform JWTs are verified for issuer, audience, signature, expiry,
  tenant claim, and subject. Token roles are not trusted for authorization.
- The server derives internal tenant/subject UUIDs; model-visible tools cannot
  provide them.
- AlloyDB membership is checked on every protected request. Revoked, disabled,
  mismatched, or unavailable memberships fail closed before agent execution.
- Owner/admin membership APIs support listing, provisioning, role updates, and
  explicit-confirmation soft revocation. Database functions enforce privileged
  role boundaries and prevent removing the final owner.
- Authorization and administration SQL tools use a private Toolbox toolset that
  is never loaded into an LLM agent. Model-visible CRUD tools independently
  require active membership as defense in depth.
- `setup/identity_setup.py` configures email/password authentication, disables
  duplicate identities, enforces a password policy, validates the bootstrap
  UID, and installs tenant bootstrap claims. Controlled registration is only
  reported as active when a `beforeCreate` blocking-function URL is configured.

## Phase 2 — Federation, security, and AI guardrails

- `get_productivity_trends_v2` embeds validated date, tenant, and subject
  boundaries inside PostgreSQL SQL executed by `EXTERNAL_QUERY`.
- Analytics has a fixed two-year maximum, strict date/grain validation, safe
  errors, database and BigQuery timeouts, a maximum-bytes-billed ceiling,
  transient-only bounded retry, result-cardinality checks, job labels, and no
  model-authored SQL.
- The analytics role is database-enforced read-only, has statement and idle
  transaction timeouts, and receives query-path indexes for bounded periods and
  latest task status.
- An optional AlloyDB read pool isolates analytical cache/CPU pressure. Routing,
  manual suspension, and scheduled lifecycle automation manage the primary and
  read pool as one configured unit.
- Optional CMEK and VPC Service Controls are implemented by
  `setup/security_setup.sh`; disabled by default. VPC-SC begins in dry-run mode
  and enforcement requires a separate lockout-risk acknowledgement.

## Phase 3 — Delivery, resilience, and evidence

- `setup/migration_runner.py` provides ordered checksummed migrations, an
  advisory lock, immutable-history detection, and idempotent re-entry.
- Offline CI runs linting, types, unit tests, security scans, YAML checks,
  ShellCheck, and all container builds.
- Authenticated load and DR tooling live in `setup/load_test.py` and
  `setup/dr_drill.sh`. They require the Phase 5 gate.
- The manual cloud workflow uses an approval-protected GitHub environment and
  Workload Identity Federation, not a downloaded service-account key.

## Phase 4A — Semantic enrichment and privacy

- Migration `0002_privacy_taxonomy.sql` creates a versioned, non-identifying
  topic taxonomy and deterministic ingestion classification.
- The raw activity ledger receives HMAC subject tokens from the privileged
  privacy job.
- `rollup_and_purge_activity` preserves anonymous daily aggregates and removes
  expired raw events.
- `privacy_erasure_requests` and `erase_subject_data` provide an auditable,
  subject-scoped erasure workflow without rotating a tenant-wide key.
- Raw text and embeddings remain in AlloyDB; they are not part of the native
  warehouse contract.

## Phase 4B — CDC and native BigQuery

- `setup/datastream_setup.sh` provisions an initially stopped CDC stream.
- `setup/native_bigquery_setup.py` creates a required-partition-filter table
  clustered by tenant, event type, and topic, plus the v3 TVF.
- Runtime `ANALYTICS_BACKEND=federated|native` swaps the implementation without
  changing the model tool signature.
- `setup/evaluate_cdc_trigger.py` evaluates approved latency, CPU, CRUD, and
  concurrency thresholds. It recommends a change but never performs one.

## Phase 5 — Billing-enabled cloud execution

All cloud provisioning, builds, database migrations, deployments, authenticated
smoke tests, load tests, DR drills, Identity Platform mutations, and CDC setup
belong here. Execute only after change approval:

1. Keep the checked-in/default configuration at:
   `ENABLE_BILLABLE_PHASE=false` and `BILLING_ACK=NOT_ACKNOWLEDGED`.
2. Populate the git-ignored `.env` SOT with reviewed production values.
3. Enable billing and set the explicit acknowledgement:
   `ENABLE_BILLABLE_PHASE=true` and
   `BILLING_ACK=I_ACKNOWLEDGE_GCP_CHARGES`.
4. Use `setup/phase5.sh plan`.
5. Use the smallest approved action, or trigger the manual
   `Phase 5 - Billing-gated cloud validation` workflow.
6. Return AlloyDB activation to `NEVER` and Cloud Run minimum instances to zero
   after validation when the environment must remain suspended.

`setup/provision.sh`, `setup/deploy.sh`, native setup, security setup, and CDC
setup all reject direct execution unless the Phase 5 gate is active.

## Current suspension contract

The repository does not enable billing, start AlloyDB, deploy revisions, execute
migrations, or run authenticated cloud tests during ordinary development or CI.
The local SOT must retain `ALLOYDB_ACTIVATION_POLICY=NEVER`, service minimum
instances of zero, scheduled lifecycle disabled, and the Phase 5 gate disabled
until an operator explicitly approves a charged validation window.
