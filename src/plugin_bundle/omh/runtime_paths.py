"""Stateless runtime roots shared by the copied plugin and the OMH package.

Only trusted API parameters and host configuration select stores. Never feed
model arguments or observation metadata into these overrides. No binding is
cached here: native tasks/threads carry their own Hermes scope; long-lived
providers bind the returned pair before doing I/O.
"""
from __future__ import annotations

from importlib import import_module
import os
from pathlib import Path
import re
import sys


class RuntimeBindingError(ValueError):
    """No safe runtime store can be selected (messages contain no path values)."""


class UnattributableSessionError(RuntimeBindingError):
    """No profile owns this session, so no store was named to read or write.

    Every other binding refusal names a store and then rejects it: a malformed
    setting, an unresolvable path, an unverified owner. This one is raised
    before any store is named at all, which is the distinction a caller needs
    when it must decide whether user configuration might exist and go
    unread. `pre_tool_call` is that caller (#1674).
    """


_VARIABLE = re.compile(r"\$(?:\{(?:env:)?([A-Za-z_][A-Za-z_0-9]*)\}|([A-Za-z_][A-Za-z_0-9]*))|%([A-Za-z_][A-Za-z_0-9]*)%")
_MISSING = object()
# Lifecycle marker only, never a current-profile/home/secret cache. Native
# single-owner callbacks and the memory collector may run without task scopes.
_NATIVE_REGISTERED = False


def note_host_registration(ctx) -> None:
    """Recognize actual native registration, not an importable installation.

    Inspect already-loaded host types only. Standalone fake/operator contexts
    neither import Hermes nor activate the native lane. Both supported native
    loaders retain their normal lifecycle; no wrappers or host scopes are set.
    """
    global _NATIVE_REGISTERED
    for module, name in (("hermes_cli.plugins", "PluginContext"),
                         ("plugins.memory", "_ProviderCollector")):
        native_type = getattr(sys.modules.get(module), name, None)
        if isinstance(native_type, type) and isinstance(ctx, native_type):
            _NATIVE_REGISTERED = True
            return


def _optional_module(name):
    try:
        return import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name and not name.startswith(str(exc.name) + "."):
            raise
        return None


def _require_api(module, *names):
    if any(not callable(getattr(module, name, None)) for name in names):
        raise RuntimeBindingError("OMH native runtime binding APIs are unavailable")
    return module


def _host():
    host = _optional_module("hermes_constants")
    if host is None:
        # A partially missing native installation is not standalone while an
        # already-loaded scope still says a profile/multiplexer is active.
        secrets = sys.modules.get("agent.secret_scope")
        scoped = getattr(secrets, "current_secret_scope", None)
        multiplex = getattr(secrets, "is_multiplex_active", None)
        if (_NATIVE_REGISTERED or (callable(scoped) and scoped() is not None)
                or (callable(multiplex) and multiplex())):
            raise RuntimeBindingError("OMH native runtime binding APIs are unavailable")
        return None
    # Importability alone is not a native lifecycle. A colocated OMH CLI has
    # neither a home override nor a secret scope/multiplexer. Probe these
    # read-only signals first; an unprobeable host is ambiguous, not standalone.
    _require_api(host, "get_hermes_home_override")
    secrets = _require_api(_optional_module("agent.secret_scope"),
                           "current_secret_scope", "is_multiplex_active")
    if (not _NATIVE_REGISTERED and host.get_hermes_home_override() is None
            and secrets.current_secret_scope() is None and not secrets.is_multiplex_active()):
        return None
    _require_api(host, "get_hermes_home")
    _require_api(secrets, "get_secret", "build_profile_secret_scope")
    _require_api(_optional_module("agent.runtime_cwd"), "resolve_context_cwd", "resolve_agent_cwd")
    _require_api(_optional_module("hermes_cli.managed_scope"), "load_managed_config")
    _require_api(_optional_module("hermes_cli.config"),
                 "require_readable_config_before_write", "load_config_readonly")
    return host


