from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path

from scheduler.crypto import CryptoBox
from scheduler.store import Store


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(int(len(ordered) * fraction), len(ordered) - 1)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure Agenda Relay's local SQLite workload.")
    parser.add_argument("--records", type=int, default=500)
    parser.add_argument("--reads", type=int, default=250)
    args = parser.parse_args()
    if not 1 <= args.records <= 10_000 or not 1 <= args.reads <= 10_000:
        parser.error("records and reads must be between 1 and 10000")

    tracemalloc.start()
    with tempfile.TemporaryDirectory(prefix="agenda-relay-benchmark-") as folder:
        store = Store(Path(folder) / "benchmark.sqlite3", CryptoBox("benchmark-key"))
        try:
            store.ensure_workspace("benchmark", "Benchmark", "Europe/Amsterdam")
            write_started = time.perf_counter()
            for index in range(args.records):
                contact_id = store.upsert_contact("benchmark", f"316000{index:05d}", "Europe/Amsterdam")
                store.create_request(
                    "benchmark",
                    contact_id,
                    f"benchmark-{index}",
                    "Benchmark scheduling request",
                    30,
                    "Europe/Amsterdam",
                    "2026-08-10T09:00:00+02:00",
                    0.95,
                )
            write_seconds = time.perf_counter() - write_started

            latencies: list[float] = []
            for _ in range(args.reads):
                started = time.perf_counter()
                result = store.dashboard("benchmark", page=1, per_page=50)
                latencies.append((time.perf_counter() - started) * 1000)
            feed_started = time.perf_counter()
            feed, _ = store.hai_feed("benchmark", limit=500)
            feed_ms = (time.perf_counter() - feed_started) * 1000
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            store.close()

    report = {
        "records": args.records,
        "verified_total": result["total"],
        "write_records_per_second": round(args.records / write_seconds, 1),
        "dashboard_read_ms": {
            "median": round(statistics.median(latencies), 3),
            "p95": round(percentile(latencies, 0.95), 3),
            "maximum": round(max(latencies), 3),
        },
        "hai_feed_items": len(feed),
        "hai_feed_500_ms": round(feed_ms, 3),
        "python_peak_memory_mib": round(peak_bytes / 1024 / 1024, 2),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
