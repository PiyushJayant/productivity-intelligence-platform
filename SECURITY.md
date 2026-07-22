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