def _canonical_path(value, *, relative_to=None):
    try:
        path = Path(value).expanduser()
        if relative_to is not None and not path.is_absolute():
            path = relative_to / path
        resolved = path.resolve()
        # CPython 3.11 and 3.12 raise on a symlink loop; 3.13 resolves it
        # without raising and hands the link itself back. A root that is
        # still a symlink after resolution is therefore the same fault on
        # every supported interpreter, and it must surface here, as a
        # binding error, rather than downstream as a bare RuntimeError from
        # the runtime reader's own symlink guard.
        if resolved.is_symlink():
            raise RuntimeBindingError("OMH runtime path could not be resolved")
        return resolved
    except (OSError, RuntimeError):
        raise RuntimeBindingError("OMH runtime path could not be resolved") from None


def profile_is_routed() -> bool:
    """Only routed profiles pin inferred project artifacts to their own store."""
    if _host() is None:
        return False
    return (import_module("agent.secret_scope").is_multiplex_active()
            or default_hermes_home() != _canonical_path(
                os.environ.get("HERMES_HOME") or _platform_default_hermes_home()))


def tool_home_error(args) -> dict | None:
    """Reject legacy model overrides before observers or tool readers do I/O.

    Standalone operator callers retain their explicit API. Native callbacks
    bind from the host, never from these fields (even an equal/blank value).
    """
    try:
        if _host() is not None and any(key in args for key in ("omh_home", "hermes_home")):
            return {"status": "error", "error": "OMH native tools do not accept runtime home overrides"}
    except RuntimeBindingError:
        return {"status": "error", "error": "OMH native runtime home binding is unavailable"}
    return None


def _profile_variable(name: str, home: Path):
    secrets = import_module("agent.secret_scope")
    scope = secrets.current_secret_scope()
    launch_home = _canonical_path(os.environ.get("HERMES_HOME") or _platform_default_hermes_home())
    if scope is None:
        if secrets.is_multiplex_active() or home != launch_home:
            raise RuntimeBindingError("OMH requires an owned profile variable binding")
        return secrets.get_secret(name)
    value = scope.get(name)
    if value is None and not secrets.is_multiplex_active() and home == launch_home:
        # Single-owner native scopes remain dotenv overlays on their OWN process.
        return secrets.get_secret(name)
    if value is not None:
        # Secret mappings carry no owner identity. A native manager may set only
        # home while retaining its caller's mapping. Verify the selected value
        # against the host's home-keyed snapshot (dotenv + hydrated sources),
        # without hydrating sources, inspecting registries or changing scopes.
        owned = secrets.build_profile_secret_scope(home).get(name)
        if owned != value:
            raise RuntimeBindingError("OMH profile variable ownership is unverified; configure an absolute home")
    return value


def expand_input_path(value: str | Path) -> Path:
    """Observation/model paths are not a credential or environment lookup API."""
    if _VARIABLE.search(str(value)) or "${" in str(value):
        raise RuntimeBindingError("OMH input paths do not support variable references")
    if str(value).startswith("~") and str(value) != "~" and not str(value).startswith("~/"):
        raise RuntimeBindingError("OMH input paths do not support named-user expansion")
    return expand_path(value)


def expand_path(value: str | Path, *, hermes_home: Path | None = None, relative_to: Path | None = None) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip() or "\0" in str(value):
        raise RuntimeBindingError("OMH runtime home must be a nonblank path")

    def replace(match):
        name = next(group for group in match.groups() if group is not None)
        host = _host()
        if name == "HERMES_HOME":
            resolved = str(hermes_home or default_hermes_home())
        elif name == "HOME":
            resolved = str(Path.home())
        elif host is not None:
            resolved = _profile_variable(name, hermes_home or default_hermes_home())
        else:
            resolved = os.environ.get(name)
        if not isinstance(resolved, str) or not resolved.strip():
            raise RuntimeBindingError("OMH runtime path variable is unavailable in this profile")
        return resolved

    expanded = _VARIABLE.sub(replace, str(value))
    if _VARIABLE.search(expanded) or "${" in expanded:
        raise RuntimeBindingError("OMH runtime path contains an unresolved variable")
    return _canonical_path(expanded, relative_to=relative_to)


