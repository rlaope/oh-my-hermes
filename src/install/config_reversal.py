"""What `omh setup` wrote into Hermes' `config.yaml`, and how uninstall takes it back.

Setup's apply step writes several keys in one pass. Uninstall used to reverse
exactly one of them -- the `skills.external_dirs` registration -- so a machine
kept `plugins.enabled: - omh` and `memory.provider: omh` naming a bundle that
was gone. Observed against Hermes 0.21.3 with the bundle removed: a leftover
`memory.provider: omh` makes agent init look the provider up in the plugin
catalogue and warn that it is neither installed nor in it. The lookup is
`hermes-agent.nousresearch.com/docs/api/plugin-catalog.json`, cached under
`HERMES_HOME/cache` for six hours and skipped entirely when
`security.allow_lazy_installs` is off, so the cost is a warning on every
affected start and at most one request per six-hour window per home. The
stale `plugins.enabled` entry and `display.skin: omh` are silent.

Two facts decide every reversal here, and they are deliberately separate:

* WHAT OMH WROTE. Recorded at write time as the difference between the
  reading before the pass and the reading after it -- the same idea #1750
  applied to `display.sections`, extended to every key. The difference is
  what makes a key OMH's: a value the person already had is preserved by the
  writers and must stay theirs.
* WHETHER IT IS STILL OMH'S. Re-read at uninstall time and compared against
  the record. A person who moved `memory.provider` to honcho keeps honcho,
  and the uninstall report names the key it left alone.

Installs that predate the record get the honest subset. `display.skin: omh`,
`plugins.enabled` containing `omh` and `memory.provider: omh` name OMH by
construction and are reversible without a record. `display.interface: tui`,
the `display.sections` children and the compression fallback chain are not
distinguishable from a person's own choice, so they are kept and reported as
unrecorded rather than guessed at.

The three display keys stopped being OMH's to write when bare `hermes` went
back to stock Hermes: bare `omh` opens the OMH TUI, and nothing OMH ships
restyles Hermes' own terminal any more. `release_managed_display` is the
migration. Setup and update run it with the same per-key rules uninstall
uses, and once a pass leaves no key `refused` the record says so
(`display_released_at`): from that point no display value in that config is
OMH's, including an `omh*` skin name, which only the person can have chosen
since. A key the editor would not touch for its YAML shape, and that the
record or the OMH skin name says may be OMH's, is `refused` instead; it
stays OMH's in the record, and the next pass tries again.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from omh.skin_pack import is_omh_skin_name

from ..plugin_bundle.omh.metadata import MEMORY_PROVIDER_NAME
from ..system.local_store import utc_now
from .compression_defaults import (
    compression_fallback_chain_lines,
    compression_settings,
    remove_compression_fallback_chain,
)
from .config_adapter import (
    ConfigChange,
    config_container_paths,
    display_edit_refusal,
    display_interface_selection,
    display_key_named_twice,
    display_sections_selection,
    display_skin_selection,
    display_skin_selections,
    external_dirs,
    memory_provider_selection,
    plugin_enablement,
    plugin_enablement_is_readable,
    plugin_omh_home_setting,
    references_mapping_key,
    references_top_level_section,
    childless_containers,
    remove_childless_containers,
    revert_display_scalar,
    remove_display_sections,
    remove_memory_provider,
    remove_plugin_enabled,
    remove_plugin_omh_home,
)
from ..plugin_bundle.omh import runtime_paths
from .plugin_pack import PLUGIN_NAME

MANAGED_CONFIG_WRITES_STATE_KEY = "hermes_config_writes"
MANAGED_CONFIG_WRITES_SCHEMA = "omh_hermes_config_writes/v1"

DISPLAY_INTERFACE_KEY = "display.interface"
DISPLAY_SECTIONS_KEY = "display.sections"
DISPLAY_SKIN_KEY = "display.skin"
MEMORY_PROVIDER_KEY = "memory.provider"
PLUGINS_ENABLED_KEY = "plugins.enabled"
COMPRESSION_FALLBACK_KEY = "auxiliary.compression.fallback_chain"
EXTERNAL_DIRS_KEY = "skills.external_dirs"
PLUGIN_OMH_HOME_KEY = "plugins.entries.omh.settings.omh_home"

# `skills.external_dirs` is read into the record for the container cleanup
# below, but never reversed here: `_remove_managed_external_dirs` in the
# uninstall command already strips every managed path this home may carry,
# including generations the record never named, and it runs for every scope
# including `--registration-only`.
REVERSIBLE_KEYS: tuple[str, ...] = (
    DISPLAY_INTERFACE_KEY,
    DISPLAY_SECTIONS_KEY,
    DISPLAY_SKIN_KEY,
    MEMORY_PROVIDER_KEY,
    PLUGINS_ENABLED_KEY,
    COMPRESSION_FALLBACK_KEY,
    PLUGIN_OMH_HOME_KEY,
)

# Containers OMH's writers can create. A `display:` that was not there before
# the install and is empty after the reversal is OMH's to remove; one the
# person already had stays whatever the reversal leaves in it.
MANAGED_CONTAINERS: tuple[str, ...] = (
    "display",
    "display.sections",
    "memory",
    "plugins",
    "plugins.enabled",
    "plugins.entries",
    "skills",
    "skills.external_dirs",
)

_SECTION_VALUE = "collapsed"

# The two keys consent let earlier versions write OVER a value the person
# already had. Everything else OMH writes is unset-only, so its inverse is a
# removal; these two need the prior value put back or the person loses a
# choice they made before they ever installed OMH.
RESTORABLE_KEYS: tuple[str, ...] = (DISPLAY_INTERFACE_KEY, DISPLAY_SKIN_KEY)

# What `release_managed_display` takes back, and the containers it may drop
# with them. Earlier versions wrote all three; this one writes none.
DISPLAY_KEYS: tuple[str, ...] = (DISPLAY_INTERFACE_KEY, DISPLAY_SECTIONS_KEY, DISPLAY_SKIN_KEY)
DISPLAY_CONTAINERS: tuple[str, ...] = ("display", "display.sections")

# The per-config record field saying the release ran. Its presence, not its
# value, is what every later reader checks.
DISPLAY_RELEASED_FIELD = "display_released_at"


@dataclass(frozen=True)
class ReversalRow:
    """One managed key's outcome, for the uninstall report.

    `kept` names the children left with the person on a key that was
    otherwise reversed. It is a field rather than a phrase inside `detail`
    because the terminal has to decide whether to print a line about it, and
    deciding that by searching English prose is how the status classification
    went wrong once already.
    """

    key: str
    status: str
    detail: str
    kept: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"key": self.key, "status": self.status, "detail": self.detail, "kept": self.kept}


def managed_config_reading(config_text: str) -> dict[str, object]:
    """Read every key OMH's apply step can write, in one pass.

    One reader per key, each the same one the matching writer consults, so
    "what is there now" can never disagree between the write side and the
    uninstall side.
    """
    return {
        DISPLAY_INTERFACE_KEY: display_interface_selection(config_text),
        DISPLAY_SECTIONS_KEY: display_sections_selection(config_text),
        DISPLAY_SKIN_KEY: display_skin_selection(config_text),
        MEMORY_PROVIDER_KEY: memory_provider_selection(config_text),
        PLUGINS_ENABLED_KEY: list(plugin_enablement(config_text)["enabled"]),
        COMPRESSION_FALLBACK_KEY: compression_fallback_chain_lines(config_text),
        EXTERNAL_DIRS_KEY: list(external_dirs(config_text)),
        PLUGIN_OMH_HOME_KEY: plugin_omh_home_setting(config_text),
    }


def _written_keys(before: dict[str, object], after: dict[str, object]) -> dict[str, object]:
    written: dict[str, object] = {}
    for key in (DISPLAY_INTERFACE_KEY, DISPLAY_SKIN_KEY, MEMORY_PROVIDER_KEY, PLUGIN_OMH_HOME_KEY):
        value = str(after.get(key) or "")
        if value and value != str(before.get(key) or ""):
            written[key] = value
    for key in (DISPLAY_SECTIONS_KEY,):
        before_keys = before.get(key)
        after_keys = after.get(key)
        if isinstance(before_keys, dict) and isinstance(after_keys, dict):
            added = sorted(name for name in after_keys if name not in before_keys)
            if added:
                written[key] = added
    for key in (PLUGINS_ENABLED_KEY, EXTERNAL_DIRS_KEY):
        before_items = before.get(key)
        after_items = after.get(key)
        if isinstance(before_items, list) and isinstance(after_items, list):
            added = sorted(str(item) for item in after_items if item not in before_items)
            if added:
                written[key] = added
    before_chain = before.get(COMPRESSION_FALLBACK_KEY)
    after_chain = after.get(COMPRESSION_FALLBACK_KEY)
    if isinstance(after_chain, list) and after_chain and not before_chain:
        written[COMPRESSION_FALLBACK_KEY] = [str(line) for line in after_chain]
    return written


def _replaced_values(before: dict[str, object], after: dict[str, object]) -> dict[str, str]:
    """What the person had in a key OMH then wrote over, per `RESTORABLE_KEYS`."""
    replaced: dict[str, str] = {}
    for key in RESTORABLE_KEYS:
        prior = str(before.get(key) or "")
        current = str(after.get(key) or "")
        if prior and current and prior != current:
            replaced[key] = prior
    return replaced


def _merged_keys(previous: dict[str, object], written: dict[str, object]) -> dict[str, object]:
    """Carry an earlier run's record forward; a later run only ever adds.

    `_apply_result` runs on every `omh setup` AND every `omh update`, and on
    the second run the writers report "already enabled" and change nothing. A
    record that only ever held the latest run's writes would therefore erase
    itself on the first update, which is exactly the install that most needs
    it.
    """
    merged: dict[str, object] = dict(previous)
    for key, value in written.items():
        if isinstance(value, list) and isinstance(merged.get(key), list):
            existing = [str(item) for item in merged[key]]  # type: ignore[index]
            if key == COMPRESSION_FALLBACK_KEY:
                # Verbatim lines, not a set: two chains cannot be unioned,
                # and the earlier one is the one still on disk.
                merged[key] = existing or [str(item) for item in value]
                continue
            merged[key] = sorted({*existing, *(str(item) for item in value)})
            continue
        merged[key] = value
    return merged


def managed_config_writes(
    before_text: str,
    after_text: str,
    *,
    config_path: str | Path,
    previous: object = None,
    now: str | None = None,
    released: Iterable[str] = (),
    display_released: bool = False,
) -> dict[str, object]:
    """Add this apply pass's record to the per-config map, keeping the others.

    Keyed by config path, and it has to be: `_sync_hermes_profiles` names
    the PRIMARY's store for every bot profile (`_profile_clone`), so one
    `omh setup` calls this once per Hermes home and every call writes the
    same `runtime/state.json`. A single-record slot would end the run
    holding the last profile's record, and the primary -- the home somebody
    is most likely to uninstall -- would silently fall back to the
    no-record subset.

    `released` names keys this pass took back from the config, which leave
    the record with them, `restores` entry included. The record only ever
    grows otherwise, so a key removed without this would still read as
    OMH's, and a later pass would take the same value back from the person
    who wrote it again (#1973). It has to cover `restores` as well as
    `keys`: a release that puts a person's own value back reads, to the
    before/after comparison below, like OMH writing that value over its own.

    `display_released` says this pass ran `release_managed_display`. The
    record keeps the first time it did, and stops naming the display
    containers, which the release has already dropped where they were OMH's.
    """
    before = managed_config_reading(before_text)
    after = managed_config_reading(after_text)
    prior = load_managed_config_writes(previous, config_path=config_path)
    prior_keys = prior.get("keys") if isinstance(prior.get("keys"), dict) else {}
    prior_containers = prior.get("containers_created") if isinstance(prior.get("containers_created"), list) else []
    released_at = str(prior.get(DISPLAY_RELEASED_FIELD) or "")
    if display_released and not released_at:
        released_at = now or utc_now()
    containers = sorted(
        path
        for path in {
            *(str(item) for item in prior_containers),
            *(
                path
                for path in config_container_paths(after_text) - config_container_paths(before_text)
                if path in MANAGED_CONTAINERS
            ),
        }
        if not (released_at and path in DISPLAY_CONTAINERS)
    )
    prior_restores = prior.get("restores") if isinstance(prior.get("restores"), dict) else {}
    dropped = {str(key) for key in released}
    restores = {**{str(k): str(v) for k, v in prior_restores.items()}, **_replaced_values(before, after)}  # type: ignore[union-attr]
    record = {
        "schema_version": MANAGED_CONFIG_WRITES_SCHEMA,
        "config_path": str(config_path),
        "recorded_at": now or utc_now(),
        "keys": {
            key: value
            for key, value in _merged_keys(dict(prior_keys), _written_keys(before, after)).items()  # type: ignore[arg-type]
            if key not in dropped
        },
        # The most recent replacement wins, and a pass that replaced nothing
        # leaves the entry alone. Only an explicit re-consent replaced a
        # value at all -- the unset-only default writer earlier versions ran
        # refused anything the person had set -- so a second entry means
        # they chose something new and then let OMH migrate them off THAT. Putting back the value from
        # before the first install would hand them a choice they had already
        # abandoned.
        "restores": {key: value for key, value in restores.items() if key not in dropped},
        "containers_created": containers,
    }
    if released_at:
        record[DISPLAY_RELEASED_FIELD] = released_at
    return {**_config_map(previous), str(config_path): record}


def _config_map(value: object) -> dict[str, object]:
    """The stored map, dropping any entry that is not a well-formed record."""
    if not isinstance(value, dict):
        return {}
    return {
        str(key): dict(entry)
        for key, entry in value.items()
        if isinstance(entry, dict)
        and entry.get("schema_version") == MANAGED_CONFIG_WRITES_SCHEMA
        and str(entry.get("config_path") or "") == str(key)
    }


def load_managed_config_writes(value: object, *, config_path: str | Path) -> dict[str, object]:
    """This config's own record out of the stored map, `{}` when there is none.

    The entry's `config_path` is checked against its key as well as against
    the caller's, so a map somebody hand-edited cannot make one profile's
    record answer for another's. Same rule the delegation route-restore
    record follows, and for the same reason: two Hermes profiles can share
    one OMH home.
    """
    return _config_map(value).get(str(config_path), {})  # type: ignore[return-value]


def reclaim_plugin_omh_home(config_text: str, record: object, *, config_path: str | Path) -> ConfigChange:
    """Take back the `omh_home` OMH wrote to a home that has since named its own store (#1973).

    The caller decides that the home chose: a bot profile whose `.env`
    names `OMH_HOME` after setup gave it the primary's store, which the
    setting outranks in the plugin's resolver. Only the value this config's
    record says OMH wrote goes; one OMH never wrote, or one changed since,
    is the person's and stays. `plugins.entries` goes with it only when the
    record says OMH created it and the removal left it empty -- every other
    container is the uninstall's business, not this one's.
    """
    owned = load_managed_config_writes(record, config_path=config_path)
    keys = owned.get("keys") if isinstance(owned.get("keys"), dict) else {}
    recorded = keys.get(PLUGIN_OMH_HOME_KEY) if isinstance(keys, dict) else None  # type: ignore[union-attr]
    if not isinstance(recorded, str) or not recorded:
        return ConfigChange(False, "no record of OMH writing plugins.entries.omh.settings.omh_home", config_text)
    removed = remove_plugin_omh_home(config_text, recorded)
    if not removed.changed:
        return removed
    created = owned.get("containers_created") if isinstance(owned.get("containers_created"), list) else []
    if "plugins.entries" not in created:  # type: ignore[operator]
        return removed
    cleanup = remove_childless_containers(removed.text, ["plugins.entries"])
    return ConfigChange(True, removed.message, cleanup.text)


def _unrecorded_row(key: str, present: bool, absent_detail: str) -> ReversalRow:
    """The row for a key with no record, which is only interesting if it is set.

    A key that is not in the config at all has nothing to attribute, so it
    reports `absent` like any other. Saying "left in place" about a key that
    is not there would fill the uninstall report with lines nobody can act
    on, which is how a report stops being read.
    """
    if not present:
        return ReversalRow(key, "absent", absent_detail)
    return ReversalRow(
        key,
        "unrecorded",
        "no record of OMH writing it and its value is not distinguishable from a user's own choice",
    )


def drop_emptied_containers(
    config_text: str,
    empty_before: set[str],
    *,
    recorded: Iterable[str] = (),
    record_is_complete: bool = False,
) -> ConfigChange:
    """Drop every managed container this uninstall created and then emptied.

    Two sources answer "did OMH create this container?", and they are not
    equal. `containers_created` in the write record answers it exactly. The
    `empty_before` comparison only answers "was it empty when the uninstall
    started?", which is a GUESS standing in for the record -- and it is wrong
    in one direction that costs a person their key: a container they already
    had, empty, before setup, which setup then filled. At uninstall time it
    has children, so it is not in `empty_before`; the reversal empties it;
    and the guess concludes OMH created it. The record says otherwise, and
    the record is right.

    So with a record the guess is not consulted at all -- `record_is_complete`
    is what says a record was found. Without one, which is the case #1767 is
    about, the guess is all there is, and its by-construction argument holds
    for what it does cover: a managed container this run emptied held nothing
    but OMH's entries, or it would still have a child.

    Every candidate goes in at once rather than only those childless at this
    moment, because `remove_childless_containers` re-reads the text after each
    removal and works deepest first. That is what lets a parent leave with its
    last child in one pass: `plugins:` becomes childless only once
    `plugins.enabled:` is gone, so a candidate set fixed beforehand could
    never name it.
    """
    named = {str(item) for item in recorded}
    guessed = set() if record_is_complete else set(MANAGED_CONTAINERS) - empty_before
    return remove_childless_containers(config_text, sorted(named | guessed))


def reverse_managed_config(
    config_text: str,
    record: dict[str, object],
    *,
    config_path: str | Path,
    text_before_removals: str | None = None,
) -> tuple[ConfigChange, list[ReversalRow]]:
    """Take back the managed keys this config still holds at OMH's values.

    Returns the accumulated change plus one row per managed key, so the
    uninstall report can name what it reversed, what it left with the person,
    and what it could not attribute at all.

    `text_before_removals` is the config as it stood before the CALLER's own
    removals, and the caller has to pass it when it removed anything first.
    Uninstall strips the managed skills directories before this runs, so by
    the time `config_text` arrives `skills.external_dirs` is already empty
    and "was it empty before?" answers yes about a container this uninstall
    emptied. It defaults to `config_text` for a caller that removed nothing.
    """
    owned = load_managed_config_writes(record, config_path=config_path)
    keys = owned.get("keys") if isinstance(owned.get("keys"), dict) else {}
    restores = owned.get("restores") if isinstance(owned.get("restores"), dict) else {}
    containers = owned.get("containers_created") if isinstance(owned.get("containers_created"), list) else []
    released = bool(owned.get(DISPLAY_RELEASED_FIELD))
    rows: list[ReversalRow] = []
    text = config_text
    changed = False
    baseline = config_text if text_before_removals is None else text_before_removals
    empty_before = childless_containers(baseline)

    for key in REVERSIBLE_KEYS:
        if released and key in DISPLAY_KEYS:
            rows.append(_released_row(text, key))
            continue
        recorded = keys.get(key) if isinstance(keys, dict) else None  # type: ignore[union-attr]
        previous = str(restores.get(key) or "") if isinstance(restores, dict) else ""  # type: ignore[union-attr]
        change, row = _reverse_one(text, key, recorded, previous)
        if change.changed:
            text = change.text
            changed = True
        rows.append(row)

    cleanup = drop_emptied_containers(
        text,
        empty_before,
        recorded=(str(item) for item in containers),
        record_is_complete=bool(owned),
    )
    if cleanup.changed:
        text = cleanup.text
        changed = True

    if not changed:
        return ConfigChange(False, "no managed config key to reverse", text), rows
    reversed_keys = [row.key for row in rows if row.status == "reversed"]
    message = f"reversed {', '.join(reversed_keys)}" if reversed_keys else cleanup.message
    return ConfigChange(True, message, text), rows


def _released_row(config_text: str, key: str) -> ReversalRow:
    """A display key after `release_managed_display` ran: never OMH's again."""
    if not config_names_key(config_text, key):
        return ReversalRow(key, "absent", f"{key} is not set")
    return ReversalRow(key, "kept", f"{key} is the person's own; OMH released its display keys")


def release_managed_display(
    config_text: str,
    record: object,
    *,
    config_path: str | Path,
) -> tuple[ConfigChange, list[ReversalRow]]:
    """Take back the display keys OMH wrote, once per config, so bare `hermes` is stock Hermes.

    The display half of `reverse_managed_config`, under the same per-key
    rules, because it is the same question asked on setup and update instead
    of on uninstall: a recorded value still on disk goes, or goes back to
    the value consent replaced; a value the person changed since stays; an
    `omh*` skin is OMH's with or without a record; an unrecorded
    `display.interface` or section stays, because nothing says OMH wrote
    it. A display container goes when OMH created it (or, with no record,
    when this pass emptied it), exactly as uninstall decides.

    Never `reverse_managed_config` itself: that reverses `plugins.enabled`
    and `memory.provider` too, which on an update would switch OMH off.

    Once only. The caller records `display_released_at` with the pass, and
    from then on this changes nothing: OMH writes no display key any more,
    so a `display.skin: omh-crimson` that appears later is one the person
    chose, and taking it back on every update would undo that choice each
    time (the #1973 shape).

    Except when a row comes back `refused`: the editor would not touch that
    key for its YAML shape, and the record or the OMH skin name says its
    value may still be OMH's (`_refused_or_kept`). The caller must not
    record the release on that pass, and must keep the key in the record so
    the next pass asks again.
    """
    owned = load_managed_config_writes(record, config_path=config_path)
    if owned.get(DISPLAY_RELEASED_FIELD):
        return ConfigChange(False, "display keys were already released", config_text), []
    keys = owned.get("keys") if isinstance(owned.get("keys"), dict) else {}
    restores = owned.get("restores") if isinstance(owned.get("restores"), dict) else {}
    containers = owned.get("containers_created") if isinstance(owned.get("containers_created"), list) else []
    empty_before = childless_containers(config_text)
    rows: list[ReversalRow] = []
    text = config_text
    for key in DISPLAY_KEYS:
        recorded = keys.get(key) if isinstance(keys, dict) else None  # type: ignore[union-attr]
        previous = str(restores.get(key) or "") if isinstance(restores, dict) else ""  # type: ignore[union-attr]
        change, row = _reverse_one(text, key, recorded, previous)
        text = change.text
        rows.append(_refused_or_kept(text, row, recorded) if row.status == "kept" else row)
    # Only the display containers are candidates: this pass removed nothing
    # else, so no other container can have lost its last child here.
    named = {str(item) for item in containers if str(item) in DISPLAY_CONTAINERS}  # type: ignore[union-attr]
    guessed = set() if owned else set(DISPLAY_CONTAINERS) - empty_before
    cleanup = remove_childless_containers(text, sorted(named | guessed))
    text = cleanup.text
    reversed_keys = [row.key for row in rows if row.status == "reversed"]
    if text == config_text:
        return ConfigChange(False, "no display key of OMH's to release", config_text), rows
    message = f"released {', '.join(reversed_keys)}" if reversed_keys else cleanup.message
    return ConfigChange(True, message, text), rows


def _refused_or_kept(config_text: str, row: ReversalRow, recorded: object) -> ReversalRow:
    """A `kept` display row, or `refused` when the shape stopped the edit and the value may still be OMH's.

    `kept` from the removers covers two different outcomes: the value is no
    longer the one OMH wrote, or the editor refused the YAML shape before
    looking (a quoted key anywhere in the file, a dotted or duplicate
    `display`, anchors, tags, a BOM). Only the first leaves nothing of OMH's
    behind. The value is read here without the editor's guards.

    With a record naming the key, a value that reads as the person's own
    keeps the row `kept`; one that reads as OMH's, or cannot be read at
    all, is `refused`. A key set in more than one place (a second `skin`
    in the block, a second `display`, a dotted key beside the block) cannot
    be read either: the reader returns the first value, and Hermes may
    resolve another (`display_key_named_twice`), so the first reading as
    the person's says nothing of the one Hermes uses. Without a record,
    only an OMH skin name makes it `refused`, among any of the values when
    the key is set more than once, since the one Hermes resolves may be an
    OMH name behind a first one that is not. OMH's writers never wrote the
    flow, dotted or duplicate shapes the editor refuses, so an unreadable
    value nobody recorded, such as a fresh install's
    `display: {skin: mytheme}`, is the person's.
    """
    leaf = row.key.rpartition(".")[2]
    refusal = display_edit_refusal(config_text, leaf)
    if not refusal:
        return row
    # The value is read past a leading BOM, as Hermes' YAML loader and
    # `config_names_key` read it; the editor's refusal of the file stands.
    readable = config_text.removeprefix("\ufeff")
    if recorded:
        may_be_omhs = display_key_named_twice(readable, leaf) or not _reads_as_persons(
            readable, row.key, recorded
        )
    else:
        may_be_omhs = row.key == DISPLAY_SKIN_KEY and any(
            is_omh_skin_name(_plain_scalar(value)) for value in display_skin_selections(readable)
        )
    return ReversalRow(row.key, "refused", refusal) if may_be_omhs else row


def _plain_scalar(value: str) -> str:
    """`value`, or "" when it opens with a YAML node property or alias the readers return verbatim.

    `skin: !!str omh-crimson` and `skin: &s omh-crimson` read as
    "!!str omh-crimson" and "&s omh-crimson", which match no OMH skin name
    while Hermes resolves the skin `omh-crimson`. Such a value cannot be
    read here at all, so it never counts as the person's own.
    """
    return "" if value.startswith(("&", "!", "*")) else value


def _reads_as_persons(config_text: str, key: str, recorded: object) -> bool:
    if key == DISPLAY_INTERFACE_KEY:
        current = _plain_scalar(display_interface_selection(config_text))
        return bool(current) and current != recorded
    if key == DISPLAY_SKIN_KEY:
        current = _plain_scalar(display_skin_selection(config_text))
        return bool(current) and not is_omh_skin_name(current)
    # The sections reader returns nothing under the guards the editor
    # applies, so a refused sections key never reads as anybody's.
    current = display_sections_selection(config_text)
    wanted = [str(name) for name in recorded] if isinstance(recorded, list) else []
    return bool(current) and not any(current.get(name) == _SECTION_VALUE for name in wanted)


def _reverse_one(
    config_text: str,
    key: str,
    recorded: object,
    previous: str = "",
) -> tuple[ConfigChange, ReversalRow]:
    if key == DISPLAY_INTERFACE_KEY:
        if not isinstance(recorded, str) or not recorded:
            # `tui` is one of Hermes' own two values; without the record
            # there is nothing that says OMH set it rather than the person.
            present = config_names_key(config_text, DISPLAY_INTERFACE_KEY)
            return ConfigChange(False, "", config_text), _unrecorded_row(
                key, present, "display.interface is not set"
            )
        return _row_from(key, revert_display_scalar(config_text, "interface", recorded, previous))

    if key == DISPLAY_SKIN_KEY:
        expected = recorded if isinstance(recorded, str) and recorded else ""
        current = display_skin_selection(config_text)
        if expected and current != expected and is_omh_skin_name(current):
            # `omh theme use` used to write `display.skin` without touching
            # the record, so a recorded `omh` can be on disk as
            # `omh-crimson`. The name is OMH's by construction, the same
            # rule the record-less branch below applies.
            expected = current
        if not expected:
            if not current:
                if config_names_key(config_text, DISPLAY_SKIN_KEY):
                    return ConfigChange(False, "", config_text), ReversalRow(
                        key, "kept", "display.skin is in a shape OMH does not edit; leaving it alone"
                    )
                return ConfigChange(False, "", config_text), ReversalRow(key, "absent", "display.skin is not set")
            if not is_omh_skin_name(current):
                return ConfigChange(False, "", config_text), ReversalRow(
                    key, "kept", f"display.skin is {current}, which OMH did not write"
                )
            # An OMH skin name is OMH's by construction even with no record:
            # `omh` and the `omh-*` themes are this product's own names, and
            # until the display release setup, update and `omh theme use`
            # were the only things that wrote them. After it, nothing of
            # OMH's does, which is why neither caller asks this question
            # again once `display_released_at` is recorded.
            expected = current
        return _row_from(key, revert_display_scalar(config_text, "skin", expected, previous))

    if key == MEMORY_PROVIDER_KEY:
        # `omh` in this slot is OMH's by construction: Hermes runs one
        # external provider and `set_memory_provider` refuses to take the
        # slot from another product, so OMH is the only thing that writes it.
        expected = recorded if isinstance(recorded, str) and recorded else MEMORY_PROVIDER_NAME
        return _row_from(key, remove_memory_provider(config_text, expected))

    if key == PLUGINS_ENABLED_KEY:
        names = [str(item) for item in recorded] if isinstance(recorded, list) and recorded else [PLUGIN_NAME]
        change = ConfigChange(False, f"{PLUGIN_NAME} is not in plugins.enabled", config_text)
        removed: list[str] = []
        for name in names:
            step = remove_plugin_enabled(change.text, name)
            if step.changed:
                removed.append(name)
            # Keep the last step's message either way. Seeding this loop with
            # "not in plugins.enabled" and only overwriting it on success
            # threw away every refusal the remover produced, so a guard that
            # correctly declined to edit an anchored list was reported as
            # nothing being there.
            change = ConfigChange(step.changed or change.changed, step.message, step.text)
        if removed:
            return change, ReversalRow(key, "reversed", f"removed {', '.join(sorted(removed))}")
        return _row_from(key, change, name=names[0] if names else PLUGIN_NAME)

    if key == DISPLAY_SECTIONS_KEY:
        if not isinstance(recorded, list) or not recorded:
            # Hermes' own default for these three is `expanded`, so a
            # `collapsed` value says somebody chose it and nothing says who.
            present = config_names_key(config_text, DISPLAY_SECTIONS_KEY)
            return ConfigChange(False, "", config_text), _unrecorded_row(
                key, present, "display.sections is not set"
            )
        current = display_sections_selection(config_text)
        wanted = [str(name) for name in recorded]
        kept = sorted(name for name in wanted if current.get(name, "") not in {"", _SECTION_VALUE})
        change = remove_display_sections(config_text, wanted, _SECTION_VALUE)
        kept_names = ", ".join(kept)
        if change.changed:
            detail = change.message
            if kept:
                detail = f"{detail}; kept user value(s) for {kept_names}"
            return change, ReversalRow(key, "reversed", detail, kept_names)
        if kept:
            return change, ReversalRow(key, "kept", f"user value(s) for {kept_names}", kept_names)
        return _row_from(key, change)

    if key == COMPRESSION_FALLBACK_KEY:
        if not isinstance(recorded, list) or not recorded:
            # Derived from the person's own providers, so the chain carries
            # no mark saying OMH wrote it.
            present = config_names_key(config_text, COMPRESSION_FALLBACK_KEY)
            return ConfigChange(False, "", config_text), _unrecorded_row(
                key, present, "auxiliary.compression.fallback_chain is not set"
            )
        return _row_from(key, remove_compression_fallback_chain(config_text, [str(line) for line in recorded]))

    if key == PLUGIN_OMH_HOME_KEY:
        if not isinstance(recorded, str) or not recorded:
            # Before #1960 setup never wrote this key, so a value with no
            # record is a store somebody chose -- a bot profile's own
            # dispatch store is exactly that (#1679).
            present = config_names_key(config_text, PLUGIN_OMH_HOME_KEY)
            return ConfigChange(False, "", config_text), _unrecorded_row(
                key, present, "plugins.entries.omh.settings.omh_home is not set"
            )
        return _row_from(key, remove_plugin_omh_home(config_text, recorded))

    raise ValueError(f"unknown managed config key: {key}")


def _row_from(key: str, change: ConfigChange, *, name: str = "") -> tuple[ConfigChange, ReversalRow]:
    """Classify one key's outcome from the config, never from the message text.

    An earlier version searched `ConfigChange.message` for six English
    fragments to tell `absent` from `kept`. Two things went wrong with that,
    and the second was not hypothetical: rephrasing any remover silently
    reclassified its row, and a refusal whose wording happened to contain
    "line not found" was reported as "nothing here", so a key that was
    present and deliberately untouched told the person nothing at all. The
    question "is this key still in the file" has an answer in the file.
    """
    if change.changed:
        return change, ReversalRow(key, "reversed", change.message)
    if not config_names_key(change.text, key, name=name):
        return change, ReversalRow(key, "absent", change.message)
    return change, ReversalRow(key, "kept", change.message)


def config_names_key(config_text: str, key: str, *, name: str = "") -> bool:
    """Whether the document still names this managed key, in any shape.

    Deliberately looser than the readers the writers use: those return "" for
    a shape they refuse to edit, which is the right answer for "may I write
    here" and the wrong one for "is anything left". A dotted
    `memory.provider: omh` that the guard refuses is present, and saying so
    is the whole point of the uninstall report.

    A leading BOM is read through. Hermes' YAML loader skips it, so a key
    on the line right after it is there. The editor refuses the whole file
    for it, and the strict readers do not see past it, so the release reads
    the value past it too (`_refused_or_kept`, setup's `_selected_skins`).
    """
    config_text = config_text.removeprefix("\ufeff")
    if key == PLUGINS_ENABLED_KEY:
        if not plugin_enablement_is_readable(config_text):
            # The one answer this row must not give over a node OMH did not
            # read. `absent` says nothing is left here, and a `plugins` node
            # written in a form the reader walks past leaves the same empty
            # list a config enabling nothing leaves, so the row said the
            # person's own entry was gone while the message beside it said
            # the node was left alone (#1814).
            return True
        return (name or PLUGIN_NAME) in plugin_enablement(config_text)["enabled"]
    if key == COMPRESSION_FALLBACK_KEY:
        return bool(compression_settings(config_text).get("has_fallback_chain"))
    if key == PLUGIN_OMH_HOME_KEY:
        try:
            return runtime_paths.omh_home_setting(config_text)[0]
        except runtime_paths.RuntimeBindingError:
            # A shape the plugin's scan refuses may still carry the key.
            return True
    section, _, leaf = key.rpartition(".")
    return _names_section_key(config_text, section, leaf)


def _names_section_key(config_text: str, section: str, key: str) -> bool:
    dotted = f"{section}.{key}"
    in_section = False
    for line in config_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" "):
            if references_mapping_key(line, dotted):
                return True
            # Only a column-0 line whose own root key is `section` opens it.
            # The wider `references_mapping_key` also matches `section` named
            # inside another root key's flow mapping, which would read
            # `webhooks: {routes: {a: {skills: [x]}}}` as opening `skills`
            # and report a `skills.<key>` that no root block carries (#2829).
            in_section = references_top_level_section(line, section)
            # A flow mapping carries the child on the section's own line, so
            # `display: {skin: omh}` names `display.skin` without ever
            # opening a block. The editors refuse that shape; the report
            # still has to say the key is there.
            if in_section and references_mapping_key(line, key):
                return True
            continue
        if in_section and references_mapping_key(line, key):
            return True
    return False


def dry_run_reversal_keys(rows: list[ReversalRow]) -> list[str]:
    """The keys a real run would reverse, for `omh uninstall --dry-run`."""
    return [row.key for row in rows if row.status == "reversed"]
