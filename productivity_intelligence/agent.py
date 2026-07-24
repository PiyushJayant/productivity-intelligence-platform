"""Root orchestrator for Productivity Intelligence Platform.

The coordinator only advertises the capabilities that are actually available at
startup. This keeps analytics-only deployments from promising task,
notes, or calendar actions when the AlloyDB-backed MCP toolbox is unavailable.
"""
from google.adk.agents import LlmAgent

from productivity_intelligence.config import settings
from productivity_intelligence.context_policy import record_model_usage
from productivity_intelligence.model_config import gemini_generate_content_config
from productivity_intelligence.response_contract import COMMON_RESPONSE_CONTRACT
from productivity_intelligence.status import capabilities
from productivity_intelligence.sub_agents.analytics_agent import analytics_agent

EXPECTED_AGENTS = (
    {"analytics_agent"}
    if settings.app_mode == "prototype"
    else {"task_agent", "notes_agent", "calendar_agent", "analytics_agent"}
)
capabilities.configure(EXPECTED_AGENTS)

if settings.app_mode == "full":
    from productivity_intelligence.sub_agents.calendar_agent import calendar_agent
    from productivity_intelligence.sub_agents.notes_agent import notes_agent
    from productivity_intelligence.sub_agents.task_agent import task_agent
else:
    task_agent = notes_agent = calendar_agent = None


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
        "A work-intelligence orchestration platform backed by Google Cloud services. "
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

    return f"""You are Productivity Intelligence, a secure work-orchestration
platform powered by Google Cloud.

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
capabilities that are actually available.

{COMMON_RESPONSE_CONTRACT}"""


root_agent = LlmAgent(
    model=settings.model,
    generate_content_config=gemini_generate_content_config("router"),
    name="productivity_orchestrator",
    description=_build_description(),
    instruction=_build_instruction(),
    sub_agents=AVAILABLE_AGENTS,
    after_model_callback=record_model_usage,
)
