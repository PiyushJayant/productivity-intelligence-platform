# Security policy

## Temporary dependency exception

The runtime dependency scan currently reports `PYSEC-2026-161`,
`PYSEC-2026-249`, `PYSEC-2026-248`, `PYSEC-2026-2281`, and
`PYSEC-2026-2280` against Starlette 0.52.1. Their fixed releases require
Starlette 1.x, while the required Google ADK 1.36.1 release constrains FastAPI
to `<1`, and FastAPI in turn constrains Starlette to `<0.53`.

The CI exceptions are limited to those five IDs. They must be removed as soon
as an ADK/FastAPI combination compatible with fixed Starlette releases is
available. Compensating controls for this public synthetic-data demo are:

- Cloud Run's Google Front End validates the service host before Starlette.
- No application authorization decision is based on `request.url`, host, or
  path reconstruction.
- Toolbox authorization occurs at Cloud Run IAM before its application server.
- Database credentials and administrative interfaces are not exposed publicly.

Re-run `pip-audit -r requirements.txt` without ignores during every dependency
upgrade review.

## Local configuration secret boundary

The git-ignored `.env` is intentionally the single deployment source of truth and
contains database password values. Treat it as a secret:

- Create it with `python setup/init_env.py --project PROJECT_ID`.
- Never commit, upload, print, attach, or paste it into logs or support requests.
- Store workstation backups only in an approved encrypted secret store.
- Use independent values for administrator, application, and analytics users.
- Rotate a password by editing only `.env` and rerunning provisioning and migration;
  provisioning adds a Secret Manager version and Cloud Run pins the resolved number.
- Delete `.env` securely when the local deployment authority is retired.

Cloud Run never receives these values as ordinary environment variables. Toolbox
and migration revisions refer to Secret Manager numeric versions.

## Lifecycle automation boundary

Optional scheduled lifecycle automation uses separate scheduler and lifecycle
identities. The scheduler can invoke only the lifecycle Cloud Run Jobs. The
lifecycle identity receives a project custom role containing only
`alloydb.instances.get` and `alloydb.instances.update`; it does not receive the
predefined AlloyDB Administrator role. The job implementation only changes the
configured instance activation policy and never deletes database resources.
