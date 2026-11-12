"""Closed, inert support-template export for the frontend phone-check toolkit."""
from __future__ import annotations

import hashlib
from importlib.resources import files
import json

SKILL_NAME = "frontend"
TOOLKIT_DIR = "frontend_toolkit"
TOOLKIT_RESOURCES = (
    "README.md", "LICENSE.upstream", "scripts/phone_check.py",
    "examples/phone-clean.html", "examples/phone-overflow.html", "upstream-manifest.json",
)
PROVENANCE_SCHEMA = "omh_frontend_toolkit_provenance/v1"


def frontend_toolkit_provenance_manifest():
    """Generate hashes for reviewed original resources; this does not write them."""
    root = files("omh.skills").joinpath(TOOLKIT_DIR)
    entries = {}
    for relative in TOOLKIT_RESOURCES:
        if relative == "upstream-manifest.json":
            continue
        sha256 = hashlib.sha256(root.joinpath(relative).read_bytes()).hexdigest()
        entries[relative] = {"local_sha256": sha256, "source_sha256": sha256,
            "source_path": f"src/skills/{TOOLKIT_DIR}/" + relative,
            "classification": "original_omh", "upstream": [], "license": "MIT",
            "copyright": "Copyright (c) 2026 oh-my-hermes contributors",
            "modification_notice": "Original OMH helper, synthetic example or guidance; no upstream source copied."}
    return {"schema": PROVENANCE_SCHEMA,
        "repository": "https://github.com/rlaope/oh-my-hermes", "revision": None,
        "revision_note": "Original uncommitted resources identified by content hashes; not attributed to an upstream revision.",
        "license": "MIT", "self_hash": "excluded; outer distribution inventories hash this manifest", "files": entries}


def frontend_toolkit_support_templates():
    from .support_files import SkillSupportTemplate, validate_support_templates
    root = files("omh.skills").joinpath(TOOLKIT_DIR)
    texts = {}
    for relative in TOOLKIT_RESOURCES:
        with root.joinpath(relative).open("rb") as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("frontend toolkit resource exceeds size limit")
        texts[relative] = raw.decode("utf-8")
    provenance = json.loads(texts["upstream-manifest.json"])
    expected = set(TOOLKIT_RESOURCES) - {"upstream-manifest.json"}
    if (not isinstance(provenance, dict) or provenance.get("schema") != PROVENANCE_SCHEMA
            or not isinstance(provenance.get("files"), dict) or set(provenance["files"]) != expected):
        raise ValueError("invalid closed frontend toolkit provenance inventory")
    for relative in expected:
        entry = provenance["files"][relative]
        if not isinstance(entry, dict) or hashlib.sha256(texts[relative].encode("utf-8")).hexdigest() != entry.get("local_sha256"):
            raise ValueError(f"frontend toolkit provenance digest mismatch: {relative}")
    return validate_support_templates([SkillSupportTemplate(SKILL_NAME, "toolkit/" + relative, texts[relative])
                                       for relative in TOOLKIT_RESOURCES])
