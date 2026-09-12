"""Let Hermes see how its own memory relates to OMH's approved records.

PR #672 built the comparison but left it CLI-only: `omh memory status` carried
it, and none of the nine registered tools did, so the model could not reach it
from chat. That is the half of the problem #672 did not close -- the store had
governance and no outlet.

The tool later grew a second job. OMH's memory blocks split into a tier that
renders every turn and a tier that is listed by label and read on request, and
the second tier only means anything if something can perform the read. That
something is this tool rather than a memory-provider tool schema: Hermes gates
provider tools behind toolset config (``memory_provider_tools_enabled`` in
``agent/memory_manager.py``), so a tier built on one would disappear for any
operator whose toolsets exclude memory, and ``agent/memory_provider.py`` names
tool-schema bloat as the reason only one external provider may run at all.

Two different redaction rules meet here, and they do not merge. OMH block values
are OMH's own content and are returned in full. Hermes memory entries are not
OMH's, are never returned, and appear only as counts, hashes, and similarity
scores -- the same boundary this file has always held.

Read-only with respect to Hermes: nothing here opens a Hermes file for writing.
Hermes owns ``~/.hermes/memories``, and the `memory` tool Hermes exposes to the
model is what edits it.
"""

from __future__ import annotations

from .. import runtime_paths

import json

from ..degradation import safe_error_type as _safe_error_type
from ..hermes_memory import build_hermes_memory_bridge
from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, observe_plugin_tool_call
from ..memory_blocks import read_memory_block, read_memory_blocks, select_memory_blocks
from ..memory_dreaming import read_dreaming_state, read_latest_consolidation

MEMORY_ACTIONS = ("status", "blocks", "read", "consolidation")

OMH_MEMORY_SCHEMA = {
    "name": "omh_memory",
    "description": (
        "Read OMH's durable memory and how it relates to Hermes' own. Actions: 'status' "
        "compares Hermes' built-in memory (MEMORY.md, USER.md) against OMH's approved records "
        "and reports what fits under Hermes' character cap; 'blocks' is a review-readable status "
        "listing with admission and replay state; 'read' returns a value only for replay-eligible "
        "OMH-reviewed blocks; 'consolidation' reads the latest recorded reminder and counters "
        "without evaluating or consuming them (no 'due' field when no brief is recorded). Hermes "
        "native, provider, and vector context is not_omh_reviewed and never grants OMH admission. "
        "Hermes memory entries are never returned, only counted and hashed. OMH cannot change Hermes memory."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(MEMORY_ACTIONS),
                "description": "Which review/read view to return. Defaults to 'status'. Blocks are review-readable; only replay-eligible reviewed blocks are value-readable.",
            },
            "label": {
                "type": "string",
                "description": "Block label, required by the 'read' action.",
            },
            "observation": OBSERVATION_SCHEMA,
        },
    },
}


def omh_memory_handler(args: dict, **kwargs) -> str:
    observation = observe_plugin_tool_call("omh_memory", args, kwargs)
    action = str((args or {}).get("action", "") or "status").strip().lower()
    if action not in MEMORY_ACTIONS:
        payload, backend = _unknown_action(action), "bundle_memory"
    elif action == "blocks":
        payload, backend = _blocks(), "bundle_memory"
    elif action == "read":
        payload, backend = _read_block(str((args or {}).get("label", "") or "")), "bundle_memory"
    elif action == "consolidation":
        payload, backend = _consolidation()
    else:
        payload, backend = _memory_bridge()
    payload["plugin_tool"] = "omh_memory"
    payload["action"] = action
    payload["source_backend"] = backend
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)


def _memory_bridge() -> tuple[dict[str, object], str]:
    """Compare the two stores using the bundle's own reader.

    This used to delegate to `omh.memory` and fall back when the import failed.
    The Hermes process cannot import that package -- it lives in its own
    environment -- so the fallback was the *only* path taken on the host this
    tool exists for, and the tool answered "package_absent" every time. Measured
    live before the fix: the model called it, got nothing, and shelled out to
    `omh memory status` instead. The reader is vendored here now, which is what
    every other working bundle surface already does.
    """
    try:
        return (
            build_hermes_memory_bridge(_home("OMH_HOME", "~/.omh"), _home("HERMES_HOME", "~/.hermes")),
            "bundle_memory",
        )
    except Exception as exc:
        # A read failure must stay distinguishable from an empty comparison, or
        # an unreadable memory file reads as a memory with nothing in it.
        return _unavailable(_safe_error_type(type(exc).__name__)), "bundle_memory_error"


