from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from pathlib import Path

from waitress import create_server

from scheduler.app import create_app
from scheduler.config import validate_bind_host

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int | None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] != "--setup":
        # Keep the source and frozen Windows entry points on the same operator CLI.
        from scheduler.cli import main as cli_main
        return cli_main(arguments)
    parser = argparse.ArgumentParser(description="Agenda Relay standalone scheduler")
    parser.add_argument("--setup", action="store_true", help="Create local login and security configuration")
    args = parser.parse_args(arguments)
    if args.setup:
        from scheduler.setup import interactive_setup
        setup_directory = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
        raise SystemExit(interactive_setup(setup_directory))
    app = create_app()
    host = validate_bind_host(os.getenv("BIND_HOST", "127.0.0.1"), app.extensions["settings"].is_production)
    service = app.extensions["scheduling"]
    interval = max(int(os.getenv("WORKER_INTERVAL_SECONDS", "30")), 5)
    stop = threading.Event()

    def worker() -> None:
        while not stop.is_set():
            try:
                service.run_due_jobs()
            except Exception:
                logger.exception("Background scheduling worker failed")
            stop.wait(interval)

    server = None
    thread = None
    try:
        # Bind the listener before starting background work. A port/configuration
        # failure must not send reminders from an instance that never came online.
        server = create_server(
            app,
            host=host,
            port=int(os.getenv("PORT", "5000")),
            threads=max(2, min(int(os.getenv("WAITRESS_THREADS", "4")), 16)),
            connection_limit=max(20, min(int(os.getenv("WAITRESS_CONNECTION_LIMIT", "100")), 1000)),
            channel_timeout=120,
        )
        thread = threading.Thread(target=worker, name="agenda-relay-worker", daemon=True)
        thread.start()
        server.run()
    finally:
        stop.set()
        try:
            if thread is not None:
                thread.join(timeout=5)
            if server is not None:
                server.close()
        finally:
            app.extensions["store"].close()


if __name__ == "__main__":
    raise SystemExit(main())
