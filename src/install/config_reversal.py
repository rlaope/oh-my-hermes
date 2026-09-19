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
"""

from __future__ import annotations

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
    display_interface_selection,
    display_sections_selection,
    display_skin_selection,
    external_dirs,
    memory_provider_selection,
    plugin_enablement,
    references_mapping_key,
    childless_containers,
    remove_childless_containers,
    revert_display_scalar,
    remove_display_sections,
    remove_memory_provider,
    remove_plugin_enabled,
)
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
    "skills",
    "skills.external_dirs",
)

_SECTION_VALUE = "collapsed"

# The two keys consent lets OMH write OVER a value the person already had.
# Everything else it writes is unset-only, so its inverse is a removal;
# these two need the prior value put back or the person loses a choice they
# made before they ever installed OMH.
RESTORABLE_KEYS: tuple[str, ...] = (DISPLAY_INTERFACE_KEY, DISPLAY_SKIN_KEY)


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
    }


def _written_keys(before: dict[str, object], after: dict[str, object]) -> dict[str, object]:
    written: dict[str, object] = {}
    for key in (DISPLAY_INTERFACE_KEY, DISPLAY_SKIN_KEY, MEMORY_PROVIDER_KEY):
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
    the second run the writers report "already tui" and change nothing. A
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
) -> dict[str, object]:
    """Add this apply pass's record to the per-config map, keeping the others.

    Keyed by config path, and it has to be: `_sync_hermes_profiles` names
    the PRIMARY's store for every bot profile (`_profile_clone`), so one
    `omh setup` calls this once per Hermes home and every call writes the
    same `runtime/state.json`. A single-record slot would end the run
    holding the last profile's record, and the primary -- the home somebody
    is most likely to uninstall -- would silently fall back to the
    no-record subset.
    """
    before = managed_config_reading(before_text)
    after = managed_config_reading(after_text)
    prior = load_managed_config_writes(previous, config_path=config_path)
    prior_keys = prior.get("keys") if isinstance(prior.get("keys"), dict) else {}
    prior_containers = prior.get("containers_created") if isinstance(prior.get("containers_created"), list) else []
    containers = sorted(
        {
            *(str(item) for item in prior_containers),
            *(
                path
                for path in config_container_paths(after_text) - config_container_paths(before_text)
                if path in MANAGED_CONTAINERS
            ),
        }
    )
    prior_restores = prior.get("restores") if isinstance(prior.get("restores"), dict) else {}
    record = {
        "schema_version": MANAGED_CONFIG_WRITES_SCHEMA,
        "config_path": str(config_path),
        "recorded_at": now or utc_now(),
        "keys": _merged_keys(dict(prior_keys), _written_keys(before, after)),  # type: ignore[arg-type]
        # The most recent replacement wins, and a pass that replaced nothing
        # leaves the entry alone. Only an explicit re-consent replaces a
        # value at all -- `ensure_tui_interface` refuses anything the person
        # has set -- so a second entry means they chose something new and
        # then let OMH migrate them off THAT. Putting back the value from
        # before the first install would hand them a choice they had already
        # abandoned.
        "restores": {**{str(k): str(v) for k, v in prior_restores.items()}, **_replaced_values(before, after)},  # type: ignore[union-attr]
        "containers_created": containers,
    }
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


def reverse_managed_config(
    config_text: str,
    record: dict[str, object],
    *,
    config_path: str | Path,
) -> tuple[ConfigChange, list[ReversalRow]]:
    """Take back the managed keys this config still holds at OMH's values.

    Returns the accumulated change plus one row per managed key, so the
    uninstall report can name what it reversed, what it left with the person,
    and what it could not attribute at all.
    """
    owned = load_managed_config_writes(record, config_path=config_path)
    keys = owned.get("keys") if isinstance(owned.get("keys"), dict) else {}
    restores = owned.get("restores") if isinstance(owned.get("restores"), dict) else {}
    containers = owned.get("containers_created") if isinstance(owned.get("containers_created"), list) else []
    rows: list[ReversalRow] = []
    text = config_text
    changed = False
    empty_before = childless_containers(config_text)

    for key in REVERSIBLE_KEYS:
        recorded = keys.get(key) if isinstance(keys, dict) else None  # type: ignore[union-attr]
        previous = str(restores.get(key) or "") if isinstance(restores, dict) else ""  # type: ignore[union-attr]
        change, row = _reverse_one(text, key, recorded, previous)
        if change.changed:
            text = change.text
            changed = True
        rows.append(row)

    # A managed container this pass emptied is OMH's to drop even with no
    # record: everything that was in it was OMH's, or it would still have a
    # child. One the person already kept empty is left exactly as it was.
    emptied = {
        path
        for path in childless_containers(text)
        if path in MANAGED_CONTAINERS and path not in empty_before
    }
    cleanup = remove_childless_containers(text, sorted({*(str(item) for item in containers), *emptied}))
    if cleanup.changed:
        text = cleanup.text
        changed = True

    if not changed:
        return ConfigChange(False, "no managed config key to reverse", text), rows
    reversed_keys = [row.key for row in rows if row.status == "reversed"]
    message = f"reversed {', '.join(reversed_keys)}" if reversed_keys else cleanup.message
    return ConfigChange(True, message, text), rows


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
        if not expected:
            current = display_skin_selection(config_text)
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
            # `omh theme use <name>` is the only thing that writes them.
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
    """
    if key == PLUGINS_ENABLED_KEY:
        return (name or PLUGIN_NAME) in plugin_enablement(config_text)["enabled"]
    if key == COMPRESSION_FALLBACK_KEY:
        return bool(compression_settings(config_text).get("has_fallback_chain"))
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
            in_section = references_mapping_key(line, section)
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
