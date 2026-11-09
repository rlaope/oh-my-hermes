"""Persisted ownership evidence used before destructive installer operations."""
from __future__ import annotations

from pathlib import Path
import re

from .config_adapter import anchor_external_dir_entry, external_dirs, plugin_is_enabled, read_config
from ..paths import managed_command_generations_dir
from ..plugin_bundle.omh import runtime_paths
from ..skin_pack import TUI_PROFILE


def primary_hermes_home(home: Path) -> Path:
    """A named profile's primary, or the supplied primary itself."""
    return home.parent.parent if home.parent.name == "profiles" else home


def _persisted_store(home: Path, config: str) -> Path:
    found, value = runtime_paths.omh_home_setting(config)
    if found:
        return runtime_paths.expand_path(value, hermes_home=home, relative_to=home)
    # Do not interpret dotenv as shell code or hydrate secrets. A named but
    # unreadable binding is unknown, not evidence that a store is unshared.
    try:
        dotenv = (home / ".env").read_text(encoding="utf-8")
    except FileNotFoundError:
        dotenv = ""
    if re.search(r"^\s*(?:export\s+)?OMH_HOME\s*=", dotenv, re.MULTILINE):
        raise ValueError("unreadable reference inventory: .env names OMH_HOME; configure an absolute plugins.entries.omh.settings.omh_home before removal")
    return runtime_paths.unset_launch_omh_home(home)


def store_removal_plan(paths, *, remove_profiles: bool, detached_homes: tuple[Path, ...] = ()) -> dict[str, object]:
    """Keep real remaining references, never treating scheduled work as detached.

    `remove_profiles` describes scope only, not evidence that detach succeeded.
    A successfully reversed home no longer implicitly binds the default store,
    but its retained explicit binding, enabled plugin and skills still count.
    """
    home = paths.hermes_home
    primary = primary_hermes_home(home)
    target = paths.omh_home.resolve()
    try:
        root = primary / "profiles"
        try:
            # The TUI's own runtime profile mirrors the root's config: it is OMH's, removed with it, never a reference.
            profiles = sorted(entry for entry in root.iterdir()
                              if entry.is_dir() and not entry.name.startswith(".") and entry.name != TUI_PROFILE)
        except FileNotFoundError:
            profiles = []
        homes = [primary, *profiles]
        shared: list[str] = []
        unknown: list[dict[str, str]] = []
        for candidate in homes:
            if candidate == home:
                continue
            try:
                config = read_config(candidate / "config.yaml")
                store = _persisted_store(candidate, config)
                explicit, _ = runtime_paths.omh_home_setting(config)
                runtime_reference = (
                    candidate not in detached_homes or explicit or plugin_is_enabled(config, "omh")
                )
                if (runtime_reference and store == target) or any(
                    anchor_external_dir_entry(entry, candidate).resolve().is_relative_to(target)
                    for entry in external_dirs(config)
                ):
                    shared.append(str(candidate))
            except (OSError, UnicodeError, ValueError) as exc:
                unknown.append({"home": str(candidate), "error": f"{type(exc).__name__}: {exc}"})
        if unknown:
            return {"status": "kept", "reason": "unreadable_reference_inventory", "homes": unknown, "failed": True}
        if shared:
            return {"status": "kept", "reason": "shared by Hermes homes: " + ", ".join(shared), "homes": shared, "failed": False}
    except (OSError, UnicodeError, ValueError) as exc:
        return {"status": "kept", "reason": "unreadable_reference_inventory", "homes": [str(primary)], "error": str(exc), "failed": True}
    return {"status": "remove", "reason": "no other persisted Hermes home references this store", "homes": [], "failed": False}


def command_runtime_owned(executable: Path, venv_dir: Path) -> bool:
    """Attribute actual legacy/generation containment, never a staging hint.

    Resolve parent aliases but not the final interpreter symlink: a real venv
    commonly links python to the system interpreter. A symlinked generation
    escaping the install root, or an environment-only staging override, owns
    neither that interpreter nor the command store.
    """
    try:
        candidate = executable.expanduser().parent.resolve() / executable.name
        legacy = venv_dir.expanduser().resolve()
        if candidate.is_relative_to(legacy):
            return True
        generations = managed_command_generations_dir()
        if generations is None or not generations.is_dir():
            return False
        root = generations.resolve()
        for generation in generations.iterdir():
            resolved = generation.resolve()
            if resolved.parent != root:
                continue
            if candidate.is_relative_to(resolved / "venv"):
                return True
    except (OSError, RuntimeError, ValueError):
        return False
    return False
