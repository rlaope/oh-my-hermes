"""Persistent state, pointer switching, and retention for staged self updates."""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import secrets
import shutil
from typing import Any, Iterable, TypedDict

from ..plugin_bundle.omh import runtime_paths

try:
    from ..core.errors import OmhError
    from ..install.config_adapter import ConfigChange, ensure_external_dir, remove_external_dir, update_config
    from ..system.local_store import atomic_write_json, read_json_object_result
    from ..system.paths import managed_command_bin_dir
    from .generation_hold import held_generations
    from .self_update_platform import SelfUpdatePlatform
    from .self_update_state_validation import parse_gc_entries, parse_generation_entry, parse_marker, parse_state, require_generation_path, same_existing_path
except ImportError:  # pragma: no cover - direct-source installer smoke.
    from core.errors import OmhError
    from install.config_adapter import ConfigChange, ensure_external_dir, remove_external_dir, update_config
    from system.local_store import atomic_write_json, read_json_object_result
    from system.paths import managed_command_bin_dir
    from install.generation_hold import held_generations
    from install.self_update_platform import SelfUpdatePlatform
    from install.self_update_state_validation import parse_gc_entries, parse_generation_entry, parse_marker, parse_state, require_generation_path, same_existing_path

STATE_SCHEMA_VERSION = "self_update_state/v1"


class GenerationEntry(TypedDict):
    id: str
    path: str
    kind: str
    version: str


class _CleanupFields(TypedDict, total=False):
    reason: str


class CleanupResult(_CleanupFields):
    collected: list[str]


class GarbageCollectionResult(TypedDict):
    cleanup: CleanupResult


def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def state_path(root: Path) -> Path:
    return root / "self-update.json"


def committed_generation(root: Path) -> str:
    """The generation the last finished update left active, read from its state file; "" while an activation is under
    way, or when the file cannot be read. The pointer moves first: the re-entry that installs the new plugin bundle
    runs after that, and its failure moves the pointer back and deletes the candidate."""
    state, _error = read_json_object_result(state_path(root))
    if state is None or state.get("activation_in_progress"):
        return ""
    active = state.get("active")
    return str(active.get("id", "")) if isinstance(active, dict) else ""


def generation_entry(path: Path, kind: str = "generation", version: str = "") -> GenerationEntry:
    return {"id": path.name, "path": str(path), "kind": kind, "version": version}


def load_state(root: Path, legacy: Path) -> dict[str, Any]:
    path = state_path(root)
    state, error = read_json_object_result(path)
    if state is None:
        if path.exists():
            raise OmhError(f"cannot read {path}: {error}; run omh update --recover-known-good")
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "active": generation_entry(legacy, "legacy"),
            "previous_known_good": None,
            "pointer": {"path": str(root / "current"), "target": ""},
            "migration": {"status": "pending"},
            "activation_in_progress": None,
            "retained_generations": [],
        }
    schema = state.get("schema_version")
    if schema != STATE_SCHEMA_VERSION:
        reason = "newer" if isinstance(schema, str) and schema > STATE_SCHEMA_VERSION else "unsupported"
        raise OmhError(f"cannot use {path}: {reason} self-update state schema {schema!r}")
    return parse_state(root, state, legacy)


def save_state(root: Path, state: dict[str, Any]) -> None:
    state["schema_version"] = STATE_SCHEMA_VERSION
    state["updated_at"] = now()
    atomic_write_json(state_path(root), state, private=True)


def pointer_target(root: Path, *, platform: SelfUpdatePlatform | None = None) -> Path | None:
    return (platform or SelfUpdatePlatform.host()).link_target(root, root / "current")


def switch_current(
    root: Path,
    target: Path,
    *,
    is_windows: bool | None = None,
    platform: SelfUpdatePlatform | None = None,
) -> None:
    """Atomically replace the one consumer pointer with a link or junction."""
    selected = platform or SelfUpdatePlatform.host(is_windows=is_windows)
    selected.replace_current(root, require_generation_path(root, target, None, "switch target"))


def migration_needed(state: dict[str, Any]) -> bool:
    return state.get("migration", {}).get("status") != "completed"


def mark_activation(state: dict[str, Any], candidate: Path, previous: Path) -> None:
    state["activation_in_progress"] = {
        "candidate": str(candidate),
        "previous": str(previous),
        "marker_written_at": now(),
        "phase": "pre_switch",
    }


