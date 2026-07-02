from __future__ import annotations

import os
from pathlib import Path
from typing import assert_never

from ..config_adapter import external_dirs, read_config
from ..paths import OmhPaths
from .hermes_readiness_catalog import (
    HERMES_AGENT_READINESS_SCHEMA_VERSION,
    HERMES_AGENT_SOURCE_REPO,
    HermesAgentReadiness,
    NativeSurface,
    NextAction,
    ProbeKind,
    ReadinessStatus,
    ReadinessSummary,
    ReinforcementSurface,
    SurfaceSpec,
    SurfaceStatus,
    official_basis,
    omh_reinforcement,
    surface_specs,
)


def build_hermes_agent_readiness(paths: OmhPaths) -> HermesAgentReadiness:
    config_text = read_config(paths.hermes_config_path)
    configured_dirs = external_dirs(config_text)
    surfaces = [_surface(spec) for spec in surface_specs(paths)]
    surfaces.append(_registered_skill_surface(paths, configured_dirs))
    reinforcement = omh_reinforcement()
    return {
        "schema_version": HERMES_AGENT_READINESS_SCHEMA_VERSION,
        "status": _readiness_status(surfaces),
        "hermes_home": str(paths.hermes_home),
        "omh_home": str(paths.omh_home),
        "official_basis": official_basis(),
        "summary": _summary(surfaces, reinforcement),
        "native_surfaces": surfaces,
        "omh_reinforcement": reinforcement,
        "next_actions": _next_actions(surfaces),
        "claim_boundary": (
            "Hermes Agent readiness is a local prepared inspection of known file-system surfaces and OMH "
            "reinforcement coverage. It is not proof that Hermes loaded OMH, executed work, reviewed changes, "
            "passed CI, merged code, wrote external knowledge, or changed opaque Hermes internal memory."
        ),
    }


def _surface(spec: SurfaceSpec) -> NativeSurface:
    available = _surface_available(spec.kind, spec.paths)
    status: SurfaceStatus = "available" if available else spec.missing_status
    return {
        "id": spec.surface_id,
        "label": spec.label,
        "kind": spec.kind,
        "status": status,
        "required_for_omh": spec.required_for_omh,
        "evidence": [str(path) for path in spec.paths],
        "coverage": list(spec.coverage),
        "message": spec.available_message if available else spec.missing_message,
    }


def _surface_available(kind: ProbeKind, paths: tuple[Path, ...]) -> bool:
    match kind:
        case "file":
            return paths[0].is_file()
        case "dir":
            return paths[0].is_dir()
        case "any_file":
            return any(path.is_file() for path in paths)
        case "any_path":
            return any(path.exists() for path in paths)
        case unreachable:
            assert_never(unreachable)


def _registered_skill_surface(paths: OmhPaths, configured_dirs: list[str]) -> NativeSurface:
    registered = _path_registered(paths.skills_dir, configured_dirs)
    config_exists = paths.hermes_config_path.is_file()
    status: SurfaceStatus = "available" if registered else ("missing" if config_exists else "unknown")
    return {
        "id": "omh_skill_external_dir",
        "label": "OMH skill directory registered in Hermes config",
        "kind": "config_value",
        "status": status,
        "required_for_omh": True,
        "evidence": [str(paths.hermes_config_path), str(paths.skills_dir)],
        "coverage": ["Hermes skill discovery", "OMH managed skill loading"],
        "message": (
            "Hermes config registers the managed OMH skill directory."
            if registered
            else "Hermes config does not register the managed OMH skill directory."
        ),
    }


def _path_registered(path: Path, configured_dirs: list[str]) -> bool:
    target = path.expanduser().resolve()
    return any(Path(os.path.expandvars(value)).expanduser().resolve() == target for value in configured_dirs)


def _summary(surfaces: list[NativeSurface], reinforcement: list[ReinforcementSurface]) -> ReadinessSummary:
    return {
        "total_surfaces": len(surfaces),
        "available_surfaces": sum(1 for surface in surfaces if surface["status"] == "available"),
        "missing_required_surfaces": sum(
            1 for surface in surfaces if surface["required_for_omh"] and surface["status"] != "available"
        ),
        "observed_native_state_surfaces": sum(
            1 for surface in surfaces if surface["id"] in {"sessions_index", "state_db"} and surface["status"] == "available"
        ),
        "omh_reinforcement_surfaces": len(reinforcement),
    }


def _readiness_status(surfaces: list[NativeSurface]) -> ReadinessStatus:
    if any(surface["required_for_omh"] and surface["status"] != "available" for surface in surfaces):
        return "needs_setup"
    if any(surface["id"] in {"sessions_index", "state_db"} and surface["status"] == "available" for surface in surfaces):
        return "ready"
    return "needs_observation"


def _next_actions(surfaces: list[NativeSurface]) -> list[NextAction]:
    by_id = {surface["id"]: surface for surface in surfaces}
    actions: list[NextAction] = []
    if by_id["hermes_config"]["status"] != "available":
        actions.append(
            {
                "id": "run_hermes_setup",
                "command": "hermes setup",
                "reason": "Create the Hermes home config before OMH can verify skill registration.",
            }
        )
    if by_id["managed_omh_skills"]["status"] != "available" or by_id["omh_skill_external_dir"]["status"] != "available":
        actions.append(
            {
                "id": "run_omh_setup",
                "command": "omh setup",
                "reason": "Install managed OMH skills and register the skill directory in Hermes config.",
            }
        )
    if by_id["sessions_index"]["status"] != "available" and by_id["state_db"]["status"] != "available":
        actions.append(
            {
                "id": "observe_hermes_runtime",
                "command": "omh runtime status",
                "reason": "No Hermes sessions index or state database was found, so native runtime activity is not observed.",
            }
        )
    actions.append(
        {
            "id": "review_learning_and_memory",
            "command": "omh learning store-routes",
            "reason": "Review retained memory and self-improvement routing queues before claiming durable learning.",
        }
    )
    return actions


__all__ = [
    "HERMES_AGENT_READINESS_SCHEMA_VERSION",
    "HERMES_AGENT_SOURCE_REPO",
    "HermesAgentReadiness",
    "NativeSurface",
    "NextAction",
    "ReadinessSummary",
    "ReinforcementSurface",
    "build_hermes_agent_readiness",
]
