"""Terminal-state journal for one fanout run, and the resume plan read off it.

A dispatch summary answers "what happened", in full, for a human and for `omh
coding fanout brief`. It is not a resume input: it carries per-unit telemetry,
capability snapshots, bounded output tails, and a merge view, and deciding what
to re-run by re-deriving all of that on every resume would couple the resume
rule to every field any of those surfaces later adds.

The journal is the narrow projection instead: one row per unit, holding only
the four things a resume decision needs.

1. **What terminally happened** -- succeeded, failed, declined by the unit's
   own conclusive negative answer, skipped because a dependency did not
   clear, or never attempted at all. `declined` is not a shade of `failed`:
   the unit itself reported (in a validated `fanout_unit_result/v1` sidecar)
   that the work cannot be done at all -- the target does not exist, the
   request is refused by policy, or the criteria are infeasible as
   specified -- which a retry cannot answer differently.
2. **How it failed**, in the classification vocabulary `fanout_retry` already
   owns, read off the retry decision the dispatcher recorded rather than
   re-derived from tails the summary does not keep.
3. **Whether it may be replayed.** Same predicate, same three verdicts, plus
   the one case an in-flight retry never has to consider: a unit that never
   spawned in the prior run left nothing behind, so it is trivially safe.
4. **What it was blocked on**, so a dependent can be un-skipped when its
   blocker is going to be attempted again.

The resume rule is replay-safety, not transience. An automatic retry inside a
run declines terminal failures because re-running them would spend a whole
agent-CLI run to re-derive an answer already in hand; an operator asking to
resume an interrupted fanout has already decided that answer is worth
re-deriving. What stays refused in both places is a replay that would destroy
observed work: a unit whose failure left changes in its worktree, wrote a
result artifact, or could not be measured at all is held, with the reason
named, and continued by hand through the recovery path.

A declined unit is refused a third way, unconditionally: replay-safety is
about whether re-dispatching would destroy something, and a decline holds
regardless of that answer, because re-dispatching would not produce a
different verdict either way. `RESUME_HOLD_DECLINED` is checked ahead of
replay-unsafe side effects for exactly that reason -- the unit's own
conclusive negative answer is why it is held, not what it may have touched
on the way to reaching it.

Writes go through `atomic_write_json` -- serialize, write a sibling temp,
rename over -- so an interrupted write leaves the previous journal exactly as
it was rather than a truncated document nothing can resume from. A journal
that cannot be read as this schema raises `FanoutJournalError` carrying a
machine-readable `reason_code`; a resume must refuse loudly rather than treat
an unreadable prior run as "nothing happened" and re-dispatch everything.

A plan decides eligibility, not outcome, and it deliberately does not reach
into the repository: a unit whose earlier attempt left its worktree in place
is still selected here, and still meets the dispatcher's existing
`worktree_path_already_exists` refusal, which already names its own remedy.
Nothing in this module removes a worktree -- deleting an operator's directory
is a much larger claim than deciding what is eligible to run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..system.local_store import atomic_write_json, utc_now
from .fanout_retry import (
    REPLAY_SAFE,
    REPLAY_UNSAFE_SIDE_EFFECTS,
    classify_unit_failure,
    replay_safety,
)

FANOUT_RUN_JOURNAL_SCHEMA_VERSION = "fanout_run_journal/v1"
FANOUT_RESUME_PLAN_SCHEMA_VERSION = "fanout_resume_plan/v1"

JOURNAL_CLAIM_BOUNDARY = (
    "A run journal records the terminal state each unit reached in one dispatch and whether "
    "re-running it would destroy observed work. It is not verification, review, CI, or merge "
    "evidence, and a resumed unit that succeeds is no more verified than one that succeeded first time."
)
RESUME_CLAIM_BOUNDARY = (
    "A resume plan states which units a prior journal makes eligible for another dispatch and why "
    "the rest are held. Deciding a unit is eligible is not a claim that re-running it will succeed, "
    "and holding one is not a claim that its work is complete."
)

# Terminal states. Every unit in a dispatch lands in exactly one of them.
TERMINAL_SUCCEEDED = "succeeded"
TERMINAL_FAILED = "failed"
TERMINAL_DECLINED = "declined"
TERMINAL_SKIPPED_BY_DEPENDENCY = "skipped_by_dependency"
TERMINAL_NOT_ATTEMPTED = "not_attempted"
# A unit whose process was running when the dispatch was stopped, or that was in
# flight and never reported back. Kept apart from `failed` because a resume acts
# on it differently: nothing about the unit's own work is known to be wrong, so
# the question is whether to run it again, not what to fix. It still goes
# through the replay-safety gate -- a killed unit can leave a dirty worktree
# exactly as a crashed one can.
TERMINAL_CANCELLED = "cancelled"

# The journal's own name for a decline in `failure_class`, kept apart from
# every class `fanout_retry` owns: a decline was never classified by the
# retry ladder's transport-vs-terminal question (`fanout_retry` only asks
# "is this the unit's own answer", and a decline always is), so it earns its
# own label rather than borrowing `terminal_failure` and reading as an
# ordinary bug the retry ladder happened to give up on.
FAILURE_CLASS_DECLINED_CONCLUSIVE = "declined_conclusive"

# Resume actions. The four `hold_*` actions mean "not re-dispatched", each for
# a different reason an operator acts on differently.
RESUME_RERUN_FAILED = "rerun_replay_safe_failure"
RESUME_RERUN_NOT_ATTEMPTED = "rerun_not_attempted"
RESUME_UNSKIP_DEPENDENT = "unskip_dependent"
RESUME_HOLD_SUCCEEDED = "hold_succeeded"
RESUME_HOLD_REPLAY_UNSAFE = "hold_replay_unsafe"
RESUME_HOLD_BLOCKED_DEPENDENCY = "hold_blocked_dependency"
RESUME_HOLD_DECLINED = "hold_declined_conclusive"
# The operator chose "wait" for this unit in the dispatch recovery interview:
# its provider refused to serve the owner, and the answer was to come back
# later rather than retarget or switch lanes. It is a rerun action with its own
# name so the resume record says the unit is being re-attempted because someone
# asked for exactly that, not because a failure happened to be replay-safe.
RESUME_RERUN_AWAITING_RETRY = "rerun_awaiting_retry"
# The prior run was stopped while this unit was running. It is re-dispatched
# under its own action name so a resume record says the unit is being attempted
# again because someone stopped it, not because it failed replay-safely.
RESUME_RERUN_CANCELLED = "rerun_cancelled"

RESUME_HOLD_ACTIONS = frozenset(
    {RESUME_HOLD_SUCCEEDED, RESUME_HOLD_REPLAY_UNSAFE, RESUME_HOLD_BLOCKED_DEPENDENCY, RESUME_HOLD_DECLINED}
)
RESUME_RERUN_ACTIONS = frozenset(
    {
        RESUME_RERUN_FAILED,
        RESUME_RERUN_NOT_ATTEMPTED,
        RESUME_UNSKIP_DEPENDENT,
        RESUME_RERUN_AWAITING_RETRY,
        RESUME_RERUN_CANCELLED,
    }
)

# Reason codes for an unreadable journal, in OMH's `reason_code` idiom so a
# wrapper branches on a code rather than on prose.
JOURNAL_MISSING = "journal_missing"
JOURNAL_CORRUPT = "journal_corrupt"
JOURNAL_SCHEMA_UNSUPPORTED = "journal_schema_unsupported"
JOURNAL_FANOUT_MISMATCH = "journal_fanout_mismatch"

# Statuses a unit can carry without any process ever having started for it.
# They are failures of the batch around the unit, not answers from the unit,
# so a resume re-attempts them -- an executor that was not ready then may be
# ready now, and a worktree that could not be created may create cleanly.
_NEVER_SPAWNED_STATUSES = frozenset(
    {
        "not_selected",
        "interrupted",
        # The dispatcher's own word for a unit a cancelled batch never spawned.
        # `interrupted` stays a member so a journal written before the
        # cancellation states existed still resumes the way it always did.
        "not_started_cancelled",
        "model_choice_required",
        "spawn_ceiling_reached",
        "review_dispatch_budget_exhausted",
        # A cooldown veto refuses the spawn before the worktree exists, so the
        # unit left nothing behind and a later resume — by which time the
        # window may have reset or the credential been repaired — re-attempts
        # it like any other unit that never ran.
        "executor_limit_cooldown",
        "executor_auth_invalid",
    }
)
_SUCCEEDED_STATUSES = frozenset({"completed", "already_completed", "dry_run_planned"})

_JOURNAL_UNIT_KEYS = (
    "unit_id",
    "run_ref",
    "owner",
    "terminal_state",
    "status",
    "failure_class",
    "failure_label",
    "decline_reason",
    "replay_safe",
    "replay_verdict",
    "side_effect",
    "blocked_on",
)


class FanoutJournalError(ValueError):
    """A stored run journal could not be read as `fanout_run_journal/v1`."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def journal_unit_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Project one dispatch-summary unit entry into its journal row.

    Carried-forward rows come back unchanged: a unit held by an earlier resume
    is recorded in that run's summary as a skip, and re-deriving its state from
    the skip would lose exactly the verdict that held it -- a unit refused as
    replay-unsafe would read as `not_attempted` on the next resume and be
    re-dispatched, which is the one outcome the hold exists to prevent.
    """
    carried = _carried_forward(entry)
    if carried is not None:
        return carried
    state = _terminal_state(entry)
    row: dict[str, Any] = {
        "unit_id": str(entry.get("unit_id", "")),
        "run_ref": str(entry.get("run_ref", "")),
        "owner": str(entry.get("owner") or "choose"),
        "terminal_state": state,
        "status": str(entry.get("status", "")),
        **_failure_classification(entry, state=state),
        "decline_reason": _decline_reason(entry) if state == TERMINAL_DECLINED else "",
        **_entry_replay_safety(entry, succeeded=state == TERMINAL_SUCCEEDED),
        "blocked_on": [str(dep) for dep in entry.get("blocked_on", []) or []],
    }
    exit_code = entry.get("exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        row["exit_code"] = exit_code
    # Optional rather than part of `_JOURNAL_UNIT_KEYS`: a journal written
    # before the recovery lane existed is still readable, and a unit nobody
    # chose to defer carries no marker at all.
    kind = str(entry.get("failure_kind", ""))
    if kind:
        row["failure_kind"] = kind
    if entry.get("awaiting_retry"):
        row["awaiting_retry"] = True
        choice = entry.get("recovery_choice")
        if isinstance(choice, Mapping):
            row["awaiting_retry_kind"] = str(choice.get("failure_kind", ""))
    return row


def build_fanout_run_journal(summary: Mapping[str, Any]) -> dict[str, Any]:
    """The journal for one completed dispatch, built from its own summary."""
    order = [str(unit_id) for unit_id in summary.get("merge_order", []) or []]
    rows = {
        str(entry.get("unit_id", "")): journal_unit_entry(entry)
        for entry in summary.get("units", []) or []
        if isinstance(entry, Mapping)
    }
    journal: dict[str, Any] = {
        "schema_version": FANOUT_RUN_JOURNAL_SCHEMA_VERSION,
        "fanout_id": str(summary.get("fanout_id", "")),
        "observed_at": utc_now(),
        "base_sha": str(summary.get("base_sha", "")),
        "merge_order": order,
        "units": [rows[unit_id] for unit_id in order if unit_id in rows],
        "privacy": "metadata_only",
        "claim_boundary": JOURNAL_CLAIM_BOUNDARY,
    }
    if summary.get("interrupted"):
        # The state that makes a resume worth having: this run was cut short,
        # so units reading `not_attempted` were never asked the question.
        journal["interrupted"] = True
    return journal


def write_fanout_run_journal(path: Path, journal: Mapping[str, Any]) -> Path:
    """Persist one run journal crash-consistently and return its path.

    `atomic_write_json` writes a sibling temp file and renames it over the
    target, so a write interrupted at any point leaves the previous journal
    byte-identical instead of a half-document a resume would misread.
    """
    atomic_write_json(path, dict(journal), private=True)
    return path


def read_fanout_run_journal(path: Path, *, expected_fanout_id: str = "") -> dict[str, Any]:
    """Load one run journal, refusing anything this schema cannot resume from."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FanoutJournalError(f"run journal not found: {path}", reason_code=JOURNAL_MISSING) from exc
    except OSError as exc:
        raise FanoutJournalError(f"run journal unreadable: {exc}", reason_code=JOURNAL_CORRUPT) from exc
    try:
        journal = json.loads(raw)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise FanoutJournalError(f"run journal is not valid JSON: {exc}", reason_code=JOURNAL_CORRUPT) from exc
    if not isinstance(journal, dict):
        raise FanoutJournalError("run journal must be a JSON object", reason_code=JOURNAL_CORRUPT)
    if journal.get("schema_version") != FANOUT_RUN_JOURNAL_SCHEMA_VERSION:
        raise FanoutJournalError(
            f"unsupported run journal schema_version: {journal.get('schema_version') or 'missing'}",
            reason_code=JOURNAL_SCHEMA_UNSUPPORTED,
        )
    units = journal.get("units")
    if not isinstance(units, list) or not all(isinstance(row, Mapping) for row in units):
        raise FanoutJournalError("run journal units must be a list of objects", reason_code=JOURNAL_CORRUPT)
    for row in units:
        missing = [key for key in _JOURNAL_UNIT_KEYS if key not in row]
        if missing:
            raise FanoutJournalError(
                f"run journal unit {row.get('unit_id') or '?'} is missing {', '.join(missing)}",
                reason_code=JOURNAL_CORRUPT,
            )
    if expected_fanout_id and str(journal.get("fanout_id", "")) != expected_fanout_id:
        raise FanoutJournalError(
            f"run journal is for fanout {journal.get('fanout_id') or '?'}, not {expected_fanout_id}",
            reason_code=JOURNAL_FANOUT_MISMATCH,
        )
    return journal


