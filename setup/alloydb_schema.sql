-- Idempotent AlloyDB schema and migration for Productivity Intelligence Platform.
-- Run as the database administrator. Application passwords are provisioned
-- separately and are never embedded in this file.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS google_ml_integration;

CREATE TABLE IF NOT EXISTS tasks (
    id            BIGSERIAL PRIMARY KEY,
    title         TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    priority      TEXT NOT NULL DEFAULT 'medium',
    status        TEXT NOT NULL DEFAULT 'pending',
    due_date      DATE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at  TIMESTAMPTZ,
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
    CONSTRAINT events_title_nonblank CHECK (btrim(title) <> ''),
    CONSTRAINT events_duration_positive CHECK (duration_minutes > 0)
);

-- Upgrade databases created by the original prototype.
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
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

GRANT USAGE ON SCHEMA public, google_ml TO productivity_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON tasks, notes, events TO productivity_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO productivity_app;
GRANT EXECUTE ON FUNCTION google_ml.embedding TO productivity_app;

GRANT USAGE ON SCHEMA public TO productivity_analytics;
GRANT SELECT ON tasks, notes, events TO productivity_analytics;

INSERT INTO schema_migrations(version) VALUES ('001_deployment_readiness')
ON CONFLICT (version) DO NOTHING;

SELECT 'AlloyDB schema and migration applied' AS status;
