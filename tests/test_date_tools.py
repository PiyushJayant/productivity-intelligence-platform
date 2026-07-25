from __future__ import annotations

import json
from datetime import date

import pytest

from productivity_intelligence.date_tools import (
    _resolve_date,
    _resolve_datetime,
    resolve_relative_date,
    resolve_relative_datetime,
    resolve_reporting_period,
)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("today", "2026-07-23"),
        ("tomorrow", "2026-07-24"),
        ("Friday", "2026-07-24"),
        ("next Friday", "2026-07-31"),
        ("in 2 weeks", "2026-08-06"),
        ("2026-12-05", "2026-12-05"),
        ("26th July", "2026-07-26"),
        ("July 26, 2026", "2026-07-26"),
        ("1 January", "2027-01-01"),
    ],
)
def test_resolve_supported_date_expressions(expression, expected):
    resolved, _ = _resolve_date(expression, today=date(2026, 7, 23))
    assert resolved.isoformat() == expected


def test_ambiguous_date_requires_clarification():
    with pytest.raises(ValueError, match="ambiguous"):
        _resolve_date("sometime soon", today=date(2026, 7, 23))


def test_public_date_tool_returns_structured_error():
    result = json.loads(resolve_relative_date("whenever"))
    assert result["status"] == "clarification_required"
    assert result["timezone"] == "Asia/Kolkata"


@pytest.mark.parametrize(
    ("expression", "expected_date", "expected_time"),
    [
        ("today at 4 PM", "2026-07-23", "16:00"),
        ("tomorrow at 09:30 am", "2026-07-24", "09:30"),
        ("next Friday at 16:45", "2026-07-31", "16:45"),
        ("2026-12-05 14:00", "2026-12-05", "14:00"),
        ("2 pm tomorrow", "2026-07-24", "14:00"),
        ("at 2 pm tomorrow", "2026-07-24", "14:00"),
        ("14:30 next Friday", "2026-07-31", "14:30"),
    ],
)
def test_resolve_supported_datetime_expressions(
    expression, expected_date, expected_time
):
    resolved_date, resolved_time, _ = _resolve_datetime(
        expression, today=date(2026, 7, 23)
    )
    assert resolved_date.isoformat() == expected_date
    assert resolved_time.strftime("%H:%M") == expected_time


def test_bare_hour_requires_only_am_pm_clarification():
    with pytest.raises(ValueError, match="AM or PM"):
        _resolve_datetime("today at 4", today=date(2026, 7, 23))

    result = json.loads(resolve_relative_datetime("today at 4"))
    assert result["status"] == "clarification_required"
    assert "AM or PM" in result["message"]


def test_last_year_requires_explicit_reporting_semantics():
    result = json.loads(resolve_reporting_period("last year"))
    assert result["status"] == "clarification_required"
    assert "rolling 12 months" in result["message"]


@pytest.mark.parametrize(
    ("expression", "expected_start", "expected_end", "expected_grain"),
    [
        ("last month", "2026-06-01", "2026-06-30", "day"),
        ("this quarter", "2026-07-01", "2026-07-23", "month"),
        ("last quarter", "2026-04-01", "2026-06-30", "month"),
    ],
)
def test_reporting_period_supports_calendar_business_ranges(
    monkeypatch, expression, expected_start, expected_end, expected_grain
):
    from productivity_intelligence import date_tools

    class FixedDateTime:
        @staticmethod
        def now(_timezone):
            from datetime import datetime

            return datetime(2026, 7, 23, 12)

    monkeypatch.setattr(date_tools, "datetime", FixedDateTime)
    result = json.loads(resolve_reporting_period(expression))
    assert result["status"] == "resolved"
    assert result["start_date"] == expected_start
    assert result["end_date"] == expected_end
    assert result["grain"] == expected_grain
