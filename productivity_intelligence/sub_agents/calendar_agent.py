"""
Calendar Agent
--------------
Manages calendar events stored in AlloyDB via the MCP Toolbox for Databases.
"""
from google.adk.agents import LlmAgent

from productivity_intelligence.config import settings
from productivity_intelligence.date_tools import resolve_relative_date
from productivity_intelligence.model_config import gemini_generate_content_config
from productivity_intelligence.response_contract import CALENDAR_RESPONSE_CONTRACT
from productivity_intelligence.status import capabilities
from productivity_intelligence.tools import load_toolset


def _build_calendar_agent() -> LlmAgent | None:
    calendar_tools = load_toolset("calendar-tools")
    if calendar_tools is None:
        capabilities.mark_unavailable("calendar_agent", "Toolbox calendar toolset unavailable")
        return None

    agent = LlmAgent(
        model=settings.model,
        generate_content_config=gemini_generate_content_config("specialist"),
        name="calendar_agent",
        description=(
            "Handles calendar events and scheduling: create, list, and delete events. "
            "Events are stored in AlloyDB for PostgreSQL."
        ),
        instruction=f"""You are a calendar and scheduling assistant. Events are stored in AlloyDB.

You can:
- Create events with title, date (YYYY-MM-DD), time (HH:MM 24-hour), duration
  in minutes, and optional description
- List all events or filter by a specific date
- Delete events by their ID, but only after the user explicitly confirms the deletion

Call `resolve_relative_date` for phrases such as today, tomorrow, Friday, next
Monday, or in two weeks. Use its ISO date in the database tool call.

Always confirm actions and display event details clearly.
If a delete returns no row, explain that the event ID was not found.

{CALENDAR_RESPONSE_CONTRACT}""",
        tools=[*calendar_tools, resolve_relative_date],
    )
    capabilities.mark_loaded("calendar_agent")
    return agent

calendar_agent = _build_calendar_agent()
