from __future__ import annotations

from collections.abc import Iterable
import os
import shutil
import sys
from pathlib import Path, PurePosixPath

from ..core.errors import OmhError
from ..converter import convert_from_dir, convert_references_from_dir, convert_support_from_dir
from ..hashutil import sha256_file, sha256_text
from .curator_ledger import (
    LedgerWrite,
    hermes_edit_still_on_disk,
    ledger_holds_copy,
    newest_write_to,
    read_ledger_writes,
    write_still_on_disk,
    writes_in_skill_dir,
    writes_under,
)
from .plugin_pack import host_managed_plugin
from .lifecycle_safety import command_runtime_owned, store_removal_plan
from .uninstall_safety import configured_link_reason, linked_removal_reason, unsafe_removal_reason
from ..local_store import atomic_write_text, discard_path, is_directory_link, read_json_object_result
from ..manifest import (
    local_modifications,
    new_manifest,
    read_manifest,
    same_directory,
    skill_records,
    write_manifest,
)
from ..paths import (
    OmhPaths,
    command_entry_belongs_to_managed_install,
    managed_command_bin_dir,
    managed_command_current_dir,
    managed_current_workflow_pack_dir,
    managed_command_generations_dir,
    managed_command_self_update_state_path,
    managed_command_filenames,
    managed_command_venv_dir,
    managed_command_venv_scripts_dir,
)
from ..profiles.team import TEAM_PROFILE_SCHEMA_VERSION
from ..skills.catalog import omh_skill_display_name, omh_skill_install_path
from ..skill_pack import (
    CORE_PROFILE_SKILLS,
    SKILL_PACKS,
    SKILL_PACK_NAMES,
    SkillReferenceTemplate,
    SkillTemplate,
    builtin_skill_reference_templates,
    builtin_skill_templates,
    builtin_skill_support_templates,
    core_with_packs_skill_names,
    resolve_skill_pack_names,
)
from .support_materialization import legacy_support_paths, preflight_support, write_support
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
    "Every installed skill adds an index line to every Hermes request and about 8k chars each time its "
    "body loads, and a loaded body stays in history until compaction, so an install that still carries "
    "full-only skills costs full-profile context weight even when the recorded profile is core."
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


def _manifest_describes(manifest: dict | None, skills_dir: Path) -> bool:
    """Whether ``manifest`` records the pack that lives in ``skills_dir``.

    Real paths on both sides: the legacy bootstrap generation reaches the old
    ``<omh_home>/skills`` through a directory link, and that is still the same
    pack. A manifest without a recorded directory predates generations and can
    only describe the one pack directory that existed then.
    """
    if not manifest:
        return False
    recorded = manifest.get("skills_dir")
    if not recorded:
        return True
    return os.path.realpath(str(recorded)) == os.path.realpath(str(skills_dir))


# The manifest record key that keeps a Hermes-edited skill kept on the next
# install. The ledger row that first proved the edit can be trimmed, and after
# a staged update it names a generation OMH has moved off, so the evidence
# travels with the record instead.
HERMES_EDIT_RECORD_KEY = "hermes_edit"
HERMES_EDIT_EVIDENCE_KEYS = ("actor", "ts", "action", "ledger")
# The render mark: the manifest record of a SKILL.md an install itself wrote
# carries the hash it wrote, and the manifest says that its records carry such
# marks. The manifest records every SKILL.md under the pack, so a record alone
# never proved OMH rendered a directory; the mark does, and only a marked
# record whose SKILL.md still has that hash may be pruned. A manifest written
# before marks existed has no flag and is pruned by the rule it was written
# under, once, after which the rewritten manifest carries marks.
RENDER_MARK_KEY = "rendered_sha256"
RENDER_MARKS_FLAG = "render_marks"
# On a `--force` entry whose loss list (`ledger_copy`, `discarded`) was built
# while some ledger could not be read: the list counts only what was read.
LEDGER_COPY_PARTIAL_KEY = "ledger_copy_partial"
# Every reason a pruner leaves a candidate directory in place. Each has its own
# summary line; the install result carries the reason itself.
PRUNE_SKIP_REASONS = (
    "not_rendered_by_omh",
    "changed_since_rendered",
    "ledger_unreadable",
    "not_an_omh_layout",
    "outside_the_skills_directory",
    "category_directory",
    "same_directory_as_a_rendered_skill",
)


def hermes_edited_skills(
    manifest: dict | None,
    paths: OmhPaths,
    *,
    overwritten: bool = False,
    writes: list[LedgerWrite] | None = None,
    stored_writes: list[LedgerWrite] | None = None,
    reference_templates: list[SkillReferenceTemplate] | None = None,
    catalog_names: set[str] | None = None,
) -> list[dict]:
    """Managed skills whose files on disk are what a Hermes skill edit left there.

    Hermes may edit a skill in `skills.external_dirs` in place -- its
    background self-improvement review does so unprompted -- and records every
    such write in its curator ledger (`install.curator_ledger`). Upstream's
    rule for the skills it installs itself is that an edited skill counts as
    locally modified and updates stop overwriting it. OMH holds its managed
    skills to the same rule: a skill a Hermes write still accounts for is kept
    as it is and reported, rather than refusing the whole install the way an
    unexplained change does, or being stranded in the generation the edit
    happened in. `--force` keeps its meaning and replaces it, and the report
    says that it did.

    Rule: a skill counts as Hermes-edited only while the ledger accounts for
    what is on disk, file by file where the manifest can tell:
      - SKILL.md differs from its manifest record: kept only when the newest
        ledger write to that very SKILL.md left exactly the content it holds
        now. Otherwise the difference is a person's hand edit -- even beside a
        ledgered write to a supporting file -- and keeps its existing contract
        (refuse the install until `--force`).
      - SKILL.md matches its record: kept when a ledger write to any file of
        the skill (a supporting file, which the manifest never hashed) left
        what that file holds now, or removed a file OMH renders for the skill
        that is still absent. An absent file OMH never renders is not counted:
        a `write_file` undone by a `remove_file` leaves exactly OMH's render.
    Only a record at the directory an install renders for its name counts
    (`render_record_dir`): the manifest also records a person's copy of a
    managed skill elsewhere in the pack under the same name.
    A row counts only the files whose hash it changed, so a row that lists a
    whole skill (Hermes before 0.21.4 did) does not make OMH's own files read
    as edits, and a row whose result was since replaced, by `--force` or a
    rollback, is history: counting it would hold the skill back from every
    later update. That narrows "differs from the manifest and/or the ledger
    names it" on purpose, and its cost is stated: a Hermes edit made while
    the ledger is switched off (`skills.ledger: false`) still refuses like a
    hand edit.

    A skill kept once stays kept while its SKILL.md is unchanged since, through
    the evidence its manifest record carries. Read against the pack the
    manifest describes, which on a staged update is the previous generation.
    A skill whose SKILL.md is gone is not an edit; the install renders it
    again (`missing_managed_skills`).

    When `overwritten`, each entry also names, in `ledger_copy`, the files of
    the skill whose current content Hermes' ledger still holds a copy of, so
    the report can say whether the replaced edit is recoverable from there.
    That is judged against `stored_writes`, every write the ledgers record
    (`read_ledger_writes` `every_write`), read here when not given.

    A Hermes edit under the skill's own label in a directory this release
    does not render it into -- an earlier release's directory after a move,
    or a same-name copy elsewhere in the pack -- is reported as `left_behind`
    and nothing else: it is not kept (nothing is skipped for it), not carried,
    and not cleared. Unreported, it would vanish with the generation it sits in.
    """
    if not manifest:
        return []
    pack = manifest_pack(manifest, paths)
    if writes is None:
        writes = read_ledger_writes(paths.hermes_home, within=[pack])[0]
    pack_writes = writes_under(writes, pack)
    rendered = rendered_skill_files(reference_templates)
    catalog = {template.name for template in builtin_skill_templates()} if catalog_names is None else catalog_names
    found: list[dict] = []
    for record in manifest.get("skills", []):
        if not isinstance(record, dict):
            continue
        name, rel = str(record.get("name", "")), str(record.get("path", ""))
        if not name:
            continue
        if render_record_dir(name, rel) is None:
            left = _left_behind_edit(record, pack, pack_writes, rendered, catalog)
            if left is not None:
                found.append(left)
            continue
        skill_file = pack / rel
        if not skill_file.is_file():
            continue
        skill_file_changed = sha256_file(skill_file) != record.get("sha256")
        evidence = record.get(HERMES_EDIT_RECORD_KEY)
        if not (isinstance(evidence, dict) and not skill_file_changed):
            if skill_file_changed:
                write = newest_write_to(skill_file.parent, "SKILL.md", pack_writes)
                if write is None or not write_still_on_disk(write):
                    continue
            else:
                write = hermes_edit_still_on_disk(skill_file.parent, pack_writes, rendered.get(name, _SKILL_FILE_ONLY))
                if write is None:
                    continue
            evidence = _write_evidence(write)
        if overwritten and stored_writes is None:
            # By content across every generation, so read without the pack cut.
            stored_writes = read_ledger_writes(paths.hermes_home)[0]
        found.append(_hermes_edit_item(name, rel, skill_file.parent, evidence, overwritten, stored_writes))
    return found


