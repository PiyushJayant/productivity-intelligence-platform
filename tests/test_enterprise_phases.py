from __future__ import annotations

import json
from pathlib import Path

import pytest

from setup.evaluate_cdc_trigger import Metrics, decision
from setup.identity_setup import configure
from setup.migration_runner import discover_migrations


def test_migrations_are_ordered_unique_and_checksummed():
    migrations = discover_migrations(Path("setup"))
    assert [item.version for item in migrations] == [
        "0001_baseline",
        "0002_privacy_taxonomy",
        "0003_tenant_membership_lifecycle",
        "0004_federation_guardrails",
        "0005_privacy_operations",
    ]
    assert all(len(item.checksum) == 64 for item in migrations)


def test_phase3_migration_contains_privacy_and_taxonomy_contracts():
    sql = Path("setup/migrations/0002_privacy_taxonomy.sql").read_text()
    for contract in (
        "productivity_topics",
        "subject_token",
        "rollup_and_purge_activity",
        "privacy_erasure_requests",
        "erase_subject_data",
    ):
        assert contract in sql


def test_membership_migration_enforces_revocation_and_owner_invariants():
    sql = Path("setup/migrations/0003_tenant_membership_lifecycle.sql").read_text()
    for contract in (
        "authorize_identity",
        "m.status = 'active'",
        "s.disabled_at IS NULL",
        "the last tenant owner cannot be demoted",
        "the last tenant owner cannot be revoked",
        "CREATE OR REPLACE FUNCTION enforce_active_membership",
    ):
        assert contract in sql


def test_federation_migration_is_read_only_bounded_and_indexed():
    sql = Path("setup/migrations/0004_federation_guardrails.sql").read_text()
    for contract in (
        "activity_events_tenant_period_type_idx",
        "activity_events_tenant_entity_latest_idx",
        "default_transaction_read_only = on",
        "application_name = 'productivity-federation'",
        "REVOKE CREATE ON SCHEMA public",
    ):
        assert contract in sql
    migrate = Path("setup/migrate.py").read_text()
    assert "SET statement_timeout" in migrate
    assert "SET idle_in_transaction_session_timeout" in migrate


def test_privacy_operations_are_least_privilege_and_ingestion_time():
    sql = Path("setup/migrations/0005_privacy_operations.sql").read_text()
    for contract in (
        "tasks_assign_topic",
        "request_subject_erasure",
        "list_unpseudonymized_activity",
        "apply_activity_subject_tokens",
        "mark_erasure_request_failed",
        "TO productivity_privacy",
        "issuer = 'urn:productivity-intelligence:erased'",
    ):
        assert contract in sql
    assert "GRANT SELECT ON activity_events TO productivity_privacy" not in sql


def test_cdc_evaluator_never_changes_infrastructure():
    result = decision(Metrics(6, 11, 71, 11, 12, 7))
    assert result["recommendation"] == "migrate_to_native"
    assert result["automatic_change_performed"] is False


def test_cdc_evaluator_keeps_healthy_federation():
    result = decision(Metrics(1, 2, 20, 0, 2, 30))
    assert result["recommendation"] == "remain_federated"


def test_identity_plan_is_offline(monkeypatch):
    monkeypatch.setenv("IDENTITY_PLATFORM_PROJECT_ID", "test-project")
    monkeypatch.setenv("BOOTSTRAP_IDP_SUBJECT", "identity-uid")
    monkeypatch.setenv("IDENTITY_CONTROLLED_REGISTRATION", "true")
    monkeypatch.setenv("IDENTITY_BEFORE_CREATE_URL", "")
    monkeypatch.setenv("IDENTITY_PASSWORD_MIN_LENGTH", "12")
    monkeypatch.setenv("IDENTITY_PASSWORD_MAX_LENGTH", "128")
    result = configure(apply=False)
    assert result["public_signup_disabled"] is False
    assert result["controlled_registration"] is True
    assert result["passwordPolicyConfig"]["enforcementState"] == "ENFORCE"
    assert result["bootstrap_subject"] == "identity-uid"


def test_phase5_contract_is_explicit_and_disabled_by_default():
    template = Path(".env.example").read_text()
    phase5 = Path("setup/phase5.sh").read_text()
    assert "ENABLE_BILLABLE_PHASE=false" in template
    assert "BILLING_ACK=NOT_ACKNOWLEDGED" in template
    assert "I_ACKNOWLEDGE_GCP_CHARGES" in phase5
    assert "billing projects describe" in phase5


def test_native_contract_is_partitioned_and_pseudonymous():
    source = Path("setup/native_bigquery_setup.py").read_text()
    assert "require_partition_filter = True" in source
    assert "clustering_fields" in source
    assert "p_subject_token" in source


def test_trigger_cli_input_contract(tmp_path):
    payload = {
        "p95_seconds": 1,
        "p99_seconds": 2,
        "read_pool_cpu_percent": 10,
        "crud_degradation_percent": 0,
        "concurrent_users": 1,
        "sustained_days": 7,
    }
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(payload))
    assert Metrics(**json.loads(path.read_text())).p95_seconds == 1


@pytest.mark.parametrize("placeholder", ["", "replace-with-identity-platform-uid"])
def test_identity_plan_rejects_missing_or_placeholder_subject(monkeypatch, placeholder):
    monkeypatch.setenv("IDENTITY_PLATFORM_PROJECT_ID", "test-project")
    monkeypatch.setenv("BOOTSTRAP_IDP_SUBJECT", placeholder)
    with pytest.raises(ValueError):
        configure(apply=False)
