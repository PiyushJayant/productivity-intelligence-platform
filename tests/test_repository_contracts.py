import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_assistant_image_contains_only_the_agent_runtime():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY . ." not in dockerfile
    assert "./agents/productivity_intelligence" in dockerfile


def test_product_and_cloud_resource_names_are_consistent():
    agent = (ROOT / "productivity_intelligence" / "agent.py").read_text(encoding="utf-8")
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert 'name="productivity_orchestrator"' in agent
    assert "ASSISTANT_SERVICE_NAME=productivity-intelligence" in example
    assert "TOOLBOX_SERVICE_NAME=productivity-toolbox" in example
    assert "ALLOYDB_DATABASE=productivity_platform" in example


def test_toolbox_configuration_is_valid_and_parameterized():
    config = yaml.safe_load((ROOT / "mcp_toolbox" / "tools.yaml").read_text(encoding="utf-8"))
    assert set(config["toolsets"]) == {"task-tools", "notes-tools", "calendar-tools"}
    statements = "\n".join(tool["statement"] for tool in config["tools"].values())
    assert "google_ml.embedding" in statements
    assert "${EMBEDDING_MODEL}" in statements
    assert "NULLIF($4, '')::date" in statements
    assert statements.count("LIMIT ${DEFAULT_PAGE_SIZE}") == 3


def test_schema_uses_exact_vector_search_without_scann_or_password():
    schema = (ROOT / "setup" / "alloydb_schema.sql").read_text(encoding="utf-8")
    assert "alloydb_scann" not in schema
    assert "CREATE INDEX notes_embedding_scann_idx" not in schema
    assert "VECTOR(__EMBEDDING_DIMENSIONS__)" in schema
    assert "PASSWORD '" not in schema


def test_deployment_never_allows_unauthenticated_toolbox():
    deploy = (ROOT / "setup" / "deploy.sh").read_text(encoding="utf-8")
    toolbox_block = deploy.split("deploy_toolbox()", 1)[1].split("run_migration()", 1)[0]
    assert "--no-allow-unauthenticated" in toolbox_block
    assert "--set-secrets" in toolbox_block
    env_line = next(line for line in toolbox_block.splitlines() if "--set-env-vars" in line)
    assert "PASSWORD" not in env_line


def test_assistant_uses_global_vertex_endpoint_by_default():
    deploy = (ROOT / "setup" / "deploy.sh").read_text(encoding="utf-8")
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "GOOGLE_CLOUD_LOCATION=global" in example
    assert "GOOGLE_CLOUD_LOCATION=${VERTEX_LOCATION}" in deploy


def test_deployment_requires_an_explicit_project_and_installs_monitoring():
    common = (ROOT / "setup" / "common.sh").read_text(encoding="utf-8")
    deploy = (ROOT / "setup" / "deploy.sh").read_text(encoding="utf-8")
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert 'PROJECT_ID="${GOOGLE_CLOUD_PROJECT}"' in common
    assert "GOOGLE_CLOUD_PROJECT=your-project-id" in example
    full_block = deploy.split("  full)", 1)[1].split("    ;;", 1)[0]
    assert '"${SCRIPT_DIR}/monitoring.sh"' in full_block
    assert '"${ACTION}" =~ ^(toolbox|migrate|assistant|lifecycle|deploy)$' in deploy


def test_single_environment_file_is_the_deployment_source_of_truth():
    common = (ROOT / "setup" / "common.sh").read_text(encoding="utf-8")
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    provision = (ROOT / "setup" / "provision.sh").read_text(encoding="utf-8")

    assert 'ENV_FILE="${REPO_ROOT}/.env"' in common
    assert 'source "${ENV_FILE}"' in common
    assert "ADMIN_DB_PASSWORD=" in example
    assert "APP_DB_PASSWORD=" in example
    assert "ANALYTICS_DB_PASSWORD=" in example
    assert "ensure_secret_from_env" in provision
    assert "openssl rand" not in common


