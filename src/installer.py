from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .core.errors import OmhError
from .converter import convert_from_dir
from .local_store import atomic_write_text, read_json_object_result
from .manifest import local_modifications, new_manifest, read_manifest, skill_records, write_manifest
from .paths import OmhPaths
from .profiles.team import TEAM_PROFILE_SCHEMA_VERSION
from .skill_pack import SkillTemplate, builtin_skill_templates


def _write_skill(skills_dir: Path, template: SkillTemplate, force: bool = False, managed: bool = False) -> None:
    target_dir = skills_dir / template.name
    target_file = target_dir / "SKILL.md"
    if target_file.exists() and not force and not managed:
        existing = target_file.read_text(encoding="utf-8")
        if existing != template.content:
            raise OmhError(f"local skill differs, refusing to overwrite without --force: {target_file}")
    atomic_write_text(target_file, template.content)


def install_skill_pack(
    paths: OmhPaths,
    *,
    source: str = "builtin",
    source_dir: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    templates = convert_from_dir(source_dir) if source_dir else builtin_skill_templates()
    manifest = read_manifest(paths.manifest_path)
    modified = local_modifications(manifest, paths.skills_dir)
    if modified and not force:
        raise OmhError("local modifications detected; rerun with --force or resolve: " + ", ".join(modified))
    if dry_run:
        return {
            "dry_run": True,
            "skills_dir": str(paths.skills_dir),
            "skills": [template.name for template in templates],
            "source": source,
        }
    paths.skills_dir.mkdir(parents=True, exist_ok=True)
    managed = manifest is not None
    for template in templates:
        _write_skill(paths.skills_dir, template, force=force, managed=managed)
    records = skill_records(paths.skills_dir, source)
    manifest_data = new_manifest(source, paths.skills_dir, records)
    write_manifest(paths.manifest_path, manifest_data)
    return manifest_data


def uninstall_skill_pack(
    paths: OmhPaths,
    *,
    remove_files: bool = False,
    remove_all: bool = False,
    dry_run: bool = False,
    force: bool = False,
    remove_command_package: bool = False,
) -> dict:
    """Remove OMH-managed local files without deleting unrelated Hermes state."""
    removed: list[str] = []
    would_remove: list[str] = []
    kept: list[dict[str, str]] = []

    if remove_all:
        _collect_removal(
            paths.hermes_plugin_dir,
            removed=removed,
            would_remove=would_remove,
            kept=kept,
            dry_run=dry_run,
            force=force,
            managed_plugin=True,
        )
        for team_file in _managed_team_profile_files(paths):
            _collect_removal(
                team_file,
                removed=removed,
                would_remove=would_remove,
                kept=kept,
                dry_run=dry_run,
                force=force,
            )

    if remove_files or remove_all:
        _collect_removal(paths.omh_home, removed=removed, would_remove=would_remove, kept=kept, dry_run=dry_run, force=True)

    command_removed_at = len(removed)
    command_would_remove_at = len(would_remove)
    command_kept_at = len(kept)
    if remove_command_package:
        _collect_command_package_removal(
            removed=removed,
            would_remove=would_remove,
            kept=kept,
            dry_run=dry_run,
        )
    command_removed = removed[command_removed_at:]
    command_would_remove = would_remove[command_would_remove_at:]
    command_kept = kept[command_kept_at:]

    return {
        "schema_version": "omh_uninstall/v1",
        "removed_files": bool(removed),
        "remove_files": remove_files or remove_all,
        "remove_all": remove_all,
        "dry_run": dry_run,
        "omh_home": str(paths.omh_home),
        "plugin_dir": str(paths.hermes_plugin_dir),
        "team_agents_dir": str(paths.hermes_agents_dir),
        "removed_paths": removed,
        "would_remove": would_remove,
        "kept_paths": kept,
        "command_package_remove_requested": remove_command_package,
        "command_package_removed": bool(command_removed),
        "command_package_removed_paths": command_removed,
        "command_package_would_remove": command_would_remove,
        "command_package_kept": command_kept,
    }


def _collect_removal(
    path: Path,
    *,
    removed: list[str],
    would_remove: list[str],
    kept: list[dict[str, str]],
    dry_run: bool,
    force: bool,
    managed_plugin: bool = False,
) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if managed_plugin and not force and not _looks_like_managed_plugin(path):
        kept.append({"path": str(path), "reason": "plugin dir is not an OMH-managed bundle; rerun with --force to remove it"})
        return
    if dry_run:
        would_remove.append(str(path))
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
    removed.append(str(path))


def _looks_like_managed_plugin(path: Path) -> bool:
    return (path / ".omh-plugin-manifest.json").exists()


def _collect_command_package_removal(
    *,
    removed: list[str],
    would_remove: list[str],
    kept: list[dict[str, str]],
    dry_run: bool,
) -> None:
    venv_dir = _managed_command_venv_dir()
    if venv_dir is None:
        kept.append({"path": "omh", "reason": "HOME is not available, so the install.sh-managed command venv cannot be located"})
        return
    executable = Path(sys.executable).expanduser().resolve()
    if not _is_relative_to(executable, venv_dir):
        kept.append(
            {
                "path": str(executable),
                "reason": "current omh command is not running from the install.sh-managed OMH venv",
            }
        )
        return

    for link in _managed_command_links(venv_dir):
        _collect_removal(link, removed=removed, would_remove=would_remove, kept=kept, dry_run=dry_run, force=True)
    _collect_removal(venv_dir, removed=removed, would_remove=would_remove, kept=kept, dry_run=dry_run, force=True)


def _managed_command_venv_dir() -> Path | None:
    explicit = os.environ.get("OMH_VENV_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return (Path(xdg_data_home).expanduser() / "omh" / "venv").resolve()
    home = os.environ.get("HOME")
    if home:
        return (Path(home).expanduser() / ".local" / "share" / "omh" / "venv").resolve()
    return None


def _managed_command_links(venv_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    explicit_bin = os.environ.get("OMH_BIN_DIR")
    home = os.environ.get("HOME")
    if explicit_bin:
        candidates.append(Path(explicit_bin).expanduser() / "omh")
    elif home:
        candidates.append(Path(home).expanduser() / ".local" / "bin" / "omh")
    which = shutil.which("omh")
    if which:
        candidates.append(Path(which))
    if sys.argv and sys.argv[0]:
        candidates.append(Path(sys.argv[0]))

    links: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        path = candidate.expanduser()
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if path in seen or not path.is_symlink() or not _is_relative_to(resolved, venv_dir):
            continue
        seen.add(path)
        links.append(path)
    return links


def _managed_team_profile_files(paths: OmhPaths) -> list[Path]:
    manifest_files = _manifest_team_profile_files(paths)
    if manifest_files:
        return manifest_files
    return _legacy_managed_team_profile_files(paths)


def _manifest_team_profile_files(paths: OmhPaths) -> list[Path]:
    if not paths.team_profile_manifest_dir.exists():
        return []
    files: list[Path] = []
    seen: set[Path] = set()
    for manifest_path in sorted(paths.team_profile_manifest_dir.glob("*.json")):
        manifest, _error = read_json_object_result(manifest_path)
        if manifest is None or manifest.get("schema_version") != TEAM_PROFILE_SCHEMA_VERSION:
            continue
        for raw_path in manifest.get("files", []):
            if not isinstance(raw_path, str):
                continue
            path = Path(raw_path).expanduser().resolve()
            if path in seen or not _is_relative_to(path, paths.hermes_agents_dir):
                continue
            seen.add(path)
            files.append(path)
    return files


def _legacy_managed_team_profile_files(paths: OmhPaths) -> list[Path]:
    if not paths.hermes_agents_dir.exists():
        return []
    files: list[Path] = []
    for path in sorted(paths.hermes_agents_dir.glob("omh-*.md")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "schema_version: omh_team_profile_pack/v1" in text:
            files.append(path)
    return files


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent.resolve())
    except ValueError:
        return False
    return True
