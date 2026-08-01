"""Reconcile federated v2 and native v3 before an analytics cutover."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from google.cloud import bigquery

from productivity_intelligence.tokenization import subject_token, tenant_token

SCHEMA_VERSION = 1
MAX_AGE_HOURS = 24


def _rows(result: Any) -> list[dict[str, object]]:
    normalized = []
    for row in result:
        values = {}
        for key, value in row.items():
            values[key] = float(value) if isinstance(value, Decimal) else value
        normalized.append(values)
    return sorted(normalized, key=lambda item: str(item.get("period")))


def _digest(rows: list[dict[str, object]]) -> str:
    payload = json.dumps(rows, default=str, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def reconcile(start: date, end: date) -> dict[str, object]:
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    dataset = os.environ["BIGQUERY_DATASET"]
    client = bigquery.Client(project=project)
    shared = [
        bigquery.ScalarQueryParameter("start", "DATE", start),
        bigquery.ScalarQueryParameter("end", "DATE", end),
        bigquery.ScalarQueryParameter("grain", "STRING", "day"),
    ]
    tenant_id = os.environ["LOAD_TEST_TENANT_ID"]
    subject_id = os.environ["LOAD_TEST_SUBJECT_ID"]
    v2_config = bigquery.QueryJobConfig(
        query_parameters=shared
        + [
            bigquery.ScalarQueryParameter("tenant", "STRING", tenant_id),
            bigquery.ScalarQueryParameter("subject", "STRING", subject_id),
        ],
        labels={"component": "cdc-reconciliation", "contract": "v2"},
    )
    key = os.environ["PSEUDONYMIZATION_KEY"]
    v3_config = bigquery.QueryJobConfig(
        query_parameters=shared
        + [
            bigquery.ScalarQueryParameter(
                "tenant_token", "STRING", tenant_token(key, tenant_id)
            ),
            bigquery.ScalarQueryParameter(
                "subject_token", "STRING", subject_token(key, tenant_id, subject_id)
            ),
        ],
        labels={"component": "cdc-reconciliation", "contract": "v3"},
    )
    maximum_bytes = int(os.environ["ANALYTICS_MAX_BYTES_BILLED"])
    v2_config.maximum_bytes_billed = maximum_bytes
    v3_config.maximum_bytes_billed = maximum_bytes
    v2 = _rows(
        client.query(
            f"CALL `{project}.{dataset}.{os.environ['BIGQUERY_ANALYTICS_PROCEDURE']}`"
            "(@start, @end, @grain, @tenant, @subject)",
            job_config=v2_config,
            location=os.environ["REGION"],
        ).result(timeout=int(os.environ["ANALYTICS_QUERY_TIMEOUT_SECONDS"]))
    )
    v3 = _rows(
        client.query(
            f"SELECT * FROM `{project}.{dataset}.{os.environ['BIGQUERY_NATIVE_TVF']}`"
            "(@start, @end, @grain, @tenant_token, @subject_token)",
            job_config=v3_config,
            location=os.environ["REGION"],
        ).result(timeout=int(os.environ["ANALYTICS_QUERY_TIMEOUT_SECONDS"]))
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": "cdc_reconciliation",
        "measured_at": datetime.now(UTC).isoformat(),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "federated_row_count": len(v2),
        "native_row_count": len(v3),
        "federated_digest": _digest(v2),
        "native_digest": _digest(v3),
        "matched": bool(v2) and v2 == v3,
    }


def evidence_sha256(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(canonical).hexdigest()


def verify(payload: dict[str, object], expected_sha256: str) -> None:
    if evidence_sha256(payload) != expected_sha256.lower():
        raise ValueError("CDC reconciliation evidence checksum mismatch")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported CDC reconciliation evidence schema")
    if payload.get("evidence_type") != "cdc_reconciliation":
        raise ValueError("invalid CDC reconciliation evidence type")
    measured = datetime.fromisoformat(str(payload["measured_at"]))
    now = datetime.now(UTC)
    if measured.tzinfo is None or measured > now + timedelta(minutes=5):
        raise ValueError("CDC reconciliation timestamp is invalid")
    if now - measured > timedelta(hours=MAX_AGE_HOURS):
        raise ValueError("CDC reconciliation evidence is stale")
    native_count = payload.get("native_row_count")
    if (
        payload.get("matched") is not True
        or not isinstance(native_count, int)
        or native_count < 1
    ):
        raise ValueError("CDC reconciliation did not produce a non-empty exact match")
    if payload.get("federated_digest") != payload.get("native_digest"):
        raise ValueError("CDC reconciliation digests differ")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run")
    run.add_argument("start", type=date.fromisoformat)
    run.add_argument("end", type=date.fromisoformat)
    run.add_argument("--output", required=True, type=Path)
    check = sub.add_parser("verify")
    check.add_argument("evidence", type=Path)
    check.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    if args.action == "run":
        if args.end < args.start:
            raise ValueError("end date precedes start date")
        if (args.end - args.start).days + 1 > int(os.environ["ANALYTICS_MAX_RANGE_DAYS"]):
            raise ValueError("reconciliation range exceeds the analytics maximum")
        evidence = reconcile(args.start, args.end)
        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(f"sha256={evidence_sha256(evidence)}")
    else:
        payload = json.loads(args.evidence.read_text(encoding="utf-8"))
        verify(payload, args.expected_sha256)
        print("[OK] CDC reconciliation evidence is current and exact")


if __name__ == "__main__":
    main()
