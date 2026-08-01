-- Privacy-safe CDC source contract. Datastream is permitted to replicate only
-- analytics_export_events, which contains no operational tenant/subject UUIDs
-- and no user-authored text or embeddings.

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS analytics_tenant_token CHAR(64);
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS analytics_subject_token CHAR(64);
ALTER TABLE notes ADD COLUMN IF NOT EXISTS analytics_tenant_token CHAR(64);
ALTER TABLE notes ADD COLUMN IF NOT EXISTS analytics_subject_token CHAR(64);
ALTER TABLE events ADD COLUMN IF NOT EXISTS analytics_tenant_token CHAR(64);
ALTER TABLE events ADD COLUMN IF NOT EXISTS analytics_subject_token CHAR(64);
ALTER TABLE activity_events ADD COLUMN IF NOT EXISTS tenant_token CHAR(64);

DO $$
DECLARE table_name TEXT;
DECLARE constraint_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['tasks', 'notes', 'events'] LOOP
    constraint_name := table_name || '_analytics_tokens_valid';
    IF NOT EXISTS (
      SELECT 1 FROM pg_constraint WHERE conname = constraint_name
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I ADD CONSTRAINT %I CHECK (' ||
        '(analytics_tenant_token IS NULL AND analytics_subject_token IS NULL) OR (' ||
        'analytics_tenant_token ~ ''^[0-9a-f]{64}$'' AND ' ||
        'analytics_subject_token ~ ''^[0-9a-f]{64}$''))',
        table_name, constraint_name
      );
    END IF;
  END LOOP;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'activity_analytics_tokens_valid'
  ) THEN
    ALTER TABLE activity_events ADD CONSTRAINT activity_analytics_tokens_valid
      CHECK (
        (tenant_token IS NULL AND subject_token IS NULL) OR
        (tenant_token ~ '^[0-9a-f]{64}$' AND subject_token ~ '^[0-9a-f]{64}$')
      );
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS analytics_export_events (
  event_id BIGINT PRIMARY KEY REFERENCES activity_events(id) ON DELETE CASCADE,
  tenant_token CHAR(64) NOT NULL,
  subject_token CHAR(64) NOT NULL,
  entity_type TEXT NOT NULL,
  event_type TEXT NOT NULL,
  priority TEXT,
  topic_id TEXT NOT NULL REFERENCES productivity_topics(topic_id),
  is_synthetic BOOLEAN NOT NULL DEFAULT false,
  occurred_at TIMESTAMPTZ NOT NULL,
  exported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT analytics_export_tenant_token_valid
    CHECK (tenant_token ~ '^[0-9a-f]{64}$'),
  CONSTRAINT analytics_export_subject_token_valid
    CHECK (subject_token ~ '^[0-9a-f]{64}$')
);
CREATE INDEX IF NOT EXISTS analytics_export_scope_period_idx
  ON analytics_export_events(tenant_token, subject_token, occurred_at, event_type)
  WHERE NOT is_synthetic;

CREATE OR REPLACE FUNCTION sync_activity_event_to_export()
RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NEW.tenant_token IS NULL OR NEW.subject_token IS NULL THEN
    RETURN NEW;
  END IF;
  INSERT INTO analytics_export_events(
    event_id, tenant_token, subject_token, entity_type, event_type, priority,
    topic_id, is_synthetic, occurred_at, exported_at
  ) VALUES (
    NEW.id, NEW.tenant_token, NEW.subject_token, NEW.entity_type,
    NEW.event_type, NEW.priority, NEW.topic_id, NEW.is_synthetic,
    NEW.occurred_at, now()
  )
  ON CONFLICT (event_id) DO UPDATE SET
    tenant_token = EXCLUDED.tenant_token,
    subject_token = EXCLUDED.subject_token,
    entity_type = EXCLUDED.entity_type,
    event_type = EXCLUDED.event_type,
    priority = EXCLUDED.priority,
    topic_id = EXCLUDED.topic_id,
    is_synthetic = EXCLUDED.is_synthetic,
    occurred_at = EXCLUDED.occurred_at,
    exported_at = now();
  RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS activity_event_export_sync ON activity_events;
