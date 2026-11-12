"""Closed UTF-8 companion resources: a separate kind, never imports/execution."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re


@dataclass(frozen=True)
class SkillSupportTemplate:
    skill_name: str
    relative_path: str
    content: str
    kind: str = "support"


def validate_support_path(relative: str) -> str:
    if not isinstance(relative, str) or len(relative) > 240:
        raise ValueError("invalid support path")
    parts = relative.split("/")
    if len(parts) < 2 or parts[0] != "toolkit":
        raise ValueError("support must be under toolkit/")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    for part in parts:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", part) or part in (".", "..") or part.endswith(".") or part.split(".")[0].upper() in reserved:
            raise ValueError(f"unsafe support path: {relative!r}")
    if parts[-1] != "LICENSE.upstream" and Path(parts[-1]).suffix not in (".md", ".json", ".html", ".css", ".js", ".mjs", ".py", ".swift", ".sh"):
        raise ValueError("support is restricted to declared UTF-8 text types")
    return relative


def validate_support_templates(templates):
    seen = set()
    for template in templates:
        validate_support_path(template.relative_path)
        if not re.fullmatch(r"[a-z][a-z0-9-]*", template.skill_name) or template.kind != "support":
            raise ValueError("invalid support identity/kind")
        key = (template.skill_name.casefold(), template.relative_path.casefold())
        if key in seen:
            raise ValueError("duplicate/casefold support collision")
        seen.add(key)
        if not isinstance(template.content, str) or "\x00" in template.content or len(template.content.encode("utf-8")) > 1_048_576:
            raise ValueError("support content must be bounded UTF-8 text without NUL")
    return templates


def checked_support_path(root: Path, relative: str) -> Path:
    validate_support_path(relative)
    root = root.absolute()
    candidate = root / relative
    # The root's own parent and every component below it, as the Agent Skills
    # writer checks; the user's layout above that is theirs.
    for path in (root.parent, root, *(root / parent for parent in Path(relative).parents), candidate):
        if path.is_symlink():
            raise ValueError(f"support refuses symlink component: {path}")
        if path.exists() and path != candidate and not path.is_dir():
            raise ValueError(f"support parent is not a directory: {path}")
    if candidate.exists() and not candidate.is_file():
        raise ValueError(f"support destination is not a file: {candidate}")
    return candidate


def builtin_skill_support_templates():
    from .show_reel_support import show_reel_support_templates
    from .geospatial_analysis_skill import geospatial_analysis_support_templates
    from .sprite_forge_skill import sprite_forge_support_templates
    from .biomedical_evidence_skill import biomedical_evidence_support_templates
    from .molecular_docking_skill import molecular_docking_support_templates
    from .ai_job_search_skill import ai_job_search_support_templates
    from .frontend_support import frontend_toolkit_support_templates

    return validate_support_templates([
        *show_reel_support_templates(),
        *geospatial_analysis_support_templates(),
        *sprite_forge_support_templates(),
        *biomedical_evidence_support_templates(),
        *molecular_docking_support_templates(),
        *ai_job_search_support_templates(),
        *frontend_toolkit_support_templates(),
    ])


@lru_cache(maxsize=1)
def builtin_support_owners():
    """Finite reviewed owners, derived from the authoritative support inventory."""
    return frozenset(t.skill_name for t in builtin_skill_support_templates())

def agent_skill_support_templates():
    from dataclasses import replace
    from .catalog import omh_skill_display_name
    from .catalog_portable import PORTABLE_SUPPORT_PATHS

    return [replace(t, skill_name=omh_skill_display_name(t.skill_name)) for t in builtin_skill_support_templates()
            if f"{t.skill_name}/{t.relative_path}" in PORTABLE_SUPPORT_PATHS]
