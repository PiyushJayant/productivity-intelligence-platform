import logging
import os
import sys

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

# Force capability discovery during process startup. ADK otherwise imports an
# agent lazily on the first conversational request, making readiness vacuous.
from productivity_assistant.agent import root_agent as _root_agent  # noqa: E402,F401
from productivity_assistant.status import capabilities  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info("Starting productivity assistant...")

app = get_fast_api_app(
    agents_dir=AGENTS_DIR,
    web=True,
)
logger.info("ADK FastAPI app created successfully")


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
def readyz():
    snapshot = capabilities.snapshot()
    return JSONResponse(snapshot, status_code=200 if snapshot["ready"] else 503)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
