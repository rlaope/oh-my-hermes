"""Match the recovery to the cause of one unit's failure.

`dispatch_failure_recovery` answers "what kind of failure was that" and offers
three ways out. It does not answer the question the 2026-09-11 incident turned
into a post-mortem item: *which* way out this particular cause admits. A
credential rejection and a permission denial both reach the operator as a
failed unit, and re-running is the right move for neither. A worker that has
been alive for thirty-six minutes retrying the same git workaround is not
failed at all, and adding a second worker to its scope is the worst available
move.

This module is that missing answer, and it is a table rather than a chain of
conditionals so that the answer for a cause can be read in one row.

Five rules are encoded here and nowhere else:

1. **A live worker wins over every other row.** If an in-flight marker still
   names this unit id or this worktree, the plan is `wait_for_live_worker` and
   no rerun is allowed, whatever the cause was. This is the "never add a second
   worker to a scope whose worker is still alive" rule; it is checked first
   precisely so no cause can talk its way past it. Marker presence is not
   liveness (`inflight` says so itself), so the plan reports the marker and
   asks for it to be cleared — it never claims the process exists.
2. **Re-running under the same permissions is not a recovery.** A permission or
   sandbox denial requires a fresh workspace preflight to pass before anything
   is re-dispatched.
3. **A limit is an account fact, not a clock fact.** A limit-shaped failure may
   be re-run only when the account differs from the one that hit the limit, or
   when the recorded reset has elapsed. `reset_text` is carried as the literal
   string the provider wrote and is never parsed into a time — the elapsed
   answer comes from the cooldown window going stale or from an explicitly
   observed `reset_elapsed`, both of which OMH can actually measure.
4. **Missing objects are supplemented, then ONE unit resumes.** The 36-minute
   stall was a partial clone described as complete. Rebuilding the fanout would
   destroy the work the failure left behind; the plan names the single unit.
5. **A stall re-runs only under changed conditions.** `conditions_fingerprint`
   folds the five things that decide whether an attempt is the same attempt
   (owner, model, prompt digest, worktree, permissions). Identical fingerprint,
   no rerun — that is "never re-run under identical failure conditions" made
   false-able rather than asserted in prose.

The table is deliberately keyed by BOTH vocabularies: the `failure_kind` enum
in `dispatch_failure_recovery` (what the dispatcher observed of the process and
its output) and the `unit_state` vocabulary in `unit_execution_state` (what was
observed of the work). A unit carries whichever its producer recorded, and a
unit that carries neither resolves to `unknown`, which offers nothing and
forbids nothing. `tests/test_cause_recovery.py` re-derives both vocabularies
from source and fails when one gains a member with no row, so the class is
caught without the table freezing either vocabulary.

The remaining `failure_kind` spellings are written as literals rather than
imported: the closed enum lives with the classifier that produces it, and this
module is imported BY that classifier, so only the one name the routing has to
branch on (`FAILURE_KIND_WORKSPACE_BLOCKED`) is worth the import that forced
the classifier's own import of this module to be deferred. The derived gate is
what keeps every other spelling equal.

Nothing here reads state, writes state, or spawns anything. `recovery_plan` is
a pure function of the unit record, the in-flight markers it is handed, and the
previous attempt's conditions.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping, NamedTuple, Sequence

from .dispatch_failure_recovery import FAILURE_KIND_WORKSPACE_BLOCKED
from .unit_execution_state import (
    UNIT_STATE_ACCOUNT_LIMIT,
    UNIT_STATE_AWAITING_INPUT,
    UNIT_STATE_DATA_MISSING,
    UNIT_STATE_PERMISSION_BLOCKED,
    UNIT_STATE_PROGRESS_STALLED,
)
from .workspace_preflight import workspace_preflight_unit_state

RECOVERY_PLAN_SCHEMA_VERSION = "unit_recovery_plan/v1"

RECOVERY_PLAN_CLAIM_BOUNDARY = (
    "A recovery plan states which repair the observed cause requires before this unit is "
    "re-dispatched. It is not a claim that the repair will succeed, not evidence that the unit "
    "can succeed, and `allowed_rerun` is a refusal to re-run under conditions that already "
    "failed — never a verdict about the work itself."
)

# The conditions that decide whether a proposed attempt is the SAME attempt.
# Changing any one of them is a changed condition; changing none of them is the
# re-run the post-mortem forbids.
CONDITION_FIELDS: tuple[str, ...] = (
    "owner",
    "model",
    "prompt_sha256",
    "worktree",
    "permissions",
)

# Canonical causes. Every `failure_kind` and every `unit_state` resolves to one
# of these through `resolve_cause`.
CAUSE_LIVE_WORKER_PRESENT = "live_worker_present"
CAUSE_PERMISSION_BLOCKED = "permission_blocked"
CAUSE_ACCOUNT_LIMIT = "account_limit"
CAUSE_DATA_MISSING = "data_missing"
CAUSE_PROGRESS_STALLED = "progress_stalled"
CAUSE_AWAITING_INPUT = "awaiting_input"
CAUSE_AUTH_INVALID = "auth_invalid"
CAUSE_BINARY_MISSING = "binary_missing"
CAUSE_TIMEOUT = "timeout"
CAUSE_CAPABILITY_GATE = "capability_gate"
CAUSE_CREDENTIAL_HIDDEN = "credential_hidden"
CAUSE_CRASH = "crash"
CAUSE_UNKNOWN = "unknown"

# Actions. A reader branches on these, never on the reason prose.
ACTION_WAIT_FOR_LIVE_WORKER = "wait_for_live_worker"
ACTION_REPAIR_PERMISSIONS_THEN_REPROBE = "repair_permissions_then_reprobe"
ACTION_CHECK_ACCOUNT_THEN_SWITCH_IF_ALLOWED = "check_account_then_switch_if_allowed"
ACTION_SUPPLEMENT_OBJECTS_THEN_RESUME_UNIT = "supplement_objects_then_resume_unit"
ACTION_RERUN_WITH_CHANGED_CONDITIONS_OR_CHECKPOINT = "rerun_with_changed_conditions_or_checkpoint"
ACTION_ANSWER_OR_CANCEL = "answer_or_cancel"
ACTION_REAUTHENTICATE_THEN_REDISPATCH = "reauthenticate_then_redispatch"
ACTION_INSTALL_BINARY_THEN_REDISPATCH = "install_binary_then_redispatch"
ACTION_RECORD_CAPABILITY_EVIDENCE_THEN_REDISPATCH = "record_capability_evidence_then_redispatch"
ACTION_PASS_FENCE_READABLE_CREDENTIAL_THEN_REDISPATCH = "pass_fence_readable_credential_then_redispatch"
ACTION_REPORT_OR_CHOOSE_RECOVERY = "report_or_choose_recovery"
ACTION_REPORT_ONLY = "report_only"

# Requirement names. Each one is a condition a caller must be able to show was
# met; an unmet requirement is why `allowed_rerun` is false.
REQUIRE_WORKSPACE_PREFLIGHT_OK = "workspace_preflight_ok"
REQUIRE_ACCOUNT_CHANGED_OR_RESET_ELAPSED = "account_changed_or_reset_elapsed"
REQUIRE_OBJECTS_PRESENT = "objects_present"
REQUIRE_CONDITIONS_CHANGED = "conditions_changed"
REQUIRE_CREDENTIAL_REPAIRED = "credential_repaired"
REQUIRE_BINARY_PRESENT = "binary_present"
REQUIRE_CAPABILITY_EVIDENCE_RECORDED = "capability_evidence_recorded"
REQUIRE_CREDENTIAL_REACHABLE = "credential_reachable"


class RecoveryRow(NamedTuple):
    """One cause, one action, and the conditions a rerun of it requires."""

    cause: str
    action: str
    requires: tuple[str, ...]
    # True when no rerun of this unit is a recovery at all, whatever is
    # satisfied. Distinct from "requires something first": a question nobody
    # answered is answered or cancelled, never re-run.
    never_rerun: bool
    # True when this cause would be inherited by ANY new worker on this scope,
    # so retargeting or re-running through another lane is also refused until
    # the requirement is met. A quota is an account fact and a stall is a
    # conditions fact — neither is inherited, so neither blocks a new worker.
    blocks_new_worker: bool
    # True when the plan resumes exactly one unit rather than the fanout.
    resumes_single_unit: bool
    reason: str


RECOVERY_ROWS: tuple[RecoveryRow, ...] = (
    # A marker still names this unit id or this worktree. This row is checked
    # before the cause is even resolved: a second worker on a live scope is the
    # one recovery that can make things worse than doing nothing.
    RecoveryRow(
        cause=CAUSE_LIVE_WORKER_PRESENT,
        action=ACTION_WAIT_FOR_LIVE_WORKER,
        requires=(),
        never_rerun=True,
        blocks_new_worker=True,
        resumes_single_unit=False,
        reason="an in-flight marker still occupies this scope; a second worker must not be added to it",
    ),
    # A permission or sandbox denial (file write, git index, an isolation dir
    # omh cannot write). The next attempt inherits the same permissions unless
    # something changes them, so a fresh preflight has to pass first.
    RecoveryRow(
        cause=CAUSE_PERMISSION_BLOCKED,
        action=ACTION_REPAIR_PERMISSIONS_THEN_REPROBE,
        requires=(REQUIRE_WORKSPACE_PREFLIGHT_OK,),
        never_rerun=False,
        blocks_new_worker=True,
        resumes_single_unit=True,
        reason="re-running under the same permissions cannot clear a permission denial",
    ),
    # The provider refused for account reasons. Waiting clears it, and so does
    # a different account; nothing else does, and a blind retry inside the
    # cooldown is the behaviour the post-mortem named.
    RecoveryRow(
        cause=CAUSE_ACCOUNT_LIMIT,
        action=ACTION_CHECK_ACCOUNT_THEN_SWITCH_IF_ALLOWED,
        requires=(REQUIRE_ACCOUNT_CHANGED_OR_RESET_ELAPSED,),
        never_rerun=False,
        blocks_new_worker=False,
        resumes_single_unit=True,
        reason="a limit clears with a different account or with its reset, never with a retry inside the cooldown",
    ),
    # Objects the work needs are absent from its isolation: partial-clone
    # blobs, a missing base commit, a ref described but never fetched. The
    # parent supplements and verifies them, then exactly one unit resumes.
    RecoveryRow(
        cause=CAUSE_DATA_MISSING,
        action=ACTION_SUPPLEMENT_OBJECTS_THEN_RESUME_UNIT,
        requires=(REQUIRE_OBJECTS_PRESENT,),
        never_rerun=False,
        blocks_new_worker=True,
        resumes_single_unit=True,
        reason="the objects the work needs are absent; supplement and verify them, then resume this one unit",
    ),
    # Alive and not moving. The only honest rerun is one whose conditions
    # differ, or one that starts from a checkpoint rather than from base.
    RecoveryRow(
        cause=CAUSE_PROGRESS_STALLED,
        action=ACTION_RERUN_WITH_CHANGED_CONDITIONS_OR_CHECKPOINT,
        requires=(REQUIRE_CONDITIONS_CHANGED,),
        never_rerun=False,
        blocks_new_worker=False,
        resumes_single_unit=True,
        reason="identical conditions produced the stall; re-running them reproduces it",
    ),
    # The worker asked a question. A rerun discards the work that reached the
    # question and asks it again.
    RecoveryRow(
        cause=CAUSE_AWAITING_INPUT,
        action=ACTION_ANSWER_OR_CANCEL,
        requires=(),
        never_rerun=True,
        blocks_new_worker=True,
        resumes_single_unit=False,
        reason="the worker is waiting on an answer; answer it or cancel it, a rerun only asks again",
    ),
    # Credential rejection. Same shape as a permission denial — the next
    # attempt on this owner inherits the rejected credential — but another
    # owner carries its own, so a retarget is not blocked.
    RecoveryRow(
        cause=CAUSE_AUTH_INVALID,
        action=ACTION_REAUTHENTICATE_THEN_REDISPATCH,
        requires=(REQUIRE_CREDENTIAL_REPAIRED,),
        never_rerun=False,
        blocks_new_worker=False,
        resumes_single_unit=True,
        reason="the stored credential was rejected; re-running before it is repaired repeats the rejection",
    ),
    # The login is fine but the fence hid it (#3253): a keyring credential over
    # the user D-Bus session, which the bwrap fence hides. Re-authenticating
    # changes nothing and a rerun repeats the refusal; a credential the fence
    # can read (agy: AGY_ADC_AUTH or an API key, granted by name) does. Another
    # owner carries its own credential, so a retarget is not blocked.
    RecoveryRow(
        cause=CAUSE_CREDENTIAL_HIDDEN,
        action=ACTION_PASS_FENCE_READABLE_CREDENTIAL_THEN_REDISPATCH,
        requires=(REQUIRE_CREDENTIAL_REACHABLE,),
        never_rerun=False,
        blocks_new_worker=False,
        resumes_single_unit=True,
        reason=(
            "the CLI's keyring login sits behind the user D-Bus session the fence hides; the login was not "
            "rejected, and a rerun without a fence-readable credential repeats the refusal"
        ),
    ),
    # The dispatcher's own exit 127. Re-running with the binary still absent
    # from PATH is the same pointless attempt.
    RecoveryRow(
        cause=CAUSE_BINARY_MISSING,
        action=ACTION_INSTALL_BINARY_THEN_REDISPATCH,
        requires=(REQUIRE_BINARY_PRESENT,),
        never_rerun=False,
        blocks_new_worker=False,
        resumes_single_unit=True,
        reason="the owner's CLI was not on PATH; install or point at it before re-dispatching",
    ),
    # The frozen capability evidence refused the spawn: no snapshot for the
    # owner, or the media gate (no resolved route, no fresh route-scoped
    # modality evidence, evidence that says unavailable, or a transformation
    # nobody observed). Re-running against the same evidence repeats the
    # refusal; the unit's own `executor_modality_decision` names the one
    # action that changes it. Another owner with its own evidence may take the
    # unit, and the retarget path rechecks that evidence before it spawns.
    RecoveryRow(
        cause=CAUSE_CAPABILITY_GATE,
        action=ACTION_RECORD_CAPABILITY_EVIDENCE_THEN_REDISPATCH,
        requires=(REQUIRE_CAPABILITY_EVIDENCE_RECORDED,),
        never_rerun=False,
        blocks_new_worker=False,
        resumes_single_unit=True,
        reason=(
            "the frozen capability evidence refused the spawn; record fresh route-scoped evidence, bind the "
            "route, or hand the input over as text before re-dispatching"
        ),
    ),
    # Existing behaviour, mapped through unchanged: a timeout and a crash are
    # already offered report / retarget / hermes / wait, and neither carries a
    # precondition omh can check.
    RecoveryRow(
        cause=CAUSE_TIMEOUT,
        action=ACTION_REPORT_OR_CHOOSE_RECOVERY,
        requires=(),
        never_rerun=False,
        blocks_new_worker=False,
        resumes_single_unit=True,
        reason="the unit burned its timeout; re-run it, give it a different owner or lane, or wait",
    ),
    RecoveryRow(
        cause=CAUSE_CRASH,
        action=ACTION_REPORT_OR_CHOOSE_RECOVERY,
        requires=(),
        never_rerun=False,
        blocks_new_worker=False,
        resumes_single_unit=True,
        reason="the unit exited non-zero with no recognised shape; the tails are the only account of why",
    ),
    # Nothing was recorded. Offering a repair for a cause nobody observed would
    # be the invention this repo's evidence rule forbids.
    RecoveryRow(
        cause=CAUSE_UNKNOWN,
        action=ACTION_REPORT_ONLY,
        requires=(),
        never_rerun=False,
        blocks_new_worker=False,
        resumes_single_unit=True,
        reason="no failure kind and no unit state were recorded, so no cause-specific repair is claimed",
    ),
)

_ROWS_BY_CAUSE: dict[str, RecoveryRow] = {row.cause: row for row in RECOVERY_ROWS}

# Vocabulary members that are the same cause under a different name. Both
# vocabularies are aliased here rather than renamed at the producer, because
# each one is right for its own surface: `limit_shaped` describes the output
# shape the dispatcher matched, `account_limit` describes the state the work is
# in, and the recovery is the same either way.
RECOVERY_CAUSE_ALIASES: dict[str, str] = {
    # `failure_kind` spellings (dispatch_failure_recovery).
    "auth_shaped": CAUSE_AUTH_INVALID,
    "limit_shaped": CAUSE_ACCOUNT_LIMIT,
    # `unit_state` spellings (unit_execution_state).
    UNIT_STATE_PERMISSION_BLOCKED: CAUSE_PERMISSION_BLOCKED,
    UNIT_STATE_ACCOUNT_LIMIT: CAUSE_ACCOUNT_LIMIT,
    UNIT_STATE_DATA_MISSING: CAUSE_DATA_MISSING,
    UNIT_STATE_PROGRESS_STALLED: CAUSE_PROGRESS_STALLED,
    UNIT_STATE_AWAITING_INPUT: CAUSE_AWAITING_INPUT,
}

# A workspace preflight refusal splits two ways, and `workspace_preflight` owns
# which — `workspace_preflight_unit_state` is the same function that stamps the
# unit's state, so the routing here and the state on the envelope cannot drift.
# Absent or unreadable, the refusal is read as a file/index denial: that is what
# a preflight refusal mostly is, and it is the more conservative of the two — it
# blocks a new worker, where the objects row would have let one start.
_WORKSPACE_BLOCKED_DEFAULT_CAUSE = CAUSE_PERMISSION_BLOCKED


def recovery_row_for(cause: str) -> RecoveryRow | None:
    """The row for one cause or vocabulary member, or None when it has none."""
    name = str(cause or "").strip()
    return _ROWS_BY_CAUSE.get(RECOVERY_CAUSE_ALIASES.get(name, name))


def has_recovery_row(name: str) -> bool:
    """Whether one vocabulary member resolves to a row. The derived gate's question.

    `workspace_blocked` answers True through `resolve_cause` rather than through
    a row of its own: it is two causes wearing one name, and which one it is
    depends on the preflight payload, not on the name.
    """
    if str(name or "").strip() == FAILURE_KIND_WORKSPACE_BLOCKED:
        return True
    return recovery_row_for(name) is not None


def resolve_cause(
    *,
    failure_kind: str = "",
    unit_state: str = "",
    workspace_preflight: Mapping[str, Any] | None = None,
) -> str:
    """The canonical cause of one failure, from whichever vocabulary recorded it.

    `unit_state` is consulted first: it describes the WORK, which is the thing
    a recovery acts on, and it is the vocabulary that can say `progress_stalled`
    at all. `failure_kind` describes the process and its output tails and
    answers for everything the state vocabulary has no member for. A unit that
    carries neither — or carries a member nothing here knows — is `unknown`.
    """
    state = str(unit_state or "").strip()
    if state:
        row = recovery_row_for(state)
        if row is not None:
            return row.cause
    kind = str(failure_kind or "").strip()
    if kind == FAILURE_KIND_WORKSPACE_BLOCKED:
        return _workspace_blocked_cause(workspace_preflight)
    row = recovery_row_for(kind)
    if row is not None:
        return row.cause
    return CAUSE_UNKNOWN


def _workspace_blocked_cause(preflight: Mapping[str, Any] | None) -> str:
    """Which repair a `workspace_preflight/v1` refusal admits.

    This is the fallback path. A unit the preflight blocked already carries the
    answer as `unit_state`, and `resolve_cause` reads that first, so this runs
    only for a record that lost its state or never had one. It asks the
    preflight's own `workspace_preflight_unit_state` rather than re-deriving the
    rule, so the routing and the stamped state cannot disagree: a second copy of
    "which blocking check decides" is how two answers start to drift.
    """
    if not isinstance(preflight, Mapping):
        return _WORKSPACE_BLOCKED_DEFAULT_CAUSE
    state = workspace_preflight_unit_state(dict(preflight))
    row = recovery_row_for(state) if state else None
    return row.cause if row is not None else _WORKSPACE_BLOCKED_DEFAULT_CAUSE


def unit_worktree(unit: Mapping[str, Any]) -> str:
    """The unit's worktree, under whichever of the two names its producer used.

    An in-flight marker spells it `worktree`; a dispatch result envelope spells
    it `worktree_path`. Both are read because scope matching is the rule that
    must not miss, and neither producer is this module's to rename.
    """
    return str(unit.get("worktree", "") or unit.get("worktree_path", "") or "")


def attempt_conditions(unit: Mapping[str, Any]) -> dict[str, str]:
    """The five fingerprinted conditions plus the account tag, from a unit record.

    A field the producer did not record stays empty rather than being guessed;
    `conditions_fingerprint` folds empties, so a record carrying four of five
    still compares against another record carrying the same four.
    """
    conditions = {field: str(unit.get(field, "") or "") for field in CONDITION_FIELDS}
    conditions["worktree"] = unit_worktree(unit)
    conditions["account_tag"] = str(unit.get("account_tag", "") or "")
    return conditions


def conditions_fingerprint(conditions: Mapping[str, Any] | None) -> str:
    """A short stable digest of the five conditions that make an attempt itself.

    Empty when the mapping names none of them: a fingerprint over nothing would
    compare equal to every other fingerprint over nothing, and "the conditions
    are identical" is exactly the claim that must never be made by accident.
    Absent fields are folded as empty strings so a caller that records four of
    the five still gets a comparable digest.
    """
    if not isinstance(conditions, Mapping):
        return ""
    values = [str(conditions.get(field, "") or "") for field in CONDITION_FIELDS]
    if not any(values):
        return ""
    joined = "\n".join(f"{field}={value}" for field, value in zip(CONDITION_FIELDS, values))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


# `resets 6:10pm (Asia/Seoul)` and friends. The literal string the provider
# wrote is taken and kept; nothing here converts it to a time. A timezone-aware
# reset instant computed from a provider's prose would be a fabricated
# observation, and the elapsed answer comes from the cooldown window instead.
_RESET_TEXT_RE = re.compile(r"\bresets?\s+(?P<text>[^\n\r]{1,60})", re.IGNORECASE)
_MAX_RESET_TEXT = 60


def limit_reset_text(*tails: str) -> str:
    """The literal reset phrase a limit message carried, or an empty string."""
    for tail in tails:
        match = _RESET_TEXT_RE.search(str(tail or ""))
        if match is None:
            continue
        text = match.group("text").strip().rstrip(".,;")
        if text:
            return text[:_MAX_RESET_TEXT]
    return ""


def recovery_plan(
    unit: Mapping[str, Any],
    *,
    inflight: Sequence[Mapping[str, Any]] = (),
    last_attempt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The cause-specific recovery for one unit, and whether a rerun is allowed.

    `unit` is the unit record (or result envelope): `unit_id`, `worktree`, and
    whichever of `failure_kind` / `unit_state` its producer recorded, plus the
    optional observations a requirement is checked against —
    `workspace_preflight`, `objects_present`, `credential_repaired`,
    `binary_present`, `limit_signal`, `reset_elapsed`, and `proposed_attempt`.

    `proposed_attempt` is the conditions the caller intends to re-run under.
    When it is absent the proposal is taken to BE `last_attempt`, because that
    is what re-running the same command does — which is why a stall with no
    stated change is refused rather than waved through.
    """
    unit_id = str(unit.get("unit_id", "") or "")
    live = _live_marker(inflight, unit_id=unit_id, worktree=unit_worktree(unit))
    if live is not None:
        row = _ROWS_BY_CAUSE[CAUSE_LIVE_WORKER_PRESENT]
        return _plan(
            row=row,
            unit_id=unit_id,
            unmet=(),
            reason=(
                f"{row.reason}: marker for unit {live.get('unit_id') or 'unknown'} "
                f"in fanout {live.get('fanout_id') or 'unknown'} started "
                f"{live.get('started_at') or 'at an unrecorded time'}. Marker presence is not "
                "liveness; confirm the worker is gone and clear the marker before re-dispatching."
            ),
        )
    cause = resolve_cause(
        failure_kind=str(unit.get("failure_kind", "") or ""),
        unit_state=str(unit.get("unit_state", "") or ""),
        workspace_preflight=unit.get("workspace_preflight")
        if isinstance(unit.get("workspace_preflight"), Mapping)
        else None,
    )
    row = _ROWS_BY_CAUSE[cause]
    unmet = tuple(
        requirement
        for requirement in row.requires
        if not _requirement_met(requirement, unit=unit, last_attempt=last_attempt)
    )
    reason = row.reason
    if row.cause == CAUSE_DATA_MISSING:
        reason = f"{reason} (resume unit {unit_id or 'unknown'} only, never the whole fanout)"
    if unmet:
        reason = f"{reason}; not yet shown: {', '.join(unmet)}"
    return _plan(row=row, unit_id=unit_id, unmet=unmet, reason=reason)


