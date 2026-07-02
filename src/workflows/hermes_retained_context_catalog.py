from __future__ import annotations

from typing import Final, Literal, TypedDict, assert_never

from .hermes_readiness_catalog import official_basis


HERMES_RETAINED_CONTEXT_SCHEMA_VERSION: Final = "hermes_retained_context/v1"

ChannelStatus = Literal["available", "missing", "unknown"]
RetainedContextStatus = Literal["ready", "needs_setup", "needs_observation"]


class RetainedContextChannel(TypedDict):
    id: str
    label: str
    status: ChannelStatus
    required_for_retained_context: bool
    evidence: list[str]
    metrics: dict[str, int | str | bool]
    improves: list[str]
    message: str


class RetainedContextAction(TypedDict):
    id: str
    command: str
    reason: str


class RetainedContextSummary(TypedDict):
    total_channels: int
    available_channels: int
    missing_required_channels: int
    hermes_native_channels: int
    omh_retention_channels: int
    external_knowledge_channels: int
    uncategorized_channels: int


class HermesRetainedContext(TypedDict):
    schema_version: str
    status: RetainedContextStatus
    hermes_home: str
    omh_home: str
    source_basis: dict[str, str | list[str]]
    summary: RetainedContextSummary
    channels: list[RetainedContextChannel]
    next_actions: list[RetainedContextAction]
    claim_boundary: str


def retained_context_source_basis() -> dict[str, str | list[str]]:
    readiness_basis = official_basis()
    return {
        "source_repo": str(readiness_basis["source_repo"]),
        "basis_version": "hermes_agent_retained_context_basis/v1",
        "readiness_basis_version": str(readiness_basis["basis_version"]),
        "default_branch": str(readiness_basis["default_branch"]),
        "checked_at": str(readiness_basis["checked_at"]),
        "stable_surfaces": _retained_context_surfaces(readiness_basis),
        "evidence_boundary": "Source mapping informs local channel inspection; this command makes no network call.",
        "refresh_policy": str(readiness_basis["refresh_policy"]),
    }


def _retained_context_surfaces(readiness_basis: dict[str, str | list[str]]) -> list[str]:
    inherited = [
        surface
        for surface in _readiness_stable_surfaces(readiness_basis)
        if surface
        in {
            "HERMES_HOME/config.yaml",
            "HERMES_HOME/sessions/sessions.json",
            "HERMES_HOME/state.db",
            "trajectory_compressor.py",
        }
    ]
    return [
        *inherited,
        *[
            "HERMES_HOME/config.yaml memory.provider",
            "plugins/memory/<provider>/plugin.yaml",
            "agent/memory_manager.py",
            "agent/memory_provider.py",
            "mcp_serve.py conversation/session tools",
        ],
    ]


def _readiness_stable_surfaces(readiness_basis: dict[str, str | list[str]]) -> list[str]:
    match readiness_basis["stable_surfaces"]:
        case list() as surfaces:
            return [str(surface) for surface in surfaces]
        case str() as surface:
            return [surface]
        case unreachable:
            assert_never(unreachable)


__all__ = [
    "HERMES_RETAINED_CONTEXT_SCHEMA_VERSION",
    "ChannelStatus",
    "HermesRetainedContext",
    "RetainedContextAction",
    "RetainedContextChannel",
    "RetainedContextStatus",
    "RetainedContextSummary",
    "retained_context_source_basis",
]
