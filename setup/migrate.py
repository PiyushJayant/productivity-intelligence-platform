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


def quote_identifier(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value):
        raise ValueError("ALLOYDB_DATABASE must be a lowercase PostgreSQL identifier")
    return f'"{value}"'


def main() -> None:
    instance_uri = required("ALLOYDB_INSTANCE_URI")
    database = os.getenv("ALLOYDB_DATABASE", "productivity_platform")
    admin_password = required("ADMIN_DB_PASSWORD")
    app_password = required("APP_DB_PASSWORD")
    analytics_password = required("ANALYTICS_DB_PASSWORD")

    connector = Connector()
    if database != "postgres":
        bootstrap = connector.connect(
            instance_uri,
            "pg8000",
            user="postgres",
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
        user="postgres",
        password=admin_password,
        db=database,
        ip_type=IPTypes.PRIVATE,
    )
    try:
        connection.autocommit = True
        cursor = connection.cursor()
        cursor.execute(Path("alloydb_schema.sql").read_text(encoding="utf-8"))
        cursor.execute(
            f"ALTER ROLE productivity_app LOGIN PASSWORD {quote_literal(app_password)}"
        )
        cursor.execute(
            "ALTER ROLE productivity_analytics LOGIN PASSWORD "
            f"{quote_literal(analytics_password)}"
        )
        if os.getenv("SEED_DEMO", "false").lower() == "true":
            cursor.execute(Path("seed_demo.sql").read_text(encoding="utf-8"))
        cursor.execute(
            "SELECT vector_dims(google_ml.embedding('text-embedding-005', 'health check')::vector)"
        )
        dimensions = cursor.fetchone()[0]
        if dimensions != 768:
            raise RuntimeError(f"Unexpected embedding dimension: {dimensions}")
        print("[OK] Productivity Intelligence database migration passed")
    finally:
        connection.close()
        connector.close()


if __name__ == "__main__":
    main()
