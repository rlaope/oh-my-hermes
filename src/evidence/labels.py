"""Human-readable labels for OMH's evidence vocabulary.

The wire values (``prepared_not_observed``, ``observed_partial``,
``worktree_failed``, …) are a contract: external wrappers gate on them and ~169
test assertions pin them. Nothing here changes a value. This module owns the
separate question of what a PERSON reads when one of those values reaches a
screen, and it is the only place those words are written down.

Two axes, because the wire values weld two different questions into one token
and that is why they are unreadable:

* **Phase** -- what stage the work is at: ``Route``, ``Plan``, ``Code``,
  ``Setup``, ``Test``, ``Review``, ``Ship``.
* **Confidence** -- what OMH actually knows: ``not run``, ``running``,
  ``partly seen``, ``reported done``, ``seen``, ``failed``, ``verified``.

Rendered as ``Plan · not run``, ``Code · running``, ``Test · verified``.

Why not one friendly word per value. Collapsing the axes is the failure this
whole vocabulary exists to prevent: ``Code`` alone cannot say whether OMH
watched an executor run or only wrote a prompt for one, and ``prepared_not_observed``
is overwhelmingly the second. The phase axis is deliberately incapable of
asserting activity -- every label on it is a noun, never a gerund, because
"Coding" reads as *someone is coding right now* on a fast scan and "Code" does
not.

Why the phase words are nouns and why ``ready`` is not among them:
``operator_productivity.OBSERVED_CLAIM_STATUSES`` lists ``ready`` beside
``complete``, ``passed``, and ``merged``, and
``_nested_observed_claim_errors`` rejects any payload whose ``status`` field
carries one. A label reading ``ready`` would be refused by OMH's own guard as
an unbacked observation claim. It survives only as the long-form prose
``ready to run``, which is future tense and cannot be read as an achievement.
"""

from __future__ import annotations

from typing import Final

EVIDENCE_LABELS_SCHEMA_VERSION: Final[str] = "omh_evidence_labels/v1"

# Orthogonal skill-load probe labels. These describe protocol capability and
# inventory comparison; they never inherit routing or child-success wording.
SKILL_LOAD_PROBE_LABELS: Final[dict[str, str]] = {
    "observed": "machine inventory observed",
    "unsupported": "machine inventory unsupported",
    "probe_error": "machine inventory probe failed",
}
SKILL_LOAD_STATE_LABELS: Final[dict[str, str]] = {
    "all_loaded": "all expected skills loaded",
    "partially_loaded": "some expected skills missing",
    "none_loaded": "no expected skills loaded",
    "not_applicable": "no skills expected",
}

# The separator between the two axes. U+00B7 rather than an em dash because the
# status board already joins its own fields with " — "; an em dash here would
# make a six-field row read as seven. Already shipping elsewhere in this repo
# under enforcing Windows CI, so the encoding is proven.
SEPARATOR: Final[str] = " · "

# --- Phase axis -------------------------------------------------------------

PHASE_ROUTE: Final[str] = "Route"
PHASE_PLAN: Final[str] = "Plan"
PHASE_CODE: Final[str] = "Code"
PHASE_SETUP: Final[str] = "Setup"
PHASE_TEST: Final[str] = "Test"
PHASE_REVIEW: Final[str] = "Review"
PHASE_SHIP: Final[str] = "Ship"

PHASES: Final[tuple[str, ...]] = (
    PHASE_ROUTE,
    PHASE_PLAN,
    PHASE_CODE,
    PHASE_SETUP,
    PHASE_TEST,
    PHASE_REVIEW,
    PHASE_SHIP,
)

# --- Confidence axis --------------------------------------------------------

# The load-bearing label. Three properties, each chosen against a failure:
# the negation sits in the first three characters so every truncation budget in
# the repo preserves it; it is a past-tense negative, so unlike "prepared" or
# "ready" it cannot be read as an achievement; and at 7 characters against the
# 21 of `prepared_not_observed` it loosens every width budget rather than
# tightening one.
CONFIDENCE_NOT_RUN: Final[str] = "not run"
CONFIDENCE_RUNNING: Final[str] = "running"
CONFIDENCE_PARTLY_SEEN: Final[str] = "partly seen"
# Names the claimant inside the label. `completed` is the EXECUTOR'S OWN report
# about itself; OMH observed the claim, never the result. Without this a
# self-reported unit and a gate-checked unit render identically.
CONFIDENCE_REPORTED_DONE: Final[str] = "reported done"
CONFIDENCE_SEEN: Final[str] = "seen"
CONFIDENCE_FAILED: Final[str] = "failed"
CONFIDENCE_VERIFIED: Final[str] = "verified"
# Neither a success nor a failure: something is in the way, or someone stopped
# it. Kept distinct from `failed` because the action a reader should take is
# different, and distinct from `not run` because a blocker IS an observation.
CONFIDENCE_BLOCKED: Final[str] = "blocked"
CONFIDENCE_CANCELLED: Final[str] = "cancelled"

CONFIDENCES: Final[tuple[str, ...]] = (
    CONFIDENCE_NOT_RUN,
    CONFIDENCE_RUNNING,
    CONFIDENCE_PARTLY_SEEN,
    CONFIDENCE_REPORTED_DONE,
    CONFIDENCE_SEEN,
    CONFIDENCE_FAILED,
    CONFIDENCE_VERIFIED,
    CONFIDENCE_BLOCKED,
    CONFIDENCE_CANCELLED,
)

