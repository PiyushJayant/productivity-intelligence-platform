from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

import main
from productivity_intelligence.observability import JsonLogFormatter


def test_request_middleware_preserves_or_creates_correlation_id():
    response = TestClient(main.app).get("/healthz", headers={"X-Request-ID": "test-request"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request"


def test_structured_formatter_excludes_credentials_and_body():
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "request completed",
        (),
        None,
    )
    record.method = "POST"
    record.path = "/run"
    record.status = 200
    record.latency_ms = 12.5
    payload = json.loads(JsonLogFormatter().format(record))
    assert payload["path"] == "/run"
    assert "body" not in payload
    assert "headers" not in payload
