from __future__ import annotations

from pathlib import Path

from productivity_intelligence.evaluation import (
    load_evaluation_cases,
    validate_evaluation_result,
)
from productivity_intelligence.response_contract import validate_visible_response

ROOT = Path(__file__).parents[1]


def test_evaluation_manifest_covers_every_agent_and_destructive_confirmation():
    cases = load_evaluation_cases(ROOT / "tests" / "eval_cases.json")
    assert {case.expected_agent for case in cases} == {
        "task_agent",
        "notes_agent",
        "calendar_agent",
        "analytics_agent",
    }
    assert {case.expected_agent for case in cases if case.requires_confirmation} == {
        "task_agent",
        "notes_agent",
        "calendar_agent",
    }


def test_visible_response_rejects_internal_events_and_tool_only_results():
    assert validate_visible_response("notes_agent", "") == [
        "final response is empty after tool execution"
    ]
    violations = validate_visible_response(
        "notes_agent",
        "#54\nFor context:\nfunctionCall search_notes_semantic",
    )
    assert len(violations) >= 4


def test_captured_result_contract_accepts_a_structured_response():
    case = load_evaluation_cases(ROOT / "tests" / "eval_cases.json")[4]
    result = {
        "agent": "notes_agent",
        "tools": ["search_notes_semantic"],
        "mutation_executed": False,
        "response": "### Notes\n\n1. **Access controls** (ID: 4)\n   - **Preview:** Review IAM.",
    }
    assert validate_evaluation_result(case, result) == []
