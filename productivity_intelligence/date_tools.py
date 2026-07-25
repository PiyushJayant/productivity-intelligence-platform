"""Deterministic date resolution tools shared by task and calendar agents."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, time, timedelta
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
MONTHS = {
    name: number
    for number, name in enumerate(
        (
            "",
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        )
    )
    if name
}


def _resolve_date(expression: str, *, today: date) -> tuple[date, str]:
    normalized = re.sub(r"\s+", " ", expression.strip().lower())
    normalized = re.sub(r"^(?:by|on|at)\s+", "", normalized)

    try:
        return date.fromisoformat(normalized), "explicit ISO date"
    except ValueError:
        pass

    named_date = re.fullmatch(
        r"(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(january|february|march|april|may|june|july|august|september|"
        r"october|november|december)(?:\s+(\d{4}))?",
        normalized,
    )
    month_first_date = re.fullmatch(
        r"(january|february|march|april|may|june|july|august|september|"
        r"october|november|december)\s+"
        r"(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?",
        normalized,
    )
    named_parts = named_date.groups() if named_date else None
    if month_first_date is not None:
        month_name, day, explicit_year = month_first_date.groups()
        named_parts = (day, month_name, explicit_year)
    if named_parts is not None:
        day, month_name, explicit_year = named_parts
        year = int(explicit_year) if explicit_year else today.year
        try:
            resolved = date(year, MONTHS[month_name], int(day))
        except ValueError as error:
            raise ValueError("named date is not a valid calendar date") from error
        if explicit_year is None and resolved < today:
            resolved = resolved.replace(year=year + 1)
        return resolved, "explicit named date"

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


def _parse_clock(hour: int, minute: int, meridiem: str | None) -> time:
    if minute > 59:
        raise ValueError("minutes must be between 00 and 59")
    if meridiem:
        if not 1 <= hour <= 12:
            raise ValueError("12-hour times must use an hour from 1 to 12")
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    elif not 0 <= hour <= 23:
        raise ValueError("24-hour times must use an hour from 00 to 23")
    return time(hour, minute)


def _resolve_datetime(expression: str, *, today: date) -> tuple[date, time, str]:
    normalized = re.sub(r"\s+", " ", expression.strip().lower())
    time_first = re.fullmatch(
        r"(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s+(?:on\s+)?(.+)",
        normalized,
    )
    if time_first:
        hour, minute, meridiem, date_expression = time_first.groups()
        resolved_date, date_interpretation = _resolve_date(date_expression, today=today)
        resolved_time = _parse_clock(int(hour), int(minute or "0"), meridiem)
        return resolved_date, resolved_time, f"{date_interpretation} at {resolved_time:%H:%M}"

    time_first_24h = re.fullmatch(
        r"(?:at\s+)?(\d{1,2}):(\d{2})\s+(?:on\s+)?(.+)",
        normalized,
    )
    if time_first_24h:
        hour, minute, date_expression = time_first_24h.groups()
        resolved_date, date_interpretation = _resolve_date(date_expression, today=today)
        resolved_time = _parse_clock(int(hour), int(minute), None)
        return resolved_date, resolved_time, f"{date_interpretation} at {resolved_time:%H:%M}"

    match = re.fullmatch(
        r"(.+?)\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
        normalized,
    )
    if match:
        date_expression, hour, minute, meridiem = match.groups()
        resolved_date, date_interpretation = _resolve_date(date_expression, today=today)
        resolved_time = _parse_clock(int(hour), int(minute or "0"), meridiem)
        return resolved_date, resolved_time, f"{date_interpretation} at {resolved_time:%H:%M}"

    match = re.fullmatch(r"(.+?)\s+at\s+(\d{1,2}):(\d{2})", normalized)
    if match:
        date_expression, hour, minute = match.groups()
        resolved_date, date_interpretation = _resolve_date(date_expression, today=today)
        resolved_time = _parse_clock(int(hour), int(minute), None)
        return resolved_date, resolved_time, f"{date_interpretation} at {resolved_time:%H:%M}"

    match = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2})[t ](\d{1,2}):(\d{2})",
        normalized,
    )
    if match:
        date_expression, hour, minute = match.groups()
        resolved_date, _ = _resolve_date(date_expression, today=today)
        resolved_time = _parse_clock(int(hour), int(minute), None)
        return resolved_date, resolved_time, "explicit local date and time"

    if re.fullmatch(r".+?\s+at\s+\d{1,2}(?::\d{2})?", normalized):
        raise ValueError(
            "time is ambiguous; include AM or PM, or use 24-hour HH:MM format"
        )
    raise ValueError(
        "unsupported date-time expression; use a relative date with a time "
        "(for example, tomorrow at 4 PM) or YYYY-MM-DD HH:MM"
    )


def resolve_relative_datetime(expression: str) -> str:
    """Resolve a local date-time expression without guessing an ambiguous clock time.

    Args:
        expression: A phrase such as "today at 4 PM", "next Friday at 09:30 AM",
            or "2026-07-25 16:00".

    Returns:
        Compact JSON containing the resolved local date/time, configured timezone,
        and an RFC 3339 UTC instant suitable for a TIMESTAMPTZ database field.
    """

    timezone = ZoneInfo(settings.default_timezone)
    today = datetime.now(timezone).date()
    try:
        resolved_date, resolved_time, interpretation = _resolve_datetime(
            expression, today=today
        )
        local_datetime = datetime.combine(
            resolved_date, resolved_time, tzinfo=timezone
        )
        result = {
            "status": "resolved",
            "date": resolved_date.isoformat(),
            "time": resolved_time.strftime("%H:%M"),
            "timezone": settings.default_timezone,
            "local_datetime": local_datetime.isoformat(),
            "utc_datetime": local_datetime.astimezone(UTC).isoformat().replace(
                "+00:00", "Z"
            ),
            "interpretation": interpretation,
        }
    except ValueError as error:
        result = {
            "status": "clarification_required",
            "timezone": settings.default_timezone,
            "message": str(error),
        }
    return json.dumps(result, separators=(",", ":"))


def _subtract_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    return date(month_index // 12, month_index % 12 + 1, 1)


def _quarter_start(value: date) -> date:
    return date(value.year, ((value.month - 1) // 3) * 3 + 1, 1)


def resolve_reporting_period(expression: str) -> str:
    """Resolve a reporting-period phrase to an inclusive date range and grain.

    Args:
        expression: A period such as "last 7 days", "rolling 12 months",
            "this month", "previous calendar year", or
            "2026-01-01 to 2026-07-25".

    Returns:
        JSON with resolved start/end dates and a recommended day/month grain.
        The phrase "last year" intentionally requests clarification because it
        can mean either a rolling year or the previous calendar year.
    """

    timezone = ZoneInfo(settings.default_timezone)
    today = datetime.now(timezone).date()
    normalized = re.sub(r"\s+", " ", expression.strip().lower())
    try:
        if normalized == "last year":
            raise ValueError(
                'say "rolling 12 months" or "previous calendar year"'
            )
        if normalized == "rolling 12 months":
            start = _subtract_months(today.replace(day=1), 11)
            end, grain = today, "month"
        elif normalized == "previous calendar year":
            start = date(today.year - 1, 1, 1)
            end, grain = date(today.year - 1, 12, 31), "month"
        elif normalized == "this year":
            start, end, grain = date(today.year, 1, 1), today, "month"
        elif normalized == "this month":
            start, end, grain = today.replace(day=1), today, "day"
        elif normalized == "last month":
            start = _subtract_months(today.replace(day=1), 1)
            end = today.replace(day=1) - timedelta(days=1)
            grain = "day"
        elif normalized == "this quarter":
            start, end, grain = _quarter_start(today), today, "month"
        elif normalized in {"last quarter", "previous calendar quarter"}:
            current_quarter = _quarter_start(today)
            start = _subtract_months(current_quarter, 3)
            end, grain = current_quarter - timedelta(days=1), "month"
        elif normalized == "this week":
            start, end, grain = today - timedelta(days=today.weekday()), today, "day"
        elif match := re.fullmatch(r"last (\d{1,3}) (day|days|week|weeks)", normalized):
            count = int(match.group(1))
            if count < 1 or count > 365:
                raise ValueError("reporting periods must be between 1 and 365 days")
            days = count * (7 if match.group(2).startswith("week") else 1)
            start, end = today - timedelta(days=days - 1), today
            grain = "day" if days <= 31 else "month"
        elif match := re.fullmatch(r"last (\d{1,2}) (month|months)", normalized):
            count = int(match.group(1))
            if count < 1 or count > 24:
                raise ValueError("reporting periods must be between 1 and 24 months")
            start = _subtract_months(today.replace(day=1), count - 1)
            end, grain = today, "month"
        elif match := re.fullmatch(
            r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})",
            normalized,
        ):
            start, end = date.fromisoformat(match.group(1)), date.fromisoformat(
                match.group(2)
            )
            if end < start:
                raise ValueError("reporting end date must not be before its start date")
            grain = "day" if (end - start).days <= 31 else "month"
        else:
            raise ValueError(
                "use last N days/weeks/months, last month/quarter, "
                "this week/month/quarter/year, rolling 12 months, "
                "previous calendar year, or an ISO date range"
            )
        result = {
            "status": "resolved",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "grain": grain,
            "timezone": settings.default_timezone,
            "interpretation": normalized,
        }
    except ValueError as error:
        result = {
            "status": "clarification_required",
            "timezone": settings.default_timezone,
            "message": str(error),
        }
    return json.dumps(result, separators=(",", ":"))
