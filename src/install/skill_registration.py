"""Which managed skills directory a Hermes home registers, and whether it is one.

`omh setup` and `omh update` register one OMH-managed skills directory in a
Hermes home's `skills.external_dirs`: the shared generation pointer on an
installer-managed command, otherwise the OMH home's own `skills` directory.
Which of them a given home recorded depends only on when it was registered,
so "registered" reads any of them -- a profile left on the older path was
once scored as opted out and frozen on the generation it was installed at.

Two of them at once is a different state, not a wider registration. Hermes
resolves a bare skill name across every external directory and refuses one
that resolves to two different files ("Ambiguous skill name ... Refusing to
guess"); only copies that resolve to the same file count as one. Every
generation refresh makes the pre-pointer copy and the pointer differ, so a
home naming both loses every OMH skill by name (#1857). A generation's own
pack named beside the pointer is the same state one update later, so it is
a managed entry too, whichever generation it names. Setup and update
migrate such a home to the one path the running command writes; `omh doctor`
and the update post-check report a home that still names two, in the same
words. This module is the one place both sides read the candidate set and
spell the finding, so the writer and the readers cannot drift: both match an
entry by its real path, the way Hermes reads it, so a spelling through `~`,
a trailing slash, a `${VAR}` or a symlink is the same directory to the
migration that it is to the finding.

Pure path and text work: no config write, no subprocess, no network.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import sys

from .config_adapter import (
    anchored_external_dir,
    ensure_external_dir,
    external_dir_names_a_root,
    external_dirs,
    remove_external_dir_entries,
)
from ..paths import OmhPaths, configured_omh_home, managed_command_venv_dir
from ..skin_pack import TUI_PROFILE
from .lifecycle_safety import command_runtime_owned, primary_hermes_home
from ..plugin_bundle.omh import runtime_paths

AMBIGUOUS_REGISTRATION_NEXT_ACTION = "run `omh update`"


def external_dir_key(path: str | Path) -> str:
    """One comparable spelling of a registered directory across separators and case."""
    return os.path.normcase(os.path.normpath(str(path))).replace("\\", "/")


def managed_command_runtime() -> dict[str, object]:
    """Whether the running `omh` is the installer-managed command, and why not when it is not."""
    venv_dir = managed_command_venv_dir()
    if venv_dir is None:
        return {"managed": False, "reason": "no home directory or OMH_VENV_DIR is available"}
    executable = Path(sys.executable).expanduser()
    if not command_runtime_owned(executable, venv_dir):
        return {
            "managed": False,
            "reason": "current omh command is not running from the installer-managed OMH venv",
            "python": str(executable.resolve()),
            "venv_dir": str(venv_dir),
        }
    return {"managed": True, "reason": "", "python": str(executable), "venv_dir": str(venv_dir)}


def registered_skill_dir(
    paths: OmhPaths, *, current: Path | None, runtime: Callable[[], Mapping[str, object]]
) -> Path:
    """The ONE managed skills directory this command writes into a home's registration.

    The shared generation pointer when it is on disk and the running command
    is the installer-managed one, otherwise `paths.skills_dir` -- never the
    running generation's own pack, which the next update would leave beside
    the pointer. `omh setup`, `omh update` and `omh chat
    --auto-apply-target-change` all write through this. `current` and
    `runtime` (`managed_command_runtime`) are the caller's own bindings,
    passed in for the reason `managed_skill_dir_candidates` takes `current`;
    `runtime` is only called once the pointer is on disk.
    """
    if current is not None and current.is_dir() and runtime().get("managed"):
        return current
    return paths.skills_dir


def managed_skill_dir_candidates(paths: OmhPaths, *, current: Path | None) -> list[Path]:
    """Every managed skills directory a registration may legitimately name.

    `<omh_home>/skills` is listed by name, not only through `paths.skills_dir`:
    on a managed command install `resolve_paths` redirects `skills_dir` to the
    running generation's pack, so the pre-pointer registration home -- the
    path a frozen profile carries -- would otherwise never be a candidate on
    exactly the machines that need it. The standalone default store is named
    too: a profile that later selected its own store was registered by the
    sync at the primary's, which for a default install is that one.

    `current` is the shared generation pointer as the caller resolved it,
    passed in rather than read here so the installer's own binding (and the
    fixtures that stub it) stays the one reading.
    """
    primary = primary_hermes_home(paths.hermes_home)
    primary_store = configured_omh_home(primary) if primary != paths.hermes_home else None
    runtime_store = configured_omh_home(paths.hermes_home)
    candidates: list[Path] = []
    for candidate in (
        primary_store / "skills" if primary_store is not None else None,
        runtime_store / "skills" if runtime_store is not None else None,
        paths.omh_home / "skills",
        paths.skills_dir,
        current,
        runtime_paths.standalone_default_omh_home(paths.hermes_home) / "skills",
    ):
        if candidate is not None and candidate not in candidates:
            candidates.append(candidate)
    return candidates


@dataclass(frozen=True)
class RegistrationMigration:
    """One home's registration after the migration: the text to write and what moved."""

    text: str
    added: bool
    message: str
    retired: list[str]

    @property
    def registration(self) -> str:
        """`migrated` when an older managed entry was retired, `added` when only
        today's path went in, else `unchanged` -- the word setup's apply step
        and each profile row carry."""
        if self.retired:
            return "migrated"
        return "added" if self.added else "unchanged"


