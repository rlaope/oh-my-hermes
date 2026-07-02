from __future__ import annotations

from typing import assert_never

from ..config_adapter import read_config
from ..paths import OmhPaths
from .hermes_retained_context_catalog import (
    HERMES_RETAINED_CONTEXT_SCHEMA_VERSION,
    HermesRetainedContext,
    RetainedContextAction,
    RetainedContextChannel,
    RetainedContextStatus,
    RetainedContextSummary,
    retained_context_source_basis,
)
from .hermes_retained_context_probes import retained_context_channels


def build_hermes_retained_context(paths: OmhPaths) -> HermesRetainedContext:
    config_text = read_config(paths.hermes_config_path)
    channels = retained_context_channels(paths, config_text)
    return {
        "schema_version": HERMES_RETAINED_CONTEXT_SCHEMA_VERSION,
        "status": _retained_context_status(channels),
        "hermes_home": str(paths.hermes_home),
        "omh_home": str(paths.omh_home),
        "source_basis": retained_context_source_basis(),
        "summary": _summary(channels),
        "channels": channels,
        "next_actions": _next_actions(channels),
        "claim_boundary": (
            "Hermes retained context is a local metadata-only inspection of Hermes Agent setup markers and OMH "
            "retention artifacts. It is not proof of opaque Hermes internal memory contents, external knowledge "
            "writes, runtime execution, review, CI, merge, or self-applied skill changes."
        ),
    }


def _retained_context_status(channels: list[RetainedContextChannel]) -> RetainedContextStatus:
    if any(channel["required_for_retained_context"] and channel["status"] != "available" for channel in channels):
        return "needs_setup"
    if any(channel["status"] == "available" for channel in channels):
        return "ready"
    return "needs_observation"


def _summary(channels: list[RetainedContextChannel]) -> RetainedContextSummary:
    hermes_native_channels = sum(1 for channel in channels if channel["id"].startswith("hermes_"))
    omh_retention_channels = sum(1 for channel in channels if channel["id"].startswith("omh_"))
    external_knowledge_channels = sum(1 for channel in channels if channel["id"].startswith("external_"))
    return {
        "total_channels": len(channels),
        "available_channels": sum(1 for channel in channels if channel["status"] == "available"),
        "missing_required_channels": sum(
            1 for channel in channels if channel["required_for_retained_context"] and channel["status"] != "available"
        ),
        "hermes_native_channels": hermes_native_channels,
        "omh_retention_channels": omh_retention_channels,
        "external_knowledge_channels": external_knowledge_channels,
        "uncategorized_channels": len(channels)
        - hermes_native_channels
        - omh_retention_channels
        - external_knowledge_channels,
    }


def _next_actions(channels: list[RetainedContextChannel]) -> list[RetainedContextAction]:
    by_id = {channel["id"]: channel for channel in channels}
    actions: list[RetainedContextAction] = []
    if by_id["hermes_config"]["status"] != "available":
        actions.append(
            {
                "id": "run_hermes_setup",
                "command": "hermes setup",
                "reason": "Create config.yaml before retained-context inspection can read memory settings.",
            }
        )
    match by_id["hermes_memory_provider"]["status"]:
        case "available":
            pass
        case "missing" | "unknown":
            actions.append(
                {
                    "id": "configure_memory_provider",
                    "command": "hermes memory setup",
                    "reason": (
                        "Select and materialize a Hermes memory provider before claiming durable "
                        "native memory readiness."
                    ),
                }
            )
        case unreachable:
            assert_never(unreachable)
    if by_id["hermes_sessions_index"]["status"] != "available" and by_id["hermes_state_db"]["status"] != "available":
        actions.append(
            {
                "id": "observe_hermes_runtime",
                "command": "omh runtime status",
                "reason": "No Hermes session index or state database was found yet.",
            }
        )
    if by_id["omh_learning_store"]["status"] != "available":
        actions.append(
            {
                "id": "record_learning_trace",
                "command": "omh learning trace",
                "reason": "Capture reviewed workflow-learning evidence before claiming self-improvement material.",
            }
        )
    return actions


__all__ = [
    "HERMES_RETAINED_CONTEXT_SCHEMA_VERSION",
    "HermesRetainedContext",
    "RetainedContextAction",
    "RetainedContextChannel",
    "RetainedContextSummary",
    "build_hermes_retained_context",
]
