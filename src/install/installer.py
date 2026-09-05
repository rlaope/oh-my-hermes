from __future__ import annotations

import shutil
import sys
from pathlib import Path

from ..core.errors import OmhError
from ..converter import convert_from_dir, convert_references_from_dir
from ..local_store import atomic_write_text, read_json_object_result
from ..manifest import local_modifications, new_manifest, read_manifest, skill_records, write_manifest
from ..paths import (
    OmhPaths,
    command_entry_belongs_to_managed_install,
    managed_command_bin_dir,
    managed_command_current_dir,
    managed_command_generations_dir,
    managed_command_self_update_state_path,
    managed_command_filenames,
    managed_command_venv_dir,
)
from ..profiles.team import TEAM_PROFILE_SCHEMA_VERSION
from ..skills.catalog import omh_skill_display_name, omh_skill_install_path
from ..skill_pack import (
    CORE_PROFILE_SKILLS,
    SkillReferenceTemplate,
    SkillTemplate,
    builtin_skill_reference_templates,
    builtin_skill_templates,
)
from ..system.approval_tier import TIER_AUTO_ALLOWED, resolve_approval_tier
from ..system.security_posture import resolve_security_posture

SKILL_PROFILES = ("core", "full")
# The full catalog is the default: installing OMH means getting OMH, ULW
# engines included -- a fresh setup that silently withheld 90+ skills read as
# "ULW is broken" to the owner, not as a context optimisation. `--core` is the
# explicit opt-in for the lightweight footprint, and reconcile still shrinks
# to core only (CORE_SKILL_PROFILE below), decoupled from this default.
DEFAULT_SKILL_PROFILE = "full"
CORE_SKILL_PROFILE = "core"
CONTEXT_COST_WARNING_SCHEMA_VERSION = "omh_skill_profile_context_cost_warning/v1"
SKILL_PROFILE_STATE_SCHEMA_VERSION = "omh_skill_profile_state/v1"
SKILL_PROFILE_RECONCILE_SCHEMA_VERSION = "omh_skill_profile_reconcile/v1"
SKILL_PROFILE_RECONCILE_COMMAND = "omh skill-profile reconcile --to core"
SKILL_PROFILE_STATUS_COMMAND = "omh skill-profile status"
NON_DESTRUCTIVE_DEFAULT_NOTE = (
    "omh setup, install, and update never delete installed skills, so a full install keeps its "
    f"skills after the recorded profile changes; run `{SKILL_PROFILE_RECONCILE_COMMAND}` explicitly "
    "to shrink an existing full install."
)
RECONCILE_CONTEXT_COST_NOTE = (
    "Every installed skill adds per-turn context weight to every Hermes request, so an install that "
    "still carries full-only skills costs full-profile context even when the recorded profile is core."
)


def skill_directory_name(canonical: str) -> str:
    """Leaf directory a skill is installed under.

    The directory now matches the label a host shows, because they were visibly
    disagreeing: Hermes printed `Loading skill: ulw-process` and then
    `[Skill directory: .../.omh/skills/ultraprocess]`. The canonical name still
    owns routing keys, triggers, and CLI arguments - only where the files sit
    changes, so `visual-qa` keeps working as something a user types.

    The leaf sits under a category directory; see `skill_install_relative_dir`.
    """
    return omh_skill_display_name(canonical)


def skill_install_relative_dir(canonical: str) -> Path:
    """Skills-dir-relative install directory: `<category>/<label>`.

    Hermes reads a skill's dashboard category off the DIRECTORY it sits in, not
    off frontmatter, and only when the path relative to a configured skills dir
    has three or more parts. The flat `<skills_dir>/<label>/SKILL.md` layout has
    two, so every OMH skill showed up in the startup banner under "general".
    Nesting one level deeper is the whole fix; `hermes_skill_category` owns
    which group a skill lands in.

    This is the MANAGED INSTALL layout only. The repo's `skills/` tree stays
    flat because it is a different distribution surface: Hermes' tap lister
    (`tools/skills_hub.py::_list_skills_in_repo`) reads exactly one directory
    level under a tap path, so nesting the tap tree would hide every OMH skill
    from `hermes skills search` and `hermes skills browse`. Tap installs land in
    Hermes' own skills dir, which OMH does not own or register.
    """
    return Path(omh_skill_install_path(canonical))


def _write_skill(skills_dir: Path, template: SkillTemplate, force: bool = False, managed: bool = False) -> None:
    target_dir = skills_dir / skill_install_relative_dir(template.name)
    target_file = target_dir / "SKILL.md"
    if target_file.exists() and not managed:
        existing = target_file.read_text(encoding="utf-8")
        if existing != template.content and not _overwrite_allowed(force):
            raise OmhError(f"local skill differs, refusing to overwrite without --force: {target_file}")
    atomic_write_text(target_file, template.content)


