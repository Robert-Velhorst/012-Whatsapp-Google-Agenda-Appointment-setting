"""Record the exact wheels built from hash-locked inputs; no installation."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from packaging.utils import canonicalize_name, parse_wheel_filename

root = Path("/wheelhouse")
if sys.platform != "linux" or Path(__file__).resolve().parents[1] != Path(
    "/native-build"
):
    raise RuntimeError("Wheel locking is restricted to the isolated Linux SDK stage")
profile = json.loads(Path("/native-build/native-client-runtime.json").read_text())
toolchain = {}
for name in ("rustc", "cargo"):
    version = subprocess.check_output(
        [name, "--version"], text=True, timeout=30
    ).strip()
    if version.split()[:2] != [name, profile["rust"]["version"]]:
        raise RuntimeError("Unexpected isolated Rust toolchain: " + version)
    toolchain[name] = version
toolchain["input_locks"] = {
    name: hashlib.sha256(Path("/native-build", name).read_bytes()).hexdigest()
    for name in ("requirements-image.lock", "requirements-native-build.lock")
}
root.joinpath("build-toolchain.json").write_text(json.dumps(toolchain, indent=2) + "\n")
rows = []
seen = set()
for path in sorted(root.glob("*.whl")):
    name, version, _, _ = parse_wheel_filename(path.name)
    name = canonicalize_name(name)
    if name in seen:
        raise RuntimeError("Ambiguous wheel version: " + name)
    seen.add(name)
    rows.append(
        {
            "name": name,
            "version": str(version),
            "file": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    )
if not rows or "cryptography" not in seen:
    raise RuntimeError("The image requires the source-built cryptography wheel")
root.joinpath("installed.lock").write_text(
    "\n".join(
        row["name"] + "==" + row["version"] + " --hash=sha256:" + row["sha256"]
        for row in rows
    )
    + "\n"
)
root.joinpath("build-wheels.json").write_text(json.dumps(rows, indent=2) + "\n")
