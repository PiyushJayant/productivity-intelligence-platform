-- Idempotent AlloyDB schema and migration for Productivity Intelligence Platform.
-- Run as the database administrator. Application passwords are provisioned
-- separately and are never embedded in this file.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS google_ml_integration;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tenants (
    id          UUID PRIMARY KEY,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT tenants_name_nonblank CHECK (btrim(name) <> ''),
    CONSTRAINT tenants_status_valid CHECK (status IN ('active', 'suspended'))
);

CREATE TABLE IF NOT EXISTS subjects (
    id                UUID PRIMARY KEY,
    issuer            TEXT NOT NULL,
    external_subject  TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    disabled_at       TIMESTAMPTZ,
    CONSTRAINT subjects_external_identity_unique
      UNIQUE (issuer, external_subject)
);

CREATE TABLE IF NOT EXISTS tenant_memberships (
    tenant_id  UUID NOT NULL REFERENCES tenants(id),
    subject_id UUID NOT NULL REFERENCES subjects(id),
    role       TEXT NOT NULL DEFAULT 'member',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, subject_id),
    CONSTRAINT tenant_membership_role_valid
      CHECK (role IN ('owner', 'admin', 'member', 'viewer'))
);

INSERT INTO tenants(id, name)
VALUES ('__DEFAULT_TENANT_ID__'::uuid, 'Default tenant')
ON CONFLICT (id) DO NOTHING;
INSERT INTO subjects(id, issuer, external_subject)
VALUES (
  '__BOOTSTRAP_SUBJECT_ID__'::uuid,
  '__BOOTSTRAP_ISSUER__',
  '__BOOTSTRAP_EXTERNAL_SUBJECT__'
)
ON CONFLICT (id) DO NOTHING;
INSERT INTO tenant_memberships(tenant_id, subject_id, role)
VALUES (
  '__DEFAULT_TENANT_ID__'::uuid, '__BOOTSTRAP_SUBJECT_ID__'::uuid, 'owner'
)
ON CONFLICT (tenant_id, subject_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS tasks (
    id            BIGSERIAL PRIMARY KEY,
    title         TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    priority      TEXT NOT NULL DEFAULT 'medium',
    status        TEXT NOT NULL DEFAULT 'pending',
    due_date      DATE,
    due_at        TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at  TIMESTAMPTZ,
    tenant_id     UUID,
    created_by_subject_id UUID,
    CONSTRAINT tasks_title_nonblank CHECK (btrim(title) <> ''),
    CONSTRAINT tasks_priority_valid CHECK (priority IN ('low', 'medium', 'high')),
    CONSTRAINT tasks_status_valid CHECK (status IN ('pending', 'in_progress', 'done'))
);

CREATE TABLE IF NOT EXISTS notes (
    id          BIGSERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    tags        TEXT NOT NULL DEFAULT '',
    embedding   VECTOR(__EMBEDDING_DIMENSIONS__),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    tenant_id   UUID,
    created_by_subject_id UUID,
    CONSTRAINT notes_title_nonblank CHECK (btrim(title) <> ''),
    CONSTRAINT notes_content_nonblank CHECK (btrim(content) <> '')
);

CREATE TABLE IF NOT EXISTS events (
    id               BIGSERIAL PRIMARY KEY,
    title            TEXT NOT NULL,
    date             DATE NOT NULL,
    time             TIME NOT NULL,
    duration_minutes INTEGER NOT NULL DEFAULT 60,
    description      TEXT NOT NULL DEFAULT '',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    tenant_id        UUID,
    created_by_subject_id UUID,
    CONSTRAINT events_title_nonblank CHECK (btrim(title) <> ''),
    CONSTRAINT events_duration_positive CHECK (duration_minutes > 0)
);

-- Privacy-minimized, append-only activity facts preserve analytics when a user
-- hard-deletes operational content. Titles, descriptions, note text, and event
-- details are intentionally never copied into this ledger.
CREATE TABLE IF NOT EXISTS activity_events (
    id           BIGSERIAL PRIMARY KEY,
    entity_type  TEXT NOT NULL,
    entity_id    BIGINT NOT NULL,
    event_type   TEXT NOT NULL,
    priority     TEXT,
    is_synthetic BOOLEAN NOT NULL DEFAULT FALSE,
    tenant_id    UUID,
    subject_id   UUID,
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT activity_entity_type_valid
      CHECK (entity_type IN ('task', 'note', 'event')),
    CONSTRAINT activity_event_type_valid CHECK (
      event_type IN (
        'task_created', 'task_pending', 'task_in_progress', 'task_completed',
        'task_deleted', 'note_created', 'note_deleted',
        'event_scheduled', 'event_deleted'
      )
    ),
    CONSTRAINT activity_priority_valid
      CHECK (priority IS NULL OR priority IN ('low', 'medium', 'high'))
);
ALTER TABLE activity_events ADD COLUMN IF NOT EXISTS
  is_synthetic BOOLEAN NOT NULL DEFAULT FALSE;

-- Upgrade databases created by the original prototype.
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS tenant_id UUID;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS created_by_subject_id UUID;
ALTER TABLE notes ADD COLUMN IF NOT EXISTS tenant_id UUID;
ALTER TABLE notes ADD COLUMN IF NOT EXISTS created_by_subject_id UUID;
ALTER TABLE events ADD COLUMN IF NOT EXISTS tenant_id UUID;
ALTER TABLE events ADD COLUMN IF NOT EXISTS created_by_subject_id UUID;
ALTER TABLE activity_events ADD COLUMN IF NOT EXISTS tenant_id UUID;
ALTER TABLE activity_events ADD COLUMN IF NOT EXISTS subject_id UUID;
UPDATE tasks SET
  tenant_id = COALESCE(tenant_id, '__DEFAULT_TENANT_ID__'::uuid),
  created_by_subject_id = COALESCE(
    created_by_subject_id, '__BOOTSTRAP_SUBJECT_ID__'::uuid
  )
WHERE tenant_id IS NULL OR created_by_subject_id IS NULL;
UPDATE notes SET
  tenant_id = COALESCE(tenant_id, '__DEFAULT_TENANT_ID__'::uuid),
  created_by_subject_id = COALESCE(
    created_by_subject_id, '__BOOTSTRAP_SUBJECT_ID__'::uuid
  )
WHERE tenant_id IS NULL OR created_by_subject_id IS NULL;
UPDATE events SET
  tenant_id = COALESCE(tenant_id, '__DEFAULT_TENANT_ID__'::uuid),
  created_by_subject_id = COALESCE(
    created_by_subject_id, '__BOOTSTRAP_SUBJECT_ID__'::uuid
  )
WHERE tenant_id IS NULL OR created_by_subject_id IS NULL;
UPDATE activity_events SET
  tenant_id = COALESCE(tenant_id, '__DEFAULT_TENANT_ID__'::uuid),
  subject_id = COALESCE(subject_id, '__BOOTSTRAP_SUBJECT_ID__'::uuid)
WHERE tenant_id IS NULL OR subject_id IS NULL;
ALTER TABLE tasks ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE tasks ALTER COLUMN created_by_subject_id SET NOT NULL;
ALTER TABLE notes ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE notes ALTER COLUMN created_by_subject_id SET NOT NULL;
ALTER TABLE events ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE events ALTER COLUMN created_by_subject_id SET NOT NULL;
ALTER TABLE activity_events ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE activity_events ALTER COLUMN subject_id SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'tasks_membership_fk'
  ) THEN
    ALTER TABLE tasks ADD CONSTRAINT tasks_membership_fk
      FOREIGN KEY (tenant_id, created_by_subject_id)
      REFERENCES tenant_memberships(tenant_id, subject_id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'notes_membership_fk'
  ) THEN
    ALTER TABLE notes ADD CONSTRAINT notes_membership_fk
      FOREIGN KEY (tenant_id, created_by_subject_id)
      REFERENCES tenant_memberships(tenant_id, subject_id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'events_membership_fk'
  ) THEN
    ALTER TABLE events ADD CONSTRAINT events_membership_fk
      FOREIGN KEY (tenant_id, created_by_subject_id)
      REFERENCES tenant_memberships(tenant_id, subject_id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'activity_membership_fk'
  ) THEN
    ALTER TABLE activity_events ADD CONSTRAINT activity_membership_fk
      FOREIGN KEY (tenant_id, subject_id)
      REFERENCES tenant_memberships(tenant_id, subject_id);
  END IF;
