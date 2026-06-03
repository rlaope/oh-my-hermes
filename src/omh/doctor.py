from __future__ import annotations

from dataclasses import dataclass

from .config_adapter import external_dirs, read_config
from .manifest import read_manifest
from .paths import OmhPaths
from .skill_pack import CORE_SKILLS


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    message: str


def run_doctor(paths: OmhPaths) -> list[Check]:
    checks: list[Check] = []
    manifest = read_manifest(paths.manifest_path)
    checks.append(Check("manifest", manifest is not None, f"{paths.manifest_path}"))
    checks.append(Check("skills_dir", paths.skills_dir.exists(), f"{paths.skills_dir}"))
    for skill in CORE_SKILLS:
        path = paths.skills_dir / skill / "SKILL.md"
        checks.append(Check(f"skill:{skill}", path.exists(), str(path)))
    config_text = read_config(paths.hermes_config_path)
    dirs = external_dirs(config_text)
    checks.append(Check("hermes_config", paths.hermes_config_path.exists(), f"{paths.hermes_config_path}"))
    checks.append(Check("external_dir", str(paths.skills_dir) in dirs, f"{paths.skills_dir} in skills.external_dirs"))
    return checks


def doctor_ok(checks: list[Check]) -> bool:
    return all(check.ok for check in checks)

