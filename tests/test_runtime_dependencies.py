from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _pinned_requirements(path: Path) -> dict[str, str]:
    packages = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+)==([^ ;]+)", line)
        if match:
            name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
            packages[name] = match.group(2)
    return packages


def test_runtime_lock_covers_runtime_pins_without_test_runner():
    direct = _pinned_requirements(ROOT / "requirements-runtime.txt")
    locked = _pinned_requirements(ROOT / "requirements-runtime.lock")

    assert direct
    assert all(locked.get(name) == version for name, version in direct.items())
    assert "pytest" not in locked


def test_development_requirements_include_runtime_and_test_runner():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "-r requirements-runtime.txt" in requirements.splitlines()
    assert "pytest==" in requirements