def _blocks() -> dict[str, object]:
    """Review-readable block status, never values or ineligible descriptions."""
    home = _home("OMH_HOME", "~/.omh")
    blocks = read_memory_blocks(home)
    selection = select_memory_blocks(blocks, omh_home=home)
    rows = []
    for block in blocks:
        row = block.to_summary()
        row["replay"] = _public_replay(selection.evaluations[block.block_id])
        rows.append(row)
    return {
        "schema_version": "omh_memory_block_listing/v2",
        "blocks": rows,
        "block_count": len(rows),
        "next_action": "Use action='read' only for a replay-eligible block label.",
        "claim_boundary": "Listings are review-readable metadata, not evidence Hermes read, wrote, or used memory.",
    }


def _read_block(label: str) -> dict[str, object]:
    """One block's value, or a stated miss.

    A missing block returns ``found: false`` rather than an empty value, so an
    absent block is never mistaken for a block that has nothing to say.
    """
    if not label:
        return {
            "schema_version": "omh_memory_block_read/v1",
            "found": False,
            "reason": "label_required",
            "next_action": "Call action='blocks' to list available labels.",
        }
    home = _home("OMH_HOME", "~/.omh")
    blocks = read_memory_blocks(home)
    selection = select_memory_blocks(blocks, omh_home=home)
    for block in blocks:
        if block.label != label:
            continue
        replay = _public_replay(selection.evaluations[block.block_id])
        if not replay["eligible"]:
            return {
                "schema_version": "omh_memory_block_read/v2",
                "found": True,
                "block_id": block.block_id,
                "revision": block.revision,
                "replay": replay,
                "next_action": "Review or reactivate this block; ineligible blocks never return values.",
            }
        return {
            "schema_version": "omh_memory_block_read/v2",
            "found": True,
            "block": block.to_dict(),
            "replay": replay,
            "claim_boundary": "A replay-eligible value is prepared OMH context, not observed Hermes use or mutation.",
        }
    return {
        "schema_version": "omh_memory_block_read/v1",
        "found": False,
        "reason": "unknown_label",
        "label": label,
        "next_action": "Call action='blocks' to list available labels.",
    }


def _public_replay(evaluation: dict[str, object]) -> dict[str, object]:
    return {
        "eligible": bool(evaluation.get("eligible")),
        "reason_code": str(evaluation.get("reason_code", "ineligible")),
        "admission_state": evaluation.get("admission_state"),
        "source_class": evaluation.get("source_class"),
        "retention_class": evaluation.get("retention_class"),
    }


def _consolidation() -> tuple[dict[str, object], str]:
    """Read the latest reminder and counters without entering a provider session.

    Like `omh memory dream` without `--evaluate`, this is a status query, not
    a scheduler trigger. Keep a recorded due brief visible even when its
    reasons are suppressed for the next evaluation. No brief means unknown,
    not a fresh evaluation that found nothing due.
    """
    omh_home = _home("OMH_HOME", "~/.omh")
    try:
        payload = dict(read_latest_consolidation(omh_home) or {})
        payload["state"] = read_dreaming_state(omh_home)
        payload["evaluated"] = False
        return payload, "bundle_memory"
    except Exception as exc:
        return _unavailable(_safe_error_type(type(exc).__name__)), "bundle_memory_error"


def _unknown_action(action: str) -> dict[str, object]:
    return {
        "schema_version": "omh_memory_unknown_action/v1",
        "status": "unavailable",
        "reason": "unknown_action",
        "requested_action": action,
        "supported_actions": list(MEMORY_ACTIONS),
        "next_action": f"Retry with one of: {', '.join(MEMORY_ACTIONS)}.",
        "claim_boundary": "No memory view was produced. This is not evidence about memory state.",
    }


def _home(variable: str, default: str) -> str:
    return str(runtime_paths.default_omh_home() if variable == "OMH_HOME" else runtime_paths.default_hermes_home())


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


__all__ = ["MEMORY_ACTIONS", "OMH_MEMORY_SCHEMA", "omh_memory_handler", "read_memory_block"]