def _unattributed_launch_read(host, secrets) -> bool:
    """Whether a multiplexed read of the launch home belongs to no profile at all.

    The launch profile is a profile: Hermes binds its secret scope for every
    launch-profile body and installs no HERMES_HOME override, because the launch
    home IS ``get_hermes_home()`` (``tui_gateway/model_switch.py::
    _profile_runtime_scope_tokens`` reports no override for "already the launch
    profile"; ``gateway/run_turn.py::launch_profile_runtime_scope`` does the same
    for the messaging gateway). A missing override alone therefore does not make
    a read unattributed — only a missing override AND no bound secret scope does,
    which is the witness ``_profile_variable`` reads. Without the second half,
    every launch-profile turn in a process that also hosts a second profile home
    was refused as unowned while the secondary profile's own sessions bound
    normally.
    """
    return (secrets.is_multiplex_active()
            and host.get_hermes_home_override() is None
            and secrets.current_secret_scope() is None)


def _platform_default_hermes_home() -> Path:
    """Hermes' own platform default, mirrored from
    ``hermes_constants._platform_default_hermes_home``.

    Hermes does not default to ``~/.hermes`` on Windows: it uses
    ``%LOCALAPPDATA%\\hermes``. A standalone caller that assumed the POSIX shape
    named a SECOND home there, so the gateway that owned the real store refused
    every session the other one pointed at (``storage_unavailable``).
    """
    suffix = os.environ.get("HERMES_DATA_DIR_SUFFIX", "")
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
        return base / ("hermes" + suffix)
    return Path.home() / (".hermes" + suffix)


def default_hermes_home() -> Path:
    host = _host()
    if host is not None:
        secrets = import_module("agent.secret_scope")
        if _unattributed_launch_read(host, secrets):
            raise UnattributableSessionError("OMH requires an active Hermes profile scope")
    value = host.get_hermes_home() if host is not None else (os.environ.get("HERMES_HOME") or _platform_default_hermes_home())
    # Hermes already resolves its profile home. Do not expand it through an
    # environment lookup which could recursively select the launch profile.
    if not isinstance(value, (str, Path)) or not str(value).strip() or "\0" in str(value):
        raise RuntimeBindingError("Hermes runtime home is invalid")
    return _canonical_path(value)


def _setting(config):
    node = config
    for key in ("plugins", "entries", "omh"):
        if not isinstance(node, dict):
            raise RuntimeBindingError("OMH profile configuration must be a mapping")
        if key not in node:
            return _MISSING
        node = node[key]
    if not isinstance(node, dict):
        raise RuntimeBindingError("OMH profile configuration must be a mapping")
    for key in ("settings", "config"):
        if key not in node:
            continue
        settings = node[key]
        if not isinstance(settings, dict):
            raise RuntimeBindingError("OMH profile settings must be a mapping")
        if "omh_home" in settings:
            return settings["omh_home"]
    return _MISSING


# The same setting, read by the standalone lane. A colocated `omh` CLI and the
# OMH TUI's HUD reader have no `hermes_cli.config`, so they cannot load
# the effective, managed-overlaid configuration the native lane validates
# against; the user file is what they can read, and it is the store the
# profile's own plugin resolves on every ordinary install. Not reading it is
# what had `/omh-model` and `omh model-chains` editing `~/.omh` in a profile
# whose dispatches never looked there (#1679).
_STANDALONE_SETTING_PATHS = (
    ("plugins", "entries", "omh", "settings", "omh_home"),
    ("plugins", "entries", "omh", "config", "omh_home"),
)
# The native lane hands a `$VAR` in the setting to `_profile_variable`, which
# verifies the value against the profile's own secret scope. The standalone
# lane has no scope to verify against, and the file this value comes from is
# one a bot can write, so it expands the two names it can answer itself and
# refuses the rest rather than read them out of the process environment.
_STANDALONE_SETTING_VARIABLES = frozenset({"HERMES_HOME", "HOME"})
_LINE_BREAK = re.compile(r"\r\n|\r|\n")
# What a YAML loader hands back as something other than a string. The native
# lane refuses those through `expand_path`'s type check; this lane refuses
# them by spelling, rather than read `true` as a directory name.
_YAML_WORD_SCALARS = frozenset({"true", "false", "yes", "no", "on", "off"})
_YAML_NUMBER = re.compile(
    r"^[-+]?(?:0x[0-9a-f_]+|0o[0-7_]+|\d[\d_]*(?:\.\d*)?(?:e[-+]?\d+)?|\.\d+(?:e[-+]?\d+)?|\.inf|\.nan)$",
    re.IGNORECASE,
)
_YAML_INDICATORS = "{[&*!|>%@`"


