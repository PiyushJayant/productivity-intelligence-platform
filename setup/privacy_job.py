"""Least-privilege retention, pseudonymization, and erasure Cloud Run Job."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import uuid
from typing import Any, cast

from google.cloud.alloydb.connector import Connector, IPTypes


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def bounded_integer(name: str, minimum: int, maximum: int) -> int:
    try:
        value = int(required(name))
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _connect(connector: Connector):
    return connector.connect(
        required("ALLOYDB_INSTANCE_URI"),
        "pg8000",
        user=required("PRIVACY_DB_USER"),
        password=required("PRIVACY_DB_PASSWORD"),
        db=required("ALLOYDB_DATABASE"),
        ip_type=IPTypes.PRIVATE,
    )


def _subject_token(key: bytes, tenant_id: object, subject_id: object) -> str:
    scoped_subject = f"subject:v1:{tenant_id}:{subject_id}"
    return hmac.new(key, scoped_subject.encode(), hashlib.sha256).hexdigest()


def run_retention(connection: Any) -> dict[str, int]:
    batch_size = bounded_integer("PRIVACY_BATCH_SIZE", 1, 10_000)
    max_batches = bounded_integer("PRIVACY_MAX_BATCHES", 1, 1_000)
    retention_days = bounded_integer("PRIVACY_RETENTION_DAYS", 1, 3_650)
    key = required("PSEUDONYMIZATION_KEY").encode()
    pseudonymized = 0
    batches = 0
    for _ in range(max_batches):
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM list_unpseudonymized_activity(%s)", (batch_size,))
        rows = cursor.fetchall()
        if not rows:
            connection.commit()
            break
        updates = [
            {
                "event_id": event_id,
                "token": _subject_token(key, tenant_id, subject_id),
            }
            for event_id, tenant_id, subject_id in rows
        ]
        cursor.execute(
            "SELECT apply_activity_subject_tokens(%s::jsonb)",
            (json.dumps(updates, separators=(",", ":")),),
        )
        pseudonymized += int(cursor.fetchone()[0])
        batches += 1
        connection.commit()
        if len(rows) < batch_size:
            break
    cursor = connection.cursor()
    cursor.execute("SELECT rollup_and_purge_activity(%s)", (retention_days,))
    purged = int(cursor.fetchone()[0])
    connection.commit()
    return {"pseudonymized": pseudonymized, "purged": purged, "batches": batches}


def run_erasure(connection: Any, request_id: str) -> dict[str, str]:
    normalized_id = str(uuid.UUID(request_id))
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT erase_subject_data(%s)", (normalized_id,))
        connection.commit()
    except Exception:
        connection.rollback()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT mark_erasure_request_failed(%s, %s)",
                (normalized_id, "execution_failed"),
            )
            connection.commit()
        except Exception:
            connection.rollback()
        raise RuntimeError("subject erasure failed safely") from None
    return {"request_id": normalized_id, "status": "completed"}


def run(operation: str, request_id: str | None) -> dict[str, object]:
    connector = Connector()
    connection = _connect(connector)
    try:
        connection.autocommit = False
        if operation == "retention":
            result = cast(dict[str, object], run_retention(connection))
        else:
            if not request_id:
                raise ValueError("--request-id is required for erase")
            result = cast(dict[str, object], run_erasure(connection, request_id))
        return {"operation": operation, "status": "ok", **result}
    finally:
        connection.close()
        connector.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("retention", "erase"))
    parser.add_argument("--request-id")
    args = parser.parse_args()
    print(json.dumps(run(args.operation, args.request_id), sort_keys=True))


if __name__ == "__main__":
    main()
