"""Create live BigQuery analytics views over an AlloyDB federation connection."""

from __future__ import annotations

import argparse
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google.cloud import bigquery


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} environment variable is required")
    return value


def create_live_views(
    project_id: str,
    region: str,
    dataset_id: str,
    connection_id: str,
    timezone: str,
) -> None:
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError("DEFAULT_TIMEZONE must be a valid IANA timezone") from error
    if "'" in timezone:
        raise ValueError("DEFAULT_TIMEZONE contains unsupported characters")

    client = bigquery.Client(project=project_id)
    dataset_ref = bigquery.Dataset(f"{project_id}.{dataset_id}")
    dataset_ref.location = region
    dataset_ref.description = "Live federated productivity analytics"
    client.create_dataset(dataset_ref, exists_ok=True)

    connection = f"{project_id}.{region}.{connection_id}"
    task_summary_sql = f"""
    CREATE OR REPLACE VIEW `{project_id}.{dataset_id}.task_summary` AS
    SELECT *
    FROM EXTERNAL_QUERY(
      '{connection}',
      '''
      WITH created AS (
        SELECT
          entity_id,
          priority,
          (occurred_at AT TIME ZONE '{timezone}')::date AS date
        FROM activity_events
        WHERE entity_type = 'task'
          AND event_type = 'task_created'
          AND NOT is_synthetic
      ),
      latest_status AS (
        SELECT DISTINCT ON (entity_id)
          entity_id,
          CASE event_type
            WHEN 'task_created' THEN 'pending'
            WHEN 'task_pending' THEN 'pending'
            WHEN 'task_in_progress' THEN 'in_progress'
            WHEN 'task_completed' THEN 'done'
          END AS status
        FROM activity_events
        WHERE entity_type = 'task'
          AND NOT is_synthetic
          AND event_type IN (
            'task_created', 'task_pending', 'task_in_progress', 'task_completed'
          )
        ORDER BY entity_id, occurred_at DESC, id DESC
      )
      SELECT
        created.date,
        created.priority,
        COUNT(*)::bigint AS total_tasks,
        COUNT(*) FILTER (WHERE latest_status.status = 'done')::bigint
          AS completed_tasks,
        COUNT(*) FILTER (WHERE latest_status.status = 'pending')::bigint
          AS pending_tasks,
        COUNT(*) FILTER (WHERE latest_status.status = 'in_progress')::bigint
          AS in_progress_tasks,
        (COUNT(*) FILTER (WHERE latest_status.status = 'done'))::double precision
          / NULLIF(COUNT(*), 0) AS completion_rate
      FROM created
      JOIN latest_status USING (entity_id)
      GROUP BY created.date, created.priority
      '''
    )
    """

    daily_activity_sql = f"""
    CREATE OR REPLACE VIEW `{project_id}.{dataset_id}.daily_activity` AS
    SELECT *
    FROM EXTERNAL_QUERY(
      '{connection}',
      '''
      SELECT
        (occurred_at AT TIME ZONE '{timezone}')::date AS date,
        COUNT(*) FILTER (WHERE event_type = 'task_created')::bigint
          AS tasks_created,
        COUNT(*) FILTER (WHERE event_type = 'task_completed')::bigint
          AS tasks_completed,
        COUNT(*) FILTER (WHERE event_type = 'note_created')::bigint
          AS notes_created,
        COUNT(*) FILTER (WHERE event_type = 'event_scheduled')::bigint
          AS events_scheduled
      FROM activity_events
      WHERE event_type IN (
        'task_created', 'task_completed', 'note_created', 'event_scheduled'
      )
        AND NOT is_synthetic
      GROUP BY (occurred_at AT TIME ZONE '{timezone}')::date
      '''
    )
    """

    client.query(task_summary_sql, location=region).result()
    client.query(daily_activity_sql, location=region).result()
    print(f"[OK] Live analytics views created in {project_id}.{dataset_id}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    create_live_views(
        required_env("GOOGLE_CLOUD_PROJECT"),
        required_env("REGION"),
        required_env("BIGQUERY_DATASET"),
        required_env("BIGQUERY_CONNECTION_ID"),
        required_env("DEFAULT_TIMEZONE"),
    )


if __name__ == "__main__":
    main()
