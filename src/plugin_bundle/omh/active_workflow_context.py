"""Read-only, bounded workflow continuation for a standalone Hermes plugin.

The control-plane writer owns activation. Current-message routing and explicit
user instructions outrank this reminder; neither chat text nor history writes
workflow state. Every call reprojects state into the payload metadata, because
retained API history is not proof that a workflow marker survived a host
summary boundary. The rendered reminder rides the message only when it is not
already the latest workflow line in the history Hermes replays: a session
carries one copy rather than one per turn, a compaction that dropped it gets it
again, a changed workflow gets its new text, and a workflow that ended gets
`ACTIVE_WORKFLOW_ENDED_LINE` once.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal, NotRequired, TypedDict, assert_never

from .active_workflow_context_state import (
    ALLOWED_TRANSITIONS,
    WorkflowRecord,
    WorkflowRecordError,
    parse_workflow_record,
    session_fingerprint,
)
from .runtime_reader import default_omh_home


ACTIVE_WORKFLOW_HEAD = "[OMH Active Workflow]"
ACTIVE_WORKFLOW_ENDED_LINE = f"{ACTIVE_WORKFLOW_HEAD} ended; the earlier workflow reminder no longer applies."


class ActiveWorkflowContext(TypedDict):
    schema_version: str
    state: Literal["active", "recovery_required"]
    claim_boundary: str
    projection_fingerprint: str
    compaction_observed: Literal["not_observed"]
    activation_observed: Literal["not_observed"]
    workflow: NotRequired[str]
    lifecycle_state: NotRequired[str]
    session_binding: NotRequired[str]
    phase_ref: NotRequired[str]
    transition_targets: NotRequired[list[str]]
    continuation_rule: NotRequired[str]
    precedence: NotRequired[str]
    interjection_rule: NotRequired[str]
    error_types: NotRequired[list[str]]
    recovery_actions: NotRequired[list[str]]


def active_workflow_context(omh_home: str = "", session_id: str = "") -> ActiveWorkflowContext | None:
    """Read one home-wide active set, then restrict disclosure to its session.

    Malformed state and directory errors are recovery, not an absent workflow.
    Counts/error categories never reveal another session's identity or notes.
    The file and set limits bound this hot-path reader even after corruption.
    """
    directory = (Path(omh_home).expanduser() if omh_home else default_omh_home()) / "state"
    active: list[WorkflowRecord] = []
    errors: set[str] = set()
    try:
        if directory.is_symlink():
            raise WorkflowRecordError("linked_state_directory")
        with os.scandir(directory) as entries:
            for index, entry in enumerate(entries):
                if index >= 512:
                    errors.add("state_scan_limit")
                    break
                if not entry.name.endswith("-state.json"):
                    continue
                try:
                    if entry.is_symlink():
                        raise WorkflowRecordError("linked_state_record")
                    with Path(entry.path).open(encoding="utf-8") as handle:
                        raw = handle.read(65537)
                    if len(raw) > 65536:
                        raise WorkflowRecordError("state_size_limit")
                    record = parse_workflow_record(raw, entry.name[:-len("-state.json")])
                    if record.active:
                        active.append(record)
                except (OSError, ValueError, UnicodeError, RecursionError) as exc:
                    errors.add(type(exc).__name__)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        errors.add(type(exc).__name__)
    if len(active) > 1:
        errors.add("multiple_active_workflows")
    if not errors and not active:
        return None
    if not errors and active[0].session_ref and (
        not session_id or active[0].session_ref != session_fingerprint(session_id)
    ):
        return None
    projection: ActiveWorkflowContext = {
        "schema_version": "active_workflow_context/v1",
        "state": "recovery_required" if errors else "active",
        "claim_boundary": "Metadata-only continuation; not dispatch, execution, review, CI, or merge evidence.",
        "projection_fingerprint": "",
        "activation_observed": "not_observed",
        "compaction_observed": "not_observed",
    }
    if errors:
        projection["error_types"] = sorted(errors)
        projection["recovery_actions"] = [
            "omh state status",
            "restore_unreadable_state_from_trusted_backup",
            "omh state finish --workflow <workflow> --session-ref <session>",
            "omh state clear --workflow <workflow> --session-ref <session>",
        ]
    else:
        record = active[0]
        projection.update(
            workflow=record.workflow,
            lifecycle_state="active",
            session_binding="bound" if record.session_ref else "unbound",
            phase_ref="",
            transition_targets=list(ALLOWED_TRANSITIONS.get(record.workflow, ())),
            continuation_rule="return_to_active_checklist",
            precedence="explicit_user_instruction_outranks_continuation",
            interjection_rule="answer_then_return",
        )
    projection["projection_fingerprint"] = hashlib.sha256(
        json.dumps(projection, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return projection


def render_active_workflow_context(projection: ActiveWorkflowContext) -> str:
    """Render a stable suffix, never the source record or a retained prompt."""
    match projection["state"]:
        case "recovery_required":
            return (
                "[OMH Active Workflow] recovery_required. Inspect omh state status; "
                "restore unreadable state from a trusted backup or finish/clear conflicting "
                "records with the owning --session-ref. Do not silently select a workflow. "
                + projection["claim_boundary"]
            )
        case "active":
            return (
                f"[OMH Active Workflow] workflow={projection.get('workflow')}; lifecycle=active. "
                "Explicit user instructions (cancel, transition, new scope) take precedence. "
                "Answer interjections, then return to this workflow's active checklist and rules. "
                "Continue until finished, blocked, failed, transitioned or cancelled. "
                + projection["claim_boundary"]
            )
        case unreachable:
            assert_never(unreachable)