def migrate_managed_registration(
    config_text: str,
    registered_dir: Path,
    candidates: Iterable[Path],
    *,
    hermes_home: Path,
    current: Path | None = None,
) -> RegistrationMigration:
    """Register `registered_dir` and retire every OTHER managed candidate, in one text.

    A migration, not an unregistration: the home ends registered at exactly
    one managed path. A home carried forward from the pre-pointer path used
    to keep `<omh_home>/skills` beside the generation pointer, and Hermes
    refuses a bare skill name that resolves to two different files -- so
    every generation refresh made every OMH skill fail to load by name in
    that home (#1857). Only entries that resolve to one of `candidates` are
    retired; a directory the person registered themselves is not OMH's to
    touch. An entry is matched by real path, the same rule
    `registered_managed_entries` and `external_dir_registered` read by, so an
    older entry spelled through `~`, a trailing slash or a symlink is
    retired too -- Hermes expands and resolves every entry, and a spelling
    the migration could not match would be reported as an ambiguity that
    `omh update` can never clear. Every entry is read the way Hermes reads
    it in `hermes_home`, the home whose config this is
    (`anchored_external_dir`): a relative one names a directory under that
    home, never under this command's working directory, and a drive-less
    rooted one on Windows sits on the home's drive. An entry naming
    `registered_dir` in any of those spellings is not added beside, and an
    entry resolving to `registered_dir` itself is one directory to Hermes and
    stays. Whether a home should be
    registered at all, and whether this command may retire anything, are the
    caller's questions: this function always writes today's path, the
    opt-out rule (a home naming no managed directory is left alone) is
    applied before it is called, and a caller that must stay additive passes
    no candidates. The retired entries are reported as `external_dirs` reads
    them from the file.

    `current` is the shared generation pointer, passed by a caller that
    retires: every entry naming one generation's own pack beside it is
    retired as well, including the one the pointer resolves to today (see
    `generation_pack_entries`).

    Pure text work, so it can be run against a copy of a live config.
    """
    change = ensure_external_dir(config_text, registered_dir, hermes_home=hermes_home)
    registered_real = _real_key(registered_dir)
    others = [candidate for candidate in candidates if _real_key(candidate) != registered_real]
    named = set(managed_candidate_entries(change.text, others, hermes_home=hermes_home))
    packs = set(generation_pack_entries(change.text, current, hermes_home=hermes_home))
    to_retire = [entry for entry in external_dirs(change.text) if entry in packs or entry in named]
    removal = remove_external_dir_entries(change.text, to_retire)
    retired = list(to_retire) if removal.changed else []
    return RegistrationMigration(text=removal.text, added=change.changed, message=change.message, retired=retired)