CREATE TRIGGER activity_event_export_sync
AFTER INSERT OR UPDATE OF tenant_token, subject_token ON activity_events
FOR EACH ROW EXECUTE FUNCTION sync_activity_event_to_export();

CREATE OR REPLACE FUNCTION record_task_activity()
RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE status_event TEXT;
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO activity_events(
      entity_type, entity_id, event_type, priority, topic_id, is_synthetic,
      occurred_at, tenant_id, subject_id, tenant_token, subject_token
    ) VALUES (
      'task', NEW.id, 'task_created', NEW.priority, NEW.topic_id,
      NEW.title LIKE 'smoke-%', NEW.created_at, NEW.tenant_id,
      NEW.created_by_subject_id, NEW.analytics_tenant_token,
      NEW.analytics_subject_token
    ) ON CONFLICT DO NOTHING;
    RETURN NEW;
  ELSIF TG_OP = 'UPDATE' AND OLD.status IS DISTINCT FROM NEW.status THEN
    status_event := CASE NEW.status
      WHEN 'pending' THEN 'task_pending'
      WHEN 'in_progress' THEN 'task_in_progress'
      WHEN 'done' THEN 'task_completed'
    END;
    INSERT INTO activity_events(
      entity_type, entity_id, event_type, priority, topic_id, is_synthetic,
      occurred_at, tenant_id, subject_id, tenant_token, subject_token
    ) VALUES (
      'task', NEW.id, status_event, NEW.priority, NEW.topic_id,
      NEW.title LIKE 'smoke-%',
      COALESCE(NEW.completed_at, NEW.updated_at, CURRENT_TIMESTAMP),
      NEW.tenant_id, NEW.created_by_subject_id, NEW.analytics_tenant_token,
      NEW.analytics_subject_token
    ) ON CONFLICT DO NOTHING;
    RETURN NEW;
  ELSIF TG_OP = 'DELETE' THEN
    INSERT INTO activity_events(
      entity_type, entity_id, event_type, priority, topic_id, is_synthetic,
      occurred_at, tenant_id, subject_id, tenant_token, subject_token
    ) VALUES (
      'task', OLD.id, 'task_deleted', OLD.priority, OLD.topic_id,
      OLD.title LIKE 'smoke-%', CURRENT_TIMESTAMP, OLD.tenant_id,
      OLD.created_by_subject_id, OLD.analytics_tenant_token,
      OLD.analytics_subject_token
    ) ON CONFLICT DO NOTHING;
    RETURN OLD;
  END IF;
  RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION record_note_activity()
RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO activity_events(
      entity_type, entity_id, event_type, topic_id, is_synthetic, occurred_at,
      tenant_id, subject_id, tenant_token, subject_token
    ) VALUES (
      'note', NEW.id, 'note_created', NEW.topic_id,
      NEW.title LIKE 'smoke-%', NEW.created_at, NEW.tenant_id,
      NEW.created_by_subject_id, NEW.analytics_tenant_token,
      NEW.analytics_subject_token
    ) ON CONFLICT DO NOTHING;
    RETURN NEW;
  END IF;
  INSERT INTO activity_events(
    entity_type, entity_id, event_type, topic_id, is_synthetic,
    tenant_id, subject_id, tenant_token, subject_token
  ) VALUES (
    'note', OLD.id, 'note_deleted', OLD.topic_id, OLD.title LIKE 'smoke-%',
    OLD.tenant_id, OLD.created_by_subject_id, OLD.analytics_tenant_token,
    OLD.analytics_subject_token
  ) ON CONFLICT DO NOTHING;
  RETURN OLD;
END
$$;

