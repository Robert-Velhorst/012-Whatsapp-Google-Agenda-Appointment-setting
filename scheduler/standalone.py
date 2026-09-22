from __future__ import annotations

import logging
import os
import threading
import argparse

from waitress import serve

from scheduler.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Agenda Relay standalone scheduler")
    parser.add_argument("--setup", action="store_true", help="Create local login and security configuration")
    args = parser.parse_args()
    if args.setup:
        from scheduler.setup import interactive_setup
        raise SystemExit(interactive_setup())
    app = create_app()
    service = app.extensions["scheduling"]
    interval = max(int(os.getenv("WORKER_INTERVAL_SECONDS", "30")), 5)
    stop = threading.Event()

    def worker() -> None:
        while not stop.is_set():
            try:
                service.run_due_jobs()
            except Exception:
                logging.exception("Background scheduling worker failed")
            stop.wait(interval)

    thread = threading.Thread(target=worker, name="agenda-relay-worker", daemon=True)
    thread.start()
    try:
        serve(
            app,
            host=os.getenv("BIND_HOST", "127.0.0.1"),
            port=int(os.getenv("PORT", "5000")),
            threads=max(2, min(int(os.getenv("WAITRESS_THREADS", "4")), 16)),
            connection_limit=max(20, min(int(os.getenv("WAITRESS_CONNECTION_LIMIT", "100")), 1000)),
            channel_timeout=120,
        )
    finally:
        stop.set()
        thread.join(timeout=5)
        app.extensions["store"].close()


if __name__ == "__main__":
    main()
