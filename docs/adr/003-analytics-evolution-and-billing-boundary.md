# ADR 003: Analytics evolution and billing boundary

Status: Accepted

## Decision

Keep bounded live federation as the default analytics backend. Isolate it with a
read pool when deployed. Move to Datastream and native partitioned BigQuery only
after measured hard triggers are sustained. Preserve one Python tool contract
across both backends.

Every cloud mutation or authenticated cloud validation is placed behind Phase 5
and explicit billing acknowledgement. Recommendations never trigger automatic
infrastructure changes.

## Consequences

The demonstration remains inexpensive and operationally simple. Production
operators gain deterministic pushdown, tenant isolation, immutable migration
history, privacy lifecycle controls, and a tested native-scale exit path.
Running two engines still adds schema, security, DR, and cost-management
responsibilities; the gated change process makes that burden explicit.
