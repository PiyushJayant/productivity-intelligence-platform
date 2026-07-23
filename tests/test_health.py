from fastapi.testclient import TestClient

import main
from productivity_intelligence.status import capabilities


def test_health_endpoint_contains_no_dependency_details():
    response = TestClient(main.app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_503_for_missing_agents():
    capabilities.configure({"required_test_agent"})
    capabilities.mark_unavailable("required_test_agent", "dependency unavailable")
    response = TestClient(main.app).get("/readyz")
    assert response.status_code == 503
    assert response.json()["missing_agents"] == ["required_test_agent"]
