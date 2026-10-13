"""Local first-run setup, shared by the source CLI and Windows executable."""
from __future__ import annotations

import getpass
import os
import secrets
from pathlib import Path

from werkzeug.security import generate_password_hash


def initialize(directory: Path, password: str) -> Path:
    destination = directory / ".env"
    if destination.exists():
        raise FileExistsError("An .env already exists. Keep its encryption key and edit that file to finish setup.")
    if len(password) < 12:
        raise ValueError("The operator password must contain at least 12 characters.")
    template = (directory / ".env.example").read_text(encoding="utf-8-sig")
    values = {name: secrets.token_urlsafe(48) for name in (
        "FLASK_SECRET_KEY", "ADMIN_API_TOKEN", "DATA_ENCRYPTION_KEY", "WHATSAPP_VERIFY_TOKEN",
    )}
    values.update(ADMIN_PASSWORD_HASH=generate_password_hash(password), APP_ENV="development",
                  AUTO_SEND_SUGGESTIONS="false", AUTO_BOOK_CONFIRMED="false")
    content = "\n".join(
        f"{line.split('=', 1)[0]}={values[line.split('=', 1)[0]]}"
        if line.split('=', 1)[0] in values else line
        for line in template.splitlines()
    ) + "\n"
    # Exclusive creation prevents replacing an existing instance's encryption key.
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(content)
    return destination


def interactive_setup(directory: Path | None = None) -> int:
    directory = directory or Path.cwd()
    if (directory / ".env").exists():
        print("Setup stopped: .env already exists. Edit it to finish provider setup; preserve its security keys.")
        return 1
    try:
        password = getpass.getpass("Choose an operator password (12+ characters): ")
        repeated = getpass.getpass("Repeat the password: ")
        if password != repeated:
            raise ValueError("Passwords did not match; no configuration was written.")
        initialize(directory, password)
    except (OSError, ValueError, EOFError) as exc:
        print(f"Setup could not finish: {exc}")
        return 1
    print("Local login and encryption are configured. Add your Meta and Google settings in .env, then start Agenda Relay.")
    print("The app starts in development mode. Complete provider setup before enabling public access.")
    return 0
