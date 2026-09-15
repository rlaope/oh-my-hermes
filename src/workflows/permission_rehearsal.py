"""Rehearse a planned batch of tool calls against the local rules, before it runs.

A cron entry or an unattended batch discovers one command at a time which of
its calls the local rules refuse, while the run is already going. This module
answers that up front: given the ``(tool, args)`` pairs a run intends to
issue, which of them does the user's toolcall-rules file refuse, and is an
approval bypass currently active.

It decides nothing new. The refusal verdict comes from
``matched_toolcall_rule`` -- the same matcher the enforcing ``pre_tool_call``
hook calls, so a rehearsal cannot drift from enforcement -- and the bypass
state from ``effective_approval_bypass``. Nothing here writes a file, spawns
a process, or reaches a network.

**Two of the three tiers are derivable, not three.** Refusal comes from the
rules file. Bypass comes from ``approvals.mode`` plus the live session row.
"Needs approval" does not: it lives in Hermes' per-tool approval
declarations, and OMH has no reader for them -- ``approval_bypass.py``'s
``_approvals_mode_off`` reads only the ``approvals:`` section's direct
``mode`` child and says outright that a deeper ``mode:`` is a different key
it does not read. So a call no rule refuses resolves to ``unknown`` with the
reason attached, and no count here folds an ``unknown`` into an allowed
bucket -- there is no allowed bucket. Claiming the third tier would hand an
operator a green light OMH cannot give.

The plan document fails CLOSED, unlike the rules file it is rehearsed
against. The rules loader fails open because a broken rules file must not
break the hook that feeds the model. A plan OMH could not read in full is
not a rehearsal of that plan, and reporting "nothing refused" over it would
be the exact failure this command exists to prevent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

from ..plugin_bundle.omh.approval_bypass import effective_approval_bypass
from ..plugin_bundle.omh.toolcall_rules import (
    MAX_RULES_FILE_BYTES,
    load_toolcall_rules,
    matched_toolcall_rule,
    toolcall_rules_path,
    validate_toolcall_rules_document,
)

PERMISSION_REHEARSAL_SCHEMA_VERSION: Final = "omh_permission_rehearsal/v1"
PERMISSION_REHEARSAL_PLAN_SCHEMA_VERSION: Final = "omh_permission_rehearsal_plan/v1"

# A plan is read whole or not at all, so both bounds refuse rather than
# truncate: a rehearsal whose tail was dropped reports the unrehearsed calls
# as absent instead of unchecked.
MAX_PLANNED_CALLS: Final = 256
MAX_PLAN_FILE_BYTES: Final = 262_144

VERDICT_REFUSED: Final = "refused"
VERDICT_UNKNOWN: Final = "unknown"
PERMISSION_REHEARSAL_VERDICTS: Final = (VERDICT_REFUSED, VERDICT_UNKNOWN)

REASON_REFUSED_BY_RULE: Final = "refused_by_rule"
REASON_NEEDS_APPROVAL_NOT_READABLE: Final = "needs_approval_not_readable"
REASON_TEXT: Final[dict[str, str]] = {
    REASON_REFUSED_BY_RULE: (
        "A toolcall rule in this rules file matches the call; the enforcing pre_tool_call "
        "hook returns the host's block directive for it and the call does not run."
    ),
    REASON_NEEDS_APPROVAL_NOT_READABLE: (
        "No toolcall rule refuses this call. Whether Hermes stops it for approval is not "
        "derivable here: that lives in Hermes' per-tool approval declarations, and OMH "
        "reads only the global approvals.mode bypass."
    ),
}

PERMISSION_REHEARSAL_CLAIM_BOUNDARY: Final = (
    "A rehearsal reads the local rules file and the observed approval-bypass state; it "
    "executes nothing, writes nothing, and reaches no network. An unknown verdict is not "
    "permission: OMH cannot read Hermes' per-tool approval declarations, so a call no rule "
    "refuses may still stop for approval, and no count here treats one as permitted. "
    "`rules.loaded` counts the rules the enforcing hook would read -- a present file with "
    "defects loads fewer, and `omh ops toolcall-rules-validate` names them. The bypass row "
    "is a projection of host state that can lag a toggle. None of this is approval, "
    "execution, review, or safety evidence."
)


@dataclass(frozen=True, slots=True)
class PlannedCall:
    """One ``(tool, args)`` pair an unattended run intends to issue."""

    tool: str
    args: Any


def read_planned_calls(path: Path) -> tuple[PlannedCall, ...]:
    """Parse a plan document off disk. Fail-closed: every defect raises."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"could not read plan file {path}: {exc}") from exc
    if size > MAX_PLAN_FILE_BYTES:
        raise ValueError(
            f"plan file is {size} bytes; at most {MAX_PLAN_FILE_BYTES} are read, and a "
            "partially read plan is not a rehearsal of that plan"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"could not parse plan file {path}: {exc}") from exc
    return parse_planned_calls(raw)


