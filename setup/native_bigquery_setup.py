"""Provision the Phase 4 native BigQuery schema and v3 TVF contract."""

from __future__ import annotations

import os
import re

from google.cloud import bigquery


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def identifier(name: str) -> str:
    value = required(name)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"{name} must be a SQL identifier")
    return value


def create_native_contracts(
    project: str,
    region: str,
    dataset: str,
    table: str,
    tvf: str,
    max_range_days: int,
) -> None:
    client = bigquery.Client(project=project)
    schema = [
        bigquery.SchemaField("event_id", "INT64", mode="REQUIRED"),
        bigquery.SchemaField("tenant_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("subject_id", "STRING"),
        bigquery.SchemaField("subject_token", "STRING"),
        bigquery.SchemaField("entity_type", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("entity_id", "INT64", mode="REQUIRED"),
        bigquery.SchemaField("event_type", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("priority", "STRING"),
        bigquery.SchemaField("topic_id", "STRING"),
        bigquery.SchemaField("is_synthetic", "BOOL", mode="REQUIRED"),
        bigquery.SchemaField("occurred_at", "TIMESTAMP", mode="REQUIRED"),
    ]
    table_ref = bigquery.Table(f"{project}.{dataset}.{table}", schema=schema)
    table_ref.time_partitioning = bigquery.TimePartitioning(
        field="occurred_at", type_=bigquery.TimePartitioningType.DAY
    )
    table_ref.clustering_fields = ["tenant_id", "event_type", "topic_id"]
    table_ref.require_partition_filter = True
    client.create_table(table_ref, exists_ok=True)

    sql = f"""
    CREATE OR REPLACE TABLE FUNCTION `{project}.{dataset}.{tvf}`(
      p_start_date DATE,
      p_end_date DATE,
      p_grain STRING,
      p_tenant_id STRING,
      p_subject_token STRING
    ) AS (
      WITH validated AS (
        SELECT
          IF(p_end_date >= p_start_date, true,
             ERROR('end_date must not be before start_date')) AS dates_valid,
          IF(DATE_DIFF(p_end_date, p_start_date, DAY) + 1 <= {max_range_days},
             true, ERROR('requested period exceeds configured maximum')) AS range_valid,
          IF(p_grain IN ('day', 'month'), true,
             ERROR('grain must be day or month')) AS grain_valid
      ),
      scoped AS (
        SELECT
          IF(p_grain = 'day', FORMAT_DATE('%F', DATE(occurred_at)),
             FORMAT_DATE('%Y-%m', DATE(occurred_at))) AS period,
          event_type
        FROM `{project}.{dataset}.{table}`, validated
        WHERE DATE(occurred_at) BETWEEN p_start_date AND p_end_date
          AND tenant_id = p_tenant_id
          AND subject_token = p_subject_token
          AND NOT is_synthetic
          AND dates_valid AND range_valid AND grain_valid
      )
      SELECT
        period,
        COUNTIF(event_type = 'task_created') AS tasks_created,
        COUNTIF(event_type = 'task_completed') AS tasks_completed,
        COUNTIF(event_type = 'note_created') AS notes_created,
        COUNTIF(event_type = 'event_scheduled') AS events_scheduled,
        SAFE_DIVIDE(
          COUNTIF(event_type = 'task_completed'),
          COUNTIF(event_type = 'task_created')
        ) AS completion_rate
      FROM scoped
      GROUP BY period
      ORDER BY period
    )
    """
    client.query(sql, location=region).result()


def main() -> None:
    if required("PHASE5_ACTIVE").lower() != "true":
        raise RuntimeError("native BigQuery provisioning is restricted to Phase 5")
    create_native_contracts(
        required("GOOGLE_CLOUD_PROJECT"),
        required("REGION"),
        identifier("BIGQUERY_DATASET"),
        identifier("BIGQUERY_NATIVE_TABLE"),
        identifier("BIGQUERY_NATIVE_TVF"),
        int(required("ANALYTICS_MAX_RANGE_DAYS")),
    )
    print("[OK] Native BigQuery table and v3 TVF contract are ready")


if __name__ == "__main__":
    main()
