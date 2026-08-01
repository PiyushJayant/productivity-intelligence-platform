from __future__ import annotations

import os
from pathlib import Path

import pg8000.dbapi
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_HOST"),
    reason="TEST_POSTGRES_HOST is required for PostgreSQL integration tests",
)


def test_privacy_migration_is_idempotent_and_enforces_core_contracts():
    connection = pg8000.dbapi.connect(
        host=os.environ["TEST_POSTGRES_HOST"],
        port=int(os.getenv("TEST_POSTGRES_PORT", "5432")),
        database=os.getenv("TEST_POSTGRES_DATABASE", "postgres"),
        user=os.getenv("TEST_POSTGRES_USER", "postgres"),
        password=os.getenv("TEST_POSTGRES_PASSWORD", "postgres"),
    )
    cursor = connection.cursor()
    try:
        prerequisites = Path("tests/sql/privacy_prerequisites.sql").read_text()
        migration = Path("setup/migrations/0005_privacy_operations.sql").read_text()
        cursor.execute(prerequisites)
        cursor.execute(migration)
        cursor.execute(migration)

        tenant = "11111111-1111-4111-8111-111111111111"
        owner = "22222222-2222-4222-8222-222222222222"
        member = "33333333-3333-4333-8333-333333333333"
        cursor.execute("INSERT INTO tenants(id, name) VALUES (%s, 'tenant')", (tenant,))
        cursor.execute(
            "INSERT INTO subjects(id, issuer, external_subject) VALUES "
            "(%s, 'issuer', 'owner'), (%s, 'issuer', 'member')",
            (owner, member),
        )
        cursor.execute(
            "INSERT INTO tenant_memberships(tenant_id, subject_id, role) VALUES "
            "(%s, %s, 'owner'), (%s, %s, 'member')",
            (tenant, owner, tenant, member),
        )
        cursor.execute(
            "INSERT INTO tasks(title, description, tenant_id, created_by_subject_id) "
            "VALUES ('Deploy service', 'secure cloud', %s, %s) RETURNING topic_id",
            (tenant, member),
        )
        assert cursor.fetchone()[0] == "operations"
        cursor.execute(
            "SELECT topic_id FROM activity_events WHERE subject_id = %s", (member,)
        )
        assert cursor.fetchone()[0] == "operations"

        cursor.execute(
            "SELECT request_id FROM request_subject_erasure(%s, %s, %s)",
            (tenant, owner, member),
        )
        request_id = cursor.fetchone()[0]
        cursor.execute("SELECT erase_subject_data(%s)", (request_id,))
        cursor.execute("SELECT count(*) FROM tasks WHERE created_by_subject_id = %s", (member,))
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT issuer, disabled_at FROM subjects WHERE id = %s", (member,))
        issuer, disabled_at = cursor.fetchone()
        assert issuer == "urn:productivity-intelligence:erased"
        assert disabled_at is not None
        connection.rollback()
    finally:
        cursor.close()
        connection.close()
