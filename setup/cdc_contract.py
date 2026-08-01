"""Render the narrowly scoped Datastream contract without cloud access."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
from typing import Any


def build_contract(environment: dict[str, str]) -> dict[str, Any]:
    schema = environment["DATASTREAM_SOURCE_SCHEMA"]
    table = environment["DATASTREAM_SOURCE_TABLE"]
    if (schema, table) != ("public", "analytics_export_events"):
        raise ValueError("CDC is restricted to public.analytics_export_events")
    cidr = ipaddress.ip_network(environment["DATASTREAM_PEERING_CIDR"], strict=True)
    if cidr.version != 4 or cidr.prefixlen != 29:
        raise ValueError("DATASTREAM_PEERING_CIDR must be a canonical private IPv4 /29")
    if not cidr.is_private:
        raise ValueError("DATASTREAM_PEERING_CIDR must be private")
    freshness = int(environment["DATASTREAM_DATA_FRESHNESS_SECONDS"])
    if not 60 <= freshness <= 86400:
        raise ValueError("DATASTREAM_DATA_FRESHNESS_SECONDS must be 60..86400")
    return {
        "source": {
            "includeObjects": {
                "postgresqlSchemas": [
                    {"schema": schema, "postgresqlTables": [{"table": table}]}
                ]
            },
            "publication": environment["DATASTREAM_PUBLICATION"],
            "replicationSlot": environment["DATASTREAM_REPLICATION_SLOT"],
        },
        "destination": {
            "singleTargetDataset": {
                "datasetId": (
                    f"{environment['GOOGLE_CLOUD_PROJECT']}:"
                    f"{environment['BIGQUERY_DATASET']}"
                )
            },
            "dataFreshness": f"{freshness}s",
            "merge": {},
        },
        "rules": [
            {
                "objectFilter": {
                    "sourceObjectIdentifier": {
                        "postgresqlIdentifier": {"schema": schema, "table": table}
                    }
                },
                "customizationRules": [
                    {
                        "bigqueryPartitioning": {
                            "timeUnitPartition": {
                                "column": "occurred_at",
                                "partitioningTimeGranularity": (
                                    "PARTITIONING_TIME_GRANULARITY_DAY"
                                ),
                            }
                        }
                    },
                    {
                        "bigqueryClustering": {
                            "columns": [
                                "tenant_token",
                                "subject_token",
                                "event_type",
                            ]
                        }
                    },
                ],
            }
        ],
    }


def write_contract(contract: dict[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name in ("source", "destination", "rules"):
        path = output / f"{name}.json"
        path.write_text(json.dumps(contract[name], indent=2) + "\n", encoding="utf-8")
        path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    contract = build_contract(dict(os.environ))
    if args.output_dir:
        write_contract(contract, args.output_dir)
    else:
        print(json.dumps(contract, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