_SKILL_FILE_ONLY: frozenset[str] = frozenset({"SKILL.md"})


def manifest_pack(manifest: dict, paths: OmhPaths) -> Path:
    """The pack directory a manifest describes; one without a recorded directory predates generations."""
    recorded = manifest.get("skills_dir")
    return Path(str(recorded)) if recorded else paths.skills_dir


def render_record_dir(name: str, rel: str) -> Path | None:
    """The record's skill directory when it is the one an install renders for `name`, else None.

    The manifest records every SKILL.md it finds under the pack, so a person's
    copy of a managed skill (`my-backups/omh-routing/SKILL.md`) carries the
    same canonical name as the skill itself. Nothing an install keeps, carries,
    replaces, or restores as a Hermes edit may follow such a record. The
    equality with the render path is what contains it: an absolute path or one
    climbing out with `..` can never equal that path, so no separate check for
    them is made here.
    """
    path = PurePosixPath(rel)
    expected = PurePosixPath(skill_install_relative_dir(name).as_posix())
    return Path(*expected.parts) if path.name == "SKILL.md" and path.parent == expected else None


def render_categories(catalog_names: Iterable[str]) -> set[str]:
    """The category directories an install of this catalog renders skills under."""
    return {skill_install_relative_dir(name).parts[0] for name in catalog_names}


def omh_layout_dir(rel: str, categories: set[str]) -> Path | None:
    """The record's skill directory when it sits where an OMH release renders skills, else None.

    Two layouts ever existed: `<label>/SKILL.md` at the top of the pack, and
    `<category>/<label>/SKILL.md`. A directory anywhere else was not rendered
    by OMH, whatever the manifest recorded about it, and a path that is
    absolute or climbs out with `..` is not a layout at all.
    """
    path = PurePosixPath(rel)
    parts = path.parent.parts
    if path.is_absolute() or ".." in path.parts or path.name != "SKILL.md":
        return None
    if len(parts) == 1 or (len(parts) == 2 and parts[0] in categories):
        return Path(*parts)
    return None


def _left_behind_edit(
    record: dict,
    pack: Path,
    pack_writes: list[LedgerWrite],
    rendered: dict[str, frozenset[str]],
    catalog: set[str],
) -> dict | None:
    """A report-only entry for a Hermes edit in a directory this release does not render the skill into.

    The record names a catalog skill and sits under that skill's own label,
    but not at the directory this release renders for it: a release moved the
    skill, or it is a same-name copy elsewhere in the pack. Either way the
    skill renders at its own directory as usual and this one is left exactly
    as it is. Reported only when the edit is real -- kept evidence on the
    record, or a ledger write still on disk -- and only for a path that stays
    inside the pack.
    """
    name, rel = str(record.get("name", "")), str(record.get("path", ""))
    path = PurePosixPath(rel)
    if (
        name not in catalog
        or path.is_absolute()
        or ".." in path.parts
        or path.name != "SKILL.md"
        or path.parent.name != skill_directory_name(name)
    ):
        return None
    skill_dir = pack / Path(*path.parent.parts)
    if not (skill_dir / "SKILL.md").is_file():
        return None
    evidence = record.get(HERMES_EDIT_RECORD_KEY)
    if not isinstance(evidence, dict):
        write = hermes_edit_still_on_disk(skill_dir, pack_writes, rendered.get(name, _SKILL_FILE_ONLY))
        if write is None:
            return None
        evidence = _write_evidence(write)
    return {
        "name": name,
        "path": rel,
        "skill_dir": str(skill_dir),
        "disposition": "left_behind",
        **{key: str(evidence.get(key, "")) for key in HERMES_EDIT_EVIDENCE_KEYS},
    }


def rendered_skill_files(reference_templates: list[SkillReferenceTemplate] | None = None) -> dict[str, frozenset[str]]:
    """Skill name -> the skill-relative files an install renders for it: SKILL.md and its references."""
    templates = builtin_skill_reference_templates() if reference_templates is None else reference_templates
    rendered: dict[str, set[str]] = {}
    for template in [*templates, *builtin_skill_support_templates()]:
        rendered.setdefault(template.skill_name, {"SKILL.md"}).add(PurePosixPath(str(template.relative_path)).as_posix())
    return {name: frozenset(files) for name, files in rendered.items()}


def _write_evidence(write: LedgerWrite) -> dict[str, str]:
    return {"actor": write.actor, "ts": write.ts, "action": write.action, "ledger": write.ledger}


def _hermes_edit_item(
    name: str,
    rel: str,
    skill_dir: Path,
    evidence: dict,
    overwritten: bool,
    stored_writes: list[LedgerWrite] | None,
) -> dict:
    item = {
        "name": name,
        "path": rel,
        "skill_dir": str(skill_dir),
        "disposition": "replaced" if overwritten else "kept",
        **{key: str(evidence.get(key, "")) for key in HERMES_EDIT_EVIDENCE_KEYS},
    }
    if overwritten:
        item["ledger_copy"] = _ledger_copies(skill_dir, stored_writes or [])
    return item


def _force_replacements(
    hermes_edited: list[dict],
    paths: OmhPaths,
    install_names: set[str],
    writes: list[LedgerWrite],
    rendered: dict[str, frozenset[str]],
    stored_writes: list[LedgerWrite],
) -> tuple[list[dict], list[Path]]:
    """What `--force` replaces in the pack being written, and the skill directories it clears first.

    Every skill this install renders again whose render directory holds a
    Hermes write still on disk is cleared, including one a hand edit to its
    SKILL.md kept out of `hermes_edited` -- otherwise a file Hermes added
    would outlive `--force` and keep the skill on the next plain install. The
    directory cleared is always the render directory under this pack, never
    a path a manifest record names, and never one reached through a category
    directory that is a link out of the pack. Each entry names, in
    `discarded`, the files the clear removes that OMH does not render and
    Hermes' ledger holds no copy of: those are gone for good. `stored_writes`
    is every write the ledgers record, for what a copy is held of.
    """
    by_name = {str(item["name"]): item for item in hermes_edited if item["disposition"] == "replaced"}
    pack_writes = writes_under(writes, paths.skills_dir)
    real_pack = os.path.realpath(paths.skills_dir)
    replaced = list(hermes_edited)
    targets: list[Path] = []
    for name in sorted(install_names):
        relative = skill_install_relative_dir(name)
        target = paths.skills_dir / relative
        if os.path.realpath(target.parent) != os.path.join(real_pack, *relative.parent.parts):
            continue
        item = by_name.get(name)
        if item is None:
            write = hermes_edit_still_on_disk(target, pack_writes, rendered.get(name, _SKILL_FILE_ONLY))
            if write is None:
                continue
            item = _hermes_edit_item(
                name, f"{relative.as_posix()}/SKILL.md", target, _write_evidence(write), True, stored_writes
            )
            replaced.append(item)
        item["discarded"] = _discarded_for_good(target, rendered.get(name, _SKILL_FILE_ONLY), item["ledger_copy"])
        targets.append(target)
    return replaced, targets


def _discarded_for_good(skill_dir: Path, rendered: frozenset[str], ledger_copy: list[str]) -> list[str]:
    """Files a clear of `skill_dir` removes that no render writes back and no ledger blob holds."""
    if skill_dir.is_symlink() or not skill_dir.is_dir():
        # Only the link goes; what it points at is not this install's to remove.
        return []
    files = sorted(path.relative_to(skill_dir).as_posix() for path in skill_dir.rglob("*") if path.is_file())
    return [file for file in files if file not in rendered and file not in ledger_copy]


def _ledger_copies(skill_dir: Path, writes: list[LedgerWrite]) -> list[str]:
    """Files of the skill whose current content a ledger row wrote and Hermes still stores.

    By content, not path: a blob is keyed by its hash, and after a staged
    update the row names a generation the skill has since been copied out of.
    """
    stored = {write.sha256: write for write in writes if write.sha256}
    copies: list[str] = []
    for file in sorted(path for path in skill_dir.rglob("*") if path.is_file()):
        write = stored.get(sha256_file(file))
        if write is not None and ledger_holds_copy(write):
            copies.append(file.relative_to(skill_dir).as_posix())
    return copies