def _plan(*, row: RecoveryRow, unit_id: str, unmet: Sequence[str], reason: str) -> dict[str, Any]:
    allowed = (not row.never_rerun) and not unmet
    return {
        "schema_version": RECOVERY_PLAN_SCHEMA_VERSION,
        "cause": row.cause,
        "action": row.action,
        "allowed_rerun": bool(allowed),
        "requires": list(row.requires),
        "unmet": list(unmet),
        "blocks_new_worker": bool(row.blocks_new_worker),
        "unit_id": unit_id,
        # The ONE unit to resume, and only once the rerun is actually allowed:
        # a caller acting on this key must never be handed a unit id it may not
        # start yet. Empty otherwise, and empty is never "the fanout" -- the
        # unit this plan is about is always named in `unit_id`.
        "resume_unit_id": unit_id if (row.resumes_single_unit and allowed) else "",
        "reason": reason,
        "claim_boundary": RECOVERY_PLAN_CLAIM_BOUNDARY,
    }


def _live_marker(
    inflight: Sequence[Mapping[str, Any]], *, unit_id: str, worktree: str
) -> Mapping[str, Any] | None:
    """The first present marker occupying this unit's scope, or None.

    Scope is the unit id or the worktree path: two dispatchers racing the same
    unit and two units pointed at one directory are the same hazard.
    """
    for marker in inflight or ():
        if not isinstance(marker, Mapping):
            continue
        if str(marker.get("marker_status", "")) != "present":
            continue
        marker_unit = str(marker.get("unit_id", "") or "")
        marker_worktree = str(marker.get("worktree", "") or "")
        if unit_id and marker_unit == unit_id:
            return marker
        if worktree and marker_worktree == worktree:
            return marker
    return None


