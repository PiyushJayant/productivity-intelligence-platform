from __future__ import annotations

import json
from datetime import date

import pytest

from productivity_intelligence.date_tools import _resolve_date, resolve_relative_date


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("today", "2026-07-23"),
        ("tomorrow", "2026-07-24"),
        ("Friday", "2026-07-24"),
        ("next Friday", "2026-07-31"),
        ("in 2 weeks", "2026-08-06"),
        ("2026-12-05", "2026-12-05"),
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
