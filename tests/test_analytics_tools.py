from __future__ import annotations

import json

import pytest

from productivity_intelligence import analytics_tools


class FakeRow:
    def items(self):
        return {
            "period": "2026-07",
            "total_tasks": 3,
            "completed_tasks": 2,
            "completion_rate": 2 / 3,
        }.items()


class FakeQuery:
    def result(self, *, timeout):
        assert timeout == 30
        return [FakeRow()]


class FakeClient:
    calls = []

    def __init__(self, *, project):
        self.project = project

    def query(self, query, *, job_config, location):
        self.calls.append((query, job_config, location))
        return FakeQuery()


class TimeoutQuery:
    def result(self, *, timeout):
        raise TimeoutError


class TimeoutClient:
    def __init__(self, *, project):
        self.project = project

    def query(self, query, *, job_config, location):
        return TimeoutQuery()


def test_productivity_trends_call_one_parameterized_bounded_procedure(monkeypatch):
    FakeClient.calls.clear()
    monkeypatch.setattr(analytics_tools.bigquery, "Client", FakeClient)
    monkeypatch.setattr(
        analytics_tools,
        "current_tenant_id",
        lambda: "11111111-1111-4111-8111-111111111111",
    )
    monkeypatch.setattr(
        analytics_tools,
        "current_subject_id",
        lambda: "22222222-2222-4222-8222-222222222222",
    )

    result = json.loads(
        analytics_tools.get_productivity_trends(
            "2026-07-01", "2026-07-31", "month"
        )
    )

    assert len(FakeClient.calls) == 1
    query, job_config, location = FakeClient.calls[0]
    assert (
        query
        == "CALL `test-project.productivity_analytics."
        "get_productivity_trends_v2`"
        "(@start_date, @end_date, @grain, @tenant_id, @subject_id)"
    )
    assert "@start_date" in query and "@end_date" in query
    assert len(job_config.query_parameters) == 5
    assert job_config.query_parameters[-2].value == (
        "11111111-1111-4111-8111-111111111111"
    )
    assert job_config.query_parameters[-1].value == (
        "22222222-2222-4222-8222-222222222222"
    )
    assert int(job_config.job_timeout_ms) == 30_000
    assert location == "us-central1"
    assert result["contract_version"] == "v2"
    assert result["rows"][0]["completion_rate"] == 0.6667


@pytest.mark.parametrize(
    ("start", "end", "grain", "message"),
    [
        ("bad", "2026-07-31", "month", "YYYY-MM-DD"),
        ("2026-08-01", "2026-07-31", "month", "before"),
        ("2026-07-01", "2026-07-31", "year", "grain"),
        ("2020-01-01", "2026-07-31", "month", "configured maximum"),
    ],
)
def test_productivity_trends_reject_invalid_parameters(start, end, grain, message):
    with pytest.raises(ValueError, match=message):
        analytics_tools.get_productivity_trends(start, end, grain)


def test_productivity_trends_hide_dependency_timeout(monkeypatch):
    monkeypatch.setattr(analytics_tools.bigquery, "Client", TimeoutClient)
    monkeypatch.setattr(
        analytics_tools,
        "current_tenant_id",
        lambda: "11111111-1111-4111-8111-111111111111",
    )
    monkeypatch.setattr(
        analytics_tools,
        "current_subject_id",
        lambda: "22222222-2222-4222-8222-222222222222",
    )

    with pytest.raises(
        analytics_tools.AnalyticsUnavailableError,
        match="temporarily unavailable",
    ) as failure:
        analytics_tools.get_productivity_trends(
            "2026-07-01", "2026-07-31", "month"
        )

    assert "Timeout" not in str(failure.value)