def _requirement_met(
    requirement: str, *, unit: Mapping[str, Any], last_attempt: Mapping[str, Any] | None
) -> bool:
    if requirement == REQUIRE_WORKSPACE_PREFLIGHT_OK:
        return _preflight_ok(unit.get("workspace_preflight"))
    if requirement == REQUIRE_ACCOUNT_CHANGED_OR_RESET_ELAPSED:
        return _account_changed(unit, last_attempt) or _reset_elapsed(unit)
    if requirement == REQUIRE_OBJECTS_PRESENT:
        return unit.get("objects_present") is True
    if requirement == REQUIRE_CONDITIONS_CHANGED:
        return _conditions_changed(unit, last_attempt)
    if requirement == REQUIRE_CREDENTIAL_REPAIRED:
        return unit.get("credential_repaired") is True
    if requirement == REQUIRE_BINARY_PRESENT:
        return unit.get("binary_present") is True
    if requirement == REQUIRE_CAPABILITY_EVIDENCE_RECORDED:
        return unit.get("capability_evidence_recorded") is True
    if requirement == REQUIRE_CREDENTIAL_REACHABLE:
        return unit.get("credential_reachable") is True
    return False


def _preflight_ok(preflight: Any) -> bool:
    """A preflight counts only when it says so itself: `ok is True`, nothing else.

    `workspace_preflight/v1` has exactly one pass field and it is a boolean, so
    `is True` rather than a truthiness test — a report whose `ok` arrived as a
    non-empty string or a 1 is a report this module did not understand, and an
    unreadable answer must not read as a pass. Absent, unparsed, or a refusal is
    likewise not one.
    """
    return isinstance(preflight, Mapping) and preflight.get("ok") is True


