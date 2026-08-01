import logging
import os
import sys

from fastapi import Request
from fastapi.responses import JSONResponse
from google.adk.cli.fast_api import get_fast_api_app

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
PACKAGED_AGENTS_DIR = os.path.join(APP_ROOT, "agents")
AGENTS_DIR = os.environ.get(
    "AGENTS_DIR",
    PACKAGED_AGENTS_DIR if os.path.isdir(PACKAGED_AGENTS_DIR) else APP_ROOT,
)
if AGENTS_DIR not in sys.path:
    sys.path.insert(0, AGENTS_DIR)

from productivity_intelligence.config import settings  # noqa: E402
from productivity_intelligence.identity import identity_middleware  # noqa: E402
from productivity_intelligence.observability import (  # noqa: E402
    configure_logging,
    request_observability_middleware,
)

configure_logging()

# Force capability discovery during process startup. ADK otherwise imports an
# agent lazily on the first conversational request, making readiness vacuous.
from productivity_intelligence.agent import root_agent as _root_agent  # noqa: E402,F401
from productivity_intelligence.status import capabilities  # noqa: E402

logger = logging.getLogger(__name__)

logger.info("Starting Productivity Intelligence Platform...")

app = get_fast_api_app(
    agents_dir=AGENTS_DIR,
    web=settings.auth_mode == "disabled",
)
# Debug, evaluation, builder, and live-development transports are not production
# application APIs. Remove them entirely when end-user authentication is active.
if settings.auth_mode == "identity_platform":
    blocked_fragments = (
        "/debug/",
        "/dev/",
        "/builder/",
        "/eval",
        "/metrics-info",
        "/run_live",
    )
    app.router.routes = [
        route
        for route in app.router.routes
        if not any(
            fragment in getattr(route, "path", "")
            for fragment in blocked_fragments
        )
    ]
app.middleware("http")(request_observability_middleware)
app.middleware("http")(identity_middleware)
logger.info("ADK FastAPI app created successfully")


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
def readyz():
    snapshot = capabilities.snapshot()
    return JSONResponse(snapshot, status_code=200 if snapshot["ready"] else 503)


@app.get("/auth/me", include_in_schema=False)
def auth_me(request: Request):
    identity = request.state.identity
    return {
        "tenant_id": str(identity.tenant_id),
        "subject_id": str(identity.subject_id),
        "role": identity.role,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