def _write_skill_reference(
    skills_dir: Path,
    template: SkillReferenceTemplate,
    force: bool = False,
    managed: bool = False,
) -> None:
    target_file = skills_dir / skill_install_relative_dir(template.skill_name) / template.relative_path
    if target_file.exists() and not managed:
        existing = target_file.read_text(encoding="utf-8")
        if existing != template.content and not _overwrite_allowed(force):
            raise OmhError(f"local skill reference differs, refusing to overwrite without --force: {target_file}")
    atomic_write_text(target_file, template.content)


def _overwrite_allowed(force: bool) -> bool:
    """The DECISION for every installer overwrite/removal guard in this module.

    `force` is the caller's confirmation; `resolve_approval_tier` also folds
    in the active security posture, so `--force` stops overriding a local
    modification at all once `OMH_SECURITY=strict` is set
    (`installer_confirmation_override_available` in security_posture.py).
    """
    decision = resolve_approval_tier(
        "installer_overwrite_local_modification", confirmed=force, posture=resolve_security_posture()
    )
    return decision.tier == TIER_AUTO_ALLOWED


def install_skill_pack(
    paths: OmhPaths,
    *,
    source: str = "builtin",
    source_dir: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
    profile: str = DEFAULT_SKILL_PROFILE,
) -> dict:
    if profile not in SKILL_PROFILES:
        raise OmhError(f"unknown skill profile {profile!r}; choose one of {', '.join(SKILL_PROFILES)}")
    all_templates = convert_from_dir(source_dir) if source_dir else builtin_skill_templates()
    reference_templates = convert_references_from_dir(source_dir) if source_dir else builtin_skill_reference_templates()
    if source_dir:
        # A retired ULW engine copied from a stale tap or checkout fails with
        # the explicit migration error, never a silent install of a contract
        # the catalog no longer ships (#954 stage 5, plan Q3: no tombstones).
        from ..skills.catalog import retired_skill_migration_error

        for template in all_templates:
            migration_error = retired_skill_migration_error(template.name)
            if migration_error:
                raise OmhError(str(migration_error["message"]))
    # Profile filtering only applies to the packaged builtin catalog: an explicit
    # `source_dir` is a caller-scoped skill set, not the curated core/full catalog,
    # so every skill it names is installed regardless of `profile`.
    if source_dir or profile == "full":
        templates = all_templates
    else:
        # The profile decides what gets ADDED, never what gets REFRESHED. A skill
        # already on disk is refreshed whichever profile is recorded, because
        # `omh update` promising "updated" while leaving installed skills on an
        # older render is the same as lying: that is how an install ended up
        # serving `name: ultrawork` long after the catalog had moved to
        # `ulw-ultrawork`. Shedding full-only skills stays an explicit act -
        # `omh skill-profile reconcile --to core`.
        installed = _installed_skill_names(paths.skills_dir)
        refreshable = {
            template.name
            for template in all_templates
            if template.name in CORE_PROFILE_SKILLS
            or skill_directory_name(template.name) in installed
            # A pre-relabel install has the CANONICAL directory on disk and the
            # labelled one absent, so matching only the label dropped the skill
            # from refresh entirely: the labelled replacement was never
            # written, the relabel pruner then kept the old directory ("no
            # replacement yet"), and the host kept serving the stale pre-label
            # SKILL.md forever. The canonical name keeps it refreshable so one
            # update writes the labelled directory and prunes the old one.
            or template.name in installed
        }
        templates = [template for template in all_templates if template.name in refreshable]
        reference_templates = [
            template for template in reference_templates if template.skill_name in refreshable
        ]
    manifest = read_manifest(paths.manifest_path)
    modified = local_modifications(manifest, paths.skills_dir)
    if modified and not _overwrite_allowed(force):
        raise OmhError("local modifications detected; rerun with --force or resolve: " + ", ".join(modified))
    context_cost_warning = (
        _context_cost_warning(core_count=len(CORE_PROFILE_SKILLS), full_count=len(builtin_skill_templates()))
        if profile == "full"
        else None
    )
    if dry_run:
        result = {
            "dry_run": True,
            "skills_dir": str(paths.skills_dir),
            "skills": [template.name for template in templates],
            "source": source,
            "skill_profile": profile,
        }
        if context_cost_warning is not None:
            result["context_cost_warning"] = context_cost_warning
        return result
    paths.skills_dir.mkdir(parents=True, exist_ok=True)
    managed = manifest is not None
    for template in templates:
        _write_skill(paths.skills_dir, template, force=force, managed=managed)
    for template in reference_templates:
        _write_skill_reference(paths.skills_dir, template, force=force, managed=managed)
    pruned_skills = _prune_orphaned_skills(
        paths.skills_dir,
        manifest,
        {template.name for template in all_templates},
        force=force,
    )
    flat_layout = _prune_flat_layout_skill_directories(
        paths.skills_dir,
        manifest,
        {template.name for template in all_templates},
        force=force,
    )
    _remove_empty_category_directories(paths.skills_dir)
    records = skill_records(paths.skills_dir, source)
    manifest_data = new_manifest(source, paths.skills_dir, records)
    manifest_data["skill_profile"] = profile
    if context_cost_warning is not None:
        manifest_data["context_cost_warning"] = context_cost_warning
    manifest_data["pruned_skills"] = pruned_skills
    manifest_data["flat_layout_skills_removed"] = flat_layout["removed"]
    manifest_data["flat_layout_skills_retained"] = flat_layout["retained"]
    manifest_data["skill_profile_state"] = skill_profile_state(paths.skills_dir, manifest_data)
    manifest_data = _carry_installed_at_when_nothing_moved(manifest, manifest_data)
    write_manifest(paths.manifest_path, manifest_data)
    return manifest_data


