from __future__ import annotations

from pathlib import Path
import re

ROLE_CONTEXT_SCHEMA_VERSION = "omh_role_context/v1"
ROLE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
ROLE_MARKER_RE = re.compile(r"\[omh-role:([a-zA-Z0-9_-]+)\]")
_REFERENCES_DIR = Path(__file__).parent / "references"


def extract_role_marker(text: str) -> str:
    match = ROLE_MARKER_RE.search(text or "")
    return match.group(1) if match else ""


def role_catalog() -> dict[str, Path]:
    if not _REFERENCES_DIR.exists():
        return {}
    return {
        path.stem.removeprefix("role-"): path
        for path in sorted(_REFERENCES_DIR.glob("role-*.md"))
        if path.is_file()
    }


def role_names() -> list[str]:
    return sorted(role_catalog())


def load_role_prompt(role: str) -> str:
    name = str(role or "").strip()
    if not ROLE_NAME_RE.fullmatch(name):
        return ""
    path = role_catalog().get(name)
    if not path:
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def role_context_payload(role: str) -> dict[str, object]:
    prompt = load_role_prompt(role)
    if not prompt:
        return {
            "schema_version": ROLE_CONTEXT_SCHEMA_VERSION,
            "status": "unknown_role",
            "role": str(role or ""),
            "available_roles": role_names(),
            "context": "",
            "claim_boundary": "OMH role context is prompt guidance only; it is not runtime delegation or execution evidence.",
        }
    return {
        "schema_version": ROLE_CONTEXT_SCHEMA_VERSION,
        "status": "available",
        "role": str(role),
        "available_roles": role_names(),
        "context": prompt,
        "claim_boundary": "OMH role context is prompt guidance only; it is not runtime delegation or execution evidence.",
    }
