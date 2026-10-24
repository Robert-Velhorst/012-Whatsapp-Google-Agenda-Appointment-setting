"""Link Docker's root descriptor to the exact saved image configuration."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tarfile
from pathlib import Path


def archive_identity(archive: Path, inspections: list, tag: str) -> dict:
    if len(inspections) != 1:
        raise ValueError("Exactly one inspected image is required")
    inspection = inspections[0]
    if tag not in inspection.get("RepoTags", []):
        raise ValueError("The inspected image does not have the expected tag")
    with tarfile.open(archive, "r:*") as bundle:

        def read(name: str) -> bytes:
            member = bundle.getmember(name)
            if not member.isfile() or member.size > 8 * 1024 * 1024:
                raise ValueError("Unexpected image metadata member")
            return bundle.extractfile(member).read()

        entries = [
            entry
            for entry in json.loads(read("manifest.json"))
            if tag in entry.get("RepoTags", [])
        ]
        if len(entries) != 1:
            raise ValueError("The saved archive must identify exactly one tagged image")
        config_name = entries[0]["Config"]
        config_bytes = read(config_name)
        config_id = "sha256:" + hashlib.sha256(config_bytes).hexdigest()
        if config_name not in {
            "blobs/sha256/" + config_id[7:],
            config_id[7:] + ".json",
        }:
            raise ValueError(
                "The saved configuration filename does not match its bytes"
            )
        config = json.loads(config_bytes)
        if (
            inspection.get("Architecture") != config.get("architecture")
            or inspection.get("Os") != config.get("os")
            or inspection.get("RootFS", {}).get("Layers")
            != config.get("rootfs", {}).get("diff_ids")
        ):
            raise ValueError(
                "Inspected platform or filesystem differs from the saved image"
            )
        root_id = inspection["Id"]
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", root_id):
            raise ValueError("Invalid inspected image identifier")

        def reachable_configs(digest: str, depth: int = 0) -> set[str]:
            if depth > 4 or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
                raise ValueError("Unexpected image descriptor graph")
            payload = read("blobs/sha256/" + digest[7:])
            if "sha256:" + hashlib.sha256(payload).hexdigest() != digest:
                raise ValueError("Image descriptor checksum mismatch")
            descriptor = json.loads(payload)
            if "config" in descriptor:
                return {descriptor["config"]["digest"]}
            children = descriptor.get("manifests", [])
            if not children or len(children) > 100:
                raise ValueError("Missing or oversized image descriptor graph")
            found = set()
            for child in children:
                found.update(reachable_configs(child["digest"], depth + 1))
            return found

        # Classic Docker IDs are configuration hashes. Containerd can expose a
        # manifest/index hash instead: verify its actual archive descriptor chain.
        if root_id != config_id and config_id not in reachable_configs(root_id):
            raise ValueError(
                "The inspected descriptor does not select this configuration"
            )
    with archive.open("rb") as stream:
        archive_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "tag": tag,
        "docker_image_id": root_id,
        "config_id": config_id,
        "archive_sha256": archive_digest,
        "architecture": config["architecture"],
        "os": config["os"],
        "diff_ids": config["rootfs"]["diff_ids"],
        "verified_descriptor_chain": True,
    }


if __name__ == "__main__":
    archive, inspection, tag, report, config_output = sys.argv[1:]
    proof = archive_identity(
        Path(archive), json.loads(Path(inspection).read_text()), tag
    )
    Path(report).write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    Path(config_output).write_text(proof["config_id"] + "\n", encoding="ascii")
