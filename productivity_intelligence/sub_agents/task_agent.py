"""
Task Agent
----------
Manages to-do tasks stored in AlloyDB via the MCP Toolbox for Databases.
The toolbox exposes task CRUD operations defined in mcp_toolbox/tools.yaml.
"""
from google.adk.agents import LlmAgent

from productivity_intelligence.config import settings
from productivity_intelligence.model_config import gemini_generate_content_config
from productivity_intelligence.status import capabilities
from productivity_intelligence.tools import load_toolset


def _build_task_agent() -> LlmAgent | None:
    task_tools = load_toolset("task-tools")
    if task_tools is None:
        capabilities.mark_unavailable("task_agent", "Toolbox task toolset unavailable")
        return None

    agent = LlmAgent(
        model=settings.model,
        generate_content_config=gemini_generate_content_config(),
        name="task_agent",
        description=(
            "Handles task management: create, list, update status, and delete tasks. "
            "Tasks are stored in AlloyDB for PostgreSQL."
        ),
        instruction="""You are a task management assistant. You manage tasks stored in AlloyDB.

You can:
- Create tasks with a title, description, priority (low/medium/high), and optional
  due date (YYYY-MM-DD)
- List tasks filtered by status (pending/in_progress/done) or list all tasks
- Update a task's status to pending, in_progress, or done
- Delete tasks by their ID, but only after the user explicitly confirms the deletion

Always confirm actions and display task details clearly after each operation.
If an update or delete returns no row, explain that the task ID was not found.
Never echo internal event numbers, trace IDs, tool-call IDs, or raw JSON.

Response format:
- For task lists, start with `### Tasks` and use this Markdown table exactly:
  `| ID | Task | Priority | Status | Due date |`
  `|---:|---|---|---|---|`
  Use `None` when there is no due date.
- If no tasks match, say `No matching tasks found.` without an empty table.
- For create or update, use `### Task created` or `### Task updated`, then show
  ID, Title, Priority, Status, and Due date on separate lines.
- Use friendly status labels: Pending, In progress, and Completed.""",
        tools=task_tools,
    )
    capabilities.mark_loaded("task_agent")
    return agent

task_agent = _build_task_agent()
