"""Validate the Datastream-created table and install the native v3 TVF."""

from __future__ import annotations

import os
import re

from google.cloud import bigquery

EXPECTED_FIELDS = {
    "event_id",
    "tenant_token",
    "subject_token",
    "entity_type",
    "event_type",
    "priority",
    "topic_id",
    "is_synthetic",
    "occurred_at",
    "exported_at",
}
FORBIDDEN_FIELDS = {
    "tenant_id",
    "subject_id",
    "entity_id",
    "title",
    "description",
    "content",
    "embedding",
}


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


def validate_native_table(
    table: bigquery.Table, *, require_partition_filter: bool = True
) -> None:
    fields = {field.name for field in table.schema}
    missing = EXPECTED_FIELDS - fields
    forbidden = FORBIDDEN_FIELDS & fields
    if missing:
        raise RuntimeError(f"native CDC table is missing fields: {sorted(missing)}")
    if forbidden:
        raise RuntimeError("native CDC table contains prohibited operational identifiers")
    if table.time_partitioning is None or table.time_partitioning.field != "occurred_at":
        raise RuntimeError("native CDC table must be partitioned by occurred_at")
    if require_partition_filter and not table.require_partition_filter:
        raise RuntimeError("native CDC table must require a partition filter")
    clustering = table.clustering_fields or []
    if clustering[:3] != ["tenant_token", "subject_token", "event_type"]:
        raise RuntimeError("native CDC table clustering contract is invalid")


def native_tvf_sql(
    project: str,
    dataset: str,
    table: str,
    tvf: str,
    max_range_days: int,
) -> str:
    return f"""
    CREATE OR REPLACE TABLE FUNCTION `{project}.{dataset}.{tvf}`(
      p_start_date DATE,
      p_end_date DATE,
      p_grain STRING,
      p_tenant_token STRING,
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
          AND tenant_token = p_tenant_token
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


def create_native_contracts(
    project: str,
    region: str,
    dataset: str,
    table: str,
    tvf: str,
    max_range_days: int,
) -> None:
    client = bigquery.Client(project=project)
    table_ref = client.get_table(f"{project}.{dataset}.{table}")
    validate_native_table(table_ref, require_partition_filter=False)
    if not table_ref.require_partition_filter:
        table_ref.require_partition_filter = True
        table_ref = client.update_table(table_ref, ["require_partition_filter"])
    validate_native_table(table_ref)
    client.query(
        native_tvf_sql(project, dataset, table, tvf, max_range_days),
        location=region,
    ).result()


def main() -> None:
    if required("PHASE5_ACTIVE").lower() != "true":
        raise RuntimeError("native BigQuery provisioning is restricted to Phase 5")
    if required("ENABLE_DATASTREAM").lower() != "true":
        raise RuntimeError("native contracts require an explicitly activated CDC stream")
    create_native_contracts(
        required("GOOGLE_CLOUD_PROJECT"),
        required("REGION"),
        identifier("BIGQUERY_DATASET"),
        identifier("BIGQUERY_NATIVE_TABLE"),
        identifier("BIGQUERY_NATIVE_TVF"),
        int(required("ANALYTICS_MAX_RANGE_DAYS")),
    )
    print("[OK] Validated privacy-safe CDC table and installed native v3 TVF")


if __name__ == "__main__":
    main()
