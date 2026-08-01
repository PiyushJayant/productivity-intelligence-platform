"""Create versioned BigQuery analytics contracts over AlloyDB federation."""

from __future__ import annotations

import argparse
import os
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google.api_core.exceptions import NotFound
from google.cloud import bigquery


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} environment variable is required")
    return value


def positive_int_env(name: str) -> int:
    raw = required_env(name)
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if value < 1:
        raise ValueError(f"{name} must be greater than zero")
    return value


def create_analytics_contracts(
    project_id: str,
    region: str,
    dataset_id: str,
    connection_id: str,
    procedure_id: str,
    timezone: str,
    max_range_days: int,
) -> None:
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError("DEFAULT_TIMEZONE must be a valid IANA timezone") from error
    if "'" in timezone:
        raise ValueError("DEFAULT_TIMEZONE contains unsupported characters")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", procedure_id):
        raise ValueError("BIGQUERY_ANALYTICS_PROCEDURE must be a SQL identifier")
    if max_range_days < 1:
        raise ValueError("ANALYTICS_MAX_RANGE_DAYS must be greater than zero")

    client = bigquery.Client(project=project_id)
    dataset_ref = bigquery.Dataset(f"{project_id}.{dataset_id}")
    dataset_ref.location = region
    dataset_ref.description = "Live federated productivity analytics"
    if os.getenv("ENABLE_CMEK", "false").lower() == "true":
        key = (
            f"projects/{project_id}/locations/{region}/keyRings/"
            f"{required_env('KMS_KEYRING')}/cryptoKeys/"
            f"{required_env('KMS_BIGQUERY_KEY')}"
        )
        dataset_ref.default_encryption_configuration = (
            bigquery.EncryptionConfiguration(kms_key_name=key)
        )
    try:
        existing_dataset = client.get_dataset(dataset_ref.reference)
    except NotFound:
        client.create_dataset(dataset_ref)
    else:
        if existing_dataset.location.lower() != region.lower():
            raise ValueError("existing BigQuery dataset is in a different region")
        if dataset_ref.default_encryption_configuration is not None:
            existing_dataset.default_encryption_configuration = (
                dataset_ref.default_encryption_configuration
            )
            client.update_dataset(
                existing_dataset,
                ["default_encryption_configuration"],
            )

    connection = f"{project_id}.{region}.{connection_id}"
    # Date bounds and the trusted tenant ID are embedded in the PostgreSQL
    # statement so filtering is deterministic and happens before aggregation.
    procedure_sql = f'''
    CREATE OR REPLACE PROCEDURE
      `{project_id}.{dataset_id}.{procedure_id}`(
        p_start_date DATE,
        p_end_date DATE,
        p_grain STRING,
        p_tenant_id STRING,
        p_subject_id STRING
      )
    BEGIN
      DECLARE remote_sql STRING;
      DECLARE period_expression STRING;
      DECLARE period_format STRING;
      DECLARE connection_name STRING DEFAULT '{connection}';
      DECLARE exclusive_end DATE;

      IF p_start_date IS NULL OR p_end_date IS NULL THEN
        RAISE USING MESSAGE = 'start_date and end_date are required';
      END IF;
      IF NOT REGEXP_CONTAINS(
        p_tenant_id,
        r'^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[1-5][0-9a-f]{{3}}-[89ab][0-9a-f]{{3}}-[0-9a-f]{{12}}$'
      ) THEN
        RAISE USING MESSAGE = 'tenant identity is invalid';
      END IF;
      IF NOT REGEXP_CONTAINS(
        p_subject_id,
        r'^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[1-5][0-9a-f]{{3}}-[89ab][0-9a-f]{{3}}-[0-9a-f]{{12}}$'
      ) THEN
        RAISE USING MESSAGE = 'subject identity is invalid';
      END IF;
      IF p_end_date < p_start_date THEN
        RAISE USING MESSAGE = 'end_date must not be before start_date';
      END IF;
      IF DATE_DIFF(p_end_date, p_start_date, DAY) + 1 > {max_range_days} THEN
        RAISE USING MESSAGE =
          'requested analytics period exceeds the configured maximum';
      END IF;
      IF p_grain = 'day' THEN
        SET period_expression =
          "(e.occurred_at AT TIME ZONE '{timezone}')::date";
        SET period_format = 'YYYY-MM-DD';
      ELSEIF p_grain = 'month' THEN
        SET period_expression =
          "date_trunc('month', e.occurred_at AT TIME ZONE "
          || "'{timezone}')::date";
        SET period_format = 'YYYY-MM';
      ELSE
        RAISE USING MESSAGE = 'grain must be day or month';
      END IF;

      SET exclusive_end = DATE_ADD(p_end_date, INTERVAL 1 DAY);
      SET remote_sql = FORMAT("""
        WITH bounds AS (
          SELECT
            (DATE '%s'::timestamp AT TIME ZONE '{timezone}') AS start_at,
            (DATE '%s'::timestamp AT TIME ZONE '{timezone}') AS end_at
        ),
        scoped_events AS (
          SELECT
            e.entity_type,
            e.entity_id,
            e.event_type,
            e.priority,
            %s AS period
          FROM activity_events AS e
          CROSS JOIN bounds AS b
          WHERE e.occurred_at >= b.start_at
            AND e.occurred_at < b.end_at
            AND e.tenant_id = '%s'::uuid
            AND EXISTS (
              SELECT 1
              FROM tenant_memberships AS m
              JOIN tenants AS t ON t.id = m.tenant_id
              WHERE m.tenant_id = e.tenant_id
                AND m.subject_id = '%s'::uuid
                AND t.status = 'active'
                AND m.status = 'active'
            )
            AND NOT e.is_synthetic
        ),
        created AS (
          SELECT entity_id, priority, period
          FROM scoped_events
          WHERE entity_type = 'task' AND event_type = 'task_created'
        ),
        latest_status AS (
          SELECT DISTINCT ON (e.entity_id)
            e.entity_id,
            CASE e.event_type
              WHEN 'task_created' THEN 'pending'
              WHEN 'task_pending' THEN 'pending'
              WHEN 'task_in_progress' THEN 'in_progress'
              WHEN 'task_completed' THEN 'done'
            END AS status
          FROM activity_events AS e
          JOIN (SELECT DISTINCT entity_id FROM created) AS c
            ON c.entity_id = e.entity_id
          CROSS JOIN bounds AS b
          WHERE e.entity_type = 'task'
            AND e.tenant_id = '%s'::uuid
            AND NOT e.is_synthetic
            AND e.occurred_at < b.end_at
            AND e.event_type IN (
              'task_created', 'task_pending', 'task_in_progress',
              'task_completed'
            )
          ORDER BY e.entity_id, e.occurred_at DESC, e.id DESC
        ),
        task AS (
          SELECT
            c.period,
            COUNT(*)::bigint AS total_tasks,
            COUNT(*) FILTER (WHERE s.status = 'done')::bigint
              AS completed_tasks,
            COUNT(*) FILTER (WHERE s.status = 'pending')::bigint
              AS pending_tasks,
            COUNT(*) FILTER (WHERE s.status = 'in_progress')::bigint
              AS in_progress_tasks
          FROM created AS c
          JOIN latest_status AS s USING (entity_id)
          GROUP BY c.period
        ),
        activity AS (
          SELECT
            period,
            COUNT(*) FILTER (WHERE event_type = 'task_created')::bigint
              AS tasks_created,
            COUNT(*) FILTER (WHERE event_type = 'task_completed')::bigint
              AS tasks_completed,
            COUNT(*) FILTER (WHERE event_type = 'note_created')::bigint
              AS notes_created,
            COUNT(*) FILTER (WHERE event_type = 'event_scheduled')::bigint
              AS events_scheduled
          FROM scoped_events
          WHERE event_type IN (
            'task_created', 'task_completed', 'note_created', 'event_scheduled'
          )
          GROUP BY period
        )
        SELECT
          to_char(COALESCE(t.period, a.period), '%s') AS period,
          COALESCE(t.total_tasks, 0)::bigint AS total_tasks,
          COALESCE(t.completed_tasks, 0)::bigint AS completed_tasks,
          COALESCE(t.pending_tasks, 0)::bigint AS pending_tasks,
          COALESCE(t.in_progress_tasks, 0)::bigint AS in_progress_tasks,
          COALESCE(t.completed_tasks, 0)::double precision
            / NULLIF(COALESCE(t.total_tasks, 0), 0)::double precision
              AS completion_rate,
          COALESCE(a.tasks_created, 0)::bigint AS tasks_created,
          COALESCE(a.tasks_completed, 0)::bigint AS tasks_completed,
          COALESCE(a.notes_created, 0)::bigint AS notes_created,
          COALESCE(a.events_scheduled, 0)::bigint AS events_scheduled
        FROM task AS t
        FULL OUTER JOIN activity AS a USING (period)
        ORDER BY COALESCE(t.period, a.period)
      """,
        FORMAT_DATE('%F', p_start_date),
        FORMAT_DATE('%F', exclusive_end),
        period_expression,
        p_tenant_id,
        p_subject_id,
        p_tenant_id,
        period_format
      );

      -- %T renders each string as a valid GoogleSQL literal, including quotes
      -- inside the PostgreSQL statement. No model-authored SQL reaches here.
      EXECUTE IMMEDIATE FORMAT(
        "SELECT * FROM EXTERNAL_QUERY(%T, %T)",
        connection_name,
        remote_sql
      );
    END
    '''

    # Unparameterized compatibility views cannot enforce request tenant
    # ownership. Remove them before installing the trusted routine contract.
    client.query(
        f"""
        DROP VIEW IF EXISTS `{project_id}.{dataset_id}.task_summary`;
        DROP VIEW IF EXISTS `{project_id}.{dataset_id}.daily_activity`;
        """,
        location=region,
    ).result()
    client.query(procedure_sql, location=region).result()
    print(
        "[OK] Live analytics views and bounded procedure created in "
        f"{project_id}.{dataset_id}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    create_analytics_contracts(
        required_env("GOOGLE_CLOUD_PROJECT"),
        required_env("REGION"),
        required_env("BIGQUERY_DATASET"),
        required_env("BIGQUERY_CONNECTION_ID"),
        required_env("BIGQUERY_ANALYTICS_PROCEDURE"),
        required_env("DEFAULT_TIMEZONE"),
        positive_int_env("ANALYTICS_MAX_RANGE_DAYS"),
    )


if __name__ == "__main__":
    main()
