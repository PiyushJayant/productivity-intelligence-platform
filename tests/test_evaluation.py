from __future__ import annotations

from pathlib import Path

from productivity_intelligence.evaluation import (
    load_evaluation_cases,
    validate_evaluation_result,
)
from productivity_intelligence.response_contract import validate_visible_response
from productivity_intelligence.response_validation import validate_action_fidelity

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


def test_created_note_requires_preview_and_normalized_tags():
    violations = validate_visible_response(
        "notes_agent",
        "### Note created\nID: 2\nTitle: Application Logs\nTags:\n"
        "Created at: 2026-07-24T23:24:39.376539Z",
    )
    assert "response exposes empty labelled field" in violations
    assert "response exposes raw UTC timestamp" in violations
    assert "created note response is missing a content preview" in violations
    assert "created note response is missing a normalized tag value" in violations

    assert (
        validate_visible_response(
            "notes_agent",
            "### Note created\nID: 2\nTitle: Application Logs\n"
            "Preview: Capture structured application events.\nTags: No tags",
        )
        == []
    )


def test_action_fidelity_detects_a_dropped_deadline_time():
    violations = validate_action_fidelity(
        {"title": "suspend application", "due_at": "2026-07-25T10:30:00Z"},
        {"title": "suspend application", "due_date": "2026-07-25"},
    )
    assert violations == ["confirmed action dropped requested field: due_at"]


def test_ambiguous_evaluation_blocks_mutation():
    cases = load_evaluation_cases(ROOT / "tests" / "eval_cases.json")
    case = next(item for item in cases if item.case_id == "session_44_ambiguous_note")
    violations = validate_evaluation_result(
        case,
        {
            "agent": "notes_agent",
            "tools": ["create_note"],
            "mutation_executed": True,
            "clarification_requested": False,
            "response": "### Note created\nPreview: Create logs.\nTags: No tags",
        },
    )
    assert "forbidden tool create_note was called" in violations
    assert "mutation executed before resolving an ambiguous request" in violations
