"""
Task Agent
----------
Manages to-do tasks stored in AlloyDB via the MCP Toolbox for Databases.
The toolbox exposes task CRUD operations defined in mcp_toolbox/tools.yaml.
"""
from google.adk.agents import LlmAgent

from productivity_intelligence.config import settings
from productivity_intelligence.date_tools import resolve_relative_date
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
  due date (YYYY-MM-DD)
- List tasks filtered by status (pending/in_progress/done) or list all tasks
- Update a task's status to pending, in_progress, or done
- Delete tasks by their ID, but only after the user explicitly confirms the deletion

Call `resolve_relative_date` for phrases such as tomorrow, Friday, next Monday,
or in two weeks. Use its ISO date in the database tool call.

Always confirm actions and display task details clearly after each operation.
If an update or delete returns no row, explain that the task ID was not found.

{TASK_RESPONSE_CONTRACT}""",
        tools=[*task_tools, resolve_relative_date],
    )
    capabilities.mark_loaded("task_agent")
    return agent

task_agent = _build_task_agent()
