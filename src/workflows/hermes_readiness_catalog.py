from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TypedDict

from ..paths import OmhPaths


HERMES_AGENT_READINESS_SCHEMA_VERSION: Final = "hermes_agent_readiness/v1"
HERMES_AGENT_SOURCE_REPO: Final = "NousResearch/hermes-agent"

ProbeKind = Literal["file", "dir", "any_file", "any_path"]
SurfaceKind = ProbeKind | Literal["config_value"]
SurfaceStatus = Literal["available", "missing", "unknown"]
ReadinessStatus = Literal["ready", "needs_setup", "needs_observation"]
MappingState = Literal["mapped"]


class NativeSurface(TypedDict):
    id: str
    label: str
    kind: SurfaceKind
    status: SurfaceStatus
    required_for_omh: bool
    evidence: list[str]
    coverage: list[str]
    message: str


class ReinforcementSurface(TypedDict):
    id: str
    hermes_agent_surface: str
    omh_commands: list[str]
    mapping_state: MappingState
    claim_boundary: str


class NextAction(TypedDict):
    id: str
    command: str
    reason: str


class ReadinessSummary(TypedDict):
    total_surfaces: int
    available_surfaces: int
    missing_required_surfaces: int
    observed_native_state_surfaces: int
    omh_reinforcement_surfaces: int


class HermesAgentReadiness(TypedDict):
    schema_version: str
    status: ReadinessStatus
    hermes_home: str
    omh_home: str
    official_basis: dict[str, str | list[str]]
    summary: ReadinessSummary
    native_surfaces: list[NativeSurface]
    omh_reinforcement: list[ReinforcementSurface]
    next_actions: list[NextAction]
    claim_boundary: str


@dataclass(frozen=True, slots=True)
class SurfaceSpec:
    surface_id: str
    label: str
    kind: ProbeKind
    paths: tuple[Path, ...]
    required_for_omh: bool
    coverage: tuple[str, ...]
    available_message: str
    missing_message: str
    missing_status: SurfaceStatus = "missing"


def official_basis() -> dict[str, str | list[str]]:
    return {
        "source_repo": HERMES_AGENT_SOURCE_REPO,
        "basis_version": "hermes_agent_source_basis/v1",
        "default_branch": "main",
        "checked_at": "2026-07-02",
        "stable_surfaces": [
            "HERMES_HOME/config.yaml",
            "HERMES_HOME/skills",
            "HERMES_HOME/optional-skills",
            "HERMES_HOME/plugins",
            "HERMES_HOME/sessions/sessions.json",
            "HERMES_HOME/state.db",
            "hermes mcp serve",
            "gateway",
            "cron",
            "trajectory_compressor.py",
        ],
        "evidence_boundary": "Official source mapping informs this local probe; the command itself makes no network call.",
        "refresh_policy": "Refresh this basis when official Hermes Agent surface names used by this probe change.",
    }


