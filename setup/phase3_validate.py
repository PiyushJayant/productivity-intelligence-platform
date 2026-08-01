"""Build an offline Phase 3 release-evidence manifest without cloud access."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from setup.dr_contract import DrPlan
from setup.load_test import LoadTestContract
from setup.migration_runner import discover_migrations, migration_manifest_sha256
from setup.observability_contract import ObservabilityContract


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_evidence(root: Path) -> dict[str, object]:
    migrations = discover_migrations(root / "setup")
    load = LoadTestContract()
    load.validate()
    dr = DrPlan(
        project="offline-validation",
        region="us-central1",
        source_cluster="productivity-cluster",
        source_instance="productivity-instance",
        restore_cluster="productivity-cluster-dr-restore",
        restore_instance="productivity-dr-primary",
        pitr_timestamp="",
        rto_target_seconds=900,
        rpo_target_seconds=300,
    )
    dr.validate()
    observability = ObservabilityContract(300, 0, 2000, 80, 70, False, True, False)
    observability.validate()
    guarded_scripts = [
        root / "setup" / "load_test.py",
        root / "setup" / "dr_drill.sh",
        root / "setup" / "monitoring.sh",
        root / "setup" / "observability_inventory.py",
    ]
    for script in guarded_scripts:
        source = script.read_text(encoding="utf-8")
        if "PHASE5_ACTIVE" not in source and "require_phase5" not in source:
            raise RuntimeError(f"billable execution gate missing from {script.name}")
    return {
        "schema_version": 1,
        "evidence_type": "phase3_offline_release_contract",
        "generated_at": datetime.now(UTC).isoformat(),
        "cloud_accessed": False,
        "cloud_change_performed": False,
        "status": "pass",
        "migration_manifest_sha256": migration_manifest_sha256(migrations),
        "migration_versions": [item.version for item in migrations],
        "load_test_contract": load.__dict__,
        "dr_contract": dr.evidence(),
        "observability_contract": observability.manifest(),
        "artifact_sha256": {
            str(path.relative_to(root)).replace("\\", "/"): sha256(path)
            for path in guarded_scripts
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", default="")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    payload = build_evidence(root)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.evidence:
        Path(args.evidence).write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
