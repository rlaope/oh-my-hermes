"""The declared per-arm Hermes home a confirmed paired-run cell runs in.

Only `omh coding paired-run dispatch --confirm-dispatch` builds one
(`paired_run_arm_home`). Every other Hermes child keeps the safe-mode,
ignore-user-config, file-only transport. This module holds the value the
dispatcher reads and the from-disk observation it signs, and spawns nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Final

from ..quality.paired_run_values import exposure_digest

ARM_SETUP_FIELDS: Final = frozenset({"omh_plugin", "exposure_digest"})
_DIGEST: Final = re.compile(r"^[0-9a-f]{64}$")
_ENABLED_LINE: Final = re.compile(r"""^\s*-\s*["']?omh["']?\s*$""", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class PairedRunArmHome:
    """One disposable arm home whose harness-owned gateway is already warm.

    `skill_names` maps an installed skill directory label back to its
    canonical catalog name, so the observation digest is comparable with the
    arm's frozen `exposed_skills`.
    """

    root: Path
    hermes_home: Path
    home: Path
    key_env_names: tuple[str, ...]
    skill_names: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ArmSetup:
    omh_plugin: bool
    exposure_digest: str

    def to_record(self) -> dict[str, bool | str]:
        return {"omh_plugin": self.omh_plugin, "exposure_digest": self.exposure_digest}


def observe_arm_setup(arm_home: PairedRunArmHome) -> ArmSetup:
    """Read what the arm home actually holds, never what was requested.

    The plugin counts only when its manifest is on disk AND the home's config
    enables it. Skills count only for top-level directories whose label is an
    OMH skill with a SKILL.md; Hermes' own bundled skills sit under category
    directories and are the same for both arms.
    """
    hermes_home = arm_home.hermes_home
    plugin = (hermes_home / "plugins" / "omh" / "plugin.yaml").is_file() and _config_enables_omh(
        hermes_home / "config.yaml"
    )
    labels = dict(arm_home.skill_names)
    skills_dir = hermes_home / "skills"
    present: list[str] = []
    if skills_dir.is_dir():
        for entry in skills_dir.iterdir():
            canonical = labels.get(entry.name)
            if canonical is not None and (entry / "SKILL.md").is_file() and not entry.is_symlink():
                present.append(canonical)
    return ArmSetup(plugin, exposure_digest(tuple(sorted(present))))


def arm_setup_errors(value: object) -> list[str]:
    if not isinstance(value, dict) or set(value) != ARM_SETUP_FIELDS:
        return ["arm_setup must be an object with omh_plugin and exposure_digest"]
    errors: list[str] = []
    if not isinstance(value.get("omh_plugin"), bool):
        errors.append("arm_setup.omh_plugin must be a boolean")
    digest = value.get("exposure_digest")
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        errors.append("arm_setup.exposure_digest must be a lowercase sha256 digest")
    return errors


def parse_arm_setup(value: object) -> ArmSetup | None:
    if arm_setup_errors(value) or not isinstance(value, dict):
        return None
    return ArmSetup(bool(value["omh_plugin"]), str(value["exposure_digest"]))


def _config_enables_omh(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    try:
        parsed = json.loads(text)
    except ValueError:
        # Hermes may rewrite the JSON-shaped file as block YAML on start.
        return "plugins:" in text and _ENABLED_LINE.search(text) is not None
    plugins = parsed.get("plugins") if isinstance(parsed, dict) else None
    enabled = plugins.get("enabled") if isinstance(plugins, dict) else None
    return isinstance(enabled, list) and "omh" in enabled
