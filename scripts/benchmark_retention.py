from __future__ import annotations

import argparse
import json
import math
import platform
import sqlite3
import statistics
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from scheduler.store import Store, utc_now


def benchmark(rows: int, samples: int, warmups: int, indexed: bool) -> dict:
    with tempfile.TemporaryDirectory(prefix="agenda-relay-retention-benchmark-") as folder:
        store = Store(Path(folder) / "benchmark.sqlite3")
        store.ensure_workspace("benchmark", "Synthetic benchmark", "UTC")
        if not indexed:
            with store.connect() as db:
                db.execute("DROP INDEX idx_messages_retention")
                db.execute("DROP INDEX idx_rate_retention")

        timestamp = utc_now().isoformat()
        with store.connect() as db:
            db.executemany(
                "INSERT INTO inbound_messages(workspace_id,external_id,sender,body_ciphertext,received_at) "
                "VALUES(?,?,?,?,?)",
                (("benchmark", f"message-{index}", f"sender-{index % 1000}", "x", timestamp) for index in range(rows)),
            )
            db.executemany(
                "INSERT INTO rate_events(workspace_id,subject,action,created_at) VALUES(?,?,?,?)",
                (("benchmark", f"sender-{index % 1000}", "test", timestamp) for index in range(rows)),
            )

        cutoff = (utc_now() - timedelta(days=30)).isoformat()
        with store.connect() as db:
            message_plan = [
                row[3]
                for row in db.execute(
                    "EXPLAIN QUERY PLAN DELETE FROM inbound_messages WHERE workspace_id=? AND received_at<?",
                    ("benchmark", cutoff),
                )
            ]
            rate_plan = [
                row[3]
                for row in db.execute(
                    "EXPLAIN QUERY PLAN DELETE FROM rate_events WHERE workspace_id=? AND created_at<?",
                    ("benchmark", cutoff),
                )
            ]
            database_bytes = db.execute("PRAGMA page_count").fetchone()[0] * db.execute("PRAGMA page_size").fetchone()[0]

        for _ in range(warmups):
            store.purge_expired("benchmark", 30)
        elapsed_ms = []
        for _ in range(samples):
            started = time.perf_counter()
            store.purge_expired("benchmark", 30)
            elapsed_ms.append((time.perf_counter() - started) * 1000)
        store.close()

    ordered = sorted(elapsed_ms)
    return {
        "rows_per_table": rows,
        "median_ms": round(statistics.median(elapsed_ms), 4),
        "p95_ms": round(ordered[math.ceil(0.95 * len(ordered)) - 1], 4),
        "max_ms": round(max(elapsed_ms), 4),
        "message_plan": message_plan,
        "rate_plan": rate_plan,
        "database_mib": round(database_bytes / 1024 / 1024, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Agenda Relay retention queries using synthetic SQLite data.")
    parser.add_argument("--rows", type=int, default=100_000, help="Synthetic rows per table (1–1,000,000).")
    parser.add_argument("--samples", type=int, default=100, help="Timed purge samples per schema (5–10,000).")
    parser.add_argument("--warmups", type=int, default=5, help="Untimed purge calls before measurement (0–100).")
    args = parser.parse_args()
    if not 1 <= args.rows <= 1_000_000:
        parser.error("--rows must be between 1 and 1000000")
    if not 5 <= args.samples <= 10_000:
        parser.error("--samples must be between 5 and 10000")
    if not 0 <= args.warmups <= 100:
        parser.error("--warmups must be between 0 and 100")

    report = {
        "dataset": "synthetic SQLite rows; no expired records; temporary databases",
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "platform": platform.platform(),
        "samples": args.samples,
        "warmups": args.warmups,
        "before_indexes": benchmark(args.rows, args.samples, args.warmups, indexed=False),
        "after_indexes": benchmark(args.rows, args.samples, args.warmups, indexed=True),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
