"""Catalog-generated Agent Skills files, independent of Hermes configuration.

Host-selected installs have one portable receipt; unselected installs duplicate
one manifest at both roots. Updates reuse an installed user pack's receipt.
A partial write cannot report fresh: status compares every destination's bytes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any

from ..hashutil import sha256_file, sha256_text
from ..local_store import atomic_write_text
from ..skills.render import agent_skill_reference_templates, agent_skill_templates
from ..skills.support_files import agent_skill_support_templates

MANIFEST_NAME = ".omh-agent-skills-manifest.json"
SCHEMA_VERSION = "omh_agent_skills_projection/v1"
CLAIM_BOUNDARY = (
    "Generated local guidance only. Fresh files do not prove host discovery, "
    "selection, loading, execution, review, CI, or merge."
)


# The two directories any installer writes. Cursor and opencode load both, so
# a pack in each is every skill twice (docs/AGENT-SKILLS.md#duplicate-copies).
PACK_ROOTS = (".agents/skills", ".claude/skills")


def sibling_pack_root(root: str) -> str:
    return PACK_ROOTS[1] if root == PACK_ROOTS[0] else PACK_ROOTS[0]


def duplicate_pack_warnings(target: Path) -> list[str]:
    """Warn, never refuse: Claude Code plus a .agents host legitimately needs both."""
    base = target.parent.parent
    if not all((base / root / MANIFEST_NAME).is_file() for root in PACK_ROOTS):
        return []
    return [
        f"OMH Agent Skills are installed in both {base / PACK_ROOTS[0]} and {base / PACK_ROOTS[1]}. "
        "Cursor and opencode load both directories and find each skill twice; Codex and OpenClaw "
        "read only .agents/skills, and Claude Code only .claude/skills. Keep the copy your host reads "
        "(install with --host <host>) and remove the other: see docs/AGENT-SKILLS.md#duplicate-copies."
    ]


def agent_skill_files() -> dict[str, str]:
    """The same packaged producer drives install and the committed byte gate."""
    files = {f"{t.name}/SKILL.md": t.content for t in agent_skill_templates()}
    files.update({f"{t.skill_name}/{t.relative_path}": t.content for t in agent_skill_reference_templates()})
    files.update({f"{t.skill_name}/{t.relative_path}": t.content for t in agent_skill_support_templates()})
    return files


def agent_skills_targets(scope: str, *, host: str | None = None) -> tuple[Path, Path | None]:
    if host is not None:
        from ..skills.host_adapters import host_adapter_manifest

        manifest = host_adapter_manifest(host, agent_skill_files())
        if scope not in manifest["targets"]:
            raise ValueError("Agent Skills scope must be repo or user")
        # Clone installers need neither Python nor git: repo scope is explicitly
        # the current project directory, identically in this host-selected path.
        base = Path.home().resolve() if scope == "user" else Path.cwd().resolve()
        return base / manifest["targets"][scope], None
    if scope == "user":
        home = Path.home().resolve()
        return home / ".agents/skills", home / ".claude/skills"
    if scope != "repo":
        raise ValueError("Agent Skills scope must be repo or user")
    try:
        result = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "--no-optional-locks", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=False, timeout=10,
            env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Agent Skills git-root probe timed out; no files were written") from exc
    if result.returncode:
        raise ValueError("Agent Skills repo scope requires a git repository; no files were written")
    root = Path(result.stdout.strip()).resolve()
    return root / ".agents/skills", root / ".claude/skills"


def _checked_path(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if (path.is_absolute() or "\\" in relative or ":" in relative
            or any(part in ("", ".", "..") for part in relative.split("/"))):
        raise ValueError(f"Unsafe Agent Skills manifest path: {relative!r}")
    if any(not re.fullmatch(r"[A-Za-z0-9._-]+", part) for part in relative.split("/")):
        raise ValueError(f"Unsafe Agent Skills manifest path: {relative!r}")
    if "/toolkit/" in relative:
        from ..skills.support_files import validate_support_path

        validate_support_path("toolkit/" + relative.split("/toolkit/", 1)[1])
    candidate = root / path
    if candidate.exists() and not candidate.is_file():
        raise ValueError(f"Agent Skills manifest target is not a regular file: {candidate}")
    # .agents/.claude and every destination component must be real directories
    # or files; a pre-existing symlink may not redirect an authorized install.
    for item in (root.parent, root, *candidate.relative_to(root).parents):
        checked = item if item.is_absolute() else root / item
        if checked.is_symlink():
            raise ValueError(f"Agent Skills refuses symlink destination: {checked}")
        if checked.exists() and not checked.is_dir():
            raise ValueError(f"Agent Skills parent is not a directory: {checked}")
    if candidate.is_symlink():
        raise ValueError(f"Agent Skills refuses symlink destination: {candidate}")
    return candidate


def _read_manifest(root: Path) -> dict[str, Any] | None:
    path = _checked_path(root, MANIFEST_NAME)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION
            or not isinstance(payload.get("files"), dict)
            or not isinstance(payload.get("catalog_revision"), str)
            or not isinstance(payload.get("target_dirs"), list)
            or not all(isinstance(item, str) for item in payload["target_dirs"])):
        raise ValueError(f"Invalid Agent Skills manifest: {path}")
    seen = set()
    for relative, digest in payload["files"].items():
        if relative.casefold() in seen:
            raise ValueError("Casefold-colliding Agent Skills manifest paths")
        seen.add(relative.casefold())
        _checked_path(root, relative)
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError(f"Invalid Agent Skills digest: {relative}")
    return payload


def agent_skills_manifest(files: dict[str, str], *, roots: tuple[Path, ...] = ()) -> dict[str, Any]:
    """Portable single-target receipt, or the existing absolute mirrored receipt."""
    hashes = {name: sha256_text(content) for name, content in sorted(files.items())}
    revision = sha256_text("\n".join(f"{name}\0{digest}" for name, digest in hashes.items()))
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_revision": revision,
        "target_dirs": [str(root) for root in roots] if len(roots) > 1 else ["."],
        "files": hashes,
    }


def agent_skills_status(target: Path, *, mirror: Path | None = None) -> dict[str, Any]:
    roots = (target.absolute(),) if mirror is None else (target.absolute(), mirror.absolute())
    files = agent_skill_files()
    expected = agent_skills_manifest(files, roots=roots)
    portable_expected = agent_skills_manifest(files)
    modified: list[str] = []
    states = []
    installed_revisions = []
    for index, root in enumerate(roots):
        manifest = _read_manifest(root)
        installed_revisions.append(manifest["catalog_revision"] if manifest else "")
        if manifest is None:
            states.append("missing")
            continue
        for relative, digest in manifest["files"].items():
            path = _checked_path(root, relative)
            if not path.is_file() or sha256_file(path) != digest:
                modified.append(relative if index == 0 else f"mirror:{relative}")
        # A host-selected receipt stays portable even when status also probes
        # the sibling root used by an unselected install.
        matches = manifest in (expected, portable_expected) and all(
            _checked_path(root, relative).is_file()
            and sha256_file(root / relative) == digest
            for relative, digest in expected["files"].items()
        )
        states.append("fresh" if matches else "stale")
    projection = (
        states[0] if len(states) == 2 and states[1] == "missing"
        else "missing" if "missing" in states else "stale" if "stale" in states else "fresh"
    )
    warnings = duplicate_pack_warnings(target.absolute())
    if len(states) == 2 and states[0] != "missing" and states[1] == "missing":
        scope = "user" if target.absolute() == Path.home().absolute() / ".agents/skills" else "repo"
        warnings.append(
            f"The mirror copy at {roots[1]} is absent; the primary pack is {states[0]}. "
            f"To create both copies, run `omh install --target agents --scope {scope}`."
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_revision": expected["catalog_revision"],
        "installed_revisions": installed_revisions,
        "target_dirs": [str(root) for root in roots],
        "projection": projection,
        "primary": states[0],
        "mirror": states[1] if len(states) == 2 else "none",
        "drift": "locally_modified" if modified else "unknown" if "missing" in states else "clean",
        "locally_modified": sorted(modified),
        "next_action": (
            "Edited toolkit files are never replaced: back up each locally-modified file, move the "
            "toolkit ones aside, then rerun the same install command."
            if any("/toolkit/" in relative for relative in modified)
            else "Review or back up locally-modified files; rerun the same install command to replace them."
            if modified else "Rerun the same install command to generate the current catalog."
            if projection != "fresh" else "No repair needed; host use remains not_observed."
        ),
        "warnings": warnings,
        "host_observation": "not_observed",
        "claim_boundary": CLAIM_BOUNDARY,
    }


def refresh_installed_agent_skills(home: Path, *, dry_run: bool) -> dict[str, Any] | None:
    """Refresh only an existing user .agents pack, preserving its install layout."""
    target = home.absolute() / ".agents/skills"
    if not (target / MANIFEST_NAME).exists():
        return None
    manifest = _read_manifest(target)
    if manifest is None:
        return None
    directories = manifest["target_dirs"]
    mirror = None
    if directories != ["."]:
        if (len(directories) != 2 or not all(Path(item).is_absolute() for item in directories)
                or Path(directories[0]) != target or Path(directories[1]) == target):
            raise ValueError("Invalid installed user Agent Skills target_dirs")
        mirror = Path(directories[1])
    roots = [str(target)] + ([str(mirror)] if mirror is not None else [])
    if dry_run:
        return {"would_refresh": roots}
    before = agent_skills_status(target, mirror=mirror)
    after = install_agent_skills(target, mirror=mirror)
    return {
        "target_dirs": roots,
        "projection_before": before["projection"],
        "projection_after": after["projection"],
        "refreshed_files": len(agent_skill_files()) * len(roots),
    }


def install_agent_skills(target: Path, *, mirror: Path | None = None) -> dict[str, Any]:
    roots = (target.absolute(),) if mirror is None else (target.absolute(), mirror.absolute())
    files = agent_skill_files()
    manifests = [_read_manifest(root) for root in roots]
    # Preflight all destinations before writing either scope or mirror. Preserve
    # unrelated host skills and refuse conflicting files OMH never installed.
    for root, previous in zip(roots, manifests):
        for relative, content in files.items():
            path = _checked_path(root, relative)
            owned = relative in (previous or {}).get("files", {})
            if path.exists() and owned and "/toolkit/" in relative and (
                not path.is_file() or sha256_file(path) != previous["files"][relative]
            ):
                raise ValueError(f"Agent Skills refuses edited support: {path}")
            if path.exists() and not owned and (not path.is_file() or path.read_bytes() != content.encode("utf-8")):
                raise ValueError(f"Agent Skills refuses unowned file collision: {path}")
    manifest = agent_skills_manifest(files, roots=roots)
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    for root, previous in zip(roots, manifests):
        for relative, content in files.items():
            atomic_write_text(_checked_path(root, relative), content)
        for relative in (previous or {}).get("files", {}).keys() - files.keys():
            path = _checked_path(root, relative)
            if path.exists():
                if "/toolkit/" in relative and sha256_file(path) != previous["files"][relative]:
                    # Retired edited support becomes foreign data, not recursive cleanup.
                    continue
                path.unlink()
            # Empty retired skill/reference directories are ours; never recurse
            # into or remove a foreign file that shares the same skill root.
            parent = path.parent
            while parent != root and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
        atomic_write_text(_checked_path(root, MANIFEST_NAME), manifest_text)
    return agent_skills_status(target, mirror=mirror)
