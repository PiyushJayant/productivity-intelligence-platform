"""Runtime-independent validation for final user-visible responses."""

from __future__ import annotations

import re

FORBIDDEN_VISIBLE_PATTERNS = {
    "standalone internal event number": re.compile(r"(?m)^\s*#\d+\s*$"),
    "function-call internals": re.compile(
        r"\b(?:function_call|functionCall|thought_signature|thoughtSignature|invocationId)\b",
        re.IGNORECASE,
    ),
    "agent transfer internals": re.compile(
        r"\b(?:transfer_to_agent|called tool|tool returned result)\b",
        re.IGNORECASE,
    ),
    "synthetic context wrapper": re.compile(r"(?m)^\s*For context:\s*$", re.IGNORECASE),
    "empty labelled field": re.compile(
        r"(?m)^\s*(?:Tags|Title|Task|Description|Date|Time|Content preview):\s*$",
        re.IGNORECASE,
    ),
    "placeholder labelled value": re.compile(
        r"(?mi)^\s*(?:Tags|Title|Task|Description|Date|Time|Content preview):"
        r"\s*(?:None|null)\s*$"
    ),
    "raw UTC timestamp": re.compile(
        r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\b"
    ),
}

AGENT_HEADING_PATTERNS = {
    "task_agent": re.compile(r"(?m)^### Task(?:s| created| updated| deleted)\s*$"),
    "notes_agent": re.compile(r"(?m)^### Note(?:s| created| deleted)\s*$"),
    "calendar_agent": re.compile(
        r"(?m)^### (?:Calendar events|Event scheduled|Event deleted)\s*$"
    ),
    "analytics_agent": re.compile(r"(?m)^### Productivity analytics\s*$"),
}


def validate_visible_response(agent_name: str, response: str) -> list[str]:
    """Return deterministic contract violations for a final chat response."""

    violations: list[str] = []
    if not response.strip():
        return ["final response is empty after tool execution"]
    for description, pattern in FORBIDDEN_VISIBLE_PATTERNS.items():
        if pattern.search(response):
            violations.append(f"response exposes {description}")
    heading = AGENT_HEADING_PATTERNS.get(agent_name)
    if heading is not None and not heading.search(response):
        violations.append(f"response is missing the required {agent_name} heading")
    if agent_name == "notes_agent" and "### Note created" in response:
        if not re.search(
            r"(?mi)^[ \t]*(?:Content preview|Preview):[ \t]*\S", response
        ):
            violations.append("created note response is missing a content preview")
        if not re.search(r"(?mi)^[ \t]*Tags:[ \t]*\S", response):
            violations.append("created note response is missing a normalized tag value")
    return violations


def validate_action_fidelity(
    requested: dict[str, object],
    confirmed: dict[str, object],
) -> list[str]:
    """Return requested material fields absent from a confirmed mutation."""

    violations: list[str] = []
    for field, value in requested.items():
        if value is None or value == "":
            continue
        confirmed_value = confirmed.get(field)
        if confirmed_value is None or confirmed_value == "":
            violations.append(f"confirmed action dropped requested field: {field}")
    return violations