def _standalone_configured_home(home: Path):
    try:
        text = (home / "config.yaml").read_text(encoding="utf-8")
    except FileNotFoundError:
        return _MISSING
    except (OSError, UnicodeDecodeError):
        raise RuntimeBindingError("OMH profile configuration is unreadable or invalid") from None
    found, value = standalone_omh_home_setting(text)
    return value if found else _MISSING


def standalone_omh_home_setting(config_text: str) -> tuple[bool, str | None]:
    """`omh_home_setting`, as a caller outside a Hermes host may take it: no variable but $HERMES_HOME or $HOME.

    The value comes back unexpanded; `expand_path(value, hermes_home=home,
    relative_to=home)` is the store it names. Raises `RuntimeBindingError` on
    any other variable rather than read it out of this process's environment.
    """
    found, value = omh_home_setting(config_text)
    for match in _VARIABLE.finditer(value or ""):
        name = next(group for group in match.groups() if group is not None)
        if name not in _STANDALONE_SETTING_VARIABLES:
            raise RuntimeBindingError("OMH profile setting may reference only $HERMES_HOME or $HOME outside a Hermes host")
    return found, value


def omh_home_setting(config_text: str) -> tuple[bool, str | None]:
    """`(found, raw value)` of the `omh_home` a config text names, unexpanded.

    The standalone lane's own scan, public so the installer that writes the
    setting and doctor that reports it read it the way the plugin does rather
    than through a second parser that could disagree about the same file.
    """
    lines = _LINE_BREAK.split(config_text)
    for key_path in _STANDALONE_SETTING_PATHS:
        found, value = _scan_block_setting(lines, key_path)
        if found:
            return True, value
    return False, None


def plugin_setting_text(config_text: str, name: str) -> str | None:
    """The scalar a config text names at `plugins.entries.omh.settings.<name>`, as written; None when unset.

    The same block scan as `omh_home_setting`, with the legacy `config`
    subtree as the fallback Hermes' `get_config` reads. For a setting that is
    not a path, the leaf comes back as its text, quotes removed, rather than
    refused when a YAML loader would read it as a boolean: `off` written bare
    is a YAML false, and only the setting's own reader knows what that means.
    A blank or null leaf reads as unset. Raises `RuntimeBindingError` on a
    shape the scan cannot follow, as `omh_home_setting` does.
    """
    lines = _LINE_BREAK.split(config_text)
    for section in ("settings", "config"):
        found, value = _scan_block_setting(lines, ("plugins", "entries", "omh", section, name), leaf=_leaf_text)
        if found:
            return value
    return None


def config_scalar_text(config_text: str, key_path: tuple[str, ...]) -> str | None:
    """The scalar a config text names at `key_path`, as `plugin_setting_text` reads one; None when unset.

    For a reader of a Hermes setting outside the plugin's subtree, such as
    `model.default`. Raises `RuntimeBindingError` on a shape the scan cannot
    follow.
    """
    return _scan_block_setting(_LINE_BREAK.split(config_text), key_path, leaf=_leaf_text)[1]


def _scan_block_setting(lines: list[str], key_path: tuple[str, ...], *, leaf=None) -> tuple[bool, str | None]:
    """Follow one nested key through block-style YAML by indentation.

    Returns ``(True, value)`` when every key on the path is a block mapping
    key at its level and the last one carries a scalar (``None`` for a YAML
    null), and ``(False, None)`` when a key is absent or an intermediate key
    holds an inline value that cannot name the setting (`plugins: {enabled:
    [omh]}`, `entries: {}`). The one shape understood is the one Hermes
    writes -- a key at a fixed indent, its children on deeper-indented
    lines -- with the last duplicate winning as a YAML loader resolves it.
    Refused rather than read past: an inline value that does mention the
    setting, an alias or merge key where the setting could be inherited from
    an anchor, a tab-indented line, and -- through the default ``leaf``,
    `_leaf_string` -- a leaf a loader would not hand back as one string.
    """
    start, stop, parent_indent = 0, len(lines), -1
    for depth, key in enumerate(key_path):
        child_indent = None
        found_at = None
        merge_key = False
        for index in range(start, stop):
            line = lines[index]
            body = line.strip()
            if not body or body.startswith("#"):
                continue
            indent = len(line) - len(line.lstrip(" \t"))
            if "\t" in line[:indent]:
                raise RuntimeBindingError("OMH profile configuration is tab-indented; YAML indents with spaces")
            if indent <= parent_indent:
                stop = index
                break
            if child_indent is None:
                child_indent = indent
            if indent != child_indent:
                continue
            name, separator, rest = body.partition(":")
            if not separator or (rest and not rest[0].isspace()):
                continue
            name = name.strip().strip("'\"")
            if name == key:
                found_at = index
            elif name == "<<":
                merge_key = True
        if found_at is None:
            if merge_key:
                # `<<: *base` may carry the key from an anchor this reader
                # cannot follow; the profile may well have named a store.
                raise RuntimeBindingError(_INLINE_SHAPE_MESSAGE)
            return False, None
        quoted, value = _yaml_scalar(lines[found_at].partition(":")[2])
        if depth == len(key_path) - 1:
            return True, (leaf or _leaf_string)(quoted, value)
        if quoted or value.startswith("*") or key_path[-1] in value:
            raise RuntimeBindingError(_INLINE_SHAPE_MESSAGE)
        if value:
            return False, None
        start, parent_indent = found_at + 1, child_indent
    return False, None


