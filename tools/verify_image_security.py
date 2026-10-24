"""Reconcile the raw complete scan with the exact inspected runtime image."""

import json
import re
import sys
from pathlib import Path


def main():
    scan, identity, runtime = [
        json.loads(Path(name).read_text(encoding="utf-8")) for name in sys.argv[1:]
    ]
    if scan["Metadata"]["ImageID"] != identity["config_id"]:
        raise RuntimeError(
            "Scanner image identity differs from the saved runtime image"
        )
    os_info = scan["Metadata"]["OS"]
    if (
        os_info["Family"] != "alpine"
        or ".".join(os_info["Name"].split(".")[:2]) != "3.24"
        or os_info.get("EOSL")
    ):
        raise RuntimeError("Expected supported stable Alpine 3.24")
    normalize = lambda name: re.sub(r"[-_.]+", "-", name.lower())
    installed = {}
    os_count = python_count = 0
    for result in [scan, *scan["Results"]]:
        for field in [
            "Vulnerabilities",
            "ModifiedFindings",
            "ExperimentalModifiedFindings",
        ]:
            if result.get(field):
                raise RuntimeError("Unresolved or modified raw findings: " + field)
        if result is scan:
            continue
        if not result.get("Packages"):
            raise RuntimeError("The complete scan must retain every result inventory")
        if result.get("Class") == "os-pkgs":
            os_count += len(result["Packages"])
        if result.get("Type") == "python-pkg":
            python_count += len(result["Packages"])
        for package in result["Packages"]:
            installed.setdefault(normalize(package["Name"]), set()).add(
                package["Version"]
            )
    if not os_count or not python_count:
        raise RuntimeError("Both OS and installed Python inventory are required")
    for package in runtime["installed_python"]:
        if package["version"] not in installed.get(normalize(package["name"]), set()):
            raise RuntimeError(
                "Installed Python distribution is absent from scan: " + package["name"]
            )
    if installed.get("sqlite-libs") != {"3.54.1-r0"} or installed.get("libssl4") != {
        "4.1.0-r0"
    }:
        raise RuntimeError(
            "The scan must include the registered native source packages"
        )
    print(
        json.dumps(
            {
                "config_id": identity["config_id"],
                "os_inventory_entries": os_count,
                "python_inventory_entries": python_count,
                "raw_findings": 0,
                "modified_findings": 0,
                "all_components_current": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
