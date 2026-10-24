from __future__ import annotations

import platform
import sqlite3
import sysconfig

MINIMUM_SQLITE = (3, 54, 1)


def require_current_sqlite() -> None:
    if sqlite3.sqlite_version_info < MINIMUM_SQLITE:
        raise RuntimeError(
            "SQLite 3.54.1 or newer is required. Use the prepared runtime or current packaged image."
        )


def runtime_versions() -> dict:
    return {
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "free_threaded_build": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
    }
