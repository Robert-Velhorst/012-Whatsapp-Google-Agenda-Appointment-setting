from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from werkzeug.security import generate_password_hash

from .app import create_app
from .config import Settings
from .crypto_rotation import rotate_encryption_bundle
from .migrations import MIGRATIONS, migrate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agenda-relay", description="Agenda Relay operator commands")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="Create local login and encryption configuration without overwriting existing settings")
    sub.add_parser("doctor", help="Validate configuration, storage, and provider readiness")
    sub.add_parser("migrate", help="Apply safe forward-only SQLite migrations")
    worker = sub.add_parser("worker", help="Process due reminder and retention jobs")
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--interval", type=int, default=30)
    backup = sub.add_parser("backup", help="Create a consistent SQLite backup")
    backup.add_argument("--output", type=Path)
    restore = sub.add_parser("restore", help="Restore a validated SQLite backup")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--confirm", required=True, help="Must equal RESTORE")
    rotate = sub.add_parser("rotate-encryption-key", help="Create a verified, non-overwriting encrypted-data rotation bundle")
    rotate.add_argument("--output-dir", type=Path, required=True, help="New directory for rotated database, token file, and manifest")
    bundle = sub.add_parser("support-bundle", help="Create a redacted diagnostic bundle")
    bundle.add_argument("--output", type=Path)
    password = sub.add_parser("hash-password", help="Generate ADMIN_PASSWORD_HASH without storing the password")
    password.add_argument("password", nargs="?")
    return parser


def _database_is_healthy_and_writable(path: Path) -> bool:
    """Check SQLite integrity and prove a write lock can be acquired without changing data."""
    try:
        with closing(sqlite3.connect(path, timeout=2)) as connection:
            if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
                return False
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
        return True
    except (OSError, sqlite3.Error):
        return False


def _validate_app_database(connection: sqlite3.Connection) -> bool:
    try:
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            return False
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            return False
    except sqlite3.Error:
        return False
    try:
        versions = {
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }
    except sqlite3.Error:
        return False
    expected_versions = {version for version, _ in MIGRATIONS}
    if versions != expected_versions:
        return False

    expected_schema = _expected_schema()
    try:
        actual_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        if not set(expected_schema).issubset(actual_tables):
            return False
        for table, expected_columns in expected_schema.items():
            quoted_table = table.replace('"', '""')
            actual_columns = {
                row[1]: (row[2].upper(), row[3], row[5])
                for row in connection.execute(f'PRAGMA table_info("{quoted_table}")').fetchall()
            }
            if any(actual_columns.get(column) != signature for column, signature in expected_columns.items()):
                return False
    except sqlite3.Error:
        return False
    return True


@lru_cache(maxsize=1)
def _expected_schema() -> dict[str, dict[str, tuple[str, int, int]]]:
    """Derive required table columns from the same migrations used by the application."""
    with closing(sqlite3.connect(":memory:")) as reference:
        migrate(reference, "1970-01-01T00:00:00+00:00")
        tables = reference.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {
            table[0]: {
                row[1]: (row[2].upper(), row[3], row[5])
                for row in reference.execute(f'PRAGMA table_info("{table[0]}")').fetchall()
            }
            for table in tables
        }


