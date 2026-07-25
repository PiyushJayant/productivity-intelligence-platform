import logging
from types import SimpleNamespace

from productivity_intelligence.context_policy import (
    compact_specialist_history,
    record_model_usage,
)


def content(role: str, text: str):
    return SimpleNamespace(role=role, parts=[SimpleNamespace(text=text)])


def test_specialist_context_is_bounded_at_a_real_user_message(monkeypatch):
    from productivity_intelligence import context_policy

    monkeypatch.setattr(
        context_policy, "settings", SimpleNamespace(agent_context_max_events=4)
    )
    request = SimpleNamespace(
        contents=[
            content("user", "old request"),
            content("model", "old response"),
            content("user", "For context:"),
            content("user", "[task_agent] said: old state"),
            content("user", "current request"),
            content("model", "current response"),
        ]
    )

    compact_specialist_history(None, request)

    assert request.contents[0].parts[0].text == "current request"
    assert len(request.contents) == 2


def test_adk_callback_keyword_contract_is_supported(caplog):
    caplog.set_level(logging.INFO, logger="productivity.model")
    request = SimpleNamespace(contents=[content("user", "current request")])
    compact_specialist_history(
        callback_context=SimpleNamespace(agent_name="notes_agent"),
        llm_request=request,
    )
    record_model_usage(
        callback_context=SimpleNamespace(agent_name="notes_agent"),
        llm_response=SimpleNamespace(
            usage_metadata=SimpleNamespace(
                prompt_token_count=10,
                candidates_token_count=3,
                cached_content_token_count=4,
            )
        ),
    )
    assert "model response completed" in caplog.text
