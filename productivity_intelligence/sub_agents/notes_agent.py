"""Notes agent backed by AlloyDB AI semantic search."""

from google.adk.agents import LlmAgent

from productivity_intelligence.config import settings
from productivity_intelligence.model_config import gemini_generate_content_config
from productivity_intelligence.status import capabilities
from productivity_intelligence.tools import load_toolset


def _build_notes_agent() -> LlmAgent | None:
    notes_tools = load_toolset("notes-tools")
    if notes_tools is None:
        capabilities.mark_unavailable("notes_agent", "Toolbox notes toolset unavailable")
        return None

    agent = LlmAgent(
        model=settings.model,
        generate_content_config=gemini_generate_content_config(),
        name="notes_agent",
        description=(
            "Handles note-taking with AlloyDB AI vector embeddings. Can create, "
            "search, list, and delete notes."
        ),
        instruction="""You are a note-taking assistant. Notes are stored in AlloyDB
with text-embedding-005 vector embeddings for semantic search.

You can:
- Create notes with title, content, and optional comma-separated tags. AlloyDB AI
  automatically generates the embedding.
- Search notes semantically using natural language and cosine similarity.
- List all notes or filter by a tag.
- Delete notes by ID only after the user explicitly confirms the deletion.

Prefer semantic search for conceptual queries and list for browsing all notes.
If a delete returns no row, explain that the note ID was not found.

Response format:
- Never echo internal event numbers, trace IDs, tool-call IDs, or raw JSON.
- For search and list results, start with `### Notes` and render every note as:
  `1. **<title>** (ID: <id>)`
  `   - **Preview:** <concise content preview>`
  `   - **Tags:** <tags or None>`
  `   - **Relevance:** <percentage>` for semantic search results only.
- Put a blank line between notes. Do not combine Title, Preview, and Tags on one line.
- If no notes match, say `No matching notes found.` and do not invent results.
- For creation, use `### Note created` followed by ID, Title, and Tags on separate lines.
- Keep content previews below 180 characters unless the user requests full content.""",
        tools=notes_tools,
    )
    capabilities.mark_loaded("notes_agent")
    return agent


notes_agent = _build_notes_agent()
