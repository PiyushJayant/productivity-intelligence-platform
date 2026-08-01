# ADR-001: Bounded federated analytics

## Status

Accepted

## Context

The initial BigQuery views execute aggregate PostgreSQL queries over the complete
AlloyDB `activity_events` ledger and apply the user's reporting range afterward.
That work grows with retained history and can eventually affect the operational
database. BigQuery optimizer pushdown is not a reliable contract once an
external query contains aggregation or joins.

At the time of this decision, the application had no authenticated tenant or
user identity. ADR-002 now supplies that boundary.

## Decision

During live federation, the application calls a versioned BigQuery stored
procedure named by `BIGQUERY_ANALYTICS_PROCEDURE`.

The procedure:

- accepts typed inclusive start and end dates plus an allowlisted grain;
- rejects reversed, null, unsupported, and overlong ranges;
- converts the inclusive end date to an exclusive upper boundary;
- constructs PostgreSQL only from typed dates and internally selected templates;
- renders the complete remote query as a GoogleSQL literal with `FORMAT('%T')`;
- applies time boundaries inside AlloyDB before aggregation;
- returns a fixed v2 result contract.

ADR-002 removes the unscoped compatibility views and adds a trusted tenant
parameter to the v2 routine. The application tool keeps its model-visible
signature; tenant identity comes from verified backend request context.

## Options considered

| Option | Advantages | Disadvantages |
|---|---|---|
| Keep aggregate views | Simple and already deployed | Full-history source work |
| Raw external view plus TVF | Composable and read-only | Depends on optimizer pushdown |
| Bounded stored procedure | Deterministic remote bounds and stable contract | Dynamic SQL and routine lifecycle |
| Native BigQuery with CDC | Strong isolation and scalable analytics | Additional pipeline and storage cost |

## Consequences

### Positive

- Requested dates bound AlloyDB work before aggregation.
- The LLM cannot provide SQL, connection names, identifiers, or query fragments.
- Range and timeout settings remain in the `.env` source of truth.
- BigQuery jobs have a configured maximum-bytes-billed ceiling and low-cardinality
  attribution labels.
- The database principal independently enforces read-only transactions and
  statement/idle timeouts.
- The public application tool remains stable for a future CDC migration.

### Negative

- The procedure uses controlled dynamic SQL because nested PostgreSQL parameters
  cannot be bound through BigQuery query parameters.
- Federation still consumes AlloyDB resources.
- Analytics remains unavailable when AlloyDB is stopped or recovering.
- Federation authorization relies on the trusted assistant identity and
  server-injected tenant routine parameter.

### Mitigations

- Use typed dates, a fixed grain allowlist, fixed SQL templates, and `%T` literal
  rendering.
- Enforce maximum range, result cardinality, BigQuery bytes, BigQuery job time,
  and AlloyDB statement time independently.
- Retry only transient service, quota, gateway, and deadline failures; permanent
  query errors fail immediately behind a safe user-facing message.
- Monitor query latency, error rate, and AlloyDB load.
- Route the connection to a read pool before analytical load affects OLTP, and
  manage that pool in every suspend/resume path so cost state cannot drift.

## Revisit triggers

Adopt Datastream CDC into native, date-partitioned BigQuery tables and replace
the procedure with a TVF when two performance thresholds are breached for seven
days, or immediately when analytics must remain available independently of
AlloyDB, requires cross-source joins, or requires database-enforced tenant row
security.
