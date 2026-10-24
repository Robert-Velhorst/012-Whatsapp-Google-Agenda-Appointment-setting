"""Inspect installed code without starting the scheduler or opening its database."""

import ctypes
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import sqlite3
import ssl
import subprocess
from pathlib import Path


def main():
    if platform.python_version() != "3.15.1":
        raise RuntimeError("Expected the selected CPython security release")
    packages = sorted(
        [
            {"name": item.metadata["Name"], "version": item.version}
            for item in importlib.metadata.distributions()
        ],
        key=lambda item: item["name"].lower(),
    )
    native_modules = {}
    for name in ["_ssl", "_hashlib", "_sqlite3"]:
        module = __import__(name)
        file = Path(module.__file__)
        native_modules[name] = {
            "path": str(file),
            "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
        }
    profile = json.loads(
        (Path(__file__).resolve().parents[1] / "native-client-runtime.json").read_text(
            encoding="utf-8"
        )
    )
    if os.getuid() != 10001 or sqlite3.sqlite_version != profile["sqlite"]["version"]:
        raise RuntimeError("Expected the selected SQLite library and unprivileged user")
    expected_ssl = "OpenSSL " + profile["openssl"]["version"] + " "
    if not ssl.OPENSSL_VERSION.startswith(expected_ssl):
        raise RuntimeError("Python SSL differs from the selected upstream library")
    from cryptography.hazmat.bindings.openssl.binding import Binding

    binding = Binding()
    cryptography_ssl = binding.ffi.string(binding.lib.OpenSSL_version(0)).decode(
        "ascii"
    )
    if not cryptography_ssl.startswith(expected_ssl):
        raise RuntimeError("Cryptography must use the selected upstream library")
    tls = json.loads(
        Path("/usr/share/doc/agenda-python-tls/provenance.json").read_text(
            encoding="utf-8"
        )
    )
    if tls["source"] != profile["cpython"] or len(tls["modules"]) != 2:
        raise RuntimeError("Unexpected CPython module source or count")
    for name, info in tls["modules"].items():
        file = Path("/usr/local/lib/python3.15/lib-dynload") / name
        if hashlib.sha256(file.read_bytes()).hexdigest() != info["sha256"]:
            raise RuntimeError("CPython TLS module hash mismatch")
    native = json.loads(
        Path("/usr/share/agenda-native/openssl.json").read_text(encoding="utf-8")
    )
    for name, digest in native["libraries"].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
            raise RuntimeError("Native TLS library hash mismatch")
    crypto = ctypes.CDLL(str(Path(profile["prefix"]) / "lib/libcrypto.so.4"))
    crypto.OSSL_PROVIDER_load.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    crypto.OSSL_PROVIDER_load.restype = ctypes.c_void_p
    legacy_provider = crypto.OSSL_PROVIDER_load(None, b"legacy")
    if not legacy_provider:
        raise RuntimeError("The built OpenSSL legacy provider must remain loadable")
    loaded = {
        line.split()[-1]
        for line in Path("/proc/self/maps").read_text(encoding="utf-8").splitlines()
        if len(line.split()) >= 6 and ".so" in line.split()[-1]
    }
    for stem in ["libssl.so.4", "libcrypto.so.4"]:
        paths = {name for name in loaded if Path(name).name.startswith(stem)}
        if not paths or any(
            not name.startswith(profile["prefix"] + "/lib/") for name in paths
        ):
            raise RuntimeError("Loaded TLS library is outside the selected prefix")
    sqlite_provenance = json.loads(
        Path("/usr/share/agenda-native/sqlite.json").read_text(encoding="utf-8")
    )
    sqlite_paths = {
        name for name in loaded if Path(name).name.startswith("libsqlite3.so")
    }
    if len(sqlite_paths) != 1 or any(
        hashlib.sha256(Path(name).read_bytes()).hexdigest()
        != sqlite_provenance["library_sha256"]
        for name in sqlite_paths
    ):
        raise RuntimeError("Loaded SQLite library hash mismatch")
    ca_roots = len(ssl.create_default_context().get_ca_certs())
    if ca_roots < 1:
        raise RuntimeError("Native TLS must retain usable CA roots")
    wheels = json.loads(
        Path("/usr/share/doc/agenda-wheels/build-wheels.json").read_text(
            encoding="utf-8"
        )
    )
    normalize = lambda name: re.sub(r"[-_.]+", "-", name.lower())
    actual_packages = {normalize(item["name"]): item["version"] for item in packages}
    if actual_packages != {item["name"]: item["version"] for item in wheels}:
        raise RuntimeError(
            "Installed Python distributions differ from the locked wheel set"
        )
    toolchain = json.loads(
        Path("/usr/share/doc/agenda-wheels/build-toolchain.json").read_text(
            encoding="utf-8"
        )
    )
    for tool in ["rustc", "cargo"]:
        if toolchain[tool].split()[1] != profile["rust"]["version"]:
            raise RuntimeError(
                "Wheel toolchain differs from the selected stable Rust release"
            )
    installed_os = subprocess.check_output(
        ["apk", "list", "--installed"],
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    print(
        json.dumps(
            {
                "python": platform.python_version(),
                "sqlite": sqlite3.sqlite_version,
                "python_ssl": ssl.OPENSSL_VERSION,
                "ca_roots": ca_roots,
                "cryptography_ssl": cryptography_ssl,
                "legacy_provider_loadable": True,
                "python_tls_provenance": tls,
                "native_tls_provenance": native,
                "sqlite_provenance": sqlite_provenance,
                "loaded_native_libraries": sorted(loaded),
                "os_release": Path("/etc/os-release").read_text(encoding="utf-8"),
                "installed_os": installed_os,
                "installed_python": packages,
                "native_modules": native_modules,
                "built_wheels": wheels,
                "wheel_build_toolchain": toolchain,
                "uid": os.getuid(),
                "application_started": False,
                "operator_database_opened": False,
                "provider_requests": 0,
                "all_components_current": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