def surface_specs(paths: OmhPaths) -> list[SurfaceSpec]:
    managed_skill = paths.skills_dir / "oh-my-hermes" / "SKILL.md"
    return [
        SurfaceSpec(
            "hermes_config",
            "Hermes config",
            "file",
            (paths.hermes_config_path,),
            True,
            ("setup", "skill registration"),
            "Hermes config exists.",
            "Hermes config is missing; Hermes setup has not produced a local config marker.",
        ),
        SurfaceSpec(
            "native_skills",
            "Hermes native skills",
            "dir",
            (paths.hermes_home / "skills",),
            True,
            ("Hermes skill loading",),
            "Hermes native skills directory exists.",
            "Hermes native skills directory is missing.",
        ),
        SurfaceSpec(
            "managed_omh_skills",
            "Managed OMH skills",
            "file",
            (managed_skill,),
            True,
            ("OMH skill pack", "router guidance"),
            "Managed oh-my-hermes skill is installed.",
            "Managed oh-my-hermes skill is not installed.",
        ),
        SurfaceSpec(
            "optional_skills",
            "Hermes optional skills",
            "dir",
            (paths.hermes_home / "optional-skills",),
            False,
            ("optional skill catalog",),
            "Hermes optional-skills directory exists.",
            "No Hermes optional-skills directory detected.",
            "unknown",
        ),
        SurfaceSpec(
            "plugins",
            "Hermes plugins",
            "dir",
            (paths.hermes_plugins_dir,),
            False,
            ("plugin bundle", "host observation"),
            "Hermes plugins directory exists.",
            "No Hermes plugins directory detected.",
            "unknown",
        ),
        SurfaceSpec(
            "mcp_host_config",
            "MCP host config",
            "any_file",
            (paths.hermes_home / ".mcp.json", paths.hermes_home / "mcp.json"),
            False,
            ("MCP bridge", "tool visibility"),
            "MCP host config marker exists.",
            "No MCP host config marker detected.",
            "unknown",
        ),
        SurfaceSpec(
            "sessions_index",
            "Hermes sessions index",
            "file",
            (paths.hermes_home / "sessions" / "sessions.json",),
            False,
            ("conversation recall", "MCP session bridge"),
            "Hermes sessions index exists.",
            "No Hermes sessions index detected yet.",
            "unknown",
        ),
        SurfaceSpec(
            "state_db",
            "Hermes state database",
            "file",
            (paths.hermes_home / "state.db",),
            False,
            ("memory", "session search", "cron runs", "subagent lineage"),
            "Hermes state.db exists.",
            "No Hermes state.db detected yet.",
            "unknown",
        ),
        SurfaceSpec(
            "source_checkout",
            "Hermes Agent source checkout",
            "any_file",
            (
                paths.hermes_home / "hermes-agent" / "README.md",
                paths.hermes_home / "hermes-agent" / "mcp_serve.py",
                paths.hermes_home / "hermes-agent" / "hermes_state.py",
            ),
            False,
            ("operator inspection", "official surface alignment"),
            "Hermes Agent source checkout markers exist.",
            "No Hermes Agent source checkout marker detected under Hermes home.",
            "unknown",
        ),
    ]


def omh_reinforcement() -> list[ReinforcementSurface]:
    boundary = "Local OMH command coverage is prepared guidance until host/runtime evidence records observed use."
    return [
        {
            "id": "memory_management",
            "hermes_agent_surface": "state.db memory, session search, user-model context",
            "omh_commands": ["omh memory status", "omh memory recall", "omh memory review"],
            "mapping_state": "mapped",
            "claim_boundary": boundary,
        },
        {
            "id": "self_improvement",
            "hermes_agent_surface": "skill self-improvement, retrospectives, missed-route learning",
            "omh_commands": ["omh learning route-signal", "omh learning store-routes", "omh learning review"],
            "mapping_state": "mapped",
            "claim_boundary": boundary,
        },
        {
            "id": "loop_control",
            "hermes_agent_surface": "cron, recurring workflows, long-running goals",
            "omh_commands": ["omh loop status", "omh loop run-once", "omh goal status"],
            "mapping_state": "mapped",
            "claim_boundary": boundary,
        },
        {
            "id": "wiki_external_knowledge",
            "hermes_agent_surface": "external notes, wiki, Obsidian-like markdown vaults, Notion or document stores",
            "omh_commands": ["omh recommend \"wiki\"", "omh chat interact \"connect my knowledge store\""],
            "mapping_state": "mapped",
            "claim_boundary": "External knowledge targets are abstract destinations; OMH does not claim a write until observed.",
        },
        {
            "id": "runtime_observation",
            "hermes_agent_surface": "gateway sessions, MCP bridge events, plugin host load/use",
            "omh_commands": ["omh runtime status", "omh runtime observe", "omh plugin observe-host", "omh mcp sessions"],
            "mapping_state": "mapped",
            "claim_boundary": boundary,
        },
        {
            "id": "subagent_and_handoff",
            "hermes_agent_surface": "isolated subagents, branch sessions, coding executor handoffs",
            "omh_commands": ["omh runtime team-readiness", "omh coding delegate", "omh worktree prepare"],
            "mapping_state": "mapped",
            "claim_boundary": boundary,
        },
    ]


__all__ = [
    "HERMES_AGENT_READINESS_SCHEMA_VERSION",
    "HERMES_AGENT_SOURCE_REPO",
    "HermesAgentReadiness",
    "NativeSurface",
    "NextAction",
    "MappingState",
    "ProbeKind",
    "ReadinessStatus",
    "ReadinessSummary",
    "ReinforcementSurface",
    "SurfaceKind",
    "SurfaceSpec",
    "SurfaceStatus",
    "official_basis",
    "omh_reinforcement",
    "surface_specs",
]
