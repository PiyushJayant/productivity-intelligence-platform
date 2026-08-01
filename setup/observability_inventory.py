"""Read deployed monitoring inventory and evaluate it against the local contract."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime

from setup.observability_contract import from_environment, validate_inventory


def canonical_inventory(
    policies: list[dict[str, object]],
    metrics: list[dict[str, object]],
    uptime_checks: list[dict[str, object]],
) -> dict[str, object]:
    policy_details = {
        str(item["displayName"]): {
            "enabled": item.get("enabled", True),
            "notification_channels": item.get("notificationChannels", []),
        }
        for item in policies
        if item.get("displayName")
    }
    return {
        "alert_policies": sorted(policy_details),
        "alert_policy_details": policy_details,
        "log_metrics": sorted(
            str(item["name"]).rsplit("/", 1)[-1] for item in metrics if item.get("name")
        ),
        "uptime_checks": sorted(
            str(item["displayName"])
            for item in uptime_checks
            if item.get("displayName")
        ),
    }


def gcloud_json(arguments: list[str]) -> list[dict[str, object]]:
    try:
        result = subprocess.run(
            ["gcloud", *arguments, "--format=json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("failed to read deployed monitoring inventory") from error
    payload = json.loads(result.stdout)
    if not isinstance(payload, list):
        raise RuntimeError("deployed monitoring inventory has an invalid shape")
    return payload


def main() -> None:
    if os.getenv("PHASE5_ACTIVE") != "true":
        raise RuntimeError("authenticated observability validation is restricted to Phase 5")
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    if not project:
        raise ValueError("GOOGLE_CLOUD_PROJECT is required")
    inventory = canonical_inventory(
        gcloud_json(["monitoring", "policies", "list", f"--project={project}"]),
        gcloud_json(["logging", "metrics", "list", f"--project={project}"]),
        gcloud_json(["monitoring", "uptime", "list-configs", f"--project={project}"]),
    )
    contract = from_environment()
    missing = validate_inventory(inventory, contract)
    evidence = {
        "schema_version": 1,
        "evidence_type": "deployed_observability_inventory",
        "generated_at": datetime.now(UTC).isoformat(),
        "project": project,
        "status": "pass" if not missing else "fail",
        "missing_controls": missing,
        "inventory": inventory,
    }
    print(json.dumps(evidence, indent=2, sort_keys=True))
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