def _carry_installed_at_when_nothing_moved(previous: dict | None, current: dict) -> dict:
    """Keep `installed_at` still when the install changed nothing.

    Every other manifest field is derived from the catalog and from disk, so
    `installed_at` is the only thing that can move on its own -- and `utc_now()`
    truncates it to whole seconds. Two installs of identical content therefore
    produced identical manifest BYTES only when both happened to land inside the
    same wall-clock second.

    That is a real product bug, not just a flaky test. `omh update` answers "did
    the workflow pack actually move?" by comparing `sha256_file(manifest_path)`
    against the recorded hash (`_workflow_content_status` in commands/setup.py),
    because on the preview channel the version does not move between updates.
    With a per-run timestamp in the hashed bytes, any rerun that crossed a
    second boundary reported a content change that never happened -- which is
    exactly the false claim that comparison exists to prevent. It reproduces on
    any platform by sleeping 1s between two installs; Windows CI hit it first
    only because the suite runs ~2.4x slower there, so the gap between the two
    installs' timestamps regularly spans a second.

    Recording when the installed content last changed, rather than when the
    installer last ran, makes the answer true. A real content move still
    refreshes the timestamp, because some other field moves with it.
    """
    if not previous:
        return current
    carried = previous.get("installed_at")
    if not isinstance(carried, str) or not carried:
        return current
    if _without_installed_at(current) != _without_installed_at(previous):
        return current
    return {**current, "installed_at": carried}


def _without_installed_at(manifest: dict) -> dict:
    return {key: value for key, value in manifest.items() if key != "installed_at"}


def _prune_flat_layout_skill_directories(
    skills_dir: Path,
    manifest: dict | None,
    catalog_names: set[str],
    *,
    force: bool,
) -> dict[str, list[str]]:
    """Drop a flat top-level skill directory once its categorized copy is in place.

    Two layout moves left directories behind, and both fail the same way.
    Skills first moved from `skills/<canonical>/` to `skills/<label>/`; they now
    move again to `skills/<category>/<label>/` so Hermes can read a dashboard
    category off the path. Installs are non-destructive, so each move wrote the
    new directories and left the old ones beside them: an observed machine went
    from 92 skills to 184 after the relabel, doubling the pack's per-turn
    context weight, and the manifest then reported every vanished old path as a
    local modification. A leftover flat copy after this move would double-register
    every skill in Hermes AND keep a "general" group in the banner, which is the
    exact symptom the categorized layout exists to remove.

    The safety rules match `_prune_orphaned_skills`: remove only a directory that
    is (a) named after a catalog skill under either spelling, (b) recorded in the
    prior manifest at its flat path, (c) already replaced by a categorized
    directory holding a SKILL.md, and (d) byte-identical to what the manifest
    recorded. Anything a user edited is kept and reported instead, unless
    ``force``.
    """
    if not manifest:
        return {"removed": [], "retained": []}
    modified = set(local_modifications(manifest, skills_dir))
    recorded_paths = {
        str(record.get("path", "")) for record in manifest.get("skills", []) if record.get("path")
    }
    canonical_by_directory: dict[str, str] = {}
    for name in sorted(catalog_names):
        canonical_by_directory[name] = name
        canonical_by_directory.setdefault(skill_directory_name(name), name)
    categories = {skill_install_relative_dir(name).parts[0] for name in catalog_names}
    removed: list[str] = []
    retained: list[str] = []
    for entry in sorted(skills_dir.iterdir(), key=lambda item: item.name):
        if not entry.is_dir() or entry.is_symlink():
            continue
        if not (entry / "SKILL.md").is_file():
            # A category directory, or something with no skill at this level.
            continue
        canonical = canonical_by_directory.get(entry.name)
        if canonical is None:
            # Not a catalog skill; `_prune_orphaned_skills` owns that decision.
            continue
        rel = f"{entry.name}/SKILL.md"
        if rel not in recorded_paths:
            # Nothing in the manifest explains this file, so OMH did not install it.
            continue
        if not (skills_dir / skill_install_relative_dir(canonical) / "SKILL.md").is_file():
            # Nothing to fall back on yet; never leave the skill uninstalled.
            retained.append(canonical)
            continue
        if rel in modified and not force:
            retained.append(canonical)
            continue
        _remove_flat_skill_payload(entry, is_category_dir=entry.name in categories)
        removed.append(canonical)
    return {"removed": sorted(removed), "retained": sorted(retained)}


