# Source verification adapted from MCP Hub at 3ed125e157ed23d3254a7a91b2409893566d811e.
"""Build pinned client libraries in a disposable Linux image stage.

No database server is built, started or contacted. The selected prefix must be
absent; this command never replaces the host SDK or system crypto libraries.
"""

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "native-client-runtime.json").read_text(encoding="utf-8"))
PREFIX = Path(SPEC["prefix"])


def validate_source_url(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.hostname
        not in {
            "github.com",
            "release-assets.githubusercontent.com",
            "www.sqlite.org",
            "www.python.org",
        }
    ):
        raise RuntimeError("Native source URL is outside the verified upstream hosts")


class SourceRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_source_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def run(command, cwd, env=None):
    subprocess.run(command, cwd=cwd, env=env, check=True, timeout=1200)


def source_archive(component, directory):
    archive = directory / (component["version"] + ".archive")
    digest = hashlib.new(component.get("digest_algorithm", "sha256"))
    size = 0
    validate_source_url(component["url"])
    with (
        build_opener(SourceRedirects()).open(component["url"], timeout=60) as response,
        archive.open("xb") as output,
    ):
        validate_source_url(response.url)
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > 100 * 1024 * 1024:
                raise RuntimeError("Native source archive exceeds its download limit")
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != component["sha256"]:
        raise RuntimeError("Native source archive checksum mismatch")
    destination = directory / "source"
    destination.mkdir()
    with tarfile.open(archive) as source:
        members = source.getmembers()
        if len(members) > 50000 or sum(item.size for item in members) > 1024**3:
            raise RuntimeError("Native source archive exceeds its extraction limit")
        source.extractall(destination, filter="data")
    roots = list(destination.iterdir())
    if len(roots) != 1 or not roots[0].is_dir() or roots[0].is_symlink():
        raise RuntimeError("Native archive must contain one source directory")
    return roots[0]


def package(name, version, source_name, directory, output, architecture):
    """Sign an inventory-bearing APK; never export its ephemeral private key."""
    keys = output.parent / "keys"
    keys.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="agenda-apk-signing-") as temporary:
        key = Path(temporary) / (name + ".rsa")
        run(
            [
                "openssl",
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:3072",
                "-out",
                str(key),
            ],
            ROOT,
        )
        key.chmod(0o600)
        run(
            [
                "openssl",
                "rsa",
                "-in",
                str(key),
                "-pubout",
                "-out",
                str(keys / (name + ".rsa.pub")),
            ],
            ROOT,
        )
        command = ["apk", "--sign-key", str(key), "mkpkg", "--files", str(directory)]
        fields = {
            "name": name,
            "version": version + "-r0",
            "arch": architecture,
            "origin": source_name,
            "description": "Agenda Relay checksum-verified upstream native runtime",
            "license": "blessing" if name == "sqlite-libs" else "Apache-2.0",
            "maintainer": "Agenda Relay runtime contributors",
            "depends": "musl",
            "url": "https://www.sqlite.org/"
            if name == "sqlite-libs"
            else "https://www.openssl.org/",
        }
        if name == "sqlite-libs":
            fields["provides"] = "so:libsqlite3.so.0=0"
        for field, value in fields.items():
            command.extend(["--info", field + ":" + value])
        run([*command, "--output", str(output)], ROOT)
        run(["apk", "--keys-dir", str(keys), "verify", str(output)], ROOT)


