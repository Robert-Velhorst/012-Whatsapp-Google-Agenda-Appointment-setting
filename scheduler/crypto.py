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

    def decrypt_strict(self, value: str | None) -> str:
        """Decrypt a stored value or fail instead of disguising key/data corruption."""
        if not value:
            return ""
        if value.startswith("plain:"):
            return value[6:]
        if not value.startswith("enc:") or not self._fernet:
            raise ValueError("Stored value is not encrypted with a usable key")
        try:
            return self._fernet.decrypt(value[4:].encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
            raise ValueError("Stored value cannot be decrypted with the supplied key") from exc