def _remove_flat_skill_payload(entry: Path, *, is_category_dir: bool) -> None:
    """Remove a flat skill directory without taking a category directory with it.

    One directory name is both: `ultrawork` was the pre-relabel canonical
    directory for the ULW engine AND is now the category every ULW skill installs
    under, so `skills/ultrawork/` can legitimately hold `SKILL.md` (stale) beside
    `ulw-work/SKILL.md` (current). Removing the tree would delete the skills that
    were just written, so for a category directory only the flat payload goes:
    the SKILL.md at that level and the `references/` beside it.
    """
    if not is_category_dir:
        shutil.rmtree(entry)
        return
    (entry / "SKILL.md").unlink()
    references = entry / "references"
    if references.is_dir() and not references.is_symlink():
        shutil.rmtree(references)


def _remove_empty_category_directories(skills_dir: Path) -> None:
    """Drop a category directory that pruning emptied, so no bare group is listed."""
    if not skills_dir.is_dir():
        return
    for entry in sorted(skills_dir.iterdir(), key=lambda item: item.name):
        if not entry.is_dir() or entry.is_symlink():
            continue
        if any(entry.iterdir()):
            continue
        entry.rmdir()


def _installed_skill_names(skills_dir: Path) -> set[str]:
    """Skill directory names already present, whatever profile put them there.

    Read from disk rather than the manifest on purpose: a core-profile manifest
    records only the core skills, so the full-only directories beside them are
    exactly the ones the manifest cannot see and the ones that were going stale.

    Both layouts are read. A flat directory left by an older release still names
    an installed skill, and dropping it from the refresh set is what once left a
    host serving a stale pre-relabel SKILL.md forever.
    """
    if not skills_dir.is_dir():
        return set()
    names: set[str] = set()
    for entry in skills_dir.iterdir():
        if not entry.is_dir() or entry.is_symlink():
            continue
        if (entry / "SKILL.md").is_file():
            names.add(entry.name)
        for child in entry.iterdir():
            if child.is_dir() and not child.is_symlink() and (child / "SKILL.md").is_file():
                names.add(child.name)
    return names



def _prune_orphaned_skills(
    skills_dir: Path,
    manifest: dict | None,
    catalog_names: set[str],
    *,
    force: bool,
) -> list[str]:
    """Remove managed skill dirs recorded in the prior manifest that the full catalog no longer ships.

    ``catalog_names`` must be the FULL ``builtin_skill_templates()`` catalog, never the
    profile-filtered install set, so a full->core reinstall does not shed full-only skills.
    A dir is pruned only when it is (a) recorded in the prior manifest, (b) absent from the
    full catalog, and (c) sha-unmodified vs. the manifest; user-modified dirs are kept unless
    ``force``. Removed directory names are returned so the caller can surface them.
    """
    if not manifest:
        return []
    modified = set(local_modifications(manifest, skills_dir))
    removed: list[str] = []
    for record in manifest.get("skills", []):
        name = record.get("name")
        rel = record.get("path")
        if not name or not rel or name in catalog_names:
            continue
        if str(rel) in modified and not force:
            continue
        # The manifest-recorded path, not the catalog name: the two differ under
        # both the display-label and the category layout, and only the recorded
        # path names the directory that actually exists.
        target_dir = skills_dir / Path(str(rel)).parent
        if not target_dir.is_dir() or target_dir.is_symlink() or target_dir == skills_dir:
            continue
        shutil.rmtree(target_dir)
        removed.append(name)
    return removed


def _context_cost_warning(*, core_count: int, full_count: int) -> dict:
    extra_count = max(full_count - core_count, 0)
    return {
        "schema_version": CONTEXT_COST_WARNING_SCHEMA_VERSION,
        "profile": "full",
        "installed_skill_count": full_count,
        "core_profile_skill_count": core_count,
        "extra_skill_count": extra_count,
        "message": (
            f"full profile installs all {full_count} packaged skills, {extra_count} more than the "
            f"{core_count}-skill core default; every installed skill adds per-turn context weight to "
            "every Hermes request, so prefer core unless this workspace genuinely needs the complete catalog."
        ),
    }


def _all_catalog_skill_names() -> list[str]:
    return [template.name for template in builtin_skill_templates()]


