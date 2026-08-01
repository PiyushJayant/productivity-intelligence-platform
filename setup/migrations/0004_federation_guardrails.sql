-- Phase 2 federation isolation, bounded execution, and query-path indexes.
CREATE INDEX IF NOT EXISTS activity_events_tenant_period_type_idx
  ON activity_events(tenant_id, occurred_at, event_type)
  INCLUDE (entity_type, entity_id, priority)
  WHERE NOT is_synthetic;

CREATE INDEX IF NOT EXISTS activity_events_tenant_entity_latest_idx
  ON activity_events(
    tenant_id, entity_type, entity_id, occurred_at DESC, id DESC
  )
  INCLUDE (event_type)
  WHERE NOT is_synthetic;

ALTER ROLE productivity_analytics SET default_transaction_read_only = on;
ALTER ROLE productivity_analytics SET application_name = 'productivity-federation';
REVOKE CREATE ON SCHEMA public FROM productivity_analytics;
