from types import SimpleNamespace

from productivity_intelligence.context_policy import compact_specialist_history


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