def installed_skill_names(skills_dir: Path) -> list[str]:
    """Names of skill directories that currently hold a SKILL.md under ``skills_dir``."""
    if not skills_dir.is_dir():
        return []
    # Directories carry display labels; every caller reasons in canonical names
    # (CORE_PROFILE_SKILLS, manifests, capability ids), so translate back here
    # rather than leaving each caller to guess which namespace it is holding.
    canonical_by_directory = {
        skill_directory_name(name): name for name in _all_catalog_skill_names()
    }
    names = {
        canonical_by_directory.get(directory.name, directory.name)
        for directory in installed_skill_directories(skills_dir)
    }
    return sorted(names)


def installed_skill_directories(skills_dir: Path) -> list[Path]:
    """Every directory holding a SKILL.md, under the category layout or flat.

    Flat directories are still counted because an install that predates the
    category layout has them and is still an install; the migration prunes them
    once the categorized copy exists.
    """
    if not skills_dir.is_dir():
        return []
    found: list[Path] = []
    for entry in sorted(skills_dir.iterdir(), key=lambda item: item.name):
        if not entry.is_dir() or entry.is_symlink():
            continue
        if (entry / "SKILL.md").is_file():
            found.append(entry)
        found.extend(
            child
            for child in sorted(entry.iterdir(), key=lambda item: item.name)
            if child.is_dir() and not child.is_symlink() and (child / "SKILL.md").is_file()
        )
    return found


def _skill_index_line_bytes(skill_file: Path) -> int:
    text = skill_file.read_text(encoding="utf-8")
    name = skill_file.parent.name
    description = ""
    if text.startswith("---\n"):
        frontmatter = text.split("---\n", 2)[1]
        for line in frontmatter.splitlines():
            key, separator, value = line.partition(":")
            if not separator:
                continue
            if key.strip() == "name":
                name = value.strip().strip("\"'")
            elif key.strip() == "description":
                description = value.strip().strip("\"'")
    line = f"    - {name}: {description}" if description else f"    - {name}"
    return len(line.encode("utf-8"))


def _skill_prompt_cost(
    skills_dir: Path,
    core_names: set[str],
    full_only_names: set[str],
) -> dict[str, object]:
    fixed_index_bytes = 0
    core_fixed_index_bytes = 0
    full_only_fixed_index_bytes = 0
    installed_skill_body_bytes = 0
    for skill_dir in installed_skill_directories(skills_dir):
        skill_file = skill_dir / "SKILL.md"
        bytes_count = _skill_index_line_bytes(skill_file)
        fixed_index_bytes += bytes_count
        installed_skill_body_bytes += skill_file.stat().st_size
        canonical_name = next(
            (
                name
                for name in core_names | full_only_names
                if skill_directory_name(name) == skill_file.parent.name
            ),
            skill_file.parent.name,
        )
        if canonical_name in core_names:
            core_fixed_index_bytes += bytes_count
        elif canonical_name in full_only_names:
            full_only_fixed_index_bytes += bytes_count
    return {
        "schema_version": "omh_skill_prompt_cost_estimate/v1",
        "evidence_status": "prepared_estimate_not_host_observed",
        "estimated_index_line_bytes": fixed_index_bytes,
        "core_fixed_index_bytes": core_fixed_index_bytes,
        "full_only_fixed_index_bytes": full_only_fixed_index_bytes,
        "installed_skill_body_bytes": installed_skill_body_bytes,
        "observation_command": "hermes prompt-size --json",
        "claim_boundary": (
            "These are OMH-local filesystem estimates, not observed serialized request bytes, "
            "selected skill bodies, provider input tokens, or cache counters. Use "
            "`hermes prompt-size --json` for host-observed prompt accounting."
        ),
    }


def skill_profile_state(skills_dir: Path, manifest: dict | None) -> dict:
    """Describe requested vs. effective profile so status output cannot claim a footprint it does not have.

    ``requested_profile`` is the profile the last install recorded; ``effective_profile`` is derived
    from the skill directories that actually exist on disk. They diverge whenever a full install is
    reinstalled as core, because installs are non-destructive by design.
    """
    catalog_names = {template.name for template in builtin_skill_templates()}
    core_names = set(CORE_PROFILE_SKILLS)
    installed = installed_skill_names(skills_dir)
    installed_catalog = [name for name in installed if name in catalog_names]
    full_only_installed = sorted(name for name in installed_catalog if name not in core_names)
    requested = str((manifest or {}).get("skill_profile") or "")
    if not installed_catalog:
        effective = "none"
    elif catalog_names.issubset(installed_catalog):
        effective = "full"
    elif not full_only_installed:
        effective = "core"
    else:
        effective = "mixed"
    retained_exception = bool(requested == "core" and full_only_installed)
    prompt_cost = _skill_prompt_cost(
        skills_dir,
        core_names,
        catalog_names - core_names,
    )
    return {
        "schema_version": SKILL_PROFILE_STATE_SCHEMA_VERSION,
        "requested_profile": requested,
        "effective_profile": effective,
        "matches_requested_profile": bool(requested) and effective == requested,
        "core_profile_skill_count": len(core_names),
        "full_profile_skill_count": len(catalog_names),
        "installed_skill_count": len(installed),
        "installed_catalog_skill_count": len(installed_catalog),
        "unmanaged_skill_count": len(installed) - len(installed_catalog),
        "full_only_installed_skills": full_only_installed,
        "retained_exception": retained_exception,
        "context_cost_note": RECONCILE_CONTEXT_COST_NOTE,
        "prompt_cost": prompt_cost,
        "non_destructive_default": NON_DESTRUCTIVE_DEFAULT_NOTE,
        "next_action": SKILL_PROFILE_RECONCILE_COMMAND if retained_exception else "",
    }


