-- Production privacy operations: ingestion classification, least privilege,
-- pseudonymization batches, and auditable tenant-scoped erasure requests.

ALTER TABLE privacy_erasure_requests
  ADD COLUMN IF NOT EXISTS requested_by_subject_id UUID;
ALTER TABLE privacy_erasure_requests
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE privacy_erasure_requests
  ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0;

UPDATE privacy_erasure_requests
SET requested_by_subject_id = subject_id
WHERE requested_by_subject_id IS NULL;
ALTER TABLE privacy_erasure_requests
  ALTER COLUMN requested_by_subject_id SET NOT NULL;

-- Preserve the oldest active request when upgrading databases that may already
-- contain duplicate pending/processing requests from the earlier schema.
WITH ranked_open_requests AS (
  SELECT id, row_number() OVER (
    PARTITION BY tenant_id, subject_id ORDER BY requested_at, id
  ) AS position
  FROM privacy_erasure_requests
  WHERE status IN ('pending', 'processing')
)
UPDATE privacy_erasure_requests AS request
SET status = 'failed', failure_code = 'superseded_during_migration',
    updated_at = now()
FROM ranked_open_requests AS ranked
WHERE request.id = ranked.id AND ranked.position > 1;

CREATE UNIQUE INDEX IF NOT EXISTS privacy_erasure_one_open_request_idx
  ON privacy_erasure_requests(tenant_id, subject_id)
  WHERE status IN ('pending', 'processing');
CREATE INDEX IF NOT EXISTS privacy_erasure_status_requested_idx
  ON privacy_erasure_requests(status, requested_at);

UPDATE tasks SET topic_id = 'uncategorized'
WHERE topic_id IS NULL OR NOT EXISTS (
  SELECT 1 FROM productivity_topics WHERE productivity_topics.topic_id = tasks.topic_id
);
UPDATE notes SET topic_id = 'uncategorized'
WHERE topic_id IS NULL OR NOT EXISTS (
  SELECT 1 FROM productivity_topics WHERE productivity_topics.topic_id = notes.topic_id
);
UPDATE events SET topic_id = 'uncategorized'
WHERE topic_id IS NULL OR NOT EXISTS (
  SELECT 1 FROM productivity_topics WHERE productivity_topics.topic_id = events.topic_id
);
UPDATE activity_events SET topic_id = 'uncategorized'
WHERE topic_id IS NULL OR NOT EXISTS (
  SELECT 1 FROM productivity_topics
  WHERE productivity_topics.topic_id = activity_events.topic_id
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'tasks_topic_fk'
  ) THEN
    ALTER TABLE tasks ADD CONSTRAINT tasks_topic_fk
      FOREIGN KEY (topic_id) REFERENCES productivity_topics(topic_id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'notes_topic_fk'
  ) THEN
    ALTER TABLE notes ADD CONSTRAINT notes_topic_fk
      FOREIGN KEY (topic_id) REFERENCES productivity_topics(topic_id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'events_topic_fk'
  ) THEN
    ALTER TABLE events ADD CONSTRAINT events_topic_fk
      FOREIGN KEY (topic_id) REFERENCES productivity_topics(topic_id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'activity_events_topic_fk'
  ) THEN
    ALTER TABLE activity_events ADD CONSTRAINT activity_events_topic_fk
      FOREIGN KEY (topic_id) REFERENCES productivity_topics(topic_id);
  END IF;
END $$;

CREATE OR REPLACE FUNCTION assign_productivity_topic()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF TG_TABLE_NAME = 'tasks' THEN
    NEW.topic_id := classify_productivity_topic(NEW.title || ' ' || NEW.description);
  ELSIF TG_TABLE_NAME = 'notes' THEN
    NEW.topic_id := classify_productivity_topic(NEW.title || ' ' || NEW.content);
  ELSIF TG_TABLE_NAME = 'events' THEN
    NEW.topic_id := classify_productivity_topic(NEW.title || ' ' || NEW.description);
  ELSE
    RAISE EXCEPTION 'unsupported classification table' USING ERRCODE = '22023';
  END IF;
  RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS tasks_assign_topic ON tasks;
