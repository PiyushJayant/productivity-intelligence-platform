from __future__ import annotations

import json

import pytest

from setup import privacy_job


class FakeCursor:
    def __init__(self, batches):
        self.batches = batches
        self.last_sql = ""
        self.payloads: list[str] = []

    def execute(self, sql, parameters):
        self.last_sql = sql
        if "apply_activity_export_tokens" in sql:
            self.payloads.append(parameters[0])

    def fetchall(self):
        return self.batches.pop(0) if self.batches else []

    def fetchone(self):
        if "apply_activity_export_tokens" in self.last_sql:
            return (len(json.loads(self.payloads[-1])),)
        return (3,)


class FakeConnection:
    def __init__(self, batches):
        self.cursor_instance = FakeCursor(batches)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_retention_pseudonymizes_in_bounded_batches(monkeypatch):
    monkeypatch.setenv("PRIVACY_BATCH_SIZE", "2")
    monkeypatch.setenv("PRIVACY_MAX_BATCHES", "2")
    monkeypatch.setenv("PRIVACY_RETENTION_DAYS", "90")
    monkeypatch.setenv("PSEUDONYMIZATION_KEY", "test-key-with-sufficient-entropy")
    connection = FakeConnection(
        [[(1, "tenant-a", "subject-a"), (2, "tenant-a", "subject-b")], []]
    )

    result = privacy_job.run_retention(connection)

    assert result == {"exported": 2, "purged": 3, "batches": 1}
    payload = json.loads(connection.cursor_instance.payloads[0])
    assert all(len(item["tenant_token"]) == 64 for item in payload)
    assert all(len(item["subject_token"]) == 64 for item in payload)
    assert "subject-a" not in connection.cursor_instance.payloads[0]


def test_subject_tokens_are_tenant_scoped():
    key = "test-key"
    assert privacy_job.subject_token(key, "tenant-a", "subject") != (
        privacy_job.subject_token(key, "tenant-b", "subject")
    )


def test_retention_rejects_unbounded_configuration(monkeypatch):
    monkeypatch.setenv("PRIVACY_BATCH_SIZE", "10001")
    monkeypatch.setenv("PRIVACY_MAX_BATCHES", "2")
    monkeypatch.setenv("PRIVACY_RETENTION_DAYS", "90")
    monkeypatch.setenv("PSEUDONYMIZATION_KEY", "test-key")
    with pytest.raises(ValueError, match="PRIVACY_BATCH_SIZE"):
        privacy_job.run_retention(FakeConnection([]))