def managed_candidate_entries(config_text: str, candidates: Iterable[Path], *, hermes_home: Path) -> list[str]:
    """The registered entries that name one of `candidates` to Hermes in `hermes_home`.

    Matched by real path after anchoring each entry at the home
    (`_anchored_real_key`), so every spelling Hermes reads as that directory
    -- `${VAR}`, `~`, a trailing slash, a symlink, a path relative to the
    home -- is one, and an entry Hermes reads as anything else, a directory
    the person registered included, is not. The migration retires these and
    the opt-out removes them, so the writer and uninstall cannot disagree
    about a spelling. Config order is kept.
    """
    reals = {_real_key(candidate) for candidate in candidates}
    return [entry for entry in external_dirs(config_text) if _anchored_real_key(entry, hermes_home) in reals]


def generation_pack_entries(config_text: str, current: Path | None, *, hermes_home: Path) -> list[str]:
    """The registered entries that name one generation's own pack, gone or not.

    `current` is the shared pointer, `<root>/current/skills`, and every
    generation it may point at keeps its pack at
    `<root>/generations/<id>/skills`. A home that names one of those beside
    the pointer is registered at the same pack twice on the day it is
    written, and at two different packs after the next update moves the
    pointer -- every OMH skill then resolves to two files and Hermes lists
    none of them. Nothing ever re-registers a generation by its own path, so
    any such entry is retired: one whose generation was garbage-collected
    too, which Hermes skips today but which still names a directory OMH
    owns. Matched by the real path of the `generations` directory, so the
    entry's spelling through `~`, a trailing slash or a link to the root is
    the same entry; `generations/<id>` itself is not resolved, because the
    pack it names may no longer exist. An entry is read the way Hermes reads
    it in `hermes_home` (`anchored_external_dir`), so a spelling through
    `${VAR}` is the same entry, a relative one is one only when it reaches
    the managed root from that home (`../m/generations/<id>/skills`), and a
    drive-less rooted one on Windows sits on the home's drive -- whatever
    directory, and drive, this command runs from. Config order is kept.
    """
    if current is None:
        return []
    generations = _real_key(current.parent.parent / "generations")
    entries: list[str] = []
    for entry in external_dirs(config_text):
        anchored = _anchored(entry, hermes_home)
        if anchored is None:
            continue
        normalized = os.path.normpath(anchored)
        if os.path.normcase(os.path.basename(normalized)) != "skills":
            continue
        if _real_key(os.path.dirname(os.path.dirname(normalized))) == generations:
            entries.append(entry)
    return entries


def _anchored(entry: str, hermes_home: Path) -> str | None:
    """`entry` as Hermes reads it in `hermes_home`, or None when that is not rooted.

    Only a drive-relative entry on a drive other than the home's stays
    unrooted; Hermes resolves it against its own process's directory on that
    drive, which no command here can know, so it is never matched.
    """
    anchored = anchored_external_dir(entry, hermes_home)
    return anchored if external_dir_names_a_root(anchored) else None


def _anchored_real_key(entry: str, hermes_home: Path) -> str | None:
    """The real-path key of the directory Hermes reads for `entry`, else None."""
    anchored = _anchored(entry, hermes_home)
    return None if anchored is None else _real_key(anchored)


def _real_key(path: str | Path) -> str:
    expanded = os.path.expanduser(str(path))
    try:
        return external_dir_key(os.path.realpath(expanded))
    except OSError:
        return external_dir_key(expanded)


