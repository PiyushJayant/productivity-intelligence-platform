"""Deterministic tool-execution guardrails independent of model compliance."""

from __future__ import annotations

import re
from typing import Any

DESTRUCTIVE_TOOL_ID_ARGUMENT = {
    "delete_task": "task_id",
    "delete_tasks": "task_ids",
    "delete_note": "note_id",
    "delete_notes": "note_ids",
    "delete_event": "event_id",
    "delete_events": "event_ids",
}
DESTRUCTIVE_INTENT = re.compile(
    r"\b(?:delete|remove|cancel|erase|purge)\b",
    re.IGNORECASE,
)
AFFIRMATIVE_CONFIRMATION = re.compile(
    r"^\s*(?:yes(?:,\s*(?:confirm|confirmed|proceed|do it))?|"
    r"confirm(?:ed)?|proceed|do it)\s*[.!]?\s*$",
    re.IGNORECASE,
)
EXPLICIT_CONFIRMATION = re.compile(
    r"\b(?:confirm|confirmed|proceed|do it)\b",
    re.IGNORECASE,
)


def _content_text(content: Any) -> str:
    return " ".join(
        str(getattr(part, "text", "") or "").strip()
        for part in (getattr(content, "parts", None) or [])
        if getattr(part, "text", None)
    ).strip()


def _ids(value: Any) -> set[int]:
    if isinstance(value, int):
        return {value}
    return {int(item) for item in re.findall(r"\d+", str(value))}


def _recent_user_messages(tool_context: Any) -> list[str]:
    messages: list[str] = []
    session = getattr(tool_context, "session", None)
    for event in list(getattr(session, "events", None) or [])[-30:]:
        if getattr(event, "author", None) != "user":
            continue
        text = _content_text(getattr(event, "content", None))
        if text and not text.lower().startswith("for context:"):
            messages.append(text)
    current = _content_text(getattr(tool_context, "user_content", None))
    if current and (not messages or messages[-1] != current):
        messages.append(current)
    return messages[-5:]


def enforce_destructive_confirmation(
    tool: Any,
    args: dict[str, Any],
    tool_context: Any,
) -> dict[str, Any] | None:
    """Block destructive tools unless exact IDs are grounded in user confirmation."""

    tool_name = getattr(tool, "name", "")
    id_argument = DESTRUCTIVE_TOOL_ID_ARGUMENT.get(tool_name)
    if id_argument is None:
        return None

    requested_ids = _ids(args.get(id_argument))
    messages = _recent_user_messages(tool_context)
    current = messages[-1] if messages else ""
    current_ids = _ids(current)
    prior_intent = next(
        (
            text
            for text in reversed(messages[:-1])
            if DESTRUCTIVE_INTENT.search(text)
        ),
        "",
    )
    intent_ids = _ids(prior_intent)

    directly_confirmed = (
        DESTRUCTIVE_INTENT.search(current) is not None
        and EXPLICIT_CONFIRMATION.search(current) is not None
        and requested_ids
        and requested_ids <= current_ids
    )
    selected_after_intent = (
        requested_ids
        and requested_ids <= current_ids
        and bool(prior_intent)
    )
    affirmed_prior_request = (
        AFFIRMATIVE_CONFIRMATION.fullmatch(current) is not None
        and requested_ids
        and requested_ids <= intent_ids
    )
    if directly_confirmed or selected_after_intent or affirmed_prior_request:
        return None

    return {
        "status": "confirmation_required",
        "message": (
            "Deletion was not executed. Ask the user to explicitly confirm the "
            f"exact IDs: {', '.join(str(item) for item in sorted(requested_ids))}."
        ),
    }
