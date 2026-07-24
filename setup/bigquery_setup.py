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
      SELECT
        (created_at AT TIME ZONE '{timezone}')::date AS date,
        priority,
        COUNT(*)::bigint AS total_tasks,
        COUNT(*) FILTER (WHERE status = 'done')::bigint AS completed_tasks,
        COUNT(*) FILTER (WHERE status = 'pending')::bigint AS pending_tasks,
        COUNT(*) FILTER (WHERE status = 'in_progress')::bigint AS in_progress_tasks,
        (COUNT(*) FILTER (WHERE status = 'done'))::double precision
          / NULLIF(COUNT(*), 0) AS completion_rate
      FROM tasks
      GROUP BY (created_at AT TIME ZONE '{timezone}')::date, priority
      '''
    )
    """

    daily_activity_sql = f"""
    CREATE OR REPLACE VIEW `{project_id}.{dataset_id}.daily_activity` AS
    SELECT *
    FROM EXTERNAL_QUERY(
      '{connection}',
      '''
      WITH activity AS (
        SELECT (created_at AT TIME ZONE '{timezone}')::date AS date,
               1 AS tasks_created, 0 AS tasks_completed,
               0 AS notes_created, 0 AS events_scheduled
        FROM tasks
        UNION ALL
        SELECT (completed_at AT TIME ZONE '{timezone}')::date, 0, 1, 0, 0
        FROM tasks
        WHERE completed_at IS NOT NULL
        UNION ALL
        SELECT (created_at AT TIME ZONE '{timezone}')::date, 0, 0, 1, 0
        FROM notes
        UNION ALL
        SELECT (created_at AT TIME ZONE '{timezone}')::date, 0, 0, 0, 1
        FROM events
      )
      SELECT date,
             SUM(tasks_created)::bigint AS tasks_created,
             SUM(tasks_completed)::bigint AS tasks_completed,
             SUM(notes_created)::bigint AS notes_created,
             SUM(events_scheduled)::bigint AS events_scheduled
      FROM activity
      GROUP BY date
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
