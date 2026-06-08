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
    def runtime_dir(self) -> Path:
        return self.omh_home / "runtime"

    @property
    def runtime_state_path(self) -> Path:
        return self.runtime_dir / "state.json"

    @property
    def runtime_runs_dir(self) -> Path:
        return self.runtime_dir / "runs"

    @property
    def runtime_wrapper_sessions_dir(self) -> Path:
        return self.runtime_dir / "wrapper_sessions"

    @property
    def setup_profile_path(self) -> Path:
        return self.omh_home / "setup-profile.json"

    @property
    def target_registry_path(self) -> Path:
        return self.omh_home / "targets.json"

    @property
    def workflow_state_dir(self) -> Path:
        return self.omh_home / "state"

    @property
    def hermes_config_path(self) -> Path:
        return self.hermes_home / "config.yaml"

    @property
    def hermes_plugins_dir(self) -> Path:
        return self.hermes_home / "plugins"

    @property
    def hermes_plugin_dir(self) -> Path:
        return self.hermes_plugins_dir / "omh"

    @property
    def hermes_agents_dir(self) -> Path:
        return self.hermes_home / "agents"

    @property
    def team_profile_manifest_dir(self) -> Path:
        return self.omh_home / "team-profile-packs"


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
