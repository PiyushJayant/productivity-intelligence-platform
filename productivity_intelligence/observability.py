"""Structured, privacy-conscious request observability."""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

from fastapi import Request, Response

from productivity_intelligence.config import settings

request_id_context: ContextVar[str] = ContextVar("request_id", default="")


class JsonLogFormatter(logging.Formatter):
    """Emit Cloud Logging-friendly JSON without request bodies or credentials."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_context.get()
        if request_id:
            payload["request_id"] = request_id
        for field in (
            "method",
            "path",
            "status",
            "latency_ms",
            "agent",
            "context_events_before",
            "context_events_after",
            "prompt_tokens",
            "output_tokens",
            "cached_tokens",
        ):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def configure_logging() -> None:
    """Configure the root logger once from the environment SOT."""

    root = logging.getLogger()
    root.setLevel(settings.log_level)
    handlers: list[logging.Handler]
    if root.handlers:
        handlers = list(root.handlers)
    else:
        handler: logging.Handler = logging.StreamHandler()
        root.addHandler(handler)
        handlers = [handler]
    formatter: logging.Formatter
    if settings.structured_logging:
        formatter = JsonLogFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s",
            defaults={"request_id": ""},
        )
    for handler in handlers:
        handler.setFormatter(formatter)


async def request_observability_middleware(request: Request, call_next) -> Response:
    """Attach a correlation ID and record method/path/status/latency only."""

    incoming = request.headers.get(settings.request_id_header, "").strip()
    request_id = incoming[:128] if incoming else uuid.uuid4().hex
    token = request_id_context.set(request_id)
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers[settings.request_id_header] = request_id
        return response
    finally:
        if settings.enable_request_logging:
            logging.getLogger("productivity.request").info(
                "request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
        request_id_context.reset(token)
