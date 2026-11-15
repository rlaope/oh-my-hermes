"""Typed configuration for the explicit paired-run local adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..system.paths import OmhPaths
from .paired_run_arm_home import PairedRunProviderConfig


class PairedRunLocalRunnerError(ValueError):
    """The explicit local runner cannot safely execute the frozen plan."""


@dataclass(frozen=True, slots=True)
class PairedRunLocalRunnerConfig:
    paths: OmhPaths
    repo_root: Path
    provider: str
    hermes: str = "hermes"
    reasoning: str = "medium"
    timeout_seconds: float = 900.0
    # A custom provider's non-secret declaration; None for a built-in one.
    provider_config: PairedRunProviderConfig | None = None
