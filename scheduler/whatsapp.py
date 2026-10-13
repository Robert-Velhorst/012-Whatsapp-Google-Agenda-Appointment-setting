from __future__ import annotations

import hashlib
import hmac

import requests

from .config import Settings


class WhatsAppUnavailable(RuntimeError):
    def __init__(self, message: str, *, retry_safe: bool = False):
        super().__init__(message)
        self.retry_safe = retry_safe


def signature_is_valid(raw_body: bytes, signature: str | None, app_secret: str) -> bool:
    if not app_secret or not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class WhatsAppClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def configured(self) -> bool:
        return bool(self.settings.whatsapp_access_token and self.settings.whatsapp_phone_number_id)

    def send_reply(self, recipient: str, message: str, reply_to: str | None = None) -> dict:
        payload = {
            "messaging_product": "whatsapp", "recipient_type": "individual", "to": recipient,
            "type": "text", "text": {"preview_url": False, "body": message},
        }
        if reply_to:
            payload["context"] = {"message_id": reply_to}
        return self._post(payload)

    def send_template(self, recipient: str, template_name: str, language: str, parameters: list[str]) -> dict:
        payload = {
            "messaging_product": "whatsapp", "to": recipient, "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": "nl" if language == "nl" else "en_US"},
                "components": [{"type": "body", "parameters": [{"type": "text", "text": value} for value in parameters]}],
            },
        }
        return self._post(payload)

    def _post(self, payload: dict) -> dict:
        if not self.configured():
            raise WhatsAppUnavailable("WhatsApp Cloud API credentials are not configured.", retry_safe=True)
        try:
            response = requests.post(
                f"https://graph.facebook.com/{self.settings.whatsapp_graph_api_version}/{self.settings.whatsapp_phone_number_id}/messages",
                headers={"Authorization": f"Bearer {self.settings.whatsapp_access_token}"},
                json=payload,
                timeout=(5, 20),
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise WhatsAppUnavailable(
                "WhatsApp delivery is ambiguous after a network failure; verify the provider before any manual resend.",
                retry_safe=False,
            ) from exc
        except requests.RequestException as exc:
            raise WhatsAppUnavailable(f"WhatsApp request failed before a verified response: {exc}", retry_safe=False) from exc
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            status = response.status_code
            raise WhatsAppUnavailable(
                f"WhatsApp rejected the request with HTTP {status}.",
                retry_safe=400 <= status < 500,
            ) from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise WhatsAppUnavailable(
                "WhatsApp returned an unreadable success response; verify delivery before any manual resend.",
                retry_safe=False,
            ) from exc
        if not data.get("messages"):
            raise WhatsAppUnavailable(
                "WhatsApp returned no message identifier; verify delivery before any manual resend.",
                retry_safe=False,
            )
        return data
