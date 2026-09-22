from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class CryptoBox:
    """Encrypts sensitive fields. Empty-key development mode is visibly reported by readiness."""

    def __init__(self, key: str):
        self.enabled = bool(key)
        if key:
            digest = hashlib.sha256(key.encode("utf-8")).digest()
            self._fernet = Fernet(base64.urlsafe_b64encode(digest))
        else:
            self._fernet = None

    def encrypt(self, value: str) -> str:
        if not value or not self._fernet:
            return "plain:" + value
        return "enc:" + self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str | None) -> str:
        if not value:
            return ""
        if value.startswith("plain:"):
            return value[6:]
        if value.startswith("enc:") and self._fernet:
            try:
                return self._fernet.decrypt(value[4:].encode("ascii")).decode("utf-8")
            except InvalidToken:
                return "[encrypted with a different key]"
        return value
