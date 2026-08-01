from __future__ import annotations

import pytest

from setup import bigquery_setup


class CompletedQuery:
    def result(self):
        return []


class FakeClient:
    queries: list[tuple[str, str]] = []

    def __init__(self, *, project: str):
        self.project = project

    def create_dataset(self, dataset, *, exists_ok: bool):
        assert exists_ok is True
        return dataset

    def query(self, query: str, *, location: str):
        self.queries.append((query, location))
        return CompletedQuery()


def test_bounded_tenant_procedure_retires_unscoped_views(monkeypatch):
    FakeClient.queries.clear()
    monkeypatch.setattr(bigquery_setup.bigquery, "Client", FakeClient)

    bigquery_setup.create_analytics_contracts(
        "test-project",
        "us-central1",
        "productivity_analytics",
        "productivity_alloydb",
        "get_productivity_trends_v2",
        "Asia/Kolkata",
        730,
    )

    assert len(FakeClient.queries) == 2
    retired_views, _ = FakeClient.queries[0]
    assert "DROP VIEW IF EXISTS" in retired_views
    assert "task_summary" in retired_views and "daily_activity" in retired_views
    procedure, location = FakeClient.queries[-1]
    assert location == "us-central1"
    assert "CREATE OR REPLACE PROCEDURE" in procedure
    assert "get_productivity_trends_v2" in procedure
    assert "DATE_DIFF(p_end_date, p_start_date, DAY) + 1 > 730" in procedure
    assert "e.occurred_at >= b.start_at" in procedure
    assert "e.occurred_at < b.end_at" in procedure
    assert "p_tenant_id STRING" in procedure
    assert "p_subject_id STRING" in procedure
    assert "e.tenant_id = '%s'::uuid" in procedure
    assert '"SELECT * FROM EXTERNAL_QUERY(%T, %T)"' in procedure


@pytest.mark.parametrize(
    ("procedure", "timezone", "max_days", "message"),
    [
        ("unsafe-name", "Asia/Kolkata", 730, "SQL identifier"),
        ("safe_name", "bad-timezone", 730, "IANA timezone"),
        ("safe_name", "Asia/Kolkata", 0, "greater than zero"),
    ],
)
def test_bounded_procedure_configuration_is_validated(
    monkeypatch,
    procedure: str,
    timezone: str,
    max_days: int,
    message: str,
):
    monkeypatch.setattr(bigquery_setup.bigquery, "Client", FakeClient)

    with pytest.raises(ValueError, match=message):
        bigquery_setup.create_analytics_contracts(
            "test-project",
            "us-central1",
            "productivity_analytics",
            "productivity_alloydb",
            procedure,
            timezone,
            max_days,
        )
