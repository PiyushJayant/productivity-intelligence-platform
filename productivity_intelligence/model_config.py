"""Shared Gemini request configuration for every ADK agent."""

from google.genai import types

from productivity_intelligence.config import settings


def gemini_generate_content_config(agent_kind: str = "specialist") -> types.GenerateContentConfig:
    """Return cost-bounded generation and retry settings for an agent role."""

    budgets = {
        "router": (
            settings.router_max_output_tokens,
            settings.router_thinking_budget,
        ),
        "specialist": (
            settings.specialist_max_output_tokens,
            settings.specialist_thinking_budget,
        ),
        "analytics": (
            settings.analytics_max_output_tokens,
            settings.analytics_thinking_budget,
        ),
    }
    if agent_kind not in budgets:
        raise ValueError(f"Unknown agent kind: {agent_kind}")
    max_output_tokens, thinking_budget = budgets[agent_kind]

    return types.GenerateContentConfig(
        temperature=settings.model_temperature,
        max_output_tokens=max_output_tokens,
        thinking_config=types.ThinkingConfig(
            include_thoughts=False,
            thinking_budget=thinking_budget,
        ),
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
