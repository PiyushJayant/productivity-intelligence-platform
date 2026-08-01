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
    assert set(config["toolsets"]) == {
        "task-tools",
        "notes-tools",
        "calendar-tools",
        "identity-admin-tools",
        "privacy-admin-tools",
    }
    statements = "\n".join(tool["statement"] for tool in config["tools"].values())
    assert "google_ml.embedding" in statements
    assert "${EMBEDDING_MODEL}" in statements
    assert "NULLIF($4, '')::date" in statements
    assert "NULLIF($5, '')::timestamptz" in statements
    assert "${DEFAULT_TIMEZONE}" in statements
    assert "to_char(time, 'HH24:MI')" in statements
    assert statements.count("LIMIT ${DEFAULT_PAGE_SIZE}") == 3
    assert "update_tasks_status" in config["tools"]
    assert "delete_tasks" in config["tools"]
    assert "delete_notes" in config["tools"]
    assert "delete_events" in config["tools"]
    assert "string_to_array" in statements
    agent_tools = {
        name
        for toolset in ("task-tools", "notes-tools", "calendar-tools")
        for name in config["toolsets"][toolset]
    }
    assert not agent_tools & {
        "authorize_identity",
        "list_tenant_members",
        "provision_tenant_member",
        "update_tenant_member_role",
        "revoke_tenant_member",
        "request_subject_erasure",
        "list_subject_erasure_requests",
    }
    for name in agent_tools:
        tool = config["tools"][name]
        parameter_names = [parameter["name"] for parameter in tool["parameters"]]
        assert parameter_names[-2:] == ["tenant_id", "subject_id"]
        assert "tenant_id" in tool["statement"]
        positions = {
            int(position) for position in re.findall(r"\$(\d+)", tool["statement"])
        }
        assert positions == set(range(1, len(parameter_names) + 1))


def test_identity_and_tenant_boundary_is_fail_closed():
    identity = (
        ROOT / "productivity_intelligence" / "identity.py"
    ).read_text(encoding="utf-8")
    runtime_tools = (
        ROOT / "productivity_intelligence" / "tools.py"
    ).read_text(encoding="utf-8")
    schema = (ROOT / "setup" / "alloydb_schema.sql").read_text(encoding="utf-8")
    provision = (ROOT / "setup" / "provision.sh").read_text(encoding="utf-8")

    assert "verify_firebase_token" in identity
    assert "token issuer is invalid" in identity
    assert "No verified request identity" in identity
    assert '"tenant_id": current_tenant_id' in runtime_tools
    assert '"subject_id": current_subject_id' in runtime_tools
    assert "strict=True" in runtime_tools
    assert "CREATE TABLE IF NOT EXISTS tenant_memberships" in schema
    assert "enforce_active_membership" in schema
    assert "004_identity_and_tenant_ownership" in schema
    assert "identitytoolkit.googleapis.com" in provision


def test_schema_uses_exact_vector_search_without_scann_or_password():
    schema = (ROOT / "setup" / "alloydb_schema.sql").read_text(encoding="utf-8")
    assert "alloydb_scann" not in schema
    assert "CREATE INDEX notes_embedding_scann_idx" not in schema
    assert "VECTOR(__EMBEDDING_DIMENSIONS__)" in schema
    assert "due_at        TIMESTAMPTZ" in schema
    assert "002_task_deadlines" in schema
    assert "CREATE TABLE IF NOT EXISTS activity_events" in schema
    assert "003_activity_ledger" in schema
    assert "SECURITY DEFINER" in schema
    assert "REVOKE ALL ON activity_events FROM productivity_app" in schema
    activity_table = schema.split(
        "CREATE TABLE IF NOT EXISTS activity_events", 1
    )[1].split(");", 1)[0]
    for private_field in ("title", "description", "content", "tags"):
        assert private_field not in activity_table
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


def test_runtime_includes_cross_platform_timezone_database():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "tzdata==" in requirements


def test_migration_image_contains_the_complete_versioned_migration_runtime():
    dockerfile = (ROOT / "Dockerfile.migrate").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "COPY setup ./setup" in dockerfile
    assert '["python", "-m", "setup.migrate"]' in dockerfile
    for required_path in (
        "!setup/__init__.py",
        "!setup/migration_runner.py",
        "!setup/privacy_job.py",
        "!setup/migrations/",
        "!setup/migrations/*.sql",
    ):
        assert required_path in dockerignore


