from productivity_intelligence.status import CapabilityRegistry


def test_registry_reports_missing_agents_without_internal_errors():
    registry = CapabilityRegistry()
    registry.configure({"task_agent", "analytics_agent"})
    registry.mark_loaded("analytics_agent")
    registry.mark_unavailable("task_agent", "Toolbox task toolset unavailable")

    assert registry.snapshot() == {
        "ready": False,
        "expected_agents": ["analytics_agent", "task_agent"],
        "loaded_agents": ["analytics_agent"],
        "missing_agents": ["task_agent"],
        "unavailable": {"task_agent": "Toolbox task toolset unavailable"},
    }


def test_registry_is_ready_when_all_expected_agents_loaded():
    registry = CapabilityRegistry()
    registry.configure({"analytics_agent"})
    registry.mark_loaded("analytics_agent")
    assert registry.snapshot()["ready"] is True