def _catalog_skill_files() -> dict[str, dict[str, str]]:
    """Rendered catalog content per skill: name -> {posix relative path: file content}."""
    files: dict[str, dict[str, str]] = {}
    for template in builtin_skill_templates():
        files.setdefault(template.name, {})["SKILL.md"] = template.content
    for template in builtin_skill_reference_templates():
        rel = Path(template.relative_path).as_posix()
        files.setdefault(template.skill_name, {})[rel] = template.content
    return files


def _installed_skill_dir(skills_dir: Path, canonical: str) -> Path | None:
    """Where a skill actually sits: the categorized directory, or a flat leftover.

    `ultrawork` names both a category and a pre-relabel skill directory, so this
    can return a path that is also a category root. Nothing here deletes it on
    that basis: the only caller that removes a directory (`_reconcile_plan` ->
    `reconcile_skill_profile`) first requires the directory's whole content to
    equal the rendered catalog templates, and a category root holding other
    skills never does.
    """
    for candidate in (
        skills_dir / skill_install_relative_dir(canonical),
        skills_dir / skill_directory_name(canonical),
        skills_dir / canonical,
    ):
        if (candidate / "SKILL.md").is_file() and not candidate.is_symlink():
            return candidate
    return None


def _installed_skill_files(skill_dir: Path) -> dict[str, str] | None:
    """Read every regular file under a skill dir; return None when anything is not plainly readable."""
    files: dict[str, str] = {}
    for path in sorted(skill_dir.rglob("*")):
        if path.is_symlink():
            return None
        if path.is_dir():
            continue
        if not path.is_file():
            return None
        try:
            files[path.relative_to(skill_dir).as_posix()] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
    return files


def _reconcile_plan(skills_dir: Path, manifest: dict) -> dict:
    """Split installed full-only skills into safely removable and retained-with-reason sets.

    A skill is removable only when it is OMH-managed (recorded in the install manifest) AND
    unmodified (every file under its directory is byte-identical to the rendered catalog
    templates, with no extra or missing files). Anything else is retained and reported.
    """
    catalog_files = _catalog_skill_files()
    core_names = set(CORE_PROFILE_SKILLS)
    managed_names = {
        str(record.get("name"))
        for record in manifest.get("skills", [])
        if isinstance(record, dict) and record.get("name")
    }
    removable: list[str] = []
    retained: list[dict[str, str]] = []
    for name in installed_skill_names(skills_dir):
        if name in core_names:
            continue
        expected = catalog_files.get(name)
        if expected is None:
            retained.append({"name": name, "reason": "not an OMH catalog skill"})
            continue
        if name not in managed_names:
            retained.append({"name": name, "reason": "no OMH install-manifest record; not OMH-managed"})
            continue
        installed_dir = _installed_skill_dir(skills_dir, name)
        actual = None if installed_dir is None else _installed_skill_files(installed_dir)
        if actual is None:
            retained.append({"name": name, "reason": "skill directory is not plainly readable managed content"})
            continue
        if actual != expected:
            retained.append({"name": name, "reason": "locally modified vs. the rendered catalog templates"})
            continue
        removable.append(name)
    return {"removable_skills": removable, "retained_skills": retained}


def skill_profile_report(paths: OmhPaths) -> dict:
    """Read-only requested/effective profile report plus the reconcile plan; mutates nothing."""
    manifest = read_manifest(paths.manifest_path)
    state = skill_profile_state(paths.skills_dir, manifest)
    plan = _reconcile_plan(paths.skills_dir, manifest or {})
    return {
        "schema_version": SKILL_PROFILE_STATE_SCHEMA_VERSION,
        "skills_dir": str(paths.skills_dir),
        "manifest_path": str(paths.manifest_path),
        "installed": manifest is not None,
        "profile_state": state,
        "reconcilable_skills": plan["removable_skills"],
        "retained_skills": plan["retained_skills"],
    }