def test_environment_initializer_generates_every_local_secret():
    initializer = (ROOT / "setup" / "init_env.py").read_text(encoding="utf-8")
    for secret in (
        "ADMIN_DB_PASSWORD",
        "APP_DB_PASSWORD",
        "ANALYTICS_DB_PASSWORD",
        "PRIVACY_DB_PASSWORD",
        "PSEUDONYMIZATION_KEY",
    ):
        assert f'"{secret}"' in initializer


def test_deployment_requires_an_explicit_project_and_installs_monitoring():
    common = (ROOT / "setup" / "common.sh").read_text(encoding="utf-8")
    deploy = (ROOT / "setup" / "deploy.sh").read_text(encoding="utf-8")
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert 'PROJECT_ID="${GOOGLE_CLOUD_PROJECT}"' in common
    assert "GOOGLE_CLOUD_PROJECT=your-project-id" in example
    full_block = deploy.split("  full)", 1)[1].split("    ;;", 1)[0]
    assert '"${SCRIPT_DIR}/monitoring.sh"' in full_block
    build_tag_actions = (
        '"${ACTION}" =~ '
        "^(toolbox|migrate|assistant|lifecycle|privacy|privacy-erase|deploy)$"
    )
    assert build_tag_actions in deploy


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
    assert '${#BIGQUERY_DATASET}" -le 1024' in common
    assert "{0,1023}" not in common


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
    assert "resume) resume_application" in deploy
    assert "suspend) suspend_application" in deploy
    assert "cost-status) cost_status" in deploy


def test_budget_lookup_and_cleanup_compare_exact_display_names():
    provision = (ROOT / "setup" / "provision.sh").read_text(encoding="utf-8")
    cleanup = (ROOT / "cleanup" / "cleanup_all.sh").read_text(encoding="utf-8")

    assert 'item.get("displayName") == target' in provision
    assert 'item.get("displayName") == target' in cleanup
    assert "--filter=\"displayName=" not in provision


def test_builds_are_immutable_and_reused():
    deploy = (ROOT / "setup" / "deploy.sh").read_text(encoding="utf-8")
    assert 'git -C "${REPO_ROOT}" rev-parse HEAD' in deploy
    assert "SKIP_EXISTING_IMAGES" in deploy
    assert "$(date " not in deploy


def test_bigquery_bounded_procedure_aggregates_inside_alloydb():
    setup = (ROOT / "setup" / "bigquery_setup.py").read_text(encoding="utf-8")
    assert setup.count("FROM EXTERNAL_QUERY(") == 1
    assert "CREATE OR REPLACE PROCEDURE" in setup
    assert "p_start_date DATE" in setup
    assert "p_end_date DATE" in setup
    assert "p_tenant_id STRING" in setup
    assert "p_subject_id STRING" in setup
    assert "DATE_DIFF(p_end_date, p_start_date, DAY)" in setup
    assert "e.occurred_at >= b.start_at" in setup
    assert "e.occurred_at < b.end_at" in setup
    assert '"SELECT * FROM EXTERNAL_QUERY(%T, %T)"' in setup
    assert "BIGQUERY_ANALYTICS_PROCEDURE" in setup
    assert "FROM tasks" not in setup
    assert "FROM notes" not in setup
    assert "FROM events" not in setup
    assert "latest_status" in setup
    assert "DROP VIEW IF EXISTS" in setup
    assert "m.status = 'active'" in setup
    assert setup.count("AT TIME ZONE '{timezone}'") >= 2


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
    assert "resolve_relative_datetime" in task
    assert "resolve_relative_datetime" in calendar
    assert "function call by itself is never a complete answer" in response_contract
    assert "setup/evaluate_contracts.py" in workflow


def test_analytics_agent_exposes_only_parameterized_domain_query():
    agent = (
        ROOT / "productivity_intelligence" / "sub_agents" / "analytics_agent.py"
    ).read_text(encoding="utf-8")
    tools = (
        ROOT / "productivity_intelligence" / "analytics_tools.py"
    ).read_text(encoding="utf-8")

    assert "get_productivity_trends" in agent
    assert "execute_sql_readonly" not in agent
    assert "CALL `{dataset}.{settings.bigquery_analytics_procedure}`" in tools
    assert "ANALYTICS_MAX_RANGE_DAYS" not in tools
    assert "analytics_max_range_days" in tools


