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


def configured_instances(primary: str, additional: str) -> tuple[str, ...]:
    """Return unique, validated instance names in deterministic order."""

    candidates = [primary, *additional.split(",")]
    instances: list[str] = []
    for candidate in candidates:
        name = candidate.strip()
        if not name:
            continue
        if not all(
            character.islower() or character.isdigit() or character == "-"
            for character in name
        ):
            raise ValueError("AlloyDB instance names contain unsupported characters")
        if name not in instances:
            instances.append(name)
    return tuple(instances)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("resume", "suspend"), required=True)
    args = parser.parse_args()
    project = required_env("GOOGLE_CLOUD_PROJECT")
    region = required_env("ALLOYDB_REGION")
    cluster = required_env("ALLOYDB_CLUSTER")
    instances = configured_instances(
        required_env("ALLOYDB_INSTANCE"),
        os.getenv("ALLOYDB_ADDITIONAL_INSTANCES", ""),
    )
    operations = []
    for instance in instances:
        update = build_lifecycle_update(
            project=project,
            region=region,
            cluster=cluster,
            instance=instance,
            action=args.action,
        )
        operations.append(execute_update(update).get("name", "unknown"))
    print(
        json.dumps(
            {
                "status": "requested",
                "action": args.action,
                "instances": list(instances),
                "operations": operations,
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