def _online_backup(source_path: Path, destination: Path) -> None:
    """Create a consistent SQLite backup and atomically publish it at destination."""
    source = source_path.resolve()
    output = destination.resolve()
    if source == output:
        raise ValueError("Backup output cannot be the live database")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with closing(sqlite3.connect(source)) as source_db, closing(sqlite3.connect(temporary)) as target_db:
            source_db.backup(target_db)
            if not _validate_app_database(target_db):
                raise ValueError("Source database failed integrity or schema validation")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def _restore_database(backup_path: Path, database_path: Path, store) -> Path | None:
    """Stage a validated restore, snapshot the current DB, then atomically replace it."""
    backup = backup_path.resolve()
    database = database_path.resolve()
    if backup == database or not backup.is_file():
        raise ValueError("Backup path is invalid")
    with closing(sqlite3.connect(backup)) as candidate:
        if not _validate_app_database(candidate):
            raise ValueError("Backup failed SQLite integrity or application schema validation")

    database.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{database.name}.", suffix=".restore", dir=database.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    safety = database.with_name(f"{database.name}.pre-restore-{datetime.now(UTC):%Y%m%d-%H%M%S-%f}")
    try:
        with closing(sqlite3.connect(backup)) as source_db, closing(sqlite3.connect(temporary)) as staged_db:
            source_db.backup(staged_db)
            if not _validate_app_database(staged_db):
                raise ValueError("Staged backup failed SQLite integrity or application schema validation")
        if database.exists():
            with closing(sqlite3.connect(database)) as current_db, closing(sqlite3.connect(safety)) as safety_db:
                current_db.backup(safety_db)
            with closing(sqlite3.connect(safety)) as safety_db:
                if not _validate_app_database(safety_db):
                    raise ValueError("Could not verify the pre-restore safety backup")
        store.close()
        # A non-empty WAL means another process may still have the database open. Replacing
        # the main file in that state could lose committed data, so fail closed.
        wal_path = Path(f"{database}-wal")
        if wal_path.exists() and wal_path.stat().st_size:
            raise RuntimeError("Database WAL is still active; stop all web and worker processes before restoring")
        os.replace(temporary, database)
        return safety if safety.exists() else None
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "setup":
        from .setup import interactive_setup
        return interactive_setup()
    if args.command == "hash-password":
        import getpass
        password = args.password or getpass.getpass("Operator password: ")
        if len(password) < 12:
            print("Password must be at least 12 characters", file=sys.stderr)
            return 2
        print(generate_password_hash(password))
        return 0

    if args.command == "rotate-encryption-key":
        settings = Settings.from_env()
        try:
            result = rotate_encryption_bundle(
                settings.database_path,
                Path(settings.google_token_file),
                args.output_dir,
                settings.data_encryption_key,
                os.getenv("NEW_DATA_ENCRYPTION_KEY", ""),
            )
        except (OSError, sqlite3.Error, ValueError) as exc:
            print(f"Encryption-key rotation failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, indent=2))
        return 0

    app = create_app()
    settings = app.extensions["settings"]
    store = app.extensions["store"]
    service = app.extensions["scheduling"]

    if args.command == "doctor":
        result = service.readiness()
        result["database"] = {
            "path": str(settings.database_path.resolve()),
            "writable": _database_is_healthy_and_writable(settings.database_path),
        }
        print(json.dumps(result, indent=2))
        return 0 if result["ready"] else 1
    if args.command == "migrate":
        print(json.dumps({"ok": True, "database": str(settings.database_path.resolve())}))
        return 0
    if args.command == "worker":
        while True:
            print(json.dumps(service.run_due_jobs(), sort_keys=True), flush=True)
            if args.once:
                return 0
            time.sleep(max(args.interval, 5))
    if args.command == "backup":
        output = args.output or Path("backups") / f"agenda-relay-{datetime.now(UTC):%Y%m%d-%H%M%S}.sqlite3"
        try:
            _online_backup(settings.database_path, output)
        except (OSError, sqlite3.Error, ValueError) as exc:
            print(f"Backup failed: {exc}", file=sys.stderr)
            return 2
        print(output.resolve())
        return 0
    if args.command == "restore":
        if args.confirm != "RESTORE":
            print("Refusing restore: --confirm must equal RESTORE", file=sys.stderr)
            return 2
        try:
            safety = _restore_database(args.backup, settings.database_path, store)
        except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
            print(f"Restore failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({"restored": str(args.backup.resolve()), "previous_database": str(safety) if safety else None}))
        return 0
    if args.command == "support-bundle":
        output = args.output or Path("support-bundles") / f"agenda-relay-support-{datetime.now(UTC):%Y%m%d-%H%M%S}.zip"
        output.parent.mkdir(parents=True, exist_ok=True)
        readiness = service.readiness()
        audit = [{"action": row["action"], "entity_type": row["entity_type"], "created_at": row["created_at"]} for row in store.recent_audit(settings.workspace_id, 100)]
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("readiness.json", json.dumps(readiness, indent=2))
            archive.writestr("recent-actions.json", json.dumps(audit, indent=2))
            archive.writestr("runtime.json", json.dumps({"app_env": settings.app_env, "timezone": settings.timezone, "database_exists": settings.database_path.exists()}, indent=2))
        print(output.resolve())
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
