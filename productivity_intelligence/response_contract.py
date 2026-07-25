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
- Before a tool call, emit only the function call. Do not send progress prose,
  headings, or a partial answer in the same model turn. When multiple tools are
  needed, complete every tool call first and then send exactly one final summary.
- Never expose ADK event numbers, trace IDs, invocation IDs, function-call IDs,
  thought signatures, raw JSON, SQL, authentication headers, or internal agent
  transfer messages.
- Use Markdown only when it improves readability. Do not emit empty headings,
  empty tables, or unexplained numeric labels.
- Preserve record IDs only when the user needs them for a later update or
  deletion. Label them explicitly as `ID`.
- Translate dependency failures into a short capability message and a useful
  next step. Do not claim an action succeeded unless its tool result confirms it.
- Preserve every material value in the user's request. If a requested value
  cannot be represented by a tool, explain the limitation before mutation
  rather than silently dropping it.
- Omit unavailable or empty fields. Never render `None`, `null`, an empty label,
  or a value that was not confirmed by a tool result.
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
  `| ID | Task | Priority | Status | Due date or deadline |`
  `|---:|---|---|---|---|`
- Use `No due date` instead of `None` or `null`.
- Show timed deadlines in `{settings.default_timezone}` and include the timezone.
- Use friendly status labels: Pending, In progress, and Completed.
- If no records match, say `No matching tasks found.` without an empty table.
- For a mutation, use `### Task created`, `### Task updated`, or
  `### Task deleted`, then show only confirmed, non-empty fields on separate
  lines. Use the same friendly priority and status labels as list responses.
""".strip()


NOTES_RESPONSE_CONTRACT = f"""
{COMMON_RESPONSE_CONTRACT}

Note presentation:
- Start search and list results with `### Notes`.
- Render each note as a numbered item with title, explicitly labelled ID,
  content preview, and tags on separate lines.
- Include relevance as a percentage only when semantic search returned a score.
- Keep previews under 180 characters unless full content was requested.
- Render an empty tag value as `No tags`; never emit an empty `Tags:` label.
- If no records match, say `No matching notes found.` without placeholders.
- For creation, use `### Note created`, followed by the confirmed title, ID,
  content preview, and normalized tags on separate lines.
- For deletion, use `### Note deleted` and show only the confirmed title and ID.
  Do not invent a preview or tags for a deleted record.
- Omit raw creation timestamps unless the user requested them.
""".strip()


CALENDAR_RESPONSE_CONTRACT = f"""
{COMMON_RESPONSE_CONTRACT}

Calendar presentation:
- For a list, start with `### Calendar events` and use:
  `| ID | Date | Time | Event | Duration |`
  `|---:|---|---|---|---:|`
- Sort returned events chronologically and express duration in minutes.
- When duration was omitted, state that the displayed 60-minute duration is the
  applied default.
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
- Calculate aggregate completion rates from total completed and total task
  counts, never by averaging per-group percentages.
- Clearly identify periods with no activity and never fabricate missing values.
""".strip()

__all__ = ["validate_visible_response"]
