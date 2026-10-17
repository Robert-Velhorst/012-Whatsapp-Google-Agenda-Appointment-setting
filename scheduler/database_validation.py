from __future__ import annotations

import sqlite3
from contextlib import closing
from functools import lru_cache

from .migrations import MIGRATIONS, migrate


def validate_app_database(connection: sqlite3.Connection) -> bool:
    """Check integrity, the complete migration ledger, and migration-derived columns."""
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
    if versions != {version for version, _ in MIGRATIONS}:
        return False

    expected = _expected_schema()
    try:
        actual_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        if not set(expected).issubset(actual_tables):
            return False
        for table, expected_columns in expected.items():
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
    """Derive required columns from the same migrations used by the application."""
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
