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
    result = configure(apply=False)
    assert result["public_signup_disabled"] is True
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