def mark_switched(state: dict[str, Any]) -> None:
    marker = state.get("activation_in_progress")
    if isinstance(marker, dict):
        marker["phase"] = "post_switch"


def interrupted_activation(
    root: Path,
    state: dict[str, Any],
    *,
    platform: SelfUpdatePlatform | None = None,
) -> tuple[Path, Path] | None:
    parsed = parse_marker(root, state.get("activation_in_progress"))
    if parsed is None:
        return None
    candidate, previous = parsed
    pointed = pointer_target(root, platform=platform)
    if pointed is not None:
        pointed = require_generation_path(root, pointed, None, "current pointer target")
        if same_existing_path(pointed, candidate):
            return candidate, previous
    if state["activation_in_progress"].get("restore_required") is True:
        return candidate, previous
    shutil.rmtree(candidate, ignore_errors=True)
    state["activation_in_progress"] = None
    save_state(root, state)
    return None


def record_pointer(state: dict[str, Any], root: Path, target: Path) -> None:
    relative_target = os.path.relpath(target, root).replace("\\", "/")
    state["pointer"] = {"path": str(root / "current"), "target": relative_target}


def _record_activation(state: dict[str, Any], identifier: str) -> None:
    # A Hermes gateway resolves `current/skills` to the generation behind it
    # and caches that path until config.yaml changes or it restarts, so GC
    # must know which generation was current at a recorded gateway start.
    history = [entry for entry in state.get("activations") or () if isinstance(entry, dict)]
    if not history:
        # Activated before this record existed, at a time nobody wrote down.
        # `None` is that unknown time, never "before every gateway start".
        history.append({"id": str(state["active"].get("id", "")), "activated_at": None})
    marker = state.get("activation_in_progress")
    switched = marker.get("marker_written_at") if isinstance(marker, dict) else None
    history.append({"id": identifier, "activated_at": switched if isinstance(switched, str) else now()})
    state["activations"] = history


def _held_by_gateways(state: dict[str, Any], gateway_starts: Iterable[float]) -> tuple[set[str], list[float]]:
    """The newest generation activated at or before each recorded gateway start.

    Also returns the starts no stamped activation precedes: the generation
    current then was activated before the history began (its row, if any,
    has no time) or its row is gone, so the history cannot name it.
    """
    activations: list[tuple[str, float]] = []
    for entry in state.get("activations") or ():
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or entry.get("activated_at") is None:
            continue
        try:
            activated = datetime.fromisoformat(str(entry["activated_at"])).timestamp()
        except (ValueError, OverflowError, OSError):
            continue
        activations.append((entry["id"], activated))
    held: set[str] = set()
    unresolved: list[float] = []
    for start in gateway_starts:
        current = [identifier for identifier, activated in activations if activated <= start]
        if current:
            held.add(current[-1])
        else:
            unresolved.append(start)
    return held, unresolved


def _created_after(name: str, moment: float) -> bool:
    """Whether a generation id's creation stamp proves it was made after `moment`."""
    try:
        created = datetime.strptime(name[:20], "%Y%m%d%H%M%S%f").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return False
    return created > moment


def commit_activation(root: Path, state: dict[str, Any], candidate: Path) -> None:
    _record_activation(state, candidate.name)
    state["previous_known_good"] = state["active"]
    state["active"] = generation_entry(candidate)
    state["activation_in_progress"] = None
    state.pop("recovery_selected", None)
    record_pointer(state, root, candidate)


def restore_known_good(root: Path, state: dict[str, Any], target: Path) -> None:
    _record_activation(state, target.name)
    state["active"] = generation_entry(target, str(state.get("active", {}).get("kind", "generation")))
    state["activation_in_progress"] = None
    state["recovery_selected"] = target.name
    record_pointer(state, root, target)


def recovery_target(root: Path, state: dict[str, Any]) -> Path:
    selected = state.get("recovery_selected")
    active = state.get("active")
    if isinstance(selected, str) and isinstance(active, dict) and active.get("id") == selected:
        target = parse_generation_entry(root, active, "active generation")
    else:
        previous = state.get("previous_known_good")
        if previous is None:
            raise OmhError("no retained previous known-good generation is available")
        target = parse_generation_entry(root, previous, "previous known-good generation")
    if not target.is_dir():
        raise OmhError("no retained previous known-good generation is available")
    return target


