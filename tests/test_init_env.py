from __future__ import annotations

from pathlib import Path

from setup.init_env import SECRET_KEYS, initialize


def test_initializer_creates_one_complete_env_with_unique_secrets(tmp_path: Path):
    template = tmp_path / ".env.example"
    target = tmp_path / ".env"
    template.write_text(
        "GOOGLE_CLOUD_PROJECT=your-project-id\n"
        "ADMIN_DB_PASSWORD=change-me-admin-at-least-24-characters\n"
        "APP_DB_PASSWORD=change-me-application-at-least-24-characters\n"
        "ANALYTICS_DB_PASSWORD=change-me-analytics-at-least-24-characters\n",
        encoding="utf-8",
    )

    initialize("cost-test-project", template=template, target=target)
    values = dict(
        line.split("=", 1)
        for line in target.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )

    assert values["GOOGLE_CLOUD_PROJECT"] == "cost-test-project"
    secrets = [values[key] for key in SECRET_KEYS]
    assert len(set(secrets)) == 3
    assert all(len(value) >= 24 and "change-me" not in value for value in secrets)