CREATE TRIGGER tasks_assign_topic
BEFORE INSERT OR UPDATE OF title, description ON tasks
FOR EACH ROW EXECUTE FUNCTION assign_productivity_topic();
DROP TRIGGER IF EXISTS notes_assign_topic ON notes;
CREATE TRIGGER notes_assign_topic
BEFORE INSERT OR UPDATE OF title, content ON notes
FOR EACH ROW EXECUTE FUNCTION assign_productivity_topic();
DROP TRIGGER IF EXISTS events_assign_topic ON events;
CREATE TRIGGER events_assign_topic
BEFORE INSERT OR UPDATE OF title, description ON events
FOR EACH ROW EXECUTE FUNCTION assign_productivity_topic();

-- Replace ledger triggers so the non-identifying topic is captured at ingest.
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
      occurred_at, tenant_id, subject_id
    ) VALUES (
      'task', NEW.id, 'task_created', NEW.priority, NEW.topic_id,
      NEW.title LIKE 'smoke-%', NEW.created_at, NEW.tenant_id,
      NEW.created_by_subject_id
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
      occurred_at, tenant_id, subject_id
    ) VALUES (
      'task', NEW.id, status_event, NEW.priority, NEW.topic_id,
      NEW.title LIKE 'smoke-%',
      COALESCE(NEW.completed_at, NEW.updated_at, CURRENT_TIMESTAMP),
      NEW.tenant_id, NEW.created_by_subject_id
    ) ON CONFLICT DO NOTHING;
    RETURN NEW;
  ELSIF TG_OP = 'DELETE' THEN
    INSERT INTO activity_events(
      entity_type, entity_id, event_type, priority, topic_id, is_synthetic,
      occurred_at, tenant_id, subject_id
    ) VALUES (
      'task', OLD.id, 'task_deleted', OLD.priority, OLD.topic_id,
      OLD.title LIKE 'smoke-%', CURRENT_TIMESTAMP, OLD.tenant_id,
      OLD.created_by_subject_id
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
      tenant_id, subject_id
    ) VALUES (
      'note', NEW.id, 'note_created', NEW.topic_id,
      NEW.title LIKE 'smoke-%', NEW.created_at, NEW.tenant_id,
      NEW.created_by_subject_id
    ) ON CONFLICT DO NOTHING;
    RETURN NEW;
  END IF;
  INSERT INTO activity_events(
    entity_type, entity_id, event_type, topic_id, is_synthetic,
    tenant_id, subject_id
  ) VALUES (
    'note', OLD.id, 'note_deleted', OLD.topic_id, OLD.title LIKE 'smoke-%',
    OLD.tenant_id, OLD.created_by_subject_id
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
      tenant_id, subject_id
    ) VALUES (
      'event', NEW.id, 'event_scheduled', NEW.topic_id,
      NEW.title LIKE 'smoke-%', NEW.created_at, NEW.tenant_id,
      NEW.created_by_subject_id
    ) ON CONFLICT DO NOTHING;
    RETURN NEW;
  END IF;
  INSERT INTO activity_events(
    entity_type, entity_id, event_type, topic_id, is_synthetic,
    tenant_id, subject_id
  ) VALUES (
    'event', OLD.id, 'event_deleted', OLD.topic_id, OLD.title LIKE 'smoke-%',
    OLD.tenant_id, OLD.created_by_subject_id
  ) ON CONFLICT DO NOTHING;
  RETURN OLD;
END
$$;

