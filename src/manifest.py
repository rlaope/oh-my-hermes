from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .hashutil import sha256_file
from .local_store import atomic_write_json, read_json_object, utc_now


@dataclass(frozen=True)
class SkillRecord:
    name: str
    path: str
    sha256: str
    source: str


def new_manifest(source: str, skills_dir: Path, records: list[SkillRecord]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "package": "oh-my-hermes-agent",
        "version": __version__,
        "source": source,
        "installed_at": utc_now(),
        "skills_dir": str(skills_dir),
        "skills": [record.__dict__ for record in sorted(records, key=lambda item: item.name)],
    }


def read_manifest(path: Path) -> dict[str, Any] | None:
    return read_json_object(path)


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    atomic_write_json(path, manifest)


def skill_records(skills_dir: Path, source: str) -> list[SkillRecord]:
    records: list[SkillRecord] = []
    if not skills_dir.exists():
        return records
    for skill_file in sorted(skills_dir.rglob("SKILL.md")):
        rel = skill_file.relative_to(skills_dir)
        records.append(
            SkillRecord(
                name=skill_file.parent.name,
                path=str(rel),
                sha256=sha256_file(skill_file),
                source=source,
            )
        )
    return records


def local_modifications(manifest: dict[str, Any] | None, skills_dir: Path) -> list[str]:
    if not manifest:
        return []
    modified: list[str] = []
    for record in manifest.get("skills", []):
        rel = record.get("path")
        expected = record.get("sha256")
        if not rel or not expected:
            continue
        path = skills_dir / rel
        if not path.exists():
            modified.append(str(rel))
            continue
        if sha256_file(path) != expected:
            modified.append(str(rel))
    return modified
