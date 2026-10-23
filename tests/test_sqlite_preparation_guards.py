import io
import zipfile

import pytest

from tools.prepare_sqlite_runtime import artifact_member, fetch_archive


def test_download_requires_the_published_archive_hash(monkeypatch):
    monkeypatch.setattr("tools.prepare_sqlite_runtime.urllib.request.urlopen", lambda *_a, **_kw: io.BytesIO(b"not the official archive"))
    with pytest.raises(RuntimeError, match="SHA3-256"):
        fetch_archive("windows")


def test_duplicate_archive_members_are_rejected():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("sqlite3.dll", b"first")
        archive.writestr("another/sqlite3.dll", b"second")
    payload.seek(0)
    with zipfile.ZipFile(payload) as archive, pytest.raises(RuntimeError, match="archive member"):
        artifact_member(archive, "sqlite3.dll")