def parse_planned_calls(raw: object) -> tuple[PlannedCall, ...]:
    """The planned calls in a plan document, or ``ValueError`` naming the defect."""
    if not isinstance(raw, dict):
        raise ValueError("plan document must be a JSON object")
    if raw.get("schema_version") != PERMISSION_REHEARSAL_PLAN_SCHEMA_VERSION:
        raise ValueError(f"plan schema_version must be {PERMISSION_REHEARSAL_PLAN_SCHEMA_VERSION}")
    entries = raw.get("calls")
    if not isinstance(entries, list) or not entries:
        raise ValueError("plan calls must be a nonempty list")
    if len(entries) > MAX_PLANNED_CALLS:
        raise ValueError(f"plan lists {len(entries)} calls; at most {MAX_PLANNED_CALLS} are rehearsed")
    calls: list[PlannedCall] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"calls[{index}] must be an object")
        tool = entry.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            raise ValueError(f"calls[{index}] tool must be a nonempty string")
        calls.append(PlannedCall(tool.strip(), entry.get("args", {})))
    return tuple(calls)


def rehearse_planned_calls(
    planned_calls: tuple[PlannedCall, ...],
    *,
    omh_home: str | Path = "",
    hermes_home: str | Path = "",
    now: float | None = None,
) -> dict[str, Any]:
    """The per-call verdict table, the rules-file state, and the bypass state."""
    home = str(omh_home or "")
    rules_path = toolcall_rules_path(home)
    present = rules_path.exists()
    loaded = len(load_toolcall_rules(rules_path))
    defect_count = _rules_defect_count(rules_path) if present else 0
    # One fresh session, calls in plan order: a repeat="once" rule fires at
    # most once across the batch, exactly as it would in the session this
    # batch will run in. The synthetic session id is unique per rehearsal so
    # one invocation can never consume another's once-claims, and never a
    # real session's.
    session_id = f"omh-permission-rehearsal-{uuid4().hex}"
    calls = [_rehearse_one(index, call, session_id, home) for index, call in enumerate(planned_calls)]
    bypass = effective_approval_bypass(home, str(hermes_home or ""), now=now)
    refused = sum(1 for row in calls if row["verdict"] == VERDICT_REFUSED)
    return {
        "schema_version": PERMISSION_REHEARSAL_SCHEMA_VERSION,
        "rules": {
            "path": str(rules_path),
            "present": present,
            "loaded": loaded,
            "defect_count": defect_count,
        },
        "approval_bypass": bypass,
        "calls": calls,
        "summary": {
            "planned": len(calls),
            "refused": refused,
            # Every call no rule refuses. Deliberately not named `allowed`:
            # nothing here can tell whether Hermes will stop it for approval,
            # so there is no bucket an unknown could be counted into.
            "unknown": len(calls) - refused,
            "approval_bypass_active": bypass.get("status") == "observed" and bypass.get("enabled") is True,
        },
        "reason_codes": dict(REASON_TEXT),
        "claim_boundary": PERMISSION_REHEARSAL_CLAIM_BOUNDARY,
    }


def _rehearse_one(index: int, call: PlannedCall, session_id: str, omh_home: str) -> dict[str, Any]:
    rule = matched_toolcall_rule(
        tool_name=call.tool,
        tool_input=call.args,
        session_id=session_id,
        omh_home=omh_home,
    )
    # The row names the rule but never the arguments: the operator wrote both,
    # and echoing a planned call's input into a captured rehearsal payload
    # adds nothing it does not already have.
    if rule is None:
        return {
            "index": index,
            "tool": call.tool,
            "verdict": VERDICT_UNKNOWN,
            "reason": REASON_NEEDS_APPROVAL_NOT_READABLE,
            "rule": "",
        }
    return {
        "index": index,
        "tool": call.tool,
        "verdict": VERDICT_REFUSED,
        "reason": REASON_REFUSED_BY_RULE,
        "rule": rule.name,
    }


def _rules_defect_count(path: Path) -> int:
    """How many defects `omh ops toolcall-rules-validate` would report.

    A rules file whose defects the loader silently skips makes the refusal
    tier answer from a policy the operator did not write -- the same failure
    as ignoring an active bypass, one file earlier. Only the count belongs
    here; the defects themselves stay with the validate command that prints
    them. A file that does not parse at all, or that the hook ignores whole
    for its size, counts as one defect: in both cases no rule is loaded.
    """
    try:
        if path.stat().st_size > MAX_RULES_FILE_BYTES:
            return 1
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 1
    errors, _accepted = validate_toolcall_rules_document(raw)
    return len(errors)
