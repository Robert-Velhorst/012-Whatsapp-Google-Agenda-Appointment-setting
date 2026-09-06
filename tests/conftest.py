from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from werkzeug.security import generate_password_hash

from scheduler.app import create_app


class FakeCalendar:
    def __init__(self):
        self.created = []
        self.cancelled = []

    def connected(self):
        return True

    def free_slots(self, start_day, duration, count=3):
        tz = ZoneInfo("Europe/Amsterdam")
        base = datetime.now(tz).replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=2)
        while base.weekday() >= 5:
            base += timedelta(days=1)
        return [base + timedelta(hours=index) for index in range(min(count, 3))]

    def create_event(self, appointment):
        self.created.append(dict(appointment))
        return {"id": f"event-{appointment['id']}", "htmlLink": f"https://calendar.google.com/event/{appointment['id']}"}

    def cancel_event(self, event_id):
        self.cancelled.append(event_id)


class FakeWhatsApp:
    def __init__(self):
        self.sent = []
        self.templates = []

    def configured(self):
        return True

    def send_reply(self, recipient, message, reply_to=None):
        self.sent.append((recipient, message, reply_to))
        return {"messages": [{"id": f"wamid.out.{len(self.sent)}"}]}

    def send_template(self, recipient, template_name, language, parameters):
        self.templates.append((recipient, template_name, language, parameters))
        return {"messages": [{"id": f"wamid.template.{len(self.templates)}"}]}


def signed(raw: bytes, secret: str = "test-app-secret") -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def webhook(message_id="wamid.1", sender="31612345678", body="Could we schedule a 30 minute call tomorrow?", name="Emma de Vries"):
    return {
        "entry": [{"changes": [{"value": {
            "contacts": [{"wa_id": sender, "profile": {"name": name}}],
            "messages": [{"id": message_id, "from": sender, "timestamp": "1786000000", "type": "text", "text": {"body": body}}],
        }}]}]
    }


def post_webhook(client, payload):
    raw = json.dumps(payload).encode()
    return client.post("/webhook/whatsapp", data=raw, headers={"Content-Type": "application/json", "X-Hub-Signature-256": signed(raw)})


@pytest.fixture
def app_bundle(tmp_path):
    calendar = FakeCalendar()
    whatsapp = FakeWhatsApp()
    settings = {
        "app_env": "test",
        "database_path": tmp_path / "scheduler.sqlite3",
        "flask_secret_key": "test-flask-secret",
        "admin_api_token": "test-admin-token",
        # A deliberately low-cost test hash keeps the suite fast; operators use the CLI's
        # default scrypt hash for real credentials.
        "admin_password_hash": generate_password_hash("correct horse battery staple", method="pbkdf2:sha256:1000"),
        "data_encryption_key": "test-encryption-key",
        "whatsapp_verify_token": "verify-me",
        "whatsapp_app_secret": "test-app-secret",
        "whatsapp_access_token": "test-token",
        "whatsapp_phone_number_id": "123",
        "public_base_url": "http://localhost",
        "timezone": "Europe/Amsterdam",
        "auto_send_suggestions": False,
        "auto_book_confirmed": False,
    }
    app = create_app(settings, calendar=calendar, whatsapp=whatsapp)
    app.config["TESTING"] = True
    yield app, calendar, whatsapp
    app.extensions["store"].close()


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-admin-token"}