def test_environment_template_covers_every_required_deployment_variable():
    common = (ROOT / "setup" / "common.sh").read_text(encoding="utf-8")
    example_lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    required_block = re.search(
        r"REQUIRED_CONFIG=\(\n(?P<body>.*?)\n\)",
        common,
        re.DOTALL,
    )
    assert required_block is not None
    required = set(required_block.group("body").split())
    configured_keys = [
        line.split("=", 1)[0]
        for line in example_lines
        if line and not line.startswith("#") and "=" in line
    ]

    assert len(configured_keys) == len(set(configured_keys))
    assert required <= set(configured_keys)


def test_demo_cost_profile_has_hard_scaling_and_database_guards():
    common = (ROOT / "setup" / "common.sh").read_text(encoding="utf-8")
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    provision = (ROOT / "setup" / "provision.sh").read_text(encoding="utf-8")
    deploy = (ROOT / "setup" / "deploy.sh").read_text(encoding="utf-8")

    assert "ALLOYDB_MACHINE_TYPE=c4a-highmem-1" in example
    assert "demo profile requires min=0 and max=1" in common
    assert '--machine-type="${ALLOYDB_MACHINE_TYPE}"' in provision
    assert "--cpu-count=2" not in provision
    assert "resume) resume_alloydb" in deploy
    assert "suspend) suspend_alloydb" in deploy
    assert "cost-status) cost_status" in deploy


def test_builds_are_immutable_and_reused():
    deploy = (ROOT / "setup" / "deploy.sh").read_text(encoding="utf-8")
    assert 'git -C "${REPO_ROOT}" rev-parse HEAD' in deploy
    assert "SKIP_EXISTING_IMAGES" in deploy
    assert "$(date " not in deploy


def test_bigquery_aggregation_is_pushed_to_alloydb():
    setup = (ROOT / "setup" / "bigquery_setup.py").read_text(encoding="utf-8")
    assert setup.count("FROM EXTERNAL_QUERY(") == 2
    assert "GROUP BY created_at::date, priority" in setup
    assert "GROUP BY date" in setup


def test_destructive_agent_prompts_require_confirmation():
    for filename in ("task_agent.py", "notes_agent.py", "calendar_agent.py"):
        prompt = (
            ROOT / "productivity_intelligence" / "sub_agents" / filename
        ).read_text(encoding="utf-8")
        assert "explicitly confirms" in prompt


def test_response_contract_date_resolution_and_evaluations_are_shared():
    task = (ROOT / "productivity_intelligence" / "sub_agents" / "task_agent.py").read_text(
        encoding="utf-8"
    )
    calendar = (
        ROOT / "productivity_intelligence" / "sub_agents" / "calendar_agent.py"
    ).read_text(encoding="utf-8")
    response_contract = (
        ROOT / "productivity_intelligence" / "response_contract.py"
    ).read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "TASK_RESPONSE_CONTRACT" in task
    assert "CALENDAR_RESPONSE_CONTRACT" in calendar
    assert "resolve_relative_date" in task
    assert "resolve_relative_date" in calendar
    assert "function call by itself is never a complete answer" in response_contract
    assert "setup/evaluate_contracts.py" in workflow


def test_scheduled_lifecycle_is_opt_in_private_and_cleanable():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    provision = (ROOT / "setup" / "provision.sh").read_text(encoding="utf-8")
    deploy = (ROOT / "setup" / "deploy.sh").read_text(encoding="utf-8")
    cleanup = (ROOT / "cleanup" / "cleanup_all.sh").read_text(encoding="utf-8")

    assert "ENABLE_SCHEDULED_LIFECYCLE=false" in example
    assert "alloydb.instances.get,alloydb.instances.update" in provision
    assert "roles/alloydb.admin" not in provision
    assert "--oauth-service-account-email=${SCHEDULER_SA}" in deploy
    assert "--role=roles/run.invoker" in deploy
    assert "LIFECYCLE_JOB_NAME" in cleanup


def test_candidate_verification_runs_mode_aware_end_to_end_smoke_checks():
    deploy = (ROOT / "setup" / "deploy.sh").read_text(encoding="utf-8")
    verify = deploy.split("verify_candidate()", 1)[1].split("promote()", 1)[0]

    assert '"${readiness_file}" "${APP_MODE}"' in verify
    assert '"${SCRIPT_DIR}/smoke_test.py"' in verify
    assert '--assistant-url="${assistant_url}"' in verify
    assert 'if [[ "${APP_MODE}" == "full" ]]' in verify
