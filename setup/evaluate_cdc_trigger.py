"""Create and verify non-mutating evidence for the CDC migration decision."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
MINIMUM_SAMPLES = 100
MAX_EVIDENCE_AGE_HOURS = 24


@dataclass(frozen=True)
class Metrics:
    p95_seconds: float
    p99_seconds: float
    read_pool_cpu_percent: float
    crud_degradation_percent: float
    concurrent_users: int
    sustained_days: int
    sample_count: int = MINIMUM_SAMPLES

    def validate(self) -> None:
        values = (
            self.p95_seconds,
            self.p99_seconds,
            self.read_pool_cpu_percent,
            self.crud_degradation_percent,
        )
        if any(value < 0 for value in values):
            raise ValueError("CDC metrics cannot be negative")
        if not 0 <= self.read_pool_cpu_percent <= 100:
            raise ValueError("read_pool_cpu_percent must be between 0 and 100")
        if self.concurrent_users < 0 or self.sustained_days < 0:
            raise ValueError("CDC counts cannot be negative")
        if self.sample_count < MINIMUM_SAMPLES:
            raise ValueError(f"sample_count must be at least {MINIMUM_SAMPLES}")


def decision(metrics: Metrics) -> dict[str, object]:
    metrics.validate()
    sustained = metrics.sustained_days >= 7
    warnings = {
        "p95": metrics.p95_seconds > 3,
        "p99": metrics.p99_seconds > 7,
        "read_pool_cpu": metrics.read_pool_cpu_percent > 40,
        "crud_degradation": metrics.crud_degradation_percent > 5,
        "concurrency": metrics.concurrent_users >= 5,
    }
    hard = {
        "p95_sustained": metrics.p95_seconds > 5 and sustained,
        "p99": metrics.p99_seconds > 10,
        "read_pool_cpu_sustained": metrics.read_pool_cpu_percent > 70 and sustained,
        "crud_degradation_sustained": (
            metrics.crud_degradation_percent > 10 and sustained
        ),
        "concurrency_sustained": metrics.concurrent_users >= 10 and sustained,
    }
    return {
        "recommendation": (
            "migrate_to_native"
            if any(hard.values())
            else "investigate"
            if any(warnings.values())
            else "remain_federated"
        ),
        "warnings": warnings,
        "hard_triggers": hard,
        "automatic_change_performed": False,
    }


def build_evidence(metrics: Metrics, *, measured_at: datetime | None = None) -> dict[str, Any]:
    measured = measured_at or datetime.now(UTC)
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": "cdc_migration_trigger",
        "measured_at": measured.astimezone(UTC).isoformat(),
        "metrics": asdict(metrics),
        **decision(metrics),
    }


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def evidence_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def verify_evidence(
    payload: dict[str, Any],
    expected_sha256: str,
    *,
    now: datetime | None = None,
) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported CDC evidence schema")
    if payload.get("evidence_type") != "cdc_migration_trigger":
        raise ValueError("invalid CDC evidence type")
    if evidence_sha256(payload) != expected_sha256.lower():
        raise ValueError("CDC evidence checksum mismatch")
    measured_at = datetime.fromisoformat(str(payload["measured_at"]))
    if measured_at.tzinfo is None:
        raise ValueError("CDC evidence timestamp must include a timezone")
    current = now or datetime.now(UTC)
    if measured_at > current + timedelta(minutes=5):
        raise ValueError("CDC evidence timestamp is in the future")
    if current - measured_at.astimezone(UTC) > timedelta(hours=MAX_EVIDENCE_AGE_HOURS):
        raise ValueError("CDC evidence is stale")
    metrics = Metrics(**payload["metrics"])
    expected_decision = decision(metrics)
    for key, value in expected_decision.items():
        if payload.get(key) != value:
            raise ValueError("CDC evidence decision does not match its metrics")
    if payload["recommendation"] != "migrate_to_native":
        raise ValueError("measured thresholds do not justify CDC activation")
    if not any(payload["hard_triggers"].values()):
        raise ValueError("CDC evidence contains no hard trigger")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("metrics_json", type=Path)
    evaluate.add_argument("--output", type=Path)
    verify = subparsers.add_parser("verify")
    verify.add_argument("evidence_json", type=Path)
    verify.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()

    payload = json.loads(args.metrics_json.read_text(encoding="utf-8")) if (
        args.command == "evaluate"
    ) else json.loads(args.evidence_json.read_text(encoding="utf-8"))
    if args.command == "evaluate":
        evidence = build_evidence(Metrics(**payload))
        rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        print(f"sha256={evidence_sha256(evidence)}")
        return
    verify_evidence(payload, args.expected_sha256)
    print("[OK] CDC activation evidence is current, consistent, and above threshold")


if __name__ == "__main__":
    main()
