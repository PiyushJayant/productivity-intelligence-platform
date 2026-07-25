"""
Task Agent
----------
Manages to-do tasks stored in AlloyDB via the MCP Toolbox for Databases.
The toolbox exposes task CRUD operations defined in mcp_toolbox/tools.yaml.
"""
from google.adk.agents import LlmAgent

from productivity_intelligence.config import settings
from productivity_intelligence.context_policy import (
    compact_specialist_history,
    record_model_usage,
)
from productivity_intelligence.date_tools import (
    resolve_relative_date,
    resolve_relative_datetime,
)
from productivity_intelligence.guardrails import enforce_destructive_confirmation
from productivity_intelligence.model_config import gemini_generate_content_config
from productivity_intelligence.response_contract import TASK_RESPONSE_CONTRACT
from productivity_intelligence.status import capabilities
from productivity_intelligence.tools import load_toolset


def _build_task_agent() -> LlmAgent | None:
    task_tools = load_toolset("task-tools")
    if task_tools is None:
        capabilities.mark_unavailable("task_agent", "Toolbox task toolset unavailable")
        return None

    agent = LlmAgent(
        model=settings.model,
        generate_content_config=gemini_generate_content_config("specialist"),
        name="task_agent",
        description=(
            "Handles task management: create, list, update status, and delete tasks. "
            "Tasks are stored in AlloyDB for PostgreSQL."
        ),
        instruction=f"""You are a task management assistant. You manage tasks stored in AlloyDB.

You can:
- Create tasks with a title, description, priority (low/medium/high), and optional
  due date or timezone-aware deadline
- List tasks filtered by status (pending/in_progress/done) or list all tasks
- Update a task's status to pending, in_progress, or done
- Delete tasks by their ID, but only after the user explicitly confirms the deletion

When the user selects multiple exact IDs, use the matching bulk tool once
(`update_tasks_status` or `delete_tasks`) instead of making repeated single-ID
calls. Report requested IDs that were absent without claiming success.

Extract every value already present in the user's request before asking a
question. Infer a concise title from the requested action, use an empty
description when omitted, and default priority to medium when the user does not
specify one. Never ask the user to repeat a title or date they already supplied.

Call `resolve_relative_datetime` when the request includes a clock time. Put its
`utc_datetime` in `due_at` and its date in `due_date`. Call
`resolve_relative_date` for date-only phrases. If a bare hour is ambiguous, ask
only whether it is AM or PM. Never silently discard a requested time.

Always confirm actions and display task details clearly after each operation.
If an update or delete returns no row, explain that the task ID was not found.

{TASK_RESPONSE_CONTRACT}""",
        tools=[*task_tools, resolve_relative_date, resolve_relative_datetime],
        before_tool_callback=enforce_destructive_confirmation,
        before_model_callback=compact_specialist_history,
        after_model_callback=record_model_usage,
    )
    capabilities.mark_loaded("task_agent")
    return agent

task_agent = _build_task_agent()
