"""Read-only productivity analytics agent backed by BigQuery MCP."""

import logging

from google.adk.agents import LlmAgent

from productivity_intelligence.config import settings
from productivity_intelligence.model_config import gemini_generate_content_config
from productivity_intelligence.status import capabilities
from productivity_intelligence.tools import get_bigquery_mcp_toolset

LOGGER = logging.getLogger(__name__)


def _build_analytics_agent() -> LlmAgent | None:
    try:
        bq_toolset = get_bigquery_mcp_toolset()
    except Exception:
        LOGGER.warning(
            "Analytics agent disabled because BigQuery MCP initialization failed",
            exc_info=True,
        )
        capabilities.mark_unavailable("analytics_agent", "BigQuery MCP unavailable")
        return None

    agent = LlmAgent(
        model=settings.model,
        generate_content_config=gemini_generate_content_config(),
        name="analytics_agent",
        description=(
            "Provides productivity analytics and insights by querying the live "
            "AlloyDB-backed BigQuery views in `productivity_analytics`."
        ),
        instruction=f"""You are a productivity analytics assistant.

BigQuery dataset: `{settings.google_cloud_project}.productivity_analytics`

Approved views:
- `task_summary`: date, priority, total_tasks, completed_tasks, pending_tasks,
  in_progress_tasks, completion_rate
- `daily_activity`: date, tasks_created, tasks_completed, notes_created,
  events_scheduled

Use only read-only SQL against these two approved views. Never modify datasets,
tables, views, connections, IAM policies, or rows. Present concise results and
clearly identify periods with no activity. Never echo internal event numbers,
trace IDs, tool-call IDs, or raw JSON. Start with `### Productivity analytics`.
Use a compact Markdown table for multiple rows and bullets for a single summary.
Format completion rates as percentages rather than decimal fractions.""",
        tools=[bq_toolset],
    )
    capabilities.mark_loaded("analytics_agent")
    return agent


analytics_agent = _build_analytics_agent()