END $$;

CREATE OR REPLACE FUNCTION enforce_active_membership()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM tenant_memberships AS m
    JOIN tenants AS t ON t.id = m.tenant_id
    WHERE m.tenant_id = NEW.tenant_id
      AND m.subject_id = NEW.created_by_subject_id
      AND t.status = 'active'
      AND m.role IN ('owner', 'admin', 'member')
  ) THEN
    RAISE EXCEPTION 'active tenant membership is required'
      USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tasks_enforce_membership ON tasks;
CREATE TRIGGER tasks_enforce_membership
BEFORE INSERT OR UPDATE OF tenant_id, created_by_subject_id ON tasks
FOR EACH ROW EXECUTE FUNCTION enforce_active_membership();
DROP TRIGGER IF EXISTS notes_enforce_membership ON notes;
CREATE TRIGGER notes_enforce_membership
BEFORE INSERT OR UPDATE OF tenant_id, created_by_subject_id ON notes
FOR EACH ROW EXECUTE FUNCTION enforce_active_membership();
DROP TRIGGER IF EXISTS events_enforce_membership ON events;
CREATE TRIGGER events_enforce_membership
BEFORE INSERT OR UPDATE OF tenant_id, created_by_subject_id ON events
FOR EACH ROW EXECUTE FUNCTION enforce_active_membership();
UPDATE tasks SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
WHERE updated_at IS NULL;
ALTER TABLE tasks ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE tasks ALTER COLUMN updated_at SET NOT NULL;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'tasks' AND column_name = 'due_date' AND data_type = 'text'
  ) THEN
    ALTER TABLE tasks ALTER COLUMN due_date DROP DEFAULT;
    ALTER TABLE tasks ALTER COLUMN due_date TYPE DATE
      USING NULLIF(due_date, '')::date;
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'events' AND column_name = 'date' AND data_type = 'text'
  ) THEN
    ALTER TABLE events ALTER COLUMN date TYPE DATE USING date::date;
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'events' AND column_name = 'time' AND data_type = 'text'
  ) THEN
    ALTER TABLE events ALTER COLUMN time TYPE TIME USING time::time;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION maintain_task_timestamps()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = CURRENT_TIMESTAMP;
  IF NEW.status = 'done' AND OLD.status IS DISTINCT FROM 'done' THEN
    NEW.completed_at = CURRENT_TIMESTAMP;
  ELSIF NEW.status <> 'done' THEN
    NEW.completed_at = NULL;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tasks_maintain_timestamps ON tasks;
