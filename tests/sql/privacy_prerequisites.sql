CREATE ROLE productivity_app NOLOGIN;
CREATE ROLE productivity_privacy NOLOGIN;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE tenants (
  id UUID PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE subjects (
  id UUID PRIMARY KEY, issuer TEXT NOT NULL, external_subject TEXT NOT NULL,
  disabled_at TIMESTAMPTZ, UNIQUE (issuer, external_subject)
);
CREATE TABLE tenant_memberships (
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  subject_id UUID NOT NULL REFERENCES subjects(id),
  role TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
  PRIMARY KEY (tenant_id, subject_id)
);
CREATE TABLE productivity_topics (
  topic_id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
  taxonomy_version TEXT NOT NULL, is_active BOOLEAN NOT NULL DEFAULT true
);
INSERT INTO productivity_topics(topic_id, display_name, taxonomy_version)
VALUES
  ('operations', 'Operations', 'v1'),
  ('engineering', 'Engineering', 'v1'),
  ('communication', 'Communication', 'v1'),
  ('learning', 'Learning', 'v1'),
  ('planning', 'Planning', 'v1'),
  ('personal', 'Personal', 'v1'),
  ('uncategorized', 'Uncategorized', 'v1');

CREATE TABLE tasks (
  id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
  priority TEXT NOT NULL DEFAULT 'medium', status TEXT NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ, tenant_id UUID, created_by_subject_id UUID, topic_id TEXT
);
CREATE TABLE notes (
  id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), tenant_id UUID,
  created_by_subject_id UUID, topic_id TEXT
);
CREATE TABLE events (
  id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), tenant_id UUID,
  created_by_subject_id UUID, topic_id TEXT
);
CREATE TABLE activity_events (
  id BIGSERIAL PRIMARY KEY, entity_type TEXT NOT NULL, entity_id BIGINT NOT NULL,
  event_type TEXT NOT NULL CHECK (event_type IN (
    'task_created', 'task_pending', 'task_in_progress', 'task_completed',
    'task_deleted', 'note_created', 'note_deleted', 'event_scheduled', 'event_deleted'
  )), priority TEXT, topic_id TEXT, is_synthetic BOOLEAN NOT NULL DEFAULT false,
  tenant_id UUID, subject_id UUID, subject_token CHAR(64),
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE privacy_erasure_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  subject_id UUID NOT NULL REFERENCES subjects(id), requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ, status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
  failure_code TEXT
);
CREATE TABLE daily_activity_aggregates (
  tenant_id UUID NOT NULL, activity_date DATE NOT NULL, topic_id TEXT NOT NULL,
  event_type TEXT NOT NULL, event_count BIGINT NOT NULL,
  PRIMARY KEY (tenant_id, activity_date, topic_id, event_type)
);

CREATE FUNCTION classify_productivity_topic(input_text TEXT) RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN input_text ~* '(deploy|cloud)' THEN 'operations'
    ELSE 'uncategorized' END
$$;
CREATE FUNCTION tenant_actor_role(p_tenant_id UUID, p_subject_id UUID) RETURNS TEXT
LANGUAGE sql STABLE AS $$
  SELECT role FROM tenant_memberships
  WHERE tenant_id = p_tenant_id AND subject_id = p_subject_id AND status = 'active'
$$;
CREATE FUNCTION rollup_and_purge_activity(retention_days INTEGER) RETURNS BIGINT
LANGUAGE sql AS $$ SELECT 0::BIGINT $$;

CREATE FUNCTION record_task_activity() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN RETURN COALESCE(NEW, OLD); END $$;
CREATE FUNCTION record_note_activity() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN RETURN COALESCE(NEW, OLD); END $$;
CREATE FUNCTION record_calendar_activity() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN RETURN COALESCE(NEW, OLD); END $$;
CREATE TRIGGER tasks_activity AFTER INSERT OR UPDATE OR DELETE ON tasks
FOR EACH ROW EXECUTE FUNCTION record_task_activity();
CREATE TRIGGER notes_activity AFTER INSERT OR DELETE ON notes
FOR EACH ROW EXECUTE FUNCTION record_note_activity();
CREATE TRIGGER events_activity AFTER INSERT OR DELETE ON events
FOR EACH ROW EXECUTE FUNCTION record_calendar_activity();