def profile_skill_names(
    skills_dir: Path,
    profile: str,
    catalog_names: list[str],
    *,
    packs: Iterable[str] = (),
) -> set[str]:
    """Canonical names an install of the packaged catalog renders into `skills_dir` under `profile`.

    `full` renders the whole catalog. Otherwise the profile (plus any requested
    layered packs) decides what gets ADDED, never what gets REFRESHED. A skill
    already on disk is refreshed whichever profile is recorded, because
    `omh update` promising "updated" while leaving installed skills on an older
    render is the same as lying: that is how an install ended up serving
    `name: ultrawork` long after the catalog had moved to `ulw-ultrawork`.
    Shedding full-only skills stays an explicit act -
    `omh skill-profile reconcile --to core`. `omh doctor` asks the same question
    to say what the next install does with a missing skill.
    """
    if profile == "full":
        return set(catalog_names)
    try:
        selected = set(core_with_packs_skill_names(tuple(packs)))
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    installed = _installed_skill_names(skills_dir) | _active_generation_skill_names(skills_dir)
    return {
        name
        for name in catalog_names
        if name in selected
        or skill_directory_name(name) in installed
        # A pre-relabel install has the CANONICAL directory on disk and the
        # labelled one absent, so matching only the label dropped the skill
        # from refresh entirely: the labelled replacement was never written,
        # the relabel pruner then kept the old directory ("no replacement
        # yet"), and the host kept serving the stale pre-label SKILL.md
        # forever. The canonical name keeps it refreshable so one update
        # writes the labelled directory and prunes the old one.
        or name in installed
    }


def missing_managed_skills(
    manifest: dict | None, skills_dir: Path, install_names: set[str]
) -> list[dict]:
    """Managed skills the manifest records whose SKILL.md is gone from the pack it describes.

    A removed skill holds no edit to keep, so it is not a reason to refuse the
    install: it is rendered again when this install carries it, and reported
    either way. One this install does not carry -- outside the skill profile,
    or dropped from the catalog -- stays uninstalled, and the report says so.
    """
    if not manifest:
        return []
    missing: list[dict] = []
    for record in manifest.get("skills", []):
        if not isinstance(record, dict):
            continue
        name, rel = str(record.get("name", "")), str(record.get("path", ""))
        if not name or render_record_dir(name, rel) is None or (skills_dir / rel).is_file():
            continue
        missing.append(
            {"name": name, "path": rel, "disposition": "restored" if name in install_names else "not_restored"}
        )
    return missing


