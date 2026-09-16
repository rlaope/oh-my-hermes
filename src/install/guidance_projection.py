"""One status for the Hermes-visible projection of reviewed OMH guidance.

The canonical guidance is catalog data in `src/skills/`. What Hermes reads is a
generated projection of it under the managed skills directory. Those are two
different things, and four different questions can be asked about the gap
between them:

1. Is the projection rendered from the catalog this package carries?
2. Has anything rewritten the projected files since they were installed?
3. Is the managed directory registered where Hermes would look?
4. Has the running host actually been observed reading it?

Doctor already answered fragments of all four, across `manifest`,
`local_modifications`, `skill_freshness`, `external_dir`, and `runtime_context`.
What it could not do was say which of the four was the problem, because there
was no single identifier for "the catalog this package would render". Comparing
per-file checksums against freshly rendered templates detects drift but cannot
name the revision that drifted, so a manifest could not record what it was
projected from.

`catalog_revision` is that identifier, and `build_guidance_projection_status`
is the projection that keeps the four answers separate. The separation is the
point: registration is not observation, and a fresh projection is not proof
that Hermes loaded it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..hashutil import sha256_file, sha256_text
from ..skill_pack import builtin_skill_reference_templates, builtin_skill_templates
from ..skills.catalog import omh_skill_install_path

GUIDANCE_PROJECTION_STATUS_SCHEMA_VERSION = "guidance_projection_status/v1"

# Whether the installed files were rendered from the catalog this package
# carries. `not_comparable` is for a projection installed from a local source
# tree, where "the packaged catalog" is not the thing it came from.
PROJECTION_STATES = ("fresh", "stale", "missing", "not_comparable")
# Whether anything rewrote the projected files after they were installed. This
# is deliberately a separate axis from `PROJECTION_STATES`: a locally edited
# file and a file left behind by an older release both differ from the current
# catalog, and they need different repairs.
DRIFT_STATES = ("clean", "locally_modified", "unknown")
REGISTRATION_STATES = ("registered", "not_registered", "unknown")
# Whether the running host was observed reading the projection. There is no
# `not_registered` here on purpose -- an unregistered directory that a host was
# somehow observed reading is a real state, and collapsing the two axes would
# hide it.
HOST_OBSERVATION_STATES = ("observed", "not_observed")

GUIDANCE_PROJECTION_STATUS_KEYS = (
    "catalog_revision",
    "claim_boundary",
    "drift",
    "host_observation",
    "installed_revision",
    "locally_modified",
    "next_action",
    "projection",
    "registration",
    "schema_version",
    "skills_dir",
)

GUIDANCE_PROJECTION_CLAIM_BOUNDARY = (
    "This is the local projection state of generated OMH guidance. A fresh projection means the "
    "installed files match the catalog this package carries; it is not evidence that Hermes loaded, "
    "selected, or executed them. Registration is where Hermes would look, not proof that it did."
)


def catalog_revision() -> str:
    """A digest naming the guidance this package would render.

    Every generated file has a template, so hashing the templates names the
    catalog without touching disk. Names are included beside content so that
    renaming a skill changes the revision even when no body text does, and the
    pairs are sorted so the digest does not depend on catalog iteration order.
    """
    lines = [
        f"skill\0{template.name}\0{sha256_text(template.content)}" for template in builtin_skill_templates()
    ]
    lines.extend(
        f"reference\0{template.skill_name}\0{template.relative_path}\0{sha256_text(template.content)}"
        for template in builtin_skill_reference_templates()
    )
    return sha256_text("\n".join(sorted(lines)))


def projected_skill_paths() -> tuple[str, ...]:
    """The projection-relative path of every generated SKILL.md, in catalog order."""
    return tuple(
        f"{omh_skill_install_path(template.name)}/SKILL.md" for template in builtin_skill_templates()
    )


def build_guidance_projection_status(
    skills_dir: Path,
    manifest: dict[str, Any] | None,
    *,
    registered: bool | None,
    host_observed: bool,
) -> dict[str, Any]:
    """Report the four projection questions as four separate answers.

    `registered` is `None` when the Hermes config could not be read at all,
    which is `unknown` rather than `not_registered`: an unreadable config is a
    different repair from a config that simply does not list the directory.

    `host_observed` comes from the caller because OMH cannot observe a running
    Hermes from here. Absent evidence is `not_observed`, never `observed`.
    """
    current = catalog_revision()
    installed = str((manifest or {}).get("catalog_revision", ""))
    source = str((manifest or {}).get("source", "")) or "unknown"
    modified = _locally_modified(manifest, skills_dir)
    projection = _projection_state(
        skills_dir=skills_dir,
        manifest=manifest,
        source=source,
        installed_revision=installed,
        current_revision=current,
    )
    drift = "unknown" if manifest is None else "locally_modified" if modified else "clean"
    registration = (
        "unknown" if registered is None else "registered" if registered else "not_registered"
    )
    return {
        "schema_version": GUIDANCE_PROJECTION_STATUS_SCHEMA_VERSION,
        "skills_dir": str(skills_dir),
        "catalog_revision": current,
        "installed_revision": installed,
        "projection": projection,
        "drift": drift,
        "locally_modified": modified,
        "registration": registration,
        "host_observation": "observed" if host_observed else "not_observed",
        "next_action": _next_action(projection, drift, registration),
        "claim_boundary": GUIDANCE_PROJECTION_CLAIM_BOUNDARY,
    }


def validate_guidance_projection_status(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["guidance_projection_status must be an object"]
    extra = sorted(set(payload) - set(GUIDANCE_PROJECTION_STATUS_KEYS))
    if extra:
        errors.append(f"guidance_projection_status has unsupported keys: {extra}")
    missing = sorted(set(GUIDANCE_PROJECTION_STATUS_KEYS) - set(payload))
    if missing:
        errors.append(f"guidance_projection_status is missing keys: {missing}")
    if payload.get("schema_version") != GUIDANCE_PROJECTION_STATUS_SCHEMA_VERSION:
        errors.append(
            f"guidance_projection_status schema_version must be {GUIDANCE_PROJECTION_STATUS_SCHEMA_VERSION}"
        )
    for key, vocabulary in (
        ("projection", PROJECTION_STATES),
        ("drift", DRIFT_STATES),
        ("registration", REGISTRATION_STATES),
        ("host_observation", HOST_OBSERVATION_STATES),
    ):
        value = payload.get(key)
        if value not in vocabulary:
            errors.append(f"guidance_projection_status {key} must be one of {list(vocabulary)}")
    for key in ("catalog_revision", "claim_boundary", "installed_revision", "next_action", "skills_dir"):
        if not isinstance(payload.get(key), str):
            errors.append(f"guidance_projection_status {key} must be a string")
    modified = payload.get("locally_modified")
    if not isinstance(modified, list) or not all(isinstance(item, str) for item in modified):
        errors.append("guidance_projection_status locally_modified must be a list of strings")
    elif list(modified) != sorted(modified):
        errors.append("guidance_projection_status locally_modified must be sorted")
    elif modified and payload.get("drift") != "locally_modified":
        errors.append("guidance_projection_status drift must be locally_modified when files are listed")
    return errors


def _projection_state(
    *,
    skills_dir: Path,
    manifest: dict[str, Any] | None,
    source: str,
    installed_revision: str,
    current_revision: str,
) -> str:
    if manifest is None:
        return "missing"
    if source != "builtin":
        # Installed from a local source tree. The packaged catalog is not what
        # it was rendered from, so comparing the two would report drift that no
        # `omh update` can resolve.
        return "not_comparable"
    installed_paths = _manifest_paths(manifest)
    if not installed_paths:
        return "missing"
    # Completeness is measured against the manifest, not against the catalog,
    # because the profile recorded at install time decides which templates
    # should exist: a `core` install holds `CORE_PROFILE_SKILLS` and nothing
    # else, so "every template has a file" would report that correct install as
    # missing. The rule holds whatever the default profile is, which is why no
    # default is named here -- an earlier revision of this comment asserted the
    # default WAS that subset, and stayed in place after the default became
    # `full`. `GuidanceProjectionProfileTests` computes both halves instead:
    # that a core install reads `fresh`, and what the default actually is.
    if any(not (skills_dir / rel).is_file() for rel in installed_paths):
        return "missing"
    if not installed_revision:
        # A manifest written before revisions were recorded. Fall back to the
        # comparison that does not need one: does every installed file match
        # what this package renders for it today?
        return "fresh" if _installed_files_match_catalog(skills_dir, manifest) else "stale"
    return "fresh" if installed_revision == current_revision else "stale"


def _manifest_paths(manifest: dict[str, Any]) -> list[str]:
    return [
        str(record.get("path", ""))
        for record in manifest.get("skills", [])
        if isinstance(record, dict) and str(record.get("path", ""))
    ]


def _installed_files_match_catalog(skills_dir: Path, manifest: dict[str, Any]) -> bool:
    """Whether every installed SKILL.md matches the template this package renders.

    Only files the manifest lists are compared, for the same reason
    `_projection_state` measures completeness that way: a profile install is
    complete without every template on disk.
    """
    rendered = {
        f"{omh_skill_install_path(template.name)}/SKILL.md": sha256_text(template.content)
        for template in builtin_skill_templates()
    }
    for rel in _manifest_paths(manifest):
        expected = rendered.get(rel)
        if expected is None:
            # A file with no template in this package: it cannot be compared
            # against the packaged catalog, so it is not evidence of staleness.
            continue
        path = skills_dir / rel
        if not path.is_file() or sha256_file(path) != expected:
            return False
    return True


def _locally_modified(manifest: dict[str, Any] | None, skills_dir: Path) -> list[str]:
    """Projected files whose bytes no longer match the manifest that installed them.

    This is read-only and one-way. Nothing here reads a modified file back into
    catalog data -- the projection is generated from `src/skills/`, never
    imported from disk -- so an edited file is reported and then replaced by the
    next `omh update`, not adopted.
    """
    if not manifest:
        return []
    modified: list[str] = []
    for record in manifest.get("skills", []):
        if not isinstance(record, dict):
            continue
        rel = str(record.get("path", ""))
        expected = str(record.get("sha256", ""))
        if not rel or not expected:
            continue
        path = skills_dir / rel
        if not path.is_file() or sha256_file(path) != expected:
            modified.append(rel)
    return sorted(modified)


def _next_action(projection: str, drift: str, registration: str) -> str:
    # Ordered by which repair has to happen first: content the operator edited
    # would be overwritten by an update, so it is named before the update.
    if drift == "locally_modified":
        return "Run `omh update --force` to replace locally modified managed skills, or keep the edits and accept drift."
    if projection in {"stale", "missing"}:
        return "Run `omh update` to regenerate the managed projection from this package's catalog."
    if registration == "not_registered":
        return "Run `omh setup` to register the managed skills directory with Hermes."
    if registration == "unknown":
        return "Run `omh doctor --hermes-home <the home the Hermes process uses>` to read its config."
    return "No repair needed. Hermes runtime use stays unobserved until a host observation records it."
