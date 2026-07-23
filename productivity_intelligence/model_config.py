"""Shared Gemini request configuration for every ADK agent."""

from google.genai import types


def gemini_generate_content_config() -> types.GenerateContentConfig:
    """Return bounded retries for transient Vertex AI capacity failures."""

    return types.GenerateContentConfig(
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(
                attempts=5,
                initial_delay=1.0,
                max_delay=16.0,
                exp_base=2.0,
                jitter=1.0,
                http_status_codes=[429, 500, 502, 503, 504],
            )
        )
    )
