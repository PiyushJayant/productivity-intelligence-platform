"""Privileged retention and subject-erasure worker for Cloud Run Jobs."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import uuid

from google.cloud.alloydb.connector import Connector, IPTypes


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def run(operation: str, request_id: str | None) -> None:
    connector = Connector()
    connection = connector.connect(
        required("ALLOYDB_INSTANCE_URI"),
        "pg8000",
        user=required("ADMIN_DB_USER"),
        password=required("ADMIN_DB_PASSWORD"),
        db=required("ALLOYDB_DATABASE"),
        ip_type=IPTypes.PRIVATE,
    )
    try:
        connection.autocommit = False
        cursor = connection.cursor()
        if operation == "retention":
            key = required("PSEUDONYMIZATION_KEY").encode()
            cursor.execute(
                "SELECT id, subject_id::text FROM activity_events "
                "WHERE subject_token IS NULL AND subject_id IS NOT NULL "
                "LIMIT 10000"
            )
            updates = [
                (
                    hmac.new(key, subject.encode(), hashlib.sha256).hexdigest(),
                    event_id,
                )
                for event_id, subject in cursor.fetchall()
            ]
            if updates:
                cursor.executemany(
                    "UPDATE activity_events SET subject_token = %s WHERE id = %s",
                    updates,
                )
            days = int(required("PRIVACY_RETENTION_DAYS"))
            cursor.execute("SELECT rollup_and_purge_activity(%s)", (days,))
            print(f"[OK] Purged {cursor.fetchone()[0]} expired activity events")
        else:
            if not request_id:
                raise ValueError("--request-id is required for erase")
            cursor.execute("SELECT erase_subject_data(%s)", (str(uuid.UUID(request_id)),))
            print("[OK] Subject erasure request completed")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
        connector.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("retention", "erase"))
    parser.add_argument("--request-id")
    args = parser.parse_args()
    run(args.operation, args.request_id)


if __name__ == "__main__":
    main()