def test_scheduled_lifecycle_is_opt_in_private_and_cleanable():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    provision = (ROOT / "setup" / "provision.sh").read_text(encoding="utf-8")
    deploy = (ROOT / "setup" / "deploy.sh").read_text(encoding="utf-8")
    cleanup = (ROOT / "cleanup" / "cleanup_all.sh").read_text(encoding="utf-8")

    assert "ENABLE_SCHEDULED_LIFECYCLE=false" in example
    assert "!setup/lifecycle.py" in dockerignore
    assert "alloydb.instances.get,alloydb.instances.update" in provision
    assert "roles/alloydb.admin" not in provision
    assert "services identity create --service=alloydb.googleapis.com" in provision
    assert "--oauth-service-account-email=${SCHEDULER_SA}" in deploy
    assert "--role=roles/run.invoker" in deploy
    assert "LIFECYCLE_JOB_NAME" in cleanup


def test_candidate_verification_runs_mode_aware_end_to_end_smoke_checks():
    deploy = (ROOT / "setup" / "deploy.sh").read_text(encoding="utf-8")
    verify = deploy.split("verify_candidate()", 1)[1].split("promote()", 1)[0]

    assert '"${readiness_file}" "${APP_MODE}"' in verify
    assert '"${SCRIPT_DIR}/smoke_test.py"' in verify
    assert 'assistant_smoke_arg=("--assistant-url=${assistant_url}")' in verify
    assert 'if [[ "${AUTH_MODE}" == "disabled" ]]' in verify
    assert '--connection="${BIGQUERY_CONNECTION_ID}"' in verify
    assert 'if [[ "${APP_MODE}" == "full" ]]' in verify


def test_complete_suspend_is_reversible_and_quiesces_request_driven_cost():
    deploy = (ROOT / "setup" / "deploy.sh").read_text(encoding="utf-8")
    suspend = deploy.split("suspend_application()", 1)[1].split(
        "resume_application()", 1
    )[0]
    resume = deploy.split("resume_application()", 1)[1].split(
        "cost_status()", 1
    )[0]

    assert "remove_assistant_public_access" in suspend
    assert "set_schedulers_state pause" in suspend
    assert '"${PRIVACY_JOB_NAME}-retention"' in suspend
    assert "remove_hosted_uptime_check" in suspend
    assert '"${ASSISTANT_SERVICE_NAME}" 0' in suspend
    assert '"${TOOLBOX_SERVICE_NAME}" 0' in suspend
    assert "suspend_alloydb" in suspend
    assert "restore_assistant_public_access" in resume
    assert "resume_alloydb" in resume
    assert 'if [[ "${ENABLE_SCHEDULED_PRIVACY}" == "true" ]]' in resume
    assert 'instances+=("${ALLOYDB_READ_POOL}")' in deploy
    assert "ALLOYDB_ADDITIONAL_INSTANCES" in deploy


def test_phase2_security_controls_are_dry_run_first_and_explicit():
    common = (ROOT / "setup" / "common.sh").read_text(encoding="utf-8")
    security = (ROOT / "setup" / "security_setup.sh").read_text(encoding="utf-8")
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "VPC_SC_MODE=dry-run" in example
    assert "VPC_SC_ENFORCEMENT_ACK=NOT_ACKNOWLEDGED" in example
    assert "I_ACKNOWLEDGE_VPC_SC_LOCKOUT_RISK" in common
    assert "perimeters dry-run create" in security
    assert "perimeters dry-run update" in security
    assert 'show --encryption_service_account' in security
    assert "secretmanager.googleapis.com" in security


def test_read_pool_routing_cannot_drift_from_feature_flag():
    common = (ROOT / "setup" / "common.sh").read_text(encoding="utf-8")
    assert '"${ANALYTICS_ALLOYDB_INSTANCE}" == "${ALLOYDB_READ_POOL}"' in common
    assert '"${ANALYTICS_ALLOYDB_INSTANCE}" == "${ALLOYDB_INSTANCE}"' in common


def test_billing_gate_allows_only_suspension_and_cost_inspection():
    deploy = (ROOT / "setup" / "deploy.sh").read_text(encoding="utf-8")
    phase5 = (ROOT / "setup" / "phase5.sh").read_text(encoding="utf-8")

    assert '"${ACTION}" != "suspend" && "${ACTION}" != "cost-status"' in deploy
    assert "require_phase5" in deploy
    assert "preflight_project_access" in deploy
    assert 'verify) "${SCRIPT_DIR}/deploy.sh" verify' in phase5
    assert 'promote) "${SCRIPT_DIR}/deploy.sh" promote' in phase5
    assert '"${SCRIPT_DIR}/deploy.sh" rollback "$2"' in phase5
    assert 'rollback) rollback "${2:-}"' in deploy
