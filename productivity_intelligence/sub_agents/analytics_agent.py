"""Read-only productivity analytics agent backed by deterministic BigQuery queries."""

import logging

from google.adk.agents import LlmAgent

from productivity_intelligence.analytics_tools import get_productivity_trends
from productivity_intelligence.config import settings
from productivity_intelligence.context_policy import (
    compact_specialist_history,
    record_model_usage,
)
from productivity_intelligence.date_tools import resolve_reporting_period
from productivity_intelligence.model_config import gemini_generate_content_config
from productivity_intelligence.response_contract import ANALYTICS_RESPONSE_CONTRACT
from productivity_intelligence.status import capabilities
from productivity_intelligence.tools import get_bigquery_mcp_toolset

LOGGER = logging.getLogger(__name__)


def _build_analytics_agent() -> LlmAgent | None:
    try:
        # Keep the authenticated hosted MCP integration as a startup capability
        # check and compatibility path, but never expose its generic SQL tools to
        # the model. User analytics runs only through the domain tool below.
        _bq_toolset = get_bigquery_mcp_toolset()
    except Exception:
        LOGGER.warning(
            "Analytics agent disabled because BigQuery MCP initialization failed",
            exc_info=True,
        )
        capabilities.mark_unavailable("analytics_agent", "BigQuery MCP unavailable")
        return None

    agent = LlmAgent(
        model=settings.model,
        generate_content_config=gemini_generate_content_config("analytics"),
        name="analytics_agent",
        description=(
            "Provides productivity analytics and insights by querying the live "
            "tenant-scoped AlloyDB-backed BigQuery routine in "
            f"`{settings.bigquery_dataset}`."
        ),
        instruction=f"""You are a productivity analytics assistant.

BigQuery dataset: `{settings.google_cloud_project}.{settings.bigquery_dataset}`

Approved contract: the tenant-scoped `{settings.bigquery_analytics_procedure}`
routine, exposed only through `get_productivity_trends`.

Use `resolve_reporting_period` before querying. The phrase "last year" is
ambiguous: ask whether the user means a rolling 12 months or the previous
calendar year. Pass the resolver's dates and grain to
`get_productivity_trends`, which is the only data-query tool you may use.
Offer only resolver-supported examples, such as "last month", "this quarter",
"rolling 12 months", or an explicit YYYY-MM-DD date range.

Never write or generate SQL and never modify datasets, tables, views,
connections, IAM policies, or rows. Present concise results, disclose the
interpreted period, and clearly identify periods with no activity.

{ANALYTICS_RESPONSE_CONTRACT}""",
        tools=[resolve_reporting_period, get_productivity_trends],
        before_model_callback=compact_specialist_history,
        after_model_callback=record_model_usage,
    )
    capabilities.mark_loaded("analytics_agent")
    return agent


analytics_agent = _build_analytics_agent()
