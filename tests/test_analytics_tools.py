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
    def result(self):
        return [FakeRow()]


class FakeClient:
    calls = []

    def __init__(self, *, project):
        self.project = project

    def query(self, query, *, job_config):
        self.calls.append((query, job_config))
        return FakeQuery()


def test_productivity_trends_use_one_parameterized_weighted_query(monkeypatch):
    FakeClient.calls.clear()
    monkeypatch.setattr(analytics_tools.bigquery, "Client", FakeClient)

    result = json.loads(
        analytics_tools.get_productivity_trends(
            "2026-07-01", "2026-07-31", "month"
        )
    )

    assert len(FakeClient.calls) == 1
    query, job_config = FakeClient.calls[0]
    assert "SAFE_DIVIDE(task.completed_tasks, task.total_tasks)" in query
    assert "AVG(completion_rate)" not in query
    assert "@start_date" in query and "@end_date" in query
    assert len(job_config.query_parameters) == 2
    assert result["rows"][0]["completion_rate"] == 0.6667


@pytest.mark.parametrize(
    ("start", "end", "grain", "message"),
    [
        ("bad", "2026-07-31", "month", "YYYY-MM-DD"),
        ("2026-08-01", "2026-07-31", "month", "before"),
        ("2026-07-01", "2026-07-31", "year", "grain"),
    ],
)
def test_productivity_trends_reject_invalid_parameters(start, end, grain, message):
    with pytest.raises(ValueError, match=message):
        analytics_tools.get_productivity_trends(start, end, grain)
