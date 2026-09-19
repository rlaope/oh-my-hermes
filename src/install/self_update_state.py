"""Persistent state, pointer switching, and retention for staged self updates."""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import shutil
from typing import Any, TypedDict

from ..plugin_bundle.omh import runtime_paths

try:
    from ..core.errors import OmhError
    from ..install.config_adapter import ConfigChange, ensure_external_dir, remove_external_dir, update_config
    from ..system.local_store import atomic_write_json, read_json_object_result
    from ..system.paths import managed_command_bin_dir
    from .self_update_platform import SelfUpdatePlatform
    from .self_update_state_validation import parse_gc_entries, parse_generation_entry, parse_marker, parse_state, require_generation_path, same_existing_path
except ImportError:  # pragma: no cover - direct-source installer smoke.
    from core.errors import OmhError
    from install.config_adapter import ConfigChange, ensure_external_dir, remove_external_dir, update_config
    from system.local_store import atomic_write_json, read_json_object_result
    from system.paths import managed_command_bin_dir
    from install.self_update_platform import SelfUpdatePlatform
    from install.self_update_state_validation import parse_gc_entries, parse_generation_entry, parse_marker, parse_state, require_generation_path, same_existing_path

STATE_SCHEMA_VERSION = "self_update_state/v1"


class GenerationEntry(TypedDict):
    id: str
    path: str
    kind: str
    version: str


class CleanupResult(TypedDict):
    collected: list[str]


class GarbageCollectionResult(TypedDict):
    cleanup: CleanupResult


def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def state_path(root: Path) -> Path:
    return root / "self-update.json"


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
    shutil.rmtree(candidate, ignore_errors=True)
    state["activation_in_progress"] = None
    save_state(root, state)
    return None


def record_pointer(state: dict[str, Any], root: Path, target: Path) -> None:
    relative_target = os.path.relpath(target, root).replace("\\", "/")
    state["pointer"] = {"path": str(root / "current"), "target": relative_target}


def commit_activation(root: Path, state: dict[str, Any], candidate: Path) -> None:
    state["previous_known_good"] = state["active"]
    state["active"] = generation_entry(candidate)
    state["activation_in_progress"] = None
    state.pop("recovery_selected", None)
    record_pointer(state, root, candidate)


def restore_known_good(root: Path, state: dict[str, Any], target: Path) -> None:
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
) -> None:
    keep = parse_gc_entries(root, state)
    if running_generation is not None:
        keep.add(running_generation.name)
    generations = root / "generations"
    for item in generations.iterdir() if generations.exists() else ():
        junction = getattr(item, "is_junction", None)
        if item.name not in keep and not item.is_symlink() and not (junction and junction()):
            shutil.rmtree(item, ignore_errors=True)
            result["cleanup"]["collected"].append(str(item))
    state["retained_generations"] = sorted(keep & {item.name for item in generations.iterdir()}) if generations.exists() else []


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
    temporary = launcher.with_name(f".{launcher.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    os.symlink(str(target), temporary)
    os.replace(temporary, launcher)
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
        text = ensure_external_dir(text, root / "current" / "skills").text
        return ConfigChange(text != original, "retargeted skills.external_dirs", text)

    update_config(paths.hermes_config_path, _retarget_registration, omh_home=paths.omh_home)
    state["active"] = generation_entry(bootstrap, "bootstrap")
    state["migration"] = {"status": "completed", "launcher_on_pointer": launcher, "registration_on_pointer": True, "completed_at": now()}
    record_pointer(state, root, bootstrap)
    save_state(root, state)
