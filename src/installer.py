from __future__ import annotations

import shutil
from pathlib import Path

from .core.errors import OmhError
from .converter import convert_from_dir
from .local_store import atomic_write_text
from .manifest import local_modifications, new_manifest, read_manifest, skill_records, write_manifest
from .paths import OmhPaths
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


def uninstall_skill_pack(paths: OmhPaths, *, remove_files: bool = False) -> dict:
    removed = False
    if remove_files and paths.omh_home.exists():
        shutil.rmtree(paths.omh_home)
        removed = True
    return {"removed_files": removed, "omh_home": str(paths.omh_home)}
