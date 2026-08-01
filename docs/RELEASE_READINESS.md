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