_INLINE_SHAPE_MESSAGE = (
    "OMH profile configuration uses an inline shape this reader cannot follow; "
    "write the setting in block style or pass --omh-home"
)


def _yaml_scalar(raw: str) -> tuple[bool, str]:
    """``(quoted, text)`` for one scalar; a quoted value is a string as written.

    A node property (`&anchor`, `!tag`) before the value is not the value:
    `plugins: &base` heads a block mapping whose children follow, and
    `omh_home: &a /x` names `/x`.
    """
    value = raw.strip()
    while value[:1] in {"&", "!"}:
        value = value.partition(" ")[2].strip()
    if value[:1] in {"'", '"'}:
        end = value.find(value[0], 1)
        remainder = value[end + 1:].strip() if end > 0 else ""
        if end <= 0 or (remainder and not remainder.startswith("#")):
            raise RuntimeBindingError("OMH profile configuration is unreadable or invalid")
        return True, value[1:end]
    if value.startswith("#"):
        return False, ""
    return False, re.split(r"\s#", value, maxsplit=1)[0].rstrip()


def _leaf_string(quoted: bool, value: str) -> str | None:
    if quoted:
        return value
    if not value or value.lower() in {"~", "null"}:
        # A present-but-blank setting, which `expand_path` refuses the way
        # the native lane refuses `None`; it is not the OS user's home.
        return None
    if (
        value[0] in _YAML_INDICATORS
        or value.lower() in _YAML_WORD_SCALARS
        or _YAML_NUMBER.match(value)
        # A character Python splits lines on and a YAML loader may not: the
        # two readings would name different stores, so neither is taken.
        or len(value.splitlines()) != 1
    ):
        raise RuntimeBindingError("OMH profile setting is not a path string")
    return value


def _leaf_text(quoted: bool, value: str) -> str | None:
    if not quoted and (not value or value.lower() in {"~", "null"}):
        return None
    return value


def _overlay_config(user: dict, managed: dict) -> dict:
    # Preserve the winning *raw* leaf, before native process expansion. A
    # shadowed user template is not the provenance of a managed literal.
    result = dict(user)
    for key, value in managed.items():
        # Native merging treats empty YAML sections as absent, not removals.
        if isinstance(result.get(key), dict) and value is None:
            continue
        result[key] = (_overlay_config(result[key], value)
                       if isinstance(result.get(key), dict) and isinstance(value, dict) else value)
    return result


def _configured_home(home: Path):
    config = import_module("hermes_cli.config")
    # This host validator preserves the source YAML (and may save a recovery
    # copy when it is malformed). The normal behavioral loader deliberately
    # tolerates malformed/unreadable YAML and can reuse last-known-good data;
    # neither is safe for selecting a state owner. Validate before using it.
    try:
        raw = config.require_readable_config_before_write(home / "config.yaml")
    except (RuntimeError, OSError, ValueError) as exc:
        raise RuntimeBindingError("OMH profile configuration is unreadable or invalid") from exc
    original = _setting(_overlay_config(raw, import_module("hermes_cli.managed_scope").load_managed_config()))
    if original is not _MISSING:
        original_path = expand_path(original, hermes_home=home, relative_to=home)
    effective = _setting(config.load_config_readonly())
    if (original is _MISSING) != (effective is _MISSING):
        raise RuntimeBindingError("OMH home configuration disagrees with the active profile")
    if effective is _MISSING:
        return _MISSING
    path = expand_path(effective, hermes_home=home, relative_to=home)
    # Native config currently expands ${HERMES_HOME} through the process env.
    # Reject an expansion that changed owner; bare $HERMES_HOME is expanded here
    # against the profile. Do not silently bypass managed/effective config.
    if original is not _MISSING and path != original_path:
        raise RuntimeBindingError("OMH home expansion disagrees with the active profile; use an absolute path")
    return path


