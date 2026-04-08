"""Root agent for the multi-agent productivity assistant.

The coordinator only advertises the capabilities that are actually available at
startup. This keeps prototype or degraded deployments from promising task,
notes, or calendar actions when the AlloyDB-backed MCP toolbox is unavailable.
"""
from google.adk.agents import LlmAgent

from productivity_assistant.sub_agents.analytics_agent import analytics_agent
from productivity_assistant.sub_agents.calendar_agent import calendar_agent
from productivity_assistant.sub_agents.notes_agent import notes_agent
from productivity_assistant.sub_agents.task_agent import task_agent


AVAILABLE_AGENTS = [
    agent
    for agent in [task_agent, notes_agent, calendar_agent, analytics_agent]
    if agent is not None
]

AGENT_CAPABILITIES = {
    "task_agent": (
        "Tasks, to-dos, assignments, and work items stored in AlloyDB.",
        '"create/list/update/delete task"',
    ),
    "notes_agent": (
        "Notes, ideas, and semantic note search powered by AlloyDB AI.",
        '"create/search/list/delete note"',
    ),
    "calendar_agent": (
        "Meetings, events, appointments, and scheduling in AlloyDB.",
        '"schedule/create/list event or meeting"',
    ),
    "analytics_agent": (
        "Productivity trends, insights, reports, and BigQuery statistics.",
        '"how many tasks / trends / completion rate / insights"',
    ),
}


def _build_description() -> str:
    names = {agent.name for agent in AVAILABLE_AGENTS}
    if names == {"analytics_agent"}:
        return (
            "A productivity analytics assistant backed by BigQuery on Google Cloud. "
            "Provides insights, trends, and reports."
        )

    return (
        "A multi-agent productivity assistant backed by Google Cloud services. "
        "Manages the capabilities exposed by the currently available specialist agents."
    )


def _build_instruction() -> str:
    available_names = [agent.name for agent in AVAILABLE_AGENTS]
    capability_lines = []
    routing_lines = []

    for index, name in enumerate(available_names, start=1):
        capability, trigger = AGENT_CAPABILITIES[name]
        capability_lines.append(f"{index}. {name} -> {capability}")
        routing_lines.append(f"- {trigger} -> {name}")

    if not capability_lines:
        capability_lines.append("No specialist agents are currently available.")
        routing_lines.append("- Explain that no tools are available right now.")

    unavailable = [
        name
        for name in AGENT_CAPABILITIES
        if name not in available_names
    ]
    unavailable_summary = ", ".join(unavailable) if unavailable else "none"

    return f"""You are a smart productivity assistant powered by Google Cloud.

Only offer actions supported by the specialist agents that are currently loaded.
If a capability is unavailable, say so plainly and avoid implying the action can
be completed in this deployment.

Available specialist agents:
{chr(10).join(capability_lines)}

Routing rules:
{chr(10).join(routing_lines)}

Unavailable specialist agents at startup: {unavailable_summary}

For multi-step requests, execute each supported step sequentially by delegating
to the appropriate specialist agent one at a time.

Always be concise, confirm completed actions, and guide the user based on the
capabilities that are actually available."""


root_agent = LlmAgent(
    model="gemini-2.5-flash",
    name="productivity_assistant",
    description=_build_description(),
    instruction=_build_instruction(),
    sub_agents=AVAILABLE_AGENTS,
)
