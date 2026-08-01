"""Offline observability contract and deployed-inventory validation."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

POLICIES = frozenset(
    {
        "Productivity Intelligence 5xx rate",
        "Productivity Intelligence p95 latency",
        "Productivity Intelligence AlloyDB connections",
        "Productivity Intelligence analytics read pool CPU",
        "Productivity Intelligence startup failures",
        "Productivity Intelligence Toolbox authorization failures",
        "Productivity Intelligence MCP failures",
        "Productivity Intelligence BigQuery errors",
    }
)
LOG_METRICS = frozenset(
    {
        "productivity_startup_failures",
        "productivity_toolbox_authorization_failures",
        "productivity_mcp_failures",
        "productivity_bigquery_errors",
    }
)


@dataclass(frozen=True)
class ObservabilityContract:
    alignment_seconds: int
    five_xx_rate_threshold: int
    p95_latency_ms: int
    alloydb_connection_threshold: int
    alloydb_cpu_threshold_percent: int
    uptime_enabled: bool
    log_metrics_enabled: bool
    notification_channels_required: bool

    def validate(self) -> None:
        if not 60 <= self.alignment_seconds <= 3600 or self.alignment_seconds % 60:
            raise ValueError("monitoring alignment must be 60..3600 seconds in minute steps")
        if self.five_xx_rate_threshold < 0:
            raise ValueError("5xx rate threshold must be non-negative")
        if not 1 <= self.p95_latency_ms <= 300_000:
            raise ValueError("p95 latency threshold must be 1..300000 ms")
        if self.alloydb_connection_threshold < 1:
            raise ValueError("AlloyDB connection threshold must be positive")
        if not 1 <= self.alloydb_cpu_threshold_percent <= 100:
            raise ValueError("AlloyDB CPU threshold must be 1..100 percent")

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "evidence_type": "observability_contract",
            "generated_at": datetime.now(UTC).isoformat(),
            "validated": True,
            "health_endpoint": "/healthz",
            "readiness_endpoint": "/readyz",
            "required_alert_policies": sorted(POLICIES),
            "required_log_metrics": sorted(LOG_METRICS) if self.log_metrics_enabled else [],
            "thresholds": asdict(self),
        }


def _boolean(name: str, default: str) -> bool:
    value = os.getenv(name, default).lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return value == "true"


def from_environment() -> ObservabilityContract:
    contract = ObservabilityContract(
        alignment_seconds=int(os.getenv("MONITORING_ALIGNMENT_SECONDS", "300")),
        five_xx_rate_threshold=int(os.getenv("MONITORING_5XX_RATE_THRESHOLD", "0")),
        p95_latency_ms=int(os.getenv("MONITORING_P95_LATENCY_MS", "2000")),
        alloydb_connection_threshold=int(
            os.getenv("MONITORING_ALLOYDB_CONNECTION_THRESHOLD", "80")
        ),
        alloydb_cpu_threshold_percent=int(
            os.getenv("MONITORING_ALLOYDB_CPU_THRESHOLD", "70")
        ),
        uptime_enabled=_boolean("ENABLE_UPTIME_CHECK", "false"),
        log_metrics_enabled=_boolean("ENABLE_LOG_METRICS", "true"),
        notification_channels_required=_boolean(
            "MONITORING_REQUIRE_NOTIFICATION_CHANNELS", "false"
        ),
    )
    contract.validate()
    return contract


def _string_set(value: object) -> set[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("inventory fields must be arrays of strings")
    return set(value)


def validate_inventory(inventory: dict[str, object], contract: ObservabilityContract) -> list[str]:
    policies = _string_set(inventory.get("alert_policies", []))
    metrics = _string_set(inventory.get("log_metrics", []))
    missing = [f"alert_policy:{name}" for name in sorted(POLICIES - policies)]
    if contract.log_metrics_enabled:
        missing.extend(f"log_metric:{name}" for name in sorted(LOG_METRICS - metrics))
    uptime_checks = _string_set(inventory.get("uptime_checks", []))
    if contract.uptime_enabled and "Productivity Intelligence hosted liveness" not in uptime_checks:
        missing.append("uptime_check:Productivity Intelligence hosted liveness")
    details = inventory.get("alert_policy_details", {})
    if not isinstance(details, dict):
        raise ValueError("alert_policy_details must be an object")
    for policy in sorted(POLICIES & policies):
        detail = details.get(policy, {})
        if not isinstance(detail, dict):
            raise ValueError("alert policy details must be objects")
        if detail.get("enabled") is False:
            missing.append(f"alert_policy_disabled:{policy}")
        channels = detail.get("notification_channels", [])
        if contract.notification_channels_required and not channels:
            missing.append(f"notification_channel:{policy}")
    return missing


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", help="Canonical deployed inventory JSON")
    parser.add_argument("--evidence", default=os.getenv("OBSERVABILITY_EVIDENCE_PATH", ""))
    args = parser.parse_args()
    contract = from_environment()
    evidence = contract.manifest()
    if args.inventory:
        inventory = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
        missing = validate_inventory(inventory, contract)
        evidence["inventory_validated"] = not missing
        evidence["missing_controls"] = missing
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.evidence:
        Path(args.evidence).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if evidence.get("inventory_validated") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
