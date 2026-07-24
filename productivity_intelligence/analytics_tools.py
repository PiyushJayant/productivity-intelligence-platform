"""Deterministic, read-only productivity analytics tools."""

from __future__ import annotations

import json
from datetime import date

from google.cloud import bigquery

from productivity_intelligence.config import settings

VALID_GRAINS = {"day", "month"}


def _iso_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must use YYYY-MM-DD format") from error


def get_productivity_trends(
    start_date: str,
    end_date: str,
    grain: str,
) -> str:
    """Return live task and activity trends from the approved BigQuery views.

    This is the only analytics query exposed to the model. It uses fixed,
    parameterized, read-only SQL and computes an aggregate completion rate from
    summed counts rather than averaging percentages.

    Args:
        start_date: Inclusive reporting start date in YYYY-MM-DD format.
        end_date: Inclusive reporting end date in YYYY-MM-DD format.
        grain: Result grouping: "day" or "month".

    Returns:
        JSON containing the confirmed period, grain, and chronological rows.
    """

    start = _iso_date(start_date, "start_date")
    end = _iso_date(end_date, "end_date")
    if end < start:
        raise ValueError("end_date must not be before start_date")
    if grain not in VALID_GRAINS:
        raise ValueError(f"grain must be one of {sorted(VALID_GRAINS)}")

    trunc_part = "DAY" if grain == "day" else "MONTH"
    period_format = "%Y-%m-%d" if grain == "day" else "%Y-%m"
    dataset = f"{settings.google_cloud_project}.{settings.bigquery_dataset}"
    query = f"""
    WITH task AS (
      SELECT
        DATE_TRUNC(date, {trunc_part}) AS period,
        SUM(total_tasks) AS total_tasks,
        SUM(completed_tasks) AS completed_tasks,
        SUM(pending_tasks) AS pending_tasks,
        SUM(in_progress_tasks) AS in_progress_tasks
      FROM `{dataset}.task_summary`
      WHERE date BETWEEN @start_date AND @end_date
      GROUP BY period
    ),
    activity AS (
      SELECT
        DATE_TRUNC(date, {trunc_part}) AS period,
        SUM(tasks_created) AS tasks_created,
        SUM(tasks_completed) AS tasks_completed,
        SUM(notes_created) AS notes_created,
        SUM(events_scheduled) AS events_scheduled
      FROM `{dataset}.daily_activity`
      WHERE date BETWEEN @start_date AND @end_date
      GROUP BY period
    )
    SELECT
      FORMAT_DATE('{period_format}', COALESCE(task.period, activity.period)) AS period,
      COALESCE(task.total_tasks, 0) AS total_tasks,
      COALESCE(task.completed_tasks, 0) AS completed_tasks,
      COALESCE(task.pending_tasks, 0) AS pending_tasks,
      COALESCE(task.in_progress_tasks, 0) AS in_progress_tasks,
      SAFE_DIVIDE(task.completed_tasks, task.total_tasks) AS completion_rate,
      COALESCE(activity.tasks_created, 0) AS tasks_created,
      COALESCE(activity.tasks_completed, 0) AS tasks_completed,
      COALESCE(activity.notes_created, 0) AS notes_created,
      COALESCE(activity.events_scheduled, 0) AS events_scheduled
    FROM task
    FULL OUTER JOIN activity USING (period)
    ORDER BY period
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start),
            bigquery.ScalarQueryParameter("end_date", "DATE", end),
        ]
    )
    rows = [
        {
            key: (round(value, 4) if isinstance(value, float) else value)
            for key, value in dict(row.items()).items()
        }
        for row in bigquery.Client(
            project=settings.google_cloud_project
        ).query(query, job_config=job_config).result()
    ]
    return json.dumps(
        {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "grain": grain,
            "rows": rows,
        },
        separators=(",", ":"),
    )
