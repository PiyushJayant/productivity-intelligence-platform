from __future__ import annotations

from pathlib import Path

import pytest

from setup.dr_contract import DrPlan, result_evidence
from setup.load_test import LoadTestContract, evaluate
from setup.migration_runner import Migration, apply_migrations, plan_migrations
from setup.observability_contract import (
    LOG_METRICS,
    POLICIES,
    ObservabilityContract,
    validate_inventory,
)
from setup.observability_inventory import canonical_inventory


class FakeCursor:
    def __init__(self, history: dict[str, str] | None = None, fail_sql: str = ""):
        self.history = history or {}
        self.rows: list[tuple[str, str]] = []
        self.operations: list[str] = []
        self.fail_sql = fail_sql

    def execute(self, operation: str, args=...) -> None:
        normalized = operation.strip()
        self.operations.append(normalized)
        if normalized.startswith("SELECT version, checksum"):
            self.rows = sorted(self.history.items())
        elif normalized.startswith("INSERT INTO schema_migrations"):
            self.history[args[0]] = args[1]
        elif normalized == self.fail_sql:
            raise RuntimeError("simulated migration failure")

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


def migration(version: str, sql: str = "SELECT 1") -> Migration:
    return Migration(version, Path(f"{version}.sql"), sql, f"checksum-{version}")


def test_migration_plan_rejects_database_ahead_of_image():
    cursor = FakeCursor({"9999_future": "checksum"})
    with pytest.raises(RuntimeError, match="newer than this image"):
        plan_migrations(cursor, [migration("0001_baseline")])


def test_migration_is_atomic_with_history_record():
    cursor = FakeCursor()
    assert apply_migrations(cursor, [migration("0001_baseline")]) == ["0001_baseline"]
    assert "BEGIN" in cursor.operations
    assert "COMMIT" in cursor.operations
    assert cursor.operations.index("BEGIN") < cursor.operations.index("COMMIT")
    operation_count = len(cursor.operations)
    assert apply_migrations(cursor, [migration("0001_baseline")]) == []
    assert "BEGIN" not in cursor.operations[operation_count:]


def test_migration_rolls_back_on_failure():
    cursor = FakeCursor(fail_sql="BROKEN")
    with pytest.raises(RuntimeError, match="simulated"):
        apply_migrations(cursor, [migration("0001_baseline", "BROKEN")])
    assert "ROLLBACK" in cursor.operations
    assert "COMMIT" not in cursor.operations


def test_load_contract_enforces_latency_and_error_budgets():
    contract = LoadTestContract(samples=4, p95_limit_seconds=5, p99_limit_seconds=10)
    assert evaluate([1, 2, 3, 4], 0, contract)["status"] == "pass"
    result = evaluate([1, 2, 11], 1, contract)
    assert result["status"] == "fail"
    assert set(result["violations"]) == {"p95_latency", "p99_latency", "error_rate"}


def test_dr_contract_requires_isolated_restore_target():
    plan = DrPlan("p", "r", "cluster", "instance", "cluster", "restore", "", 900, 300)
    with pytest.raises(ValueError, match="different cluster"):
        plan.validate()


def test_dr_result_fails_when_recovery_was_not_verified(monkeypatch):
    plan = DrPlan("p", "r", "source", "primary", "source-dr-restore", "restore", "", 10, 5)
    monkeypatch.setenv("DR_RESULT_OPERATION", "pitr_restore")
    monkeypatch.setenv("DR_OPERATION_ID", "operation-123")
    monkeypatch.setenv("DR_MEASURED_RTO_SECONDS", "12")
    monkeypatch.setenv("DR_MEASURED_RPO_SECONDS", "1")
    monkeypatch.setenv("DR_RECOVERY_VERIFIED", "false")
    result = result_evidence(plan)
    assert result["status"] == "fail"
    assert set(result["violations"]) == {"rto", "recovery_verification"}


def test_observability_inventory_requires_every_control():
    contract = ObservabilityContract(300, 0, 2000, 80, 70, False, True, False)
    inventory = {"alert_policies": sorted(POLICIES), "log_metrics": sorted(LOG_METRICS)}
    assert validate_inventory(inventory, contract) == []
    inventory["alert_policies"] = []
    assert validate_inventory(inventory, contract)


def test_production_observability_requires_enabled_notification_channels():
    contract = ObservabilityContract(300, 0, 2000, 80, 70, False, True, True)
    inventory = {
        "alert_policies": sorted(POLICIES),
        "alert_policy_details": {
            name: {"enabled": True, "notification_channels": []} for name in POLICIES
        },
        "log_metrics": sorted(LOG_METRICS),
    }
    missing = validate_inventory(inventory, contract)
    assert len([item for item in missing if item.startswith("notification_channel:")]) == len(
        POLICIES
    )


def test_cloud_inventory_is_normalized_without_provider_metadata():
    inventory = canonical_inventory(
        [{"displayName": "Policy", "name": "provider-id"}],
        [{"name": "projects/p/metrics/metric-name"}],
        [{"displayName": "Uptime", "name": "provider-id"}],
    )
    assert inventory == {
        "alert_policies": ["Policy"],
        "alert_policy_details": {
            "Policy": {"enabled": True, "notification_channels": []}
        },
        "log_metrics": ["metric-name"],
        "uptime_checks": ["Uptime"],
    }


def test_phase3_scripts_keep_billable_execution_gated():
    load = Path("setup/load_test.py").read_text(encoding="utf-8")
    dr = Path("setup/dr_drill.sh").read_text(encoding="utf-8")
    monitoring = Path("setup/monitoring.sh").read_text(encoding="utf-8")
    assert "PHASE5_ACTIVE" in load
    assert dr.count("require_phase5") >= 3
    assert "require_phase5" in monitoring
    assert "--path=/healthz" in monitoring


def test_phase3_operator_values_are_declared_in_single_env_template():
    template = Path(".env.example").read_text(encoding="utf-8")
    for name in (
        "LOAD_TEST_FIXTURE_EVENTS",
        "LOAD_TEST_MAX_BYTES_BILLED",
        "DR_RESTORE_CLUSTER",
        "DR_CONFIRM",
        "MONITORING_ALLOYDB_CPU_THRESHOLD",
        "MONITORING_REQUIRE_NOTIFICATION_CHANNELS",
    ):
        assert f"{name}=" in template
    assert "ALLOYDB_ACTIVATION_POLICY=NEVER" in template
