from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from setup.cdc_contract import build_contract
from setup.cdc_reconcile import evidence_sha256 as reconciliation_sha256
from setup.cdc_reconcile import verify as verify_reconciliation
from setup.evaluate_cdc_trigger import (
    Metrics,
    build_evidence,
    evidence_sha256,
    verify_evidence,
)


def environment() -> dict[str, str]:
    return {
        "DATASTREAM_SOURCE_SCHEMA": "public",
        "DATASTREAM_SOURCE_TABLE": "analytics_export_events",
        "DATASTREAM_PEERING_CIDR": "10.30.0.0/29",
        "DATASTREAM_DATA_FRESHNESS_SECONDS": "900",
        "DATASTREAM_PUBLICATION": "productivity_analytics_export",
        "DATASTREAM_REPLICATION_SLOT": "productivity_analytics_export_slot",
        "GOOGLE_CLOUD_PROJECT": "example-project",
        "BIGQUERY_DATASET": "productivity_analytics",
    }


def test_cdc_contract_is_single_table_sanitized_merge_mode():
    contract = build_contract(environment())
    schemas = contract["source"]["includeObjects"]["postgresqlSchemas"]
    assert schemas == [
        {"schema": "public", "postgresqlTables": [{"table": "analytics_export_events"}]}
    ]
    assert contract["destination"]["merge"] == {}
    rendered = str(contract)
    for forbidden in ("tenant_id", "subject_id", "title", "content", "embedding"):
        assert forbidden not in rendered
    rules = contract["rules"][0]["customizationRules"]
    assert rules[0]["bigqueryPartitioning"]["timeUnitPartition"]["column"] == "occurred_at"
    assert rules[1]["bigqueryClustering"]["columns"] == [
        "tenant_token", "subject_token", "event_type"
    ]


def test_cdc_contract_rejects_broader_source_scope():
    values = environment()
    values["DATASTREAM_SOURCE_TABLE"] = "activity_events"
    with pytest.raises(ValueError, match="restricted"):
        build_contract(values)


def test_cdc_evidence_is_threshold_bound_current_and_tamper_evident():
    now = datetime.now(UTC)
    evidence = build_evidence(Metrics(6, 8, 50, 3, 8, 7), measured_at=now)
    digest = evidence_sha256(evidence)
    verify_evidence(evidence, digest, now=now)
    evidence["metrics"]["p95_seconds"] = 1
    with pytest.raises(ValueError, match="checksum"):
        verify_evidence(evidence, digest, now=now)


def test_cdc_evidence_rejects_stale_or_healthy_measurements():
    now = datetime.now(UTC)
    stale = build_evidence(Metrics(6, 8, 50, 3, 8, 7), measured_at=now - timedelta(days=2))
    with pytest.raises(ValueError, match="stale"):
        verify_evidence(stale, evidence_sha256(stale), now=now)
    healthy = build_evidence(Metrics(1, 2, 20, 0, 2, 7), measured_at=now)
    with pytest.raises(ValueError, match="do not justify"):
        verify_evidence(healthy, evidence_sha256(healthy), now=now)


def test_reconciliation_requires_a_current_nonempty_exact_match():
    payload: dict[str, object] = {
        "schema_version": 1,
        "evidence_type": "cdc_reconciliation",
        "measured_at": datetime.now(UTC).isoformat(),
        "federated_row_count": 1,
        "native_row_count": 1,
        "federated_digest": "a" * 64,
        "native_digest": "a" * 64,
        "matched": True,
    }
    verify_reconciliation(payload, reconciliation_sha256(payload))
    payload["matched"] = False
    with pytest.raises(ValueError, match="checksum"):
        verify_reconciliation(payload, reconciliation_sha256({**payload, "matched": True}))
