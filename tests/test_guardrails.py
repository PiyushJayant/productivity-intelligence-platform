from types import SimpleNamespace

from productivity_intelligence.guardrails import enforce_destructive_confirmation


def content(text: str):
    return SimpleNamespace(parts=[SimpleNamespace(text=text)])


def context(*messages: str):
    events = [
        SimpleNamespace(author="user", content=content(message))
        for message in messages
    ]
    return SimpleNamespace(
        session=SimpleNamespace(events=events),
        user_content=content(messages[-1]),
    )


def tool(name: str):
    return SimpleNamespace(name=name)


def test_destructive_tool_blocks_ungrounded_ids():
    result = enforce_destructive_confirmation(
        tool("delete_notes"),
        {"note_ids": "2,5"},
        context("Show all notes."),
    )
    assert result is not None
    assert result["status"] == "confirmation_required"


def test_initial_delete_request_still_requires_confirmation():
    result = enforce_destructive_confirmation(
        tool("delete_task"),
        {"task_id": 12},
        context("Delete task 12."),
    )
    assert result is not None
    assert result["status"] == "confirmation_required"


def test_bulk_selection_after_delete_intent_is_allowed():
    result = enforce_destructive_confirmation(
        tool("delete_notes"),
        {"note_ids": "2,5"},
        context("Delete all notes.", "Show notes.", "2 and 5"),
    )
    assert result is None


def test_affirmative_confirmation_for_exact_prior_id_is_allowed():
    result = enforce_destructive_confirmation(
        tool("delete_task"),
        {"task_id": 12},
        context("Delete task 12.", "Yes, confirm."),
    )
    assert result is None


def test_non_destructive_tools_are_not_intercepted():
    result = enforce_destructive_confirmation(
        tool("list_tasks"),
        {"status": "all"},
        context("Show all tasks."),
    )
    assert result is None
