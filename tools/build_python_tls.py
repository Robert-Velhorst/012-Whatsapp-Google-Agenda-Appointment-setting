"""Rebuild the exact CPython SSL modules inside the disposable build SDK."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

from build_native_runtime import PREFIX, ROOT, SPEC, source_archive


def main():
    if (
        sys.platform != "linux"
        or ROOT != Path("/native-build")
        or os.environ.get("AGENDA_DISPOSABLE_BUILD_SDK") != "1"
        or not PREFIX.is_dir()
    ):
        raise RuntimeError(
            "TLS module compilation is restricted to the isolated SDK stage"
        )
    if sys.version.split()[0] != SPEC["cpython"]["version"]:
        raise RuntimeError("The SDK interpreter must match the verified CPython source")
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    if not re.fullmatch(r"\.cpython-315-[a-z0-9_-]+\.so", suffix):
        raise RuntimeError("Unsupported CPython module ABI")
    destination = Path(sysconfig.get_config_var("DESTSHARED"))
    if destination != Path("/usr/local/lib/python3.15/lib-dynload"):
        raise RuntimeError("Unexpected isolated SDK module directory")
    export = Path("/python-tls-runtime")
    export.mkdir()
    module_export = export / "lib-dynload"
    module_export.mkdir()
    records = {}
    with tempfile.TemporaryDirectory(prefix="agenda-cpython-tls-") as temporary:
        source = source_archive(SPEC["cpython"], Path(temporary))
        for name, filename, libraries in [
            ("_ssl", "_ssl.c", ["ssl", "crypto"]),
            ("_hashlib", "_hashopenssl.c", ["crypto"]),
        ]:
            target = destination / (name + suffix)
            if not target.is_file() or target.is_symlink():
                raise RuntimeError("Expected the exact installed SDK extension")
            original_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            output = module_export / target.name
            includes = [
                Path(sysconfig.get_path("include")),
                source / "Include",
                source / "Include/internal",
                source / "Modules",
                source / "Modules/_ssl",
                PREFIX / "include",
            ]
            command = [
                "cc",
                "-shared",
                "-fPIC",
                "-O2",
                "-DNDEBUG",
                "-DPy_BUILD_CORE_MODULE=1",
                *["-I" + str(path) for path in includes],
                str(source / "Modules" / filename),
                "-L" + str(PREFIX / "lib"),
                "-Wl,-rpath," + str(PREFIX / "lib"),
                *["-l" + library for library in libraries],
                "-o",
                str(output),
            ]
            subprocess.run(command, check=True, timeout=300)
            # This process already imports the old SSL/hash extensions through
            # download/hash tooling. Replace atomically, preserving mapped inodes.
            staged = target.with_name(target.name + ".agenda-new")
            if staged.exists():
                raise RuntimeError("Unexpected existing SDK staging file")
            shutil.copyfile(output, staged)
            os.replace(staged, target)
            records[target.name] = {
                "original_sha256": original_hash,
                "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            }
        shutil.copyfile(source / "LICENSE", export / "CPython-LICENSE")
    result = json.loads(
        subprocess.check_output(
            [
                sys.executable,
                "-I",
                "-c",
                (
                    "import ssl,hashlib,json; c=ssl.create_default_context(); "
                    "print(json.dumps({'openssl':ssl.OPENSSL_VERSION,'ca_roots':len(c.get_ca_certs()),"
                    "'sha256':hashlib.sha256(b'agenda-native-profile').hexdigest()}))"
                ),
            ],
            text=True,
            env={**os.environ, "LD_LIBRARY_PATH": str(PREFIX / "lib")},
            timeout=30,
        )
    )
    if (
        not result["openssl"].startswith("OpenSSL " + SPEC["openssl"]["version"] + " ")
        or result["ca_roots"] < 1
    ):
        raise RuntimeError(
            "The fresh interpreter must use the requested TLS library and CA roots"
        )
    if result["sha256"] != hashlib.sha256(b"agenda-native-profile").hexdigest():
        raise RuntimeError("Native hashing mismatch")
    provenance = {
        "source": SPEC["cpython"],
        "headers_sha256": hashlib.sha256(
            Path(sysconfig.get_config_h_filename()).read_bytes()
        ).hexdigest(),
        "modules": records,
        "runtime": result,
        "operator_database_opened": False,
    }
    export.joinpath("provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    print(json.dumps(provenance))


if __name__ == "__main__":
    main()
