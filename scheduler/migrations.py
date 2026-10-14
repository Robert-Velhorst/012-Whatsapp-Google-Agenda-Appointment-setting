from __future__ import annotations

import sqlite3

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
        CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS workspaces(
          id TEXT PRIMARY KEY, name TEXT NOT NULL, timezone TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS contacts(
          id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL, sender TEXT NOT NULL,
          display_name TEXT, email TEXT, timezone TEXT NOT NULL, language TEXT NOT NULL DEFAULT 'en',
          consent_status TEXT NOT NULL DEFAULT 'implicit_inbound', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(workspace_id, sender), FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
        );
        CREATE TABLE IF NOT EXISTS inbound_messages(
          id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL, external_id TEXT NOT NULL,
          sender TEXT NOT NULL, body_ciphertext TEXT NOT NULL, received_at TEXT NOT NULL,
          UNIQUE(workspace_id, external_id)
        );
        CREATE TABLE IF NOT EXISTS scheduling_requests(
          id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL, contact_id INTEGER NOT NULL,
          source_message_id TEXT NOT NULL, title TEXT NOT NULL, duration_minutes INTEGER NOT NULL,
          timezone TEXT NOT NULL, requested_start TEXT, status TEXT NOT NULL, confidence REAL NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(workspace_id, source_message_id),
          FOREIGN KEY(contact_id) REFERENCES contacts(id)
        );
        CREATE TABLE IF NOT EXISTS proposals(
          id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL, request_id INTEGER NOT NULL UNIQUE,
          reply_ciphertext TEXT NOT NULL, slots_json TEXT NOT NULL, booking_token_hash TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL, provider_message_id TEXT, error_text TEXT, created_at TEXT NOT NULL,
          sent_at TEXT, confirmed_at TEXT, selected_slot INTEGER,
          FOREIGN KEY(request_id) REFERENCES scheduling_requests(id)
        );
        CREATE TABLE IF NOT EXISTS appointments(
          id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL, request_id INTEGER NOT NULL UNIQUE,
          proposal_id INTEGER NOT NULL, start_at TEXT NOT NULL, end_at TEXT NOT NULL, timezone TEXT NOT NULL,
          status TEXT NOT NULL, google_event_id TEXT UNIQUE, google_event_link TEXT, error_text TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          FOREIGN KEY(request_id) REFERENCES scheduling_requests(id), FOREIGN KEY(proposal_id) REFERENCES proposals(id)
        );
        CREATE TABLE IF NOT EXISTS background_jobs(
          id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL, job_type TEXT NOT NULL,
          dedupe_key TEXT NOT NULL UNIQUE, run_at TEXT NOT NULL, payload_json TEXT NOT NULL,
          status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL, actor TEXT NOT NULL,
          action TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT, detail_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rate_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL, subject TEXT NOT NULL,
          action TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS system_state(
          workspace_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, updated_at TEXT NOT NULL,
          PRIMARY KEY(workspace_id, key)
        );
        CREATE INDEX IF NOT EXISTS idx_requests_workspace_status ON scheduling_requests(workspace_id, status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_messages_sender ON inbound_messages(workspace_id, sender, received_at DESC);
        CREATE INDEX IF NOT EXISTS idx_jobs_due ON background_jobs(status, run_at);
        CREATE INDEX IF NOT EXISTS idx_audit_workspace ON audit_events(workspace_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_rate_subject ON rate_events(workspace_id, subject, action, created_at DESC);
    """),
    (2, """
        ALTER TABLE proposals ADD COLUMN booking_token_ciphertext TEXT;
    """),
    (3, """
        CREATE INDEX IF NOT EXISTS idx_requests_workspace_updated ON scheduling_requests(workspace_id, updated_at, id);
        CREATE INDEX IF NOT EXISTS idx_contacts_workspace_updated ON contacts(workspace_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_proposals_workspace_status ON proposals(workspace_id, status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_appointments_workspace_status ON appointments(workspace_id, status, start_at);
        CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_events(workspace_id, entity_type, entity_id, id DESC);
    """),
    (4, """
        CREATE INDEX IF NOT EXISTS idx_jobs_stale ON background_jobs(workspace_id, status, updated_at);
    """),
    (5, """
        CREATE INDEX IF NOT EXISTS idx_messages_retention ON inbound_messages(workspace_id, received_at);
        CREATE INDEX IF NOT EXISTS idx_rate_retention ON rate_events(workspace_id, created_at);
    """),
    (6, """
        CREATE TABLE IF NOT EXISTS whatsapp_delivery_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL,
          provider_message_id TEXT NOT NULL, status TEXT NOT NULL,
          provider_timestamp TEXT NOT NULL, error_code TEXT, received_at TEXT NOT NULL,
          UNIQUE(workspace_id, provider_message_id, status, provider_timestamp),
          FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
        );
        CREATE INDEX IF NOT EXISTS idx_whatsapp_delivery_message
          ON whatsapp_delivery_events(workspace_id, provider_message_id, provider_timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_whatsapp_delivery_retention
          ON whatsapp_delivery_events(workspace_id, received_at);
    """),
    (7, """
        ALTER TABLE appointments ADD COLUMN booking_attempt INTEGER NOT NULL DEFAULT 0;
    """),
    (8, """
        UPDATE appointments SET booking_attempt=1
        WHERE status IN ('booking','booked','manual_required','failed') AND booking_attempt=0;
    """),
]


def migrate(connection: sqlite3.Connection, now_iso: str) -> list[int]:
    connection.execute("PRAGMA foreign_keys=ON")
    completed: list[int] = []
    for version, sql in MIGRATIONS:
        # Web and worker processes can start together against the same SQLite file.
        # Lock before checking the version so only one process applies each migration.
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            already_applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version=?", (version,)
            ).fetchone()
            if already_applied:
                connection.commit()
                continue
            _execute_statements(connection, sql)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, now_iso),
            )
            connection.commit()
            completed.append(version)
        except Exception:
            connection.rollback()
            raise
    return completed


def _execute_statements(connection: sqlite3.Connection, sql: str) -> None:
    """Execute a migration script without executescript's implicit transaction commit."""
    statement = ""
    for line in sql.splitlines():
        statement += line + "\n"
        if sqlite3.complete_statement(statement):
            if statement.strip():
                connection.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("Migration contains an incomplete SQL statement")
