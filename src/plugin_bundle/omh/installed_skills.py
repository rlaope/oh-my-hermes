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

Installed is not loadable. Hermes loads a bare skill name from the skill
directories it resolved, and from 27 Oct to 2 Nov 2026 those held OMH's
skills twice (a stale generation pack beside the pointer, and Hermes refuses
a name two directories of one tier hold) and then not at all (a cached path
to a generation that was garbage-collected). The manifest still listed every
skill, so the candidate line kept telling the model to load names
`skill_view` answered "not found" for. `hermes_loadable_skill_names` cuts the
installed set to the skills Hermes resolves to one copy, read from Hermes'
own cached resolution in this process.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import json
import os
from pathlib import Path, PurePosixPath
import sys

from .skill_ownership import skill_directories
from .skill_shortlist import catalog_skill_label, catalog_skill_names

MANIFEST_NAME = "manifest.json"
SKILL_FILE = "SKILL.md"
# Hermes' module that orders every skill directory by precedence and caches
# the resolved `skills.external_dirs` per `config.yaml` signature
# (`agent/skill_utils.py`); `skill_view`, the prompt index and the skills
# list all read their roots through it. `get_skill_search_roots` is the
# tiered list; `get_external_skills_dirs` alone is the older, external-only
# reader.
HERMES_SKILL_UTILS_MODULE = "agent.skill_utils"
HERMES_SEARCH_ROOTS_READER = "get_skill_search_roots"
HERMES_EXTERNAL_DIRS_READER = "get_external_skills_dirs"
# Hermes' precedence tiers, lowest wins (`agent/skill_utils.py`).
TIER_PROJECT, TIER_LOCAL, TIER_CREATE_DIR, TIER_EXTERNAL = range(4)

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
    read = (key, frozenset(alias for record in records for alias in record if alias) or None, records)
    _cache = read
    return read


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


def skill_label_copies(labels: Iterable[str], roots: Sequence[tuple[int, str | Path]]) -> dict[str, list[str]]:
    """For each label, the directories whose copy Hermes weighs when it loads the bare name.

    Hermes finds a skill by directory name at any depth (`skill_directories`
    walks the same way, and one unreadable directory skips only itself).
    The lowest tier holding a label wins outright. Inside it, copies under a
    single root count as that root, and two roots whose copies resolve to
    one `SKILL.md` count once: a root that is itself a link to another (the
    `current` pointer beside its generation). A symlinked skill directory
    inside a root is not walked at all, because `skill_directories` does not
    follow links below the root, so a link to a skill another root already
    holds adds no copy and that skill stays loadable, as it does in Hermes,
    which dedups by resolved path. So one directory is loadable, none is
    "not found", and two or more are refused as ambiguous
    (`agent/skill_utils.py` `pick_skill_candidate`).

    Every difference from Hermes lands on "loadable" but one. Hermes would
    still pick among identical copies under one root; this calls any copies
    under one root loadable. A wrong "loadable" costs one recoverable load.
    The exception: Hermes' walk follows links, so a symlinked skill
    directory pointing outside every scanned root is a copy Hermes loads and
    this does not see. If it is the only copy, the skill reads "not found"
    here. OMH's installer creates no such link.
    """
    wanted = set(labels)
    best: dict[str, tuple[int, dict[str, str]]] = {}
    for tier, root in roots:
        for directory in skill_directories(Path(root)):
            label = directory.name
            if label not in wanted:
                continue
            held = best.get(label)
            if held is None or tier < held[0]:
                held = best[label] = (tier, {})
            elif tier > held[0]:
                continue
            held[1].setdefault(os.path.realpath(directory / SKILL_FILE), str(root))
    return {label: sorted(set(best[label][1].values())) if label in best else [] for label in wanted}