CREATE OR REPLACE FUNCTION request_subject_erasure(
  p_tenant_id UUID,
  p_actor_subject_id UUID,
  p_target_subject_id UUID
)
RETURNS TABLE(request_id UUID, subject_id UUID, status TEXT, requested_at TIMESTAMPTZ)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE actor_role TEXT;
DECLARE target_role TEXT;
DECLARE existing_id UUID;
BEGIN
  actor_role := tenant_actor_role(p_tenant_id, p_actor_subject_id);
  SELECT m.role INTO target_role FROM tenant_memberships m
  WHERE m.tenant_id = p_tenant_id AND m.subject_id = p_target_subject_id
    AND m.status = 'active' FOR UPDATE;
  IF actor_role IS NULL OR target_role IS NULL THEN
    RAISE EXCEPTION 'erasure request is not authorized' USING ERRCODE = '42501';
  END IF;
  IF p_actor_subject_id <> p_target_subject_id AND actor_role NOT IN ('owner', 'admin') THEN
    RAISE EXCEPTION 'erasure request is not authorized' USING ERRCODE = '42501';
  END IF;
  IF actor_role = 'admin' AND target_role IN ('owner', 'admin') THEN
    RAISE EXCEPTION 'only an owner can erase privileged subjects'
      USING ERRCODE = '42501';
  END IF;
  IF target_role = 'owner' AND (
    SELECT count(*) FROM tenant_memberships m
    WHERE m.tenant_id = p_tenant_id AND m.role = 'owner' AND m.status = 'active'
  ) <= 1 THEN
    RAISE EXCEPTION 'the last tenant owner cannot be erased'
      USING ERRCODE = '23514';
  END IF;
  SELECT r.id INTO existing_id FROM privacy_erasure_requests r
  WHERE r.tenant_id = p_tenant_id AND r.subject_id = p_target_subject_id
    AND r.status IN ('pending', 'processing') FOR UPDATE;
  IF existing_id IS NULL THEN
    INSERT INTO privacy_erasure_requests(
      tenant_id, subject_id, requested_by_subject_id
    ) VALUES (p_tenant_id, p_target_subject_id, p_actor_subject_id)
    RETURNING id INTO existing_id;
  END IF;
  RETURN QUERY SELECT r.id, r.subject_id, r.status, r.requested_at
  FROM privacy_erasure_requests r WHERE r.id = existing_id;
END
$$;

CREATE OR REPLACE FUNCTION list_subject_erasure_requests(
  p_tenant_id UUID,
  p_actor_subject_id UUID
)
RETURNS TABLE(
  request_id UUID,
  subject_id UUID,
  status TEXT,
  requested_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  failure_code TEXT
)
LANGUAGE plpgsql SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
DECLARE actor_role TEXT;
BEGIN
  actor_role := tenant_actor_role(p_tenant_id, p_actor_subject_id);
  IF actor_role IS NULL THEN
    RAISE EXCEPTION 'erasure request listing is not authorized'
      USING ERRCODE = '42501';
  END IF;
  RETURN QUERY
  SELECT r.id, r.subject_id, r.status, r.requested_at, r.completed_at,
    r.failure_code
  FROM privacy_erasure_requests r
  WHERE r.tenant_id = p_tenant_id
    AND (actor_role IN ('owner', 'admin') OR r.subject_id = p_actor_subject_id)
  ORDER BY r.requested_at DESC
  LIMIT 100;
END
$$;

CREATE OR REPLACE FUNCTION list_unpseudonymized_activity(p_batch_size INTEGER)
RETURNS TABLE(event_id BIGINT, tenant_id UUID, subject_id UUID)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF p_batch_size < 1 OR p_batch_size > 10000 THEN
    RAISE EXCEPTION 'batch size outside allowed range' USING ERRCODE = '22023';
  END IF;
  RETURN QUERY SELECT e.id, e.tenant_id, e.subject_id FROM activity_events e
  WHERE e.subject_token IS NULL
  ORDER BY e.id
  LIMIT p_batch_size
  FOR UPDATE OF e SKIP LOCKED;
END
$$;

CREATE OR REPLACE FUNCTION apply_activity_subject_tokens(p_updates JSONB)
RETURNS BIGINT
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE updated_count BIGINT;
BEGIN
  IF jsonb_typeof(p_updates) <> 'array' OR jsonb_array_length(p_updates) > 10000 THEN
    RAISE EXCEPTION 'invalid pseudonymization batch' USING ERRCODE = '22023';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_to_recordset(p_updates) AS x(event_id BIGINT, token TEXT)
    WHERE x.event_id IS NULL OR x.token !~ '^[0-9a-f]{64}$'
  ) THEN
    RAISE EXCEPTION 'invalid pseudonymization token' USING ERRCODE = '22023';
  END IF;
  UPDATE activity_events e SET subject_token = x.token
  FROM jsonb_to_recordset(p_updates) AS x(event_id BIGINT, token TEXT)
  WHERE e.id = x.event_id AND e.subject_token IS NULL;
  GET DIAGNOSTICS updated_count = ROW_COUNT;
  RETURN updated_count;
END
$$;

