"""Ordered, checksummed and idempotent PostgreSQL migration runner."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

LEGACY_SCHEMA_MARKERS = frozenset(
    {
        "001_deployment_readiness",
        "002_task_deadlines",
        "003_activity_ledger",
        "004_identity_and_tenant_ownership",
    }
)


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


@dataclass(frozen=True)
class MigrationPlan:
    known: tuple[str, ...]
    applied: tuple[str, ...]
    pending: tuple[str, ...]
    manifest_sha256: str

    def evidence(self, newly_applied: list[str] | None = None) -> dict[str, object]:
        return {
            "schema_version": 1,
            "evidence_type": "database_migration",
            "generated_at": datetime.now(UTC).isoformat(),
            "manifest_sha256": self.manifest_sha256,
            "known_versions": list(self.known),
            "previously_applied_versions": list(self.applied),
            "pending_versions": list(self.pending),
            "newly_applied_versions": newly_applied or [],
            "verified": not self.pending or set(self.pending) == set(newly_applied or []),
        }


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


def migration_manifest_sha256(migrations: list[Migration]) -> str:
    """Fingerprint the ordered version/checksum contract, independent of paths."""
    manifest = [{"version": item.version, "checksum": item.checksum} for item in migrations]
    return hashlib.sha256(
        json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def plan_migrations(cursor: Cursor, migrations: list[Migration]) -> MigrationPlan:
    """Validate immutable history and return a deterministic deployment plan."""
    ensure_history(cursor)
    cursor.execute("SELECT version, checksum FROM schema_migrations ORDER BY version")
    rows = cursor.fetchall()
    applied = dict(rows)
    known = {item.version: item.checksum for item in migrations}
    unknown = sorted(set(applied) - set(known) - LEGACY_SCHEMA_MARKERS)
    if unknown:
        raise RuntimeError(
            "database migration history is newer than this image: " + ", ".join(unknown)
        )
    for version, checksum in applied.items():
        if version in LEGACY_SCHEMA_MARKERS:
            continue
        if checksum != known[version]:
            raise RuntimeError(f"migration {version} changed after application")
    return MigrationPlan(
        known=tuple(item.version for item in migrations),
        applied=tuple(item.version for item in migrations if item.version in applied),
        pending=tuple(item.version for item in migrations if item.version not in applied),
        manifest_sha256=migration_manifest_sha256(migrations),
    )


def apply_migrations(cursor: Cursor, migrations: list[Migration]) -> list[str]:
    """Apply pending migrations and reject modified migration history."""
    cursor.execute("SELECT pg_advisory_lock(hashtext('productivity_schema_migrations'))")
    try:
        plan = plan_migrations(cursor, migrations)
        completed: list[str] = []
        for migration in migrations:
            if migration.version not in plan.pending:
                continue
            cursor.execute("BEGIN")
            try:
                cursor.execute(migration.sql)
                cursor.execute(
                    "INSERT INTO schema_migrations(version, checksum) VALUES (%s, %s)",
                    (migration.version, migration.checksum),
                )
                cursor.execute("COMMIT")
            except Exception:
                cursor.execute("ROLLBACK")
                raise
            completed.append(migration.version)
        return completed
    finally:
        cursor.execute(
            "SELECT pg_advisory_unlock(hashtext('productivity_schema_migrations'))"
        )