def reconcile_skill_profile(
    paths: OmhPaths,
    *,
    target_profile: str = CORE_SKILL_PROFILE,
    dry_run: bool = False,
) -> dict:
    """Explicitly shrink an existing install down to the core profile.

    This is the only OMH path that deletes managed skill directories, and it never runs as part of
    setup/install/update. It removes only unmodified managed full-only skills; locally modified and
    non-managed directories stay on disk and are reported as retained exceptions.
    """
    if target_profile != CORE_SKILL_PROFILE:
        raise OmhError(
            f"skill profile reconcile only shrinks to {CORE_SKILL_PROFILE!r}; "
            "install the wider catalog with `omh install --full` instead"
        )
    manifest = read_manifest(paths.manifest_path)
    if manifest is None:
        raise OmhError(f"no OMH skill manifest at {paths.manifest_path}; run `omh setup` first")
    plan = _reconcile_plan(paths.skills_dir, manifest)
    result = {
        "schema_version": SKILL_PROFILE_RECONCILE_SCHEMA_VERSION,
        "target_profile": target_profile,
        "dry_run": dry_run,
        "skills_dir": str(paths.skills_dir),
        "profile_state_before": skill_profile_state(paths.skills_dir, manifest),
        "retained_skills": plan["retained_skills"],
        "context_cost_note": RECONCILE_CONTEXT_COST_NOTE,
        "non_destructive_default": NON_DESTRUCTIVE_DEFAULT_NOTE,
    }
    if dry_run:
        result["would_remove_skills"] = plan["removable_skills"]
        result["removed_skills"] = []
        return result

    removed: list[str] = []
    for name in plan["removable_skills"]:
        target_dir = _installed_skill_dir(paths.skills_dir, name)
        if target_dir is None or not target_dir.is_dir():
            continue
        shutil.rmtree(target_dir)
        removed.append(name)
    _remove_empty_category_directories(paths.skills_dir)
    source = str(manifest.get("source") or "builtin")
    records = skill_records(paths.skills_dir, source)
    manifest_data = new_manifest(source, paths.skills_dir, records)
    manifest_data["skill_profile"] = target_profile
    manifest_data["reconciled_skills"] = removed
    manifest_data["skill_profile_state"] = skill_profile_state(paths.skills_dir, manifest_data)
    write_manifest(paths.manifest_path, manifest_data)
    result["removed_skills"] = removed
    result["profile_state_after"] = manifest_data["skill_profile_state"]
    return result


def uninstall_skill_pack(
    paths: OmhPaths,
    *,
    remove_files: bool = False,
    remove_all: bool = False,
    dry_run: bool = False,
    force: bool = False,
    remove_command_package: bool = False,
) -> dict:
    """Remove OMH-managed local files without deleting unrelated Hermes state."""
    removed: list[str] = []
    would_remove: list[str] = []
    kept: list[dict[str, str]] = []

    if remove_all:
        _collect_removal(
            paths.hermes_plugin_dir,
            removed=removed,
            would_remove=would_remove,
            kept=kept,
            dry_run=dry_run,
            force=force,
            managed_plugin=True,
        )
        for team_file in _managed_team_profile_files(paths):
            _collect_removal(
                team_file,
                removed=removed,
                would_remove=would_remove,
                kept=kept,
                dry_run=dry_run,
                force=force,
            )

    if remove_files or remove_all:
        _collect_removal(paths.omh_home, removed=removed, would_remove=would_remove, kept=kept, dry_run=dry_run, force=True)

    command_removed_at = len(removed)
    command_would_remove_at = len(would_remove)
    command_kept_at = len(kept)
    if remove_command_package:
        _collect_command_package_removal(
            removed=removed,
            would_remove=would_remove,
            kept=kept,
            dry_run=dry_run,
        )
    command_removed = removed[command_removed_at:]
    command_would_remove = would_remove[command_would_remove_at:]
    command_kept = kept[command_kept_at:]

    return {
        "schema_version": "omh_uninstall/v1",
        "removed_files": bool(removed),
        "remove_files": remove_files or remove_all,
        "remove_all": remove_all,
        "dry_run": dry_run,
        "omh_home": str(paths.omh_home),
        "plugin_dir": str(paths.hermes_plugin_dir),
        "team_agents_dir": str(paths.hermes_agents_dir),
        "removed_paths": removed,
        "would_remove": would_remove,
        "kept_paths": kept,
        "command_package_remove_requested": remove_command_package,
        "command_package_removed": bool(command_removed),
        "command_package_removed_paths": command_removed,
        "command_package_would_remove": command_would_remove,
        "command_package_kept": command_kept,
    }


def uninstall_profile_plugin(paths: OmhPaths, *, dry_run: bool = False, force: bool = False) -> dict:
    """Remove only a bot-profile home's managed plugin directory.

    Profile homes share the primary's omh_home, so this must never route
    through uninstall_skill_pack's remove_all branches: those also collect the
    shared ~/.omh (and would double-list it in a dry run). Only the plugin directory
    is per-profile state, and it goes through the same manifest checked removal the
    primary uses -- a directory OMH cannot prove ownership of is kept unless --force,
    exactly as for the primary.
    """
    removed: list[str] = []
    would_remove: list[str] = []
    kept: list[dict[str, str]] = []
    _collect_removal(
        paths.hermes_plugin_dir,
        removed=removed,
        would_remove=would_remove,
        kept=kept,
        dry_run=dry_run,
        force=force,
        managed_plugin=True,
    )
    return {
        "removed_paths": removed,
        "would_remove": would_remove,
        "kept_paths": kept,
    }


