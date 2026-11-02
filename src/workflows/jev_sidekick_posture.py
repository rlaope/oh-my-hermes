"""Which Jev-class plugins a Hermes home holds, read and never run.

Jev is a non-generative model, so OMH cannot route it as an executor, and it
never calls a third-party Jev plugin. What an operator still needs to know is whether something
on this machine calls it on their behalf, and whether that something declares
a surface OMH also declares -- most sharply `pre_llm_call`, where OMH injects
its route hint and a Jev skill router nominates a skill, so a message can reach
the model carrying two nominations.

This builder answers that from three local reads and nothing else: the plugin
directories under ``$HERMES_HOME/plugins``, Hermes' ``plugins.enabled`` list,
and the NAMES (never the values) in ``$HERMES_HOME/.env``. It imports no
plugin, spawns nothing, opens no socket, and writes nothing anywhere. The
`omh_jev_ask` block beside it reports OMH's own opt-in Jev tool from names,
the operator setting, and the local ask ledger, and it reads no value either.

What the tiers mean, and what they do not. ``installed`` means a directory
with a manifest exists. ``enabled`` means Hermes' config lists the name.
``credential_name_present`` means a variable name a Jev plugin declares as its
route appears in the env file. The ladder is monotonic -- each tier requires
the one below it -- so a credential name beside a plugin the operator disabled
reports ``installed``, and ``credential_names_present`` carries the names
regardless so nothing is lost by the collapse. None of the three is evidence
that Jev is served, that the plugin ran, or that any request left the machine.

Every read here can fail to happen, and a read that did not happen is reported
as itself rather than as its commonest result. The manifest reader is the
bounded subset reader in ``plugin_manifest_yaml``, which refuses a construct it
does not model rather than guessing; that refusal is carried, not swallowed,
under ``skipped`` when it left the plugin unclassified and under the plugin's
own ``unreadable_declarations`` when it did not. Enablement is the same rule in
a second place: ``enablement`` is ``unknown``, with a reason, whenever OMH did
not read Hermes' ``plugins`` node or could not establish the name Hermes would
have to list, because "nothing enables it" and "nobody read it" are different
facts about a machine.

Names arriving from the filesystem are untrusted input. A plugin directory name
is chosen by whoever created the directory, never passes the manifest reader's
control-character ban, and lands in a report an operator pastes into a bug
report, so it is stripped of control characters and bounded before it reaches
any payload field or message.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ..install.config_adapter import plugin_enablement_is_readable, plugin_is_enabled
from ..plugin_bundle.omh.jev_ask_store import (
    OPENROUTER_SETTING_KEY,
    ROUTE_NONE,
    ledger_summary,
    openrouter_route_enabled,
    route_available_by_names,
    settings_path,
)
from ..plugin_bundle.omh.jev_sidekick import JEV_CREDENTIAL_ENV_NAMES, classify_plugin
from ..plugin_bundle.omh.provider_detection import env_key_names
from ..plugin_bundle.omh.todo_store import strip_control_characters
from .plugin_hook_contract import MANIFEST_FILENAME
from .plugin_manifest_yaml import (
    ManifestEntry,
    PluginManifestFormatError,
    entry_values,
    read_plugin_manifest_entries,
)

JEV_SIDEKICK_POSTURE_SCHEMA_VERSION: Final = "jev_sidekick_posture/v1"
TYPESAFE_BASE_URL_ENV_NAME: Final = "TYPESAFE_BASE_URL"
JEV_ENV_NAMES: Final = JEV_CREDENTIAL_ENV_NAMES | {TYPESAFE_BASE_URL_ENV_NAME}

# Monotonic, lowest first. `credential_name_present` sits above `enabled`
# because a credential name matters only for a plugin Hermes will load.
POSTURE_STATUSES: Final = ("absent", "installed", "enabled", "credential_name_present")

ENABLEMENT_ENABLED: Final = "enabled"
ENABLEMENT_NOT_ENABLED: Final = "not enabled"
# Not a third degree of enablement: the absence of a read. Carried beside a
# reason so a caller can say which read did not happen instead of picking one.
ENABLEMENT_UNKNOWN: Final = "unknown"

NAME_FIELD: Final = "name"
TOOLS_FIELD: Final = "provides_tools"
HOOKS_FIELD: Final = "provides_hooks"
# The manifest fields that can arrive unread, in the order a caller should
# report them. Exported so a caller writing one sentence per field can pin its
# own coverage against this vocabulary rather than against a list it copied.
UNREADABLE_DECLARATION_FIELDS: Final = (NAME_FIELD, TOOLS_FIELD, HOOKS_FIELD)

# The audit reads an untrusted local directory, so both dimensions are bounded
# before anything is interpreted. A home past either bound is not a failure --
# the entries past it are simply reported as unread.
MAX_PLUGIN_DIRECTORIES: Final = 512
MAX_MANIFEST_BYTES: Final = 256 * 1024
# Hermes' own config, read for one list. Bounded like the manifests beside it:
# it is the same file class read at the same trust level, and a config past
# this bound leaves enablement unknown rather than reported as empty.
MAX_CONFIG_BYTES: Final = 256 * 1024
# What a plugin name may cost a report line. Long enough for every catalog name
# several times over; short enough that a directory named to fill a terminal
# cannot. A name this truncates is no longer the name Hermes would match, which
# is why truncation also leaves enablement unknown.
MAX_PLUGIN_NAME_CHARS: Final = 128

# A sentence, not a fragment: it closes the doctor message after a full stop
# as well as sitting in the payload, and a fragment reads as a broken sentence
# in the surface an operator actually sees.
CLAIM_BOUNDARY: Final = (
    "Presence of a plugin directory, an enabled name, or a credential NAME is not evidence that Jev is "
    "served, that the plugin ran, or that any request left the machine; this check never reads credential values."
)


OMH_JEV_ASK_DISCLOSURE: Final = (
    "omh_jev_ask sends `state` and the question text to the route's host, billed to the user's account, "
    "only when the user asks for Jev in that turn; whatever a skill puts in `state` (commands, a working "
    "directory, file paths, source diffs, test or error output, file contents) is sent, and a configured HTTPS "
    "proxy sees the destination host."
)


def omh_jev_ask_posture(
    hermes_home: Path, omh_home: Path, environ: Any = None
) -> dict[str, Any]:
    """OMH's own Jev tool, read from variable NAMES, the operator setting, and the ask ledger.

    Kept beside, not inside, the third-party posture rule above: a
    `TYPESAFE_API_KEY` exists only for Jev, so its name is read whether or
    not a plugin was detected, while an OpenRouter key counts only when the
    operator setting turned that route on. No value is read.
    """
    names = set(env_key_names(Path(hermes_home), environ, allowed=JEV_ENV_NAMES))
    credential_names = names & JEV_CREDENTIAL_ENV_NAMES
    route = route_available_by_names(Path(omh_home), credential_names)
    return {
        "route_available": route,
        "typesafe_base_url_configured": TYPESAFE_BASE_URL_ENV_NAME in names,
        "openrouter_setting": openrouter_route_enabled(Path(omh_home)),
        "setting_path": str(settings_path(Path(omh_home))),
        "setting_key": OPENROUTER_SETTING_KEY,
        **ledger_summary(Path(omh_home)),
        "disclosure": OMH_JEV_ASK_DISCLOSURE,
    }


def omh_jev_ask_sentence(block: dict[str, Any]) -> str:
    """One line for the doctor message: the route, the ledger tier, and what is sent."""
    route = str(block.get("route_available", ROUTE_NONE))
    if route == ROUTE_NONE:
        head = (
            "omh_jev_ask: no route (set TYPESAFE_API_KEY, or OPENROUTER_API_KEY plus "
            f"{{\"{OPENROUTER_SETTING_KEY}\": true}} in {block.get('setting_path', '')})"
        )
    else:
        custom_base = route == "typesafe" and bool(block.get("typesafe_base_url_configured"))
        suffix = " (custom base URL configured)" if custom_base else ""
        head = f"omh_jev_ask: route {route}{suffix} by variable name"
    calls = int(block.get("ledger_calls", 0) or 0)
    tier = f"{calls} ask(s) recorded, last status {block.get('last_status')}" if calls else "no ask recorded"
    return f"{head}; {tier}; {OMH_JEV_ASK_DISCLOSURE.rstrip('.')}"


def build_jev_sidekick_posture(hermes_home: Path, omh_home: Path | None = None) -> dict[str, Any]:
    """Read the Jev-class plugin posture of one Hermes home.

    Read-only by construction: every path below is opened for reading and the
    function returns a plain dict. A home that does not exist is ``absent``,
    not an error, because no Hermes install is the ordinary state for a
    machine that has never run one.
    """
    home = Path(hermes_home)
    enablement = _read_enablement(home)
    plugins: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for directory in _plugin_directories(home, skipped):
        entry = _classified_plugin(directory, skipped, enablement)
        if entry is not None:
            plugins.append(entry)
    plugins.sort(key=lambda item: str(item["name"]))
    credential_names: list[str] = []
    if plugins:
        # Only consulted once a Jev-class plugin is detected: OPENROUTER_API_KEY
        # on its own is an OpenRouter account, not a Jev signal, and reporting
        # it as one would make every OpenRouter user look like a Jev user.
        credential_names = env_key_names(home, allowed=JEV_CREDENTIAL_ENV_NAMES)
    posture: dict[str, Any] = {
        "schema_version": JEV_SIDEKICK_POSTURE_SCHEMA_VERSION,
        "status": _status(plugins, credential_names),
        "plugins": plugins,
        "credential_names_present": credential_names,
        "skipped": skipped,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    if omh_home is not None:
        import os

        posture["omh_jev_ask"] = omh_jev_ask_posture(home, Path(omh_home), os.environ)
    return posture


def posture_overlaps(posture: dict[str, Any]) -> list[str]:
    """Every plugin in *posture* that declares a surface OMH also declares.

    Two independent kinds of overlap, and either is enough: a hook both the
    plugin's installed manifest and the OMH bridge declare, and an OMH surface
    the plugin's catalog entry says it decides for. Returned as plugin names so
    a caller can name them without re-deriving the rule.
    """
    names: list[str] = []
    for entry in posture.get("plugins", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("hook_overlap") or entry.get("overlap"):
            names.append(str(entry.get("name", "")))
    return names


def posture_unestablished_hook_overlap(posture: dict[str, Any]) -> list[str]:
    """Every plugin whose hook overlap with OMH could not be established.

    An empty ``hook_overlap`` means one of two different things, and a caller
    that conflates them states a fact it does not hold. When the manifest's
    ``provides_hooks`` was read, it means the plugin and the OMH bridge declare
    no hook in common. When it was not -- an inline flow sequence the bounded
    subset does not model -- it means nobody looked, and `[pre_llm_call]` and
    `[]` are the same bytes to this reader.
    """
    names: list[str] = []
    for entry in posture.get("plugins", []):
        if not isinstance(entry, dict):
            continue
        if HOOKS_FIELD in entry.get("unreadable_declarations", []):
            names.append(str(entry.get("name", "")))
    return names


def posture_unknown_enablement(posture: dict[str, Any]) -> list[str]:
    """Every plugin whose enablement OMH did not read.

    Same rule as the hook overlap above, applied to Hermes' config: a plugin
    OMH did not find in `plugins.enabled` is "not enabled" only when OMH read
    that list.
    """
    names: list[str] = []
    for entry in posture.get("plugins", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("enablement") == ENABLEMENT_UNKNOWN:
            names.append(str(entry.get("name", "")))
    return names


@dataclass(frozen=True, slots=True)
class _Enablement:
    """Hermes' `plugins` node, and whether OMH read it.

    `unread_reason` is empty exactly when `config_text` may be answered from.
    It is carried rather than collapsed to a bool so the caller can say which
    read did not happen: a config OMH could not open and a config written in a
    form the block reader walks past are different repairs.
    """

    config_text: str
    unread_reason: str

    def state(self, name: str, name_established: bool) -> tuple[str, str]:
        if self.unread_reason:
            return ENABLEMENT_UNKNOWN, self.unread_reason
        if not name_established:
            return ENABLEMENT_UNKNOWN, "OMH could not establish the name Hermes would have to list"
        if plugin_is_enabled(self.config_text, name):
            return ENABLEMENT_ENABLED, ""
        return ENABLEMENT_NOT_ENABLED, ""


def _read_enablement(hermes_home: Path) -> _Enablement:
    config_text, whole = _read_bounded_text(hermes_home / "config.yaml", MAX_CONFIG_BYTES)
    if not whole:
        return _Enablement("", "Hermes' config could not be read whole")
    if not plugin_enablement_is_readable(config_text):
        return _Enablement("", "Hermes' config declares `plugins` in a form OMH does not read")
    return _Enablement(config_text, "")


def _status(plugins: list[dict[str, Any]], credential_names: list[str]) -> str:
    if not plugins:
        return "absent"
    if not any(entry.get("enablement") == ENABLEMENT_ENABLED for entry in plugins):
        return "installed"
    return "credential_name_present" if credential_names else "enabled"


def _plugin_directories(hermes_home: Path, skipped: list[dict[str, str]]) -> list[Path]:
    plugins_dir = hermes_home / "plugins"
    try:
        children = sorted(plugins_dir.iterdir(), key=lambda item: item.name)
    except FileNotFoundError:
        # No plugins directory is the ordinary pre-install state, not a read
        # that failed.
        return []
    except OSError as error:
        skipped.append(
            {
                "plugin": _printable_name(plugins_dir.name),
                "reason": f"plugins directory is unreadable: {type(error).__name__}",
            }
        )
        return []
    directories: list[Path] = []
    # The budget counts the entries that become a plugin directory or a
    # reported one, not every entry: a loose file under `plugins/` is neither,
    # and counting it would spend a directory budget on something that can
    # never be a plugin and print `plugins` where a plugin name belongs. Loose
    # files still cost one `lstat` each, which is what `iterdir` already paid.
    accounted = 0
    for index, child in enumerate(children):
        if accounted >= MAX_PLUGIN_DIRECTORIES:
            # What is reported is the first entry the sweep did not reach.
            # Naming the container instead would put `plugins` in a report
            # that reads as a list of plugins.
            remaining = len(children) - index
            tail = "" if remaining == 1 else f" and {remaining - 1} more"
            skipped.append(
                {
                    "plugin": _printable_name(child.name),
                    "reason": f"the sweep stopped at {MAX_PLUGIN_DIRECTORIES} plugin directories; this entry{tail} was not read",
                }
            )
            break
        if child.is_symlink():
            # A symlinked plugin directory is reported rather than followed:
            # resolving one reads a path outside the home OMH was asked about.
            skipped.append({"plugin": _printable_name(child.name), "reason": "symlinked plugin directory was not followed"})
            accounted += 1
            continue
        if child.is_dir():
            directories.append(child)
            accounted += 1
    return directories


def _classified_plugin(directory: Path, skipped: list[dict[str, str]], enablement: _Enablement) -> dict[str, Any] | None:
    label = _printable_name(directory.name)
    manifest_path = directory / MANIFEST_FILENAME
    try:
        if manifest_path.is_symlink():
            # The file-level twin of the directory guard above, and refused for
            # the same reason: `is_file()` and a read both resolve the link, so
            # without this the escape the directory guard closes is open one
            # level down and nothing says the read left the home.
            skipped.append({"plugin": label, "reason": "symlinked plugin manifest was not followed"})
            return None
        if not manifest_path.is_file():
            return None
        # Bounded at the read rather than at a preceding `stat`: a file
        # reporting `st_size == 0` and a file that grows between the two calls
        # both walk past a size check, and neither walks past a short read.
        with manifest_path.open("rb") as handle:
            raw = handle.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            skipped.append({"plugin": label, "reason": f"manifest exceeds {MAX_MANIFEST_BYTES} bytes"})
            return None
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        skipped.append({"plugin": label, "reason": f"manifest is unreadable: {type(error).__name__}"})
        return None
    try:
        entries = read_plugin_manifest_entries(text)
    except PluginManifestFormatError as error:
        skipped.append({"plugin": label, "reason": f"manifest is outside the readable subset: {error}"})
        return None
    declared_name, name_readable = _scalar(entries, NAME_FIELD)
    tools, tools_readable = _sequence(entries, TOOLS_FIELD)
    hooks, hooks_readable = _sequence(entries, HOOKS_FIELD)
    # Hermes identifies a plugin by its manifest name; the directory name is
    # the fallback, and it is what `plugins.enabled` would have to list for a
    # manifest that declares none. A manifest that declares a name OMH could
    # not read is a different case: the directory name is then a guess, and
    # classifying against a guess would attach another maintainer's catalog
    # record -- its repo, its provenance, its verbatim egress disclosure -- to
    # this install on the strength of a directory name. The classifier is
    # given no name at all in that case, so only the `jev_` tool prefix can
    # match, and the directory name is carried as a label rather than as an
    # identity.
    raw_name = declared_name or directory.name
    name = _printable_name(raw_name)
    name_established = name_readable and name == raw_name
    classified = classify_plugin(name if name_readable else "", tools, hooks)
    readability = {NAME_FIELD: name_readable, TOOLS_FIELD: tools_readable, HOOKS_FIELD: hooks_readable}
    unreadable = [field for field in UNREADABLE_DECLARATION_FIELDS if not readability[field]]
    if classified is None:
        # The bounded reader's total rule: a manifest that was not understood
        # never reports a clean result. Only the two fields that can carry a
        # Jev signal count here. `provides_tools: [jev_evaluate]` is an inline
        # flow sequence the subset does not model and is indistinguishable
        # from the far commoner `provides_tools: []`, and a manifest whose
        # `name` could not be read was classified on its tools alone, which a
        # known plugin need not declare. An unread `provides_hooks` cannot
        # make a plugin Jev-class, so it never puts an otherwise ordinary
        # plugin in this list.
        hiding = [field for field in (NAME_FIELD, TOOLS_FIELD) if field in unreadable]
        if hiding:
            skipped.append(
                {
                    "plugin": label,
                    "reason": "declaration outside the readable subset: " + ", ".join(hiding),
                }
            )
        return None
    classified["name"] = name
    classified["unreadable_declarations"] = unreadable
    classified["directory"] = label
    state, reason = enablement.state(name, name_established)
    classified["enablement"] = state
    classified["enablement_reason"] = reason
    return classified


def _scalar(entries: tuple[ManifestEntry, ...], key: str) -> tuple[str, bool]:
    found = entry_values(entries, key)
    if not found:
        return "", True
    if len(found) > 1 or found[0].kind != "scalar":
        return "", False
    return found[0].scalar, True


def _sequence(entries: tuple[ManifestEntry, ...], key: str) -> tuple[tuple[str, ...], bool]:
    found = entry_values(entries, key)
    if not found:
        return (), True
    if len(found) > 1:
        return (), False
    entry = found[0]
    if entry.kind == "sequence":
        return entry.sequence, True
    # `provides_tools:` with nothing under it is YAML null, which the reader
    # reports as an empty scalar. It declares nothing, and reading it as
    # unreadable would report a finding about a manifest that said what it
    # meant. An inline `[]` is a different shape and does not arrive here as a
    # scalar; the caller decides what an unread declaration costs.
    if entry.kind == "scalar" and not entry.scalar:
        return (), True
    return (), False


def _printable_name(value: str) -> str:
    """One filesystem-supplied name, safe to put in a line an operator reads.

    A directory name never passes the manifest reader, so this is the only
    guard on it. Control characters are what a forged report line is built
    from -- `\\x1b[2K\\r` repaints the line above, a newline writes a whole one
    -- and the length cap keeps one entry from owning the check.
    """
    return strip_control_characters(value)[:MAX_PLUGIN_NAME_CHARS]


def _read_bounded_text(path: Path, limit: int) -> tuple[str, bool]:
    """(text, whether OMH read the whole file).

    A file that is not there reads as empty and whole: a machine with no
    config has nothing enabled, which is a fact. A file OMH could not open,
    could not decode, or could not read inside *limit* is not empty -- it is
    unread, and the second element says so rather than letting a caller report
    the absence of a list it never saw.
    """
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
    except FileNotFoundError:
        return "", True
    except OSError:
        return "", False
    if len(raw) > limit:
        return "", False
    try:
        return raw.decode("utf-8"), True
    except UnicodeDecodeError:
        return "", False