def _carry_kept_skills(skills_dir: Path, kept: Iterable[dict]) -> None:
    """Put each kept skill into the pack being written when it lives in another one.

    A staged update renders into a fresh generation, so a skill kept in place
    would stay behind in the old one; copying it whole is what carries the
    edit forward. In the pack the manifest already describes, it is already
    where it belongs.
    """
    real_pack = os.path.realpath(skills_dir)
    for item in kept:
        relative = render_record_dir(str(item["name"]), str(item["path"]))
        if relative is None:
            continue
        source = Path(str(item["skill_dir"]))
        target = skills_dir / relative
        if os.path.realpath(source) == os.path.realpath(target):
            continue
        if os.path.realpath(target.parent) != os.path.join(real_pack, *relative.parent.parts):
            # A category directory linking out of the pack: not ours to replace.
            continue
        discard_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, symlinks=True)


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
    packs: Iterable[str] = (),
) -> dict:
    if profile not in SKILL_PROFILES:
        raise OmhError(f"unknown skill profile {profile!r}; choose one of {', '.join(SKILL_PROFILES)}")
    try:
        normalized_packs = resolve_skill_pack_names(tuple(packs))
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    paths = legacy_support_paths(paths)
    all_templates = convert_from_dir(source_dir) if source_dir else builtin_skill_templates()
    reference_templates = convert_references_from_dir(source_dir) if source_dir else builtin_skill_reference_templates()
    # Taken before any filtering: which files OMH renders for a skill does not
    # depend on whether this install renders that skill.
    rendered = rendered_skill_files(reference_templates)
    all_reference_templates = reference_templates
    support_templates = convert_support_from_dir(source_dir) if source_dir else builtin_skill_support_templates()
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
        refreshable = profile_skill_names(
            paths.skills_dir,
            profile,
            [template.name for template in all_templates],
            packs=normalized_packs,
        )
        templates = [template for template in all_templates if template.name in refreshable]
        reference_templates = [
            template for template in reference_templates if template.skill_name in refreshable
        ]
    manifest = read_manifest(paths.manifest_path)
    recorded_manifest = manifest
    # Read against the pack the manifest describes, before the check below
    # drops a manifest that describes another generation: that pack is where
    # a Hermes edit sits on a staged update, and it would otherwise be left
    # behind in a generation Hermes no longer loads.
    overwrite_allowed = _overwrite_allowed(force)
    install_names = {template.name for template in templates}
    pack = manifest_pack(manifest, paths) if manifest else paths.skills_dir
    # One ledger read per install, cut to the two packs it can concern. Only
    # the pruners act on the unread list: a removal is final, so whatever may
    # record a write and could not be read (a ledger, a line, the profile
    # list) keeps what they would otherwise remove. The result names it too,
    # and the summary names it beside any loss list. When a local change may be
    # overwritten, the same read also keeps every write, wherever it sits:
    # what a replaced or removed skill loses is judged by content against all
    # of them, since a row may name a generation the files were copied from.
    stored_writes: list[LedgerWrite] = []
    ledger_writes, unreadable_ledgers = (
        read_ledger_writes(
            paths.hermes_home,
            within=[pack, paths.skills_dir],
            fail_closed=True,
            every_write=stored_writes if overwrite_allowed else None,
        )
        if manifest
        else ([], [])
    )
    hermes_edited = hermes_edited_skills(
        manifest,
        paths,
        overwritten=overwrite_allowed,
        writes=ledger_writes,
        stored_writes=stored_writes,
        reference_templates=all_reference_templates,
        catalog_names={template.name for template in all_templates},
    )
    same_pack = _manifest_describes(manifest, paths.skills_dir)
    if not same_pack:
        # Carried into a new generation only when this install carries the
        # skill at all: a kept full-only skill does not ride into a core one.
        hermes_edited = [item for item in hermes_edited if item["name"] in install_names]
    kept = {str(item["path"]): item for item in hermes_edited if item["disposition"] == "kept"}
    # Reported only: the edit stays where it is and the skill renders as usual.
    left_behind = {str(item["path"]) for item in hermes_edited if item["disposition"] == "left_behind"}
    # A staged self-update renders the candidate pack into its own generation
    # directory while the home manifest still describes the generation that is
    # active. That manifest cannot witness local edits in a directory it never
    # recorded, so judging the candidate by it flagged every skill the catalog
    # had changed since the last install as a "local modification", refused the
    # post-activation re-entry, and rolled the whole update back.
    # Judged in the pack the manifest describes, before it is dropped: on a
    # staged update a skill removed from the active generation is rendered
    # into the new one, and that is still a restore worth reporting.
    missing = missing_managed_skills(manifest, pack, install_names)
    missing_paths = {str(item["path"]) for item in missing}
    if not same_pack:
        manifest = None
    # A Hermes edit is kept and reported, and a removed skill is rendered
    # again; any other change to a managed file still refuses the whole
    # install until `--force` says to replace it.
    # Manifest records are one per SKILL.md, so the only other files under a
    # kept skill's directory that `local_modifications` reports are its support
    # files; a kept skill is not rendered again, so they are not replaced.
    kept_directories = {PurePosixPath(rel).parent.as_posix() + "/" for rel in kept}
    # A SKILL.md already holding the bytes `_write_skill` is about to write
    # (`atomic_write_text` of the template, UTF-8, newline-stable) is not a
    # local change even when an older release recorded another hash (#2300).
    incoming = {
        f"{skill_install_relative_dir(template.name).as_posix()}/SKILL.md": sha256_text(template.content)
        for template in templates
    }
    modified = [
        rel
        for rel in local_modifications(manifest, paths.skills_dir, incoming=incoming)
        if rel not in kept and rel not in missing_paths and rel not in left_behind
        and not any(rel.startswith(directory) for directory in kept_directories)
    ]
    if modified and not overwrite_allowed:
        raise OmhError("local modifications detected; rerun with --force or resolve: " + ", ".join(modified))
    install_skill_list = [template.name for template in templates]
    force_targets: list[Path] = []
    if overwrite_allowed and same_pack:
        hermes_edited, force_targets = _force_replacements(
            hermes_edited, paths, install_names, ledger_writes, rendered, stored_writes
        )
    if unreadable_ledgers:
        _mark_partial_loss_lists(hermes_edited)
    kept_names = {str(item["name"]) for item in kept.values()}
    support_templates = [t for t in support_templates if t.skill_name in install_names - kept_names]
    support_current = preflight_support(paths.skills_dir, support_templates, manifest, overwrite=overwrite_allowed)
    templates = [template for template in templates if template.name not in kept_names]
    reference_templates = [template for template in reference_templates if template.skill_name not in kept_names]
    context_cost_warning = (
        _context_cost_warning(core_count=len(CORE_PROFILE_SKILLS), full_count=len(builtin_skill_templates()))
        if profile == "full"
        else None
    )
    if dry_run:
        result = {
            "dry_run": True,
            "skills_dir": str(paths.skills_dir),
            "skills": install_skill_list,
            "source": source,
            "skill_profile": profile,
        }
        if normalized_packs:
            result["skill_packs"] = list(normalized_packs)
        if context_cost_warning is not None:
            result["context_cost_warning"] = context_cost_warning
        if hermes_edited:
            result["hermes_edited_skills"] = hermes_edited
        if missing:
            result["restored_skills"] = missing
        if unreadable_ledgers:
            # A replaced edit's loss list counts only the ledgers that could be read.
            result["unreadable_ledgers"] = unreadable_ledgers
        return result
    paths.skills_dir.mkdir(parents=True, exist_ok=True)
    # `--force` replaces the whole skill, not just the files OMH renders: a
    # file Hermes added with `write_file` would otherwise survive the render
    # and read as a live edit on the next install. Only a skill this install
    # renders again is cleared, only its render directory, and only in the
    # pack being written; an older generation stays the rollback target it is.
    support_dirs = {paths.skills_dir / skill_install_relative_dir(t.skill_name) for t in support_templates}
    for target in force_targets:
        if target in support_dirs and (target / "toolkit").exists():
            # Existing native --force semantics clear curator additions, but a
            # companion toolkit may contain foreign files: never recursively delete it.
            for entry in target.iterdir():
                if entry.name != "toolkit":
                    discard_path(entry)
        else:
            discard_path(target)
    managed = manifest is not None
    for template in templates:
        _write_skill(paths.skills_dir, template, force=force, managed=managed)
    for template in reference_templates:
        _write_skill_reference(paths.skills_dir, template, force=force, managed=managed)
    support_hashes = write_support(paths.skills_dir, support_current, manifest, rendered_names={t.name for t in templates})
    _carry_kept_skills(paths.skills_dir, kept.values())
    if kept_names:
        from .support_materialization import support_records

        support_hashes.update({relative: digest for relative, digest in support_records(recorded_manifest).items()
                               if any(relative.startswith(skill_install_relative_dir(name).as_posix() + "/") for name in kept_names)})
    # The pruners act only on what the prior manifest records, so leaving a
    # kept skill, and an edit reported as left behind, out of the copy they
    # read is what keeps them off both: "stays" has to be true, with or
    # without `--force`.
    prune_manifest = (
        {
            **manifest,
            "skills": [
                record
                for record in manifest.get("skills", [])
                if record.get("path") not in kept and record.get("path") not in left_behind
            ],
        }
        if manifest
        else None
    )
    catalog_names = {template.name for template in all_templates}
    # `overwrite_allowed`, not `force`: under OMH_SECURITY=strict `--force`
    # no longer overrides a local change, and a changed retired skill is one.
    orphans_removed, prune_skipped, force_pruned = _prune_orphaned_skills(
        paths.skills_dir,
        prune_manifest,
        catalog_names,
        force=overwrite_allowed,
        stored_writes=stored_writes,
        writes=ledger_writes,
        ledger_unreadable=bool(unreadable_ledgers),
    )
    flat_layout = _prune_flat_layout_skill_directories(
        paths.skills_dir,
        prune_manifest,
        catalog_names,
        force=overwrite_allowed,
        stored_writes=stored_writes,
        writes=ledger_writes,
        ledger_unreadable=bool(unreadable_ledgers),
    )
    removed_directories = orphans_removed + flat_layout["removed"]
    prune_skipped = prune_skipped + flat_layout["skipped"]
    force_pruned = force_pruned + flat_layout["forced"]
    if unreadable_ledgers:
        _mark_partial_loss_lists(force_pruned)
    _remove_empty_category_directories(paths.skills_dir)
    records = skill_records(paths.skills_dir, source)
    manifest_data = new_manifest(source, paths.skills_dir, records)
    manifest_data["support_files"] = support_hashes
    for record in manifest_data["skills"]:
        if record["path"] in kept:
            record[HERMES_EDIT_RECORD_KEY] = {key: kept[record["path"]][key] for key in HERMES_EDIT_EVIDENCE_KEYS}
    _write_render_marks(
        manifest_data,
        recorded_manifest,
        rendered_paths={f"{skill_install_relative_dir(template.name).as_posix()}/SKILL.md" for template in templates},
    )
    # What a plain install over this manifest would leave in place, persisted
    # so the manifest says the same thing on every install over an unchanged
    # disk, and so the next install can tell a directory it has named before.
    standing = _standing_prune_skips(
        paths.skills_dir,
        manifest_data,
        catalog_names,
        withheld=set(kept) | left_behind,
        writes=ledger_writes,
        ledger_unreadable=bool(unreadable_ledgers),
    )
    previously_listed = {
        str(item.get("path", ""))
        for item in (recorded_manifest or {}).get("prune_skipped_skills", [])
        if isinstance(item, dict)
    }
    if hermes_edited:
        manifest_data["hermes_edited_skills"] = hermes_edited
    if missing:
        manifest_data["restored_skills"] = missing
    if standing:
        manifest_data["prune_skipped_skills"] = standing
    if force_pruned:
        manifest_data["force_pruned_skills"] = force_pruned
    if removed_directories:
        manifest_data["removed_skill_directories"] = removed_directories
    manifest_data["skill_profile"] = profile
    if normalized_packs:
        manifest_data["skill_packs"] = list(normalized_packs)
    if context_cost_warning is not None:
        manifest_data["context_cost_warning"] = context_cost_warning
    manifest_data["pruned_skills"] = [item["name"] for item in orphans_removed]
    manifest_data["flat_layout_skills_removed"] = sorted(item["name"] for item in flat_layout["removed"])
    manifest_data["flat_layout_skills_retained"] = flat_layout["retained"]
    manifest_data["skill_profile_state"] = skill_profile_state(paths.skills_dir, manifest_data)
    manifest_data = _carry_installed_at_when_nothing_moved(manifest, manifest_data)
    write_manifest(paths.manifest_path, manifest_data)
    reported = _reported_prune_skips(prune_skipped, standing, previously_listed)
    result = {key: value for key, value in manifest_data.items() if key != "prune_skipped_skills"}
    if reported:
        result["prune_skipped_skills"] = reported
    if unreadable_ledgers:
        # In the result only: the error text would move the manifest bytes.
        result["unreadable_ledgers"] = unreadable_ledgers
    return result


def _mark_partial_loss_lists(items: list[dict]) -> None:
    """Mark each entry carrying a loss list: a ledger could not be read, so the list counts only what was."""
    for item in items:
        if "ledger_copy" in item:
            item[LEDGER_COPY_PARTIAL_KEY] = True


def _standing_prune_skips(
    skills_dir: Path,
    manifest: dict,
    catalog_names: set[str],
    *,
    withheld: set[str],
    writes: list[LedgerWrite],
    ledger_unreadable: bool,
) -> list[dict]:
    """What a plain install over `manifest` would leave in place, by both pruners, without deleting anything."""
    candidate = {**manifest, "skills": [record for record in manifest["skills"] if record.get("path") not in withheld]}
    _removed, orphan_skips, _forced = _prune_orphaned_skills(
        skills_dir, candidate, catalog_names, force=False, writes=writes, ledger_unreadable=ledger_unreadable, remove=False
    )
    flat = _prune_flat_layout_skill_directories(
        skills_dir, candidate, catalog_names, force=False, writes=writes, ledger_unreadable=ledger_unreadable, remove=False
    )
    return sorted(orphan_skips + flat["skipped"], key=lambda item: (item["path"], item["reason"]))


def _reported_prune_skips(acted: list[dict], standing: list[dict], previously_listed: set[str]) -> list[dict]:
    """The directories this install left in place, for the result and the summary.

    What the pruners decided this time, plus what the manifest now lists for
    next time (a directory first recorded by this install). A
    `not_rendered_by_omh` entry says whether it is `newly_seen` -- not in the
    list the previous manifest carried -- which is what the summary names; the
    flag lives in the result only, never in the written manifest, or the
    manifest would change between two installs over an unchanged disk.
    """
    reported: list[dict] = []
    seen: set[str] = set()
    for item in [*acted, *standing]:
        if item["path"] in seen:
            continue
        seen.add(item["path"])
        entry = dict(item)
        if entry["reason"] == "not_rendered_by_omh":
            entry["newly_seen"] = entry["path"] not in previously_listed
        reported.append(entry)
    return reported


