from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .crypto import CryptoBox
from .database_validation import validate_app_database

_ENCRYPTED_COLUMNS = (
    ("inbound_messages", "body_ciphertext"),
    ("proposals", "reply_ciphertext"),
    ("proposals", "booking_token_ciphertext"),
)


def _validate_database(connection: sqlite3.Connection) -> None:
    if not validate_app_database(connection):
        raise ValueError("Database failed integrity or application schema validation")


def _reencrypt(value: str | None, old_box: CryptoBox, new_box: CryptoBox) -> str | None:
    if value is None:
        return None
    if value.startswith("enc:") or value.startswith("plain:"):
        plaintext = old_box.decrypt_strict(value)
    else:
        raise ValueError("Database contains an unrecognized encrypted-field format")
    return new_box.encrypt(plaintext)


def _token_plaintext(token_path: Path, old_box: CryptoBox) -> str:
    raw = token_path.read_text(encoding="utf-8")
    if raw.startswith(("enc:", "plain:")):
        plaintext = old_box.decrypt_strict(raw)
    else:
        # Early local builds stored the authorized-user JSON without an envelope.
        plaintext = raw
    try:
        token_data: Any = json.loads(plaintext)
    except json.JSONDecodeError as exc:
        raise ValueError("Google token file is not valid JSON") from exc
    if not isinstance(token_data, dict):
        raise ValueError("Google token file must contain a JSON object")
    return plaintext


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rotate_encryption_bundle(
    database_path: Path,
    token_path: Path,
    output_directory: Path,
    old_key: str,
    new_key: str,
) -> dict[str, Any]:
    """Create and validate a non-overwriting replacement bundle; inputs stay untouched."""
    source_database = database_path.resolve()
    source_token = token_path.resolve()
    output = output_directory.resolve()
    if not old_key:
        raise ValueError("DATA_ENCRYPTION_KEY must contain the current key")
    if old_key == new_key:
        raise ValueError("The new encryption key must differ from the current key")
    if len(new_key) < 64:
        raise ValueError("NEW_DATA_ENCRYPTION_KEY must be at least 64 characters")
    if not source_database.is_file():
        raise ValueError("Database file does not exist")
    if output == source_database or output == source_token:
        raise ValueError("Output directory must differ from the source files")
    if output.exists():
        raise FileExistsError("Output directory already exists; choose a new path")

    output.parent.mkdir(parents=True, exist_ok=True)
    old_box = CryptoBox(old_key)
    new_box = CryptoBox(new_key)
    token_plain = _token_plaintext(source_token, old_box) if source_token.is_file() else None
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.rotation-", dir=output.parent))
    try:
        database_output = staging / "scheduler.sqlite3"
        with closing(sqlite3.connect(source_database, timeout=5)) as source, closing(
            sqlite3.connect(database_output, timeout=5)
        ) as destination:
            source.backup(destination)
            destination.execute("PRAGMA foreign_keys=ON")
            _validate_database(destination)
            rotated = 0
            destination.execute("BEGIN IMMEDIATE")
            try:
                for table, column in _ENCRYPTED_COLUMNS:
                    last_id = 0
                    while rows := destination.execute(
                        f"SELECT id, {column} FROM {table} WHERE id>? AND {column} IS NOT NULL ORDER BY id LIMIT 256",
                        (last_id,),
                    ).fetchall():
                        for row_id, encrypted_value in rows:
                            replacement = _reencrypt(encrypted_value, old_box, new_box)
                            destination.execute(
                                f"UPDATE {table} SET {column}=? WHERE id=?",
                                (replacement, row_id),
                            )
                            rotated += 1
                        last_id = int(rows[-1][0])
                destination.commit()
            except Exception:
                destination.rollback()
                raise
            _validate_database(destination)
            for table, column in _ENCRYPTED_COLUMNS:
                cursor = destination.execute(
                    f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL"
                )
                while rows := cursor.fetchmany(256):
                    for (encrypted_value,) in rows:
                        if not encrypted_value.startswith(("enc:", "plain:")):
                            raise ValueError("Rotated database contains an invalid encrypted-field format")
                        new_box.decrypt_strict(encrypted_value)

        if token_plain is not None:
            token_output = staging / "google-token.json"
            token_output.write_text(new_box.encrypt(token_plain), encoding="utf-8")
            try:
                token_output.chmod(0o600)
            except OSError:
                pass
            if new_box.decrypt_strict(token_output.read_text(encoding="utf-8")) != token_plain:
                raise ValueError("Rotated Google token failed verification")

        database_digest = _sha256_file(database_output)
        manifest = {
            "format": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "database_file": "scheduler.sqlite3",
            "database_sha256": database_digest,
            "google_token_file": "google-token.json" if token_plain is not None else None,
            "encrypted_database_values_rotated": rotated,
            "source_files_unchanged": True,
        }
        (staging / "rotation.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        # Directory rename is atomic on one volume and refuses an output created
        # after our initial existence check; unlike os.replace it never overwrites.
        os.rename(staging, output)
        return {**manifest, "output_directory": str(output)}
    except Exception:
        if staging.exists():
            for path in staging.iterdir():
                path.unlink(missing_ok=True)
            staging.rmdir()
        raise