CREATE TRIGGER tasks_maintain_timestamps
BEFORE UPDATE ON tasks
FOR EACH ROW EXECUTE FUNCTION maintain_task_timestamps();

CREATE OR REPLACE FUNCTION record_task_activity()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  status_event TEXT;
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO activity_events(
      entity_type, entity_id, event_type, priority, is_synthetic, occurred_at,
      tenant_id, subject_id
    ) VALUES (
      'task', NEW.id, 'task_created', NEW.priority,
      NEW.title LIKE 'smoke-%', NEW.created_at, NEW.tenant_id,
      NEW.created_by_subject_id
    )
    ON CONFLICT DO NOTHING;
    RETURN NEW;
  ELSIF TG_OP = 'UPDATE' AND OLD.status IS DISTINCT FROM NEW.status THEN
    status_event = CASE NEW.status
      WHEN 'pending' THEN 'task_pending'
      WHEN 'in_progress' THEN 'task_in_progress'
      WHEN 'done' THEN 'task_completed'
    END;
    INSERT INTO activity_events(
      entity_type, entity_id, event_type, priority, is_synthetic, occurred_at,
      tenant_id, subject_id
    ) VALUES (
      'task', NEW.id, status_event, NEW.priority,
      NEW.title LIKE 'smoke-%',
      COALESCE(NEW.completed_at, NEW.updated_at, CURRENT_TIMESTAMP),
      NEW.tenant_id, NEW.created_by_subject_id
    )
    ON CONFLICT DO NOTHING;
    RETURN NEW;
  ELSIF TG_OP = 'DELETE' THEN
    INSERT INTO activity_events(
      entity_type, entity_id, event_type, priority, is_synthetic, occurred_at,
      tenant_id, subject_id
    ) VALUES (
      'task', OLD.id, 'task_deleted', OLD.priority,
      OLD.title LIKE 'smoke-%', CURRENT_TIMESTAMP, OLD.tenant_id,
      OLD.created_by_subject_id
    )
    ON CONFLICT DO NOTHING;
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION record_note_activity()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO activity_events(
      entity_type, entity_id, event_type, is_synthetic, occurred_at,
      tenant_id, subject_id
    ) VALUES (
      'note', NEW.id, 'note_created', NEW.title LIKE 'smoke-%', NEW.created_at,
      NEW.tenant_id, NEW.created_by_subject_id
    )
    ON CONFLICT DO NOTHING;
    RETURN NEW;
  END IF;
  INSERT INTO activity_events(
    entity_type, entity_id, event_type, is_synthetic, tenant_id, subject_id
  ) VALUES (
    'note', OLD.id, 'note_deleted', OLD.title LIKE 'smoke-%',
    OLD.tenant_id, OLD.created_by_subject_id
  )
  ON CONFLICT DO NOTHING;
  RETURN OLD;
END;
$$;

