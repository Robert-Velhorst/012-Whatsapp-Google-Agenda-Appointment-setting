"""Build an owned SQLite runtime; never replace a shared interpreter/library."""
from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "3.54.1"
TARGET_PYTHON = (3, 15, 1)
ARTIFACTS = {
    "windows": ("https://www.sqlite.org/2026/sqlite-dll-win-x64-3540100.zip", "c2d09c8babb9399277055c057c97a53f1ffd7c5f11d0c1f2118ffdfa39f2daa4"),
    "linux": ("https://www.sqlite.org/2026/sqlite-amalgamation-3540100.zip", "92281c86e2957f9b9305890f9ac04204caa7b677cc868dc326d942689df28e30"),
}
PROBE = "import json,platform,sqlite3,sysconfig;print(json.dumps({'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'free_threaded_build':bool(sysconfig.get_config_var('Py_GIL_DISABLED'))}))"


def fetch_archive(kind: str) -> zipfile.ZipFile:
    url, digest = ARTIFACTS[kind]
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = response.read(12 * 1024 * 1024 + 1)
    if len(payload) > 12 * 1024 * 1024 or hashlib.sha3_256(payload).hexdigest() != digest:
        raise RuntimeError("Official SQLite archive failed its pinned SHA3-256 check")
    return zipfile.ZipFile(io.BytesIO(payload))


def artifact_member(archive: zipfile.ZipFile, name: str) -> bytes:
    candidates = [entry for entry in archive.infolist() if Path(entry.filename).name == name]
    if len(candidates) != 1 or candidates[0].file_size > 24 * 1024 * 1024:
        raise RuntimeError("Unexpected SQLite archive member")
    return archive.read(candidates[0])


def probe_runtime(executable: Path, library_dir: Path | None = None) -> dict:
    environment = os.environ.copy()
    if library_dir:
        environment["LD_LIBRARY_PATH"] = str(library_dir) + (":" + environment["LD_LIBRARY_PATH"] if environment.get("LD_LIBRARY_PATH") else "")
    result = json.loads(subprocess.check_output([str(executable), "-I", "-c", PROBE], text=True, env=environment, timeout=30))
    if result["python"] != "3.15.1" or result["sqlite"] != VERSION:
        raise RuntimeError("Prepared runtime does not contain the required Python/SQLite versions")
    return result


def prepare_windows(destination: Path) -> dict:
    base = Path(sys.base_prefix).resolve()
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("This pinned Windows SQLite artifact supports x64 only")
    # Copy only the interpreter and its standard library; do not copy user packages/configuration.
    for source in base.iterdir():
        if source.is_file() and source.suffix.lower() in {".exe", ".dll", ".zip"}:
            shutil.copy2(source, destination / source.name)
    ignore = shutil.ignore_patterns("site-packages", "__pycache__", "test", "tests", "idlelib", "tkinter", "turtledemo", "sitecustomize.py", "usercustomize.py")
    shutil.copytree(base / "Lib", destination / "Lib", ignore=ignore)
    shutil.copytree(base / "DLLs", destination / "DLLs")
    with fetch_archive("windows") as archive:
        replacement = artifact_member(archive, "sqlite3.dll")
    (destination / "DLLs" / "sqlite3.dll").write_bytes(replacement)
    executable = destination / Path(sys.executable).name
    result = probe_runtime(executable)
    if result["free_threaded_build"] != bool(__import__("sysconfig").get_config_var("Py_GIL_DISABLED")):
        raise RuntimeError("Interpreter copy changed the free-threaded build identity")
    return {**result, "executable": str(executable), "library_directory": str(destination / "DLLs"), "sqlite_dll_sha256": hashlib.sha256(replacement).hexdigest()}


def prepare_linux(destination: Path) -> dict:
    compiler = shutil.which("cc")
    if not compiler:
        raise RuntimeError("A C compiler is required to build the pinned SQLite source")
    with fetch_archive("linux") as archive:
        for name in ("sqlite3.c", "sqlite3.h"):
            (destination / name).write_bytes(artifact_member(archive, name))
    library = destination / "libsqlite3.so.0"
    subprocess.run([compiler, "-O2", "-fPIC", "-shared", "-DSQLITE_THREADSAFE=1", "-DSQLITE_ENABLE_FTS3", "-DSQLITE_ENABLE_FTS4", "-DSQLITE_ENABLE_FTS5", "-DSQLITE_ENABLE_RTREE", "-DSQLITE_ENABLE_COLUMN_METADATA", "-DSQLITE_ENABLE_MATH_FUNCTIONS", "-Wl,-soname,libsqlite3.so.0", str(destination / "sqlite3.c"), "-o", str(library), "-lm", "-ldl", "-lpthread"], check=True, timeout=300)
    result = probe_runtime(Path(sys.executable), destination)
    return {**result, "executable": sys.executable, "library_directory": str(destination), "library_sha256": hashlib.sha256(library.read_bytes()).hexdigest()}


def main() -> None:
    if len(sys.argv) != 1 or sys.version_info[:3] != TARGET_PYTHON or sys.implementation.name != "cpython":
        raise SystemExit("Run this fixed-workspace preparer with Python 3.15.1 and no arguments")
    kind = "windows" if sys.platform == "win32" else "linux" if sys.platform.startswith("linux") else None
    if kind is None:
        raise SystemExit("This runtime preparation supports Windows x64 and Linux")
    staging_root = ROOT / ".runtime"
    staging_root.mkdir(exist_ok=True)
    destination = staging_root / (kind + "-" + uuid.uuid4().hex)
    destination.mkdir()
    result = prepare_windows(destination) if kind == "windows" else prepare_linux(destination)
    result.update({"platform": kind, "source_url": ARTIFACTS[kind][0], "source_sha3_256": ARTIFACTS[kind][1], "shared_runtime_modified": False, "original_executable": sys.executable})
    (staging_root / "sqlite-runtime.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
