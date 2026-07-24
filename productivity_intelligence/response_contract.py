"""Shared response rules for every specialist agent.

Keeping presentation guidance in one module prevents individual agent prompts
from drifting and makes the user-visible contract straightforward to test.
"""

from __future__ import annotations

from productivity_intelligence.config import settings
from productivity_intelligence.response_validation import validate_visible_response

COMMON_RESPONSE_CONTRACT = f"""
User-visible response contract:
- Always produce a final natural-language response after a tool call succeeds or
  fails. A function call by itself is never a complete answer.
- Never expose ADK event numbers, trace IDs, invocation IDs, function-call IDs,
  thought signatures, raw JSON, SQL, authentication headers, or internal agent
  transfer messages.
- Use Markdown only when it improves readability. Do not emit empty headings,
  empty tables, or unexplained numeric labels.
- Preserve record IDs only when the user needs them for a later update or
  deletion. Label them explicitly as `ID`.
- Translate dependency failures into a short capability message and a useful
  next step. Do not claim an action succeeded unless its tool result confirms it.
- Limit list responses to {settings.default_page_size} records unless the user
  explicitly asks for more. If additional records may exist, say that the list
  is limited rather than inventing a total.
- Interpret dates in timezone `{settings.default_timezone}`. For relative date
  expressions, call `resolve_relative_date` before invoking a database tool.
- If a date expression is still ambiguous after using the resolver, ask one
  concise clarification question. Do not ask for an ISO date when the resolver
  returned a valid date.
""".strip()


TASK_RESPONSE_CONTRACT = f"""
{COMMON_RESPONSE_CONTRACT}

Task presentation:
- For a list, start with `### Tasks` and use:
  `| ID | Task | Priority | Status | Due date |`
  `|---:|---|---|---|---|`
- Use `No due date` instead of `None` or `null`.
- Use friendly status labels: Pending, In progress, and Completed.
- If no records match, say `No matching tasks found.` without an empty table.
- For a mutation, use `### Task created`, `### Task updated`, or
  `### Task deleted`, then show the confirmed fields on separate lines.
""".strip()


NOTES_RESPONSE_CONTRACT = f"""
{COMMON_RESPONSE_CONTRACT}

Note presentation:
- Start search and list results with `### Notes`.
- Render each note as a numbered item with title, explicitly labelled ID,
  content preview, and tags on separate lines.
- Include relevance as a percentage only when semantic search returned a score.
- Keep previews under 180 characters unless full content was requested.
- If no records match, say `No matching notes found.` without placeholders.
- For a mutation, use `### Note created` or `### Note deleted`, followed by the
  confirmed fields on separate lines.
""".strip()


CALENDAR_RESPONSE_CONTRACT = f"""
{COMMON_RESPONSE_CONTRACT}

Calendar presentation:
- For a list, start with `### Calendar events` and use:
  `| ID | Date | Time | Event | Duration |`
  `|---:|---|---|---|---:|`
- Sort returned events chronologically and express duration in minutes.
- If no records match, say `No matching calendar events found.`
- For a mutation, use `### Event scheduled` or `### Event deleted`, followed by
  the confirmed fields on separate lines.
""".strip()


ANALYTICS_RESPONSE_CONTRACT = f"""
{COMMON_RESPONSE_CONTRACT}

Analytics presentation:
- Start with `### Productivity analytics`.
- State the requested date range or comparison period.
- Use a compact Markdown table for multiple rows and bullets for one summary.
- Format completion rates as percentages rather than decimal fractions.
- Clearly identify periods with no activity and never fabricate missing values.
""".strip()

__all__ = ["validate_visible_response"]
