from __future__ import annotations

import pytest

from scheduler.crypto import CryptoBox


CORRUPTION_MARKER = "[encrypted with a different key]"


def test_decrypt_handles_non_ascii_ciphertext_without_raising():
    box = CryptoBox("test-encryption-key")

    assert box.decrypt("enc:☃") == CORRUPTION_MARKER


def test_decrypt_handles_authenticated_non_utf8_plaintext_without_raising():
    box = CryptoBox("test-encryption-key")
    token = box._fernet.encrypt(b"\xff").decode("ascii")

    assert box.decrypt(f"enc:{token}") == CORRUPTION_MARKER


def test_decrypt_handles_invalid_fernet_token_without_raising():
    box = CryptoBox("test-encryption-key")

    assert box.decrypt("enc:not-a-valid-token") == CORRUPTION_MARKER


def test_decrypt_strict_rejects_non_ascii_ciphertext():
    box = CryptoBox("test-encryption-key")

    with pytest.raises(ValueError, match="cannot be decrypted"):
        box.decrypt_strict("enc:☃")
