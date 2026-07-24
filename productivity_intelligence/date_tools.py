"""Deterministic date resolution tools shared by task and calendar agents."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from productivity_intelligence.config import settings

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _resolve_date(expression: str, *, today: date) -> tuple[date, str]:
    normalized = re.sub(r"\s+", " ", expression.strip().lower())
    normalized = re.sub(r"^(?:by|on|at)\s+", "", normalized)

    try:
        return date.fromisoformat(normalized), "explicit ISO date"
    except ValueError:
        pass

    fixed_offsets = {
        "today": (0, "today"),
        "tomorrow": (1, "tomorrow"),
        "day after tomorrow": (2, "the day after tomorrow"),
        "yesterday": (-1, "yesterday"),
    }
    if normalized in fixed_offsets:
        offset, label = fixed_offsets[normalized]
        return today + timedelta(days=offset), label

    offset_match = re.fullmatch(r"in (\d{1,3}) (day|days|week|weeks)", normalized)
    if offset_match:
        count = int(offset_match.group(1))
        if count > 365:
            raise ValueError("relative offsets cannot exceed 365 days")
        unit = offset_match.group(2)
        days = count * (7 if unit.startswith("week") else 1)
        return today + timedelta(days=days), normalized

    weekday_match = re.fullmatch(
        r"(?:(this|next)\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
        normalized,
    )
    if weekday_match:
        qualifier, weekday_name = weekday_match.groups()
        target_weekday = WEEKDAYS[weekday_name]
        days_ahead = (target_weekday - today.weekday()) % 7
        if qualifier == "next":
            days_ahead = days_ahead + 7 if days_ahead else 7
        return today + timedelta(days=days_ahead), normalized

    raise ValueError(
        "unsupported or ambiguous date expression; use today, tomorrow, "
        "a weekday, next weekday, in N days/weeks, or YYYY-MM-DD"
    )


def resolve_relative_date(expression: str) -> str:
    """Resolve a relative date before creating a task or calendar event.

    Args:
        expression: User-provided date phrase such as "tomorrow", "Friday",
            "next Tuesday", "in 2 weeks", or an ISO date like "2026-07-24".

    Returns:
        A JSON string with status, resolved ISO date, timezone, and a concise
        interpretation. If resolution fails, status is "clarification_required"
        and the message explains the accepted formats. Never guess after an error.
    """

    timezone = ZoneInfo(settings.default_timezone)
    today = datetime.now(timezone).date()
    try:
        resolved, interpretation = _resolve_date(expression, today=today)
        result = {
            "status": "resolved",
            "date": resolved.isoformat(),
            "timezone": settings.default_timezone,
            "interpretation": interpretation,
        }
    except ValueError as error:
        result = {
            "status": "clarification_required",
            "timezone": settings.default_timezone,
            "message": str(error),
        }
    return json.dumps(result, separators=(",", ":"))
