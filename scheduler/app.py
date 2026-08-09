from __future__ import annotations

import csv
import io
import json
import ipaddress
import os
import secrets
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from .calendar import GoogleCalendar
from .config import Settings
from .crypto import CryptoBox
from .service import SchedulingService
from .store import Store
from .whatsapp import WhatsAppClient, signature_is_valid


def create_app(overrides: dict | None = None, calendar=None, whatsapp=None, intent_provider=None) -> Flask:
    settings = Settings.from_env(overrides)
    errors, _ = settings.validation()
    if settings.is_production and errors:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(
        SECRET_KEY=settings.flask_secret_key,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.is_production,
        PERMANENT_SESSION_LIFETIME=3600,
        MAX_CONTENT_LENGTH=1_000_000,
    )
    crypto = CryptoBox(settings.data_encryption_key)
    store = Store(settings.database_path, crypto)
    store.ensure_workspace(settings.workspace_id, settings.workspace_name, settings.timezone)
    calendar = calendar or GoogleCalendar(settings, crypto)
    whatsapp = whatsapp or WhatsAppClient(settings)
    scheduling = SchedulingService(settings, store, calendar, whatsapp, intent_provider)
    app.extensions.update(settings=settings, store=store, scheduling=scheduling, calendar=calendar, whatsapp=whatsapp)

    def csrf_token() -> str:
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    def valid_csrf() -> bool:
        supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        expected = session.get("csrf_token")
        return bool(supplied and expected and secrets.compare_digest(supplied, expected))

    def safe_next_url(candidate: str | None) -> str:
        if candidate and candidate.startswith("/") and not candidate.startswith("//"):
            return candidate
        if candidate:
            parsed = urlsplit(candidate)
            if parsed.scheme in {"http", "https"} and parsed.netloc == request.host:
                return parsed.path + (f"?{parsed.query}" if parsed.query else "")
        return url_for("dashboard")

    def booking_slots(proposal: dict | None) -> list[dict[str, str | int]]:
        if not proposal or not proposal.get("slots"):
            return []
        timezone_name = proposal.get("contact_timezone") or settings.timezone
        target = ZoneInfo(timezone_name)
        return [
            {"index": index, "date": datetime.fromisoformat(value).astimezone(target).strftime("%Y-%m-%d"), "time": datetime.fromisoformat(value).astimezone(target).strftime("%H:%M")}
            for index, value in enumerate(proposal["slots"])
        ]

    def is_api_authorized() -> bool:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        return bool(token and secrets.compare_digest(token, settings.admin_api_token))

    def hai_client_allowed() -> bool:
        try:
            remote = ipaddress.ip_address(request.remote_addr or "")
            candidate = remote
            forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
            if remote.is_loopback and forwarded:
                candidate = ipaddress.ip_address(forwarded)
            networks = [ipaddress.ip_network(value.strip(), strict=False) for value in settings.hai_allowed_networks.split(",") if value.strip()]
            return any(candidate in network for network in networks)
        except ValueError:
            return False

    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if is_api_authorized():
                return view(*args, **kwargs)
            if not session.get("operator_authenticated"):
                return _error("authentication_required", "Operator authentication is required", 401)
            if request.method not in {"GET", "HEAD", "OPTIONS"} and not valid_csrf():
                return _error("invalid_csrf", "The form or API CSRF token is invalid", 403)
            return view(*args, **kwargs)
        return wrapped

    def operator_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("operator_authenticated"):
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)
        return wrapped

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        response.headers["Cache-Control"] = "public, max-age=86400, immutable" if request.endpoint == "static" else "no-store"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.get("/login")
    def login():
        return render_template("login.html", login_enabled=bool(settings.admin_password_hash), mode=settings.app_env)

    @app.post("/login")
    def login_post():
        if not valid_csrf():
            abort(403)
        login_subject = request.remote_addr or "unknown"
        if not store.rate_allowed(settings.workspace_id, login_subject, "auth.login_failed", 5, 15):
            store.audit(settings.workspace_id, "anonymous", "auth.login_throttled", "operator", None, {"remote": login_subject})
            return render_template("login.html", login_enabled=bool(settings.admin_password_hash), mode=settings.app_env, error="Too many failed sign-in attempts. Try again in 15 minutes."), 429
        if not settings.admin_password_hash:
            flash("Browser login is disabled. Configure ADMIN_PASSWORD_HASH first.", "error")
            return redirect(url_for("login"))
        password = request.form.get("password", "")
        if not check_password_hash(settings.admin_password_hash, password):
            if not store.reserve_rate_event(settings.workspace_id, login_subject, "auth.login_failed", 5, 15):
                return render_template("login.html", login_enabled=bool(settings.admin_password_hash), mode=settings.app_env, error="Too many failed sign-in attempts. Try again in 15 minutes."), 429
            store.audit(settings.workspace_id, "anonymous", "auth.login_failed", "operator", None, {"remote": request.remote_addr})
            flash("The password is incorrect.", "error")
            return redirect(url_for("login"))
        session.clear()
        session["operator_authenticated"] = True
        session["csrf_token"] = secrets.token_urlsafe(32)
        session.permanent = True
        store.audit(settings.workspace_id, settings.operator_name, "auth.login", "operator")
        return redirect(safe_next_url(request.args.get("next")))

    @app.post("/logout")
    @operator_required
    def logout():
        if not valid_csrf():
            abort(403)
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    @operator_required
    def dashboard():
        view = request.args.get("view", "overview")
        query = request.args.get("q", "").strip()[:100]
        status = request.args.get("status", "").strip()[:40]
        page = request.args.get("page", 1, type=int)
        data = store.dashboard(settings.workspace_id, query, status, page)
        selected_id = request.args.get("request", type=int)
        selected = store.request_detail(settings.workspace_id, selected_id) if selected_id else (store.request_detail(settings.workspace_id, data["items"][0]["id"]) if data["items"] else None)
        return render_template(
            "dashboard.html", view=view, data=data, selected=selected, readiness=scheduling.readiness(),
            contacts=store.contacts(settings.workspace_id, query) if view == "contacts" else [],
            audit=store.recent_audit(settings.workspace_id, 200) if view == "audit" else [],
            mode=settings.app_env, workspace_name=settings.workspace_name, operator_name=settings.operator_name,
            timezone_name=settings.timezone, query=query, status=status,
        )

    @app.post("/actions/automation/toggle")
    @operator_required
    def toggle_automation():
        if not valid_csrf():
            abort(403)
        value = "false" if scheduling.is_paused() else "true"
        store.set_state(settings.workspace_id, "automation_paused", value, settings.operator_name)
        flash("Automation resumed." if value == "false" else "Automation paused. Incoming messages will still be recorded.", "success")
        return redirect(safe_next_url(request.referrer))

    @app.post("/actions/proposals/<int:proposal_id>/send")
    @operator_required
    def action_send_proposal(proposal_id: int):
        if not valid_csrf():
            abort(403)
        try:
            scheduling.send_proposal(proposal_id, settings.operator_name)
            flash("The proposal was sent through WhatsApp Cloud API.", "success")
        except Exception as exc:
            flash(f"Proposal not sent: {exc}", "error")
        return redirect(safe_next_url(request.referrer))

    @app.post("/actions/appointments/<int:appointment_id>/book")
    @operator_required
    def action_book(appointment_id: int):
        if not valid_csrf():
            abort(403)
        try:
            result = scheduling.book_appointment(appointment_id, settings.operator_name)
            flash(result.get("warning") or "The confirmed slot was booked in Google Calendar.", "success")
        except Exception as exc:
            flash(f"Calendar booking failed safely: {exc}", "error")
        return redirect(safe_next_url(request.referrer))

    @app.post("/actions/appointments/<int:appointment_id>/cancel")
    @operator_required
    def action_cancel(appointment_id: int):
        if not valid_csrf():
            abort(403)
        try:
            scheduling.cancel_appointment(appointment_id, settings.operator_name)
            flash("The appointment was cancelled and queued reminders were stopped.", "success")
        except Exception as exc:
            flash(f"Cancellation failed safely: {exc}", "error")
        return redirect(safe_next_url(request.referrer))

    @app.post("/actions/contacts/<int:contact_id>/update")
    @operator_required
    def action_contact_update(contact_id: int):
        if not valid_csrf():
            abort(403)
        try:
            store.update_contact(
                settings.workspace_id, contact_id,
                display_name=request.form.get("display_name", "").strip()[:120] or None,
                email=request.form.get("email", "").strip()[:254] or None,
                timezone_name=request.form.get("timezone", settings.timezone).strip()[:80],
                language=request.form.get("language", "en"),
                consent_status=request.form.get("consent_status", "implicit_inbound"),
            )
            flash("Contact settings saved.", "success")
        except Exception as exc:
            flash(f"Contact not updated: {exc}", "error")
        return redirect(url_for("dashboard", view="contacts"))

    @app.get("/book/<token>")
    def booking_page(token: str):
        try:
            proposal = scheduling.public_proposal(token)
        except KeyError:
            abort(404)
        except ValueError as exc:
            return render_template("booking.html", proposal={"status": "expired"}, token=token, timezone_name=settings.timezone, display_slots=[], error=str(exc)), 410
        timezone_name = proposal.get("contact_timezone") or settings.timezone
        return render_template("booking.html", proposal=proposal, token=token, timezone_name=timezone_name, display_slots=booking_slots(proposal))

    @app.post("/book/<token>")
    def booking_confirm(token: str):
        if not valid_csrf():
            abort(403)
        try:
            slot_index = int(request.form.get("slot", "-1"))
            appointment_id = scheduling.confirm_public(token, slot_index, request.form.get("consent") == "yes")
            return render_template("booking_complete.html", appointment_id=appointment_id)
        except KeyError:
            abort(404)
        except Exception as exc:
            proposal = store.get_proposal_by_token(token)
            timezone_name = (proposal or {}).get("contact_timezone") or settings.timezone
            return render_template("booking.html", proposal=proposal, token=token, timezone_name=timezone_name, display_slots=booking_slots(proposal), error=str(exc)), 400

    @app.get("/webhook/whatsapp")
    def verify_webhook():
        if not settings.whatsapp_verify_token or request.args.get("hub.verify_token") != settings.whatsapp_verify_token:
            abort(403)
        return request.args.get("hub.challenge", "")

    @app.post("/webhook/whatsapp")
    def receive_webhook():
        raw_body = request.get_data()
        if not signature_is_valid(raw_body, request.headers.get("X-Hub-Signature-256"), settings.whatsapp_app_secret):
            abort(403)
        payload = request.get_json(silent=True) or {}
        result = scheduling.process_payload(payload)
        return jsonify(result), 200

    @app.get("/api/health")
    def health():
        return {"ok": True, "service": "agenda-relay", "version": "1.0.0", "mode": settings.app_env}

    @app.get("/api/readiness")
    def readiness():
        data = scheduling.readiness()
        return jsonify({"ready": data["ready"], "mode": data["mode"], "automation_paused": data["automation_paused"]}), 200 if data["ready"] else 503

    @app.get("/api/operator/readiness")
    @admin_required
    def operator_readiness():
        return jsonify(scheduling.readiness())

    @app.get("/api/integrations/hai/feed")
    def hai_feed():
        if not settings.hai_connector_enabled:
            abort(404)
        if not hai_client_allowed():
            return _error("connector_network_denied", "HAI connector access is not allowed from this network", 403)
        subject = request.remote_addr or "unknown"
        if not store.reserve_rate_event(settings.workspace_id, subject, "hai.feed", 60, 1):
            return _error("connector_rate_limited", "HAI feed rate limit reached", 429)
        try:
            rows, next_cursor = store.hai_feed(settings.workspace_id, request.args.get("cursor", "")[:500], settings.hai_feed_page_size)
        except ValueError as exc:
            return _error("invalid_cursor", str(exc), 400)
        items = []
        for row in rows:
            metadata = {
                "schemaVersion": "1.0",
                "requestId": row["id"],
                "status": row["status"],
                "proposalStatus": row.get("proposal_status"),
                "appointmentStatus": row.get("appointment_status"),
                "durationMinutes": row["duration_minutes"],
                "timezone": row["timezone"],
                "requestedStart": row.get("requested_start"),
                "appointmentStart": row.get("start_at"),
                "appointmentEnd": row.get("end_at"),
                "confidence": row["confidence"],
                "updatedAt": row["updated_at"],
                "authority": "advisory_read_only",
            }
            items.append({
                "externalId": f"agenda-relay-request-{row['id']}",
                "title": f"Scheduling request {row['id']}",
                "content": f"Scheduling request is {row['status']}; duration {row['duration_minutes']} minutes in {row['timezone']}.",
                "sourceUri": f"agenda-relay://request/{row['id']}",
                "itemType": "scheduling_request",
                "projectKey": settings.hai_project_key,
                "metadata": json.dumps(metadata, sort_keys=True, separators=(",", ":")),
            })
        return jsonify({"items": items, "nextCursor": next_cursor})

    @app.get("/api/google/connect")
    @admin_required
    def google_connect():
        if not settings.google_client_secrets_file or not os.path.exists(settings.google_client_secrets_file):
            return _error("google_credentials_missing", "GOOGLE_CLIENT_SECRETS_FILE is not configured or does not exist", 400)
        state = secrets.token_urlsafe(32)
        session["google_oauth_state"] = state
        redirect_uri = settings.public_base_url + "/api/google/callback"
        return redirect(calendar.authorization_url(redirect_uri, state))

    @app.get("/api/google/callback")
    def google_callback():
        if request.args.get("state") != session.pop("google_oauth_state", None):
            return _error("invalid_oauth_state", "Invalid Google OAuth state", 400)
        calendar.exchange_code(request.url, settings.public_base_url + "/api/google/callback")
        store.audit(settings.workspace_id, settings.operator_name, "provider.google_connected", "provider", "google_calendar")
        return redirect(url_for("dashboard"))

    @app.get("/api/requests")
    @admin_required
    def api_requests():
        data = store.dashboard(settings.workspace_id, request.args.get("q", "")[:100], request.args.get("status", "")[:40], request.args.get("page", 1, type=int), request.args.get("per_page", 25, type=int))
        return jsonify(data)

    @app.get("/api/requests/<int:request_id>")
    @admin_required
    def api_request_detail(request_id: int):
        data = store.request_detail(settings.workspace_id, request_id)
        return jsonify(data) if data else _error("not_found", "Scheduling request not found", 404)

    @app.post("/api/proposals/<int:proposal_id>/send")
    @admin_required
    def api_send_proposal(proposal_id: int):
        try:
            return jsonify(scheduling.send_proposal(proposal_id, settings.operator_name))
        except (KeyError, ValueError) as exc:
            return _error("proposal_not_sendable", str(exc), 409)

    @app.post("/api/appointments/<int:appointment_id>/book")
    @admin_required
    def api_book(appointment_id: int):
        try:
            return jsonify(scheduling.book_appointment(appointment_id, settings.operator_name))
        except (KeyError, ValueError) as exc:
            return _error("appointment_not_bookable", str(exc), 409)

    @app.post("/api/appointments/<int:appointment_id>/cancel")
    @admin_required
    def api_cancel(appointment_id: int):
        try:
            return jsonify(scheduling.cancel_appointment(appointment_id, settings.operator_name))
        except KeyError as exc:
            return _error("not_found", str(exc), 404)

    @app.get("/api/audit")
    @admin_required
    def api_audit():
        return jsonify(store.recent_audit(settings.workspace_id, request.args.get("limit", 100, type=int)))

    @app.get("/api/contacts/<int:contact_id>/export")
    @admin_required
    def api_contact_export(contact_id: int):
        data = store.export_contact(settings.workspace_id, contact_id)
        return jsonify(data) if data else _error("not_found", "Contact not found", 404)

    @app.delete("/api/contacts/<int:contact_id>")
    @admin_required
    def api_contact_delete(contact_id: int):
        return jsonify({"deleted": store.delete_contact(settings.workspace_id, contact_id)})

    @app.get("/api/export/requests.csv")
    @admin_required
    def api_requests_csv():
        items = store.export_requests(settings.workspace_id)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "contact", "title", "status", "confidence", "created_at"])
        for item in items:
            writer.writerow([item["id"], _csv_safe(item.get("display_name") or item["sender"]), _csv_safe(item["title"]), item["status"], item["confidence"], item["created_at"]])
        return app.response_class(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=scheduling-requests.csv"})

    return app


def _error(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message, "retryable": status >= 500 or status == 429}}), status


def _csv_safe(value: object) -> object:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value
