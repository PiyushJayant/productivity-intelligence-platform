-- Optional idempotent synthetic records for demonstrations.
INSERT INTO tasks (title, description, priority, status, due_date)
SELECT 'Submit weekly report', 'Summarize completed work and next steps', 'high', 'pending', CURRENT_DATE + 2
WHERE NOT EXISTS (SELECT 1 FROM tasks WHERE title = 'Submit weekly report');

INSERT INTO notes (title, content, tags, embedding)
SELECT
  'Focus routine',
  'Silence notifications, choose one important task, and work without interruptions for 45 minutes.',
  'productivity,focus',
  google_ml.embedding(
    '__EMBEDDING_MODEL__',
    'Focus routine Silence notifications, choose one important task, and work without interruptions for 45 minutes.'
  )::vector
WHERE NOT EXISTS (SELECT 1 FROM notes WHERE title = 'Focus routine');

INSERT INTO events (title, date, time, duration_minutes, description)
SELECT 'Weekly planning session', CURRENT_DATE + 1, TIME '14:00', 30, 'Review priorities for the coming week'
WHERE NOT EXISTS (SELECT 1 FROM events WHERE title = 'Weekly planning session');
