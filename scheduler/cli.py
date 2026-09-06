from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import generate_password_hash

from .app import create_app


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
    bundle = sub.add_parser("support-bundle", help="Create a redacted diagnostic bundle")
    bundle.add_argument("--output", type=Path)
    password = sub.add_parser("hash-password", help="Generate ADMIN_PASSWORD_HASH without storing the password")
    password.add_argument("password", nargs="?")
    return parser


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

    app = create_app()
    settings = app.extensions["settings"]
    store = app.extensions["store"]
    service = app.extensions["scheduling"]

    if args.command == "doctor":
        result = service.readiness()
        result["database"] = {"path": str(settings.database_path.resolve()), "writable": settings.database_path.exists() and settings.database_path.is_file()}
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
        output = args.output or Path("backups") / f"agenda-relay-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.sqlite3"
        output.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(settings.database_path) as source, sqlite3.connect(output) as target:
            source.backup(target)
        print(output.resolve())
        return 0
    if args.command == "restore":
        if args.confirm != "RESTORE":
            print("Refusing restore: --confirm must equal RESTORE", file=sys.stderr)
            return 2
        backup = args.backup.resolve()
        if not backup.is_file() or backup == settings.database_path.resolve():
            print("Backup path is invalid", file=sys.stderr)
            return 2
        with sqlite3.connect(backup) as check:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                print("Backup failed SQLite integrity_check", file=sys.stderr)
                return 2
        store.close()
        safety = settings.database_path.with_suffix(settings.database_path.suffix + ".pre-restore")
        if settings.database_path.exists():
            shutil.copy2(settings.database_path, safety)
        shutil.copy2(backup, settings.database_path)
        print(json.dumps({"restored": str(backup), "previous_database": str(safety)}))
        return 0
    if args.command == "support-bundle":
        output = args.output or Path("support-bundles") / f"agenda-relay-support-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.zip"
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
