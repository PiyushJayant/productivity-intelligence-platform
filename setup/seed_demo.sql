-- Optional idempotent synthetic records for hackathon demonstrations.
INSERT INTO tasks (title, description, priority, status, due_date)
SELECT 'Prepare hackathon demo', 'Synthetic shared demo task', 'high', 'pending', CURRENT_DATE + 2
WHERE NOT EXISTS (SELECT 1 FROM tasks WHERE title = 'Prepare hackathon demo');

INSERT INTO notes (title, content, tags, embedding)
SELECT
  'Demo ideas',
  'Use live federated analytics and semantic note retrieval in the presentation.',
  'hackathon,demo',
  google_ml.embedding(
    'text-embedding-005',
    'Demo ideas Use live federated analytics and semantic note retrieval in the presentation.'
  )::vector
WHERE NOT EXISTS (SELECT 1 FROM notes WHERE title = 'Demo ideas');

INSERT INTO events (title, date, time, duration_minutes, description)
SELECT 'Demo rehearsal', CURRENT_DATE + 1, TIME '14:00', 45, 'Synthetic shared demo event'
WHERE NOT EXISTS (SELECT 1 FROM events WHERE title = 'Demo rehearsal');