CREATE OR REPLACE FUNCTION erase_subject_data(request_uuid UUID)
RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE request_row privacy_erasure_requests%ROWTYPE;
DECLARE target_role TEXT;
BEGIN
  SELECT * INTO request_row FROM privacy_erasure_requests
  WHERE id = request_uuid FOR UPDATE;
  IF NOT FOUND OR request_row.status NOT IN ('pending', 'failed') THEN
    RAISE EXCEPTION 'invalid erasure request state' USING ERRCODE = '22023';
  END IF;
  SELECT m.role INTO target_role FROM tenant_memberships m
  WHERE m.tenant_id = request_row.tenant_id AND m.subject_id = request_row.subject_id
    AND m.status = 'active' FOR UPDATE;
  IF target_role = 'owner' AND (
    SELECT count(*) FROM tenant_memberships m
    WHERE m.tenant_id = request_row.tenant_id
      AND m.role = 'owner' AND m.status = 'active'
  ) <= 1 THEN
    RAISE EXCEPTION 'the last tenant owner cannot be erased'
      USING ERRCODE = '23514';
  END IF;
  UPDATE privacy_erasure_requests
  SET status = 'processing', failure_code = NULL, attempts = attempts + 1,
    updated_at = now()
  WHERE id = request_uuid;
  DELETE FROM tasks WHERE tenant_id = request_row.tenant_id
    AND created_by_subject_id = request_row.subject_id;
  DELETE FROM notes WHERE tenant_id = request_row.tenant_id
    AND created_by_subject_id = request_row.subject_id;
  DELETE FROM events WHERE tenant_id = request_row.tenant_id
    AND created_by_subject_id = request_row.subject_id;
  DELETE FROM activity_events WHERE tenant_id = request_row.tenant_id
    AND subject_id = request_row.subject_id;
  DELETE FROM tenant_memberships WHERE tenant_id = request_row.tenant_id
    AND subject_id = request_row.subject_id;
  IF NOT EXISTS (
    SELECT 1 FROM tenant_memberships WHERE subject_id = request_row.subject_id
  ) THEN
    UPDATE subjects SET
      issuer = 'urn:productivity-intelligence:erased',
      external_subject = 'erased:' || request_uuid::text,
      disabled_at = now()
    WHERE id = request_row.subject_id;
  END IF;
  UPDATE privacy_erasure_requests
  SET status = 'completed', completed_at = now(), updated_at = now()
  WHERE id = request_uuid;
END
$$;

CREATE OR REPLACE FUNCTION mark_erasure_request_failed(
  request_uuid UUID,
  p_failure_code TEXT
)
RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF p_failure_code NOT IN ('execution_failed', 'dependency_unavailable') THEN
    RAISE EXCEPTION 'invalid failure code' USING ERRCODE = '22023';
  END IF;
  UPDATE privacy_erasure_requests
  SET status = 'failed', failure_code = p_failure_code, updated_at = now()
  WHERE id = request_uuid AND status IN ('pending', 'processing', 'failed');
  IF NOT FOUND THEN
    RAISE EXCEPTION 'erasure request cannot be marked failed' USING ERRCODE = '22023';
  END IF;
END
$$;

REVOKE ALL ON FUNCTION assign_productivity_topic() FROM PUBLIC;
REVOKE ALL ON FUNCTION request_subject_erasure(UUID, UUID, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION list_subject_erasure_requests(UUID, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION list_unpseudonymized_activity(INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION apply_activity_subject_tokens(JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION rollup_and_purge_activity(INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION erase_subject_data(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION mark_erasure_request_failed(UUID, TEXT) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION request_subject_erasure(UUID, UUID, UUID)
  TO productivity_app;
GRANT EXECUTE ON FUNCTION list_subject_erasure_requests(UUID, UUID)
  TO productivity_app;
GRANT USAGE ON SCHEMA public TO productivity_privacy;
GRANT EXECUTE ON FUNCTION list_unpseudonymized_activity(INTEGER)
  TO productivity_privacy;
GRANT EXECUTE ON FUNCTION apply_activity_subject_tokens(JSONB)
  TO productivity_privacy;
GRANT EXECUTE ON FUNCTION rollup_and_purge_activity(INTEGER)
  TO productivity_privacy;
GRANT EXECUTE ON FUNCTION erase_subject_data(UUID) TO productivity_privacy;
GRANT EXECUTE ON FUNCTION mark_erasure_request_failed(UUID, TEXT)
  TO productivity_privacy;

ALTER ROLE productivity_privacy SET statement_timeout = '60s';
ALTER ROLE productivity_privacy SET idle_in_transaction_session_timeout = '60s';
