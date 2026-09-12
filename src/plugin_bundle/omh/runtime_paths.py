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


class RuntimeBindingError(ValueError):
    """No safe runtime store can be selected (messages contain no path values)."""


_VARIABLE = re.compile(r"\$(?:\{(?:env:)?([A-Za-z_][A-Za-z_0-9]*)\}|([A-Za-z_][A-Za-z_0-9]*))|%([A-Za-z_][A-Za-z_0-9]*)%")
_MISSING = object()


def _host():
    try:
        return import_module("hermes_constants")
    except ModuleNotFoundError as exc:
        if exc.name != "hermes_constants":
            raise
        return None


def _profile_variable(name: str, home: Path):
    secrets = import_module("agent.secret_scope")
    scope = secrets.current_secret_scope()
    launch_home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser().resolve()
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
    path = Path(expanded).expanduser()
    if relative_to is not None and not path.is_absolute():
        path = relative_to / path
    return path.resolve()


def default_hermes_home() -> Path:
    host = _host()
    if host is not None:
        secrets = import_module("agent.secret_scope")
        if secrets.is_multiplex_active() and host.get_hermes_home_override() is None:
            raise RuntimeBindingError("OMH requires an active Hermes profile scope")
    value = host.get_hermes_home() if host is not None else (os.environ.get("HERMES_HOME") or "~/.hermes")
    # Hermes already resolves its profile home. Do not expand it through an
    # environment lookup which could recursively select the launch profile.
    if not isinstance(value, (str, Path)) or not str(value).strip() or "\0" in str(value):
        raise RuntimeBindingError("Hermes runtime home is invalid")
    return Path(value).expanduser().resolve()


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


def _overlay_config(user: dict, managed: dict) -> dict:
    # Preserve the winning *raw* leaf, before native process expansion. A
    # shadowed user template is not the provenance of a managed literal.
    result = dict(user)
    for key, value in managed.items():
        result[key] = (_overlay_config(result[key], value)
                       if isinstance(result.get(key), dict) and isinstance(value, dict) else value)
    return result


def _configured_home(home: Path):
    config = import_module("hermes_cli.config")
    # This host validator only reads. The normal behavioral loader deliberately
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
    if effective is _MISSING:
        return _MISSING
    path = expand_path(effective, hermes_home=home, relative_to=home)
    # Native config currently expands ${HERMES_HOME} through the process env.
    # Reject an expansion that changed owner; bare $HERMES_HOME is expanded here
    # against the profile. Do not silently bypass managed/effective config.
    if original is not _MISSING and _VARIABLE.search(str(original)) and path != original_path:
        raise RuntimeBindingError("OMH home expansion disagrees with the active profile; use an absolute path")
    return path


def resolve_homes(omh_home: str | Path | None = None, hermes_home: str | Path | None = None) -> tuple[Path, Path]:
    """Trusted pair > profile settings > scoped legacy env > standalone default.

    A complete explicit pair permits offline CLI operations and intentional
    sharing. An unbound routed profile is unavailable, never a new empty store
    and never the launch profile's store.
    """
    home = expand_path(hermes_home) if hermes_home is not None else default_hermes_home()
    if omh_home is not None:
        return expand_path(omh_home, hermes_home=home), home
    host = _host()
    if host is None:
        return expand_path(os.environ.get("OMH_HOME") or "~/.omh", hermes_home=home), home
    active_home = default_hermes_home()
    if home != active_home:
        raise RuntimeBindingError("OMH requires an explicit home pair for an offline profile")
    secrets = import_module("agent.secret_scope")
    multiplex = secrets.is_multiplex_active()
    if multiplex and host.get_hermes_home_override() is None:
        raise RuntimeBindingError("OMH requires an active Hermes profile scope")
    configured = _configured_home(home)
    if configured is not _MISSING:
        return configured, home
    scope = secrets.current_secret_scope()
    launch_home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser().resolve()
    # Registration can carry only a home override. A foreign home with no
    # secret scope must not inherit env even when multiplex is not yet active.
    if home != launch_home and scope is None:
        raise RuntimeBindingError("OMH home is not configured for this profile")
    value = _profile_variable("OMH_HOME", home)
    if value is not None:
        return expand_path(value, hermes_home=home, relative_to=home if multiplex or home != launch_home else None), home
    if multiplex or home != launch_home:
        raise RuntimeBindingError("OMH home is not configured for this profile")
    return expand_path("~/.omh", hermes_home=home), home


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
    if _host() is None:
        return Path.cwd()
    cwd = import_module("agent.runtime_cwd")
    secrets = import_module("agent.secret_scope")
    launch_home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser().resolve()
    if secrets.is_multiplex_active() or default_hermes_home() != launch_home:
        return cwd.resolve_context_cwd()
    return cwd.resolve_agent_cwd()
