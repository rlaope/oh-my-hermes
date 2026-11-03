"""Which OMH skills this home actually installed, as the per-turn hints need it.

The route hint and the skill-candidate line rank the whole catalog, and a
`--core` install holds ten of its skills. Unfiltered, both told the model to
load skills that are not on disk (#1954), and `skill_view` on a missing name
is an error the model has to recover from mid-answer.

The install manifest (`<omh_home>/manifest.json`) is the record read here. The
installer writes it after every install, update and reconcile from the
`SKILL.md` files it finds on disk, so it names full-only skills a core profile
kept as well as the core ones. Each record carries the canonical name and the
installed path, whose leaf directory is the label Hermes lists; both spellings
are kept, because the route hint emits canonical names and ULW labels while
the candidate line emits labels.

`pre_llm_call` runs this every turn, so the parse is cached on the file's
mtime and size: a turn costs one `stat`, and an install that rewrites the
manifest is seen on the next turn without a Hermes restart.

Installed is not loadable. Hermes loads a bare skill name from the
`skills.external_dirs` it resolved, and from 27 Oct to 2 Nov 2026 that set
held OMH's skills twice (a stale generation pack beside the pointer, and
Hermes refuses a name two directories of one tier hold) and then not at all
(a cached path to a generation that was garbage-collected). The manifest
still listed every skill, so the candidate line kept telling the model to
load names `skill_view` answered "not found" for.
`hermes_loadable_skill_names` cuts the installed set to the skills exactly
one of Hermes' directories holds, read from Hermes' own cached resolution in
this process.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import json
import os
from pathlib import Path, PurePosixPath
import sys

from .skill_shortlist import catalog_skill_names

MANIFEST_NAME = "manifest.json"
SKILL_FILE = "SKILL.md"
# Hermes' module that resolves `skills.external_dirs` and caches the answer
# per `config.yaml` signature (`agent/skill_utils.py`); `skill_view`, the
# prompt index and the skills list all read their roots through it.
HERMES_SKILL_UTILS_MODULE = "agent.skill_utils"
HERMES_EXTERNAL_DIRS_READER = "get_external_skills_dirs"

# (canonical name, label) per manifest record; either is "" when the record
# does not carry it.
_Record = tuple[str, str]
_ManifestKey = tuple[str, int, int]
_Manifest = tuple[_ManifestKey, "frozenset[str] | None", tuple[_Record, ...]]
_cache: _Manifest | None = None
_loadable_cache: tuple[object, frozenset[str]] | None = None


def installed_skill_names(omh_home: str | Path) -> frozenset[str] | None:
    """Canonical names and labels of the skills this home's manifest records.

    `None` means the installed set is unknown -- no manifest, an unreadable
    one, or one that records no skill -- and every caller then fails OPEN, to
    the full catalog it named before this filter existed. Failing closed would
    silence the hint on every install whose manifest OMH cannot read: a
    checkout run without `omh setup`, a plugin bound to a home other than the
    one that installed, or a manifest mid-write. Naming a skill that may be
    missing is the older, recoverable cost; withholding every skill is not.
    """
    read = _manifest(omh_home)
    return None if read is None else read[1]


def _manifest(omh_home: str | Path) -> _Manifest | None:
    global _cache
    path = Path(omh_home) / MANIFEST_NAME
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    cached = _cache
    if cached is not None and cached[0] == key:
        return cached
    records = _read_manifest_records(path)
    names = frozenset(alias for record in records for alias in record if alias) or None
    _cache = (key, names, records)
    return _cache


def _read_manifest_records(path: Path) -> tuple[_Record, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    records = payload.get("skills") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return ()
    read: list[_Record] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        name = record.get("name")
        relative = record.get("path")
        label = PurePosixPath(relative).parent.name if isinstance(relative, str) and relative else ""
        read.append((name if isinstance(name, str) else "", label))
    return tuple(read)


def installed_skill_labels(omh_home: str | Path) -> frozenset[str] | None:
    """The directory names (Hermes' load names) of the skills this home's manifest records, or `None`."""
    read = _manifest(omh_home)
    labels = frozenset(label for _, label in read[2] if label) if read is not None else frozenset()
    return labels or None


def skill_labels_under(root: str | Path) -> frozenset[str] | None:
    """The skill directory names under `root` in OMH's pack layout; `None` when `root` is no directory.

    A pack puts a skill at `<root>/<category>/<label>/SKILL.md`. A directory
    holding `SKILL.md` straight under the root counts too and is not
    descended into, the way Hermes stops at a skill. Hermes matches a bare
    name at any depth; two levels is every layout OMH has written.
    """
    labels: set[str] = set()
    try:
        with os.scandir(root) as entries:
            children = [entry.path for entry in entries if entry.is_dir()]
        for child in children:
            if os.path.isfile(os.path.join(child, SKILL_FILE)):
                labels.add(os.path.basename(child))
                continue
            with os.scandir(child) as entries:
                labels.update(
                    entry.name
                    for entry in entries
                    if entry.is_dir() and os.path.isfile(os.path.join(entry.path, SKILL_FILE))
                )
    except OSError:
        if not os.path.isdir(root):
            return None
    return frozenset(labels)


def skill_label_holders(labels: Iterable[str], roots: Sequence[str | Path]) -> dict[str, int]:
    """How many of `roots` hold each label.

    Hermes loads a bare name only when exactly one directory of the lowest
    tier that holds it does. Every external directory is the same tier, and
    two copies in two directories are refused as ambiguous even when they
    are byte-identical (`agent/skill_utils.py` `pick_skill_candidate`). So 1
    is loadable, 0 is not found, and 2 or more is refused.
    """
    held = [skill_labels_under(root) or frozenset() for root in roots]
    return {label: sum(label in names for names in held) for label in labels}


def hermes_external_skill_roots() -> list[Path] | None:
    """The external skill directories this Hermes process resolved, from its own cache; `None` outside Hermes.

    The plugin runs inside Hermes, so this reads the module `skill_view`
    reads. It is already loaded, and nothing is imported. Its cache is keyed
    on the `config.yaml` signature and keeps a resolved path after the
    directory behind it is deleted, which is the state that hid every OMH
    skill from 30 Oct. A Hermes without the reader, or one whose reader
    raises, gives `None`, and the caller keeps the installed set as it was.
    """
    module = sys.modules.get(HERMES_SKILL_UTILS_MODULE)
    read = getattr(module, HERMES_EXTERNAL_DIRS_READER, None)
    if not callable(read):
        return None
    try:
        roots = read()
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError):
        return None
    if not isinstance(roots, list):
        return None
    return [Path(root) for root in roots if isinstance(root, (str, os.PathLike))]


def _root_signature(root: Path) -> tuple[object, ...]:
    try:
        stat = root.stat()
    except OSError:
        return (str(root),)
    return (str(root), stat.st_ino, stat.st_mtime_ns)


def hermes_loadable_skill_names(omh_home: str | Path) -> frozenset[str] | None:
    """`installed_skill_names`, cut to the skills Hermes can load by name in this process.

    Whenever Hermes' resolution cannot be read (`hermes_external_skill_roots`
    is `None`), this is the installed set unchanged, so outside Hermes and on
    a healthy install the hint renders what it rendered before. A record
    with no path cannot be checked and is kept.

    Cached per process on the manifest's key and each root's path, inode and
    mtime. Hermes' cached list changes only when `config.yaml` does, and a
    generation that is collected or replaced changes its root's stat, so a
    turn costs one `stat` per root. A skill removed from inside a root that
    otherwise stays is the doctor's `route_hint_skills` finding.
    """
    global _loadable_cache
    read = _manifest(omh_home)
    if read is None or read[1] is None:
        return None
    roots = hermes_external_skill_roots()
    if roots is None:
        return read[1]
    key = (read[0], tuple(_root_signature(root) for root in roots))
    cached = _loadable_cache
    if cached is not None and cached[0] == key:
        return cached[1]
    records = read[2]
    holders = skill_label_holders({label for _, label in records if label}, roots)
    loadable = frozenset(
        alias
        for name, label in records
        if not label or holders[label] == 1
        for alias in (name, label)
        if alias
    )
    _loadable_cache = (key, loadable)
    return loadable


def skill_not_installed(name: str, installed: frozenset[str] | None) -> bool:
    """True only for a catalog skill the known installed set does not hold.

    A name outside the catalog is left alone: the hint also names lanes and
    retired engines that no install ever holds, and a full install must emit
    exactly what it emitted before. An unknown installed set or an unreadable
    catalog sidecar holds nothing back, for the reason `installed_skill_names`
    gives.
    """
    if installed is None or name in installed:
        return False
    catalog = catalog_skill_names()
    return catalog is not None and name in catalog


def reset_installed_skill_cache() -> None:
    global _cache, _loadable_cache
    _cache = None
    _loadable_cache = None


__all__ = [
    "HERMES_EXTERNAL_DIRS_READER",
    "HERMES_SKILL_UTILS_MODULE",
    "MANIFEST_NAME",
    "hermes_external_skill_roots",
    "hermes_loadable_skill_names",
    "installed_skill_labels",
    "installed_skill_names",
    "reset_installed_skill_cache",
    "skill_label_holders",
    "skill_labels_under",
    "skill_not_installed",
]