def resolve_homes(omh_home: str | Path | None = None, hermes_home: str | Path | None = None) -> tuple[Path, Path]:
    """Trusted pair > profile settings > scoped legacy env > standalone default.

    A complete explicit pair permits offline CLI operations and intentional
    sharing. An unbound routed profile is unavailable, never a new empty store
    and never the launch profile's store. The standalone lane keeps the same
    order in the shape it can afford: the home's own `config.yaml` setting,
    then the process `OMH_HOME`, then `~/.omh`.
    """
    home = expand_path(hermes_home) if hermes_home is not None else default_hermes_home()
    if omh_home is not None:
        return expand_path(omh_home, hermes_home=home), home
    host = _host()
    if host is None:
        configured = _standalone_configured_home(home)
        if configured is not _MISSING:
            return expand_path(configured, hermes_home=home, relative_to=home), home
        return standalone_default_omh_home(home), home
    active_home = default_hermes_home()
    if home != active_home:
        raise RuntimeBindingError("OMH requires an explicit home pair for an offline profile")
    secrets = import_module("agent.secret_scope")
    multiplex = secrets.is_multiplex_active()
    if _unattributed_launch_read(host, secrets):
        raise UnattributableSessionError("OMH requires an active Hermes profile scope")
    configured = _configured_home(home)
    if configured is not _MISSING:
        return configured, home
    scope = secrets.current_secret_scope()
    launch_home = _canonical_path(os.environ.get("HERMES_HOME") or _platform_default_hermes_home())
    # Registration can carry only a home override. A foreign home with no
    # secret scope must not inherit env even when multiplex is not yet active.
    if home != launch_home and scope is None:
        raise RuntimeBindingError("OMH home is not configured for this profile")
    value = _profile_variable("OMH_HOME", home)
    if value is not None:
        return expand_path(value, hermes_home=home, relative_to=home if multiplex or home != launch_home else None), home
    if multiplex or home != launch_home:
        raise RuntimeBindingError("OMH home is not configured for this profile")
    return unset_launch_omh_home(home), home


def unset_launch_omh_home(hermes_home: Path | None = None) -> Path:
    """The store a launch-profile plugin binds when nothing names one.

    Neither its home's `settings.omh_home` nor the Hermes process's
    `OMH_HOME`. An install at any other store has to write the setting, or
    this is the store its plugin reads and writes (#1960).
    """
    return expand_path("~/.omh", hermes_home=hermes_home)


def standalone_default_omh_home(hermes_home: Path | None = None) -> Path:
    """The store a standalone caller reaches when no home names one.

    Also the store a profile synced from a default primary was registered
    at, which is why the installer's candidate list names it: a profile that
    later selected its own store still carries that registration.
    """
    return expand_path(os.environ.get("OMH_HOME") or "~/.omh", hermes_home=hermes_home)


def default_omh_home() -> Path:
    return resolve_homes()[0]


def plugin_home(value: object = None, *, hermes: bool = False) -> Path:
    """Native callbacks cannot choose a store through arguments/observations.

    Retain explicit standalone reader APIs for operator integrations. Within a
    native host, these same legacy fields are not authority to cross profiles.
    """
    if _host() is None and value:
        return expand_path(value)
    return default_hermes_home() if hermes else default_omh_home()


def runtime_cwd() -> Path | None:
    """Use host context discovery; never fall back to a foreign launch repo."""
    host = _host()
    try:
        if host is None:
            return Path.cwd()
        cwd = import_module("agent.runtime_cwd")
        if profile_is_routed():
            return cwd.resolve_context_cwd()
        return cwd.resolve_agent_cwd()
    except (OSError, RuntimeError):
        raise RuntimeBindingError("OMH logical working directory could not be resolved") from None
