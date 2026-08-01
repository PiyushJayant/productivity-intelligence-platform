"""Deterministic, read-only productivity analytics tools."""

from __future__ import annotations

import json
import logging
from datetime import date

from google.api_core.exceptions import (
    DeadlineExceeded,
    GatewayTimeout,
    GoogleAPICallError,
    InternalServerError,
    ResourceExhausted,
    ServiceUnavailable,
    TooManyRequests,
)
from google.cloud import bigquery

from productivity_intelligence.config import settings
from productivity_intelligence.identity import (
    current_subject_id,
    current_subject_token,
    current_tenant_id,
    current_tenant_token,
)
from productivity_intelligence.resilience import retry_with_backoff

VALID_GRAINS = {"day", "month"}
TRANSIENT_BIGQUERY_ERRORS = (
    DeadlineExceeded,
    GatewayTimeout,
    InternalServerError,
    ResourceExhausted,
    ServiceUnavailable,
    TooManyRequests,
    TimeoutError,
)
LOGGER = logging.getLogger(__name__)


class AnalyticsUnavailableError(RuntimeError):
    """Safe, user-facing analytics dependency failure."""


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
    range_days = (end - start).days + 1
    if range_days > settings.analytics_max_range_days:
        raise ValueError(
            "requested period exceeds the configured maximum of "
            f"{settings.analytics_max_range_days} days"
        )
    if grain not in VALID_GRAINS:
        raise ValueError(f"grain must be one of {sorted(VALID_GRAINS)}")

    dataset = f"{settings.google_cloud_project}.{settings.bigquery_dataset}"
    if settings.analytics_backend == "federated":
        query = (
            f"CALL `{dataset}.{settings.bigquery_analytics_procedure}`"
            "(@start_date, @end_date, @grain, @tenant_id, @subject_id)"
        )
    else:
        query = (
            f"SELECT * FROM `{dataset}.{settings.bigquery_native_tvf}`"
            "(@start_date, @end_date, @grain, @tenant_token, @subject_token)"
        )
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start),
            bigquery.ScalarQueryParameter("end_date", "DATE", end),
            bigquery.ScalarQueryParameter("grain", "STRING", grain),
            bigquery.ScalarQueryParameter(
                "tenant_id" if settings.analytics_backend == "federated"
                else "tenant_token",
                "STRING",
                current_tenant_id()
                if settings.analytics_backend == "federated"
                else current_tenant_token(),
            ),
            bigquery.ScalarQueryParameter(
                "subject_id" if settings.analytics_backend == "federated"
                else "subject_token",
                "STRING",
                current_subject_id() if settings.analytics_backend == "federated"
                else current_subject_token(),
            ),
        ]
    )
    job_config.job_timeout_ms = settings.analytics_query_timeout_seconds * 1000
    job_config.maximum_bytes_billed = settings.analytics_max_bytes_billed
    job_config.labels = {
        "application": "productivity-intelligence",
        "component": "analytics-agent",
        "backend": settings.analytics_backend,
        "contract": (
            "v2" if settings.analytics_backend == "federated" else "v3"
        ),
    }
    client = bigquery.Client(project=settings.google_cloud_project)
    job = None
    try:
        def execute_query():
            nonlocal job
            if job is None:
                job = client.query(
                    query,
                    job_config=job_config,
                    location=settings.region,
                )
            return job.result(
                timeout=settings.analytics_query_timeout_seconds,
                max_results=range_days + 1,
            )

        result = retry_with_backoff(
            execute_query,
            attempts=settings.analytics_retry_attempts,
            base_seconds=settings.analytics_retry_base_seconds,
            max_seconds=settings.analytics_retry_max_seconds,
            retryable=TRANSIENT_BIGQUERY_ERRORS,
        )
        rows = [
            {
                key: (round(value, 4) if isinstance(value, float) else value)
                for key, value in dict(row.items()).items()
            }
            for row in result
        ]
        if len(rows) > range_days:
            raise AnalyticsUnavailableError(
                "Productivity analytics returned an invalid result shape."
            )
    except AnalyticsUnavailableError:
        raise
    except (GoogleAPICallError, TimeoutError) as error:
        LOGGER.warning(
            "Bounded productivity analytics query failed",
            extra={"analytics_backend": settings.analytics_backend},
        )
        raise AnalyticsUnavailableError(
            "Productivity analytics is temporarily unavailable. Please retry shortly."
        ) from error
    return json.dumps(
        {
            "contract_version": (
                "v2" if settings.analytics_backend == "federated" else "v3"
            ),
            "backend": settings.analytics_backend,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "grain": grain,
            "rows": rows,
        },
        separators=(",", ":"),
    )
