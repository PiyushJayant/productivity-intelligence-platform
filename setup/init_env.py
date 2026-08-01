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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--force", action="store_true")
    arguments = parser.parse_args()
    path = initialize(arguments.project, arguments.force)
    print(f"[OK] Created {path}. Review cost and resource settings before deployment.")


if __name__ == "__main__":
    main()
