"""Start or stop the configured AlloyDB instance from a Cloud Run Job."""

from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass

import google.auth
from google.auth.transport.requests import Request


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


@dataclass(frozen=True)
class LifecycleUpdate:
    url: str
    body: bytes


def build_lifecycle_update(
    *,
    project: str,
    region: str,
    cluster: str,
    instance: str,
    action: str,
) -> LifecycleUpdate:
    """Build the narrow AlloyDB activation-policy update request."""

    policies = {"resume": "ALWAYS", "suspend": "NEVER"}
    if action not in policies:
        raise ValueError("action must be resume or suspend")
    resource = (
        f"projects/{project}/locations/{region}/clusters/{cluster}/instances/{instance}"
    )
    encoded_resource = urllib.parse.quote(resource, safe="/")
    url = (
        f"https://alloydb.googleapis.com/v1/{encoded_resource}"
        "?updateMask=activationPolicy"
    )
    body = json.dumps(
        {"name": resource, "activationPolicy": policies[action]},
        separators=(",", ":"),
    ).encode()
    return LifecycleUpdate(url=url, body=body)


def execute_update(update: LifecycleUpdate) -> dict[str, object]:
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    request = urllib.request.Request(
        update.url,
        data=update.body,
        method="PATCH",
        headers={
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("resume", "suspend"), required=True)
    args = parser.parse_args()
    update = build_lifecycle_update(
        project=required_env("GOOGLE_CLOUD_PROJECT"),
        region=required_env("ALLOYDB_REGION"),
        cluster=required_env("ALLOYDB_CLUSTER"),
        instance=required_env("ALLOYDB_INSTANCE"),
        action=args.action,
    )
    operation = execute_update(update)
    print(
        json.dumps(
            {
                "status": "requested",
                "action": args.action,
                "operation": operation.get("name", "unknown"),
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
