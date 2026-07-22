-- Run only after notes contains enough rows to make an ANN index useful.
DO $$
DECLARE
  note_count BIGINT;
BEGIN
  SELECT count(*) INTO note_count FROM notes WHERE embedding IS NOT NULL;
  IF note_count < 10000 THEN
    RAISE NOTICE 'Skipping ScaNN index: % embedded notes; 10000 required', note_count;
    RETURN;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE indexname = 'notes_embedding_scann_idx'
  ) THEN
    EXECUTE 'CREATE INDEX notes_embedding_scann_idx ON notes '
      'USING scann (embedding cosine) '
      'WITH (mode = ''MANUAL'', num_leaves = 100, quantizer = ''SQ8'')';
    ANALYZE notes;
  END IF;
END $$;
