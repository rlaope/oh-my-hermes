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
        "checked_at": "2026-07-21",
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
            "HERMES_HOME/kanban.db",
            "HERMES_HOME/skill-bundles",
            "HERMES_HOME/pending/skills",
            "HERMES_HOME/memories",
            "HERMES_HOME/auth.json",
            "HERMES_HOME/SOUL.md",
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
        SurfaceSpec(
            "kanban_db",
            "Hermes Kanban board",
            "file",
            (paths.hermes_home / "kanban.db",),
            False,
            ("durable multi-agent task board", "worktree-per-task", "per-task model overrides"),
            "Hermes kanban.db exists.",
            "No Hermes kanban.db detected yet.",
            "unknown",
        ),
        SurfaceSpec(
            "skill_bundles",
            "Hermes skill bundles",
            "dir",
            (paths.hermes_home / "skill-bundles",),
            False,
            ("skill bundle slash commands",),
            "Hermes skill-bundles directory exists.",
            "No Hermes skill-bundles directory detected.",
            "unknown",
        ),
        SurfaceSpec(
            "pending_skills",
            "Hermes pending skill approvals",
            "dir",
            (paths.hermes_home / "pending" / "skills",),
            False,
            ("skill write-approval review gate",),
            "Hermes pending/skills directory exists.",
            "No Hermes pending/skills directory detected.",
            "unknown",
        ),
        SurfaceSpec(
            "memories_dir",
            "Hermes memories",
            "dir",
            (paths.hermes_home / "memories",),
            False,
            ("MEMORY.md", "USER.md"),
            "Hermes memories directory exists.",
            "No Hermes memories directory detected.",
            "unknown",
        ),
    ]


def omh_reinforcement() -> list[ReinforcementSurface]:
    boundary = "Local OMH command coverage is prepared guidance until host/runtime evidence records observed use."
    return [
        {
            "id": "memory_management",
            "hermes_agent_surface": "state.db memory, session search, user-model context, memories/ (MEMORY.md, USER.md)",
            "omh_commands": ["omh memory status", "omh memory recall", "omh memory review"],
            "mapping_state": "mapped",
            "claim_boundary": boundary,
        },
        {
            "id": "self_improvement",
            "hermes_agent_surface": "skill self-improvement, retrospectives, missed-route learning, skill-bundles/ slash commands",
            "omh_commands": ["omh learning route-signal", "omh learning store-routes", "omh learning review"],
            "mapping_state": "mapped",
            "claim_boundary": boundary,
        },
        {
            "id": "skill_quality_review",
            "hermes_agent_surface": "pending/skills write-approval staging for agent self-authored skills",
            "omh_commands": ["omh recommend \"skill quality\"", "omh capabilities inspect skill-health --json"],
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
            "hermes_agent_surface": (
                "isolated subagents, branch sessions, coding executor handoffs, delegate_task background "
                "subagents, kanban.db durable multi-agent board (worktree-per-task, per-task model overrides)"
            ),
            "omh_commands": ["omh runtime team-readiness", "omh coding delegate", "omh worktree bind"],
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