def _write_render_marks(manifest_data: dict, previous: dict | None, *, rendered_paths: set[str]) -> None:
    """Mark the records this install rendered, carry the marks it did not touch, and flag the manifest.

    A record this install wrote carries the hash now on disk, which is the
    hash it wrote. Any other record keeps the mark the previous manifest held
    for that path -- a kept skill, a skill the profile did not refresh, a
    retired skill not yet pruned -- so its mark still names what OMH last
    wrote there, not what the directory holds today. A record with neither is
    a directory OMH did not render and gets no mark.
    """
    carried = _render_marks(previous)
    previous_records = {
        str(record.get("path", "")): record for record in (previous or {}).get("skills", []) if isinstance(record, dict)
    }
    for record in manifest_data["skills"]:
        path = str(record.get("path", ""))
        if path in rendered_paths:
            record[RENDER_MARK_KEY] = record["sha256"]
            continue
        if path in carried:
            record[RENDER_MARK_KEY] = carried[path]
        # Kept-edit evidence on a record this install did not render (a skill
        # a release retired, say) stays while its SKILL.md is unchanged:
        # without it the edit would be judged by a ledger row that can be
        # trimmed.
        before = previous_records.get(path)
        if (
            HERMES_EDIT_RECORD_KEY not in record
            and before is not None
            and isinstance(before.get(HERMES_EDIT_RECORD_KEY), dict)
            and before.get("sha256") == record.get("sha256")
        ):
            record[HERMES_EDIT_RECORD_KEY] = dict(before[HERMES_EDIT_RECORD_KEY])
    manifest_data[RENDER_MARKS_FLAG] = True


def _carry_record_provenance(manifest_data: dict, previous: dict) -> None:
    """Carry render marks and kept-edit evidence into a manifest rewritten without rendering."""
    carried = _render_marks(previous)
    evidence = {
        str(record.get("path", "")): record
        for record in previous.get("skills", [])
        if isinstance(record, dict) and isinstance(record.get(HERMES_EDIT_RECORD_KEY), dict)
    }
    for record in manifest_data["skills"]:
        path = str(record.get("path", ""))
        if path in carried:
            record[RENDER_MARK_KEY] = carried[path]
        kept = evidence.get(path)
        if kept is not None and kept.get("sha256") == record.get("sha256"):
            record[HERMES_EDIT_RECORD_KEY] = dict(kept[HERMES_EDIT_RECORD_KEY])
    if previous.get(RENDER_MARKS_FLAG):
        manifest_data[RENDER_MARKS_FLAG] = True
    recorded = {str(record.get("path", "")) for record in manifest_data["skills"]}
    standing = [
        item
        for item in previous.get("prune_skipped_skills", [])
        if isinstance(item, dict) and str(item.get("path", "")) in recorded
    ]
    if standing:
        manifest_data["prune_skipped_skills"] = standing


def _render_marks(manifest: dict | None) -> dict[str, str]:
    return {
        str(record.get("path", "")): str(record[RENDER_MARK_KEY])
        for record in (manifest or {}).get("skills", [])
        if isinstance(record, dict) and isinstance(record.get(RENDER_MARK_KEY), str) and record[RENDER_MARK_KEY]
    }


def _render_mark_refusal(record: dict, skill_file: Path, writes: list[LedgerWrite], ledger_unreadable: bool) -> str:
    """Why a record of a marked manifest may not be pruned on a plain install, or "" when it may.

    Only a record carrying the render mark is OMH's to delete at all: an
    unmarked one is never removed, `--force` or not. A marked one is removed
    when nothing in it changed since OMH rendered it; one that changed is
    left on a plain install and removed only by `--force`, which is the
    person's consent to lose local changes to something OMH rendered.

    "Changed" is not the SKILL.md hash alone: the SKILL.md no longer has the
    hash OMH wrote, the record carries kept Hermes-edit evidence, or the
    ledger records any write to a file in the directory -- recorded, not
    still on disk, since a removal here is final: a file Hermes wrote and the
    person then edited by hand holds neither OMH's render nor Hermes' write.
    Judged by the SKILL.md alone, a Hermes write to a supporting file of a
    skill a release retired went with the directory on a plain install, and
    nothing said so.

    A ledger that exists and cannot be read may record such a write, so a
    directory with nothing else against it is `ledger_unreadable` rather than
    removed; a ledger that does not exist records nothing.
    """
    mark = record.get(RENDER_MARK_KEY)
    if not isinstance(mark, str) or not mark:
        return "not_rendered_by_omh"
    try:
        unchanged = skill_file.is_file() and sha256_file(skill_file) == mark
    except OSError:
        unchanged = False
    if not unchanged or isinstance(record.get(HERMES_EDIT_RECORD_KEY), dict):
        return "changed_since_rendered"
    if writes_in_skill_dir(skill_file.parent, writes):
        return "changed_since_rendered"
    if ledger_unreadable:
        return "ledger_unreadable"
    return ""


# The refusals `force` overrides: a directory OMH rendered that changed since,
# or one it cannot judge because the ledger could not be read.
_FORCE_REMOVES = frozenset({"changed_since_rendered", "ledger_unreadable"})


def _skip_item(name: object, rel: object, reason: str) -> dict:
    return {"name": str(name), "path": str(rel), "reason": reason}


def _force_pruned_item(
    name: object, rel: object, directory: Path, stored_writes: list[LedgerWrite], reason: str
) -> dict:
    """What `--force` loses by removing a marked directory a plain install leaves, and why it was left.

    Built before the directory goes: the files Hermes' ledger still holds a
    copy of (`stored_writes`, every write the ledgers record), and the rest,
    which are gone for good. When the ledger could not be read, neither is
    knowable, so neither is claimed.
    """
    item = {"name": str(name), "path": str(rel), "reason": reason}
    if reason == "ledger_unreadable":
        return item
    ledger_copy = _ledger_copies(directory, stored_writes)
    return {**item, "ledger_copy": ledger_copy, "discarded": _discarded_for_good(directory, frozenset(), ledger_copy)}


def _holds_other_skills(directory: Path, category_dirs: list[Path]) -> bool:
    """Whether `directory` is more than one skill's own directory.

    A category directory of this catalog, under any spelling, or any directory
    with a SKILL.md somewhere below its own. The first is asked separately
    because the second is false exactly where it matters: a category whose
    skills are all gone still holds whatever else was put there, and a stray
    `guide/SKILL.md` is no reason to remove `guide/`.
    """
    if any(same_directory(directory, category_dir) for category_dir in category_dirs):
        return True
    try:
        return any(skill_file.parent != directory for skill_file in directory.rglob("SKILL.md"))
    except OSError:
        return True


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
    stored_writes: list[LedgerWrite] | None = None,
    writes: list[LedgerWrite] | None = None,
    ledger_unreadable: bool = False,
    remove: bool = True,
) -> dict[str, list]:
    """Drop a flat top-level skill directory once its categorized copy is in place.

    Two layout moves left directories behind, and both fail the same way.
    Skills first moved from `skills/<canonical>/` to `skills/<label>/`; they now
    move again to `skills/<category>/<label>/` so Hermes can read a dashboard
    category off the path. Installs are non-destructive, so each move wrote the
    new directories and left the old ones beside them: an observed machine went
    from 92 skills to 184 after the relabel, doubling the pack's index lines
    and context weight, and the manifest then reported every vanished old path as a
    local modification. A leftover flat copy after this move would double-register
    every skill in Hermes AND keep a "general" group in the banner, which is the
    exact symptom the categorized layout exists to remove.

    The safety rules match `_prune_orphaned_skills`: remove only a directory that
    is (a) named after a catalog skill under either spelling, (b) recorded in the
    prior manifest at its flat path, (c) already replaced by a categorized
    directory holding a SKILL.md, and (d) OMH's to delete. Under a manifest
    that carries render marks, (d) means the record carries the mark and
    nothing in the directory changed since OMH rendered it, the same question
    the orphan pruner asks (`_render_mark_refusal`). An unmarked record is never
    removed, `--force` or not; a marked one that changed, or that cannot be
    judged because a ledger could not be read (``ledger_unreadable``), is left
    on a plain install and removed by ``force``, reported in `forced` with what
    that loses. Everything left is returned in `skipped` with the reason.
    Under a manifest written before marks existed, (d) is the rule it was
    written under: byte-identical to what the manifest recorded, with anything
    a user edited kept and reported in `retained` unless ``force``.

    Each removal is returned in `removed` as {name, path, rule, kind}: `rule`
    names the rule that admitted it (`render_mark`, or `earlier_manifest` for
    a manifest from before marks), and `kind` is `flat_copy` for a whole
    directory or `flat_copy_in_category` when the directory is also a
    category, where only its top-level SKILL.md and a real references/
    directory go and `removed_entries` names the ones that did.
    """
    if not manifest:
        return {"removed": [], "retained": [], "skipped": [], "forced": []}
    modified = set(local_modifications(manifest, skills_dir))
    marked = bool(manifest.get(RENDER_MARKS_FLAG))
    pack_writes = writes_under(writes or [], skills_dir)
    records_by_path = {
        str(record.get("path", "")): record
        for record in manifest.get("skills", [])
        if isinstance(record, dict) and record.get("path")
    }
    canonical_by_directory: dict[str, str] = {}
    for name in sorted(catalog_names):
        canonical_by_directory[name] = name
        canonical_by_directory.setdefault(skill_directory_name(name), name)
    categories = {skill_install_relative_dir(name).parts[0] for name in catalog_names}
    removed: list[dict] = []
    retained: list[str] = []
    skipped: list[dict] = []
    forced: list[dict] = []
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
        record = records_by_path.get(rel)
        if record is None:
            # Nothing in the manifest explains this file, so OMH did not install it.
            continue
        if not (skills_dir / skill_install_relative_dir(canonical) / "SKILL.md").is_file():
            # Nothing to fall back on yet; never leave the skill uninstalled.
            retained.append(canonical)
            continue
        if marked:
            reason = _render_mark_refusal(record, entry / "SKILL.md", pack_writes, ledger_unreadable)
            if reason and not (force and reason in _FORCE_REMOVES):
                skipped.append(_skip_item(canonical, rel, reason))
                continue
            if reason and remove:
                forced.append(_force_pruned_item(canonical, rel, entry, stored_writes or [], reason))
        elif rel in modified and not force:
            retained.append(canonical)
            continue
        if not remove:
            continue
        in_category = entry.name in categories
        removed_entries = _remove_flat_skill_payload(entry, is_category_dir=in_category)
        item = {
            "name": canonical,
            "path": rel,
            "rule": "render_mark" if marked else "earlier_manifest",
            "kind": "flat_copy_in_category" if in_category else "flat_copy",
        }
        if in_category:
            item["removed_entries"] = removed_entries
        removed.append(item)
    return {"removed": removed, "retained": sorted(retained), "skipped": skipped, "forced": forced}


