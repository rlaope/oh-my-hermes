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

The one write is ``capture``, into OMH's own store. It is the model's path
into that store with no operator step: the store held zero records after two
months while capture and approve existed only as CLI verbs. ``capture`` calls
memory admission (``memory_admission``) in-process -- the same path the
``omh memory capture`` CLI reaches through its adapters -- and reports the
receipt state admission observed on disk, never one it did not.
"""

from __future__ import annotations

from .. import runtime_paths

import json
from pathlib import Path

from ..degradation import safe_error_type as _safe_error_type
from ..hermes_memory import build_hermes_memory_bridge
from ..memory_admission import capture_project_memory_candidate
from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, observe_plugin_tool_call
from ..memory_blocks import read_memory_block, read_memory_blocks, select_memory_blocks
from ..memory_dreaming import read_dreaming_state, read_latest_consolidation
from ..project_identity import resolve_project_identity

MEMORY_ACTIONS = ("status", "blocks", "read", "consolidation", "capture")
CAPTURE_RECORD_TYPES = ("fact", "decision", "lesson", "procedure", "episode")
CAPTURE_SCOPES = ("project", "user")
CAPTURE_RETENTION_CLASSES = ("durable", "standard", "volatile")
# Admission stores at most this many summary characters.
CAPTURE_SUMMARY_MAX_CHARS = 500
CAPTURE_MAX_TAGS = 8

OMH_MEMORY_SCHEMA = {
    "name": "omh_memory",
    "description": (
        "Read and add to OMH's durable memory. Call action='capture' yourself, without asking, when "
        "the user states something worth knowing in a later session: a lasting preference, a decision, "
        "a fact about their setup or project, or a lesson learned. One fact per call, as one or two "
        "sentences with absolute dates (never 'yesterday' or 'next week'). Never capture secrets, raw "
        "logs, transcripts, or task progress. Safe captures are remembered at once; the result's status "
        "says remembered, already_remembered, pending_review, or refused. Call 'status' first only when "
        "unsure what is already held. 'status' compares Hermes' built-in memory (MEMORY.md, USER.md) "
        "with OMH's approved records; 'blocks' lists blocks with admission and replay state; 'read' "
        "returns a replay-eligible block's value; 'consolidation' reads the latest reminder without "
        "evaluating it. Hermes memory entries are never returned, only counted and hashed. OMH cannot "
        "change Hermes memory."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(MEMORY_ACTIONS),
                "description": "Defaults to 'status'. 'capture' writes one memory; the others only read.",
            },
            "label": {
                "type": "string",
                "description": "Block label, required by the 'read' action.",
            },
            "summary": {
                "type": "string",
                "description": "capture: the fact itself, self-contained, at most 500 characters.",
            },
            "record_type": {
                "type": "string",
                "enum": list(CAPTURE_RECORD_TYPES),
                "description": "capture: defaults to 'fact'.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "capture: up to 8 short topic tags.",
            },
            "scope": {
                "type": "string",
                "enum": list(CAPTURE_SCOPES),
                "description": "capture: defaults to 'project' inside an identified repository.",
            },
            "retention_class": {
                "type": "string",
                "enum": list(CAPTURE_RETENTION_CLASSES),
                "description": "capture: defaults to 'durable'; 'volatile' expires within a week.",
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
    elif action == "capture":
        payload, backend = _capture(args or {}, kwargs), "bundle_memory"
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


def _capture(args: dict, kwargs: dict) -> dict[str, object]:
    """Capture one memory through memory admission and map its answer."""
    summary = " ".join(str(args.get("summary", "") or "").split())
    record_type = str(args.get("record_type", "") or "fact").strip().lower()
    retention = str(args.get("retention_class", "") or "durable").strip().lower()
    tags = args.get("tags") or []
    if not summary:
        return _capture_result("refused", reason="summary_required", next_action="Retry with a one- or two-sentence summary.")
    if "\x00" in summary or any(isinstance(tag, str) and "\x00" in tag for tag in (tags if isinstance(tags, list) else [])):
        # Refused rather than stored: the CLI path can never carry one (a NUL
        # cannot travel in an argv), so neither does this one.
        return _capture_result("refused", reason="control_character", next_action="Remove the NUL character and retry.")
    if len(summary) > CAPTURE_SUMMARY_MAX_CHARS:
        return _capture_result("refused", reason="summary_too_long", next_action=f"Restate the fact in at most {CAPTURE_SUMMARY_MAX_CHARS} characters.")
    if record_type not in CAPTURE_RECORD_TYPES:
        return _capture_result("refused", reason="unsupported_record_type", next_action=f"Use one of: {', '.join(CAPTURE_RECORD_TYPES)}.")
    if retention not in CAPTURE_RETENTION_CLASSES:
        return _capture_result("refused", reason="unsupported_retention_class", next_action=f"Use one of: {', '.join(CAPTURE_RETENTION_CLASSES)}.")
    if not isinstance(tags, list) or len(tags) > CAPTURE_MAX_TAGS or not all(isinstance(tag, str) for tag in tags):
        return _capture_result("refused", reason="invalid_tags", next_action=f"Pass at most {CAPTURE_MAX_TAGS} tags as a list of strings.")
    cwd = _session_cwd(kwargs)
    identity = resolve_project_identity(cwd) if cwd is not None else None
    in_project = identity is not None and identity.state == "resolved"
    scope = str(args.get("scope", "") or ("project" if in_project else "user")).strip().lower()
    if scope not in CAPTURE_SCOPES:
        return _capture_result("refused", reason="unsupported_scope", next_action="Use scope 'project' or 'user'.")
    if scope == "project" and not in_project:
        return _capture_result(
            "refused",
            reason="project_scope_unresolved",
            next_action="This session is not inside a repository OMH can identify; retry with scope='user'.",
        )
    try:
        omh_home = Path(_home("OMH_HOME", "~/.omh"))
    except ValueError as exc:  # RuntimeBindingError is a ValueError
        return _capture_result("error", reason=_safe_error_type(type(exc).__name__), next_action="Nothing was saved; this session's OMH home could not be resolved.")
    try:
        payload = capture_project_memory_candidate(
            omh_home,
            summary,
            record_type=record_type,
            retention_class=retention,
            # The model's own loop has no reviewer who would act on a duplicate
            # candidate, so a duplicate names the existing record and writes nothing.
            on_duplicate="skip",
            source="hermes_model",
            # `user` maps to the user-global scope: it needs no acting-principal
            # context, and recall delivers it beside the project scope.
            scope_kind="project" if scope == "project" else "user-global",
            scope_ref=identity.identity if scope == "project" and identity is not None else None,
            tags=list(tags),
        )
    except Exception as exc:
        # In-process now, so a store fault would otherwise raise into Hermes'
        # tool dispatch. It is an error result naming the exception class --
        # never a status that says something was saved.
        return _capture_result(
            "error",
            reason=_safe_error_type(type(exc).__name__),
            next_action="Nothing is confirmed saved. Tell the user the capture failed; call action='status' to see what is held.",
        )
    return _map_capture_payload(payload)


def _map_capture_payload(payload: dict) -> dict[str, object]:
    """Translate an admission result into the tool's closed status set."""
    candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
    record = payload.get("record") if isinstance(payload.get("record"), dict) else {}
    receipt = payload.get("receipt_state")
    fields: dict[str, object] = {
        "receipt_state": str(receipt) if receipt else None,
        "candidate_id": str(candidate.get("candidate_id", "") or "") or None,
        "record_id": str(record.get("record_id", "") or "") or None,
        "admission_state": _admission_state(record),
    }
    if not payload.get("captured"):
        reason = str(payload.get("reason", "") or "not_captured")
        if reason == "duplicate":
            duplicate_of = str(payload.get("duplicate_of", "") or "")
            return _capture_result(
                "already_remembered",
                **{**fields, "record_id": duplicate_of or None},
                duplicate_of=duplicate_of,
                next_action="Nothing new was saved; the same fact is already held.",
            )
        if payload.get("instruction_cue"):
            # A vocabulary item from admission's closed cue list, never the
            # user's text, so the model sees which words made it an order.
            fields["instruction_cue"] = str(payload["instruction_cue"])
        return _capture_result(
            "refused",
            **fields,
            reason=reason,
            # A refusal that names its own fix (an instruction-shaped summary)
            # passes it through, so the model learns how to restate it.
            next_action=(
                "Memory is turned off in OMH settings; nothing was saved."
                if reason == "project_memory_disabled"
                else str(payload.get("next_action", "") or "") or "Nothing was saved. Do not retry the same text."
            ),
        )
    if payload.get("auto_approved"):
        return _capture_result("remembered", **fields, next_action="Saved. Later sessions receive it when it fits their recall budget.")
    return _capture_result(
        "pending_review",
        **{**fields, "admission_state": "pending_review"},
        review_reason=str(payload.get("review_reason", "") or "unknown"),
        next_action=(
            "Saved as a candidate that waits for operator review (`omh memory review`). For "
            "relative_time_phrase, capture the fact again with an absolute date instead."
        ),
    )


def _admission_state(record: dict) -> str | None:
    admission = record.get("admission")
    state = admission.get("state") if isinstance(admission, dict) else None
    return str(state) if state else None


def _capture_result(status: str, **fields: object) -> dict[str, object]:
    return {
        "schema_version": "omh_memory_capture/v1",
        "status": status,
        "receipt_state": None,
        "record_id": None,
        "candidate_id": None,
        "admission_state": None,
        **fields,
        "claim_boundary": (
            "receipt_state is what OMH memory admission observed on local disk; it is not "
            "evidence that a later session recalled or used the memory, and Hermes memory is unchanged."
        ),
    }


def _session_cwd(kwargs: dict) -> Path | None:
    """A host-supplied cwd, else Hermes' logical working directory, else None."""
    supplied = kwargs.get("cwd")
    try:
        if supplied:
            return runtime_paths.expand_path(supplied)
        return runtime_paths.runtime_cwd()
    except (OSError, ValueError):
        return None


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