CREATE OR REPLACE FUNCTION record_calendar_activity()
RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO activity_events(
      entity_type, entity_id, event_type, topic_id, is_synthetic, occurred_at,
      tenant_id, subject_id, tenant_token, subject_token
    ) VALUES (
      'event', NEW.id, 'event_scheduled', NEW.topic_id,
      NEW.title LIKE 'smoke-%', NEW.created_at, NEW.tenant_id,
      NEW.created_by_subject_id, NEW.analytics_tenant_token,
      NEW.analytics_subject_token
    ) ON CONFLICT DO NOTHING;
    RETURN NEW;
  END IF;
  INSERT INTO activity_events(
    entity_type, entity_id, event_type, topic_id, is_synthetic,
    tenant_id, subject_id, tenant_token, subject_token
  ) VALUES (
    'event', OLD.id, 'event_deleted', OLD.topic_id, OLD.title LIKE 'smoke-%',
    OLD.tenant_id, OLD.created_by_subject_id, OLD.analytics_tenant_token,
    OLD.analytics_subject_token
  ) ON CONFLICT DO NOTHING;
  RETURN OLD;
END
$$;

CREATE OR REPLACE FUNCTION list_pending_analytics_export(p_batch_size INTEGER)
RETURNS TABLE(event_id BIGINT, tenant_id UUID, subject_id UUID)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF p_batch_size < 1 OR p_batch_size > 10000 THEN
    RAISE EXCEPTION 'batch size outside allowed range' USING ERRCODE = '22023';
  END IF;
  RETURN QUERY
  SELECT e.id, e.tenant_id, e.subject_id
  FROM activity_events e
  LEFT JOIN analytics_export_events x ON x.event_id = e.id
  WHERE e.tenant_token IS NULL OR e.subject_token IS NULL OR x.event_id IS NULL
  ORDER BY e.id
  LIMIT p_batch_size
  FOR UPDATE OF e SKIP LOCKED;
END
$$;

CREATE OR REPLACE FUNCTION apply_activity_export_tokens(p_updates JSONB)
RETURNS BIGINT
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE updated_count BIGINT;
BEGIN
  IF jsonb_typeof(p_updates) <> 'array' OR jsonb_array_length(p_updates) > 10000 THEN
    RAISE EXCEPTION 'invalid export batch' USING ERRCODE = '22023';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_to_recordset(p_updates) AS x(
      event_id BIGINT, tenant_token TEXT, subject_token TEXT
    )
    WHERE x.event_id IS NULL
      OR x.tenant_token !~ '^[0-9a-f]{64}$'
      OR x.subject_token !~ '^[0-9a-f]{64}$'
  ) THEN
    RAISE EXCEPTION 'invalid export token' USING ERRCODE = '22023';
  END IF;
  UPDATE activity_events e
  SET tenant_token = x.tenant_token, subject_token = x.subject_token
  FROM jsonb_to_recordset(p_updates) AS x(
    event_id BIGINT, tenant_token TEXT, subject_token TEXT
  )
  WHERE e.id = x.event_id;
  GET DIAGNOSTICS updated_count = ROW_COUNT;
  RETURN updated_count;
END
$$;

REVOKE ALL ON analytics_export_events FROM PUBLIC;
REVOKE ALL ON FUNCTION sync_activity_event_to_export() FROM PUBLIC;
REVOKE ALL ON FUNCTION list_pending_analytics_export(INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION apply_activity_export_tokens(JSONB) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION list_unpseudonymized_activity(INTEGER)
  FROM productivity_privacy;
REVOKE EXECUTE ON FUNCTION apply_activity_subject_tokens(JSONB)
  FROM productivity_privacy;
GRANT EXECUTE ON FUNCTION list_pending_analytics_export(INTEGER)
  TO productivity_privacy;
GRANT EXECUTE ON FUNCTION apply_activity_export_tokens(JSONB)
  TO productivity_privacy;

GRANT USAGE ON SCHEMA public TO productivity_cdc;
GRANT SELECT ON analytics_export_events TO productivity_cdc;
ALTER ROLE productivity_cdc WITH REPLICATION;
ALTER ROLE productivity_cdc SET default_transaction_read_only = on;
ALTER ROLE productivity_cdc SET statement_timeout = '60s';
ALTER ROLE productivity_cdc SET idle_in_transaction_session_timeout = '60s';
