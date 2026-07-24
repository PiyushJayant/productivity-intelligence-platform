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
    forbidden_tools: tuple[str, ...] = ()
    requires_clarification: bool = False


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
        optional = {"forbidden_tools", "requires_clarification"}
        if not required <= set(raw) or not set(raw) <= required | optional:
            raise ValueError(
                "evaluation case fields must contain required fields and only "
                f"supported optional fields: {sorted(required | optional)}"
            )
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
        forbidden_tools = tuple(str(tool).strip() for tool in raw.get("forbidden_tools", []))
        requires_clarification = raw.get("requires_clarification", False)
        if not isinstance(requires_clarification, bool):
            raise ValueError("requires_clarification must be a boolean")
        if not prompt:
            raise ValueError("prompt must be non-empty")
        if not expected_tool and not requires_clarification:
            raise ValueError("expected_tool may be empty only for a clarification case")
        if any(not tool for tool in forbidden_tools):
            raise ValueError("forbidden_tools must contain non-empty names")
        seen.add(case_id)
        cases.append(
            EvaluationCase(
                case_id=case_id,
                prompt=prompt,
                expected_agent=expected_agent,
                expected_tool=expected_tool,
                requires_confirmation=raw["requires_confirmation"],
                forbidden_tools=forbidden_tools,
                requires_clarification=requires_clarification,
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
    if case.expected_tool and case.expected_tool not in tool_names:
        violations.append(f"expected tool {case.expected_tool} was not called")
    for forbidden_tool in case.forbidden_tools:
        if forbidden_tool in tool_names:
            violations.append(f"forbidden tool {forbidden_tool} was called")
    if case.requires_confirmation and result.get("mutation_executed") is True:
        violations.append("destructive mutation executed before explicit confirmation")
    if case.requires_clarification and result.get("mutation_executed") is True:
        violations.append("mutation executed before resolving an ambiguous request")
    if case.requires_clarification and not result.get("clarification_requested"):
        violations.append("expected one concise clarification question")
    response = result.get("response", "")
    if not isinstance(response, str):
        violations.append("response must be a string")
    else:
        violations.extend(validate_visible_response(case.expected_agent, response))
    return violations
