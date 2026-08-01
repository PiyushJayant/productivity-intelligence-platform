# ADR-002: Identity Platform and server-owned tenant context

## Status

Accepted and implemented locally on 2026-07-25.

## Context

Client-provided tenant identifiers and model-authored tool arguments are not
authorization controls. Every operational and analytical access path needs one
verified identity source and a database-enforced ownership boundary.

## Decision

Use Google Cloud Identity Platform ID tokens. The assistant verifies token
signature, audience, issuer, timestamps, optional Identity Platform tenant,
application tenant claim, and subject at the HTTP boundary. A stable internal
subject UUID is derived from issuer and external subject.

The JWT role claim is bootstrap metadata, not an authorization decision. Every
protected request resolves the active membership from AlloyDB and replaces any
token role with that authoritative role. Membership dependency failure denies
the request with a retryable service-unavailable response.

The verified identity is stored in a request-local context. MCP Toolbox binds
`tenant_id` and `subject_id` from that context at invocation time and removes
them from model-visible schemas. AlloyDB stores tenants, subjects, and
memberships; every application row and activity fact is tenant scoped.
Database constraints, active-membership checks, and composite indexes enforce
the boundary even when agent routing is wrong.

BigQuery analytics accepts a tenant parameter supplied only by the backend. The
unparameterized compatibility views are removed because they cannot provide
request-level tenant isolation.

## Consequences

- A valid JWT alone does not grant data access; its derived subject needs an
  active database membership for the asserted application tenant.
- Revocation is soft and immediate at the request boundary; the last owner
  cannot be demoted or revoked.
- The first owner must be explicitly provisioned with
  `BOOTSTRAP_IDP_SUBJECT`.
- `/healthz` and `/readyz` remain public; application routes require a bearer
  token when identity mode is enabled.
- Local demos may use `AUTH_MODE=disabled`, but production validation rejects
  it.
- End-user chat smoke testing requires a short-lived Identity Platform token;
  infrastructure service identity is not accepted as an end-user substitute.
