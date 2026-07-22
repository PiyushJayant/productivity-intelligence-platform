"""
Calendar Agent
--------------
Manages calendar events stored in AlloyDB via the MCP Toolbox for Databases.
"""
from google.adk.agents import LlmAgent

from productivity_assistant.config import settings
from productivity_assistant.model_config import gemini_generate_content_config
from productivity_assistant.status import capabilities
from productivity_assistant.tools import load_toolset


def _build_calendar_agent() -> LlmAgent | None:
    calendar_tools = load_toolset("calendar-tools")
    if calendar_tools is None:
        capabilities.mark_unavailable("calendar_agent", "Toolbox calendar toolset unavailable")
        return None

    agent = LlmAgent(
        model=settings.model,
        generate_content_config=gemini_generate_content_config(),
        name="calendar_agent",
        description=(
            "Handles calendar events and scheduling: create, list, and delete events. "
            "Events are stored in AlloyDB for PostgreSQL."
        ),
        instruction="""You are a calendar and scheduling assistant. Events are stored in AlloyDB.

You can:
- Create events with title, date (YYYY-MM-DD), time (HH:MM 24-hour), duration
  in minutes, and optional description
- List all events or filter by a specific date
- Delete events by their ID, but only after the user explicitly confirms the deletion

Always confirm actions and display event details clearly.
If a delete returns no row, explain that the event ID was not found.
Never echo internal event numbers, trace IDs, tool-call IDs, or raw JSON.

Response format:
- For event lists, start with `### Calendar events` and use this Markdown table:
  `| ID | Date | Time | Event | Duration |`
  `|---:|---|---|---|---:|`
- Sort events chronologically and express duration in minutes.
- If no events match, say `No matching calendar events found.`
- For creation, use `### Event scheduled`, then show ID, Title, Date, Time, and
  Duration on separate lines.""",
        tools=calendar_tools,
    )
    capabilities.mark_loaded("calendar_agent")
    return agent

calendar_agent = _build_calendar_agent()
