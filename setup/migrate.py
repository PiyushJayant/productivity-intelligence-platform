"""Apply the AlloyDB schema from a VPC-connected Cloud Run Job."""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

from google.cloud.alloydb.connector import Connector, IPTypes

from setup.migration_runner import (
    Migration,
    apply_migrations,
    discover_migrations,
    plan_migrations,
)

SUBJECT_NAMESPACE = uuid.UUID("2ea7b872-6bc4-4a37-9a58-75fd18d94086")


def required(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise ValueError(f"{name} is required")
    return value


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def quote_identifier(value: str, setting: str = "ALLOYDB_DATABASE") -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value):
        raise ValueError(f"{setting} must be a lowercase PostgreSQL identifier")
    return f'"{value}"'


def main() -> None:
    instance_uri = required("ALLOYDB_INSTANCE_URI")
    database = required("ALLOYDB_DATABASE")
    admin_user = required("ADMIN_DB_USER")
    app_user = required("ALLOYDB_USER")
    analytics_user = required("ANALYTICS_DB_USER")
    privacy_user = required("PRIVACY_DB_USER")
    embedding_model = required("EMBEDDING_MODEL")
    if not re.fullmatch(r"[A-Za-z0-9._@-]+", embedding_model):
        raise ValueError("EMBEDDING_MODEL contains unsupported characters")
    try:
        embedding_dimensions = int(required("EMBEDDING_DIMENSIONS"))
    except ValueError as error:
        raise ValueError("EMBEDDING_DIMENSIONS must be an integer") from error
    if embedding_dimensions < 1:
        raise ValueError("EMBEDDING_DIMENSIONS must be positive")
    admin_password = required("ADMIN_DB_PASSWORD")
    app_password = required("APP_DB_PASSWORD")
    analytics_password = required("ANALYTICS_DB_PASSWORD")
    privacy_password = required("PRIVACY_DB_PASSWORD")
    try:
        analytics_timeout_ms = int(required("ANALYTICS_QUERY_TIMEOUT_SECONDS")) * 1000
    except ValueError as error:
        raise ValueError("ANALYTICS_QUERY_TIMEOUT_SECONDS must be an integer") from error
    if analytics_timeout_ms < 1000:
        raise ValueError("ANALYTICS_QUERY_TIMEOUT_SECONDS must be positive")
    default_tenant_id = str(uuid.UUID(required("DEFAULT_TENANT_ID")))
    auth_mode = required("AUTH_MODE").lower()
    if auth_mode == "identity_platform":
        identity_project = required("IDENTITY_PLATFORM_PROJECT_ID")
        bootstrap_external_subject = required("BOOTSTRAP_IDP_SUBJECT")
        if bootstrap_external_subject.startswith("replace-"):
            raise ValueError("BOOTSTRAP_IDP_SUBJECT is still a placeholder")
        bootstrap_issuer = f"https://securetoken.google.com/{identity_project}"
        bootstrap_subject_id = str(
            uuid.uuid5(
                SUBJECT_NAMESPACE,
                f"{bootstrap_issuer}\x1f{bootstrap_external_subject}",
            )
        )
    elif auth_mode == "disabled":
        bootstrap_issuer = "urn:productivity-intelligence:local-demo"
        bootstrap_external_subject = "local-demo"
        bootstrap_subject_id = str(uuid.UUID(required("DEMO_SUBJECT_ID")))
    else:
        raise ValueError("AUTH_MODE must be identity_platform or disabled")

    connector = Connector()
    if database != "postgres":
        bootstrap = connector.connect(
            instance_uri,
            "pg8000",
            user=admin_user,
            password=admin_password,
            db="postgres",
            ip_type=IPTypes.PRIVATE,
        )
        try:
            bootstrap.autocommit = True
            cursor = bootstrap.cursor()
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
            if cursor.fetchone() is None:
                cursor.execute(f"CREATE DATABASE {quote_identifier(database)}")
        finally:
            bootstrap.close()

    connection = connector.connect(
        instance_uri,
        "pg8000",
        user=admin_user,
        password=admin_password,
        db=database,
        ip_type=IPTypes.PRIVATE,
    )
    try:
        connection.autocommit = True
        cursor = connection.cursor()
        role_identifiers = {
            app_user: quote_identifier(app_user, "ALLOYDB_USER"),
            analytics_user: quote_identifier(analytics_user, "ANALYTICS_DB_USER"),
            privacy_user: quote_identifier(privacy_user, "PRIVACY_DB_USER"),
        }
        for role, identifier in role_identifiers.items():
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if cursor.fetchone() is None:
                cursor.execute(f"CREATE ROLE {identifier} NOLOGIN")

        replacements = {
            "__EMBEDDING_DIMENSIONS__": str(embedding_dimensions),
            "__DEFAULT_TENANT_ID__": default_tenant_id,
            "__BOOTSTRAP_SUBJECT_ID__": bootstrap_subject_id,
            "__BOOTSTRAP_ISSUER__": bootstrap_issuer.replace("'", "''"),
            "__BOOTSTRAP_EXTERNAL_SUBJECT__": bootstrap_external_subject.replace(
                "'", "''"
            ),
            "__TAXONOMY_VERSION__": required("TAXONOMY_VERSION"),
            "productivity_app": role_identifiers[app_user],
            "productivity_analytics": role_identifiers[analytics_user],
            "productivity_privacy": role_identifiers[privacy_user],
        }
        migrations = []
        setup_dir = Path(__file__).parent
        for migration in discover_migrations(setup_dir):
            sql = migration.sql
            for placeholder, value in replacements.items():
                sql = sql.replace(placeholder, value)
            migrations.append(
                Migration(
                    migration.version,
                    migration.path,
                    sql,
                    migration.checksum,
                )
            )
        initial_plan = plan_migrations(cursor, migrations)
        completed = apply_migrations(cursor, migrations)
        final_plan = plan_migrations(cursor, migrations)
        if final_plan.pending:
            raise RuntimeError("migration verification found unapplied versions")
        evidence = initial_plan.evidence(completed)
        evidence["verified"] = True
        evidence["final_applied_versions"] = list(final_plan.applied)
        rendered_evidence = json.dumps(evidence, sort_keys=True)
        evidence_path = os.getenv("MIGRATION_EVIDENCE_PATH", "")
        if evidence_path:
            Path(evidence_path).write_text(rendered_evidence + "\n", encoding="utf-8")
        print(rendered_evidence)
        print(f"[OK] Applied migrations: {completed or ['none']}")
        analytics_timeout = quote_literal(f"{analytics_timeout_ms}ms")
        cursor.execute(
            f"ALTER ROLE {role_identifiers[analytics_user]} "
            f"SET statement_timeout = {analytics_timeout}"
        )
        cursor.execute(
            f"ALTER ROLE {role_identifiers[analytics_user]} "
            f"SET idle_in_transaction_session_timeout = {analytics_timeout}"
        )
        cursor.execute(
            f"ALTER ROLE {role_identifiers[app_user]} "
            f"LOGIN PASSWORD {quote_literal(app_password)}"
        )
        cursor.execute(
            f"ALTER ROLE {role_identifiers[analytics_user]} LOGIN PASSWORD "
            f"{quote_literal(analytics_password)}"
        )
        cursor.execute(
            f"ALTER ROLE {role_identifiers[privacy_user]} LOGIN PASSWORD "
            f"{quote_literal(privacy_password)}"
        )
        if required("SEED_DEMO").lower() == "true":
            seed = (setup_dir / "seed_demo.sql").read_text(encoding="utf-8")
            seed = seed.replace("__EMBEDDING_MODEL__", embedding_model)
            cursor.execute(seed)
        cursor.execute(
            "SELECT vector_dims(google_ml.embedding(%s, 'health check')::vector)",
            (embedding_model,),
        )
        dimensions = cursor.fetchone()[0]
        if dimensions != embedding_dimensions:
            raise RuntimeError(f"Unexpected embedding dimension: {dimensions}")
        print("[OK] Productivity Intelligence database migration passed")
    finally:
        connection.close()
        connector.close()


if __name__ == "__main__":
    main()
