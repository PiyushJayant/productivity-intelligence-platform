"""Prepare or remove PostgreSQL logical-decoding objects for approved CDC."""

from __future__ import annotations

import argparse
import os
import re
from contextlib import closing

from google.cloud.alloydb.connector import Connector, IPTypes

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def _identifier(name: str) -> str:
    if not IDENTIFIER.fullmatch(name):
        raise ValueError(f"invalid PostgreSQL identifier: {name!r}")
    return name


def _connect():
    connector = Connector()
    connection = connector.connect(
        os.environ["ALLOYDB_INSTANCE_URI"],
        "pg8000",
        user=os.environ["ADMIN_DB_USER"],
        password=os.environ["ADMIN_DB_PASSWORD"],
        db=os.environ["ALLOYDB_DATABASE"],
        ip_type=IPTypes.PRIVATE,
    )
    return connector, connection


def prepare(connection) -> None:
    publication = _identifier(os.environ["DATASTREAM_PUBLICATION"])
    slot = _identifier(os.environ["DATASTREAM_REPLICATION_SLOT"])
    schema = _identifier(os.environ["DATASTREAM_SOURCE_SCHEMA"])
    table = _identifier(os.environ["DATASTREAM_SOURCE_TABLE"])
    created_publication = False
    try:
        with closing(connection.cursor()) as cursor:
            cursor.execute("SHOW alloydb.logical_decoding")
            if str(cursor.fetchone()[0]).lower() not in {"on", "true", "1"}:
                raise RuntimeError(
                    "alloydb.logical_decoding is disabled; enable it through an "
                    "approved maintenance change before CDC activation"
                )
            cursor.execute(
                "SELECT schemaname, tablename FROM pg_publication_tables "
                "WHERE pubname = %s",
                (publication,),
            )
            published = {(row[0], row[1]) for row in cursor.fetchall()}
            expected = {(schema, table)}
            if published and published != expected:
                raise RuntimeError("CDC publication scope drift detected")
            if not published:
                cursor.execute(
                    f'CREATE PUBLICATION "{publication}" '
                    f'FOR TABLE "{schema}"."{table}"'
                )
                connection.commit()
                created_publication = True
            cursor.execute(
                "SELECT plugin, active FROM pg_replication_slots WHERE slot_name = %s",
                (slot,),
            )
            row = cursor.fetchone()
            if row and row[0] != "pgoutput":
                raise RuntimeError("CDC replication slot uses an unexpected plugin")
            if not row:
                cursor.execute(
                    "SELECT pg_create_logical_replication_slot(%s, 'pgoutput')", (slot,)
                )
        connection.commit()
    except Exception:
        connection.rollback()
        if created_publication:
            with closing(connection.cursor()) as cursor:
                cursor.execute(f'DROP PUBLICATION IF EXISTS "{publication}"')
            connection.commit()
        raise


def cleanup(connection) -> None:
    publication = _identifier(os.environ["DATASTREAM_PUBLICATION"])
    slot = _identifier(os.environ["DATASTREAM_REPLICATION_SLOT"])
    with closing(connection.cursor()) as cursor:
        cursor.execute(
            "SELECT active FROM pg_replication_slots WHERE slot_name = %s", (slot,)
        )
        row = cursor.fetchone()
        if row and row[0]:
            raise RuntimeError("refusing to drop an active CDC replication slot")
        if row:
            cursor.execute("SELECT pg_drop_replication_slot(%s)", (slot,))
        cursor.execute(f'DROP PUBLICATION IF EXISTS "{publication}"')
    connection.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "cleanup"))
    args = parser.parse_args()
    connector, connection = _connect()
    try:
        (prepare if args.action == "prepare" else cleanup)(connection)
    finally:
        connection.close()
        connector.close()


if __name__ == "__main__":
    main()