CREATE OR REPLACE FUNCTION record_calendar_activity()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO activity_events(
      entity_type, entity_id, event_type, is_synthetic, occurred_at,
      tenant_id, subject_id
    ) VALUES (
      'event', NEW.id, 'event_scheduled',
      NEW.title LIKE 'smoke-%', NEW.created_at, NEW.tenant_id,
      NEW.created_by_subject_id
    )
    ON CONFLICT DO NOTHING;
    RETURN NEW;
  END IF;
  INSERT INTO activity_events(
    entity_type, entity_id, event_type, is_synthetic, tenant_id, subject_id
  ) VALUES (
    'event', OLD.id, 'event_deleted', OLD.title LIKE 'smoke-%',
    OLD.tenant_id, OLD.created_by_subject_id
  )
  ON CONFLICT DO NOTHING;
  RETURN OLD;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS activity_events_natural_key_idx
ON activity_events (entity_type, entity_id, event_type, occurred_at);

CREATE INDEX IF NOT EXISTS activity_events_occurred_at_idx
ON activity_events (occurred_at);
CREATE INDEX IF NOT EXISTS activity_events_tenant_occurred_at_idx
ON activity_events (tenant_id, occurred_at);
CREATE INDEX IF NOT EXISTS tasks_tenant_created_at_idx
ON tasks (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS notes_tenant_created_at_idx
ON notes (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS events_tenant_date_time_idx
ON events (tenant_id, date, time);

-- Backfill retained records once. ON CONFLICT makes the migration repeatable.
INSERT INTO activity_events(
  entity_type, entity_id, event_type, priority, is_synthetic, occurred_at,
  tenant_id, subject_id
)
SELECT
  'task', id, 'task_created', priority, title LIKE 'smoke-%', created_at,
  tenant_id, created_by_subject_id
FROM tasks
ON CONFLICT DO NOTHING;

INSERT INTO activity_events(
  entity_type, entity_id, event_type, priority, is_synthetic, occurred_at,
  tenant_id, subject_id
)
SELECT
  'task', id, 'task_completed', priority, title LIKE 'smoke-%', completed_at,
  tenant_id, created_by_subject_id
FROM tasks WHERE completed_at IS NOT NULL
ON CONFLICT DO NOTHING;

INSERT INTO activity_events(
  entity_type, entity_id, event_type, is_synthetic, occurred_at,
  tenant_id, subject_id
)
SELECT
  'note', id, 'note_created', title LIKE 'smoke-%', created_at,
  tenant_id, created_by_subject_id
FROM notes
ON CONFLICT DO NOTHING;

INSERT INTO activity_events(
  entity_type, entity_id, event_type, is_synthetic, occurred_at,
  tenant_id, subject_id
)
SELECT
  'event', id, 'event_scheduled', title LIKE 'smoke-%', created_at,
  tenant_id, created_by_subject_id
FROM events
ON CONFLICT DO NOTHING;

DROP TRIGGER IF EXISTS tasks_record_activity ON tasks;
CREATE TRIGGER tasks_record_activity
AFTER INSERT OR UPDATE OR DELETE ON tasks
FOR EACH ROW EXECUTE FUNCTION record_task_activity();

DROP TRIGGER IF EXISTS notes_record_activity ON notes;
CREATE TRIGGER notes_record_activity
AFTER INSERT OR DELETE ON notes
FOR EACH ROW EXECUTE FUNCTION record_note_activity();

DROP TRIGGER IF EXISTS calendar_record_activity ON events;
CREATE TRIGGER calendar_record_activity
AFTER INSERT OR DELETE ON events
FOR EACH ROW EXECUTE FUNCTION record_calendar_activity();

CREATE INDEX IF NOT EXISTS tasks_due_at_idx
ON tasks (due_at)
WHERE due_at IS NOT NULL;

GRANT USAGE ON SCHEMA public, google_ml TO productivity_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON tasks, notes, events TO productivity_app;
GRANT SELECT ON tenants, tenant_memberships TO productivity_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO productivity_app;
GRANT EXECUTE ON FUNCTION google_ml.embedding TO productivity_app;
REVOKE ALL ON activity_events FROM productivity_app;

GRANT USAGE ON SCHEMA public TO productivity_analytics;
GRANT SELECT ON activity_events, tenants, tenant_memberships
TO productivity_analytics;

INSERT INTO schema_migrations(version) VALUES ('001_deployment_readiness')
ON CONFLICT (version) DO NOTHING;
INSERT INTO schema_migrations(version) VALUES ('002_task_deadlines')
ON CONFLICT (version) DO NOTHING;
INSERT INTO schema_migrations(version) VALUES ('003_activity_ledger')
ON CONFLICT (version) DO NOTHING;
INSERT INTO schema_migrations(version) VALUES ('004_identity_and_tenant_ownership')
ON CONFLICT (version) DO NOTHING;

SELECT 'AlloyDB schema and migration applied' AS status;