def collect_garbage(
    root: Path,
    state: dict[str, Any],
    result: GarbageCollectionResult,
    *,
    running_generation: Path | None,
    gateway_starts: Iterable[float] = (),
) -> None:
    keep = parse_gc_entries(root, state)
    if running_generation is not None:
        keep.add(running_generation.name)
    # An open OMH TUI (and the gateway attach under it) imports from the
    # generation it started on for as long as it runs.
    keep |= held_generations(root)
    # A gateway still serves the generation current at its last recorded
    # start; deleting it leaves Hermes with zero OMH skills until a restart.
    held, unresolved = _held_by_gateways(state, gateway_starts)
    keep |= held
    # When the history cannot say which generation a gateway started on, only
    # a generation created after that start is provably not it.
    latest_unresolved = max(unresolved) if unresolved else None
    generations = root / "generations"
    for item in generations.iterdir() if generations.exists() else ():
        junction = getattr(item, "is_junction", None)
        if latest_unresolved is not None and item.name not in keep and not _created_after(item.name, latest_unresolved):
            keep.add(item.name)
            stamp = datetime.fromtimestamp(latest_unresolved, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            result["cleanup"]["reason"] = (
                f"kept generations created before the Hermes gateway start recorded at {stamp}: "
                "no recorded activation says which one that gateway serves; "
                "an update collects them once that gateway has restarted, or once its gateway.pid record is gone"
            )
        if item.name not in keep and not item.is_symlink() and not (junction and junction()):
            shutil.rmtree(item, ignore_errors=True)
            result["cleanup"]["collected"].append(str(item))
    state["retained_generations"] = sorted(keep & {item.name for item in generations.iterdir()}) if generations.exists() else []
    if isinstance(state.get("activations"), list):
        state["activations"] = [
            entry for entry in state["activations"] if isinstance(entry, dict) and entry.get("id") in state["retained_generations"]
        ]


def _retarget_launcher(root: Path, platform: SelfUpdatePlatform) -> bool:
    directory = managed_command_bin_dir()
    if directory is None:
        return False
    if platform.is_windows:
        launcher = directory / "omh.cmd"
        if not launcher.exists() and not launcher.is_symlink():
            return False
        platform.rewrite_command_shim(launcher, root)
        return True
    launcher = directory / "omh"
    if not launcher.exists() and not launcher.is_symlink():
        return False
    target = platform.scripts_dir(root / "current" / "venv") / "omh"
    # A random name, created exclusively by `os.symlink`: the old predictable
    # name was unlinked first, which left a window for a planted entry.
    temporary = launcher.with_name(f".{launcher.name}.{secrets.token_hex(16)}.tmp")
    os.symlink(str(target), temporary)
    try:
        os.replace(temporary, launcher)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    return True


def migrate_legacy(root: Path, state: dict[str, Any], paths: Any, platform: SelfUpdatePlatform) -> None:
    if not migration_needed(state):
        return
    legacy = Path(str(state["active"]["path"]))
    bootstrap = root / "generations" / "bootstrap-legacy"
    bootstrap.mkdir(parents=True, exist_ok=True)
    # The pre-pointer install registered and populated `<store>/skills` at
    # the store the resolver named THEN. A home that has since named its own
    # store (#1679) resolves elsewhere now, so the default store is the
    # legacy one whenever the resolved store carries no skills.
    legacy_skills = paths.omh_home / "skills"
    default_skills = runtime_paths.standalone_default_omh_home(paths.hermes_home) / "skills"
    if not legacy_skills.is_dir() and default_skills.is_dir():
        legacy_skills = default_skills
    for name, target in (("venv", legacy), ("skills", legacy_skills)):
        link = bootstrap / name
        if not link.exists() and not link.is_symlink():
            platform.create_directory_link(root, link, target)
    if pointer_target(root, platform=platform) is None:
        switch_current(root, bootstrap, platform=platform)
    launcher = _retarget_launcher(root, platform)
    def _retarget_registration(original: str) -> ConfigChange:
        text = original
        for stale in (legacy_skills, default_skills, paths.omh_home / "skills"):
            text = remove_external_dir(text, stale).text
        text = ensure_external_dir(text, root / "current" / "skills", hermes_home=paths.hermes_home).text
        return ConfigChange(text != original, "retargeted skills.external_dirs", text)

    update_config(paths.hermes_config_path, _retarget_registration, omh_home=paths.omh_home)
    state["active"] = generation_entry(bootstrap, "bootstrap")
    state["migration"] = {"status": "completed", "launcher_on_pointer": launcher, "registration_on_pointer": True, "completed_at": now()}
    record_pointer(state, root, bootstrap)
    save_state(root, state)