def plan_fanout_resume(
    journal: Mapping[str, Any],
    *,
    order: Sequence[str],
    depends_on: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    """Decide, per unit, whether a resume re-dispatches it and say why.

    Walked in `merge_order`, which the contract validator already guarantees
    names every unit exactly once and which a prepared fanout emits in
    dependency order, so a unit's blockers are always decided before it is.
    """
    rows = {str(row.get("unit_id", "")): row for row in journal.get("units", []) or [] if isinstance(row, Mapping)}
    decisions: list[dict[str, Any]] = []
    selected: list[str] = []
    resumable: set[str] = set()
    for unit_id in (str(value) for value in order):
        row = rows.get(unit_id)
        blockers = [str(dep) for dep in depends_on.get(unit_id, []) or []]
        unresolved = [dep for dep in blockers if dep not in resumable]
        decision = _unit_resume_decision(unit_id, row, unresolved)
        decisions.append(decision)
        if decision["action"] in RESUME_RERUN_ACTIONS:
            selected.append(unit_id)
            resumable.add(unit_id)
        elif decision["action"] == RESUME_HOLD_SUCCEEDED:
            # A succeeded unit is not re-dispatched and still clears the way
            # for its dependents: that pairing is the whole point of a resume.
            resumable.add(unit_id)
    return {
        "schema_version": FANOUT_RESUME_PLAN_SCHEMA_VERSION,
        "fanout_id": str(journal.get("fanout_id", "")),
        "resumed_from": {
            "journal_schema_version": str(journal.get("schema_version", "")),
            "observed_at": str(journal.get("observed_at", "")),
            "interrupted": bool(journal.get("interrupted")),
        },
        "selected_units": selected,
        "held_units": [entry["unit_id"] for entry in decisions if entry["action"] in RESUME_HOLD_ACTIONS],
        "decisions": decisions,
        "claim_boundary": RESUME_CLAIM_BOUNDARY,
    }


def _unit_resume_decision(
    unit_id: str,
    row: Mapping[str, Any] | None,
    unresolved: Sequence[str],
) -> dict[str, Any]:
    if row is None:
        # In the contract, absent from the journal: the prior run never
        # reached it, so there is nothing to preserve and nothing to hold.
        return _decision(
            unit_id,
            prior_state=TERMINAL_NOT_ATTEMPTED,
            action=RESUME_RERUN_NOT_ATTEMPTED,
            reason="no prior journal entry: the unit was never recorded",
        )
    prior_state = str(row.get("terminal_state", ""))
    if prior_state == TERMINAL_SUCCEEDED:
        return _decision(
            unit_id,
            prior_state=prior_state,
            action=RESUME_HOLD_SUCCEEDED,
            reason="the prior run observed this unit's process succeed; a resume never re-runs it",
            row=row,
        )
    if prior_state == TERMINAL_DECLINED:
        # Checked ahead of replay-safety and `unresolved` on purpose: the
        # unit already answered this question, conclusively and negatively,
        # and a resume re-asking it would spend a whole agent-CLI run to
        # relearn what the journal already states -- regardless of whether
        # replaying it would also be safe, and regardless of whether its
        # blockers have since cleared.
        return _decision(
            unit_id,
            prior_state=prior_state,
            action=RESUME_HOLD_DECLINED,
            reason=(
                f"the unit reported a negative-conclusive outcome ({row.get('decline_reason') or 'unspecified'}): "
                "resuming does not re-dispatch it because a retry cannot answer the question differently; "
                "act on the recorded reason or supersede it by hand"
            ),
            row=row,
        )
    if not bool(row.get("replay_safe")):
        return _decision(
            unit_id,
            prior_state=prior_state,
            action=RESUME_HOLD_REPLAY_UNSAFE,
            reason=(
                f"replay refused ({row.get('replay_verdict') or 'unknown'}, "
                f"side effect: {row.get('side_effect') or 'unknown'}): re-dispatching rebuilds the "
                "worktree and destroys the work the failure left behind; continue it through the recovery record"
            ),
            row=row,
        )
    if unresolved:
        return _decision(
            unit_id,
            prior_state=prior_state,
            action=RESUME_HOLD_BLOCKED_DEPENDENCY,
            reason=(
                "held because "
                + ", ".join(unresolved)
                + " is not being re-dispatched, so this unit would only block again"
            ),
            row=row,
        )
    if row.get("awaiting_retry"):
        # Reached only after replay-safety and the blocker check have both
        # passed: "wait for the provider window" is a reason to re-attempt a
        # unit, never a licence to rebuild a worktree over work a failure left
        # behind. A deferred unit that IS replay-unsafe is held above, with the
        # side effect named, exactly like any other.
        return _decision(
            unit_id,
            prior_state=prior_state,
            action=RESUME_RERUN_AWAITING_RETRY,
            reason=(
                "the operator deferred this unit in the dispatch recovery interview after a "
                f"{row.get('awaiting_retry_kind') or row.get('failure_kind') or 'recoverable'} failure; "
                "this resume is the retry that was asked for"
            ),
            row=row,
        )
    if prior_state == TERMINAL_SKIPPED_BY_DEPENDENCY:
        return _decision(
            unit_id,
            prior_state=prior_state,
            action=RESUME_UNSKIP_DEPENDENT,
            reason="every unit it was blocked on is being attempted again, so it is no longer skipped",
            row=row,
        )
    if prior_state == TERMINAL_NOT_ATTEMPTED:
        return _decision(
            unit_id,
            prior_state=prior_state,
            action=RESUME_RERUN_NOT_ATTEMPTED,
            reason=f"never attempted in the prior run (status {row.get('status') or 'unknown'})",
            row=row,
        )
    if prior_state == TERMINAL_CANCELLED:
        # After the replay-safety and blocker gates above, which apply to a
        # cancelled unit exactly as they apply to a failed one: a unit killed
        # mid-write is held with its side effect named, not re-dispatched over
        # the work it left behind.
        return _decision(
            unit_id,
            prior_state=prior_state,
            action=RESUME_RERUN_CANCELLED,
            reason=(
                f"the prior run was stopped while this unit was in flight (status "
                f"{row.get('status') or 'unknown'}) with no observed side effect, so re-dispatching "
                "it destroys nothing"
            ),
            row=row,
        )
    return _decision(
        unit_id,
        prior_state=prior_state,
        action=RESUME_RERUN_FAILED,
        reason=(
            f"failed as {row.get('failure_class') or 'unclassified'} with no observed side effect, "
            "so re-dispatching it destroys nothing"
        ),
        row=row,
    )


def _decision(
    unit_id: str,
    *,
    prior_state: str,
    action: str,
    reason: str,
    row: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    decision: dict[str, Any] = {
        "unit_id": unit_id,
        "prior_state": prior_state,
        "action": action,
        "reason": reason,
    }
    if action in RESUME_HOLD_ACTIONS and row is not None:
        # A held unit is not dispatched, so the resumed run's own summary can
        # only record a skip for it. Its prior verdict rides along so the next
        # journal restates it instead of downgrading a refused replay to
        # "never attempted".
        decision["carry_forward"] = {key: row[key] for key in _JOURNAL_UNIT_KEYS if key in row}
    return decision


def _carried_forward(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    resume = entry.get("resume")
    if not isinstance(resume, Mapping):
        return None
    carried = resume.get("carry_forward")
    if not isinstance(carried, Mapping):
        return None
    if any(key not in carried for key in _JOURNAL_UNIT_KEYS):
        return None
    return {key: value for key, value in carried.items()}


def _terminal_state(entry: Mapping[str, Any]) -> str:
    if entry.get("status") in _SUCCEEDED_STATUSES or bool(entry.get("process_succeeded")):
        return TERMINAL_SUCCEEDED
    if entry.get("status") in {"blocked_by_dependency", "blocked_by_cancelled_dependency"}:
        return TERMINAL_SKIPPED_BY_DEPENDENCY
    if entry.get("status") in {"cancelled", "cancelled_outcome_unknown"}:
        return TERMINAL_CANCELLED
    if "exit_code" not in entry and entry.get("status") in _NEVER_SPAWNED_STATUSES:
        return TERMINAL_NOT_ATTEMPTED
    if _unit_result_declined(entry):
        return TERMINAL_DECLINED
    return TERMINAL_FAILED


def _unit_result_declined(entry: Mapping[str, Any]) -> bool:
    """Whether the dispatcher's own observation validated a decline.

    Gated on `result_schema_valid`, the dispatcher's own record that it
    validated the sidecar's shape -- not on the executor's claim alone, the
    same rule `fanout_unit_results` states for every field on this contract.
    A unit that succeeded is caught by the earlier `TERMINAL_SUCCEEDED` branch
    regardless of what a stray `process_declined` sidecar might claim: the
    dispatcher's own exit-code observation always outranks a self-report.
    """
    if not bool(entry.get("result_schema_valid")):
        return False
    unit_result = entry.get("unit_result")
    if not isinstance(unit_result, Mapping):
        return False
    return str(unit_result.get("process_status", "")) == "process_declined"


def _decline_reason(entry: Mapping[str, Any]) -> str:
    unit_result = entry.get("unit_result")
    if isinstance(unit_result, Mapping):
        return str(unit_result.get("decline_reason", ""))
    return ""


def _failure_classification(entry: Mapping[str, Any], *, state: str = "") -> dict[str, str]:
    """The failure class in `fanout_retry`'s vocabulary, read not re-derived.

    The dispatcher already classified any failure it considered retrying, from
    the output tails it had in hand; the summary does not keep those tails, so
    re-matching here would be guessing. Only a failure the retry ladder never
    saw falls back to the exit-code-only classification.

    A cancelled unit skips both as well, with an empty class: nothing failed.

    A declined unit skips both: its class is the journal's own
    `FAILURE_CLASS_DECLINED_CONCLUSIVE`, never `fanout_retry`'s
    `terminal_failure`, because the retry ladder never asked "is this
    conclusive" -- only "is this the unit's own answer", which is true of
    every non-transient failure and would erase the distinction this module
    exists to keep.
    """
    if state == TERMINAL_DECLINED:
        return {"failure_class": FAILURE_CLASS_DECLINED_CONCLUSIVE, "failure_label": ""}
    if state == TERMINAL_CANCELLED:
        # A cancelled unit observed no failure. Classifying its signal exit code
        # would attribute a fault to work that was never allowed to reach a
        # verdict, and the recovery interview reads this field.
        return {"failure_class": "", "failure_label": ""}
    retry = entry.get("retry")
    if isinstance(retry, Mapping):
        decisions = retry.get("decisions")
        if isinstance(decisions, list) and decisions and isinstance(decisions[-1], Mapping):
            final = decisions[-1]
            return {
                "failure_class": str(final.get("failure_class", "")),
                "failure_label": str(final.get("failure_label", "")),
            }
    exit_code = entry.get("exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool) or exit_code == 0:
        return {"failure_class": "", "failure_label": ""}
    verdict = classify_unit_failure(
        exit_code=exit_code,
        output_tail="",
        stderr_tail="",
        limit_shaped=str(entry.get("limit_pattern", "")),
    )
    return {
        "failure_class": str(verdict["failure_class"]),
        "failure_label": str(verdict["failure_label"]),
    }


def _entry_replay_safety(entry: Mapping[str, Any], *, succeeded: bool) -> dict[str, Any]:
    """Whether a resume may re-dispatch this unit, from what was observed.

    The recovery-probe predicate is reused unchanged for a unit that ran and
    failed. Two cases it does not model, because an in-flight retry only ever
    asks about a spawn that just failed:

    * A unit that never spawned. No process means no side effect, and the
      absent exit code is the observation that says so.
    * A unit that succeeded. Its work IS the side effect, and no recovery
      probe was ever run against it because nothing failed -- reading that
      absence as "unmeasured" would file the strongest possible reason not to
      replay under the vocabulary for "I could not tell".
    """
    if succeeded:
        return {
            "replay_safe": False,
            "replay_verdict": REPLAY_UNSAFE_SIDE_EFFECTS,
            "side_effect": "succeeded_unit_work",
        }
    if "exit_code" not in entry:
        return {"replay_safe": True, "replay_verdict": REPLAY_SAFE, "side_effect": "no_spawn_observed"}
    return replay_safety(entry.get("recovery"), artifact_observed="unit_result" in entry)


def resume_counts(decisions: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """How many units each resume action covers, for the summary rollup."""
    counts: dict[str, int] = {}
    for decision in decisions:
        action = str(decision.get("action", ""))
        counts[action] = counts.get(action, 0) + 1
    return dict(sorted(counts.items()))
