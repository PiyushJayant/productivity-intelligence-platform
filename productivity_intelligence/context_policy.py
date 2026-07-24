"""Privacy-conscious specialist history compaction and model-usage telemetry."""

from __future__ import annotations

import logging
from typing import Any

from productivity_intelligence.config import settings

LOGGER = logging.getLogger("productivity.model")


def _part_value(part: Any, snake_name: str, camel_name: str) -> Any:
    return getattr(part, snake_name, None) or getattr(part, camel_name, None)


def _is_safe_user_boundary(content: Any) -> bool:
    if getattr(content, "role", None) != "user":
        return False
    parts = getattr(content, "parts", None) or []
    if any(
        _part_value(part, "function_response", "functionResponse") is not None
        for part in parts
    ):
        return False
    text = " ".join(
        str(getattr(part, "text", "") or "").strip() for part in parts
    ).strip()
    lowered = text.lower()
    synthetic_agent_context = text.startswith("[") and any(
        marker in lowered
        for marker in ("] said:", "] called tool", "] `transfer_to_agent`")
    )
    return (
        bool(text)
        and not lowered.startswith("for context:")
        and not synthetic_agent_context
    )


def compact_specialist_history(_context: Any, llm_request: Any) -> None:
    """Bound specialist history while retaining a complete current interaction.

    ADK converts prior transfers and results into synthetic context messages.
    Starting the retained window at a real user message prevents an orphaned
    function result and removes unrelated earlier intents without logging any
    prompt content.
    """

    contents = list(getattr(llm_request, "contents", None) or [])
    maximum = settings.agent_context_max_events
    if len(contents) <= maximum:
        return

    start = len(contents) - maximum
    while start < len(contents) - 1 and not _is_safe_user_boundary(contents[start]):
        start += 1
    retained = contents[start:]
    llm_request.contents = retained
    LOGGER.info(
        "specialist context compacted",
        extra={
            "context_events_before": len(contents),
            "context_events_after": len(retained),
        },
    )


def record_model_usage(context: Any, llm_response: Any) -> None:
    """Log token counters and agent name without recording prompt content."""

    usage = getattr(llm_response, "usage_metadata", None)
    if usage is None:
        return
    LOGGER.info(
        "model response completed",
        extra={
            "agent": getattr(context, "agent_name", None),
            "prompt_tokens": getattr(usage, "prompt_token_count", None),
            "output_tokens": getattr(usage, "candidates_token_count", None),
            "cached_tokens": getattr(usage, "cached_content_token_count", None),
        },
    )
