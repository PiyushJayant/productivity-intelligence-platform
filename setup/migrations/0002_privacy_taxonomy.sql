-- Privacy-minimized semantic enrichment and lifecycle controls.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS productivity_topics (
  topic_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  taxonomy_version TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT true
);

INSERT INTO productivity_topics(topic_id, display_name, taxonomy_version)
VALUES
  ('planning', 'Planning', '__TAXONOMY_VERSION__'),
  ('engineering', 'Engineering', '__TAXONOMY_VERSION__'),
  ('operations', 'Operations', '__TAXONOMY_VERSION__'),
  ('communication', 'Communication', '__TAXONOMY_VERSION__'),
  ('learning', 'Learning', '__TAXONOMY_VERSION__'),
  ('personal', 'Personal', '__TAXONOMY_VERSION__'),
  ('uncategorized', 'Uncategorized', '__TAXONOMY_VERSION__')
ON CONFLICT (topic_id) DO UPDATE
SET display_name = EXCLUDED.display_name,
    taxonomy_version = EXCLUDED.taxonomy_version;

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS topic_id TEXT;
ALTER TABLE notes ADD COLUMN IF NOT EXISTS topic_id TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS topic_id TEXT;
ALTER TABLE activity_events ADD COLUMN IF NOT EXISTS topic_id TEXT;
ALTER TABLE activity_events ADD COLUMN IF NOT EXISTS subject_token CHAR(64);

CREATE OR REPLACE FUNCTION classify_productivity_topic(input_text TEXT)
RETURNS TEXT
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$
  SELECT CASE
    WHEN input_text ~* '(deploy|server|cloud|incident|monitor|operation)' THEN 'operations'
    WHEN input_text ~* '(code|bug|api|database|develop|test)' THEN 'engineering'
    WHEN input_text ~* '(email|meeting|presentation|message|call)' THEN 'communication'
    WHEN input_text ~* '(learn|course|read|study|research)' THEN 'learning'
    WHEN input_text ~* '(plan|roadmap|schedule|milestone)' THEN 'planning'
    WHEN input_text ~* '(health|family|home|personal)' THEN 'personal'
    ELSE 'uncategorized'
  END
$$;

UPDATE tasks SET topic_id = classify_productivity_topic(title || ' ' || description)
WHERE topic_id IS NULL;
UPDATE notes SET topic_id = classify_productivity_topic(title || ' ' || content)
WHERE topic_id IS NULL;
UPDATE events SET topic_id = classify_productivity_topic(title || ' ' || description)
WHERE topic_id IS NULL;
UPDATE activity_events SET topic_id = 'uncategorized' WHERE topic_id IS NULL;

ALTER TABLE tasks ALTER COLUMN topic_id SET DEFAULT 'uncategorized';
ALTER TABLE notes ALTER COLUMN topic_id SET DEFAULT 'uncategorized';
ALTER TABLE events ALTER COLUMN topic_id SET DEFAULT 'uncategorized';
ALTER TABLE activity_events ALTER COLUMN topic_id SET DEFAULT 'uncategorized';

CREATE INDEX IF NOT EXISTS idx_activity_tenant_occurred
  ON activity_events(tenant_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_subject_occurred
  ON activity_events(subject_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_topic_occurred
  ON activity_events(topic_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS privacy_erasure_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  subject_id UUID NOT NULL REFERENCES subjects(id),
  requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
  failure_code TEXT
);

CREATE TABLE IF NOT EXISTS daily_activity_aggregates (
  tenant_id UUID NOT NULL,
  activity_date DATE NOT NULL,
  topic_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  event_count BIGINT NOT NULL CHECK (event_count >= 0),
  PRIMARY KEY (tenant_id, activity_date, topic_id, event_type)
);

CREATE OR REPLACE FUNCTION rollup_and_purge_activity(retention_days INTEGER)
RETURNS BIGINT
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE deleted_count BIGINT;
BEGIN
  IF retention_days < 1 OR retention_days > 3650 THEN
    RAISE EXCEPTION 'retention_days outside allowed range';
  END IF;
  INSERT INTO daily_activity_aggregates(
    tenant_id, activity_date, topic_id, event_type, event_count
  )
  SELECT tenant_id, occurred_at::date, topic_id, event_type, count(*)
  FROM activity_events
  WHERE occurred_at < now() - make_interval(days => retention_days)
  GROUP BY tenant_id, occurred_at::date, topic_id, event_type
  ON CONFLICT (tenant_id, activity_date, topic_id, event_type)
  DO UPDATE SET event_count = EXCLUDED.event_count;

  DELETE FROM activity_events
  WHERE occurred_at < now() - make_interval(days => retention_days);
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RETURN deleted_count;
END
$$;

CREATE OR REPLACE FUNCTION erase_subject_data(request_uuid UUID)
RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE request_row privacy_erasure_requests%ROWTYPE;
BEGIN
  SELECT * INTO request_row FROM privacy_erasure_requests
  WHERE id = request_uuid FOR UPDATE;
  IF NOT FOUND OR request_row.status NOT IN ('pending', 'failed') THEN
    RAISE EXCEPTION 'invalid erasure request state';
  END IF;
  UPDATE privacy_erasure_requests SET status = 'processing', failure_code = NULL
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
  UPDATE privacy_erasure_requests
  SET status = 'completed', completed_at = now()
  WHERE id = request_uuid;
END
$$;

REVOKE ALL ON privacy_erasure_requests, daily_activity_aggregates FROM PUBLIC;
REVOKE ALL ON FUNCTION rollup_and_purge_activity(INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION erase_subject_data(UUID) FROM PUBLIC;
GRANT SELECT ON productivity_topics, daily_activity_aggregates TO productivity_analytics;