def main():
    if (
        sys.platform != "linux"
        or ROOT != Path("/native-build")
        or os.environ.get("AGENDA_DISPOSABLE_BUILD_SDK") != "1"
        or SPEC["schema_version"] != 1
        or PREFIX != Path("/opt/agenda-native")
        or PREFIX.exists()
    ):
        raise RuntimeError(
            "Native builds require the fresh disposable SDK and dedicated prefix"
        )
    output = Path("/native-output")
    output.mkdir()
    architecture = subprocess.check_output(["apk", "--print-arch"], text=True).strip()
    if not re.fullmatch(r"[a-z0-9_-]+", architecture):
        raise RuntimeError("Unsupported Alpine architecture")
    with tempfile.TemporaryDirectory(prefix="agenda-native-source-") as temporary:
        root = Path(temporary)
        ssl_dir = root / "openssl"
        ssl_dir.mkdir()
        source = source_archive(SPEC["openssl"], ssl_dir)
        run(
            [
                "./Configure",
                "shared",
                "--prefix=" + str(PREFIX),
                "--libdir=lib",
                "--openssldir=/etc/ssl",
                "-Wl,-rpath," + str(PREFIX / "lib"),
            ],
            source,
        )
        run(["make", "-j2"], source)
        run(["make", "install_sw"], source)
        ssl_package = root / "ssl-package"
        lib_dir = ssl_package / str(PREFIX / "lib").lstrip("/")
        lib_dir.mkdir(parents=True)
        libraries = {}
        for name in ["libssl.so.4", "libcrypto.so.4"]:
            file = PREFIX / "lib" / name
            if not file.is_file() or file.is_symlink():
                raise RuntimeError("Expected actual OpenSSL runtime libraries")
            shutil.copyfile(file, lib_dir / name)
            libraries[str(file)] = hashlib.sha256(file.read_bytes()).hexdigest()
        provider = PREFIX / "lib/ossl-modules/legacy.so"
        if not provider.is_file() or provider.is_symlink():
            raise RuntimeError("Expected the current OpenSSL legacy provider module")
        (lib_dir / "ossl-modules").mkdir()
        shutil.copyfile(provider, lib_dir / "ossl-modules/legacy.so")
        libraries[str(provider)] = hashlib.sha256(provider.read_bytes()).hexdigest()
        doc = ssl_package / "usr/share/doc/libssl4"
        doc.mkdir(parents=True)
        shutil.copyfile(source / "LICENSE.txt", doc / "copyright")
        provenance = {"source": SPEC["openssl"], "libraries": libraries}
        metadata = ssl_package / "usr/share/agenda-native"
        metadata.mkdir(parents=True)
        metadata.joinpath("openssl.json").write_text(
            json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
        )
        package(
            "libssl4",
            SPEC["openssl"]["version"],
            "openssl",
            ssl_package,
            output / "agenda-openssl.apk",
            architecture,
        )

        sqlite_dir = root / "sqlite"
        sqlite_dir.mkdir()
        sqlite = source_archive(SPEC["sqlite"], sqlite_dir)
        library_dir = "/usr/lib"
        flags = [
            "-O2",
            "-fPIC",
            "-shared",
            "-Wl,-soname,libsqlite3.so.0",
            "-DSQLITE_THREADSAFE=1",
            "-DSQLITE_USE_URI=1",
            "-DSQLITE_ENABLE_COLUMN_METADATA",
            "-DSQLITE_SECURE_DELETE",
            "-DSQLITE_ENABLE_UNLOCK_NOTIFY",
            "-DSQLITE_ENABLE_RTREE",
            "-DSQLITE_ENABLE_GEOPOLY",
            "-DSQLITE_ENABLE_DBSTAT_VTAB",
            "-DSQLITE_SOUNDEX",
            "-DSQLITE_MAX_VARIABLE_NUMBER=250000",
            "-DSQLITE_ENABLE_FTS3",
            "-DSQLITE_ENABLE_FTS3_PARENTHESIS",
            "-DSQLITE_ENABLE_FTS4",
            "-DSQLITE_ENABLE_FTS5",
            "-DSQLITE_ENABLE_SESSION",
            "-DSQLITE_ENABLE_PREUPDATE_HOOK",
            "-DSQLITE_ENABLE_MATH_FUNCTIONS",
        ]
        sqlite_package = root / "sqlite-package"
        target_dir = sqlite_package / library_dir.lstrip("/")
        target_dir.mkdir(parents=True)
        library = target_dir / "libsqlite3.so.0.8.6"
        run(
            [
                "cc",
                *flags,
                str(sqlite / "sqlite3.c"),
                "-lm",
                "-ldl",
                "-pthread",
                "-o",
                str(library),
            ],
            sqlite,
        )
        library.chmod(0o644)
        (target_dir / "libsqlite3.so.0").symlink_to(library.name)
        actual = target_dir / "libsqlite3.so.0"
        engine = ctypes.CDLL(str(actual))
        engine.sqlite3_libversion.restype = ctypes.c_char_p
        if engine.sqlite3_libversion().decode("ascii") != SPEC["sqlite"]["version"]:
            raise RuntimeError(
                "Compiled SQLite version differs from the selected source"
            )
        sqlite_doc = sqlite_package / "usr/share/doc/sqlite-libs"
        sqlite_doc.mkdir(parents=True)
        header = re.search(
            r"/\*.*?\*/", (sqlite / "sqlite3.c").read_text(encoding="utf-8"), re.DOTALL
        )[0]
        sqlite_doc.joinpath("copyright").write_text(
            header + "\nhttps://www.sqlite.org/copyright.html\n"
        )
        (sqlite_package / "usr/share/agenda-native").mkdir(parents=True)
        sqlite_provenance = {
            "source": SPEC["sqlite"],
            "cflags": flags,
            "library_sha256": hashlib.sha256(actual.read_bytes()).hexdigest(),
        }
        (sqlite_package / "usr/share/agenda-native/sqlite.json").write_text(
            json.dumps(sqlite_provenance, indent=2) + "\n"
        )
        package(
            "sqlite-libs",
            SPEC["sqlite"]["version"],
            "sqlite",
            sqlite_package,
            output / "agenda-sqlite.apk",
            architecture,
        )
        output.joinpath("build-provenance.json").write_text(
            json.dumps({"openssl": provenance, "sqlite": sqlite_provenance}, indent=2)
            + "\n"
        )


if __name__ == "__main__":
    main()
