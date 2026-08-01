"""Ordered, checksummed and idempotent PostgreSQL migration runner."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class Cursor(Protocol):
    def execute(self, operation: str, args=...) -> None: ...
    def fetchone(self): ...
    def fetchall(self): ...


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    sql: str
    checksum: str


def discover_migrations(base_dir: Path) -> list[Migration]:
    """Return the baseline followed by lexically ordered versioned migrations."""
    paths = [base_dir / "alloydb_schema.sql"]
    paths.extend(sorted((base_dir / "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql")))
    migrations: list[Migration] = []
    for index, path in enumerate(paths, start=1):
        if not path.is_file():
            raise FileNotFoundError(path)
        sql = path.read_text(encoding="utf-8")
        version = "0001_baseline" if index == 1 else path.stem
        migrations.append(
            Migration(
                version=version,
                path=path,
                sql=sql,
                checksum=hashlib.sha256(sql.encode()).hexdigest(),
            )
        )
    versions = [migration.version for migration in migrations]
    if len(versions) != len(set(versions)):
        raise ValueError("duplicate migration version")
    return migrations


def ensure_history(cursor: Cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version TEXT PRIMARY KEY,
          checksum TEXT,
          applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    cursor.execute(
        "ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS checksum TEXT"
    )


def apply_migrations(cursor: Cursor, migrations: list[Migration]) -> list[str]:
    """Apply pending migrations and reject modified migration history."""
    cursor.execute("SELECT pg_advisory_lock(hashtext('productivity_schema_migrations'))")
    try:
        ensure_history(cursor)
        cursor.execute("SELECT version, checksum FROM schema_migrations")
        applied = dict(cursor.fetchall())
        completed: list[str] = []
        for migration in migrations:
            previous = applied.get(migration.version)
            if previous:
                if previous != migration.checksum:
                    raise RuntimeError(
                        f"migration {migration.version} changed after application"
                    )
                continue
            cursor.execute(migration.sql)
            cursor.execute(
                "INSERT INTO schema_migrations(version, checksum) VALUES (%s, %s)",
                (migration.version, migration.checksum),
            )
            completed.append(migration.version)
        return completed
    finally:
        cursor.execute(
            "SELECT pg_advisory_unlock(hashtext('productivity_schema_migrations'))"
        )
