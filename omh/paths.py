from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OmhPaths:
    omh_home: Path
    hermes_home: Path

    @property
    def skills_dir(self) -> Path:
        return self.omh_home / "skills"

    @property
    def manifest_path(self) -> Path:
        return self.omh_home / "manifest.json"

    @property
    def hermes_config_path(self) -> Path:
        return self.hermes_home / "config.yaml"


def expand_path(value: str | Path) -> Path:
    return Path(os.path.expandvars(str(value))).expanduser().resolve()


def default_omh_home() -> Path:
    return expand_path(os.environ.get("OMH_HOME", "~/.omh"))


def default_hermes_home() -> Path:
    return expand_path(os.environ.get("HERMES_HOME", "~/.hermes"))


def resolve_paths(
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
) -> OmhPaths:
    return OmhPaths(
        omh_home=expand_path(omh_home) if omh_home else default_omh_home(),
        hermes_home=expand_path(hermes_home) if hermes_home else default_hermes_home(),
    )