def _remove_flat_skill_payload(entry: Path, *, is_category_dir: bool) -> list[str]:
    """Remove a flat skill directory without taking a category directory with it.

    One directory name is both: `ultrawork` was the pre-relabel canonical
    directory for the ULW engine AND is now the category every ULW skill installs
    under, so `skills/ultrawork/` can legitimately hold `SKILL.md` (stale) beside
    `ulw-work/SKILL.md` (current). Removing the tree would delete the skills that
    were just written, so for a category directory only the flat payload goes:
    the SKILL.md at that level and the `references/` beside it, when it is a
    real directory. Returns what went from a category directory, by name.
    """
    if not is_category_dir:
        shutil.rmtree(entry)
        return []
    (entry / "SKILL.md").unlink()
    references = entry / "references"
    if references.is_dir() and not references.is_symlink():
        shutil.rmtree(references)
        return ["SKILL.md", "references/"]
    return ["SKILL.md"]


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


def _active_generation_skill_names(skills_dir: Path) -> set[str]:
    """Skills the active generation serves, when ``skills_dir`` is a new one.

    A staged `omh update` renders into a fresh, empty candidate generation and
    only then switches the shared `current` pointer to it. Reading the refresh
    set from the candidate alone therefore saw nothing installed, so a core
    install silently lost every full-only skill it had kept (the nine ULW
    engines, for one) although update never narrows an install. The pack
    behind `current` is what the host serves right now, so it is the install
    this update has to carry forward.
    """
    # Only a pack inside a managed generation has a predecessor behind
    # `current`; a named `--omh-home` or project pack is its own install.
    generations = managed_command_generations_dir()
    current = managed_current_workflow_pack_dir()
    if generations is None or current is None or not current.is_dir():
        return set()
    try:
        if skills_dir.resolve().parent.parent != generations.resolve():
            return set()
        if current.resolve() == skills_dir.resolve():
            return set()
    except OSError:
        return set()
    return _installed_skill_names(current)


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
    stored_writes: list[LedgerWrite] | None = None,
    writes: list[LedgerWrite] | None = None,
    ledger_unreadable: bool = False,
    remove: bool = True,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Remove managed skill dirs recorded in the prior manifest that the full catalog no longer ships.

    ``catalog_names`` must be the FULL ``builtin_skill_templates()`` catalog, never the
    profile-filtered install set, so a full->core reinstall does not shed full-only skills.
    Each removed directory is returned first as {name, path, rule, kind}, `rule` naming the
    rule that admitted it (`render_mark`, or `earlier_manifest` for a manifest from before
    marks) and `kind` always `retired_skill`; every candidate left in place is returned
    second with the reason; third, what ``force`` lost for each changed directory it removed.
    ``writes`` are Hermes' ledger writes, for what "changed" means (`_render_mark_refusal`),
    ``stored_writes`` every write the ledgers record, for what a ``force`` removal loses,
    and ``ledger_unreadable`` says a ledger exists that could not be read, which leaves a
    marked directory with nothing else against it in place (`ledger_unreadable`) until
    ``force``; with ``remove`` false nothing is deleted and only the verdicts are returned.

    The rule is provenance. The manifest records every SKILL.md under the pack, not only
    what OMH rendered, so a record alone never made a directory OMH's to delete.

    - Under a manifest that carries render marks (`RENDER_MARKS_FLAG`): a directory is
      pruned only when its record (a) names a skill absent from the full catalog, (b)
      carries the render mark, and (c) nothing in it changed since OMH rendered it: its
      SKILL.md still has the hash OMH wrote, its record carries no kept Hermes-edit
      evidence, and the ledger records no write under it (`_render_mark_refusal`).
      Every other file in the directory goes with it. A record
      without the mark is a directory an install merely found (`not_rendered_by_omh`) and
      is never removed, ``force`` or not. A marked one whose SKILL.md changed
      (`changed_since_rendered`) is left on a plain install; ``force`` removes it, because
      the mark proves OMH rendered that path and ``force`` is the person's consent to lose
      local changes -- the same meaning it has for a live skill. Without that, a retired
      skill someone once touched would stay forever.
    - Under a manifest written before marks existed: the rule it was written under. (a),
      plus sha-unmodified vs. the manifest record unless ``force``; it does not know what
      OMH rendered and does not look for Hermes writes. This is what lets a retired skill
      be cleaned up once; the manifest this install writes carries marks.

    Whichever rule admitted the record, these still hold, as defence in depth: the
    directory sits where an OMH release renders skills (`omh_layout_dir`); it resolves
    strictly inside the skills directory; it is not a category directory or any directory
    holding other skills below it (a stray `guide/SKILL.md` must never take the category
    with it); and it is not, under another spelling, a directory this catalog renders a
    skill into (a case-insensitive filesystem).
    """
    if not manifest:
        return [], [], []
    modified = set(local_modifications(manifest, skills_dir))
    marked = bool(manifest.get(RENDER_MARKS_FLAG))
    pack_writes = writes_under(writes or [], skills_dir)
    categories = render_categories(catalog_names)
    real_skills_dir = os.path.realpath(skills_dir)
    category_dirs = [skills_dir / category for category in sorted(categories)]
    render_dirs = [skills_dir / skill_install_relative_dir(catalog_name) for catalog_name in sorted(catalog_names)]
    removed: list[dict] = []
    skipped: list[dict] = []
    forced: list[dict] = []
    for record in manifest.get("skills", []):
        name = record.get("name")
        rel = record.get("path")
        if not name or not rel or name in catalog_names:
            continue
        if marked and not isinstance(record.get(RENDER_MARK_KEY), str):
            skipped.append(_skip_item(name, rel, "not_rendered_by_omh"))
            continue
        if not marked and str(rel) in modified and not force:
            continue
        # The manifest-recorded path, not the catalog name: the two differ under
        # both the display-label and the category layout, and only the recorded
        # path names the directory that actually exists.
        relative = omh_layout_dir(str(rel), categories)
        if relative is None:
            skipped.append(_skip_item(name, rel, "not_an_omh_layout"))
            continue
        target_dir = skills_dir / relative
        if not target_dir.is_dir() or target_dir.is_symlink() or same_directory(target_dir, skills_dir):
            continue
        if not _strictly_inside(os.path.realpath(target_dir), real_skills_dir):
            skipped.append(_skip_item(name, rel, "outside_the_skills_directory"))
            continue
        if _holds_other_skills(target_dir, category_dirs):
            skipped.append(_skip_item(name, rel, "category_directory"))
            continue
        if any(same_directory(target_dir, render_dir) for render_dir in render_dirs):
            skipped.append(_skip_item(name, rel, "same_directory_as_a_rendered_skill"))
            continue
        if marked:
            reason = _render_mark_refusal(record, target_dir / "SKILL.md", pack_writes, ledger_unreadable)
            if reason and not (force and reason in _FORCE_REMOVES):
                skipped.append(_skip_item(name, rel, reason))
                continue
            if reason and remove:
                forced.append(_force_pruned_item(name, rel, target_dir, stored_writes or [], reason))
        if not remove:
            continue
        shutil.rmtree(target_dir)
        removed.append(
            {
                "name": str(name),
                "path": str(rel),
                "rule": "render_mark" if marked else "earlier_manifest",
                "kind": "retired_skill",
            }
        )
    return removed, skipped, forced


def _strictly_inside(real_path: str, real_root: str) -> bool:
    """Whether a resolved path lies below a resolved root, and is not the root itself."""
    try:
        return real_path != real_root and os.path.commonpath([real_path, real_root]) == real_root
    except ValueError:
        # Different drives.
        return False


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
            f"{core_count}-skill core default; every installed skill adds an index line to every Hermes "
            "request and about 8k chars each time its body loads (a loaded body stays in history until "
            "compaction), so this context weight grows with the catalog; prefer core unless this workspace "
            "genuinely needs the complete catalog."
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
    raw_packs = (manifest or {}).get("skill_packs", [])
    requested_packs = tuple(
        str(pack) for pack in raw_packs if isinstance(pack, str) and pack in SKILL_PACKS
    ) if isinstance(raw_packs, list) else ()
    target_names = set(core_with_packs_skill_names(requested_packs)) if requested_packs else core_names
    installed = installed_skill_names(skills_dir)
    installed_catalog = [name for name in installed if name in catalog_names]
    full_only_installed = sorted(name for name in installed_catalog if name not in core_names)
    outside_target = sorted(name for name in installed_catalog if name not in target_names)
    requested = str((manifest or {}).get("skill_profile") or "")
    if not installed_catalog:
        effective = "none"
    elif catalog_names.issubset(installed_catalog):
        effective = "full"
    elif not full_only_installed:
        effective = "core"
    elif requested == "core" and requested_packs and not outside_target and target_names.issubset(installed_catalog):
        effective = "core+packs"
    else:
        effective = "mixed"
    retained_exception = bool(requested == "core" and outside_target)
    prompt_cost = _skill_prompt_cost(
        skills_dir,
        core_names,
        catalog_names - core_names,
    )
    matches_requested = (
        bool(requested)
        and (
            effective == requested
            or (requested == "core" and bool(requested_packs) and effective == "core+packs")
        )
    )
    return {
        "schema_version": SKILL_PROFILE_STATE_SCHEMA_VERSION,
        "requested_profile": requested,
        "requested_packs": list(requested_packs),
        "available_packs": list(SKILL_PACK_NAMES),
        "effective_profile": effective,
        "matches_requested_profile": matches_requested,
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
    for template in [*builtin_skill_reference_templates(), *builtin_skill_support_templates()]:
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


def _reconcile_plan(skills_dir: Path, manifest: dict, *, packs: Iterable[str] = ()) -> dict:
    """Split installed full-only skills into safely removable and retained-with-reason sets.

    A skill is removable only when it is OMH-managed (recorded in the install manifest) AND
    unmodified (every file under its directory is byte-identical to the rendered catalog
    templates, with no extra or missing files). Anything else is retained and reported.
    """
    catalog_files = _catalog_skill_files()
    try:
        keep_names = set(core_with_packs_skill_names(tuple(packs)))
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    managed_names = {
        str(record.get("name"))
        for record in manifest.get("skills", [])
        if isinstance(record, dict) and record.get("name")
    }
    removable: list[str] = []
    retained: list[dict[str, str]] = []
    for name in installed_skill_names(skills_dir):
        if name in keep_names:
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
    plan = _reconcile_plan(paths.skills_dir, manifest or {}, packs=state.get("requested_packs", ()))
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
    packs: Iterable[str] = (),
    dry_run: bool = False,
) -> dict:
    """Explicitly shrink an existing install down to the core profile (plus any requested packs).

    This is the only OMH path that deletes managed skill directories, and it never runs as part of
    setup/install/update. It removes only unmodified managed full-only skills; locally modified and
    non-managed directories stay on disk and are reported as retained exceptions.
    """
    if target_profile != CORE_SKILL_PROFILE:
        raise OmhError(
            f"skill profile reconcile only shrinks to {CORE_SKILL_PROFILE!r}; "
            "install the wider catalog with `omh install --full` instead"
        )
    try:
        normalized_packs = resolve_skill_pack_names(tuple(packs))
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    manifest = read_manifest(paths.manifest_path)
    if manifest is None:
        raise OmhError(f"no OMH skill manifest at {paths.manifest_path}; run `omh setup` first")
    plan = _reconcile_plan(paths.skills_dir, manifest, packs=normalized_packs)
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
    if normalized_packs:
        result["target_packs"] = list(normalized_packs)
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
    # Reconcile must not adopt edited support or discard retained ownership.
    from .support_materialization import support_records, support_path

    manifest_data["support_files"] = {rel: digest for rel, digest in support_records(manifest).items() if support_path(paths.skills_dir, rel).is_file()}
    # Reconcile renders nothing, so every mark and every kept-edit record it
    # writes is one the manifest it replaces already held.
    _carry_record_provenance(manifest_data, manifest)
    manifest_data["skill_profile"] = target_profile
    if normalized_packs:
        manifest_data["skill_packs"] = list(normalized_packs)
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
    store_plan: dict[str, object] | None = None,
    home_refusal: str | None = None,
) -> dict:
    """Remove OMH-managed local files without deleting unrelated Hermes state.

    `home_refusal` is a caller's reason to keep `omh_home`: one only the caller
    can know, such as a configured spelling that resolution already erased.
    """
    removed: list[str] = []
    would_remove: list[str] = []
    kept: list[dict[str, str]] = []

    plan = store_plan or (store_removal_plan(paths, remove_profiles=remove_all) if remove_files or remove_all else {})
    blocked = bool(plan.get("failed"))
    if plan.get("status") == "kept":
        kept.append({"path": str(paths.omh_home), "reason": str(plan["reason"])})

    if remove_all and not blocked:
        _collect_removal(
            paths.hermes_plugin_dir,
            removed=removed,
            would_remove=would_remove,
            kept=kept,
            dry_run=dry_run,
            force=force,
            managed_plugin=True,
            boundary=paths.hermes_home,
        )
        for team_file in _managed_team_profile_files(paths):
            _collect_removal(
                team_file,
                removed=removed,
                would_remove=would_remove,
                kept=kept,
                dry_run=dry_run,
                force=force,
                managed_team_file=True,
                boundary=paths.hermes_agents_dir,
            )

    if (remove_files or remove_all) and plan.get("status") != "kept":
        reason = home_refusal or _omh_home_removal_refusal(paths)
        if reason:
            kept.append({"path": str(paths.omh_home), "reason": reason})
        else:
            _collect_omh_home_contents(paths, removed=removed, would_remove=would_remove, kept=kept, dry_run=dry_run)

    command_removed_at = len(removed)
    command_would_remove_at = len(would_remove)
    command_kept_at = len(kept)
    if remove_command_package and (plan.get("status") == "kept" or paths.hermes_home.parent.name == "profiles"):
        kept.append({"path": "omh", "reason": "shared command retained for other Hermes homes; remove it from the primary home only after detaching profiles"})
    elif remove_command_package:
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
        "store_removal": plan,
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
        boundary=paths.hermes_home,
    )
    return {
        "removed_paths": removed,
        "would_remove": would_remove,
        "kept_paths": kept,
    }


def _omh_home_removal_refusal(paths: OmhPaths) -> str | None:
    reason = unsafe_removal_reason(paths.omh_home, hermes_home=paths.hermes_home) or configured_link_reason(paths.omh_home, "OMH_HOME")
    if reason:
        return reason
    marker = paths.manifest_path
    if is_directory_link(marker):
        return "OMH home ownership is unproven: manifest.json is a symlink"
    manifest, error = read_json_object_result(marker)
    if error or not manifest or manifest.get("package") != "oh-my-hermes" or manifest.get("schema_version") != 1:
        return "OMH home ownership is unproven: no readable OMH manifest.json"
    return None


# Top-level OMH-home entries written by producers that do not go through an
# OmhPaths property. Every other top-level name comes from OmhPaths itself.
_OMH_HOME_EXTRA_ENTRIES = frozenset({
    "routing",  # route_question_mode, owner_preference_record, delegation_route_restore
    "rules",  # toolcall_rules: rules/toolcall-rules.json
    "tui",  # skin_pack theme.json, tui.launch_card launch-skills.json
    "menubar",  # surfaces.menubar_app
    "jev",  # jev_ask_store
    "documents",  # document_chunk_plan.documents_root
    "adapter-quality",  # omh.adapter_quality
    "design-direction-iterations",  # workflows.design_direction_iterations_store
    "skills-import-manifest.json",  # workflows.external_rule_import
    "plans", "plan-variants", "plan-context",  # system.paths.project_artifact_dir
    "codegraph",  # codegraph.schema, when the home is a repository's .omh
})
# system.paths.ensure_project_store_ignored writes exactly this into .gitignore.
_OMH_STORE_GITIGNORE = "*\n"


def _omh_created_names() -> frozenset[str]:
    """Top-level names OMH writes under its home, derived from OmhPaths."""
    probe = OmhPaths(omh_home=Path("/omh-home-probe"), hermes_home=Path("/hermes-home-probe"))
    names = set(_OMH_HOME_EXTRA_ENTRIES)
    for name, attribute in vars(OmhPaths).items():
        if isinstance(attribute, property):
            value = getattr(probe, name)
            if isinstance(value, Path) and value.is_relative_to(probe.omh_home) and value != probe.omh_home:
                names.add(value.relative_to(probe.omh_home).parts[0])
    return frozenset(names)


def _is_omh_created_entry(entry: Path, names: frozenset[str]) -> bool:
    name = entry.name
    if name in names:
        return True
    # local_store sidecars: `.<name>.lock` locks and `.<name>.<pid>-<hex>.tmp` writes.
    if name.startswith(".") and (name.endswith(".lock") or name.endswith(".tmp")):
        stem = name[1:].rsplit(".", 1)[0]
        return any(stem == owned or stem.startswith(f"{owned}.") for owned in names)
    if name == ".gitignore" and entry.is_file() and not entry.is_symlink():
        try:
            return entry.read_text(encoding="utf-8") == _OMH_STORE_GITIGNORE
        except (OSError, UnicodeError):
            return False
    return False


def _collect_omh_home_contents(
    paths: OmhPaths,
    *,
    removed: list[str],
    would_remove: list[str],
    kept: list[dict[str, str]],
    dry_run: bool,
) -> None:
    """Remove only top-level entries OMH creates; the home goes only once empty.

    A manifest proves OMH installed into this directory, not that OMH wrote
    everything in it: OMH_HOME may name a personal folder, and people drop
    files into ~/.omh. Anything OMH does not create is kept and reported.
    """
    home = paths.omh_home
    if not home.exists():
        return
    names = _omh_created_names()
    foreign = False
    for entry in sorted(home.iterdir(), key=lambda item: item.name):
        if not _is_omh_created_entry(entry, names):
            kept.append({"path": str(entry), "reason": "not created by OMH"})
            foreign = True
            continue
        if dry_run:
            would_remove.append(str(entry))
        else:
            discard_path(entry)
            removed.append(str(entry))
    if foreign:
        kept.append({"path": str(home), "reason": "OMH home still holds entries not created by OMH"})
    elif dry_run:
        would_remove.append(str(home))
    else:
        home.rmdir()
        removed.append(str(home))


def _collect_removal(
    path: Path,
    *,
    removed: list[str],
    would_remove: list[str],
    kept: list[dict[str, str]],
    dry_run: bool,
    force: bool,
    managed_plugin: bool = False,
    managed_team_file: bool = False,
    boundary: Path | None = None,
) -> None:
    if not path.exists() and not is_directory_link(path):
        return
    reason = None
    if managed_plugin or managed_team_file:
        reason = unsafe_removal_reason(path)
        if boundary is not None:
            reason = reason or linked_removal_reason(path, boundary)
    if managed_team_file and not path.is_file():
        reason = reason or "team-profile ownership authorizes only individual files, not directories"
    if reason:
        kept.append({"path": str(path), "reason": reason})
        return
    if managed_plugin and host_managed_plugin(path) is not None:
        # `hermes plugins install` wrote this tree and recorded it in its own
        # install metadata. Deleting it -- even under --force -- would leave
        # that record pointing at nothing; Hermes removes what Hermes installed.
        kept.append({"path": str(path), "reason": "installed by Hermes; run `hermes plugins remove omh`"})
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
    discard_path(path)
    removed.append(str(path))


def _looks_like_managed_plugin(path: Path) -> bool:
    return (path / ".omh-plugin-manifest.json").exists()


def _command_venv_scripts_dirs(venv: Path) -> tuple[Path, ...]:
    """Executable directories a venv can use on this host.

    Windows venvs normally use `Scripts`, but MSYS2/Cygwin-built Pythons there
    lay out `bin`; POSIX venvs only ever use `bin`.
    """
    native = managed_command_venv_scripts_dir(venv)
    return (native,) if native.name == "bin" else (native, venv / "bin")


def _same_path(left: Path, right: Path) -> bool:
    """Compare as the filesystem does: case-insensitive and 8.3-expanded on Windows."""
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))


def _command_venv_owned(path: Path) -> bool:
    """A runtime containment match alone cannot claim an arbitrary ancestor."""
    marker = path / "pyvenv.cfg"
    if not marker.is_file() or is_directory_link(marker):
        return False
    return any(
        not linked_removal_reason(scripts, path)
        and any((scripts / name).is_file() for name in ("omh", "omh.exe"))
        for scripts in _command_venv_scripts_dirs(path)
    )


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
    reason = unsafe_removal_reason(venv_dir) or configured_link_reason(venv_dir, "OMH_VENV_DIR")
    if reason:
        kept.append({"path": str(venv_dir), "reason": reason})
        return
    executable = Path(sys.executable).expanduser()
    interpreter_dir = _normalize_without_final_symlink(executable).parent
    runtime = interpreter_dir.parent
    if (
        not command_runtime_owned(executable, venv_dir)
        or not any(_same_path(interpreter_dir, scripts) for scripts in _command_venv_scripts_dirs(runtime))
        or not _command_venv_owned(runtime)
    ):
        kept.append(
            {
                "path": str(executable.resolve()),
                "reason": "current omh command is not running from a verified installer-managed OMH venv",
            }
        )
        return

    # A verified runtime owns neither arbitrary sibling directories nor a real
    # directory named current. Attribute every recursive target separately.
    generations = managed_command_generations_dir()
    owned_generations: list[Path] = []
    if generations is not None and generations.exists():
        reason = unsafe_removal_reason(generations)
        if reason:
            kept.append({"path": str(generations), "reason": reason})
        else:
            for generation in sorted(generations.iterdir()):
                reason = unsafe_removal_reason(generation)
                if not reason and not _command_venv_owned(generation / "venv"):
                    reason = "generation ownership is unproven: no OMH command venv"
                if reason:
                    kept.append({"path": str(generation), "reason": reason})
                else:
                    owned_generations.append(generation)
    current = managed_command_current_dir()
    if current is not None and (current.exists() or is_directory_link(current)):
        if is_directory_link(current) and current.resolve() in owned_generations:
            _collect_removal(current, removed=removed, would_remove=would_remove, kept=kept, dry_run=dry_run, force=True)
        else:
            kept.append({"path": str(current), "reason": "current pointer ownership is unproven"})

    for link in _managed_command_links(venv_dir):
        _collect_removal(link, removed=removed, would_remove=would_remove, kept=kept, dry_run=dry_run, force=True)
    for generation in owned_generations:
        _collect_removal(generation, removed=removed, would_remove=would_remove, kept=kept, dry_run=dry_run, force=True)
    state_path = managed_command_self_update_state_path()
    if state_path is not None and state_path.exists():
        state, error = read_json_object_result(state_path)
        if not is_directory_link(state_path) and not error and state and state.get("schema_version") == "self_update_state/v1":
            _collect_removal(state_path, removed=removed, would_remove=would_remove, kept=kept, dry_run=dry_run, force=True)
            lock = state_path.with_name(f".{state_path.name}.lock")
            if lock.is_file() and not is_directory_link(lock):
                _collect_removal(lock, removed=removed, would_remove=would_remove, kept=kept, dry_run=dry_run, force=True)
        else:
            kept.append({"path": str(state_path), "reason": "self-update state ownership is unproven"})
    if venv_dir.exists():
        if _command_venv_owned(venv_dir):
            _collect_removal(venv_dir, removed=removed, would_remove=would_remove, kept=kept, dry_run=dry_run, force=True)
        else:
            kept.append({"path": str(venv_dir), "reason": "legacy command venv ownership is unproven"})


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
            path = Path(os.path.abspath(Path(raw_path).expanduser()))
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
