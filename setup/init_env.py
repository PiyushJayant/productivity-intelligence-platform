"""Create the local single-source .env with strong independent database secrets."""

from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).parents[1]
TEMPLATE = ROOT / ".env.example"
TARGET = ROOT / ".env"
SECRET_KEYS = {
    "ADMIN_DB_PASSWORD",
    "APP_DB_PASSWORD",
    "ANALYTICS_DB_PASSWORD",
    "PRIVACY_DB_PASSWORD",
    "CDC_DB_PASSWORD",
    "PSEUDONYMIZATION_KEY",
}


def initialize(
    project_id: str,
    force: bool = False,
    *,
    template: Path = TEMPLATE,
    target: Path = TARGET,
) -> Path:
    if not project_id or project_id in {"your-project-id", "change-me"}:
        raise ValueError("A real Google Cloud project ID is required")
    if target.exists() and not force:
        raise FileExistsError(f"{target} already exists; use --force to replace it")

    output: list[str] = []
    for line in template.read_text(encoding="utf-8").splitlines():
        if line.startswith("GOOGLE_CLOUD_PROJECT="):
            output.append(f"GOOGLE_CLOUD_PROJECT={project_id}")
            continue
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in SECRET_KEYS:
            output.append(f"{key}={secrets.token_urlsafe(36)}")
            continue
        output.append(line)

    target.write_text("\n".join(output) + "\n", encoding="utf-8")
    if os.name != "nt":
        target.chmod(0o600)
    return target


def rotate_secret(key: str, *, target: Path = TARGET) -> Path:
    """Replace one managed secret without printing or returning its value."""
    if key not in SECRET_KEYS:
        raise ValueError(f"Unsupported managed secret: {key}")
    if not target.exists():
        raise FileNotFoundError(f"{target} does not exist; initialize it first")

    output: list[str] = []
    replaced = False
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            output.append(f"{key}={secrets.token_urlsafe(36)}")
            replaced = True
        else:
            output.append(line)
    if not replaced:
        raise ValueError(f"{key} is missing from {target}")
    target.write_text("\n".join(output) + "\n", encoding="utf-8")
    if os.name != "nt":
        target.chmod(0o600)
    return target


def sync_missing(*, template: Path = TEMPLATE, target: Path = TARGET) -> Path:
    """Append newly introduced settings without changing existing local values."""
    if not target.exists():
        raise FileNotFoundError(f"{target} does not exist; initialize it first")
    current = target.read_text(encoding="utf-8").splitlines()
    existing = {
        line.split("=", 1)[0]
        for line in current
        if line and not line.lstrip().startswith("#") and "=" in line
    }
    additions: list[str] = []
    for line in template.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0]
        if key in existing:
            continue
        additions.append(
            f"{key}={secrets.token_urlsafe(36)}" if key in SECRET_KEYS else line
        )
    if additions:
        target.write_text("\n".join(current + [""] + additions) + "\n", encoding="utf-8")
    if os.name != "nt":
        target.chmod(0o600)
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--rotate-secret", choices=sorted(SECRET_KEYS))
    arguments = parser.parse_args()
    if arguments.rotate_secret:
        path = rotate_secret(arguments.rotate_secret)
        print(f"[OK] Rotated {arguments.rotate_secret} in {path} without displaying it.")
        return
    if arguments.sync:
        path = sync_missing()
        print(f"[OK] Added missing settings to {path} without changing existing values.")
        return
    if not arguments.project:
        parser.error("--project is required unless --rotate-secret or --sync is used")
    path = initialize(arguments.project, arguments.force)
    print(f"[OK] Created {path}. Review cost and resource settings before deployment.")


if __name__ == "__main__":
    main()