def hermes_skill_search_roots() -> list[tuple[int, Path]] | None:
    """The skill directories this Hermes process searches, by tier, from its own cache; `None` outside Hermes.

    The plugin runs inside Hermes, so this reads the module `skill_view`
    reads. It is already loaded, and nothing is imported. Its external
    directories are cached on the `config.yaml` signature, and a cached path
    is kept after the directory behind it is deleted, which is the state
    that hid every OMH skill from 30 Oct. A Hermes without either reader
    gives `None`, and so does one whose reader raises, whatever it raises:
    this runs inside `pre_llm_call`, and the caller then keeps the installed
    set, which is what the hint named before this check existed.
    """
    module = sys.modules.get(HERMES_SKILL_UTILS_MODULE)
    tiered = getattr(module, HERMES_SEARCH_ROOTS_READER, None)
    external = getattr(module, HERMES_EXTERNAL_DIRS_READER, None)
    try:
        if callable(tiered):
            return [(int(tier), Path(root)) for tier, root in tiered()]
        if callable(external):
            return [(TIER_EXTERNAL, Path(root)) for root in external()]
    except Exception:  # noqa: BLE001 -- classified in tests/test_broad_exception_policy.py
        return None
    return None


def _root_signature(tier: int, root: Path) -> tuple[object, ...]:
    try:
        stat = root.stat()
    except OSError:
        return (tier, str(root))
    return (tier, str(root), stat.st_ino, stat.st_mtime_ns)


def hermes_loadable_skill_names(omh_home: str | Path) -> frozenset[str] | None:
    """`installed_skill_names`, cut to the skills Hermes can load by name in this process.

    Whenever Hermes' resolution cannot be read (`hermes_skill_search_roots`
    is `None`), this is the installed set unchanged, so outside Hermes and on
    a healthy install the hint renders what it rendered before. A record
    with no path cannot be checked and is kept.

    Cached per process on the manifest's key and each root's tier, path,
    inode and mtime. Hermes' cached list changes only when `config.yaml`
    does, and a generation that is collected or replaced changes its root's
    stat, so a turn costs one `stat` per root. A skill removed from inside a
    root that otherwise stays is the doctor's `route_hint_skills` finding.
    """
    global _loadable_cache
    read = _manifest(omh_home)
    if read is None or read[1] is None:
        return None
    roots = hermes_skill_search_roots()
    if roots is None:
        return read[1]
    key = (read[0], tuple(_root_signature(tier, root) for tier, root in roots))
    cached = _loadable_cache
    if cached is not None and cached[0] == key:
        return cached[1]
    records = read[2]
    copies = skill_label_copies({label for _, label in records if label}, roots)
    loadable = frozenset(
        alias
        for name, label in records
        if not label or len(copies[label]) == 1
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


def routable_skill_names(
    installed: frozenset[str] | None, disabled: Mapping[str, str]
) -> frozenset[str] | None:
    """`installed`, less every skill of a turned-off capability family (`capability_off`).

    Nothing turned off returns `installed` itself, so a home with no policy
    renders what it rendered before. With a family off and the installed set
    unknown, the whole catalog stands in for it, so the turned-off skills are
    still left out; without a catalog sidecar there is nothing to cut from.
    """
    if not disabled:
        return installed
    base = installed if installed is not None else catalog_skill_names()
    if base is None:
        return None
    off = {alias for name in disabled for alias in (name, catalog_skill_label(name)) if alias}
    return frozenset(name for name in base if name not in off)


def reset_installed_skill_cache() -> None:
    global _cache, _loadable_cache
    _cache = None
    _loadable_cache = None


__all__ = [
    "HERMES_EXTERNAL_DIRS_READER",
    "HERMES_SEARCH_ROOTS_READER",
    "HERMES_SKILL_UTILS_MODULE",
    "MANIFEST_NAME",
    "TIER_CREATE_DIR",
    "TIER_EXTERNAL",
    "TIER_LOCAL",
    "TIER_PROJECT",
    "hermes_loadable_skill_names",
    "hermes_skill_search_roots",
    "installed_skill_labels",
    "installed_skill_names",
    "reset_installed_skill_cache",
    "routable_skill_names",
    "skill_label_copies",
    "skill_not_installed",
]
