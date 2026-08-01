# Release readiness

## Phase 0 baseline

Status: validated locally; cloud validation intentionally deferred to Phase 5.

The Phase 0 baseline establishes a reproducible repository and image boundary.
It does not assert that AlloyDB, Identity Platform, BigQuery federation, CMEK,
VPC Service Controls, or Datastream have passed live integration testing.

### Completed offline checks

- Ruff linting
- mypy type checking across the application and deployment Python utilities
- pytest unit and repository-contract tests with coverage
- deterministic agent evaluation-manifest validation
- YAML parsing
- ShellCheck for all setup and cleanup scripts
- runtime dependency vulnerability audit with the documented temporary
  Starlette exceptions
- assistant, Toolbox, and migration Docker image builds
- migration-image content inspection
- assistant-image application-boundary inspection

### Release boundaries

- `.env` remains git-ignored and is the operator configuration SOT.
- `.env.example` contains placeholders only.
- Billable execution requires `setup/phase5.sh` and explicit acknowledgement.
- `suspend` and `cost-status` remain available without enabling the billable
  phase.
- Cloud integration results must be added here after an approved Phase 5 run.

## Phase 1 identity and tenant ownership

Status: implemented and validated locally; cloud mutation intentionally deferred
to Phase 5.

- Protected requests validate Identity Platform JWTs and then authorize against
  live, active AlloyDB membership; database roles override stale token claims.
- Versioned migration `0003_tenant_membership_lifecycle.sql` implements
  revocation, role administration, disabled-subject checks, and final-owner
  invariants.
- Tenant membership APIs never accept a tenant identifier from the client and
  require explicit confirmation for revocation.
- Private identity administration Toolbox tools are excluded from all agent
  toolsets.
- Password-policy and controlled-registration configuration is implemented but
  cannot be claimed active until the Phase 5 Identity Platform call succeeds.

### Deferred integration checks

- Identity Platform configuration and token lifecycle
- AlloyDB migration idempotency and proprietary extension smoke tests
- IAM-protected Toolbox invocation
- Federated BigQuery stored-procedure validation
- Candidate revision, authenticated end-to-end smoke test, and promotion
- Privacy retention and erasure job execution
- Read-pool load benchmark and DR/PITR evidence
- Native BigQuery/Datastream shadow reconciliation

## Phase 2 federation and security guardrails

Status: implemented and validated locally; cloud validation remains Phase 5.

- Federated SQL applies typed date bounds and active tenant membership before
  aggregation inside AlloyDB.
- Migration `0004_federation_guardrails.sql` adds analytics query-path indexes
  and enforces read-only and application-name defaults on the analytics
  principal. The migration runner reconciles statement and idle timeouts from
  `.env` on every run so configuration changes do not depend on replaying an
  immutable migration.
- BigQuery jobs use maximum-bytes-billed, timeouts, labels, bounded output, and
  retries only for transient API failures. Dependency exception details are not
  written to application logs or returned to users.
- Read-pool routing is configuration-validated and both database instances are
  handled by suspend/resume and scheduled lifecycle automation.
- VPC-SC uses dry-run by default. Enforced mode requires an independent explicit
  acknowledgement because a bad perimeter can lock out deployment and runtime
  identities.
- VPC-SC protects supported Google API boundaries; AlloyDB data-plane isolation
  still depends on private IP, service identity, and database privileges.

## Phase 3 delivery resilience and evidence

Status: implemented for offline validation; authenticated cloud measurements
remain intentionally deferred to Phase 5.

- Database migrations are serialized, checksummed, atomic with their history
  record, reject unknown future history, and emit a versioned evidence manifest.
- CI builds a retained Phase 3 artifact covering migration hashes, load SLOs,
  DR safety boundaries, observability controls, and billable gates.
- Analytics load tests are bounded to 20 workers and 200 samples, suppress
  provider error internals, and fail when p95, p99, or error-rate budgets fail.
- HA failover and PITR are distinct drills. PITR can only create an explicitly
  suffixed out-of-place cluster; cleanup is separately acknowledged.
- Monitoring targets `/healthz`, Cloud Run latency/5xx, AlloyDB connections and
  read-pool CPU, plus startup, authorization, MCP, and BigQuery log metrics.

### Deferred Phase 5 evidence

- Migration rehearsal against AlloyDB extensions, including a second no-op run
- Load results at approved 1M and 10M ledger-event fixtures
- Measured HA RTO and application recovery verification
- Isolated PITR marker verification, measured RTO/RPO, and restore cleanup
- Exported Cloud Monitoring inventory matched against the offline contract
