"""Bounded, billing-gated analytics load test with an enforceable SLO contract."""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from google.cloud import bigquery

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")
PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
REGION = re.compile(r"^[a-z]+-[a-z]+[0-9]$")


@dataclass(frozen=True)
class LoadTestContract:
    concurrency: int = 5
    samples: int = 20
    range_days: int = 90
    query_timeout_seconds: int = 60
    p95_limit_seconds: float = 5.0
    p99_limit_seconds: float = 10.0
    max_error_rate_percent: float = 1.0
    fixture_events: int = 1_000_000
    maximum_bytes_billed: int = 1_073_741_824

    def validate(self) -> None:
        if not 1 <= self.concurrency <= 20:
            raise ValueError("concurrency must be between 1 and 20")
        if not 1 <= self.samples <= 200:
            raise ValueError("samples must be between 1 and 200")
        if not 1 <= self.range_days <= 730:
            raise ValueError("range_days must be between 1 and 730")
        if not 1 <= self.query_timeout_seconds <= 300:
            raise ValueError("query_timeout_seconds must be between 1 and 300")
        if self.p95_limit_seconds <= 0 or self.p99_limit_seconds < self.p95_limit_seconds:
            raise ValueError("latency limits must be positive and p99 must be >= p95")
        if not 0 <= self.max_error_rate_percent <= 100:
            raise ValueError("max_error_rate_percent must be between 0 and 100")
        if self.fixture_events not in {1_000_000, 10_000_000}:
            raise ValueError("fixture_events must be the approved 1M or 10M baseline")
        if not 1 <= self.maximum_bytes_billed <= 10_737_418_240:
            raise ValueError("maximum_bytes_billed must be between 1 byte and 10 GiB")


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, int(len(ordered) * fraction + 0.999999))
    return ordered[rank - 1]


def evaluate(
    latencies: list[float], failures: int, contract: LoadTestContract
) -> dict[str, object]:
    total = len(latencies) + failures
    error_rate = (failures / total * 100) if total else 100.0
    p95 = percentile(latencies, 0.95)
    p99 = percentile(latencies, 0.99)
    violations: list[str] = []
    if p95 > contract.p95_limit_seconds:
        violations.append("p95_latency")
    if p99 > contract.p99_limit_seconds:
        violations.append("p99_latency")
    if error_rate > contract.max_error_rate_percent:
        violations.append("error_rate")
    return {
        "schema_version": 1,
        "evidence_type": "analytics_load_test",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "pass" if total and not violations else "fail",
        "samples_attempted": total,
        "samples_succeeded": len(latencies),
        "samples_failed": failures,
        "error_rate_percent": round(error_rate, 4),
        "mean_seconds": round(statistics.mean(latencies), 4) if latencies else None,
        "p95_seconds": round(p95, 4) if latencies else None,
        "p99_seconds": round(p99, 4) if latencies else None,
        "violations": violations,
        "contract": asdict(contract),
    }


def run_query(
    client: bigquery.Client,
    region: str,
    sql: str,
    config: bigquery.QueryJobConfig,
    timeout: int,
) -> float:
    started = time.monotonic()
    client.query(sql, job_config=config, location=region).result(timeout=timeout)
    return time.monotonic() - started


def _identifier(value: str, label: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} is not a valid BigQuery identifier")
    return value


def write_evidence(payload: dict[str, object], path: str) -> None:
    output = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path:
        Path(path).write_text(output, encoding="utf-8")
    print(output, end="")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", ""))
    parser.add_argument("--region", default=os.getenv("REGION", "us-central1"))
    parser.add_argument("--dataset", default=os.getenv("BIGQUERY_DATASET", ""))
    parser.add_argument(
        "--procedure", default=os.getenv("BIGQUERY_ANALYTICS_PROCEDURE", "")
    )
    parser.add_argument("--tenant-id", default=os.getenv("LOAD_TEST_TENANT_ID", ""))
    parser.add_argument("--subject-id", default=os.getenv("LOAD_TEST_SUBJECT_ID", ""))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--evidence", default=os.getenv("LOAD_TEST_EVIDENCE_PATH", ""))
    args = parser.parse_args()
    contract = LoadTestContract(
        concurrency=int(os.getenv("LOAD_TEST_CONCURRENCY", "5")),
        samples=int(os.getenv("LOAD_TEST_SAMPLES", "20")),
        range_days=int(os.getenv("LOAD_TEST_RANGE_DAYS", "90")),
        query_timeout_seconds=int(os.getenv("LOAD_TEST_QUERY_TIMEOUT_SECONDS", "60")),
        p95_limit_seconds=float(os.getenv("LOAD_TEST_P95_LIMIT_SECONDS", "5")),
        p99_limit_seconds=float(os.getenv("LOAD_TEST_P99_LIMIT_SECONDS", "10")),
        max_error_rate_percent=float(os.getenv("LOAD_TEST_MAX_ERROR_RATE_PERCENT", "1")),
        fixture_events=int(os.getenv("LOAD_TEST_FIXTURE_EVENTS", "1000000")),
        maximum_bytes_billed=int(
            os.getenv("LOAD_TEST_MAX_BYTES_BILLED", "1073741824")
        ),
    )
    contract.validate()
    if not PROJECT_ID.fullmatch(args.project) or not REGION.fullmatch(args.region):
        raise ValueError("project or region identifier is invalid")
    for value, label in ((args.dataset, "dataset"), (args.procedure, "procedure")):
        _identifier(value, label)
    plan: dict[str, object] = {
        "schema_version": 1,
        "evidence_type": "analytics_load_test_plan",
        "mode": "execute" if args.execute else "plan",
        "billable": True,
        "project": args.project,
        "region": args.region,
        "dataset": args.dataset,
        "procedure": args.procedure,
        "contract": asdict(contract),
    }
    if not args.execute:
        write_evidence(plan, args.evidence)
        return
    if os.getenv("PHASE5_ACTIVE") != "true":
        raise RuntimeError("authenticated load testing is restricted to Phase 5")
    if not args.project or not args.tenant_id or not args.subject_id:
        raise ValueError("project and backend-injected test identities are required")

    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=contract.range_days)
    sql = (
        f"CALL `{args.project}.{args.dataset}.{args.procedure}`"
        "(@start,@end,'day',@tenant,@subject)"
    )
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start", "DATE", start),
            bigquery.ScalarQueryParameter("end", "DATE", end),
            bigquery.ScalarQueryParameter("tenant", "STRING", args.tenant_id),
            bigquery.ScalarQueryParameter("subject", "STRING", args.subject_id),
        ],
        use_query_cache=False,
        maximum_bytes_billed=contract.maximum_bytes_billed,
    )
    client = bigquery.Client(project=args.project)
    latencies: list[float] = []
    failures = 0
    with ThreadPoolExecutor(max_workers=contract.concurrency) as executor:
        futures = [
            executor.submit(
                run_query,
                client,
                args.region,
                sql,
                config,
                contract.query_timeout_seconds,
            )
            for _ in range(contract.samples)
        ]
        for future in as_completed(futures):
            try:
                latencies.append(future.result())
            except Exception:  # Evidence records counts, never provider error internals.
                failures += 1
    result = evaluate(latencies, failures, contract)
    result.update({"project": args.project, "region": args.region})
    write_evidence(result, args.evidence)
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
