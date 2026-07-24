from __future__ import annotations

import os

TEST_ENV = {
    "APP_MODE": "full",
    "MODEL": "gemini-2.5-flash",
    "EMBEDDING_MODEL": "text-embedding-005",
    "GOOGLE_CLOUD_PROJECT": "test-project",
    "TOOLBOX_URL": "http://127.0.0.1:5000",
    "TOOLBOX_AUDIENCE": "http://127.0.0.1:5000",
    "BIGQUERY_MCP_URL": "https://bigquery.googleapis.com/mcp",
    "BIGQUERY_DATASET": "productivity_analytics",
    "ROUTER_MAX_OUTPUT_TOKENS": "512",
    "ROUTER_THINKING_BUDGET": "0",
    "SPECIALIST_MAX_OUTPUT_TOKENS": "768",
    "SPECIALIST_THINKING_BUDGET": "0",
    "ANALYTICS_MAX_OUTPUT_TOKENS": "1024",
    "ANALYTICS_THINKING_BUDGET": "256",
    "MODEL_TEMPERATURE": "0.2",
    "DEFAULT_TIMEZONE": "Asia/Kolkata",
    "DEFAULT_PAGE_SIZE": "20",
    "LOG_LEVEL": "INFO",
    "STRUCTURED_LOGGING": "true",
    "ENABLE_REQUEST_LOGGING": "true",
    "REQUEST_ID_HEADER": "X-Request-ID",
}

for key, value in TEST_ENV.items():
    os.environ.setdefault(key, value)
