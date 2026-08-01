from __future__ import annotations

from pathlib import Path

from setup.init_env import SECRET_KEYS, initialize, rotate_secret, sync_missing


def test_initializer_creates_one_complete_env_with_unique_secrets(tmp_path: Path):
    template = tmp_path / ".env.example"
    target = tmp_path / ".env"
    template.write_text(
        "GOOGLE_CLOUD_PROJECT=your-project-id\n"
        "ADMIN_DB_PASSWORD=change-me-admin-at-least-24-characters\n"
        "APP_DB_PASSWORD=change-me-application-at-least-24-characters\n"
        "ANALYTICS_DB_PASSWORD=change-me-analytics-at-least-24-characters\n"
        "PRIVACY_DB_PASSWORD=change-me-privacy-at-least-24-characters\n"
        "CDC_DB_PASSWORD=change-me-cdc-at-least-24-characters\n"
        "PSEUDONYMIZATION_KEY=change-me-pseudonymization-at-least-32-characters\n",
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
    assert len(set(secrets)) == len(SECRET_KEYS)
    assert all(len(value) >= 24 and "change-me" not in value for value in secrets)


def test_rotate_secret_changes_only_the_selected_secret(tmp_path: Path):
    target = tmp_path / ".env"
    target.write_text(
        "GOOGLE_CLOUD_PROJECT=test-project\n"
        "PRIVACY_DB_PASSWORD=old-private-value\n"
        "APP_DB_PASSWORD=unchanged-value\n",
        encoding="utf-8",
    )

    rotate_secret("PRIVACY_DB_PASSWORD", target=target)
    values = dict(
        line.split("=", 1)
        for line in target.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    assert values["PRIVACY_DB_PASSWORD"] != "old-private-value"
    assert len(values["PRIVACY_DB_PASSWORD"]) >= 24
    assert values["APP_DB_PASSWORD"] == "unchanged-value"


def test_sync_appends_new_settings_without_changing_existing_values(tmp_path: Path):
    template = tmp_path / ".env.example"
    target = tmp_path / ".env"
    template.write_text("EXISTING=new\nCDC_DB_PASSWORD=placeholder\n", encoding="utf-8")
    target.write_text("EXISTING=preserved\n", encoding="utf-8")
    sync_missing(template=template, target=target)
    values = dict(line.split("=", 1) for line in target.read_text().splitlines() if "=" in line)
    assert values["EXISTING"] == "preserved"
    assert len(values["CDC_DB_PASSWORD"]) >= 24
