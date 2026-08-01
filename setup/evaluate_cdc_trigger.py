"""Evaluate measured federation health against approved CDC migration triggers."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Metrics:
    p95_seconds: float
    p99_seconds: float
    read_pool_cpu_percent: float
    crud_degradation_percent: float
    concurrent_users: int
    sustained_days: int


def decision(metrics: Metrics) -> dict[str, object]:
    warnings = {
        "p95": metrics.p95_seconds > 3,
        "p99": metrics.p99_seconds > 7,
        "read_pool_cpu": metrics.read_pool_cpu_percent > 40,
        "crud_degradation": metrics.crud_degradation_percent > 5,
        "concurrency": metrics.concurrent_users >= 5,
    }
    hard = {
        "p95_sustained": metrics.p95_seconds > 5 and metrics.sustained_days >= 7,
        "p99": metrics.p99_seconds > 10,
        "read_pool_cpu": metrics.read_pool_cpu_percent > 70,
        "crud_degradation": metrics.crud_degradation_percent > 10,
        "concurrency": metrics.concurrent_users >= 10,
    }
    return {
        "recommendation": "migrate_to_native" if any(hard.values()) else (
            "investigate" if any(warnings.values()) else "remain_federated"
        ),
        "warnings": warnings,
        "hard_triggers": hard,
        "automatic_change_performed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("metrics_json", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.metrics_json.read_text(encoding="utf-8"))
    print(json.dumps(decision(Metrics(**payload)), indent=2))


if __name__ == "__main__":
    main()
