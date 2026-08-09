from __future__ import annotations

import hashlib
import base64
import json
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .crypto import CryptoBox
from .domain import transition_allowed
from .migrations import migrate


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, path: Path, crypto: CryptoBox | None = None):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.crypto = crypto or CryptoBox("")
        self._local = threading.local()
        with self.connect() as db:
            migrate(db, utc_now().isoformat())

    @contextmanager
    def connect(self):
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self.path, timeout=5, cached_statements=256)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA temp_store=MEMORY")
            connection.execute("PRAGMA cache_size=-4096")
            self._local.connection = connection
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def close(self) -> None:
        """Close the connection owned by the current thread."""
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            try:
                connection.execute("PRAGMA optimize")
            finally:
                connection.close()
                del self._local.connection

    def ensure_workspace(self, workspace_id: str, name: str, timezone_name: str) -> None:
        now = utc_now().isoformat()
        with self.connect() as db:
            db.execute(
                "INSERT INTO workspaces(id,name,timezone,created_at) VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, timezone=excluded.timezone",
                (workspace_id, name, timezone_name, now),
            )

    def audit(self, workspace_id: str, actor: str, action: str, entity_type: str, entity_id: Any = None, detail: dict | None = None) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO audit_events(workspace_id,actor,action,entity_type,entity_id,detail_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (workspace_id, actor, action, entity_type, None if entity_id is None else str(entity_id), json.dumps(detail or {}, sort_keys=True), utc_now().isoformat()),
            )

    def set_state(self, workspace_id: str, key: str, value: str, actor: str = "operator") -> None:
        now = utc_now().isoformat()
        with self.connect() as db:
            db.execute(
                "INSERT INTO system_state(workspace_id,key,value,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(workspace_id,key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                (workspace_id, key, value, now),
            )
        self.audit(workspace_id, actor, "system_state.changed", "system", key, {"value": value})

    def get_state(self, workspace_id: str, key: str, default: str = "") -> str:
        with self.connect() as db:
            row = db.execute("SELECT value FROM system_state WHERE workspace_id=? AND key=?", (workspace_id, key)).fetchone()
        return row[0] if row else default

    def upsert_contact(self, workspace_id: str, sender: str, timezone_name: str, language: str = "en", display_name: str | None = None) -> int:
        now = utc_now().isoformat()
        with self.connect() as db:
            db.execute(
                "INSERT INTO contacts(workspace_id,sender,display_name,timezone,language,created_at,updated_at) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(workspace_id,sender) DO UPDATE SET display_name=COALESCE(excluded.display_name,contacts.display_name), "
                "language=excluded.language,updated_at=excluded.updated_at",
                (workspace_id, sender, display_name, timezone_name, language, now, now),
            )
            row = db.execute("SELECT id FROM contacts WHERE workspace_id=? AND sender=?", (workspace_id, sender)).fetchone()
        return int(row[0])

    def update_contact(self, workspace_id: str, contact_id: int, *, display_name: str | None, email: str | None, timezone_name: str, language: str, consent_status: str) -> bool:
        if consent_status not in {"implicit_inbound", "confirmed", "revoked"}:
            raise ValueError("Invalid consent status")
        if language not in {"en", "nl"}:
            raise ValueError("Language must be en or nl")
        if email and ("@" not in email or len(email) > 254):
            raise ValueError("Email address is invalid")
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Timezone is invalid") from exc
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE contacts SET display_name=?,email=?,timezone=?,language=?,consent_status=?,updated_at=? WHERE workspace_id=? AND id=?",
                (display_name or None, email or None, timezone_name, language, consent_status, utc_now().isoformat(), workspace_id, contact_id),
            )
        if cursor.rowcount:
            self.audit(workspace_id, "operator", "contact.updated", "contact", contact_id, {"consent_status": consent_status})
        return cursor.rowcount == 1

    def record_inbound(self, workspace_id: str, external_id: str, sender: str, body: str, received_at: str) -> bool:
        with self.connect() as db:
            try:
                db.execute(
                    "INSERT INTO inbound_messages(workspace_id,external_id,sender,body_ciphertext,received_at) VALUES(?,?,?,?,?)",
                    (workspace_id, external_id, sender, self.crypto.encrypt(body), received_at),
                )
            except sqlite3.IntegrityError:
                return False
        self.audit(workspace_id, "whatsapp", "message.received", "message", external_id, {"sender_suffix": sender[-4:]})
        return True

    def recent_messages(self, workspace_id: str, sender: str, limit: int = 12) -> list[dict[str, str]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT external_id,body_ciphertext,received_at FROM inbound_messages WHERE workspace_id=? AND sender=? ORDER BY id DESC LIMIT ?",
                (workspace_id, sender, min(max(limit, 1), 50)),
            ).fetchall()
        return [{"external_id": row["external_id"], "body": self.crypto.decrypt(row["body_ciphertext"]), "received_at": row["received_at"]} for row in reversed(rows)]

    def create_request(self, workspace_id: str, contact_id: int, source_message_id: str, title: str, duration: int, timezone_name: str, requested_start: str, confidence: float) -> int:
        now = utc_now().isoformat()
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO scheduling_requests(workspace_id,contact_id,source_message_id,title,duration_minutes,timezone,requested_start,status,confidence,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (workspace_id, contact_id, source_message_id, title, duration, timezone_name, requested_start, "detected", confidence, now, now),
            )
            request_id = int(cursor.lastrowid)
        self.audit(workspace_id, "scheduler", "request.detected", "request", request_id, {"confidence": confidence, "duration_minutes": duration})
        return request_id

    def transition_request(self, workspace_id: str, request_id: int, target: str, actor: str, detail: dict | None = None) -> None:
        with self.connect() as db:
            row = db.execute("SELECT status FROM scheduling_requests WHERE workspace_id=? AND id=?", (workspace_id, request_id)).fetchone()
            if not row:
                raise KeyError("Scheduling request not found")
            current = row[0]
            if not transition_allowed(current, target):
                raise ValueError(f"Invalid request transition {current} -> {target}")
            db.execute("UPDATE scheduling_requests SET status=?,updated_at=? WHERE workspace_id=? AND id=?", (target, utc_now().isoformat(), workspace_id, request_id))
        self.audit(workspace_id, actor, "request.transition", "request", request_id, {"from": current, "to": target, **(detail or {})})

    def create_proposal(self, workspace_id: str, request_id: int, reply_text: str, slots: list[str], booking_token: str | None = None) -> tuple[int, str]:
        now = utc_now().isoformat()
        raw_token = booking_token or secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO proposals(workspace_id,request_id,reply_ciphertext,slots_json,booking_token_hash,booking_token_ciphertext,status,created_at) VALUES(?,?,?,?,?,?,'pending_approval',?)",
                (workspace_id, request_id, self.crypto.encrypt(reply_text), json.dumps(slots), token_hash, self.crypto.encrypt(raw_token), now),
            )
            proposal_id = int(cursor.lastrowid)
        self.transition_request(workspace_id, request_id, "proposal_pending", "scheduler", {"proposal_id": proposal_id})
        return proposal_id, raw_token

    def update_proposal_reply(self, workspace_id: str, proposal_id: int, reply_text: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE proposals SET reply_ciphertext=? WHERE workspace_id=? AND id=?", (self.crypto.encrypt(reply_text), workspace_id, proposal_id))

    def get_proposal(self, workspace_id: str, proposal_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT p.*,r.title,r.duration_minutes,r.contact_id,c.sender,c.display_name,c.email,c.language,c.consent_status "
                "FROM proposals p JOIN scheduling_requests r ON r.id=p.request_id JOIN contacts c ON c.id=r.contact_id "
                "WHERE p.workspace_id=? AND p.id=?",
                (workspace_id, proposal_id),
            ).fetchone()
        return self._proposal(row) if row else None

    def get_proposal_by_token(self, token: str) -> dict[str, Any] | None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            row = db.execute(
                "SELECT p.*,r.title,r.duration_minutes,r.contact_id,c.sender,c.display_name,c.email,c.language,c.consent_status "
                "FROM proposals p JOIN scheduling_requests r ON r.id=p.request_id JOIN contacts c ON c.id=r.contact_id "
                "WHERE p.booking_token_hash=?",
                (token_hash,),
            ).fetchone()
        return self._proposal(row) if row else None

    def latest_sent_proposal(self, workspace_id: str, sender: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT p.*,r.title,r.duration_minutes,r.contact_id,c.sender,c.display_name,c.email,c.language,c.consent_status "
                "FROM proposals p JOIN scheduling_requests r ON r.id=p.request_id JOIN contacts c ON c.id=r.contact_id "
                "WHERE p.workspace_id=? AND c.sender=? AND p.status='sent' ORDER BY p.id DESC LIMIT 1",
                (workspace_id, sender),
            ).fetchone()
        return self._proposal(row) if row else None

    def mark_proposal_sent(self, workspace_id: str, proposal_id: int, provider_message_id: str | None) -> None:
        with self.connect() as db:
            row = db.execute("SELECT request_id,status FROM proposals WHERE workspace_id=? AND id=?", (workspace_id, proposal_id)).fetchone()
            if not row or row["status"] not in {"pending_approval", "send_failed"}:
                raise ValueError("Proposal is not sendable")
            db.execute("UPDATE proposals SET status='sent',provider_message_id=?,sent_at=?,error_text=NULL WHERE id=?", (provider_message_id, utc_now().isoformat(), proposal_id))
        self.transition_request(workspace_id, int(row["request_id"]), "awaiting_confirmation", "operator", {"proposal_id": proposal_id})

    def mark_proposal_failed(self, workspace_id: str, proposal_id: int, error: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE proposals SET status='send_failed',error_text=? WHERE workspace_id=? AND id=?", (error[:500], workspace_id, proposal_id))
        self.audit(workspace_id, "scheduler", "proposal.send_failed", "proposal", proposal_id, {"error": error[:200]})

    def confirm_proposal(self, workspace_id: str, proposal_id: int, slot_index: int, actor: str) -> int:
        now = utc_now().isoformat()
        with self.connect() as db:
            row = db.execute("SELECT request_id,slots_json,status FROM proposals WHERE workspace_id=? AND id=?", (workspace_id, proposal_id)).fetchone()
            if not row or row["status"] != "sent":
                raise ValueError("Proposal is not awaiting confirmation")
            slots = json.loads(row["slots_json"])
            if slot_index < 0 or slot_index >= len(slots):
                raise ValueError("Selected slot is outside proposal")
            request_row = db.execute("SELECT duration_minutes,timezone FROM scheduling_requests WHERE id=?", (row["request_id"],)).fetchone()
            start = datetime.fromisoformat(slots[slot_index])
            end = start + timedelta(minutes=int(request_row["duration_minutes"]))
            db.execute("UPDATE proposals SET status='confirmed',confirmed_at=?,selected_slot=? WHERE id=?", (now, slot_index, proposal_id))
            cursor = db.execute(
                "INSERT INTO appointments(workspace_id,request_id,proposal_id,start_at,end_at,timezone,status,created_at,updated_at) VALUES(?,?,?,?,?,?,'pending_approval',?,?)",
                (workspace_id, row["request_id"], proposal_id, start.isoformat(), end.isoformat(), request_row["timezone"], now, now),
            )
            appointment_id = int(cursor.lastrowid)
        self.transition_request(workspace_id, int(row["request_id"]), "slot_confirmed", actor, {"slot_index": slot_index, "appointment_id": appointment_id})
        self.audit(workspace_id, actor, "proposal.confirmed", "proposal", proposal_id, {"slot_index": slot_index})
        return appointment_id

    def get_appointment(self, workspace_id: str, appointment_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT a.*,r.title,r.duration_minutes,r.contact_id,c.sender,c.display_name,c.email,c.language,c.consent_status "
                "FROM appointments a JOIN scheduling_requests r ON r.id=a.request_id JOIN contacts c ON c.id=r.contact_id "
                "WHERE a.workspace_id=? AND a.id=?",
                (workspace_id, appointment_id),
            ).fetchone()
        return dict(row) if row else None

    def claim_booking(self, workspace_id: str, appointment_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE appointments SET status='booking',updated_at=? WHERE workspace_id=? AND id=? AND status IN ('pending_approval','failed')",
                (utc_now().isoformat(), workspace_id, appointment_id),
            )
            if cursor.rowcount != 1:
                return None
        appointment = self.get_appointment(workspace_id, appointment_id)
        self.transition_request(workspace_id, int(appointment["request_id"]), "booking_pending", "operator", {"appointment_id": appointment_id})
        return appointment

    def mark_booked(self, workspace_id: str, appointment_id: int, event_id: str, event_link: str | None) -> None:
        now = utc_now().isoformat()
        with self.connect() as db:
            row = db.execute("SELECT request_id FROM appointments WHERE workspace_id=? AND id=?", (workspace_id, appointment_id)).fetchone()
            db.execute("UPDATE appointments SET status='booked',google_event_id=?,google_event_link=?,error_text=NULL,updated_at=? WHERE id=?", (event_id, event_link, now, appointment_id))
        self.transition_request(workspace_id, int(row["request_id"]), "booked", "scheduler", {"appointment_id": appointment_id, "google_event_id": event_id})

    def mark_booking_failed(self, workspace_id: str, appointment_id: int, error: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE appointments SET status='failed',error_text=?,updated_at=? WHERE workspace_id=? AND id=?", (error[:500], utc_now().isoformat(), workspace_id, appointment_id))
        self.audit(workspace_id, "scheduler", "appointment.booking_failed", "appointment", appointment_id, {"error": error[:200]})

    def cancel_appointment(self, workspace_id: str, appointment_id: int, actor: str) -> bool:
        now = utc_now().isoformat()
        with self.connect() as db:
            row = db.execute("SELECT request_id,status FROM appointments WHERE workspace_id=? AND id=?", (workspace_id, appointment_id)).fetchone()
            if not row or row["status"] == "cancelled":
                return False
            db.execute("UPDATE appointments SET status='cancelled',updated_at=? WHERE id=?", (now, appointment_id))
            db.execute("UPDATE background_jobs SET status='cancelled',updated_at=? WHERE workspace_id=? AND payload_json LIKE ? AND status IN ('queued','manual_required','failed')", (now, workspace_id, f'%"appointment_id": {appointment_id}%'))
        self.transition_request(workspace_id, int(row["request_id"]), "cancelled", actor, {"appointment_id": appointment_id})
        return True

    def schedule_job(self, workspace_id: str, job_type: str, dedupe_key: str, run_at: str, payload: dict) -> int | None:
        now = utc_now().isoformat()
        with self.connect() as db:
            try:
                cursor = db.execute(
                    "INSERT INTO background_jobs(workspace_id,job_type,dedupe_key,run_at,payload_json,status,created_at,updated_at) VALUES(?,?,?,?,?,'queued',?,?)",
                    (workspace_id, job_type, dedupe_key, run_at, json.dumps(payload), now, now),
                )
            except sqlite3.IntegrityError:
                return None
        return int(cursor.lastrowid)

    def claim_due_jobs(self, workspace_id: str, now_iso: str, limit: int = 20) -> list[dict[str, Any]]:
        claimed: list[dict[str, Any]] = []
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM background_jobs WHERE workspace_id=? AND status='queued' AND run_at<=? ORDER BY run_at LIMIT ?",
                (workspace_id, now_iso, limit),
            ).fetchall()
            for row in rows:
                cursor = db.execute("UPDATE background_jobs SET status='running',attempts=attempts+1,updated_at=? WHERE id=? AND status='queued'", (utc_now().isoformat(), row["id"]))
                if cursor.rowcount:
                    data = dict(row)
                    data["payload"] = json.loads(data.pop("payload_json"))
                    claimed.append(data)
        return claimed

    def complete_job(self, workspace_id: str, job_id: int, status: str, error: str | None = None) -> None:
        if status not in {"sent", "manual_required", "failed", "cancelled"}:
            raise ValueError("Invalid terminal job state")
        with self.connect() as db:
            db.execute("UPDATE background_jobs SET status=?,last_error=?,updated_at=? WHERE workspace_id=? AND id=?", (status, error, utc_now().isoformat(), workspace_id, job_id))
        self.audit(workspace_id, "worker", f"job.{status}", "job", job_id, {"error": error} if error else {})

    def outbound_allowed(self, workspace_id: str, subject: str, max_per_hour: int) -> bool:
        cutoff = (utc_now() - timedelta(hours=1)).isoformat()
        with self.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM rate_events WHERE workspace_id=? AND subject=? AND action='whatsapp.send' AND created_at>=?", (workspace_id, subject, cutoff)).fetchone()[0]
        return int(count) < max_per_hour

    def record_outbound(self, workspace_id: str, subject: str) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO rate_events(workspace_id,subject,action,created_at) VALUES(?,?,'whatsapp.send',?)", (workspace_id, subject, utc_now().isoformat()))

    def rate_allowed(self, workspace_id: str, subject: str, action: str, maximum: int, window_minutes: int) -> bool:
        cutoff = (utc_now() - timedelta(minutes=window_minutes)).isoformat()
        with self.connect() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM rate_events WHERE workspace_id=? AND subject=? AND action=? AND created_at>=?",
                (workspace_id, subject, action, cutoff),
            ).fetchone()[0]
        return int(count) < maximum

    def record_rate_event(self, workspace_id: str, subject: str, action: str) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO rate_events(workspace_id,subject,action,created_at) VALUES(?,?,?,?)",
                (workspace_id, subject, action, utc_now().isoformat()),
            )

    def dashboard(self, workspace_id: str, query: str = "", status: str = "", page: int = 1, per_page: int = 25) -> dict[str, Any]:
        page = max(page, 1)
        per_page = min(max(per_page, 1), 100)
        where = ["r.workspace_id=?"]
        args: list[Any] = [workspace_id]
        if query:
            where.append("(c.sender LIKE ? OR c.display_name LIKE ? OR r.title LIKE ?)")
            pattern = f"%{query}%"
            args.extend([pattern, pattern, pattern])
        if status:
            where.append("r.status=?")
            args.append(status)
        where_sql = " AND ".join(where)
        with self.connect() as db:
            total = db.execute(f"SELECT COUNT(*) FROM scheduling_requests r JOIN contacts c ON c.id=r.contact_id WHERE {where_sql}", args).fetchone()[0]
            rows = db.execute(
                f"SELECT r.*,c.sender,c.display_name,c.email,c.consent_status,p.id proposal_id,p.status proposal_status,p.slots_json,p.selected_slot,a.id appointment_id,a.status appointment_status,a.start_at,a.google_event_link "
                f"FROM scheduling_requests r JOIN contacts c ON c.id=r.contact_id LEFT JOIN proposals p ON p.request_id=r.id LEFT JOIN appointments a ON a.request_id=r.id "
                f"WHERE {where_sql} ORDER BY r.updated_at DESC LIMIT ? OFFSET ?",
                [*args, per_page, (page - 1) * per_page],
            ).fetchall()
            counts = {row["status"]: row["count"] for row in db.execute("SELECT status,COUNT(*) count FROM scheduling_requests WHERE workspace_id=? GROUP BY status", (workspace_id,))}
            jobs = [dict(row) for row in db.execute("SELECT * FROM background_jobs WHERE workspace_id=? AND status IN ('queued','manual_required','failed') ORDER BY run_at LIMIT 10", (workspace_id,)).fetchall()]
        return {"items": [self._request_row(row) for row in rows], "total": int(total), "page": page, "per_page": per_page, "counts": counts, "jobs": jobs}

    def export_requests(self, workspace_id: str, limit: int = 10_000) -> list[dict[str, Any]]:
        """Return a bounded, workspace-scoped export independent of UI pagination."""
        with self.connect() as db:
            rows = db.execute(
                "SELECT r.id,c.sender,c.display_name,r.title,r.status,r.confidence,r.created_at "
                "FROM scheduling_requests r JOIN contacts c ON c.id=r.contact_id "
                "WHERE r.workspace_id=? ORDER BY r.created_at DESC LIMIT ?",
                (workspace_id, min(max(limit, 1), 10_000)),
            ).fetchall()
        return [dict(row) for row in rows]

    def hai_feed(self, workspace_id: str, cursor: str = "", limit: int = 100) -> tuple[list[dict[str, Any]], str]:
        """Return a PII-minimized, cursor-based request feed for HAI's json-feed connector."""
        timestamp, cursor_id = self._decode_feed_cursor(cursor)
        page_size = min(max(limit, 1), 500)
        with self.connect() as db:
            rows = db.execute(
                "SELECT r.id,r.title,r.duration_minutes,r.timezone,r.requested_start,r.status,r.confidence,r.created_at,r.updated_at,"
                "p.status proposal_status,a.status appointment_status,a.start_at,a.end_at "
                "FROM scheduling_requests r "
                "LEFT JOIN proposals p ON p.request_id=r.id "
                "LEFT JOIN appointments a ON a.request_id=r.id "
                "WHERE r.workspace_id=? AND (r.updated_at>? OR (r.updated_at=? AND r.id>?)) "
                "ORDER BY r.updated_at,r.id LIMIT ?",
                (workspace_id, timestamp, timestamp, cursor_id, page_size),
            ).fetchall()
        items = [dict(row) for row in rows]
        next_cursor = cursor
        if items:
            last = items[-1]
            next_cursor = self._encode_feed_cursor(last["updated_at"], int(last["id"]))
        return items, next_cursor

    @staticmethod
    def _encode_feed_cursor(timestamp: str, request_id: int) -> str:
        raw = json.dumps([timestamp, request_id], separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _decode_feed_cursor(cursor: str) -> tuple[str, int]:
        if not cursor:
            return "", 0
        try:
            padding = "=" * (-len(cursor) % 4)
            value = json.loads(base64.urlsafe_b64decode(cursor + padding))
            if not isinstance(value, list) or len(value) != 2 or not isinstance(value[0], str) or not isinstance(value[1], int) or value[1] < 0:
                raise ValueError
            datetime.fromisoformat(value[0])
            return value[0], value[1]
        except Exception as exc:
            raise ValueError("Invalid HAI feed cursor") from exc

    def request_detail(self, workspace_id: str, request_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT r.*,c.sender,c.display_name,c.email,c.consent_status,p.id proposal_id,p.status proposal_status,p.slots_json,p.selected_slot,a.id appointment_id,a.status appointment_status,a.start_at,a.google_event_link "
                "FROM scheduling_requests r JOIN contacts c ON c.id=r.contact_id LEFT JOIN proposals p ON p.request_id=r.id LEFT JOIN appointments a ON a.request_id=r.id "
                "WHERE r.workspace_id=? AND r.id=?",
                (workspace_id, request_id),
            ).fetchone()
            if not row:
                return None
            request_data = self._request_row(row)
            contact = db.execute("SELECT * FROM contacts WHERE workspace_id=? AND id=?", (workspace_id, request_data["contact_id"])).fetchone()
            audit_rows = db.execute("SELECT * FROM audit_events WHERE workspace_id=? AND ((entity_type='request' AND entity_id=?) OR (entity_type='proposal' AND entity_id=?) OR (entity_type='appointment' AND entity_id=?)) ORDER BY created_at", (workspace_id, str(request_id), str(request_data.get("proposal_id")), str(request_data.get("appointment_id")))).fetchall()
        request_data["contact"] = dict(contact)
        request_data["messages"] = self.recent_messages(workspace_id, request_data["sender"], 8)
        request_data["audit"] = [self._audit_row(row) for row in audit_rows]
        return request_data

    def recent_audit(self, workspace_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM audit_events WHERE workspace_id=? ORDER BY id DESC LIMIT ?", (workspace_id, min(limit, 500))).fetchall()
        return [self._audit_row(row) for row in rows]

    def contacts(self, workspace_id: str, query: str = "") -> list[dict[str, Any]]:
        with self.connect() as db:
            if query:
                pattern = f"%{query}%"
                rows = db.execute("SELECT * FROM contacts WHERE workspace_id=? AND (sender LIKE ? OR display_name LIKE ? OR email LIKE ?) ORDER BY updated_at DESC LIMIT 100", (workspace_id, pattern, pattern, pattern)).fetchall()
            else:
                rows = db.execute("SELECT * FROM contacts WHERE workspace_id=? ORDER BY updated_at DESC LIMIT 100", (workspace_id,)).fetchall()
        return [dict(row) for row in rows]

    def export_contact(self, workspace_id: str, contact_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            contact = db.execute("SELECT * FROM contacts WHERE workspace_id=? AND id=?", (workspace_id, contact_id)).fetchone()
            if not contact:
                return None
            requests = [dict(row) for row in db.execute("SELECT * FROM scheduling_requests WHERE workspace_id=? AND contact_id=?", (workspace_id, contact_id)).fetchall()]
            messages = [dict(row) for row in db.execute("SELECT * FROM inbound_messages WHERE workspace_id=? AND sender=?", (workspace_id, contact["sender"])).fetchall()]
        for message in messages:
            message["body"] = self.crypto.decrypt(message.pop("body_ciphertext"))
        return {"contact": dict(contact), "messages": messages, "requests": requests, "exported_at": utc_now().isoformat()}

    def delete_contact(self, workspace_id: str, contact_id: int) -> bool:
        with self.connect() as db:
            contact = db.execute("SELECT sender FROM contacts WHERE workspace_id=? AND id=?", (workspace_id, contact_id)).fetchone()
            if not contact:
                return False
            request_ids = [row[0] for row in db.execute("SELECT id FROM scheduling_requests WHERE workspace_id=? AND contact_id=?", (workspace_id, contact_id))]
            if request_ids:
                placeholders = ",".join("?" for _ in request_ids)
                appointment_ids = [row[0] for row in db.execute(f"SELECT id FROM appointments WHERE request_id IN ({placeholders})", request_ids)]
                for appointment_id in appointment_ids:
                    db.execute("DELETE FROM background_jobs WHERE workspace_id=? AND payload_json LIKE ?", (workspace_id, f'%"appointment_id": {appointment_id}%'))
                db.execute(f"DELETE FROM appointments WHERE request_id IN ({placeholders})", request_ids)
                db.execute(f"DELETE FROM proposals WHERE request_id IN ({placeholders})", request_ids)
                db.execute(f"DELETE FROM scheduling_requests WHERE id IN ({placeholders})", request_ids)
            db.execute("DELETE FROM inbound_messages WHERE workspace_id=? AND sender=?", (workspace_id, contact["sender"]))
            db.execute("DELETE FROM contacts WHERE workspace_id=? AND id=?", (workspace_id, contact_id))
        self.audit(workspace_id, "operator", "privacy.contact_deleted", "contact", contact_id, {})
        return True

    def purge_expired(self, workspace_id: str, retention_days: int) -> int:
        cutoff = (utc_now() - timedelta(days=retention_days)).isoformat()
        with self.connect() as db:
            cursor = db.execute("DELETE FROM inbound_messages WHERE workspace_id=? AND received_at<?", (workspace_id, cutoff))
            db.execute("DELETE FROM rate_events WHERE workspace_id=? AND created_at<?", (workspace_id, cutoff))
        count = cursor.rowcount
        self.audit(workspace_id, "worker", "privacy.retention_purge", "workspace", workspace_id, {"messages_deleted": count, "cutoff": cutoff})
        return count

    @staticmethod
    def _request_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["slots"] = json.loads(data.pop("slots_json")) if data.get("slots_json") else []
        return data

    def _proposal(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["reply_text"] = self.crypto.decrypt(data.pop("reply_ciphertext"))
        data["booking_token"] = self.crypto.decrypt(data.pop("booking_token_ciphertext", None))
        data["slots"] = json.loads(data.pop("slots_json"))
        data.pop("booking_token_hash", None)
        return data

    @staticmethod
    def _audit_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["detail"] = json.loads(data.pop("detail_json"))
        return data
