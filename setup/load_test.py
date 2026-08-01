"""Bounded authenticated analytics benchmark used to establish CDC triggers."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from google.cloud import bigquery


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def run_query(project: str, region: str, sql: str, config: bigquery.QueryJobConfig) -> float:
    started = time.monotonic()
    bigquery.Client(project=project).query(
        sql, job_config=config, location=region
    ).result(timeout=60)
    return time.monotonic() - started


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--procedure", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--subject-id", required=True)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps(vars(args) | {"mode": "plan", "billable": True}, indent=2))
        return
    import os
    if os.getenv("PHASE5_ACTIVE") != "true":
        raise RuntimeError("authenticated load testing is restricted to Phase 5")
    if not 1 <= args.concurrency <= 20 or not 1 <= args.samples <= 200:
        raise ValueError("load test bounds exceeded")
    end = date.today()
    start = end - timedelta(days=89)
    sql = (
        f"CALL `{args.project}.{args.dataset}.{args.procedure}`"
        "(@start,@end,'day',@tenant,@subject)"
    )
    config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("start", "DATE", start),
        bigquery.ScalarQueryParameter("end", "DATE", end),
        bigquery.ScalarQueryParameter("tenant", "STRING", args.tenant_id),
        bigquery.ScalarQueryParameter("subject", "STRING", args.subject_id),
    ])
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        values = list(executor.map(
            lambda _: run_query(args.project, args.region, sql, config),
            range(args.samples),
        ))
    print(json.dumps({
        "samples": len(values),
        "concurrency": args.concurrency,
        "mean_seconds": statistics.mean(values),
        "p95_seconds": percentile(values, .95),
        "p99_seconds": percentile(values, .99),
    }, indent=2))