def _account_changed(unit: Mapping[str, Any], last_attempt: Mapping[str, Any] | None) -> bool:
    """Whether the proposed attempt runs under a different account than the limit did.

    Both tags have to be known: an unreadable tag on either side means the
    account cannot be SHOWN to have changed, and the conservative answer is the
    one that keeps the operator out of the cooldown.
    """
    proposed = _proposed(unit, last_attempt)
    before = str((last_attempt or {}).get("account_tag", "") or "")
    after = str(proposed.get("account_tag", "") or "")
    if not before or not after:
        return False
    return before != after


def _reset_elapsed(unit: Mapping[str, Any]) -> bool:
    """Whether the recorded limit window has passed.

    Two sources, both measured rather than parsed: an explicitly observed
    `reset_elapsed`, and the stored limit signal going stale — the cooldown
    window `executor_auth_signals` already ages. `reset_text` is displayed
    beside both and is never one of them.
    """
    if unit.get("reset_elapsed") is True:
        return True
    signal = unit.get("limit_signal")
    return isinstance(signal, Mapping) and signal.get("stale") is True


def _conditions_changed(unit: Mapping[str, Any], last_attempt: Mapping[str, Any] | None) -> bool:
    before = conditions_fingerprint(last_attempt)
    after = conditions_fingerprint(_proposed(unit, last_attempt))
    if not before or not after:
        return False
    return before != after


def _proposed(unit: Mapping[str, Any], last_attempt: Mapping[str, Any] | None) -> Mapping[str, Any]:
    proposed = unit.get("proposed_attempt")
    if isinstance(proposed, Mapping):
        return proposed
    return last_attempt or {}


def plan_summary_line(plan: Mapping[str, Any] | None) -> str:
    """The one line an operator surface prints: the cause and what it requires.

    Empty for an absent plan so a caller can print it unconditionally without
    emitting a blank claim.
    """
    if not isinstance(plan, Mapping) or not plan.get("cause"):
        return ""
    requires = plan.get("requires") or []
    required = ", ".join(str(name) for name in requires) if requires else "nothing further"
    verdict = "rerun allowed" if plan.get("allowed_rerun") else "rerun not allowed yet"
    return (
        f"Cause {plan.get('cause')}: {plan.get('action')} ({verdict}; requires {required}). "
        f"{plan.get('reason')}"
    )
