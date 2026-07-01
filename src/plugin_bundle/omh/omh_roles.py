from __future__ import annotations

from pathlib import Path
import re

ROLE_CONTEXT_SCHEMA_VERSION = "omh_role_context/v1"
ROLE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
ROLE_MARKER_RE = re.compile(r"\[omh-role:([a-zA-Z0-9_-]+)\]")
_REFERENCES_DIR = Path(__file__).parent / "references"
_ROLE_ALIASES = {
    "codex-handoff-guidance": "handoff-guide",
    "coding-handoff": "handoff-guide",
    "hybrid-guidance": "guide",
    "hybrid-measurement": "tracker",
    "hybrid-review": "reviewer",
    "hybrid-verification": "reviewer",
    "implementation-owner": "builder",
    "planning-lead": "planner",
    "research-lead": "researcher",
    "retained-knowledge": "memory-keeper",
    "retained-operator": "operator",
    "retained-router": "guide",
    "review-gate": "reviewer",
    "runtime-handoff-guidance": "handoff-guide",
}


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


def role_aliases() -> dict[str, str]:
    catalog = role_catalog()
    return {alias: target for alias, target in sorted(_ROLE_ALIASES.items()) if target in catalog}


def resolve_role_name(role: str) -> str:
    name = str(role or "").strip()
    return role_aliases().get(name, name)


def load_role_prompt(role: str) -> str:
    name = str(role or "").strip()
    if not ROLE_NAME_RE.fullmatch(name):
        return ""
    path = role_catalog().get(resolve_role_name(name))
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
            "resolved_role": "",
            "available_roles": role_names(),
            "aliases": role_aliases(),
            "context": "",
            "claim_boundary": "OMH role context is prompt guidance only; it is not runtime delegation or execution evidence.",
        }
    resolved = resolve_role_name(str(role or ""))
    return {
        "schema_version": ROLE_CONTEXT_SCHEMA_VERSION,
        "status": "available",
        "role": resolved,
        "requested_role": str(role),
        "resolved_role": resolved,
        "available_roles": role_names(),
        "aliases": role_aliases(),
        "context": prompt,
        "claim_boundary": "OMH role context is prompt guidance only; it is not runtime delegation or execution evidence.",
    }