def registered_managed_entries(
    config_text: str,
    candidates: Iterable[Path],
    *,
    hermes_home: Path,
    current: Path | None = None,
    present_only: bool = True,
) -> list[str]:
    """The registered entries that name a managed directory present on disk, one per real directory.

    `present_only=False` keeps an entry whose directory is gone too: the
    question "does this home register OMH's skills at all", which a dangling
    pointer still answers yes.

    By text or by real path, the way `external_dir_registered` reads a single
    candidate. Two entries that resolve to the same directory -- the pointer
    and the generation it points at -- are one SKILL.md to Hermes and count
    once; two that resolve to different directories are the ambiguity. An
    entry whose directory is not on disk is not counted at all: Hermes skips
    a missing external directory when it collects skills, so nothing can be
    ambiguous through it. Every entry is read the way Hermes reads it in
    `hermes_home` (`_anchored_real_key`), never against this command's
    working directory or drive. Config order is kept so a message names them
    the way the file does.

    With `current`, the shared pointer, an entry naming one generation's own
    pack is managed too (`generation_pack_entries`): beside the pointer it
    becomes a second directory as soon as the pointer moves on.
    """
    packs = generation_pack_entries(config_text, current, hermes_home=hermes_home)
    candidates = [*candidates, *(Path(anchored_external_dir(entry, hermes_home)) for entry in packs)]
    keys = {external_dir_key(candidate) for candidate in candidates}
    reals = {_real_key(candidate) for candidate in candidates}
    seen: set[str] = set()
    entries: list[str] = []
    for entry in external_dirs(config_text):
        real = _anchored_real_key(entry, hermes_home)
        if real is None or (external_dir_key(entry) not in keys and real not in reals):
            continue
        if present_only and not os.path.isdir(anchored_external_dir(entry, hermes_home)):
            continue
        if real in seen:
            continue
        seen.add(real)
        entries.append(entry)
    return entries


def registration_home_label(config_path: Path, *, profile: str | None = None) -> str:
    """How doctor and the update post-check both name a home in the finding."""
    if profile is None:
        return str(config_path)
    return f"profile {profile} ({config_path})"


def ambiguous_registration_message(label: str, entries: list[str]) -> str:
    """The one sentence for a home that names two managed skills directories."""
    listed = " and ".join(entries) if len(entries) == 2 else ", ".join(entries)
    return (
        f"{label} names {len(entries)} OMH-managed skills directories in skills.external_dirs ({listed}); "
        "Hermes refuses a bare skill name that resolves to two different files, "
        "so OMH skills fail to load by name"
    )


def hermes_profile_dirs(hermes_home: Path) -> list[tuple[str, Path]]:
    """List the Hermes bot-profile homes under ``<hermes_home>/profiles/``.

    Hermes profiles (``hermes profile create``, Desktop bot chats) are fully
    independent HERMES_HOME directories with their own config.yaml, skills,
    and skins -- a registration written to the primary home never reaches
    them, which is why bot chats showed zero OMH skills while the default
    chat had the full set. Sorted for deterministic output; hidden entries
    are Hermes-internal, never profiles.
    """
    root = hermes_home / "profiles"
    try:
        entries = sorted(entry for entry in root.iterdir() if entry.is_dir() and not entry.name.startswith("."))
    except OSError:
        return []
    # Match Hermes' dependency-free named_profile_has_identity contract, not
    # incidental runtime directories. Keep link markers as identity claims so
    # the existing writer/refusal boundaries still inspect them. The OMH TUI's
    # own runtime profile (`tui/own_runtime.py`) links the root's skills, OMH's
    # registration among them: a registration of its own would double every name.
    markers = ("config.yaml", ".env", "SOUL.md", "profile.yaml", "auth.json", "state.db")
    return [(entry.name, entry) for entry in entries
            if entry.name != TUI_PROFILE
            and not (root / ".deleted" / entry.name).exists()
            and any((entry / marker).is_file() or (entry / marker).is_symlink() for marker in markers)]
