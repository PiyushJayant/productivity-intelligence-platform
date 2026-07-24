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
    return violations
