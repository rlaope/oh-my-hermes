"""Compatibility projection for the superseded `executor_capability/v1` API.

New code must consume `executor_capability_snapshot/v1`. This module remains so
older integrations do not fail at import time while they migrate; every legacy
row is derived from the unified snapshot vocabulary rather than a second table.
"""

from __future__ import annotations

from typing import Any, Final, Mapping

from .pi_family_interop import PI_DISTRIBUTION_HOST, PI_FORK_HOST
from .executor_capability_snapshots import (
    EXECUTOR_CAPABILITY_SNAPSHOT_SCHEMA_VERSION,
    prepared_executor_capability_snapshot,
)


EXECUTOR_CAPABILITY_SCHEMA_VERSION: Final = "executor_capability/v1"
CAPABILITY_STATES: Final = ("supported", "unsupported", "unknown")
EDIT_FORMAT_KEYS: Final = ("hashline", "str_replace", "patch")
INPUT_MODALITY_KEYS: Final = ("text", "image", "audio", "video", "document")
KNOWN_CAPABILITY_PROFILES: Final = ("codex", "claude-code", "pi-family-runtime")
CAPABILITY_HOST_VARIANT_KEYS: Final = ("pi", PI_DISTRIBUTION_HOST, PI_FORK_HOST, "opencode")
EXECUTOR_CAPABILITY_CLAIM_BOUNDARY: Final = (
    "This deprecated compatibility projection is derived from "
    f"{EXECUTOR_CAPABILITY_SNAPSHOT_SCHEMA_VERSION}. It is not a benchmark, ranking, "
    "dispatch, execution, or owner-selection claim."
)


def legacy_executor_capability_projection(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    capabilities = snapshot.get("capabilities")
    rows = capabilities if isinstance(capabilities, Mapping) else {}
    return {
        "schema_version": EXECUTOR_CAPABILITY_SCHEMA_VERSION,
        "profile": str(snapshot.get("executor", "")),
        "edit_format_support": {
            name: _legacy_state(rows.get(f"edit_format_{name}"))
            for name in EDIT_FORMAT_KEYS
        },
        "persistent_eval": _legacy_state(rows.get("persistent_eval")),
        "tool_reentry": _legacy_state(rows.get("tool_reentry")),
        "code_mode_batching": _legacy_state(rows.get("code_mode_batching")),
        "input_modality_support": {name: "unknown" for name in INPUT_MODALITY_KEYS},
        "host_variants": {},
        "provenance": {
            "source": "",
            "observed_at": None,
            "executor_version": None,
        },
        "claim_boundary": EXECUTOR_CAPABILITY_CLAIM_BOUNDARY,
    }


def capability_for_profile(profile_key: str) -> dict[str, Any]:
    if profile_key not in KNOWN_CAPABILITY_PROFILES:
        known = ", ".join(KNOWN_CAPABILITY_PROFILES)
        raise ValueError(f"unknown dispatch profile: {profile_key!r}; known profiles are {known}")
    return legacy_executor_capability_projection(
        prepared_executor_capability_snapshot(profile_key)
    )


def capability_for_profile_or_none(profile_key: str) -> dict[str, Any] | None:
    try:
        return capability_for_profile(profile_key)
    except ValueError:
        return None


def _legacy_state(_: object) -> str:
    """Keep the old all-unknown table conservative during migration.

    Snapshot observations are scope-bound and cannot be losslessly represented
    by the legacy profile-wide tri-state cells.
    """
    return "unknown"
