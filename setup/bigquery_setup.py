"""Create live BigQuery analytics views over an AlloyDB federation connection."""

from __future__ import annotations

import argparse
import os

from google.cloud import bigquery


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} environment variable is required")
    return value


def create_live_views(project_id: str, region: str, connection_id: str) -> None:
    client = bigquery.Client(project=project_id)
    dataset_id = "productivity_analytics"
    dataset_ref = bigquery.Dataset(f"{project_id}.{dataset_id}")
    dataset_ref.location = region
    dataset_ref.description = "Live federated productivity analytics"
    client.create_dataset(dataset_ref, exists_ok=True)

    connection = f"{project_id}.{region}.{connection_id}"
    task_summary_sql = f"""
    CREATE OR REPLACE VIEW `{project_id}.{dataset_id}.task_summary` AS
    SELECT
      DATE(created_at) AS date,
      priority,
      COUNT(*) AS total_tasks,
      COUNTIF(status = 'done') AS completed_tasks,
      COUNTIF(status = 'pending') AS pending_tasks,
      COUNTIF(status = 'in_progress') AS in_progress_tasks,
      SAFE_DIVIDE(COUNTIF(status = 'done'), COUNT(*)) AS completion_rate
    FROM EXTERNAL_QUERY(
      '{connection}',
      '''SELECT created_at, priority, status FROM tasks'''
    )
    GROUP BY date, priority
    """

    daily_activity_sql = f"""
    CREATE OR REPLACE VIEW `{project_id}.{dataset_id}.daily_activity` AS
    WITH activity AS (
      SELECT DATE(created_at) AS date, 1 AS tasks_created, 0 AS tasks_completed,
             0 AS notes_created, 0 AS events_scheduled
      FROM EXTERNAL_QUERY('{connection}', '''SELECT created_at FROM tasks''')
      UNION ALL
      SELECT DATE(completed_at), 0, 1, 0, 0
      FROM EXTERNAL_QUERY(
        '{connection}',
        '''SELECT completed_at FROM tasks WHERE completed_at IS NOT NULL'''
      )
      UNION ALL
      SELECT DATE(created_at), 0, 0, 1, 0
      FROM EXTERNAL_QUERY('{connection}', '''SELECT created_at FROM notes''')
      UNION ALL
      SELECT DATE(created_at), 0, 0, 0, 1
      FROM EXTERNAL_QUERY('{connection}', '''SELECT created_at FROM events''')
    )
    SELECT date,
           SUM(tasks_created) AS tasks_created,
           SUM(tasks_completed) AS tasks_completed,
           SUM(notes_created) AS notes_created,
           SUM(events_scheduled) AS events_scheduled
    FROM activity
    GROUP BY date
    """

    client.query(task_summary_sql, location=region).result()
    client.query(daily_activity_sql, location=region).result()
    print(f"[OK] Live analytics views created in {project_id}.{dataset_id}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    create_live_views(
        required_env("GOOGLE_CLOUD_PROJECT"),
        os.getenv("REGION", "us-central1"),
        os.getenv("BIGQUERY_CONNECTION_ID", "productivity_alloydb"),
    )


if __name__ == "__main__":
    main()