def _collect_removal(
    path: Path,
    *,
    removed: list[str],
    would_remove: list[str],
    kept: list[dict[str, str]],
    dry_run: bool,
    force: bool,
    managed_plugin: bool = False,
) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if managed_plugin and not _looks_like_managed_plugin(path):
        decision = resolve_approval_tier(
            "installer_remove_unowned_plugin_dir", confirmed=force, posture=resolve_security_posture()
        )
        if decision.tier != TIER_AUTO_ALLOWED:
            kept.append({"path": str(path), "reason": "plugin dir is not an OMH-managed bundle; rerun with --force to remove it"})
            return
    if dry_run:
        would_remove.append(str(path))
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
    removed.append(str(path))


def _looks_like_managed_plugin(path: Path) -> bool:
    return (path / ".omh-plugin-manifest.json").exists()


def _collect_command_package_removal(
    *,
    removed: list[str],
    would_remove: list[str],
    kept: list[dict[str, str]],
    dry_run: bool,
) -> None:
    venv_dir = managed_command_venv_dir()
    if venv_dir is None:
        kept.append({"path": "omh", "reason": "no home directory is available, so the installer-managed command venv cannot be located"})
        return
    executable = Path(sys.executable).expanduser()
    if not _is_relative_to_without_resolving_symlinks(executable, venv_dir):
        kept.append(
            {
                "path": str(executable.resolve()),
                "reason": "current omh command is not running from the installer-managed OMH venv",
            }
        )
        return

    for link in _managed_command_links(venv_dir):
        _collect_removal(link, removed=removed, would_remove=would_remove, kept=kept, dry_run=dry_run, force=True)
    # Generation metadata is installer-owned only after attribution above has
    # proved this command is ours; `_collect_removal` unlinks pointer links.
    for path in (managed_command_current_dir(), managed_command_generations_dir(), managed_command_self_update_state_path()):
        if path is not None:
            _collect_removal(path, removed=removed, would_remove=would_remove, kept=kept, dry_run=dry_run, force=True)
    state_path = managed_command_self_update_state_path()
    if state_path is not None:
        _collect_removal(state_path.with_name(f".{state_path.name}.lock"), removed=removed, would_remove=would_remove, kept=kept, dry_run=dry_run, force=True)
    _collect_removal(venv_dir, removed=removed, would_remove=would_remove, kept=kept, dry_run=dry_run, force=True)


def _managed_command_links(venv_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    bin_dir = managed_command_bin_dir()
    if bin_dir is not None:
        candidates.extend(bin_dir / name for name in managed_command_filenames())
    which = shutil.which("omh")
    if which:
        candidates.append(Path(which))
    if sys.argv and sys.argv[0]:
        candidates.append(Path(sys.argv[0]))

    links: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        path = candidate.expanduser()
        if path in seen or not command_entry_belongs_to_managed_install(path):
            continue
        seen.add(path)
        links.append(path)
    return links


def _managed_team_profile_files(paths: OmhPaths) -> list[Path]:
    manifest_files = _manifest_team_profile_files(paths)
    if manifest_files:
        return manifest_files
    return _legacy_managed_team_profile_files(paths)


def _manifest_team_profile_files(paths: OmhPaths) -> list[Path]:
    if not paths.team_profile_manifest_dir.exists():
        return []
    files: list[Path] = []
    seen: set[Path] = set()
    for manifest_path in sorted(paths.team_profile_manifest_dir.glob("*.json")):
        manifest, _error = read_json_object_result(manifest_path)
        if manifest is None or manifest.get("schema_version") != TEAM_PROFILE_SCHEMA_VERSION:
            continue
        for raw_path in manifest.get("files", []):
            if not isinstance(raw_path, str):
                continue
            path = Path(raw_path).expanduser().resolve()
            if path in seen or not _is_relative_to(path, paths.hermes_agents_dir):
                continue
            seen.add(path)
            files.append(path)
    return files


def _legacy_managed_team_profile_files(paths: OmhPaths) -> list[Path]:
    if not paths.hermes_agents_dir.exists():
        return []
    files: list[Path] = []
    for path in sorted(paths.hermes_agents_dir.glob("omh-*.md")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "schema_version: omh_team_profile_pack/v1" in text:
            files.append(path)
    return files


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _is_relative_to_without_resolving_symlinks(path: Path, parent: Path) -> bool:
    try:
        _normalize_without_final_symlink(path).relative_to(_normalize_without_final_symlink(parent))
    except ValueError:
        return False
    return True


def _normalize_without_final_symlink(path: Path) -> Path:
    expanded = path.expanduser()
    return expanded.parent.resolve() / expanded.name
