"""Offline validation and structured evidence for AlloyDB resilience drills."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

RESOURCE_ID = re.compile(r"^[a-z][a-z0-9-]{0,61}[a-z0-9]$")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


@dataclass(frozen=True)
class DrPlan:
    project: str
    region: str
    source_cluster: str
    source_instance: str
    restore_cluster: str
    restore_instance: str
    pitr_timestamp: str
    rto_target_seconds: int
    rpo_target_seconds: int

    def validate(self) -> None:
        for label, value in (
            ("source cluster", self.source_cluster),
            ("source instance", self.source_instance),
            ("restore cluster", self.restore_cluster),
            ("restore instance", self.restore_instance),
        ):
            if not RESOURCE_ID.fullmatch(value):
                raise ValueError(f"{label} is not a valid resource ID")
        if self.restore_cluster == self.source_cluster:
            raise ValueError("PITR must restore out of place to a different cluster")
        if not self.restore_cluster.endswith("-dr-restore"):
            raise ValueError("restore cluster must end with '-dr-restore'")
        if self.pitr_timestamp and not UTC_TIMESTAMP.fullmatch(self.pitr_timestamp):
            raise ValueError("DR_PITR_TIMESTAMP must be an RFC3339 UTC timestamp")
        if self.rto_target_seconds <= 0 or self.rpo_target_seconds < 0:
            raise ValueError("RTO must be positive and RPO must be non-negative")

    def evidence(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "evidence_type": "disaster_recovery_plan",
            "generated_at": datetime.now(UTC).isoformat(),
            "mode": "plan",
            "cloud_change_performed": False,
            "ha_failover": {
                "scope": "zonal instance recovery; not a regional DR test",
                "source_instance": self.source_instance,
            },
            "pitr_restore": {
                "scope": "out-of-place recovery into an isolated cluster",
                "source_cluster": self.source_cluster,
                "restore_cluster": self.restore_cluster,
                "restore_instance": self.restore_instance,
                "point_in_time": self.pitr_timestamp or "operator-must-set-before-execution",
            },
            "targets": {
                "rto_seconds": self.rto_target_seconds,
                "rpo_seconds": self.rpo_target_seconds,
            },
            "operator_actions": [
                "capture a recovery marker before the drill",
                "verify application reads and writes after HA recovery",
                "verify row counts and the marker in the isolated PITR cluster",
                "record measured RTO and RPO before explicitly deleting the restore",
            ],
            "configuration": asdict(self),
        }


def from_environment() -> DrPlan:
    plan = DrPlan(
        project=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
        region=os.getenv("REGION", ""),
        source_cluster=os.getenv("ALLOYDB_CLUSTER", ""),
        source_instance=os.getenv("ALLOYDB_INSTANCE", ""),
        restore_cluster=os.getenv("DR_RESTORE_CLUSTER", ""),
        restore_instance=os.getenv("DR_RESTORE_INSTANCE", ""),
        pitr_timestamp=os.getenv("DR_PITR_TIMESTAMP", ""),
        rto_target_seconds=int(os.getenv("DR_RTO_TARGET_SECONDS", "900")),
        rpo_target_seconds=int(os.getenv("DR_RPO_TARGET_SECONDS", "300")),
    )
    plan.validate()
    return plan


def emit(payload: dict[str, object], output_path: str = "") -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output_path:
        Path(output_path).write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def result_evidence(plan: DrPlan) -> dict[str, object]:
    operation = os.getenv("DR_RESULT_OPERATION", "")
    if operation not in {"ha_failover", "pitr_restore"}:
        raise ValueError("DR_RESULT_OPERATION must be ha_failover or pitr_restore")
    operation_id = os.getenv("DR_OPERATION_ID", "")
    if not operation_id:
        raise ValueError("DR_OPERATION_ID is required for measured evidence")
    rto = int(os.getenv("DR_MEASURED_RTO_SECONDS", "-1"))
    rpo = int(os.getenv("DR_MEASURED_RPO_SECONDS", "-1"))
    verified = os.getenv("DR_RECOVERY_VERIFIED", "false").lower() == "true"
    if rto < 0 or rpo < 0:
        raise ValueError("measured RTO and RPO must be non-negative")
    violations = []
    if rto > plan.rto_target_seconds:
        violations.append("rto")
    if rpo > plan.rpo_target_seconds:
        violations.append("rpo")
    if not verified:
        violations.append("recovery_verification")
    return {
        "schema_version": 1,
        "evidence_type": "disaster_recovery_result",
        "generated_at": datetime.now(UTC).isoformat(),
        "operation": operation,
        "operation_id": operation_id,
        "measured_rto_seconds": rto,
        "measured_rpo_seconds": rpo,
        "recovery_verified": verified,
        "status": "pass" if not violations else "fail",
        "violations": violations,
        "targets": {
            "rto_seconds": plan.rto_target_seconds,
            "rpo_seconds": plan.rpo_target_seconds,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", default=os.getenv("DR_EVIDENCE_PATH", ""))
    parser.add_argument("--result", action="store_true")
    args = parser.parse_args()
    plan = from_environment()
    payload = result_evidence(plan) if args.result else plan.evidence()
    emit(payload, args.evidence)
    if payload.get("status") == "fail":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
