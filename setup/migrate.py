"""Apply the AlloyDB schema from a VPC-connected Cloud Run Job."""

from __future__ import annotations

import os
import re
from pathlib import Path

from google.cloud.alloydb.connector import Connector, IPTypes


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
        }
        for role, identifier in role_identifiers.items():
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if cursor.fetchone() is None:
                cursor.execute(f"CREATE ROLE {identifier} NOLOGIN")

        schema = Path("alloydb_schema.sql").read_text(encoding="utf-8")
        schema = schema.replace(
            "__EMBEDDING_DIMENSIONS__", str(embedding_dimensions)
        )
        schema = schema.replace("productivity_app", role_identifiers[app_user])
        schema = schema.replace(
            "productivity_analytics", role_identifiers[analytics_user]
        )
        cursor.execute(schema)
        cursor.execute(
            f"ALTER ROLE {role_identifiers[app_user]} "
            f"LOGIN PASSWORD {quote_literal(app_password)}"
        )
        cursor.execute(
            f"ALTER ROLE {role_identifiers[analytics_user]} LOGIN PASSWORD "
            f"{quote_literal(analytics_password)}"
        )
        if required("SEED_DEMO").lower() == "true":
            seed = Path("seed_demo.sql").read_text(encoding="utf-8")
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
