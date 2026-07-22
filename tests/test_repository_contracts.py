from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_assistant_image_contains_only_the_agent_runtime():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY . ." not in dockerfile
    assert "./agents/productivity_assistant" in dockerfile


def test_toolbox_configuration_is_valid_and_parameterized():
    config = yaml.safe_load((ROOT / "mcp_toolbox" / "tools.yaml").read_text(encoding="utf-8"))
    assert set(config["toolsets"]) == {"task-tools", "notes-tools", "calendar-tools"}
    statements = "\n".join(tool["statement"] for tool in config["tools"].values())
    assert "google_ml.embedding" in statements
    assert "NULLIF($4, '')::date" in statements


def test_schema_has_no_automatic_scann_index_or_password():
    schema = (ROOT / "setup" / "alloydb_schema.sql").read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS alloydb_scann" in schema
    assert "CREATE INDEX notes_embedding_scann_idx" not in schema
    assert "PASSWORD '" not in schema


def test_deployment_never_allows_unauthenticated_toolbox():
    deploy = (ROOT / "setup" / "deploy.sh").read_text(encoding="utf-8")
    toolbox_block = deploy.split("deploy_toolbox()", 1)[1].split("run_migration()", 1)[0]
    assert "--no-allow-unauthenticated" in toolbox_block
    assert "--set-secrets" in toolbox_block
    env_line = next(line for line in toolbox_block.splitlines() if "--set-env-vars" in line)
    assert "PASSWORD" not in env_line


def test_assistant_uses_global_vertex_endpoint_by_default():
    common = (ROOT / "setup" / "common.sh").read_text(encoding="utf-8")
    deploy = (ROOT / "setup" / "deploy.sh").read_text(encoding="utf-8")

    assert 'VERTEX_LOCATION="${GOOGLE_CLOUD_LOCATION:-global}"' in common
    assert "GOOGLE_CLOUD_LOCATION=${VERTEX_LOCATION}" in deploy


def test_destructive_agent_prompts_require_confirmation():
    for filename in ("task_agent.py", "notes_agent.py", "calendar_agent.py"):
        prompt = (
            ROOT / "productivity_assistant" / "sub_agents" / filename
        ).read_text(encoding="utf-8")
        assert "explicitly confirms" in prompt
