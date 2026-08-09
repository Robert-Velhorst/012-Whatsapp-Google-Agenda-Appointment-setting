from __future__ import annotations

import os
import ipaddress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str
    public_base_url: str
    workspace_id: str
    workspace_name: str
    operator_name: str
    database_path: Path
    flask_secret_key: str
    admin_api_token: str
    admin_password_hash: str
    data_encryption_key: str
    whatsapp_verify_token: str
    whatsapp_app_secret: str
    whatsapp_access_token: str
    whatsapp_phone_number_id: str
    whatsapp_graph_api_version: str
    whatsapp_reminder_template: str
    google_client_secrets_file: str
    google_token_file: str
    google_calendar_id: str
    timezone: str
    auto_send_suggestions: bool
    auto_book_confirmed: bool
    automation_paused: bool
    business_hours_start: int
    business_hours_end: int
    slot_interval_minutes: int
    default_duration_minutes: int
    reminder_minutes_before: int
    data_retention_days: int
    booking_link_ttl_hours: int
    max_outbound_per_contact_per_hour: int
    hai_connector_enabled: bool
    hai_allowed_networks: str
    hai_feed_page_size: int
    hai_project_key: str

    @classmethod
    def from_env(cls, overrides: dict | None = None) -> "Settings":
        values = {
            "app_env": os.getenv("APP_ENV", "development").lower(),
            "public_base_url": os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:5000").rstrip("/"),
            "workspace_id": os.getenv("WORKSPACE_ID", "default"),
            "workspace_name": os.getenv("WORKSPACE_NAME", "My scheduling desk"),
            "operator_name": os.getenv("OPERATOR_NAME", "Operator"),
            "database_path": Path(os.getenv("DATABASE_PATH", "./data/scheduler.sqlite3")),
            "flask_secret_key": os.getenv("FLASK_SECRET_KEY", "development-only-change-me"),
            "admin_api_token": os.getenv("ADMIN_API_TOKEN", "development-admin-token"),
            "admin_password_hash": os.getenv("ADMIN_PASSWORD_HASH", ""),
            "data_encryption_key": os.getenv("DATA_ENCRYPTION_KEY", ""),
            "whatsapp_verify_token": os.getenv("WHATSAPP_VERIFY_TOKEN", ""),
            "whatsapp_app_secret": os.getenv("WHATSAPP_APP_SECRET", ""),
            "whatsapp_access_token": os.getenv("WHATSAPP_ACCESS_TOKEN", ""),
            "whatsapp_phone_number_id": os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
            "whatsapp_graph_api_version": os.getenv("WHATSAPP_GRAPH_API_VERSION", "v23.0"),
            "whatsapp_reminder_template": os.getenv("WHATSAPP_REMINDER_TEMPLATE", ""),
            "google_client_secrets_file": os.getenv("GOOGLE_CLIENT_SECRETS_FILE", ""),
            "google_token_file": os.getenv("GOOGLE_TOKEN_FILE", "./data/google-token.json"),
            "google_calendar_id": os.getenv("GOOGLE_CALENDAR_ID", "primary"),
            "timezone": os.getenv("TIMEZONE", "Europe/Amsterdam"),
            "auto_send_suggestions": _bool("AUTO_SEND_SUGGESTIONS"),
            "auto_book_confirmed": _bool("AUTO_BOOK_CONFIRMED"),
            "automation_paused": _bool("AUTOMATION_PAUSED"),
            "business_hours_start": int(os.getenv("BUSINESS_HOURS_START", "9")),
            "business_hours_end": int(os.getenv("BUSINESS_HOURS_END", "17")),
            "slot_interval_minutes": int(os.getenv("SLOT_INTERVAL_MINUTES", "30")),
            "default_duration_minutes": int(os.getenv("DEFAULT_DURATION_MINUTES", "30")),
            "reminder_minutes_before": int(os.getenv("REMINDER_MINUTES_BEFORE", "1440")),
            "data_retention_days": int(os.getenv("DATA_RETENTION_DAYS", "30")),
            "booking_link_ttl_hours": int(os.getenv("BOOKING_LINK_TTL_HOURS", "168")),
            "max_outbound_per_contact_per_hour": int(os.getenv("MAX_OUTBOUND_PER_CONTACT_PER_HOUR", "10")),
            "hai_connector_enabled": _bool("HAI_CONNECTOR_ENABLED"),
            "hai_allowed_networks": os.getenv("HAI_ALLOWED_NETWORKS", "127.0.0.1/32,::1/128"),
            "hai_feed_page_size": int(os.getenv("HAI_FEED_PAGE_SIZE", "100")),
            "hai_project_key": os.getenv("HAI_PROJECT_KEY", "012-Whatsapp-Google-Agenda-Appointment-setting"),
        }
        if overrides:
            values.update(overrides)
        if isinstance(values["database_path"], str):
            values["database_path"] = Path(values["database_path"])
        return cls(**values)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_demo(self) -> bool:
        return self.app_env in {"development", "test"}

    def validation(self) -> tuple[list[str], list[str]]:
        errors: list[str] = []
        warnings: list[str] = []
        if self.app_env not in {"development", "test", "production"}:
            errors.append("APP_ENV must be development, test, or production")
        if not (0 <= self.business_hours_start < self.business_hours_end <= 24):
            errors.append("Business hours must be ordered values between 0 and 24")
        if self.slot_interval_minutes not in {5, 10, 15, 20, 30, 60}:
            errors.append("SLOT_INTERVAL_MINUTES must be one of 5, 10, 15, 20, 30, 60")
        if self.default_duration_minutes < 15 or self.default_duration_minutes > 480:
            errors.append("DEFAULT_DURATION_MINUTES must be between 15 and 480")
        if self.booking_link_ttl_hours < 1 or self.booking_link_ttl_hours > 720:
            errors.append("BOOKING_LINK_TTL_HOURS must be between 1 and 720")
        if self.hai_feed_page_size < 1 or self.hai_feed_page_size > 500:
            errors.append("HAI_FEED_PAGE_SIZE must be between 1 and 500")
        try:
            networks = [ipaddress.ip_network(value.strip(), strict=False) for value in self.hai_allowed_networks.split(",") if value.strip()]
            if self.hai_connector_enabled and not networks:
                errors.append("HAI_ALLOWED_NETWORKS must contain at least one CIDR when the connector is enabled")
        except ValueError:
            errors.append("HAI_ALLOWED_NETWORKS contains an invalid CIDR")
        parsed = urlparse(self.public_base_url)
        if not parsed.scheme or not parsed.netloc:
            errors.append("PUBLIC_BASE_URL must be an absolute URL")
        provider_missing = []
        for name, value in (
            ("WHATSAPP_VERIFY_TOKEN", self.whatsapp_verify_token),
            ("WHATSAPP_APP_SECRET", self.whatsapp_app_secret),
            ("WHATSAPP_ACCESS_TOKEN", self.whatsapp_access_token),
            ("WHATSAPP_PHONE_NUMBER_ID", self.whatsapp_phone_number_id),
            ("GOOGLE_CLIENT_SECRETS_FILE", self.google_client_secrets_file),
        ):
            if not value:
                provider_missing.append(name)
        if provider_missing:
            warnings.append("Provider configuration incomplete: " + ", ".join(provider_missing))
        if not self.admin_password_hash:
            warnings.append("Browser login is disabled until ADMIN_PASSWORD_HASH is configured")
        if not self.data_encryption_key:
            warnings.append("Sensitive message fields and Google tokens are not encrypted at rest")
        if self.auto_book_confirmed:
            warnings.append("AUTO_BOOK_CONFIRMED is enabled; confirmed slots can change Google Calendar automatically")
        if self.hai_connector_enabled:
            warnings.append("HAI metadata feed is enabled only for clients in HAI_ALLOWED_NETWORKS")
        if self.is_production:
            if parsed.scheme != "https":
                errors.append("Production PUBLIC_BASE_URL must use HTTPS")
            for name, value, rejected in (
                ("FLASK_SECRET_KEY", self.flask_secret_key, "development-only-change-me"),
                ("ADMIN_API_TOKEN", self.admin_api_token, "development-admin-token"),
            ):
                if not value or value == rejected or len(value) < 32:
                    errors.append(f"{name} must be a non-default value of at least 32 characters")
            if not self.admin_password_hash:
                errors.append("ADMIN_PASSWORD_HASH is required in production")
            if not self.data_encryption_key:
                errors.append("DATA_ENCRYPTION_KEY is required in production")
            if provider_missing:
                errors.append("All WhatsApp and Google provider settings are required in production")
            if self.google_client_secrets_file and not Path(self.google_client_secrets_file).is_file():
                errors.append("GOOGLE_CLIENT_SECRETS_FILE does not exist")
        return errors, warnings
