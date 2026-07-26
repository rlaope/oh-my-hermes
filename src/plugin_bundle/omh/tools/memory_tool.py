"""Let Hermes see how its own memory relates to OMH's approved records.

PR #672 built the comparison but left it CLI-only: `omh memory status` carries
it, and none of the nine registered tools did, so the model could not reach it
from chat. That is the half of the problem #672 did not close -- the store had
governance and no outlet.

Metadata only, like every other OMH ledger: record ids, character counts,
similarity scores, entry indices and hashes. Never the text of a memory entry.
Read-only: Hermes owns `~/.hermes/memories`, and the `memory` tool Hermes
exposes to the model is what edits it.
"""

from __future__ import annotations

import json

from ..degradation import safe_error_type as _safe_error_type
from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, observe_plugin_tool_call

OMH_MEMORY_SCHEMA = {
    "name": "omh_memory",
    "description": (
        "Compare Hermes' built-in memory (MEMORY.md, USER.md) against OMH's approved project "
        "records: what Hermes already holds, what OMH holds that it does not, and whether the "
        "next record fits under Hermes' character cap. Metadata-only and read-only; OMH cannot "
        "change Hermes memory."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "observation": OBSERVATION_SCHEMA,
        },
    },
}


def omh_memory_handler(args: dict, **kwargs) -> str:
    observation = observe_plugin_tool_call("omh_memory", args, kwargs)
    payload, backend = _memory_bridge()
    payload["plugin_tool"] = "omh_memory"
    payload["source_backend"] = backend
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)


def _memory_bridge() -> tuple[dict[str, object], str]:
    try:
        from omh.memory import build_hermes_memory_bridge
        from omh.paths import resolve_paths
    except (ImportError, ModuleNotFoundError):
        # A host without the OMH package must stay indistinguishable from today:
        # answer with the boundary rather than a broken payload.
        return _unavailable("package_absent"), "standalone_plugin_bundle_fallback"
    try:
        return build_hermes_memory_bridge(resolve_paths()), "package_memory"
    except Exception as exc:
        # The package imported but the delegated call raised. Labelling this as
        # the missing-package fallback above would hide a real failure behind a
        # response that looks identical to a host that never had OMH.
        return _unavailable(_safe_error_type(type(exc).__name__)), "package_memory_error"


def _unavailable(reason: str) -> dict[str, object]:
    return {
        "schema_version": "omh_memory_bridge_unavailable/v1",
        "status": "unavailable",
        "reason": reason,
        "next_action": "Run `omh memory status` locally, or `omh doctor` if OMH may not be installed.",
        "claim_boundary": (
            "No memory comparison was produced. This is not evidence that Hermes memory is empty, "
            "in sync, or readable."
        ),
    }