# Long form for prose, where a sentence has room and a bare "not run" reads
# clipped. This is the only place the owner's word `ready` appears, and only as
# a future-tense phrase that cannot be mistaken for a past achievement.
CONFIDENCE_PROSE: Final[dict[str, str]] = {
    CONFIDENCE_NOT_RUN: "ready to run, nothing has run yet",
    CONFIDENCE_RUNNING: "running now",
    CONFIDENCE_PARTLY_SEEN: "seen partway through",
    CONFIDENCE_REPORTED_DONE: "the executor reported it done; the result was not checked",
    CONFIDENCE_SEEN: "seen finishing; the result was not checked",
    CONFIDENCE_FAILED: "failed",
    CONFIDENCE_VERIFIED: "checked and passed",
    CONFIDENCE_BLOCKED: "blocked; something is in the way",
    CONFIDENCE_CANCELLED: "cancelled before it finished",
}

# --- Wire value -> confidence ----------------------------------------------

# Total on the values this repo emits. Anything absent fails CLOSED to
# `not run`, mirroring `status_board.normalize_status`: an unrecognized state
# must never render as work that happened.
_CONFIDENCE_BY_VALUE: Final[dict[str, str]] = {
    # `_usage_evidence_state` in src/wrapper/contract.py
    "routing_not_execution": CONFIDENCE_NOT_RUN,
    "prepared_not_observed": CONFIDENCE_NOT_RUN,
    "observed_partial": CONFIDENCE_PARTLY_SEEN,
    "observed_reportable": CONFIDENCE_SEEN,
    # `STATUS_VOCABULARY` in src/coding/status_board.py
    "running": CONFIDENCE_RUNNING,
    "completed": CONFIDENCE_REPORTED_DONE,
    "failed": CONFIDENCE_FAILED,
    "worktree_failed": CONFIDENCE_FAILED,
    # `REPORT_STATUSES` in src/coding/work_reporting.py
    "in_progress": CONFIDENCE_RUNNING,
    "blocked": CONFIDENCE_BLOCKED,
    "cancelled": CONFIDENCE_CANCELLED,
    # `_SUMMARY_STATUS_LABELS` in src/commands/chat.py, retired in favour of
    # this map. `unknown` and `pending` fail closed on purpose: neither is a
    # claim that anything happened.
    "not_observed": CONFIDENCE_NOT_RUN,
    "observed": CONFIDENCE_SEEN,
    "passed": CONFIDENCE_VERIFIED,
    "pending": CONFIDENCE_NOT_RUN,
    "unknown": CONFIDENCE_NOT_RUN,
}

# A phase the value implies on its own, used when a caller names none.
# `worktree_failed` is the clean case: it was always a phase plus an outcome
# welded together, so it decomposes with nothing left over.
_PHASE_BY_VALUE: Final[dict[str, str]] = {
    "routing_not_execution": PHASE_ROUTE,
    "prepared_not_observed": PHASE_PLAN,
    "worktree_failed": PHASE_SETUP,
}

# `next_action` values that name a stage more precisely than the evidence value
# can. Read from `usage_trace`, which already carries both axes side by side.
_PHASE_BY_NEXT_ACTION: Final[dict[str, str]] = {
    "record_verification_evidence": PHASE_TEST,
    "record_ci_evidence": PHASE_TEST,
    "record_review_evidence": PHASE_REVIEW,
    "report_merge_ready": PHASE_SHIP,
    "report_merged": PHASE_SHIP,
    "dispatch_to_workflow": PHASE_ROUTE,
    "present_plan": PHASE_PLAN,
    "accept_or_revise_plan": PHASE_PLAN,
    "wait_for_executor_evidence": PHASE_CODE,
    "report_completion_with_evidence": PHASE_CODE,
    "surface_executor_cancellation": PHASE_CODE,
}


def confidence_label(value: str) -> str:
    """What OMH knows about ``value``, fail-closed to ``not run``."""
    return _CONFIDENCE_BY_VALUE.get(str(value or "").strip(), CONFIDENCE_NOT_RUN)


def phase_label(value: str = "", *, next_action: str = "", default: str = "") -> str:
    """The stage to show beside the confidence, or "" when none is known.

    Precedence is most-specific-first: an explicit ``next_action`` names a stage
    the evidence value cannot (a value of ``observed_partial`` is equally true
    of a test run and a review), then the value's own implied phase, then the
    caller's surface default -- a coding board knows every row is ``Code`` even
    when the value does not say so.
    """
    from_action = _PHASE_BY_NEXT_ACTION.get(str(next_action or "").strip())
    if from_action:
        return from_action
    implied = _PHASE_BY_VALUE.get(str(value or "").strip())
    if implied:
        return implied
    return default if default in PHASES else ""


def status_label(value: str, *, next_action: str = "", default_phase: str = "") -> str:
    """``Plan · not run`` -- the one string a human reads for ``value``.

    Never returns "" and never returns the bare word ``unknown``: the message
    gate raises ``message_gate_missing_status`` on exactly that value, and an
    unrecognized state is a state that did not run, not a state we have no
    opinion about.
    """
    confidence = confidence_label(value)
    phase = phase_label(value, next_action=next_action, default=default_phase)
    return f"{phase}{SEPARATOR}{confidence}" if phase else confidence


def status_prose(value: str, *, next_action: str = "", default_phase: str = "") -> str:
    """The sentence form, for docs and for copy with room to breathe."""
    confidence = confidence_label(value)
    phase = phase_label(value, next_action=next_action, default=default_phase)
    long_form = CONFIDENCE_PROSE[confidence]
    return f"{phase.lower()}: {long_form}" if phase else long_form
