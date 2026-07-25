"""Notes agent backed by AlloyDB AI semantic search."""

from google.adk.agents import LlmAgent

from productivity_intelligence.config import settings
from productivity_intelligence.context_policy import (
    compact_specialist_history,
    record_model_usage,
)
from productivity_intelligence.guardrails import enforce_destructive_confirmation
from productivity_intelligence.model_config import gemini_generate_content_config
from productivity_intelligence.response_contract import NOTES_RESPONSE_CONTRACT
from productivity_intelligence.status import capabilities
from productivity_intelligence.tools import load_toolset


def _build_notes_agent() -> LlmAgent | None:
    notes_tools = load_toolset("notes-tools")
    if notes_tools is None:
        capabilities.mark_unavailable("notes_agent", "Toolbox notes toolset unavailable")
        return None

    agent = LlmAgent(
        model=settings.model,
        generate_content_config=gemini_generate_content_config("specialist"),
        name="notes_agent",
        description=(
            "Handles note-taking with AlloyDB AI vector embeddings. Can create, "
            "search, list, and delete notes."
        ),
        instruction=f"""You are a note-taking assistant. Notes are stored in AlloyDB
with {settings.embedding_model} vector embeddings for semantic search.

You can:
- Create notes with title, content, and optional comma-separated tags. AlloyDB AI
  automatically generates the embedding.
- Search notes semantically using natural language and cosine similarity.
- List all notes or filter by a tag.
- Delete notes by ID only after the user explicitly confirms the deletion.

When the user confirms multiple exact IDs, call `delete_notes` once instead of
repeating `delete_note`. Report requested IDs that were absent without claiming
success.

Prefer semantic search for conceptual queries and list for browsing all notes.
If a delete returns no row, explain that the note ID was not found.

Before creating a note, distinguish actual note content from an instruction to
perform work. If the requested content is vague or could mean changing the
application (for example, "add notes to create logs"), ask one concise question
about what should be saved. Do not save the user's instruction itself as the
note body. When the user supplied clear content, infer a concise title if needed,
use empty tags when omitted, and create the note without redundant questions.

{NOTES_RESPONSE_CONTRACT}""",
        tools=notes_tools,
        before_tool_callback=enforce_destructive_confirmation,
        before_model_callback=compact_specialist_history,
        after_model_callback=record_model_usage,
    )
    capabilities.mark_loaded("notes_agent")
    return agent


notes_agent = _build_notes_agent()
