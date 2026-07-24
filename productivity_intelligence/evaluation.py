"""Deterministic evaluation manifest and result validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from productivity_intelligence.response_validation import validate_visible_response

VALID_AGENTS = {"task_agent", "notes_agent", "calendar_agent", "analytics_agent"}


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    prompt: str
    expected_agent: str
    expected_tool: str
    requires_confirmation: bool


def load_evaluation_cases(path: Path) -> list[EvaluationCase]:
    """Load and validate the generic agent evaluation manifest."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("evaluation manifest must contain a non-empty cases list")

    cases: list[EvaluationCase] = []
    seen: set[str] = set()
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise ValueError("every evaluation case must be an object")
        required = {
            "id",
            "prompt",
            "expected_agent",
            "expected_tool",
            "requires_confirmation",
        }
        if set(raw) != required:
            raise ValueError(f"evaluation case fields must be exactly {sorted(required)}")
        case_id = str(raw["id"]).strip()
        if not case_id or case_id in seen:
            raise ValueError(f"evaluation case ID is missing or duplicated: {case_id!r}")
        expected_agent = str(raw["expected_agent"])
        if expected_agent not in VALID_AGENTS:
            raise ValueError(f"unknown expected agent: {expected_agent}")
        if not isinstance(raw["requires_confirmation"], bool):
            raise ValueError("requires_confirmation must be a boolean")
        prompt = str(raw["prompt"]).strip()
        expected_tool = str(raw["expected_tool"]).strip()
        if not prompt or not expected_tool:
            raise ValueError("prompt and expected_tool must be non-empty")
        seen.add(case_id)
        cases.append(
            EvaluationCase(
                case_id=case_id,
                prompt=prompt,
                expected_agent=expected_agent,
                expected_tool=expected_tool,
                requires_confirmation=raw["requires_confirmation"],
            )
        )
    return cases


def validate_evaluation_result(case: EvaluationCase, result: dict[str, Any]) -> list[str]:
    """Validate a captured live-agent result against its deterministic contract."""

    violations: list[str] = []
    if result.get("agent") != case.expected_agent:
        violations.append(
            f"expected agent {case.expected_agent}, got {result.get('agent')!r}"
        )
    tool_names = result.get("tools", [])
    if case.expected_tool not in tool_names:
        violations.append(f"expected tool {case.expected_tool} was not called")
    if case.requires_confirmation and result.get("mutation_executed") is True:
        violations.append("destructive mutation executed before explicit confirmation")
    response = result.get("response", "")
    if not isinstance(response, str):
        violations.append("response must be a string")
    else:
        violations.extend(validate_visible_response(case.expected_agent, response))
    return violations
