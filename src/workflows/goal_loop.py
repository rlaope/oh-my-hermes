from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Iterable, Mapping

from ..coding.executor_auth_signals import (
    AUTH_SIGNAL_PROFILES,
    auth_signal_for_profile,
    last_limit_signal_for_profile,
)
from ..codex_progress import summarize_codex_jsonl_text
from ..goal_ledger import build_goal_completion_gate, read_goal_ledger
from ..hashutil import sha256_text
from ..local_store import ensure_dir, read_json_object, utc_now
from ..system.record_revision import DuplicateMutationReplay, guarded_record_update, revision_field_errors
from ..loopability import LOOPABILITY_ASSESSMENT_SCHEMA, assess_loopability, validate_loopability_assessment
from ..paths import OmhPaths
from ..system.security_posture import resolve_security_posture, strict_override
from .goal_quality_coaching import UPSTREAM_GOAL_DEFAULT_MAX_TURNS
from .loop_phase_transitions import (
    LOOP_GOAL_DRIVER_OBSERVATION_SCHEMA,
    LOOP_PHASES,
    native_goal_status,
    parse_loop_goal_driver_observation,
    phase_target,
    set_loop_phase,
    transition_loop_phase,
    validate_loop_phase_history,
)


LOOP_CYCLE_SCHEMA = "loop_cycle/v1"
LOOP_STATUS_CARD_SCHEMA = "loop_status_card/v1"
LOOP_RUNTIME_SCHEMA = "loop_runtime/v1"
LOOP_QUEUE_ITEM_SCHEMA = "loop_queue_item/v1"
LOOP_START_CARD_SCHEMA = "loop_start_card/v1"
LOOP_QUEUE_LIST_SCHEMA = "loop_queue_list/v1"
LOOP_QUEUE_HANDOFF_SCHEMA = "loop_queue_handoff/v1"
LOOP_GOAL_DRIVER_HANDOFF_SCHEMA = "loop_goal_driver_handoff/v1"
LOOP_ENGINEERING_SCHEMA = "loop_engineering/v1"
LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA = "loop_subagent_result_contract/v1"
LOOP_VERIFICATION_PLAN_SCHEMA = "loop_verification_plan/v1"
LOOP_FAILURE_MODE_SUMMARY_SCHEMA = "loop_failure_mode_summary/v1"
LOOP_SMALL_LOOP_GUIDANCE_SCHEMA = "loop_small_loop_guidance/v1"
LOOP_RUN_ONCE_RESULT_SCHEMA = "loop_run_once_result/v1"
EXECUTOR_LOOP_CAPABILITY_SCHEMA = "executor_loop_capability/v1"
LOOP_CYCLE_NARRATION_SCHEMA = "loop_cycle_narration/v1"
LOOP_DISPATCH_ATTEMPT_SCHEMA = "loop_dispatch_attempt/v1"
LOOP_INVOCATION_SCHEMA = "loop_invocation/v1"
LOOP_CONSTRAINT_ASSESSMENT_SCHEMA = "loop_constraint_assessment/v1"
LOOP_STICKY_RULE_SCHEMA = "loop_sticky_rule/v1"
LOOP_STICKY_RULE_ATTACHMENT_SCHEMA = "loop_sticky_rule_attachment/v1"
LOOP_STOP_LADDER_SCHEMA = "loop_stop_ladder/v1"
LOOP_DISPATCH_RECOVERY_OUTCOMES = ("delivery_failed", "delivery_unknown")

# The ordered stop ladder evaluated before a tick advances. The tuple order IS
# the ladder: assess_loop_stop_ladder walks it top to bottom, the first rung
# that fires stops the tick, and every rung below it is recorded
# `not_evaluated` rather than `clear` - a lower rung that was never consulted
# must never read as a rung that passed. Per-rung rationale:
# - Rung 1, explicit_cancel: a human already said stop, OR the linked goal
#   reached its own negative-conclusive verdict (`fail_goal_ledger`: the
#   target does not exist, the request is refused by policy, the criteria
#   are infeasible as specified). Both share the rung because both leave a
#   goal ledger that refuses every checkpoint, blocker, and gate
#   (`GOAL_TERMINAL_STATUSES` covers `cancelled` and `failed` alike), so any
#   work the loop prepared under either is unrecordable by construction --
#   the `detail` text still names which of the two actually fired. Nothing
#   below this rung can outrank either kind of terminal verdict.
# - Rung 2, rate_limit_signal: an observed limit-shaped dispatch failure for
#   the active executor profile. Above auth because a rate limit is the
#   cheaper, more common, and self-clearing of the two, and because a loop
#   that keeps iterating into a limit window is the single most expensive
#   failure mode a persistence loop has.
# - Rung 3, auth_failure_signal: no local login marker for the executor
#   profile this tick is about to hand work to. Gated on the planned action
#   being executor_dispatch on purpose - `executor_auth_signals` states that
#   markers rank candidates and never veto one, because an API-key or
#   environment-token install legitimately reads `absent`. This rung does not
#   veto a candidate: it stops the loop at the one moment its own next act is
#   to hand work to a CLI for which omh can see no login at all.
# - Rung 4, no_progress_cap: the loop is running but nothing is being written
#   down. Last because it is the only rung whose evidence is the loop's own
#   history rather than an external signal, so it must not pre-empt a stop
#   whose cause is already known and named.
LOOP_STOP_REASONS: Final[tuple[str, ...]] = (
    "explicit_cancel",
    "rate_limit_signal",
    "auth_failure_signal",
    "no_progress_cap",
)
LOOP_STOP_RUNG_STATES: Final[tuple[str, ...]] = ("clear", "fired", "not_applicable", "not_evaluated")
# Two consecutive ticks that write no new goal-ledger record. Keyed to records
# written rather than ticks attempted: attempts are what a stuck loop produces
# in abundance, so counting them measures the symptom instead of the progress.
LOOP_NO_PROGRESS_TICK_CAP: Final[int] = 2
LOOP_STOP_LADDER_CLAIM_BOUNDARY: Final[str] = (
    "A stop-ladder verdict is local policy over already-recorded signals. A stop is a stop with a "
    "named reason - it is not a completion, a failure verdict on the goal, provider quota truth, or "
    "evidence that any provider rejected a request."
)
_LOOP_STOP_NEXT_ACTIONS: Final[dict[str, str]] = {
    "explicit_cancel": "show_loop_status",
    "rate_limit_signal": "wait_for_executor_limit_reset",
    "auth_failure_signal": "confirm_executor_login_or_retarget",
    "no_progress_cap": "record_goal_blocker_for_stuck_loop",
}
_LOOP_STOP_EVIDENCE_SOURCES: Final[dict[str, str]] = {
    "explicit_cancel": "goal_ledger.status",
    "rate_limit_signal": "executor_auth_signals.last_limit_signal_for_profile",
    "auth_failure_signal": "executor_auth_signals.auth_signal_for_profile",
    "no_progress_cap": "runtime.no_progress_ticks",
}

_INNER_TIER_EXPECTED_SIGNAL = (
    "Cheap focused evidence such as syntax, compile, schema validation, command smoke, "
    "or targeted test output returns pass/fail."
)
_GOAL_DRIVER_LINE_LIMIT = 360

WAIT_REASONS = {
    "none",
    "waiting_external_observation",
    "permission_required",
    "context_exhausted",
    "budget_exhausted",
}
PERMISSION_PROFILES = ("observe_only", "handoff_only", "execute_with_gates", "full_loop", "custom")
LOOP_ACTIONS = (
    "research",
    "planning",
    "ultragoal_creation",
    "executor_handoff",
    "executor_dispatch",
    "repo_edit",
    "pr_creation",
    "pr_revision",
    "review_fix_loop",
    "ci_fix_loop",
    "release_note_work",
    "external_posting_prep",
    "external_posting",
    "merge",
)
LOOP_CONTROL_ACTIONS = (
    "request_permission",
    "wait_for_external_observation",
    "checkpoint_resume",
    "show_loop_status",
)
LOOP_QUEUE_STATUSES = (
    "prepared_not_observed",
    "blocked_by_permission",
    "blocked_by_wait",
    "blocked",
    "observed",
)
# Constraint classes for the loop_constraint_assessment/v1 block. The tuple
# order IS the rank: assess_loop_constraint walks it in order, there is no
# sort step and no priority integer, so re-ranking is a tuple reorder.
# Per-rank rationale:
# - Rank 1, capacity_exhausted: the only class where no loop action succeeds.
#   Context or budget exhaustion ends the current turn; anything below it is
#   unreachable until a checkpoint exists.
# - Rank 2, permission_envelope: the second hard stop. The loop can still
#   think, but every mutating action is refused. Below capacity because a
#   checkpoint is possible under a closed envelope; a permission request is
#   not possible in an exhausted context.
# - Rank 3, goal_status_gap: a hard stop on conversion, not on activity.
#   Under blocked, failed, or cancelled the loop can still produce work, but
#   none of it becomes goal progress; a cancelled goal is terminal enough
#   that the completion gate itself overrides next_action to show_status.
#   Placed below the two loop-level hard stops and above every queue rank,
#   because filling a queue against a dead goal is the most expensive form
#   of the mistake this assessment exists to prevent.
# - Rank 4, blocked_queue_item: first of the two backlog ranks, deliberately
#   above observation_backlog. A blocked item has already stopped moving and
#   cannot be converted by any amount of the capacity the loop currently
#   holds; an unobserved item can. Naming the observable pile while blocked
#   items sit unaddressed works the wrong end of the queue and lets the
#   block quietly accumulate more work behind it.
# - Rank 5, observation_backlog: the largest pile of prepared_not_observed
#   work - the one thing the loop can convert into observed evidence with
#   capacity it already holds. This is the rank the assessment exists to
#   surface, and it stays above external_wait because prepared work is the
#   loop's own to finish.
# - Rank 6, external_wait: waiting is real, but it is not a reason to leave
#   prepared work unobserved. This is the deliberate divergence from
#   _next_action's ordering, which tests waiting_external_observation FIRST;
#   the assessment tests capacity, permission, and the queue ranks first, so
#   a card can record next_action == "record_external_wait" while the
#   assessment names observation_backlog as binding. Both are right; see
#   LOOP_CONSTRAINT_NEXT_ACTION_RELATIONSHIP.
# - Rank 7, verification_gap: the safety consequence of rank 5 rather than
#   an independent handle. _verification_gap_mode warns whenever a
#   prepared_not_observed item exists - the same predicate as
#   pending_queue_count > 0 - so ranks 5 and 7 co-fire by construction and
#   are emitted, not deduped: rank 5 names the actionable handle, rank 7
#   names the safety consequence.
# - Ranks 8-10, the ledger ranks: unsatisfied_required_criterion, then
#   active_blocker, then unsatisfied_runtime_check. All three describe what
#   the goal still needs, and none of them stops the loop from working; they
#   stop it from claiming completion. Ordered among themselves by how
#   directly the loop can act: a criterion is worked, a blocker is
#   escalated, a runtime check waits on someone else's recorded run.
# - Ranks 11-12, the soft safety signals: comprehension_debt and
#   human_judgment. Warnings about how the loop is working, not about what
#   is gating it. They sit last among firing classes precisely because a
#   loop can make real progress while carrying them, and promoting them
#   would let a style warning outrank a dead goal.
# - Rank 13, goal_link_missing: last, and structurally exclusive - when it
#   fires, ranks 3 and 8-10 cannot fire at all, because the unlinked
#   fallback block carries none of their keys. It is a setup gap, not a
#   work gap.
LOOP_CONSTRAINT_CLASSES: Final[tuple[str, ...]] = (
    "capacity_exhausted",
    "permission_envelope",
    "goal_status_gap",
    "blocked_queue_item",
    "observation_backlog",
    "external_wait",
    "verification_gap",
    "unsatisfied_required_criterion",
    "active_blocker",
    "unsatisfied_runtime_check",
    "comprehension_debt",
    "human_judgment",
    "goal_link_missing",
)
LOOP_CONSTRAINT_NEXT_ACTION_RELATIONSHIP: Final[str] = (
    "The constraint assessment explains why the loop is gated; the card's own next_action stays the "
    "recorded directive. When the two differ, the binding constraint names what to fix and next_action "
    "names the recorded step."
)
LOOP_CONSTRAINT_ASSESSMENT_CLAIM_BOUNDARY: Final[str] = (
    "A constraint assessment is prepared analysis derived from recorded loop state. It is not observed "
    "evidence, it selects no route and dispatches nothing, and it is not execution, review, CI, merge, "
    "or goal completion evidence."
)
LOOP_CONSTRAINT_REPEAT_NOTE: Final[str] = (
    "Re-identify the constraint at the next iteration boundary; resolving one constraint surfaces the next."
)
# Derived, never hand-written: a hand-written all-clear sentence can drift
# from the tuple and assert a check that never ran. Deriving it means adding
# a class automatically widens the claim.
_NO_BINDING_CONSTRAINT_REASON: Final[str] = (
    "No recorded loop state matches any constraint class: "
    + ", ".join(f"`{name}`" for name in LOOP_CONSTRAINT_CLASSES)
    + "."
)
# Authored guidance per constraint class. A class with no entry is a KeyError
# at import-adjacent test time, not a silent blank, so the closed tuple and
# the guidance cannot drift apart.
_LOOP_CONSTRAINT_GUIDANCE: Final[dict[str, dict[str, str]]] = {
    "capacity_exhausted": {
        "exploit": (
            "Record a checkpoint capturing what is already prepared, so the next context resumes from "
            "recorded state instead of re-deriving it."
        ),
        "subordinate": "Stop queueing new work and stop widening scope until that checkpoint exists.",
        "elevate": (
            "Ask the operator for a fresh context or a larger budget only after the checkpoint is recorded; "
            "it costs a restart, so it is the last step, not the first."
        ),
    },
    "permission_envelope": {
        "exploit": (
            "Finish everything the current envelope already allows, so the approval request arrives with "
            "the prepared work behind it."
        ),
        "subordinate": "Stop preparing work whose only remaining step is a blocked action.",
        "elevate": (
            "Ask the operator to widen the permission profile, naming each blocked action and why it is needed."
        ),
    },
    "goal_status_gap": {
        "exploit": (
            "Record the evidence the loop has already observed against the goal, so none of it is lost "
            "when the status changes."
        ),
        "subordinate": "Stop opening new loop work against this goal while its status is not active.",
        "elevate": (
            "Ask the operator to reopen, re-scope, or replace the goal; a cancelled goal refuses mutation, "
            "so no loop-side action clears this."
        ),
    },
    "blocked_queue_item": {
        "exploit": (
            "Record what each blocked item is waiting on, on the item itself, so the block is addressable "
            "instead of implicit."
        ),
        "subordinate": "Stop adding queue items that would land behind the same block.",
        "elevate": (
            "Escalate the block to whoever owns it - a permission, an external party, or a prerequisite "
            "goal - naming the item ids."
        ),
    },
    "observation_backlog": {
        "exploit": (
            "Observe the oldest prepared item and record its evidence before preparing anything else; "
            "this converts work the loop has already paid for."
        ),
        "subordinate": "Stop preparing new queue items until the prepared pile shrinks.",
        "elevate": (
            "Add observation capacity - a second reviewer, a longer session - only after the existing "
            "prepared items have been worked down."
        ),
    },
    "external_wait": {
        "exploit": (
            "Record exactly which observation is awaited and from whom, so the wait is auditable instead "
            "of open-ended."
        ),
        "subordinate": (
            "Stop treating the wait as work, and never narrate the awaited result as though it had arrived."
        ),
        "elevate": (
            "Ask the operator to chase the external party, or to re-scope the loop goal so it no longer "
            "depends on this observation."
        ),
    },
    "verification_gap": {
        "exploit": "Run the cheapest inner-tier check that would close this gap and record its output.",
        "subordinate": "Stop reporting progress that rests on prepared-but-unverified work.",
        "elevate": (
            "Add an outer-tier check or a verifier lane only when the inner-tier checks cannot reach the gap."
        ),
    },
    "unsatisfied_required_criterion": {
        "exploit": (
            "Do the smallest piece of work that produces evidence for this one criterion, and attach the "
            "evidence reference to it."
        ),
        "subordinate": (
            "Stop working criteria that are already satisfied, and stop claiming completion while this "
            "one is open."
        ),
        "elevate": (
            "Ask the operator to re-scope or drop the criterion, only when the evidence genuinely cannot "
            "be produced."
        ),
    },
    "active_blocker": {
        "exploit": (
            "Record what would clear this blocker and who can clear it, so it stops being a static ledger entry."
        ),
        "subordinate": "Stop opening work that depends on this blocker clearing.",
        "elevate": (
            "Escalate to the blocker's owner, or record an explicit decision to accept it and re-scope the goal."
        ),
    },
    "unsatisfied_runtime_check": {
        "exploit": (
            "Record the runtime evidence the check is missing for the named run, from observed output "
            "rather than a prepared handoff."
        ),
        "subordinate": "Stop treating the linked run as complete while its check is unsatisfied.",
        "elevate": "Re-run or replace the linked runtime run, only when its evidence cannot be recovered.",
    },
    "comprehension_debt": {
        "exploit": (
            "Read the recorded state the loop is acting on until the next action is explainable without guessing."
        ),
        "subordinate": "Stop dispatching work whose purpose cannot be stated from recorded state.",
        "elevate": (
            "Ask for a walkthrough from whoever holds the context, naming what specifically is not understood."
        ),
    },
    "human_judgment": {
        "exploit": (
            "State the decision the loop is about to make and the alternative it is discarding, and record both."
        ),
        "subordinate": "Stop letting the loop's own momentum stand in for a decision.",
        "elevate": "Hand the decision to the operator with the options and their costs named.",
    },
    "goal_link_missing": {
        "exploit": (
            "Work only what the loop's own recorded state can justify while no goal ledger is linked."
        ),
        "subordinate": (
            "Stop making completion claims; with no linked ledger there is no completion gate to satisfy."
        ),
        "elevate": (
            "Link or create a `goal_ledger/v1` goal so acceptance criteria, blockers, and runtime checks "
            "become recorded state."
        ),
    },
}
# Sticky-rule re-attachment: a standing rule (e.g. "never claim completion
# without observed evidence") that must stay in an executor's attention
# across a long loop without becoming payload bloat. Modeled on oh-my-pi's
# TTSR repeat policy (docs/ttsr-injection-lifecycle.md): a rule is declared
# once with a bounded repeat policy, and the loop re-attaches it at tick
# boundaries under that policy rather than every tick or never again.
#
# - "once": attach the rule exactly one time, at the first tick after it is
#   declared. `repeat_gap` is not consulted in this mode.
# - "after_gap": attach the rule again once `heartbeat_count -
#   last_injected_heartbeat >= repeat_gap` completed ticks have passed since
#   its last attachment. The gap is measured in `runtime.heartbeat_count`
#   (completed loop ticks), never in reads of the status card - a card can be
#   read any number of times between ticks without moving the gap, matching
#   the oh-my-pi contract that re-attachment is gated on completed turns, not
#   stream chunks.
#
# Every mode is bounded by `max_repeats`, so a long-running loop can never
# accumulate unbounded repeats of the same reminder; `injected_count >=
# max_repeats` retires the rule from further attachment regardless of mode
# or gap. Rules are deduplicated by `rule_id`: declaring an existing id again
# updates its text and policy in place rather than creating a second entry.
LOOP_STICKY_RULE_REPEAT_MODES: Final[tuple[str, ...]] = ("once", "after_gap")
LOOP_STICKY_RULE_DEFAULT_GAP: Final[int] = 10
LOOP_STICKY_RULE_DEFAULT_MAX_REPEATS: Final[int] = 5
LOOP_STICKY_RULE_ONCE_MAX_REPEATS: Final[int] = 1
LOOP_STICKY_RULE_MAX_REPEATS_CEILING: Final[int] = 100
LOOP_STICKY_RULE_CLAIM_BOUNDARY: Final[str] = (
    "A sticky-rule attachment restates an already-declared rule at a bounded interval. It is not new "
    "guidance, it decides no route, and it is not execution, review, CI, merge, or goal completion evidence."
)
LOOP_PIPELINE_STEPS = (
    "task_discovery",
    "distribution",
    "execution",
    "verification",
    "next_task_decision",
)
LOOP_BUILDING_BLOCKS = (
    "automation",
    "worktree",
    "skill",
    "connector",
    "subagent",
)
LOOP_WORKFLOW_PATTERNS = (
    "single_step",
    "fan_out_synthesize",
    "adversarial_verification",
    "tournament",
    "triage_batch",
)
LOOP_VERIFICATION_TIERS = ("none", "inner", "outer")
LOOP_CONTEXT_POLICY_REF = "loop_engineering.context_policy"
LOOP_COST_POLICY_REF = "loop_engineering.cost_policy"
LOOP_EXECUTOR_OPTIONS = (
    {"id": "choose", "label": "Ask me each time", "dispatchable_by_default": False},
    {"id": "codex", "label": "Codex", "dispatchable_by_default": True},
    {"id": "claude-code", "label": "Claude Code", "dispatchable_by_default": False},
    {"id": "generic", "label": "Other coding agent", "dispatchable_by_default": False},
    {"id": "omx-runtime", "label": "Oh-my runtime", "dispatchable_by_default": False},
    {"id": "hermes", "label": "Hermes", "dispatchable_by_default": False},
)
LOOP_EXECUTOR_OPTION_IDS = tuple(str(option["id"]) for option in LOOP_EXECUTOR_OPTIONS)
STORAGE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
LOOP_COMMAND_RE = re.compile(r"^(?:\./|/|\$)?loop(?:\s|$)")
OMH_LOOP_COMMAND_RE = re.compile(r"^omh\s+(?:loop|루프)(?:\s|$)")

LOOP_CORE_ROLES = (
    {
        "id": "interviewer",
        "skill": "deep-interview",
        "responsibility": "Resolve only decision-changing ambiguity; do not stop when repo, source, or loop context can answer.",
    },
    {
        "id": "planner",
        "skill": "ralplan",
        "responsibility": "Turn the current loop goal into a reviewed plan with risks, alternatives, acceptance criteria, and verification.",
    },
    {
        "id": "researcher",
        "skill": "research",
        "adjacent_skills": ["source-finder", "best-practice-research"],
        "responsibility": "Gather current source, web, or repo evidence before planning or handoff when facts are missing.",
    },
    {
        "id": "builder",
        "skill": "ultrawork",
        "responsibility": "Prepare the concrete goal, coordinated lanes, or executor handoff for implementation without claiming execution.",
    },
    {
        "id": "reviewer",
        "skill": "code-review",
        "adjacent_skills": ["ultraqa", "agent-ops-review"],
        "responsibility": "Gate observed work with review, QA, verification, CI, and failure-mode checks.",
    },
    {
        "id": "loop_controller",
        "skill": "loop",
        "responsibility": "Keep advancing the loop until a real permission, evidence, verification, context, budget, or external-wait gate is reached.",
    },
)
LOOP_CORE_SKILLS = tuple(
    dict.fromkeys(
        skill
        for role in LOOP_CORE_ROLES
        for skill in (str(role["skill"]), *[str(item) for item in role.get("adjacent_skills", [])])
    )
)

_PROFILE_ALLOWED_ACTIONS: dict[str, set[str]] = {
    "observe_only": {"research", "planning"},
    "handoff_only": {"research", "planning", "ultragoal_creation", "executor_handoff", "external_posting_prep"},
    "execute_with_gates": {
        "research",
        "planning",
        "ultragoal_creation",
        "executor_handoff",
        "executor_dispatch",
        "repo_edit",
        "pr_creation",
        "pr_revision",
        "review_fix_loop",
        "ci_fix_loop",
        "release_note_work",
        "external_posting_prep",
    },
    "full_loop": {
        "research",
        "planning",
        "ultragoal_creation",
        "executor_handoff",
        "executor_dispatch",
        "repo_edit",
        "pr_creation",
        "pr_revision",
        "review_fix_loop",
        "ci_fix_loop",
        "release_note_work",
        "external_posting_prep",
        "merge",
    },
    "custom": set(),
}


def create_loop_cycle(
    paths: OmhPaths,
    *,
    goal_summary: str,
    goal_reframe: str,
    success_criteria: Iterable[str],
    permission_profile: str = "handoff_only",
    allowed_executors: Iterable[str] | None = None,
    allow_actions: Iterable[str] | None = None,
    forbid_actions: Iterable[str] | None = None,
    linked_goal_id: str = "",
    source: str = "omh",
    loop_id: str | None = None,
    allow_unloopable: bool = False,
) -> dict[str, Any]:
    if not goal_summary.strip():
        raise ValueError("goal summary is required")
    if not goal_reframe.strip():
        raise ValueError("goal reframe is required")
    criteria = _criteria_objects(success_criteria)
    loop_id = _storage_id(loop_id or new_loop_id(goal_summary), "loop_id")
    if linked_goal_id:
        read_goal_ledger(paths, linked_goal_id)
    loopability = assess_loopability(goal_summary, expose_goal=True)
    _enforce_loopability_start(loopability, allow_unloopable=allow_unloopable)
    loopability = _started_loopability_assessment(loopability, goal_reframe)
    now = utc_now()
    cycle = {
        "schema_version": LOOP_CYCLE_SCHEMA,
        "loop_id": loop_id,
        "created_at": now,
        "updated_at": now,
        "source": _safe_summary(source, limit=120),
        "phase": "interview",
        "phase_generation": 0,
        "wait_reason": "none",
        "goal": {
            "summary": _safe_summary(goal_summary),
            "summary_hash": sha256_text(goal_summary),
            "reframe": _safe_summary(goal_reframe, limit=360),
            "reframe_hash": sha256_text(goal_reframe),
            "north_star": str(loopability.get("north_star", "")),
            "current_loop_goal": _safe_summary(goal_reframe, limit=360),
        },
        "loopability_assessment": loopability,
        "success_criteria": criteria,
        "authority_envelope": build_authority_envelope(
            permission_profile=permission_profile,
            allowed_executors=allowed_executors,
            allow_actions=allow_actions,
            forbid_actions=forbid_actions,
        ),
        "feedback_gate": _feedback_gate(),
        "linked_goal_id": _storage_id(linked_goal_id, "linked_goal_id") if linked_goal_id else "",
        "cycles": [],
        "phase_transitions": [],
        "goal_driver_observations": [],
        "runtime": _runtime_state(),
        "loop_engineering": _loop_engineering_template(),
        "sticky_rules": [],
        "sticky_rule_attachment": _empty_sticky_rule_attachment(),
        "next_action": "continue_loop",
        "completion_claim_allowed": False,
        "claim_boundary": _claim_boundary(),
    }
    _normalize_permission_state(cycle)
    validation = validate_loop_cycle(cycle)
    if not validation["ok"]:
        raise ValueError("; ".join(validation["errors"]))
    ensure_dir(_loop_dir(paths, loop_id), private=True)
    return _guarded_cycle_update(
        paths, loop_id, lambda current: dict(cycle), operation="create_loop_cycle", default={}
    )


def loop_executor_capability(executor: str) -> dict[str, Any]:
    selected = _safe_summary(executor or "choose", limit=120) or "choose"
    if selected == "claude-code":
        loop_mode = "native"
        dispatch_owner = "executor"
        observability = ["native_loop_or_goal", "prompt_handoff", "wrapper_observation"]
        next_action = "prepare_claude_code_native_loop_handoff"
    elif selected == "codex":
        loop_mode = "omh_managed"
        dispatch_owner = "omh_wrapper"
        observability = ["codex_session_ref", "codex_progress_summary/v1", "codex_review_summary/v1"]
        next_action = "dispatch_or_resume_codex_session_then_observe"
    elif selected == "hermes":
        loop_mode = "omh_managed"
        dispatch_owner = "omh_wrapper"
        observability = ["loop_cycle/v1", "loop_queue_item/v1", "goal_ledger/v1"]
        next_action = "continue_omh_managed_loop"
    elif selected == "generic":
        loop_mode = "prompt_handoff"
        dispatch_owner = "human_operator"
        observability = ["manual_evidence_ref"]
        next_action = "prepare_prompt_handoff"
    elif selected in {"choose", "omx-runtime"}:
        loop_mode = "prompt_handoff"
        dispatch_owner = "human_operator"
        observability = ["runtime_handoff", "manual_evidence_ref"]
        next_action = "choose_executor_or_runtime"
    else:
        loop_mode = "unsupported"
        dispatch_owner = "human_operator"
        observability = []
        next_action = "choose_supported_executor"
    return {
        "schema_version": EXECUTOR_LOOP_CAPABILITY_SCHEMA,
        "executor": selected,
        "loop_mode": loop_mode,
        "dispatch_owner": dispatch_owner,
        "observability": observability,
        "next_action": next_action,
        "claim_boundary": (
            "Executor loop capability is routing metadata only. It is not dispatch, implementation, "
            "review, CI, merge, or goal completion evidence."
        ),
    }


def _enforce_loopability_start(assessment: dict[str, Any], *, allow_unloopable: bool) -> None:
    if allow_unloopable:
        return
    loopability = str(assessment.get("loopability", ""))
    if loopability == "direct_task":
        raise ValueError(
            "loop start rejected direct_task; use a direct delivery workflow or rerun with --allow-unloopable"
        )
    if loopability == "needs_clarification":
        raise ValueError(
            "loop start rejected unclear goal; run loop assess or deep-interview before starting a loop"
        )


def _started_loopability_assessment(assessment: dict[str, Any], goal_reframe: str) -> dict[str, Any]:
    reframe = _safe_summary(goal_reframe, limit=360)
    if not reframe:
        return assessment
    updated = {
        **assessment,
        "current_loop_goal": reframe,
        "next_loop_goal": reframe,
    }
    if updated.get("loopability") in {"needs_reframe", "north_star_only", "external_wait_only"}:
        updated.update(
            {
                "goal_kind": "project",
                "loopability": "loopable",
                "recommended_surface": "loop_runtime",
                "recommended_next_action": "continue_loop",
                "required_inputs": [],
                "reason": (
                    "A bounded loop goal reframe has been accepted; preserve the north star "
                    "while continuing with verification."
                ),
            }
        )
        if not str(updated.get("bounded_arena", "")).strip():
            updated["bounded_arena"] = "accepted loop reframe"
        if not str(updated.get("observable_problem", "")).strip():
            updated["observable_problem"] = "the accepted loop target defines the current observable gap"
        if not str(updated.get("next_verification", "")).strip():
            updated["next_verification"] = "The current loop step records a pass/fail evidence signal before the next tick."
        if not str(updated.get("stop_condition", "")).strip():
            updated["stop_condition"] = "The accepted loop goal passes its named verification signal or records a blocker."
    return updated


def read_loop_cycle(paths: OmhPaths, loop_id: str) -> dict[str, Any]:
    data = read_json_object(loop_cycle_path(paths, loop_id))
    if data is None:
        raise FileNotFoundError(loop_cycle_path(paths, loop_id))
    validation = validate_loop_cycle(data)
    if not validation["ok"]:
        raise ValueError("; ".join(validation["errors"]))
    return data


def list_loop_cycles(paths: OmhPaths) -> list[dict[str, Any]]:
    if not paths.loops_dir.exists():
        return []
    cycles: list[dict[str, Any]] = []
    for loop_json in sorted(paths.loops_dir.glob("*/cycle.json")):
        data = read_json_object(loop_json)
        if isinstance(data, dict):
            cycles.append(data)
    return cycles


def build_loop_start_card(
    goal_summary: str,
    *,
    include_goal: bool = False,
    source: str = "omh",
    default_permission_profile: str = "handoff_only",
    default_executor: str = "choose",
) -> dict[str, Any]:
    summary = _safe_summary(goal_summary)
    if not summary:
        raise ValueError("loop start-card requires a goal summary")
    if default_permission_profile not in PERMISSION_PROFILES:
        raise ValueError(f"unsupported permission profile: {default_permission_profile}")
    if default_executor not in LOOP_EXECUTOR_OPTION_IDS:
        raise ValueError(f"unsupported loop default executor: {default_executor}")
    assessment = assess_loopability(goal_summary, expose_goal=include_goal)
    invocation = _loop_invocation_contract(goal_summary, assessment)
    active_status = _loop_start_status(assessment, invocation)
    active_next_action = _loop_start_next_action(assessment, invocation)
    return {
        "schema_version": LOOP_START_CARD_SCHEMA,
        "source": _safe_summary(source, limit=120),
        "status": active_status,
        "goal_summary": summary if include_goal else "{message}",
        "goal_summary_hash": sha256_text(goal_summary),
        "goal_length": len(goal_summary),
        "next_action": active_next_action,
        "loopability_assessment": assessment,
        "loop_invocation": invocation,
        "role_pipeline": _loop_role_pipeline(),
        "core_skills": list(LOOP_CORE_SKILLS),
        "agentic_theme": "loop_invocation_means_keep_progressing_until_gate",
        "permission_profile_required": active_next_action == "choose_permission_profile" or active_status == "interview_required",
        "default_permission_profile": default_permission_profile,
        "default_executor": _safe_summary(default_executor, limit=120),
        "permission_profiles": [_permission_profile_option(profile) for profile in PERMISSION_PROFILES if profile != "custom"],
        "executor_options": [dict(option) for option in LOOP_EXECUTOR_OPTIONS],
        "required_inputs": [
            {
                "id": "goal_reframe",
                "label": "Goal reframe",
                "prompt": "Reframe the north-star goal into implementable internal work without shrinking its ambition.",
            },
            {
                "id": "success_criteria",
                "label": "Success criteria",
                "prompt": "Name the evidence that would prove internal work progressed, plus what remains external waiting.",
            },
            {
                "id": "permission_profile",
                "label": "Permission profile",
                "prompt": "Choose how far the loop may go before it asks for explicit authority.",
            },
        ],
        "suggested_success_criteria": [
            "Comparable capability gaps are identified and closed with tests or docs.",
            "Prepared handoffs and observed executor results remain separate.",
            "External adoption or market response is recorded as waiting until evidence exists.",
        ],
        "backend_contract": {
            "operation": "loop.start",
            "required_fields": ["goal_summary", "goal_reframe", "success_criteria", "permission_profile"],
            "optional_fields": ["allowed_executors", "linked_goal_id", "source", "loopability_assessment"],
            "creates_artifact": "loop_cycle/v1",
            "assessment_schema": LOOPABILITY_ASSESSMENT_SCHEMA,
        },
        "loop_engineering": _loop_engineering_template(),
        "verification_policy": _loop_verification_policy(),
        "failure_modes": _failure_mode_definitions(),
        "small_loop_guidance": _small_loop_guidance(),
        "actions": [
            "choose_permission_profile",
            "assess_loopability",
            "convert_to_loop_goal",
            "route_direct_task",
            "start_loop",
            "show_loop_status",
            "cancel",
        ],
        "claim_boundary": _claim_boundary(),
        "runtime_claim_boundary": _runtime_claim_boundary(),
    }


def _loop_role_pipeline() -> list[dict[str, Any]]:
    return [dict(role) for role in LOOP_CORE_ROLES]


def _explicit_loop_invocation(goal_summary: str) -> bool:
    return explicit_loop_invocation_signal(goal_summary)


def explicit_loop_invocation_signal(goal_summary: str) -> bool:
    normalized = goal_summary.strip().casefold()
    if not normalized:
        return False
    if LOOP_COMMAND_RE.match(normalized):
        return True
    if OMH_LOOP_COMMAND_RE.match(normalized):
        return True
    return False


def _loop_invocation_payload(goal_summary: str) -> str:
    normalized = goal_summary.strip().casefold()
    match = LOOP_COMMAND_RE.match(normalized)
    if match:
        return normalized[match.end() :].strip()
    match = OMH_LOOP_COMMAND_RE.match(normalized)
    if match:
        return normalized[match.end() :].strip()
    return normalized


def _loop_invocation_help_query(goal_summary: str) -> bool:
    payload = _loop_invocation_payload(goal_summary)
    if not payload:
        return False
    return bool(re.search(r"\b(help|docs?|commands?|what|how)\b", payload)) or any(
        term in payload for term in ("도움", "설명", "명령", "뭐야")
    )


def _loop_invocation_contract(goal_summary: str, assessment: dict[str, Any]) -> dict[str, Any]:
    explicit = _explicit_loop_invocation(goal_summary)
    help_query = explicit and _loop_invocation_help_query(goal_summary)
    return {
        "schema_version": LOOP_INVOCATION_SCHEMA,
        "invoked": explicit,
        "invocation_strength": "explicit" if explicit else "implicit",
        "help_or_catalog_query": help_query,
        "raw_command_redacted": True,
        "goal_visibility": "redacted_by_default",
        "authority_interpretation": "start_or_continue_until_gate" if explicit else "prepare_until_user_starts",
        "progress_policy": "do_not_stop_until_gate" if explicit else "prepare_start_card",
        "agentic_theme": "interviewer_planner_researcher_builder_reviewer_loop_controller",
        "core_agent_roles": [str(role["id"]) for role in LOOP_CORE_ROLES],
        "core_skills": list(LOOP_CORE_SKILLS),
        "stop_conditions": [
            "permission_blocked",
            "unsafe_external_action",
            "missing_selected_executor_for_code_mutation",
            "verification_failed",
            "context_or_budget_exhausted",
            "external_wait",
        ],
        "assessment_goal_kind": str(assessment.get("goal_kind", "unknown")),
        "assessment_loopability": str(assessment.get("loopability", "unknown")),
    }


def _loop_start_status(assessment: dict[str, Any], invocation: dict[str, Any]) -> str:
    if invocation.get("invoked") is True:
        return "started_prepared"
    if str(assessment.get("loopability", "")) == "loopable":
        return "ready_to_start"
    return "interview_required"


def _loop_start_next_action(assessment: dict[str, Any], invocation: dict[str, Any]) -> str:
    if invocation.get("invoked") is True:
        loopability = str(assessment.get("loopability", ""))
        if invocation.get("help_or_catalog_query") is True:
            return str(assessment.get("recommended_next_action", "ask_goal_boundary"))
        if loopability == "needs_clarification":
            return str(assessment.get("recommended_next_action", "ask_goal_boundary"))
        if loopability == "direct_task":
            return "route_direct_task"
        if loopability == "external_wait_only":
            return "record_external_wait"
        return "start_loop_cycle"
    return str(assessment.get("recommended_next_action", "start_goal_loop"))


def record_loop_feedback(
    paths: OmhPaths,
    loop_id: str,
    *,
    observed_artifacts: Iterable[str] | None = None,
    internal_gap: str = "",
    external_wait: str = "",
    context_exhausted: bool = False,
    budget_exhausted: bool = False,
    expected_revision: int | None = None,
    mutation_id: str | None = None,
) -> dict[str, Any]:
    artifacts = [_safe_summary(value, limit=320) for value in observed_artifacts or [] if str(value).strip()]
    feedback_gate = _feedback_gate(
        observed_artifacts=artifacts,
        internal_gap=internal_gap,
        external_wait=external_wait,
    )
    if external_wait.strip():
        phase = "waiting"
        wait_reason = "waiting_external_observation"
        next_action = "record_external_wait"
    elif context_exhausted:
        phase = "waiting"
        wait_reason = "context_exhausted"
        next_action = "record_checkpoint"
    elif budget_exhausted:
        phase = "waiting"
        wait_reason = "budget_exhausted"
        next_action = "record_checkpoint"
    elif feedback_gate["clear"]:
        phase = "research"
        wait_reason = "none"
        next_action = "continue_loop"
    else:
        phase = "feedback"
        wait_reason = "none"
        next_action = "record_feedback"

    def mutate(cycle: dict[str, Any]) -> dict[str, Any]:
        cycle_id = _new_item_id("cycle")
        observed_at = utc_now()
        set_loop_phase(
            cycle,
            to_phase=phase,
            transition_kind="feedback_evaluation",
            cause=wait_reason if wait_reason != "none" else "feedback_gate",
            source_ref=cycle_id,
            evidence_refs=artifacts,
            observed_at=observed_at,
        )
        cycle["wait_reason"] = wait_reason
        cycle["feedback_gate"] = feedback_gate
        cycle["next_action"] = next_action
        cycle["cycles"].append(
            {
                "cycle_id": cycle_id,
                "created_at": observed_at,
                "phase": phase,
                "wait_reason": wait_reason,
                "observed_artifacts": artifacts,
                "internal_actionable_gap": _safe_summary(internal_gap) if internal_gap.strip() else "",
                "external_wait": _safe_summary(external_wait) if external_wait.strip() else "",
            }
        )
        cycle["updated_at"] = utc_now()
        return cycle

    return _guarded_cycle_update(
        paths,
        loop_id,
        mutate,
        operation="record_loop_feedback",
        expected_revision=expected_revision,
        mutation_id=mutation_id,
        mutation_digest=_mutation_digest(
            "record_loop_feedback", artifacts, internal_gap, external_wait, context_exhausted, budget_exhausted
        ),
    )


def update_loop_permission(
    paths: OmhPaths,
    loop_id: str,
    *,
    allow_actions: Iterable[str] | None = None,
    forbid_actions: Iterable[str] | None = None,
    allowed_executors: Iterable[str] | None = None,
    expected_revision: int | None = None,
    mutation_id: str | None = None,
) -> dict[str, Any]:
    requested_allow = _valid_actions(allow_actions or [])
    requested_forbid = _valid_actions(forbid_actions or [])
    requested_executors = _safe_list(allowed_executors or [], limit=120)

    def mutate(cycle: dict[str, Any]) -> dict[str, Any]:
        # The merge reads the envelope that is current inside the lock, so a
        # concurrent grant is extended rather than reverted.
        current = _dict_value(cycle, "authority_envelope")
        existing_allowed = _string_set(current.get("allowed_actions", []))
        existing_forbidden = _string_set(current.get("forbidden_actions", []))
        forbidden = sorted(existing_forbidden | requested_forbid)
        allowed = sorted((existing_allowed | requested_allow) - set(forbidden))
        existing_executors = _string_set(current.get("allowed_executors", []))
        cycle["authority_envelope"] = build_authority_envelope(
            permission_profile="custom",
            allowed_executors=sorted(existing_executors | set(requested_executors)),
            allow_actions=allowed,
            forbid_actions=forbidden,
        )
        _normalize_permission_state(cycle)
        cycle["updated_at"] = utc_now()
        return cycle

    return _guarded_cycle_update(
        paths,
        loop_id,
        mutate,
        operation="update_loop_permission",
        expected_revision=expected_revision,
        mutation_id=mutation_id,
        mutation_digest=_mutation_digest(
            "update_loop_permission", sorted(requested_allow), sorted(requested_forbid), requested_executors
        ),
    )


def goal_ledger_entry_count(goal: Mapping[str, Any] | None) -> int:
    """Records written into one goal ledger: checkpoints, blockers, quality gates.

    The three lists a loop can actually append to. Acceptance criteria are
    declared at creation and only change status, so counting them would make a
    loop that writes nothing look like a loop that started well.
    """
    if not isinstance(goal, Mapping):
        return 0
    total = 0
    for key in ("checkpoints", "blockers", "quality_gates"):
        entries = goal.get(key)
        if isinstance(entries, list):
            total += len(entries)
    return total


def assess_loop_stop_ladder(
    cycle: dict[str, Any],
    *,
    planned_action: str = "",
    goal_linked: bool = False,
    goal_status: str = "",
    ledger_entry_count: int = 0,
    limit_signal: Mapping[str, Any] | None = None,
    auth_signal: Mapping[str, Any] | None = None,
    no_progress_cap: int = LOOP_NO_PROGRESS_TICK_CAP,
) -> dict[str, Any]:
    """Walk LOOP_STOP_REASONS in order and name the first rung that stops the tick.

    Pure policy over signals the caller already read, in the idiom
    `build_account_authorization` uses: the ladder never probes, so the same
    verdict is reproducible from a recorded snapshot. `read_loop_stop_ladder`
    is the reading half -- it also resolves `no_progress_cap` from the active
    security posture (`system.security_posture`, key `loop_no_progress_cap`)
    before calling in; the default here stays the unposture-adjusted
    constant so a direct caller sees the same behavior as before.
    """
    runtime = _runtime_state(cycle.get("runtime"))
    executor_profile = _preferred_executor(_dict_value(cycle, "authority_envelope"))
    previous_count = int(runtime["ledger_entry_count"])
    if not goal_linked:
        no_progress_ticks = 0
    elif ledger_entry_count > previous_count:
        no_progress_ticks = 0
    else:
        no_progress_ticks = int(runtime["no_progress_ticks"]) + 1

    verdicts: list[tuple[str, str]] = [
        _stop_rung_explicit_cancel(goal_linked, goal_status),
        _stop_rung_rate_limit(executor_profile, limit_signal),
        _stop_rung_auth_failure(executor_profile, planned_action, auth_signal),
        _stop_rung_no_progress(goal_linked, no_progress_ticks, no_progress_cap),
    ]

    rungs: list[dict[str, Any]] = []
    stop_reason = "none"
    stop_rung = 0
    detail = "No stop-ladder rung fired; the tick may advance."
    for index, reason in enumerate(LOOP_STOP_REASONS):
        state, rung_detail = verdicts[index]
        if stop_reason != "none":
            state, rung_detail = "not_evaluated", "A higher rung already stopped this tick."
        rungs.append(
            {
                "rung": index + 1,
                "reason": reason,
                "state": state,
                "detail": rung_detail,
                "evidence_source": _LOOP_STOP_EVIDENCE_SOURCES[reason],
            }
        )
        if state == "fired":
            stop_reason = reason
            stop_rung = index + 1
            detail = rung_detail
    return {
        "schema_version": LOOP_STOP_LADDER_SCHEMA,
        "loop_id": str(cycle.get("loop_id", "")),
        "stop": stop_reason != "none",
        "stop_reason": stop_reason,
        "stop_rung": stop_rung,
        "executor_profile": executor_profile,
        "planned_action": str(planned_action),
        "detail": detail,
        "next_action": _LOOP_STOP_NEXT_ACTIONS.get(stop_reason, ""),
        "ledger_entry_count": ledger_entry_count if goal_linked else previous_count,
        "no_progress_ticks": no_progress_ticks,
        "no_progress_cap": no_progress_cap,
        "rungs": rungs,
        "claim_boundary": LOOP_STOP_LADDER_CLAIM_BOUNDARY,
    }


def _stop_rung_explicit_cancel(goal_linked: bool, goal_status: str) -> tuple[str, str]:
    if not goal_linked:
        return ("not_applicable", "This loop carries no linked goal ledger to cancel.")
    if goal_status == "cancelled":
        return (
            "fired",
            "The linked goal ledger is cancelled; it refuses every checkpoint, blocker, and gate.",
        )
    if goal_status == "failed":
        # A negative but CONCLUSIVE verdict on the objective itself, reached
        # through `fail_goal_ledger` -- not an operator's explicit cancel, but
        # the same downstream fact: the ledger refuses every mutation, so a
        # tick that proceeded would only fail loudly on its first write.
        # Named distinctly from `cancelled` in `detail` on purpose: an
        # operator reading this stop should not mistake a conclusive failure
        # for someone having stopped the loop by hand.
        return (
            "fired",
            "The linked goal ledger failed conclusively; it refuses every checkpoint, blocker, and gate.",
        )
    return ("clear", f"The linked goal ledger status is `{goal_status or 'unknown'}`.")


def _stop_rung_rate_limit(executor_profile: str, limit_signal: Mapping[str, Any] | None) -> tuple[str, str]:
    if executor_profile not in AUTH_SIGNAL_PROFILES:
        return ("not_applicable", f"`{executor_profile}` records no limit signals.")
    if not isinstance(limit_signal, Mapping) or not limit_signal:
        return ("clear", f"No limit-shaped dispatch failure is recorded for `{executor_profile}`.")
    if limit_signal.get("stale") is not False:
        # Missing freshness means the stored stamp did not parse. Same
        # direction `_stamp_age_seconds` takes: what cannot be shown fresh is
        # not treated as fresh, so an unreadable stamp never fabricates a stop.
        return ("clear", "The recorded limit signal is stale or undatable, so it is history rather than state.")
    label = str(limit_signal.get("pattern_label", "") or "unlabelled")
    return (
        "fired",
        f"A `{label}` limit-shaped dispatch failure was observed for `{executor_profile}` "
        "inside the freshness horizon.",
    )


def _stop_rung_auth_failure(
    executor_profile: str, planned_action: str, auth_signal: Mapping[str, Any] | None
) -> tuple[str, str]:
    if planned_action != "executor_dispatch":
        return (
            "not_applicable",
            f"This tick plans `{planned_action or 'nothing'}`, so it hands no work to an executor CLI.",
        )
    marker = str((auth_signal or {}).get("login_marker", "") or "")
    if marker in {"", "not_applicable"}:
        return ("not_applicable", f"`{executor_profile}` carries no local login marker to read.")
    if marker == "absent":
        return (
            "fired",
            f"This tick would dispatch to `{executor_profile}` and omh sees no local login marker for it. "
            "An absent marker is file presence only - an API-key or environment-token install reads absent "
            "while working, and no provider rejected anything here.",
        )
    return ("clear", f"The `{executor_profile}` login marker reads `{marker}`.")


def _stop_rung_no_progress(
    goal_linked: bool, no_progress_ticks: int, no_progress_cap: int = LOOP_NO_PROGRESS_TICK_CAP
) -> tuple[str, str]:
    if not goal_linked:
        return ("not_applicable", "Without a linked goal ledger there are no records to key progress to.")
    if no_progress_ticks >= no_progress_cap:
        return (
            "fired",
            f"{no_progress_ticks} consecutive ticks wrote no new goal-ledger record "
            f"(cap {no_progress_cap}).",
        )
    return (
        "clear",
        f"{no_progress_ticks} consecutive ticks without a new goal-ledger record, under the "
        f"{no_progress_cap} cap.",
    )


def read_loop_stop_ladder(
    paths: OmhPaths,
    cycle: dict[str, Any],
    *,
    planned_action: str = "",
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Read the ladder's inputs, then hand them to the pure assessment.

    The auth marker is read only when the tick plans `executor_dispatch`: the
    marker file is the potentially large `~/.claude.json`, and a research or
    planning tick has no executor CLI to confirm.

    `no_progress_cap` is resolved from the active security posture here, not
    inside the pure assessment: `strict` fires the no-progress rung after one
    stalled tick instead of two (`security_posture.POSTURE_MAPPING`, key
    `loop_no_progress_cap`). `default` posture resolves to the unchanged
    `LOOP_NO_PROGRESS_TICK_CAP`. `resolve_security_posture` raises
    `ValueError` for an unrecognized `OMH_SECURITY`; the CLI tick/run-once
    commands already convert that to a clean error.
    """
    posture = resolve_security_posture(env)
    no_progress_cap = strict_override("loop_no_progress_cap", posture, LOOP_NO_PROGRESS_TICK_CAP)
    linked_goal_id = str(cycle.get("linked_goal_id", ""))
    goal_linked = False
    goal_status = ""
    ledger_entry_count = 0
    if linked_goal_id:
        try:
            goal = read_goal_ledger(paths, linked_goal_id)
        except (FileNotFoundError, ValueError):
            # An unreadable link is a setup gap, not a stop reason. Reporting
            # it as `not_applicable` keeps the ladder from inventing a cancel
            # or a stuck marker out of a missing file.
            goal = None
        if isinstance(goal, dict):
            goal_linked = True
            goal_status = str(goal.get("status", ""))
            ledger_entry_count = goal_ledger_entry_count(goal)
    executor_profile = _preferred_executor(_dict_value(cycle, "authority_envelope"))
    limit_signal: dict[str, object] = {}
    if executor_profile in AUTH_SIGNAL_PROFILES:
        limit_signal = last_limit_signal_for_profile(paths, executor_profile)
    auth_signal: dict[str, object] = {}
    if planned_action == "executor_dispatch":
        auth_signal = auth_signal_for_profile(executor_profile, home=home)
    return assess_loop_stop_ladder(
        cycle,
        planned_action=planned_action,
        goal_linked=goal_linked,
        goal_status=goal_status,
        ledger_entry_count=ledger_entry_count,
        limit_signal=limit_signal,
        auth_signal=auth_signal,
        no_progress_cap=no_progress_cap,
    )


def validate_loop_stop_ladder(value: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["stop_ladder must be an object"]
    if value.get("schema_version") != LOOP_STOP_LADDER_SCHEMA:
        errors.append(f"stop_ladder.schema_version must be {LOOP_STOP_LADDER_SCHEMA}")
    stop_reason = str(value.get("stop_reason", ""))
    if stop_reason not in set(LOOP_STOP_REASONS) | {"none"}:
        errors.append("stop_ladder.stop_reason is unsupported")
    if value.get("stop") is not (stop_reason != "none"):
        errors.append("stop_ladder.stop must agree with stop_reason")
    for key in ("no_progress_ticks", "no_progress_cap", "stop_rung", "ledger_entry_count"):
        count = value.get(key)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            errors.append(f"stop_ladder.{key} must be a non-negative integer")
    rungs = value.get("rungs")
    if not isinstance(rungs, list) or len(rungs) != len(LOOP_STOP_REASONS):
        errors.append(f"stop_ladder.rungs must hold {len(LOOP_STOP_REASONS)} entries")
        return errors
    for index, rung in enumerate(rungs):
        if not isinstance(rung, dict):
            errors.append(f"stop_ladder.rungs[{index}] must be an object")
            continue
        if rung.get("reason") != LOOP_STOP_REASONS[index]:
            errors.append(f"stop_ladder.rungs[{index}].reason must be {LOOP_STOP_REASONS[index]}")
        if rung.get("rung") != index + 1:
            errors.append(f"stop_ladder.rungs[{index}].rung must be {index + 1}")
        if rung.get("state") not in LOOP_STOP_RUNG_STATES:
            errors.append(f"stop_ladder.rungs[{index}].state is unsupported")
    return errors


def _loop_stuck_marker(ladder: dict[str, Any]) -> dict[str, Any]:
    return {
        "recorded_at": utc_now(),
        "reason": str(ladder["stop_reason"]),
        "no_progress_ticks": int(ladder["no_progress_ticks"]),
        "ledger_entry_count": int(ladder["ledger_entry_count"]),
        "summary": str(ladder["detail"]),
        "next_action": str(ladder["next_action"]),
        "claim_boundary": LOOP_STOP_LADDER_CLAIM_BOUNDARY,
    }


def tick_loop_runtime(
    paths: OmhPaths,
    loop_id: str,
    *,
    trigger: str = "manual",
    cadence: str = "",
    worktree_base: str = "",
    worktree_branch: str = "",
    subagent_role: str = "",
    connector: str = "",
    connector_action: str = "",
    workflow_pattern: str = "single_step",
    note: str = "",
    expected_revision: int | None = None,
    mutation_id: str | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    def mutate(cycle: dict[str, Any]) -> dict[str, Any]:
        # The plan and the queue item are derived from the cycle read inside
        # the lock: deriving them from an unlocked read appended a queue item
        # computed against permissions or a queue that had already moved on.
        envelope = _dict_value(cycle, "authority_envelope")
        plan = _next_runtime_plan(cycle, envelope)
        # The stop ladder runs before the queue item is built, on the plan this
        # tick would actually carry out. A stop appends nothing, raises no
        # heartbeat, and names its own reason: a refused tick has to be
        # distinguishable from a tick that ran and found nothing to do.
        ladder = read_loop_stop_ladder(
            paths, cycle, planned_action=str(plan["planned_action"]), home=home
        )
        if ladder["stop"]:
            runtime = _runtime_state(cycle.get("runtime"))
            runtime["ledger_entry_count"] = int(ladder["ledger_entry_count"])
            runtime["no_progress_ticks"] = int(ladder["no_progress_ticks"])
            runtime["last_stop_reason"] = str(ladder["stop_reason"])
            runtime["last_stop_at"] = utc_now()
            runtime["stop_ladder"] = ladder
            if ladder["stop_reason"] == "no_progress_cap":
                runtime["stuck_marker"] = _loop_stuck_marker(ladder)
            cycle["runtime"] = runtime
            cycle["next_action"] = str(ladder["next_action"])
            cycle["updated_at"] = utc_now()
            return cycle
        queue_item = _runtime_queue_item(
            cycle,
            envelope,
            plan,
            trigger=trigger,
            cadence=cadence,
            worktree_base=worktree_base,
            worktree_branch=worktree_branch,
            subagent_role=subagent_role,
            connector=connector,
            connector_action=connector_action,
            workflow_pattern=workflow_pattern,
            note=note,
        )
        runtime = _runtime_state(cycle.get("runtime"))
        runtime["heartbeat_count"] = int(runtime.get("heartbeat_count", 0)) + 1
        runtime["last_tick_at"] = queue_item["created_at"]
        runtime["last_trigger"] = queue_item["trigger"]
        runtime["last_planned_action"] = queue_item["planned_action"]
        runtime["last_queue_id"] = queue_item["queue_id"]
        runtime["ledger_entry_count"] = int(ladder["ledger_entry_count"])
        runtime["no_progress_ticks"] = int(ladder["no_progress_ticks"])
        runtime["last_stop_reason"] = "none"
        runtime["stop_ladder"] = ladder
        runtime.pop("stuck_marker", None)
        runtime.setdefault("queue", []).append(queue_item)
        cycle["runtime"] = runtime
        # Sticky-rule re-attachment advances only on a tick that actually
        # incremented heartbeat_count (this branch), never on a stopped tick
        # (the early `ladder["stop"]` return above) and never on a mere
        # status-card read. That keeps the repeat gap keyed to completed
        # loop turns, matching LOOP_STICKY_RULE_REPEAT_MODES's contract.
        cycle["sticky_rules"] = _sticky_rules_list(cycle.get("sticky_rules"))
        cycle["sticky_rule_attachment"] = _advance_sticky_rule_attachment(
            cycle["sticky_rules"], int(runtime["heartbeat_count"])
        )
        if queue_item["status"] == "prepared_not_observed":
            cycle["wait_reason"] = "none"
            cycle["next_action"] = "observe_runtime_queue"
        else:
            cycle["next_action"] = str(plan["next_action"])
        cycle["updated_at"] = utc_now()
        return cycle

    return _guarded_cycle_update(
        paths,
        loop_id,
        mutate,
        operation="tick_loop_runtime",
        expected_revision=expected_revision,
        mutation_id=mutation_id,
        mutation_digest=_mutation_digest(
            "tick_loop_runtime",
            trigger,
            cadence,
            worktree_base,
            worktree_branch,
            subagent_role,
            connector,
            connector_action,
            workflow_pattern,
            note,
        ),
    )


def run_loop_once(paths: OmhPaths, loop_id: str) -> dict[str, Any]:
    needs_tick: dict[str, bool] = {}

    def mutate(cycle: dict[str, Any]) -> dict[str, Any] | None:
        runtime = _runtime_state(cycle.get("runtime"))
        pending = [
            item
            for item in runtime.get("queue", [])
            if isinstance(item, dict) and item.get("status") == "prepared_not_observed"
        ]
        if not pending:
            # No write here: the tick below takes the lock again on its own.
            needs_tick["tick"] = True
            return None
        cycle["next_action"] = "observe_runtime_queue"
        cycle["updated_at"] = utc_now()
        return cycle

    cycle = _guarded_cycle_update(paths, loop_id, mutate, operation="run_loop_once")
    if not needs_tick:
        return cycle
    return tick_loop_runtime(
        paths,
        loop_id,
        trigger="automation",
        cadence="run-once",
        workflow_pattern="single_step",
        note=(
            "Non-daemon loop run-once prepared one queue item; no worktree, subagent, "
            "connector, executor, network, or code execution was performed by OMH."
        ),
    )


def run_loop_once_result(paths: OmhPaths, loop_id: str) -> dict[str, Any]:
    before = read_loop_cycle(paths, loop_id)
    before_runtime = _runtime_state(before.get("runtime"))
    before_queue = [item for item in before_runtime.get("queue", []) if isinstance(item, dict)]
    before_pending = [item for item in before_queue if item.get("status") == "prepared_not_observed"]
    cycle = run_loop_once(paths, loop_id)
    runtime = _runtime_state(cycle.get("runtime"))
    queue = [item for item in runtime.get("queue", []) if isinstance(item, dict)]
    if before_pending:
        queue_id = str(before_pending[-1].get("queue_id", ""))
        outcome = "pending_queue_exists"
        advanced = False
        created_queue_count = 0
    else:
        created_queue_count = max(0, len(queue) - len(before_queue))
        advanced = created_queue_count > 0
        outcome = "created_tick" if advanced else "no_eligible_tick"
        queue_id = str(queue[-1].get("queue_id", "")) if queue else ""
    stop_reason = str(runtime.get("last_stop_reason", "") or "none")
    if outcome == "no_eligible_tick" and stop_reason != "none":
        # A refused tick reports the ladder rung that refused it. Collapsing it
        # into no_eligible_tick would report a stop as an absence of work.
        # `pending_queue_exists` keeps its own name: that call never ticked, so
        # the stored reason belongs to an earlier tick, not to this one.
        outcome = "stopped_by_ladder"
    return {
        "loop": cycle,
        "run_once": {
            "schema_version": LOOP_RUN_ONCE_RESULT_SCHEMA,
            "loop_id": str(cycle.get("loop_id", loop_id)),
            "outcome": outcome,
            "advanced": advanced,
            "created_queue_count": created_queue_count,
            "queue_id": queue_id,
            "pending_queue_count": sum(1 for item in queue if item.get("status") == "prepared_not_observed"),
            "stop_reason": stop_reason,
            "next_action": str(cycle.get("next_action", "")),
            "claim_boundary": _runtime_claim_boundary(),
        },
    }


def list_loop_queue(paths: OmhPaths, loop_id: str, *, include_observed: bool = False) -> dict[str, Any]:
    cycle = read_loop_cycle(paths, loop_id)
    runtime = _runtime_state(cycle.get("runtime"))
    queue = [item for item in runtime.get("queue", []) if isinstance(item, dict)]
    visible = [
        _queue_item_summary(item)
        for item in queue
        if include_observed or not (item.get("status") == "observed" and item.get("observed") is True)
    ]
    return {
        "schema_version": LOOP_QUEUE_LIST_SCHEMA,
        "loop_id": cycle["loop_id"],
        "include_observed": include_observed,
        "queue": visible,
        "pending_queue_count": sum(1 for item in queue if item.get("status") == "prepared_not_observed"),
        "blocked_queue_count": sum(1 for item in queue if item.get("status") in {"blocked", "blocked_by_permission", "blocked_by_wait"}),
        "observed_queue_count": sum(1 for item in queue if item.get("status") == "observed" and item.get("observed") is True),
        "claim_boundary": _runtime_claim_boundary(),
    }


def inspect_loop_queue_item(paths: OmhPaths, loop_id: str, queue_id: str) -> dict[str, Any]:
    cycle = read_loop_cycle(paths, loop_id)
    item = _queue_item_ref(cycle, queue_id)[1]
    return {
        "schema_version": LOOP_QUEUE_ITEM_SCHEMA,
        "loop_id": cycle["loop_id"],
        "queue_item": item,
        "claim_boundary": _runtime_claim_boundary(),
    }


def build_loop_queue_handoff(paths: OmhPaths, loop_id: str, queue_id: str) -> dict[str, Any]:
    cycle = read_loop_cycle(paths, loop_id)
    item = _queue_item_ref(cycle, queue_id)[1]
    if item.get("status") != "prepared_not_observed":
        raise ValueError("only prepared_not_observed loop queue items can render a handoff")
    text = _queue_handoff_text(cycle, item)
    return {
        "schema_version": LOOP_QUEUE_HANDOFF_SCHEMA,
        "loop_id": cycle["loop_id"],
        "queue_id": item["queue_id"],
        "planned_action": item["planned_action"],
        "phase": item["phase"],
        "status": item["status"],
        "handoff_text": text,
        "worktree_plan": item.get("worktree_plan", _empty_worktree_plan()),
        "subagent_plan": item.get("subagent_plan", _empty_subagent_plan()),
        "connector_plan": item.get("connector_plan", _connector_plan("", "", str(item.get("planned_action", "")))),
        "next_action": "observe_or_block_loop_queue",
        "actions": ["observe_loop_queue", "block_loop_queue", "show_loop_status"],
        "claim_boundary": _runtime_claim_boundary(),
    }


def build_loop_goal_driver_handoff(
    paths: OmhPaths,
    loop_id: str,
    *,
    gate_commands: Iterable[str] | None = None,
    max_turns: int = 0,
) -> dict[str, Any]:
    return _build_loop_goal_driver_handoff(
        paths,
        read_loop_cycle(paths, loop_id),
        gate_commands=gate_commands,
        max_turns=max_turns,
    )


def _build_loop_goal_driver_handoff(
    paths: OmhPaths,
    cycle: dict[str, Any],
    *,
    gate_commands: Iterable[str] | None = None,
    max_turns: int = 0,
) -> dict[str, Any]:
    if max_turns < 0:
        raise ValueError("max turns must be zero or positive")
    if cycle.get("phase") == "complete":
        raise ValueError("a completed loop cycle cannot render a goal driver handoff")
    wait_reason = str(cycle.get("wait_reason", ""))
    if cycle.get("phase") == "blocked" or wait_reason in {"permission_required", "context_exhausted", "budget_exhausted"}:
        raise ValueError("a blocked, permission-gated, or exhausted loop cycle cannot render a goal driver handoff")
    commands: list[str] = []
    for command in gate_commands or []:
        if not isinstance(command, str):
            raise ValueError("goal gate commands must be strings")
        raw = str(command)
        if not raw.strip() or len(raw.splitlines()) > 1:
            raise ValueError("goal gate commands must be single-line shell commands")
        stripped = raw.strip()
        if len(stripped) > 240:
            raise ValueError("goal gate commands must be at most 240 characters")
        commands.append(stripped)
    if len(commands) > 8:
        raise ValueError("at most 8 goal gate commands can be prepared")

    goal = _dict_value(cycle, "goal")
    envelope = _dict_value(cycle, "authority_envelope")
    headline = _safe_summary(
        f"Continue OMH loop {cycle['loop_id']}: {goal.get('reframe', '')}", limit=_GOAL_DRIVER_LINE_LIMIT
    )

    linked_goal_id = str(cycle.get("linked_goal_id", ""))
    verify_items: list[str] = []
    if linked_goal_id:
        ledger = read_goal_ledger(paths, linked_goal_id)
        verify_items = [
            str(criterion.get("summary", ""))
            for criterion in ledger.get("acceptance_criteria", [])
            if criterion.get("required") and criterion.get("status") != "satisfied"
        ]
    verify_source = "goal_ledger" if verify_items else "loop_cycle"
    if not verify_items:
        verify_items = [
            str(criterion.get("summary", ""))
            for criterion in cycle.get("success_criteria", [])
            if isinstance(criterion, dict)
        ]
    constraint_items = [f"do not {action}" for action in envelope.get("blocked_actions", [])]
    constraint_items.append("do not claim goal completion from loop or judge state")
    boundary_items = [
        f"permission profile {envelope.get('permission_profile', '')}",
        "allowed executors " + (", ".join(envelope.get("allowed_executors", [])) or "none"),
        "allowed actions " + (", ".join(envelope.get("allowed_actions", [])) or "none"),
    ]
    verify_list = _string_list(verify_items)
    verify_full = "verify: " + "; ".join(verify_list)
    verify_line = _safe_summary(verify_full, limit=_GOAL_DRIVER_LINE_LIMIT)
    if len(verify_full) > _GOAL_DRIVER_LINE_LIMIT:
        contract_truncated = True
        truncated_criteria_count = sum(1 for item in verify_list if item not in verify_line)
    else:
        contract_truncated = False
        truncated_criteria_count = 0
    contract_lines = [
        verify_line,
        _safe_summary("constraints: " + "; ".join(_string_list(constraint_items)), limit=_GOAL_DRIVER_LINE_LIMIT),
        _safe_summary("boundaries: " + "; ".join(_string_list(boundary_items)), limit=_GOAL_DRIVER_LINE_LIMIT),
        _safe_summary(
            "stop when: OMH records a blocker, a permission gate, or an external wait; "
            "the OMH goal ledger completion gate stays the completion authority",
            limit=_GOAL_DRIVER_LINE_LIMIT,
        ),
    ]
    goal_command = "/goal " + headline + "\n" + "\n".join(contract_lines)

    gates = [
        {
            "command": command,
            "tier": "inner",
            "rationale": _INNER_TIER_EXPECTED_SIGNAL,
            "command_line": f"/goal gate add {command}",
        }
        for command in commands
    ]
    if gates:
        gate_gap: dict[str, Any] = {"state": "none"}
    else:
        gate_gap = {
            "state": "missing_commands",
            "next_action": "supply_inner_tier_gate_commands",
            "summary": (
                "No gate commands were supplied, so no runnable command backs the cheap "
                "inner-tier check categories. " + _INNER_TIER_EXPECTED_SIGNAL
            ),
            "uncovered_check_categories": list(_loop_verification_policy()["inner_loop_checks"]),
        }

    if linked_goal_id:
        completion_gate = build_goal_completion_gate(paths, linked_goal_id)
        completion_ownership: dict[str, Any] = {
            "owner": "omh_goal_ledger",
            "goal_id": linked_goal_id,
            "gate": {
                "ready": completion_gate["ready"],
                "next_action": completion_gate["next_action"],
                "missing_required_criteria": completion_gate["missing_required_criteria"],
                "summary": completion_gate["summary"],
            },
        }
    else:
        completion_ownership = {
            "owner": "omh_goal_ledger",
            "goal_id": None,
            "gate": {
                "ready": False,
                "next_action": "link a goal ledger before any completion claim",
                "missing_required_criteria": [],
                "summary": "link a goal ledger before any completion claim",
            },
        }

    if wait_reason == "waiting_external_observation":
        wait_state = {
            "waiting": True,
            "reason": wait_reason,
            "caveat": (
                "This loop cycle is waiting on an external observation. The standing /goal keeps "
                "taking turns while that wait is outstanding, so the stop when: clause is what "
                "prevents the loop from narrating the wait as progress. Record the external "
                "observation as loop evidence when it arrives; a judge verdict is not that observation."
            ),
        }
    else:
        wait_state = {"waiting": False, "reason": wait_reason, "caveat": ""}

    goal_command_sha256 = sha256_text(goal_command)
    return {
        "schema_version": LOOP_GOAL_DRIVER_HANDOFF_SCHEMA,
        "loop_id": cycle["loop_id"],
        "phase": cycle["phase"],
        "goal_command": goal_command,
        "goal_command_sha256": goal_command_sha256,
        "observation_contract": {
            "schema_version": LOOP_GOAL_DRIVER_OBSERVATION_SCHEMA,
            "record_command": "omh loop goal-driver-observe",
            "requires_user_activation": True,
            "required_fields": [
                "observation_id",
                "loop_id",
                "session_ref",
                "goal_command_sha256",
                "observation_source",
                "observed_at",
                "activation",
                "turns",
            ],
        },
        "native_goal_status": native_goal_status(cycle),
        "verify_source": verify_source,
        "contract_truncated": contract_truncated,
        "truncated_criteria_count": truncated_criteria_count,
        "gate_commands": gates,
        "gate_defaults": {
            "max_retries": 3,
            "timeout_seconds": 300,
            "overridable_from_chat": False,
            "source": "hermes_cli/goals.py DEFAULT_GATE_MAX_RETRIES / DEFAULT_GATE_TIMEOUT_SECONDS",
            "summary": (
                "A gate registered through /goal gate add always gets 3 retries and a "
                "300s timeout; the chat branch passes no overrides."
            ),
        },
        "gate_gap": gate_gap,
        "max_turns_guidance": {
            "recommended": max_turns if max_turns > 0 else UPSTREAM_GOAL_DEFAULT_MAX_TURNS,
            "upstream_default": UPSTREAM_GOAL_DEFAULT_MAX_TURNS,
            "config_key": "goals.max_turns",
            "note": (
                "The upstream turn-ceiling pause is a pause, not completion; record it as a "
                "loop wait state and decide the next cycle."
            ),
        },
        "completion_ownership": completion_ownership,
        "wait_state": wait_state,
        "caveats": {
            "interactive_only": (
                "The upstream /goal loop runs on interactive surfaces only; a headless "
                "one-shot CLI turn does not loop."
            ),
            "busy_dispatch": (
                "A new /goal sent mid-run is rejected by the upstream busy dispatch policy; "
                "set the goal between runs."
            ),
            "judge_fails_open": (
                "An upstream judge error fails open and the loop continues; a missing "
                "verdict is not a gate."
            ),
            "draft_alternative": (
                "/goal draft <text> is the operator alternative when a human wants the "
                "auxiliary model to draft the contract instead."
            ),
            "gates_discarded_on_set": (
                "Setting a new /goal replaces the goal state and discards every registered gate "
                "(hermes_cli/goals.py GoalManager.set constructs a fresh GoalState with empty gates) "
                "— re-run every gate_commands[*].command_line after each /goal set."
            ),
            "every_gate_runs_every_turn": (
                "Every registered gate runs at every turn boundary (hermes_cli/goals.py the per-turn "
                "gate loop in the turn-boundary evaluator; the only skip is the unchanged-workspace "
                "replay of an already-failing gate). Register cheap inner-tier checks only."
            ),
            "paste_as_one_message": (
                "Paste the goal_command as a single multi-line chat message; if a surface submits "
                "it line-by-line, line 1 sets a contract-less goal and the rest become ordinary "
                "chat turns."
            ),
        },
        "syntax_basis": (
            "hermes-agent v0.20.4 (build 2026.8.18), observed at "
            "~/.hermes/hermes-agent/pyproject.toml when this lane was implemented; the inline "
            "/goal contract aliases and the /goal gate add chat path were verified against that basis."
        ),
        "status": "prepared_not_observed",
        "next_action": "set_goal_then_register_gates",
        "actions": [
            "set_upstream_goal",
            "register_goal_gates",
            "record_goal_driver_observation",
            "tick_loop",
            "show_loop_status",
        ],
        "claim_boundary": (
            "Preparing goal driver text is not setting an upstream goal, not registering gates, "
            "not running gates, not a judge verdict, and not goal completion evidence."
        ),
    }


def record_loop_goal_driver_observation(
    paths: OmhPaths,
    loop_id: str,
    observation: Mapping[str, Any],
    *,
    expected_revision: int | None = None,
    mutation_id: str | None = None,
) -> dict[str, Any]:
    submitted = json.loads(json.dumps(dict(observation), sort_keys=True))
    if not isinstance(submitted, dict):
        raise ValueError("goal driver observation must be an object")

    def mutate(cycle: dict[str, Any]) -> dict[str, Any] | None:
        expected_digest = str(_build_loop_goal_driver_handoff(paths, cycle)["goal_command_sha256"])
        observations = cycle.get("goal_driver_observations", [])
        if not isinstance(observations, list):
            raise ValueError("goal_driver_observations must be a list")
        stored_turns = [
            turn
            for existing in observations
            if isinstance(existing, dict)
            for turn in existing.get("turns", [])
            if isinstance(turn, dict)
        ]
        expected_first_turn = (
            max(int(turn.get("turn_index", 0)) for turn in stored_turns) + 1
            if stored_turns
            else 1
        )
        canonical = parse_loop_goal_driver_observation(
            submitted,
            expected_loop_id=loop_id,
            expected_goal_command_sha256=expected_digest,
            expected_first_turn_index=expected_first_turn,
        )
        observation_id = str(canonical["observation_id"])
        for existing in observations:
            if not isinstance(existing, dict) or existing.get("observation_id") != observation_id:
                continue
            comparable = {key: value for key, value in existing.items() if key != "native_goal_status"}
            if comparable == canonical:
                return None
            raise ValueError(f"conflicting goal driver observation: {observation_id}")

        session_ref = str(canonical["session_ref"])
        goal_command_sha256 = str(canonical["goal_command_sha256"])
        if observations:
            first = observations[0]
            if not isinstance(first, dict) or (
                first.get("session_ref"),
                first.get("goal_command_sha256"),
            ) != (session_ref, goal_command_sha256):
                raise ValueError(
                    "loop_goal_driver_observation must continue the original "
                    "session and goal command stream"
                )
        turns = canonical["turns"]

        observed_at = str(canonical["observed_at"])
        for turn in turns:
            turn_index = int(turn["turn_index"])
            ended_refs = [str(value) for value in turn["turn_ended_evidence_refs"]]
            gate_refs = [str(value) for value in turn["phase_gate_evidence_refs"]]
            transition_loop_phase(
                cycle,
                to_phase=str(turn["to_phase"]),
                phase_gate=str(turn["phase_gate"]),
                transition_kind="observed_progress",
                cause="native_goal_turn",
                source_ref=f"{observation_id}-turn-{turn_index}",
                evidence_refs=[*ended_refs, *gate_refs],
                observed_at=observed_at,
                native_goal={
                    "observation_id": observation_id,
                    "session_ref": session_ref,
                    "goal_command_sha256": goal_command_sha256,
                    "turn_index": turn_index,
                },
            )

        stored = dict(canonical)
        cycle["goal_driver_observations"] = [*observations, stored]
        stored["native_goal_status"] = native_goal_status(cycle)
        cycle["next_action"] = "continue_loop"
        cycle["updated_at"] = utc_now()
        return cycle

    return _guarded_cycle_update(
        paths,
        loop_id,
        mutate,
        operation="record_loop_goal_driver_observation",
        expected_revision=expected_revision,
        mutation_id=mutation_id,
        mutation_digest=_mutation_digest("record_loop_goal_driver_observation", submitted),
    )


def dispatch_loop_queue_item(
    paths: OmhPaths,
    loop_id: str,
    queue_id: str,
    *,
    executor: str,
    session_ref: str = "",
    thread_ref: str = "",
    evidence_refs: Iterable[str] | None = None,
    summary: str = "",
    expected_revision: int | None = None,
    mutation_id: str | None = None,
) -> dict[str, Any]:
    refs = _safe_list(evidence_refs or [], limit=320)
    capability = loop_executor_capability(executor)
    dispatch = _dispatch_request(capability, session_ref, thread_ref, refs, summary)

    def mutate(cycle: dict[str, Any]) -> dict[str, Any] | None:
        runtime, item = _queue_item_ref(cycle, queue_id)
        if item.get("status") != "prepared_not_observed":
            raise ValueError("only prepared_not_observed loop queue items can record executor dispatch")
        existing = _dict_value(item, "executor_session")
        if str(existing.get("dispatch_status", "")) in {"prepared", "dispatched"}:
            if _executor_session_dispatch(existing) == dispatch:
                return None
            if existing.get("dispatch_status") == "dispatched":
                raise ValueError(
                    "loop queue item already has a different executor dispatch; use explicit recovery"
                )
        attempts = [entry for entry in existing.get("dispatch_attempts", []) if isinstance(entry, dict)]
        attempt = (
            _new_dispatch_attempt(queue_id, len(attempts) + 1, dispatch)
            if dispatch["dispatch_status"] == "dispatched"
            else None
        )
        item["executor_session"] = {
            **_empty_executor_session(str(capability["executor"])),
            **dispatch,
            "active_attempt_id": str(attempt["attempt_id"]) if attempt else "",
            "dispatch_attempts": [*attempts, *([attempt] if attempt else [])],
            "capability": capability,
        }
        runtime["last_queue_id"] = str(item["queue_id"])
        runtime["last_queue_status"] = str(item["status"])
        cycle["runtime"] = runtime
        cycle["next_action"] = "observe_runtime_queue"
        cycle["updated_at"] = utc_now()
        return cycle

    return _guarded_cycle_update(
        paths,
        loop_id,
        mutate,
        operation="dispatch_loop_queue_item",
        expected_revision=expected_revision,
        mutation_id=mutation_id,
        mutation_digest=_mutation_digest(
            "dispatch_loop_queue_item", queue_id, executor, session_ref, thread_ref, refs, summary
        ),
    )


def recover_loop_queue_item_dispatch(
    paths: OmhPaths,
    loop_id: str,
    queue_id: str,
    *,
    prior_attempt_id: str,
    prior_outcome: str,
    outcome_evidence_refs: Iterable[str],
    executor: str,
    session_ref: str = "",
    thread_ref: str = "",
    evidence_refs: Iterable[str] | None = None,
    outcome_summary: str = "",
    summary: str = "",
    expected_revision: int | None = None,
    mutation_id: str | None = None,
) -> dict[str, Any]:
    attempt_id = _safe_summary(prior_attempt_id, limit=120)
    if not attempt_id:
        raise ValueError("prior dispatch attempt id is required")
    if prior_outcome not in LOOP_DISPATCH_RECOVERY_OUTCOMES:
        raise ValueError(
            f"prior dispatch outcome must be one of: {', '.join(LOOP_DISPATCH_RECOVERY_OUTCOMES)}"
        )
    outcome_refs = _safe_list(outcome_evidence_refs, limit=320)
    if not outcome_refs:
        raise ValueError("dispatch recovery requires prior outcome evidence")
    capability = loop_executor_capability(executor)
    dispatch_refs = _safe_list(evidence_refs or [], limit=320)
    dispatch = _dispatch_request(capability, session_ref, thread_ref, dispatch_refs, summary)
    if dispatch["dispatch_status"] != "dispatched":
        raise ValueError("dispatch recovery requires new dispatch identity or evidence")

    def mutate(cycle: dict[str, Any]) -> dict[str, Any]:
        runtime, item = _queue_item_ref(cycle, queue_id)
        if item.get("status") != "prepared_not_observed":
            raise ValueError("only prepared_not_observed loop queue items can recover executor dispatch")
        existing = _dict_value(item, "executor_session")
        attempts = [dict(entry) for entry in existing.get("dispatch_attempts", []) if isinstance(entry, dict)]
        if not attempts:
            raise ValueError("legacy executor dispatch has no attempt identity; record its outcome before recovery")
        if existing.get("active_attempt_id") != attempt_id or attempts[-1].get("attempt_id") != attempt_id:
            raise ValueError("prior dispatch attempt must be the active attempt")
        attempts[-1] = {
            **attempts[-1],
            "delivery_outcome": prior_outcome,
            "outcome_evidence_refs": outcome_refs,
            "outcome_summary": (
                _safe_summary(outcome_summary, limit=320)
                if outcome_summary.strip()
                else "Prior dispatch outcome recorded before explicit recovery."
            ),
        }
        next_attempt = _new_dispatch_attempt(queue_id, len(attempts) + 1, dispatch)
        item["executor_session"] = {
            **existing,
            **dispatch,
            "active_attempt_id": next_attempt["attempt_id"],
            "dispatch_attempts": [*attempts, next_attempt],
            "capability": capability,
        }
        runtime["last_queue_id"] = str(item["queue_id"])
        runtime["last_queue_status"] = str(item["status"])
        cycle["runtime"] = runtime
        cycle["next_action"] = "observe_runtime_queue"
        cycle["updated_at"] = utc_now()
        return cycle

    return _guarded_cycle_update(
        paths,
        loop_id,
        mutate,
        operation="recover_loop_queue_item_dispatch",
        expected_revision=expected_revision,
        mutation_id=mutation_id,
        mutation_digest=_mutation_digest(
            "recover_loop_queue_item_dispatch",
            queue_id,
            attempt_id,
            prior_outcome,
            outcome_refs,
            outcome_summary,
            executor,
            session_ref,
            thread_ref,
            dispatch_refs,
            summary,
        ),
    )


def observe_codex_loop_queue_item(
    paths: OmhPaths,
    loop_id: str,
    queue_id: str,
    *,
    codex_log_text: str = "",
    evidence_refs: Iterable[str] | None = None,
    codex_log_ref: str = "",
    summary: str = "",
    dispatch_attempt_id: str = "",
    expected_revision: int | None = None,
    mutation_id: str | None = None,
) -> dict[str, Any]:
    refs = _safe_list(evidence_refs or [], limit=320)
    log_ref = _safe_summary(codex_log_ref, limit=320) if codex_log_ref.strip() else ""
    all_refs = _safe_list([*refs, *([log_ref] if log_ref else [])], limit=320)
    if not all_refs:
        raise ValueError("Codex loop queue observation requires at least one evidence ref")
    progress = summarize_codex_jsonl_text(
        codex_log_text,
        evidence_refs=all_refs,
        source=log_ref or "codex-loop-observation",
    )

    def mutate(cycle: dict[str, Any]) -> dict[str, Any]:
        runtime, item = _queue_item_ref(cycle, queue_id)
        if item.get("status") != "prepared_not_observed":
            raise ValueError("only prepared_not_observed loop queue items can observe Codex progress")
        existing = _dict_value(item, "executor_session")
        observed_attempt_id = _resolve_observed_dispatch_attempt(
            existing,
            dispatch_attempt_id,
            expected_executor="codex",
        )
        executor_session = {
            **_empty_executor_session("codex"),
            **existing,
            "executor": "codex",
            "loop_mode": "omh_managed",
            "dispatch_owner": "omh_wrapper",
            "dispatch_status": "progress_observed",
            "progress_summary": progress,
            "summary": _safe_summary(summary, limit=320) if summary.strip() else str(progress.get("chat_summary", "")),
            "progress_evidence_refs": all_refs,
            "dispatch_attempts": _confirm_dispatch_attempt(existing, observed_attempt_id, all_refs),
            "capability": loop_executor_capability("codex"),
        }
        item["executor_session"] = executor_session
        item["observed_dispatch_attempt_id"] = observed_attempt_id
        item["status"] = "observed"
        item["observed"] = True
        observed_at = utc_now()
        item["observed_at"] = observed_at
        item["observed_evidence_refs"] = _safe_list([*_string_list(item.get("observed_evidence_refs", [])), *all_refs], limit=320)
        item["observation_summary"] = executor_session["summary"] or "Codex progress observed for this loop queue item."
        runtime["last_queue_id"] = str(item["queue_id"])
        runtime["last_queue_status"] = "observed"
        cycle["runtime"] = runtime
        phase_gate = str(item.get("phase_gate", ""))
        if phase_gate and _queue_phase_is_current(cycle, item):
            transition_loop_phase(
                cycle,
                to_phase=str(item.get("target_phase", item.get("phase", ""))),
                phase_gate=phase_gate,
                transition_kind="observed_progress",
                cause="codex_queue_observation",
                source_ref=str(item["queue_id"]),
                evidence_refs=all_refs,
                observed_at=observed_at,
            )
            item["phase_transition_status"] = "observed"
        elif phase_gate:
            item["phase_transition_status"] = "superseded"
        else:
            set_loop_phase(
                cycle,
                to_phase="feedback",
                transition_kind="legacy_queue_observation",
                cause="codex_queue_observation",
                source_ref=str(item["queue_id"]),
                evidence_refs=all_refs,
                observed_at=observed_at,
            )
        if item.get("phase_transition_status") != "superseded":
            cycle["wait_reason"] = "none"
            cycle["next_action"] = (
                "record_feedback"
                if cycle["phase"] == "feedback"
                else "continue_loop"
            )
        cycle["updated_at"] = utc_now()
        return cycle

    return _guarded_cycle_update(
        paths,
        loop_id,
        mutate,
        operation="observe_codex_loop_queue_item",
        expected_revision=expected_revision,
        mutation_id=mutation_id,
        mutation_digest=_mutation_digest(
            "observe_codex_loop_queue_item", queue_id, all_refs, summary, dispatch_attempt_id
        ),
    )


def build_loop_cycle_narration(paths: OmhPaths, loop_id: str, queue_id: str = "") -> dict[str, Any]:
    cycle = read_loop_cycle(paths, loop_id)
    item: dict[str, Any] = {}
    if queue_id:
        item = _queue_item_ref(cycle, queue_id)[1]
    else:
        runtime = _runtime_state(cycle.get("runtime"))
        queue = [entry for entry in runtime.get("queue", []) if isinstance(entry, dict)]
        item = queue[-1] if queue else {}
    goal = _dict_value(cycle, "goal")
    executor_session = _dict_value(item, "executor_session")
    executor = str(executor_session.get("executor") or _preferred_executor(_dict_value(cycle, "authority_envelope")) or "selected executor")
    executor_label = "Codex" if executor == "codex" else ("Claude Code" if executor == "claude-code" else executor)
    progress = _dict_value(executor_session, "progress_summary")
    progress_text = str(progress.get("chat_summary") or executor_session.get("summary") or item.get("observation_summary") or "아직 관측된 실행 요약은 없어.")
    status = str(item.get("status", "")) or str(cycle.get("phase", ""))
    return {
        "schema_version": LOOP_CYCLE_NARRATION_SCHEMA,
        "loop_id": str(cycle.get("loop_id", loop_id)),
        "queue_id": str(item.get("queue_id", queue_id)),
        "headline": "이번 사이클을 시작합니다." if status == "prepared_not_observed" else "이번 사이클 진행 상황입니다.",
        "cycle_state": status,
        "problem_definition": str(goal.get("current_loop_goal") or goal.get("reframe") or goal.get("summary", "")),
        "planned_approach": str(item.get("planned_action", cycle.get("next_action", "continue_loop"))),
        "executor_status": f"{executor_label} 상태: {executor_session.get('dispatch_status', 'not_dispatched')}",
        "progress_summary": progress_text,
        "verification_status": str(_dict_value(item, "verification_plan").get("expected_signal", "verification not planned yet")),
        "next_message": _narration_next_message(status, executor_session),
        "not_evidence_yet": ["implementation", "review", "ci", "merge", "goal_completion"],
        "claim_boundary": _runtime_claim_boundary(),
    }


def observe_loop_queue_item(
    paths: OmhPaths,
    loop_id: str,
    queue_id: str,
    *,
    evidence_refs: Iterable[str],
    worktree_evidence_refs: Iterable[str] | None = None,
    subagent_evidence_refs: Iterable[str] | None = None,
    connector_evidence_refs: Iterable[str] | None = None,
    summary: str = "",
    dispatch_attempt_id: str = "",
    expected_revision: int | None = None,
    mutation_id: str | None = None,
) -> dict[str, Any]:
    refs = _safe_list(evidence_refs, limit=320)
    worktree_refs = _safe_list(worktree_evidence_refs or [], limit=320)
    subagent_refs = _safe_list(subagent_evidence_refs or [], limit=320)
    connector_refs = _safe_list(connector_evidence_refs or [], limit=320)
    aggregate_refs = _safe_list([*refs, *worktree_refs, *subagent_refs, *connector_refs], limit=320)
    if not aggregate_refs:
        raise ValueError("loop queue observation requires at least one evidence ref")

    def mutate(cycle: dict[str, Any]) -> dict[str, Any]:
        runtime, item = _queue_item_ref(cycle, queue_id)
        if item.get("status") != "prepared_not_observed":
            raise ValueError("only prepared_not_observed loop queue items can be observed")
        executor_session = _dict_value(item, "executor_session")
        observed_attempt_id = _resolve_observed_dispatch_attempt(
            executor_session,
            dispatch_attempt_id,
        )
        if observed_attempt_id:
            item["executor_session"] = {
                **executor_session,
                "dispatch_attempts": _confirm_dispatch_attempt(
                    executor_session,
                    observed_attempt_id,
                    aggregate_refs,
                ),
            }
        item["status"] = "observed"
        item["observed"] = True
        item["observed_dispatch_attempt_id"] = observed_attempt_id
        observed_at = utc_now()
        item["observed_at"] = observed_at
        item["observed_evidence_refs"] = aggregate_refs
        item["observation_summary"] = _safe_summary(summary, limit=320) if summary.strip() else "Queue item observed by wrapper or operator evidence."
        _mark_queue_plans_observed(
            item,
            worktree_evidence_refs=worktree_refs,
            subagent_evidence_refs=subagent_refs,
            connector_evidence_refs=connector_refs,
        )
        runtime["last_queue_id"] = str(item["queue_id"])
        runtime["last_queue_status"] = "observed"
        cycle["runtime"] = runtime
        phase_gate = str(item.get("phase_gate", ""))
        if phase_gate and _queue_phase_is_current(cycle, item):
            transition_loop_phase(
                cycle,
                to_phase=str(item.get("target_phase", item.get("phase", ""))),
                phase_gate=phase_gate,
                transition_kind="observed_progress",
                cause="queue_observation",
                source_ref=str(item["queue_id"]),
                evidence_refs=aggregate_refs,
                observed_at=observed_at,
            )
            item["phase_transition_status"] = "observed"
        elif phase_gate:
            item["phase_transition_status"] = "superseded"
        else:
            set_loop_phase(
                cycle,
                to_phase="feedback",
                transition_kind="legacy_queue_observation",
                cause="queue_observation",
                source_ref=str(item["queue_id"]),
                evidence_refs=aggregate_refs,
                observed_at=observed_at,
            )
        if item.get("phase_transition_status") != "superseded":
            cycle["wait_reason"] = "none"
            cycle["next_action"] = (
                "record_feedback"
                if cycle["phase"] == "feedback"
                else "continue_loop"
            )
        cycle["updated_at"] = utc_now()
        return cycle

    return _guarded_cycle_update(
        paths,
        loop_id,
        mutate,
        operation="observe_loop_queue_item",
        expected_revision=expected_revision,
        mutation_id=mutation_id,
        mutation_digest=_mutation_digest(
            "observe_loop_queue_item", queue_id, aggregate_refs, summary, dispatch_attempt_id
        ),
    )


def block_loop_queue_item(
    paths: OmhPaths,
    loop_id: str,
    queue_id: str,
    *,
    reason: str,
    expected_revision: int | None = None,
    mutation_id: str | None = None,
) -> dict[str, Any]:
    blocker = _safe_summary(reason, limit=320)
    if not blocker:
        raise ValueError("loop queue blocker reason is required")

    def mutate(cycle: dict[str, Any]) -> dict[str, Any]:
        runtime, item = _queue_item_ref(cycle, queue_id)
        if item.get("status") == "observed" or item.get("observed") is True:
            raise ValueError("observed loop queue items cannot be blocked")
        item["status"] = "blocked"
        item["observed"] = False
        blocked_at = utc_now()
        item["blocked_at"] = blocked_at
        item["blocker_reason"] = blocker
        runtime["last_queue_id"] = str(item["queue_id"])
        runtime["last_queue_status"] = "blocked"
        cycle["runtime"] = runtime
        set_loop_phase(
            cycle,
            to_phase="blocked",
            transition_kind="queue_blocked",
            cause="queue_blocker_observed",
            source_ref=str(item["queue_id"]),
            observed_at=blocked_at,
        )
        cycle["wait_reason"] = "none"
        cycle["next_action"] = "resolve_runtime_queue_blocker"
        cycle["updated_at"] = utc_now()
        return cycle

    return _guarded_cycle_update(
        paths,
        loop_id,
        mutate,
        operation="block_loop_queue_item",
        expected_revision=expected_revision,
        mutation_id=mutation_id,
        mutation_digest=_mutation_digest("block_loop_queue_item", queue_id, blocker),
    )


def build_loop_status_card(paths: OmhPaths, loop_id: str) -> dict[str, Any]:
    cycle = read_loop_cycle(paths, loop_id)
    envelope = _dict_value(cycle, "authority_envelope")
    loopability = _loopability_for_cycle(cycle)
    linked_goal_id = str(cycle.get("linked_goal_id", ""))
    linked_gate: dict[str, Any] | None = None
    if linked_goal_id:
        linked_gate = build_goal_completion_gate(paths, linked_goal_id)
    card = {
        "schema_version": LOOP_STATUS_CARD_SCHEMA,
        "loop_id": cycle["loop_id"],
        "phase": cycle["phase"],
        "wait_reason": cycle["wait_reason"],
        "permission_profile": envelope.get("permission_profile", "custom"),
        "authority_summary": _authority_summary(envelope),
        "allowed_actions": list(envelope.get("allowed_actions", [])),
        "blocked_actions": list(envelope.get("blocked_actions", [])),
        "approval_required_for": list(envelope.get("blocked_actions", [])),
        "allowed_executors": list(envelope.get("allowed_executors", [])),
        "loopability_assessment": loopability,
        "north_star": loopability.get("north_star", ""),
        "current_loop_goal": loopability.get("current_loop_goal", ""),
        "feedback_gate": cycle.get("feedback_gate", _feedback_gate()),
        "native_goal_status": native_goal_status(cycle),
        "runtime_summary": _runtime_summary(cycle),
        "loop_engineering": _loop_engineering_status(cycle),
        "failure_mode_summary": _failure_mode_summary(cycle),
        "small_loop_guidance": _small_loop_guidance(),
        "linked_goal_completion": linked_gate or {"observed": False, "reason": "no linked goal ledger"},
        "next_action": _next_action(cycle),
        "safe_copy": _safe_status_copy(cycle, envelope),
        "completion_claim_allowed": _completion_claim_allowed(linked_gate),
        "sticky_rule_attachment": cycle.get("sticky_rule_attachment") or _empty_sticky_rule_attachment(),
        "claim_boundary": _claim_boundary(),
    }
    card["constraint_assessment"] = assess_loop_constraint(card)
    return card


def build_authority_envelope(
    *,
    permission_profile: str,
    allowed_executors: Iterable[str] | None = None,
    allow_actions: Iterable[str] | None = None,
    forbid_actions: Iterable[str] | None = None,
) -> dict[str, Any]:
    if permission_profile not in PERMISSION_PROFILES:
        raise ValueError(f"unsupported permission profile: {permission_profile}")
    explicitly_forbidden = _valid_actions(forbid_actions or [])
    allowed = set(_PROFILE_ALLOWED_ACTIONS[permission_profile])
    allowed.update(_valid_actions(allow_actions or []))
    allowed.difference_update(explicitly_forbidden)
    blocked = sorted(set(LOOP_ACTIONS) - allowed)
    executors = _safe_list(allowed_executors or [], limit=120)
    return {
        "permission_profile": permission_profile,
        "allowed_actions": sorted(allowed),
        "blocked_actions": blocked,
        "approval_checkpoints": blocked,
        "budget_limits": {
            "token_budget": "checkpoint_when_exhausted",
            "time_budget": "not_set",
            "external_spend": "not_allowed",
        },
        "forbidden_actions": sorted(explicitly_forbidden),
        "allowed_executors": executors,
        "approval_policy": "ask_when_exceeds_envelope",
        "resume_policy": "checkpoint_on_context_or_token_exhaustion",
        "merge_authority": "granted" if "merge" in allowed else "disabled",
        "external_action_authority": "publish_allowed" if "external_posting" in allowed else "prepare_only",
    }


def validate_loop_cycle(cycle: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if cycle.get("schema_version") != LOOP_CYCLE_SCHEMA:
        errors.append(f"schema_version must be {LOOP_CYCLE_SCHEMA}")
    loop_id = str(cycle.get("loop_id", ""))
    if not STORAGE_ID_RE.fullmatch(loop_id) or "/" in loop_id or "\\" in loop_id or ".." in loop_id:
        errors.append("loop_id must be a storage id")
    if cycle.get("phase") not in LOOP_PHASES:
        errors.append("phase is unsupported")
    phase_generation = cycle.get("phase_generation")
    if phase_generation is not None and (
        isinstance(phase_generation, bool)
        or not isinstance(phase_generation, int)
        or phase_generation < 0
    ):
        errors.append("phase_generation must be a non-negative integer")
    if cycle.get("wait_reason") not in WAIT_REASONS:
        errors.append("wait_reason is unsupported")
    goal = cycle.get("goal")
    if not isinstance(goal, dict) or not str(goal.get("summary", "")).strip() or "raw_north_star" in goal:
        errors.append("goal summary metadata is required and raw_north_star is not allowed")
    criteria = cycle.get("success_criteria")
    if not isinstance(criteria, list) or not criteria:
        errors.append("at least one success criterion is required")
    envelope = cycle.get("authority_envelope")
    if not isinstance(envelope, dict):
        errors.append("authority_envelope is required")
    else:
        profile = envelope.get("permission_profile")
        allowed_actions = envelope.get("allowed_actions")
        blocked_actions = envelope.get("blocked_actions")
        if profile not in PERMISSION_PROFILES:
            errors.append("authority_envelope.permission_profile is unsupported")
        if not isinstance(allowed_actions, list) or not all(action in LOOP_ACTIONS for action in allowed_actions):
            errors.append("authority_envelope.allowed_actions is invalid")
        if not isinstance(blocked_actions, list) or not all(action in LOOP_ACTIONS for action in blocked_actions):
            errors.append("authority_envelope.blocked_actions is invalid")
        approval_checkpoints = envelope.get("approval_checkpoints")
        forbidden_actions = envelope.get("forbidden_actions")
        budget_limits = envelope.get("budget_limits")
        if not isinstance(approval_checkpoints, list) or not all(action in LOOP_ACTIONS for action in approval_checkpoints):
            errors.append("authority_envelope.approval_checkpoints is invalid")
        if not isinstance(forbidden_actions, list) or not all(action in LOOP_ACTIONS for action in forbidden_actions):
            errors.append("authority_envelope.forbidden_actions is invalid")
        if not isinstance(budget_limits, dict):
            errors.append("authority_envelope.budget_limits is required")
    runtime = cycle.get("runtime")
    if runtime is not None:
        errors.extend(_validate_runtime(runtime))
    sticky_rules = cycle.get("sticky_rules")
    if sticky_rules is not None:
        if not isinstance(sticky_rules, list):
            errors.append("sticky_rules must be a list")
        else:
            seen_rule_ids: set[str] = set()
            for index, rule in enumerate(sticky_rules):
                for error in validate_loop_sticky_rule(rule):
                    errors.append(f"sticky_rules[{index}]: {error}")
                if isinstance(rule, dict):
                    rule_id = str(rule.get("rule_id", ""))
                    if rule_id in seen_rule_ids:
                        errors.append(f"sticky_rules[{index}].rule_id duplicates an earlier entry")
                    seen_rule_ids.add(rule_id)
    attachment = cycle.get("sticky_rule_attachment")
    if attachment is not None:
        errors.extend(validate_loop_sticky_rule_attachment(attachment))
    errors.extend(validate_loop_phase_history(cycle))
    if cycle.get("completion_claim_allowed") is not False:
        errors.append("loop_cycle cannot directly allow goal completion claims")
    assessment = cycle.get("loopability_assessment")
    if assessment is not None:
        errors.extend(validate_loopability_assessment(assessment))
    errors.extend(revision_field_errors(cycle, "loop_cycle"))
    return {"ok": not errors, "errors": errors}


def new_loop_id(goal_summary: str, now: datetime | None = None) -> str:
    return f"{_stamp(now).lower()}-{_slugify(goal_summary)}-{secrets.token_hex(3)}"


def loop_cycle_path(paths: OmhPaths, loop_id: str) -> Path:
    return _loop_dir(paths, loop_id) / "cycle.json"


def _raise_loop_validation_errors(cycle: dict[str, Any]) -> None:
    validation = validate_loop_cycle(cycle)
    if not validation["ok"]:
        raise ValueError("; ".join(validation["errors"]))


def _mutation_digest(*parts: object) -> str:
    """Digest of one operation's own arguments, for replay-conflict detection."""
    return sha256_text(json.dumps(list(parts), sort_keys=True, separators=(",", ":"), default=str))


def _guarded_cycle_update(
    paths: OmhPaths,
    loop_id: str,
    mutate,
    *,
    operation: str,
    expected_revision: int | None = None,
    mutation_id: str | None = None,
    mutation_digest: str | None = None,
    default: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One locked read-check-write transaction on cycle.json.

    Every cycle mutator goes through here: reading the cycle outside the lock
    and writing the whole record back blind-overwrote whatever a concurrent
    writer had already committed, including guarded queue observations.
    Queue-item and permission preconditions therefore run inside this
    transaction, and a replayed mutation_id returns the current cycle without
    a write or revision bump. Replay is keyed on (operation, mutation_id).
    """
    path = loop_cycle_path(paths, loop_id)

    def _mutate(current: dict[str, Any]) -> dict[str, Any] | None:
        if default is None:
            _raise_loop_validation_errors(current)
        return mutate(current)

    result = guarded_record_update(
        path,
        mutate=_mutate,
        operation=operation,
        expected_revision=expected_revision,
        mutation_id=mutation_id,
        mutation_digest=mutation_digest,
        lock_name="cycle.json",
        validate=_raise_loop_validation_errors,
        default=default,
    )
    return result.record if isinstance(result, DuplicateMutationReplay) else result


def _loop_dir(paths: OmhPaths, loop_id: str) -> Path:
    safe_loop_id = _storage_id(loop_id, "loop_id")
    root = paths.loops_dir.resolve()
    path = (root / safe_loop_id).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("loop_id escapes loops directory") from exc
    return path


def _storage_id(value: str, kind: str) -> str:
    item = str(value).strip()
    if not STORAGE_ID_RE.fullmatch(item):
        raise ValueError(f"{kind} must match {STORAGE_ID_RE.pattern}")
    if item in {".", ".."} or ".." in item or "/" in item or "\\" in item:
        raise ValueError(f"{kind} must be a storage id, not a path")
    return item


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "loop")[:48].strip("-") or "loop"


def _stamp(value: datetime | None = None) -> str:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _new_item_id(prefix: str) -> str:
    return f"{prefix}-{_stamp().lower()}-{secrets.token_hex(3)}"


def _safe_summary(value: str, *, limit: int = 240) -> str:
    summary = re.sub(r"\s+", " ", str(value)).strip()
    if len(summary) <= limit:
        return summary
    return summary[: limit - 1].rstrip() + "..."


def _safe_list(values: Iterable[str], *, limit: int = 240) -> list[str]:
    return sorted({_safe_summary(str(value), limit=limit) for value in values if str(value).strip()})


def _string_set(values: object) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {str(value) for value in values if str(value).strip()}


def _string_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if str(value).strip()]


def _loopability_for_cycle(cycle: dict[str, Any]) -> dict[str, Any]:
    assessment = cycle.get("loopability_assessment")
    if isinstance(assessment, dict) and assessment.get("schema_version") == LOOPABILITY_ASSESSMENT_SCHEMA:
        goal = _dict_value(cycle, "goal")
        if str(goal.get("reframe", "")).strip():
            assessment = {
                **assessment,
                "current_loop_goal": str(goal.get("reframe", "")),
                "next_loop_goal": str(goal.get("reframe", "")),
            }
        return assessment
    goal = _dict_value(cycle, "goal")
    summary = str(goal.get("summary", ""))
    return assess_loopability(summary or str(cycle.get("loop_id", "loop")), expose_goal=True)


def _valid_actions(values: Iterable[str]) -> set[str]:
    actions = {str(value).strip() for value in values if str(value).strip()}
    unknown = sorted(actions - set(LOOP_ACTIONS))
    if unknown:
        raise ValueError(f"unsupported loop action(s): {', '.join(unknown)}")
    return actions


def _workflow_pattern(value: str) -> str:
    pattern = _safe_summary(value or "single_step", limit=80) or "single_step"
    if pattern not in LOOP_WORKFLOW_PATTERNS:
        raise ValueError(f"unsupported loop workflow pattern: {pattern}")
    return pattern


def _loop_engineering_template() -> dict[str, Any]:
    return {
        "schema_version": LOOP_ENGINEERING_SCHEMA,
        "definition": "A loop is a local system that prompts agents through task discovery, distribution, execution, verification, and the next task decision.",
        "pipeline": [
            {
                "id": step,
                "label": step.replace("_", " "),
                "claim_boundary": "This step describes orchestration state only until observed evidence refs are recorded.",
            }
            for step in LOOP_PIPELINE_STEPS
        ],
        "building_blocks": [
            {
                "id": block,
                "label": block.replace("_", " "),
                "claim_boundary": _building_block_boundary(block),
            }
            for block in LOOP_BUILDING_BLOCKS
        ],
        "workflow_patterns": [
            {
                "id": pattern,
                "label": pattern.replace("_", " "),
                "claim_boundary": "Pattern selection changes orchestration shape only; it is not dispatch or execution evidence.",
            }
            for pattern in LOOP_WORKFLOW_PATTERNS
        ],
        "context_policy": _loop_context_policy(),
        "cost_policy": _loop_cost_policy(),
        "verification_policy": _loop_verification_policy(),
        "failure_modes": _failure_mode_definitions(),
        "small_loop_guidance": _small_loop_guidance(),
        "subagent_result_contract_schema": LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
        "claim_boundary": _runtime_claim_boundary(),
    }


def _loop_engineering_status(cycle: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime_state(cycle.get("runtime"))
    queue = [item for item in runtime.get("queue", []) if isinstance(item, dict)]
    workflow_summary = _workflow_pattern_summary(queue)
    contract = _loop_engineering_contract(cycle)
    return {
        "schema_version": LOOP_ENGINEERING_SCHEMA,
        "loop_id": str(cycle.get("loop_id", "")),
        "current_pipeline_step": _pipeline_step_for_phase(
            str(cycle.get("phase", "interview")),
            str(cycle.get("wait_reason", "none")),
        ),
        "pipeline": [
            {
                "id": step,
                "state": _pipeline_step_state(step, cycle, queue),
                "evidence_refs": _pipeline_step_evidence_refs(step, cycle, queue),
                "claim_boundary": "State is orchestration metadata unless the evidence refs point to observed wrapper/runtime artifacts.",
            }
            for step in LOOP_PIPELINE_STEPS
        ],
        "building_blocks": _building_block_statuses(cycle, queue),
        "workflow_patterns": workflow_summary,
        "context_policy": contract["context_policy"],
        "cost_policy": contract["cost_policy"],
        "verification_policy": contract.get("verification_policy") or _loop_verification_policy(),
        "failure_modes": contract.get("failure_modes") or _failure_mode_definitions(),
        "small_loop_guidance": contract.get("small_loop_guidance") or _small_loop_guidance(),
        "subagent_result_contract_schema": LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
        "claim_boundary": _runtime_claim_boundary(),
    }


def _loop_engineering_contract(cycle: dict[str, Any]) -> dict[str, Any]:
    contract = cycle.get("loop_engineering")
    if isinstance(contract, dict) and contract.get("schema_version") == LOOP_ENGINEERING_SCHEMA:
        return {
            **contract,
            "context_policy": contract.get("context_policy") or _loop_context_policy(),
            "cost_policy": contract.get("cost_policy") or _loop_cost_policy(),
            "verification_policy": contract.get("verification_policy") or _loop_verification_policy(),
            "failure_modes": contract.get("failure_modes") or _failure_mode_definitions(),
            "small_loop_guidance": contract.get("small_loop_guidance") or _small_loop_guidance(),
        }
    return _loop_engineering_template()


def _queue_loop_engineering(planned_action: str, status: str, workflow_pattern: str) -> dict[str, Any]:
    return {
        "schema_version": LOOP_ENGINEERING_SCHEMA,
        "pipeline_step": _pipeline_step_for_action(planned_action),
        "workflow_pattern": workflow_pattern,
        "status": status,
        "context_policy_ref": LOOP_CONTEXT_POLICY_REF,
        "cost_policy_ref": LOOP_COST_POLICY_REF,
        "subagent_result_contract_schema": LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
        "claim_boundary": _runtime_claim_boundary(),
    }


def _subagent_result_contract(planned_action: str, workflow_pattern: str) -> dict[str, Any]:
    return {
        "schema_version": LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
        "planned_action": _safe_summary(planned_action, limit=80),
        "workflow_pattern": workflow_pattern,
        "status_values": ["ok", "blocked", "needs_human", "failed"],
        "required_fields": ["status", "summary", "evidence_refs", "next_actions"],
        "optional_fields": ["artifacts", "changed_files", "risks", "verification"],
        "max_summary_chars": 1200,
        "parent_context_policy": "Return a bounded structured result and evidence refs; do not paste the full transcript, raw logs, or large artifacts into parent context.",
        "large_output_policy": "Store large outputs outside parent context and return a path, id, hash, or wrapper evidence ref.",
        "cost_policy": _loop_cost_policy(workflow_pattern),
        "verification_policy": _subagent_verification_policy(planned_action, workflow_pattern),
    }


def _loop_context_policy() -> dict[str, Any]:
    return {
        "read_model": "bounded_state_and_evidence_refs",
        "parent_context": "Keep the parent loop focused on decision state, summaries, evidence refs, and next actions.",
        "large_output_policy": "Reference bulky subagent, connector, test, or research output by artifact path, id, hash, or evidence ref.",
        "subagent_return": "Subagents should return structured result objects, not replay their full working context.",
        "summary_budget_chars": 1200,
    }


def _loop_cost_policy(workflow_pattern: str = "single_step") -> dict[str, Any]:
    pattern = workflow_pattern if workflow_pattern in LOOP_WORKFLOW_PATTERNS else "single_step"
    return {
        "workflow_pattern": pattern,
        "bounded_reads": True,
        "reuse_schema_scaffold": True,
        "avoid_full_rescan": True,
        "default_verifier_lanes": 1,
        "extra_verifier_policy": "Add verifier lanes only for high-risk changes, failed evidence, explicit review requests, or adversarial_verification/tournament patterns.",
        "large_output_policy": "Keep large outputs in artifacts and pass refs, not full text.",
        "summary_budget_chars": 1200,
    }


def _subagent_verification_policy(planned_action: str, workflow_pattern: str) -> str:
    if workflow_pattern == "adversarial_verification":
        return "Return independent objections, checked evidence refs, and a pass/fail/blocked verdict."
    if workflow_pattern == "tournament":
        return "Return candidate approach id, scoring criteria, tradeoffs, and evidence refs for synthesis."
    if planned_action in {"review_fix_loop", "ci_fix_loop"}:
        return "Return verification command evidence, failures, fixes required, and residual risk."
    return "Return enough evidence refs for the parent loop to decide whether to continue, block, or ask for authority."


def _pipeline_step_for_action(planned_action: str) -> str:
    if planned_action in {"research", "planning", "ultragoal_creation"}:
        return "task_discovery"
    if planned_action in {"executor_handoff", "executor_dispatch"}:
        return "distribution"
    if planned_action in {
        "repo_edit",
        "pr_creation",
        "pr_revision",
        "release_note_work",
        "external_posting_prep",
        "external_posting",
        "merge",
    }:
        return "execution"
    if planned_action in {"review_fix_loop", "ci_fix_loop"}:
        return "verification"
    return "next_task_decision"


def _pipeline_step_for_phase(phase: str, wait_reason: str) -> str:
    if wait_reason != "none" or phase in {"waiting", "blocked", "complete"}:
        return "next_task_decision"
    if phase == "handoff":
        return "distribution"
    if phase == "execution":
        return "execution"
    if phase == "feedback":
        return "verification"
    return "task_discovery"


def _pipeline_step_state(step: str, cycle: dict[str, Any], queue: list[dict[str, Any]]) -> str:
    if step == "task_discovery":
        goal = _dict_value(cycle, "goal")
        criteria = cycle.get("success_criteria")
        return "observed" if goal.get("summary") and isinstance(criteria, list) and criteria else "missing"
    if step == "verification":
        feedback = _dict_value(cycle, "feedback_gate")
        if feedback.get("observed_artifacts"):
            return "observed"
        return _queue_pipeline_state(queue, step)
    if step == "next_task_decision":
        if str(cycle.get("wait_reason", "none")) != "none":
            return "waiting"
        if str(cycle.get("next_action", "")).strip():
            return "ready"
        return "pending"
    return _queue_pipeline_state(queue, step)


def _pipeline_step_evidence_refs(step: str, cycle: dict[str, Any], queue: list[dict[str, Any]]) -> list[str]:
    loop_id = str(cycle.get("loop_id", "loop"))
    if step == "task_discovery":
        return [f"loop:{loop_id}:goal", f"loop:{loop_id}:success_criteria"]
    if step == "verification":
        refs = _string_list(_dict_value(cycle, "feedback_gate").get("observed_artifacts", []))
        return refs or _queue_pipeline_refs(queue, step)
    if step == "next_task_decision":
        return [f"loop:{loop_id}:next_action:{_next_action(cycle)}"]
    return _queue_pipeline_refs(queue, step)


def _queue_pipeline_state(queue: list[dict[str, Any]], step: str) -> str:
    relevant: list[dict[str, Any]] = []
    for item in queue:
        if _queue_item_pipeline_step(item) == step:
            relevant.append(item)
    if any(item.get("status") == "observed" and item.get("observed") is True for item in relevant):
        return "observed"
    if any(item.get("status") == "prepared_not_observed" for item in relevant):
        return "prepared_not_observed"
    if any(item.get("status") in {"blocked", "blocked_by_permission", "blocked_by_wait"} for item in relevant):
        return "blocked"
    return "pending"


def _queue_pipeline_refs(queue: list[dict[str, Any]], step: str) -> list[str]:
    refs: list[str] = []
    for item in queue:
        if _queue_item_pipeline_step(item) == step:
            queue_id = str(item.get("queue_id", ""))
            if queue_id:
                refs.append(f"loop_queue:{queue_id}")
    return sorted(set(refs))


def _queue_item_pipeline_step(item: dict[str, Any]) -> str:
    return str(item.get("pipeline_step", _pipeline_step_for_action(str(item.get("planned_action", "")))))


def _building_block_statuses(cycle: dict[str, Any], queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runtime = _runtime_state(cycle.get("runtime"))
    return [
        {
            "id": "automation",
            "state": "ticked" if int(runtime.get("heartbeat_count", 0) or 0) else "available",
            "detail": "Runtime ticks may be manual, scheduled, wrapper-driven, or automation-driven.",
            "evidence_refs": [f"runtime:heartbeat:{runtime.get('heartbeat_count', 0)}"],
            "claim_boundary": _building_block_boundary("automation"),
        },
        _plan_building_block("worktree", queue, "worktree_plan", "created"),
        {
            "id": "skill",
            "state": "available",
            "detail": "The loop skill owns visible orchestration, not hidden execution.",
            "evidence_refs": ["skill:loop"],
            "claim_boundary": _building_block_boundary("skill"),
        },
        _plan_building_block("connector", queue, "connector_plan", "dispatched"),
        _plan_building_block("subagent", queue, "subagent_plan", "dispatched"),
    ]


def _plan_building_block(block: str, queue: list[dict[str, Any]], key: str, flag: str) -> dict[str, Any]:
    plans = [_dict_value(item, key) for item in queue if isinstance(item, dict)]
    requested = [plan for plan in plans if plan.get("strategy") != "none"]
    refs: list[str] = []
    for plan in requested:
        refs.extend(_string_list(plan.get("evidence_refs", [])))
    if any(plan.get("observed") is True and plan.get(flag) is True for plan in requested):
        state = "observed"
    elif requested:
        state = "planned_not_observed"
    elif any(item.get("status") in {"blocked", "blocked_by_permission", "blocked_by_wait"} for item in queue):
        state = "blocked"
    else:
        state = "not_requested"
    result: dict[str, Any] = {
        "id": block,
        "state": state,
        "detail": _building_block_detail(block),
        "evidence_refs": sorted(set(refs)),
        "claim_boundary": _building_block_boundary(block),
    }
    if block == "subagent":
        result["result_contract_schema"] = LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA
    return result


def _building_block_detail(block: str) -> str:
    details = {
        "worktree": "Worktree entries are path and branch hints until a wrapper records creation evidence.",
        "connector": "Connector entries are intent only until wrapper evidence records I/O.",
        "subagent": "Subagent entries are handoff plans until dispatch and result evidence are recorded.",
    }
    return details.get(block, "")


def _building_block_boundary(block: str) -> str:
    boundaries = {
        "automation": "A tick records orchestration intent; it is not proof that downstream work happened.",
        "worktree": "A worktree plan is not worktree creation evidence.",
        "skill": "Skill routing is not plan acceptance, dispatch, execution, or completion evidence.",
        "connector": "Connector intent is not connector I/O evidence.",
        "subagent": "A subagent plan is not dispatch, execution, or result evidence.",
    }
    return boundaries.get(block, _runtime_claim_boundary())


def _workflow_pattern_summary(queue: list[dict[str, Any]]) -> dict[str, Any]:
    used: dict[str, int] = {}
    for item in queue:
        pattern = str(item.get("workflow_pattern", "")).strip()
        if pattern:
            used[pattern] = used.get(pattern, 0) + 1
    last = str(queue[-1].get("workflow_pattern", "")) if queue else ""
    return {
        "available": list(LOOP_WORKFLOW_PATTERNS),
        "used": used,
        "last": last,
        "claim_boundary": "A workflow pattern is an orchestration shape, not proof that any subagent or executor ran.",
    }


def _criteria_objects(criteria: Iterable[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, criterion in enumerate(criteria, start=1):
        summary = _safe_summary(str(criterion).strip())
        if not summary:
            raise ValueError(f"success criterion LC{index:03d} requires a summary")
        result.append({"id": f"LC{index:03d}", "summary": summary, "status": "pending", "evidence_refs": []})
    if not result:
        raise ValueError("at least one success criterion is required")
    return result


def _feedback_gate(
    *,
    observed_artifacts: Iterable[str] | None = None,
    internal_gap: str = "",
    external_wait: str = "",
) -> dict[str, Any]:
    artifacts = _safe_list(observed_artifacts or [], limit=320)
    internal_gap_summary = _safe_summary(internal_gap) if internal_gap.strip() else ""
    external_wait_summary = _safe_summary(external_wait) if external_wait.strip() else ""
    return {
        "clear": bool(artifacts and internal_gap_summary and not external_wait_summary),
        "observed_artifacts": artifacts,
        "internal_actionable_gap": internal_gap_summary,
        "external_wait": external_wait_summary,
        "evaluated_at": utc_now(),
    }


def _runtime_state(value: object | None = None) -> dict[str, Any]:
    runtime = value if isinstance(value, dict) else {}
    queue = runtime.get("queue", [])
    if not isinstance(queue, list):
        queue = []
    state: dict[str, Any] = {
        "schema_version": LOOP_RUNTIME_SCHEMA,
        "heartbeat_count": _non_negative_count(runtime.get("heartbeat_count")),
        "last_tick_at": str(runtime.get("last_tick_at", "")),
        "last_trigger": _safe_summary(str(runtime.get("last_trigger", "")), limit=80),
        "last_planned_action": _safe_summary(str(runtime.get("last_planned_action", "")), limit=80),
        "last_queue_id": _safe_summary(str(runtime.get("last_queue_id", "")), limit=140),
        # Stop-ladder accounting. `ledger_entry_count` is the goal-ledger record
        # count observed at the last tick, and `no_progress_ticks` counts the
        # consecutive ticks since that number last moved - the pair is what
        # keys the cap to records written rather than ticks attempted.
        "ledger_entry_count": _non_negative_count(runtime.get("ledger_entry_count")),
        "no_progress_ticks": _non_negative_count(runtime.get("no_progress_ticks")),
        "last_stop_reason": str(runtime.get("last_stop_reason", "") or "none"),
        "last_stop_at": str(runtime.get("last_stop_at", "")),
        "queue": queue,
        "claim_boundary": _runtime_claim_boundary(),
    }
    for key in ("stop_ladder", "stuck_marker"):
        carried = runtime.get(key)
        if isinstance(carried, dict):
            state[key] = carried
    return state


def _non_negative_count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _next_runtime_plan(cycle: dict[str, Any], envelope: dict[str, Any]) -> dict[str, str]:
    wait_reason = str(cycle.get("wait_reason", "none"))
    if wait_reason == "permission_required":
        return {
            "planned_action": "request_permission",
            "phase": "waiting",
            "phase_gate": "",
            "status": "blocked_by_permission",
            "next_action": "request_permission",
            "reason": "The loop has no allowed action yet.",
            "context_policy_ref": LOOP_CONTEXT_POLICY_REF,
            "cost_policy_ref": LOOP_COST_POLICY_REF,
            "subagent_result_contract_schema": LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
        }
    if wait_reason == "waiting_external_observation":
        return {
            "planned_action": "wait_for_external_observation",
            "phase": "waiting",
            "phase_gate": "",
            "status": "blocked_by_wait",
            "next_action": "record_external_wait",
            "reason": "The loop is waiting for external evidence and should not auto-continue.",
            "context_policy_ref": LOOP_CONTEXT_POLICY_REF,
            "cost_policy_ref": LOOP_COST_POLICY_REF,
            "subagent_result_contract_schema": LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
        }
    if wait_reason in {"context_exhausted", "budget_exhausted"}:
        return {
            "planned_action": "checkpoint_resume",
            "phase": "waiting",
            "phase_gate": "",
            "status": "blocked_by_wait",
            "next_action": "record_checkpoint",
            "reason": "The loop needs a checkpoint before more context or budget is available.",
            "context_policy_ref": LOOP_CONTEXT_POLICY_REF,
            "cost_policy_ref": LOOP_COST_POLICY_REF,
            "subagent_result_contract_schema": LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
        }

    planned_action, phase, phase_gate = _phase_runtime_action(str(cycle.get("phase", "interview")))
    allowed = set(_string_set(envelope.get("allowed_actions", [])))
    if planned_action not in allowed:
        return {
            "planned_action": planned_action,
            "phase": str(cycle.get("phase", "interview")),
            "phase_gate": "",
            "status": "blocked_by_permission",
            "next_action": "request_permission",
            "reason": f"`{planned_action}` is outside the current authority envelope.",
            "context_policy_ref": LOOP_CONTEXT_POLICY_REF,
            "cost_policy_ref": LOOP_COST_POLICY_REF,
            "subagent_result_contract_schema": LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
        }
    return {
        "planned_action": planned_action,
        "phase": phase,
        "phase_gate": phase_gate,
        "status": "prepared_not_observed",
        "next_action": "observe_runtime_queue",
        "reason": "Prepared the next loop step for a wrapper, scheduler, or executor to observe.",
        "context_policy_ref": LOOP_CONTEXT_POLICY_REF,
        "cost_policy_ref": LOOP_COST_POLICY_REF,
        "subagent_result_contract_schema": LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
    }


def _phase_runtime_action(phase: str) -> tuple[str, str, str]:
    return phase_target(phase)


def _runtime_queue_item(
    cycle: dict[str, Any],
    envelope: dict[str, Any],
    plan: dict[str, str],
    *,
    trigger: str,
    cadence: str,
    worktree_base: str,
    worktree_branch: str,
    subagent_role: str,
    connector: str,
    connector_action: str,
    workflow_pattern: str,
    note: str,
) -> dict[str, Any]:
    planned_action = plan["planned_action"]
    queue_id = _new_item_id("queue")
    branch_hint = worktree_branch.strip() or f"omh-loop/{cycle.get('loop_id', 'loop')}/{planned_action}"
    role = subagent_role.strip() or _default_subagent_role(planned_action)
    connector_name = connector.strip()
    is_prepared = plan["status"] == "prepared_not_observed"
    pattern = _workflow_pattern(workflow_pattern)
    return {
        "schema_version": LOOP_QUEUE_ITEM_SCHEMA,
        "queue_id": queue_id,
        "created_at": utc_now(),
        "trigger": _safe_summary(trigger or "manual", limit=80),
        "cadence": _safe_summary(cadence, limit=80) if cadence.strip() else "",
        "planned_action": planned_action,
        "workflow_pattern": pattern,
        "pipeline_step": _pipeline_step_for_action(planned_action),
        "context_policy_ref": plan.get("context_policy_ref", LOOP_CONTEXT_POLICY_REF),
        "cost_policy_ref": plan.get("cost_policy_ref", LOOP_COST_POLICY_REF),
        "subagent_result_contract_schema": plan.get(
            "subagent_result_contract_schema",
            LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA,
        ),
        "status": plan["status"],
        "source_phase": str(cycle.get("phase", "interview")),
        "source_phase_generation": int(cycle.get("phase_generation", 0)),
        "source_authority_sha256": _authority_envelope_sha256(envelope),
        "phase": plan["phase"],
        "target_phase": plan["phase"],
        "phase_gate": plan.get("phase_gate", ""),
        "reason": _safe_summary(plan["reason"], limit=320),
        "worktree_plan": (
            _worktree_plan(cycle, planned_action, worktree_base, branch_hint) if is_prepared else _empty_worktree_plan()
        ),
        "subagent_plan": (
            _subagent_plan(cycle, planned_action, role, envelope, pattern) if is_prepared else _empty_subagent_plan()
        ),
        "connector_plan": (
            _connector_plan(connector_name, connector_action, planned_action)
            if is_prepared
            else _connector_plan("", "", planned_action)
        ),
        "executor_session": _empty_executor_session(_preferred_executor(envelope)),
        "verification_plan": _verification_plan(planned_action, pattern, is_prepared=is_prepared),
        "note": _safe_summary(note, limit=240) if note.strip() else "",
        "observed": False,
        "observed_at": "",
        "observed_evidence_refs": [],
        "observation_summary": "",
        "blocked_at": "",
        "blocker_reason": "",
        "loop_engineering": _queue_loop_engineering(planned_action, plan["status"], pattern),
        "claim_boundary": _runtime_claim_boundary(),
    }


def _authority_envelope_sha256(envelope: Mapping[str, Any]) -> str:
    return sha256_text(
        json.dumps(
            dict(envelope),
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    )


def _queue_phase_is_current(
    cycle: Mapping[str, Any],
    item: Mapping[str, Any],
) -> bool:
    generation = item.get("source_phase_generation")
    if isinstance(generation, bool) or not isinstance(generation, int):
        return False
    envelope = cycle.get("authority_envelope")
    if not isinstance(envelope, Mapping):
        return False
    return (
        item.get("source_phase") == cycle.get("phase")
        and generation == cycle.get("phase_generation", 0)
        and item.get("source_authority_sha256")
        == _authority_envelope_sha256(envelope)
    )


def _worktree_plan(cycle: dict[str, Any], planned_action: str, worktree_base: str, branch_hint: str) -> dict[str, Any]:
    base = _safe_summary(worktree_base, limit=160) if worktree_base.strip() else ".worktrees"
    loop_id = str(cycle.get("loop_id", "loop"))
    path_hint = f"{base.rstrip('/')}/omh-loop-{_slugify(loop_id)}-{_slugify(planned_action)}"
    return {
        "strategy": "planned_only",
        "path_hint": path_hint,
        "branch_hint": _safe_summary(branch_hint, limit=180),
        "created": False,
        "observed": False,
        "evidence_refs": [],
        "boundary": "OMH records the worktree plan; an authorized wrapper or executor must create and observe it.",
    }


def _empty_worktree_plan() -> dict[str, Any]:
    return {
        "strategy": "none",
        "path_hint": "",
        "branch_hint": "",
        "created": False,
        "observed": False,
        "evidence_refs": [],
        "boundary": "No worktree plan is prepared while the loop is blocked.",
    }


def _subagent_plan(
    cycle: dict[str, Any],
    planned_action: str,
    role: str,
    envelope: dict[str, Any],
    workflow_pattern: str,
) -> dict[str, Any]:
    return {
        "strategy": "planned_only",
        "role": _safe_summary(role, limit=80),
        "allowed_executors": list(envelope.get("allowed_executors", [])),
        "workflow_pattern": workflow_pattern,
        "prompt_seed": _safe_summary(
            f"Continue loop {cycle.get('loop_id', '')}: {planned_action} for {cycle.get('goal', {}).get('summary', '')}",
            limit=320,
        ),
        "result_contract": _subagent_result_contract(planned_action, workflow_pattern),
        "dispatched": False,
        "observed": False,
        "evidence_refs": [],
        "boundary": "OMH prepares the subagent handoff; the wrapper/runtime records dispatch evidence separately.",
    }


def _empty_subagent_plan() -> dict[str, Any]:
    return {
        "strategy": "none",
        "role": "",
        "allowed_executors": [],
        "workflow_pattern": "",
        "prompt_seed": "",
        "result_contract": {},
        "dispatched": False,
        "observed": False,
        "evidence_refs": [],
        "boundary": "No subagent plan is prepared while the loop is blocked.",
    }


def _connector_plan(connector: str, connector_action: str, planned_action: str) -> dict[str, Any]:
    if not connector:
        return {
            "strategy": "none",
            "connector": "",
            "action": "",
            "dispatched": False,
            "observed": False,
            "evidence_refs": [],
            "boundary": "No connector was requested for this tick.",
        }
    return {
        "strategy": "planned_only",
        "connector": _safe_summary(connector, limit=120),
        "action": _safe_summary(connector_action or planned_action, limit=160),
        "dispatched": False,
        "observed": False,
        "evidence_refs": [],
        "boundary": "OMH records connector intent only; connector I/O requires a separate observed wrapper action.",
    }


def _preferred_executor(envelope: dict[str, Any]) -> str:
    executors = _string_list(envelope.get("allowed_executors", []))
    if "codex" in executors:
        return "codex"
    if "claude-code" in executors:
        return "claude-code"
    return executors[0] if executors else "choose"


def _empty_executor_session(executor: str = "choose") -> dict[str, Any]:
    capability = loop_executor_capability(executor)
    return {
        "executor": capability["executor"],
        "loop_mode": capability["loop_mode"],
        "dispatch_owner": capability["dispatch_owner"],
        "dispatch_status": "not_requested",
        "session_ref": "",
        "thread_ref": "",
        "dispatch_evidence_refs": [],
        "active_attempt_id": "",
        "dispatch_attempts": [],
        "progress_evidence_refs": [],
        "progress_summary": {},
        "review_summary": {},
        "summary": "",
        "capability": capability,
        "claim_boundary": capability["claim_boundary"],
    }


def _dispatch_request(
    capability: Mapping[str, Any],
    session_ref: str,
    thread_ref: str,
    evidence_refs: Iterable[str],
    summary: str,
) -> dict[str, Any]:
    refs = _safe_list(evidence_refs, limit=320)
    return {
        "executor": str(capability["executor"]),
        "loop_mode": str(capability["loop_mode"]),
        "dispatch_owner": str(capability["dispatch_owner"]),
        "dispatch_status": "dispatched" if refs or session_ref.strip() or thread_ref.strip() else "prepared",
        "session_ref": _safe_summary(session_ref, limit=220) if session_ref.strip() else "",
        "thread_ref": _safe_summary(thread_ref, limit=220) if thread_ref.strip() else "",
        "dispatch_evidence_refs": refs,
        "summary": (
            _safe_summary(summary, limit=320)
            if summary.strip()
            else "Executor dispatch metadata recorded for this loop queue item."
        ),
    }


def _executor_session_dispatch(executor_session: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "executor": str(executor_session.get("executor", "")),
        "loop_mode": str(executor_session.get("loop_mode", "")),
        "dispatch_owner": str(executor_session.get("dispatch_owner", "")),
        "dispatch_status": str(executor_session.get("dispatch_status", "")),
        "session_ref": str(executor_session.get("session_ref", "")),
        "thread_ref": str(executor_session.get("thread_ref", "")),
        "dispatch_evidence_refs": _safe_list(
            _string_list(executor_session.get("dispatch_evidence_refs", [])), limit=320
        ),
        "summary": str(executor_session.get("summary", "")),
    }


def _new_dispatch_attempt(
    queue_id: str,
    attempt_index: int,
    dispatch: Mapping[str, Any],
) -> dict[str, Any]:
    identity = sha256_text(
        json.dumps([queue_id, attempt_index, dict(dispatch)], sort_keys=True, separators=(",", ":"))
    )[:16]
    return {
        "schema_version": LOOP_DISPATCH_ATTEMPT_SCHEMA,
        "attempt_id": f"dispatch-{attempt_index}-{identity}",
        "attempt_index": attempt_index,
        **dict(dispatch),
        "delivery_outcome": "delivery_unknown",
        "outcome_evidence_refs": [],
        "outcome_summary": "Dispatch was recorded without a confirmed delivery outcome.",
        "recorded_at": utc_now(),
    }


def _resolve_observed_dispatch_attempt(
    executor_session: Mapping[str, Any],
    requested_attempt_id: str,
    *,
    expected_executor: str = "",
) -> str:
    attempts = [entry for entry in executor_session.get("dispatch_attempts", []) if isinstance(entry, dict)]
    requested = _safe_summary(requested_attempt_id, limit=120) if requested_attempt_id.strip() else ""
    if not attempts:
        if requested:
            raise ValueError("dispatch attempt id does not exist on this loop queue item")
        return ""
    if not requested:
        if len(attempts) != 1:
            raise ValueError("dispatch attempt id is required after explicit recovery")
        requested = str(attempts[0].get("attempt_id", ""))
    attempt = next((entry for entry in attempts if entry.get("attempt_id") == requested), None)
    if attempt is None:
        raise ValueError("dispatch attempt id does not exist on this loop queue item")
    if expected_executor and attempt.get("executor") != expected_executor:
        raise ValueError(f"dispatch attempt is not owned by {expected_executor}")
    return requested


def _confirm_dispatch_attempt(
    executor_session: Mapping[str, Any],
    attempt_id: str,
    evidence_refs: Iterable[str],
) -> list[dict[str, Any]]:
    attempts = [dict(entry) for entry in executor_session.get("dispatch_attempts", []) if isinstance(entry, dict)]
    if not attempt_id:
        return attempts
    refs = _safe_list(evidence_refs, limit=320)
    for index, attempt in enumerate(attempts):
        if attempt.get("attempt_id") != attempt_id:
            continue
        attempts[index] = {
            **attempt,
            "delivery_outcome": "delivery_confirmed",
            "outcome_evidence_refs": _safe_list(
                [*_string_list(attempt.get("outcome_evidence_refs", [])), *refs],
                limit=320,
            ),
            "outcome_summary": "Executor progress or result was observed for this dispatch attempt.",
        }
        break
    return attempts


def _narration_next_message(status: str, executor_session: dict[str, Any]) -> str:
    dispatch_status = str(executor_session.get("dispatch_status", ""))
    if status == "prepared_not_observed" and dispatch_status in {"", "not_requested", "prepared"}:
        return "아직 실행 증거는 없고, 다음 단계는 선택한 코딩 에이전트에 이 큐 항목을 넘기는 거야."
    if dispatch_status == "dispatched":
        return "코딩 에이전트 세션은 기록됐고, 다음 단계는 진행 로그나 결과 evidence를 관측하는 거야."
    if dispatch_status == "progress_observed":
        return "진행은 관측됐고, 다음 단계는 검증/리뷰 evidence를 기록한 뒤 다음 사이클을 결정하는 거야."
    if status == "observed":
        return "큐 항목은 관측됐고, 다음 단계는 feedback 또는 verification artifact를 기록하는 거야."
    return "현재 루프 상태를 확인하고 다음 관측 가능한 행동을 정해야 해."


def _verification_plan(planned_action: str, workflow_pattern: str, *, is_prepared: bool) -> dict[str, Any]:
    pattern = _workflow_pattern(workflow_pattern)
    if not is_prepared:
        return {
            "schema_version": LOOP_VERIFICATION_PLAN_SCHEMA,
            "tier": "none",
            "expected_signal": "No verification is expected while this queue item is blocked or waiting.",
            "failure_action": "do_not_advance",
            "evidence_required": [],
            "stop_signal": "The blocker, permission request, or wait state is resolved.",
            "verifier_role": "",
            "claim_boundary": _runtime_claim_boundary(),
        }
    tier = "outer" if pattern in {"fan_out_synthesize", "adversarial_verification", "tournament"} else "inner"
    if tier == "outer":
        expected_signal = (
            "Verifier review, integration-style evidence, semantic review, release gate, "
            "or human judgment returns pass/fail with evidence refs."
        )
        evidence_required = ["verifier_result_ref", "checked_evidence_ref"]
        stop_signal = "The verifier or human review returns pass with evidence refs."
        verifier_role = "verifier"
    else:
        expected_signal = _INNER_TIER_EXPECTED_SIGNAL
        evidence_required = ["focused_check_ref"]
        stop_signal = "The focused check returns pass with an evidence ref."
        verifier_role = ""
    return {
        "schema_version": LOOP_VERIFICATION_PLAN_SCHEMA,
        "tier": tier,
        "expected_signal": expected_signal,
        "failure_action": "return_to_plan_or_research",
        "evidence_required": evidence_required,
        "stop_signal": stop_signal,
        "verifier_role": verifier_role,
        "claim_boundary": "Verification intent is metadata until a wrapper or operator records observed verification evidence.",
    }


def _default_subagent_role(planned_action: str) -> str:
    if planned_action == "research":
        return "researcher"
    if planned_action == "planning":
        return "planner"
    if planned_action in {"executor_handoff", "executor_dispatch", "repo_edit"}:
        return "executor"
    if planned_action in {"review_fix_loop", "ci_fix_loop"}:
        return "verifier"
    return "operator"


def _runtime_summary(cycle: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime_state(cycle.get("runtime"))
    queue = [item for item in runtime.get("queue", []) if isinstance(item, dict)]
    pending = [item for item in queue if item.get("status") == "prepared_not_observed"]
    unobserved = [item for item in queue if not (item.get("status") == "observed" and item.get("observed") is True)]
    last = queue[-1] if queue else {}
    return {
        "schema_version": LOOP_RUNTIME_SCHEMA,
        "heartbeat_count": runtime["heartbeat_count"],
        "last_tick_at": runtime["last_tick_at"],
        "last_trigger": runtime["last_trigger"],
        "last_planned_action": runtime["last_planned_action"],
        "pending_queue_count": len(pending),
        "unobserved_queue_count": len(unobserved),
        "last_queue_id": runtime["last_queue_id"],
        "last_queue_status": str(last.get("status", "")),
        "last_queue_reason": str(last.get("reason", "")),
        "blocked_queue_count": sum(1 for item in queue if item.get("status") in {"blocked", "blocked_by_permission", "blocked_by_wait"}),
        "observed_queue_count": sum(1 for item in queue if item.get("status") == "observed" and item.get("observed") is True),
        "last_stop_reason": runtime["last_stop_reason"],
        "no_progress_ticks": runtime["no_progress_ticks"],
        "no_progress_cap": LOOP_NO_PROGRESS_TICK_CAP,
        "claim_boundary": _runtime_claim_boundary(),
    }


def _loop_verification_policy() -> dict[str, Any]:
    return {
        "inner_loop_checks": [
            "syntax_or_parse_check",
            "compile_or_import_check",
            "focused_unit_test",
            "command_smoke",
            "schema_validation",
        ],
        "outer_loop_checks": [
            "integration_test",
            "semantic_review",
            "adversarial_verifier",
            "release_gate",
            "human_review",
        ],
        "verifier_policy": (
            "Keep one cheap verification lane by default. Add a verifier subagent only for high-risk changes, "
            "failed evidence, explicit review requests, or fan_out_synthesize/adversarial_verification/tournament patterns."
        ),
        "stop_signal": "A loop step stops only when its expected verification signal is observed, blocked, or explicitly deferred.",
        "claim_boundary": "Verification policy is guidance until observed evidence refs are recorded.",
    }


def _failure_mode_definitions() -> list[dict[str, str]]:
    return [
        {
            "id": "verification_gap",
            "label": "verification gap",
            "meaning": "The loop has prepared or observed work but still lacks enough verification evidence to advance safely.",
        },
        {
            "id": "comprehension_debt",
            "label": "comprehension debt",
            "meaning": "The loop is accumulating delegated or generated work faster than summaries, ownership, or review evidence can explain.",
        },
        {
            "id": "cognitive_surrender",
            "label": "cognitive surrender",
            "meaning": "The loop is broad enough that a human-owned judgment, acceptance signal, or stop condition should be refreshed.",
        },
    ]


def _failure_mode_summary(cycle: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime_state(cycle.get("runtime"))
    queue = [item for item in runtime.get("queue", []) if isinstance(item, dict)]
    feedback = _dict_value(cycle, "feedback_gate")
    envelope = _dict_value(cycle, "authority_envelope")
    modes = [
        _verification_gap_mode(cycle, queue, feedback),
        _comprehension_debt_mode(cycle, queue, feedback),
        _cognitive_surrender_mode(cycle, envelope),
    ]
    warnings = [mode for mode in modes if mode["state"] == "warning"]
    return {
        "schema_version": LOOP_FAILURE_MODE_SUMMARY_SCHEMA,
        "warnings": warnings,
        "modes": modes,
        "next_action": warnings[0]["next_action"] if warnings else "continue_with_current_loop_gate",
        "claim_boundary": "Failure modes are loop safety warnings; they are not runtime execution evidence.",
    }


def _verification_gap_mode(cycle: dict[str, Any], queue: list[dict[str, Any]], feedback: dict[str, Any]) -> dict[str, str]:
    pending = [item for item in queue if item.get("status") == "prepared_not_observed"]
    observed = [item for item in queue if item.get("status") == "observed" and item.get("observed") is True]
    if pending:
        return _failure_mode(
            "verification_gap",
            "warning",
            "A prepared queue item is waiting for observed work and verification evidence before the loop can advance.",
            "observe_runtime_queue",
        )
    if observed and not _string_list(feedback.get("observed_artifacts", [])) and cycle.get("phase") == "feedback":
        return _failure_mode(
            "verification_gap",
            "warning",
            "Observed queue work exists, but feedback has not recorded verification artifacts yet.",
            "record_feedback",
        )
    return _failure_mode("verification_gap", "clear", "No verification gap is currently visible.", "continue_loop")


def _comprehension_debt_mode(
    cycle: dict[str, Any],
    queue: list[dict[str, Any]],
    feedback: dict[str, Any],
) -> dict[str, str]:
    heartbeat_count = int(_runtime_state(cycle.get("runtime")).get("heartbeat_count", 0) or 0)
    observed_count = sum(1 for item in queue if item.get("status") == "observed" and item.get("observed") is True)
    feedback_count = len(cycle.get("cycles", []) if isinstance(cycle.get("cycles"), list) else [])
    if heartbeat_count >= 3 and observed_count >= 2 and feedback_count == 0:
        return _failure_mode(
            "comprehension_debt",
            "warning",
            "Several loop ticks or observed items exist without a feedback checkpoint that explains what changed.",
            "record_feedback",
        )
    if observed_count >= 3 and not str(feedback.get("internal_actionable_gap", "")).strip():
        return _failure_mode(
            "comprehension_debt",
            "warning",
            "Multiple observed loop items exist; refresh a concise summary, owner, and next risk before continuing.",
            "record_feedback",
        )
    return _failure_mode("comprehension_debt", "clear", "Loop context is still bounded by summaries and evidence refs.", "continue_loop")


def _cognitive_surrender_mode(cycle: dict[str, Any], envelope: dict[str, Any]) -> dict[str, str]:
    allowed = set(_string_set(envelope.get("allowed_actions", [])))
    broad_actions = {"executor_dispatch", "repo_edit", "pr_creation", "merge", "external_posting"}
    if allowed & broad_actions and not str(cycle.get("linked_goal_id", "")).strip():
        return _failure_mode(
            "cognitive_surrender",
            "warning",
            "This loop can prepare broad actions; refresh human-owned judgment or link a goal ledger before treating it as self-steering.",
            "show_loop_status",
        )
    return _failure_mode("cognitive_surrender", "clear", "Authority and stop conditions are explicit enough for the current loop state.", "continue_loop")


def _failure_mode(mode_id: str, state: str, detail: str, next_action: str) -> dict[str, str]:
    return {
        "id": mode_id,
        "state": state,
        "detail": detail,
        "next_action": next_action,
    }


def assess_loop_constraint(card: dict[str, Any]) -> dict[str, Any]:
    """Rank the constraints gating this loop from an already-built loop_status_card/v1 payload.

    Precondition: `card` is a fully-built `loop_status_card/v1` as returned by
    `build_loop_status_card`. Every top-level key this function reads is written
    unconditionally by that builder, so a missing top-level key is a programming
    error, not an input case, and is not defended against. Nested reads inside
    `runtime_summary`, `failure_mode_summary`, and `linked_goal_completion` use
    `.get()` with typed defaults, because those blocks legitimately vary: the
    linked block degrades to `{"observed": False, "reason": ...}` when no goal
    ledger is linked, and synthetic test cards build partial nested dicts.
    """
    runtime = card.get("runtime_summary", {})
    failure = card.get("failure_mode_summary", {})
    linked = card.get("linked_goal_completion", {})
    warnings = [warning for warning in failure.get("warnings", []) if isinstance(warning, dict)]
    candidates: list[dict[str, Any]] = []
    for constraint_class in LOOP_CONSTRAINT_CLASSES:
        found = _constraint_candidate(constraint_class, card, runtime, warnings, linked)
        if found is None:
            continue
        summary, evidence_source = found
        guidance = _LOOP_CONSTRAINT_GUIDANCE[constraint_class]
        candidates.append(
            {
                "rank": len(candidates) + 1,
                "constraint_class": constraint_class,
                "summary": summary,
                "evidence_source": evidence_source,
                "exploit": guidance["exploit"],
                "subordinate": guidance["subordinate"],
                "elevate": guidance["elevate"],
            }
        )
    binding = candidates[0] if candidates else None
    return {
        "schema_version": LOOP_CONSTRAINT_ASSESSMENT_SCHEMA,
        "loop_id": card["loop_id"],
        "binding_constraint": binding,
        "candidates": candidates,
        "no_binding_constraint_reason": "" if binding is not None else _NO_BINDING_CONSTRAINT_REASON,
        "next_action_relationship": LOOP_CONSTRAINT_NEXT_ACTION_RELATIONSHIP,
        "repeat_note": LOOP_CONSTRAINT_REPEAT_NOTE,
        "claim_boundary": LOOP_CONSTRAINT_ASSESSMENT_CLAIM_BOUNDARY,
    }


def _constraint_candidate(
    constraint_class: str,
    card: dict[str, Any],
    runtime: dict[str, Any],
    warnings: list[dict[str, Any]],
    linked: dict[str, Any],
) -> tuple[str, str] | None:
    """Return (summary, evidence_source) when the class fires, or None.

    Where the source carries recorded text - a failure-mode warning, a
    completion-gate entry, the unlinked fallback - the summary quotes it
    unchanged. Where the source is a bare enum or count, the summary is an
    authored per-class template interpolating only the recorded value. A list
    source contributes its FIRST entry only, with the total stated so nothing
    is hidden.
    """
    if constraint_class == "capacity_exhausted":
        wait_reason = card["wait_reason"]
        if wait_reason not in {"context_exhausted", "budget_exhausted"}:
            return None
        return (
            f"The loop recorded `wait_reason` `{wait_reason}`: no further work fits in the current context or budget.",
            "wait_reason",
        )
    if constraint_class == "permission_envelope":
        if card["wait_reason"] != "permission_required":
            return None
        blocked_actions = card["blocked_actions"]
        return (
            f"The loop recorded `wait_reason` `permission_required`; {len(blocked_actions)} action(s) "
            "are listed in `blocked_actions`.",
            "blocked_actions",
        )
    if constraint_class == "goal_status_gap":
        goal_status = str(linked.get("goal_status", ""))
        if goal_status not in {"blocked", "failed", "cancelled"}:
            return None
        return (
            f"The linked goal ledger records status `{goal_status}`, so recorded loop work cannot become goal progress.",
            "linked_goal_completion.goal_status",
        )
    if constraint_class == "blocked_queue_item":
        blocked_count = int(runtime.get("blocked_queue_count", 0) or 0)
        if blocked_count <= 0:
            return None
        return (
            f"{blocked_count} queue item(s) are recorded blocked and cannot be observed until the block clears.",
            "runtime_summary.blocked_queue_count",
        )
    if constraint_class == "observation_backlog":
        pending_count = int(runtime.get("pending_queue_count", 0) or 0)
        if pending_count <= 0:
            return None
        unobserved_count = int(runtime.get("unobserved_queue_count", 0) or 0)
        return (
            f"{pending_count} queue item(s) are `prepared_not_observed`; {unobserved_count} item(s) "
            "in total are still unobserved.",
            "runtime_summary.pending_queue_count",
        )
    if constraint_class == "external_wait":
        if card["wait_reason"] != "waiting_external_observation":
            return None
        return (
            "The loop recorded `wait_reason` `waiting_external_observation`; progress depends on an "
            "observation from outside the loop.",
            "wait_reason",
        )
    if constraint_class in {"verification_gap", "comprehension_debt", "human_judgment"}:
        warning_id = "cognitive_surrender" if constraint_class == "human_judgment" else constraint_class
        for warning in warnings:
            if warning.get("id") == warning_id:
                return str(warning.get("detail", "")), "failure_mode_summary.warnings"
        return None
    if constraint_class == "unsatisfied_required_criterion":
        missing = [entry for entry in linked.get("missing_required_criteria", []) if isinstance(entry, dict)]
        if not missing:
            return None
        first = missing[0]
        return (
            f"`{first.get('id', '')}`: {first.get('summary', '')} (first of {len(missing)} missing required criteria)",
            "linked_goal_completion.missing_required_criteria",
        )
    if constraint_class == "active_blocker":
        blockers = [entry for entry in linked.get("active_blockers", []) if isinstance(entry, dict)]
        if not blockers:
            return None
        first = blockers[0]
        return (
            f"`{first.get('id', '')}`: {first.get('summary', '')} (first of {len(blockers)} active blockers)",
            "linked_goal_completion.active_blockers",
        )
    if constraint_class == "unsatisfied_runtime_check":
        unsatisfied = [
            entry
            for entry in linked.get("linked_runtime_checks", [])
            if isinstance(entry, dict) and entry.get("satisfied") is False
        ]
        if not unsatisfied:
            return None
        first = unsatisfied[0]
        return (
            f"`{first.get('run_id', '')}`: {first.get('summary', '')} (first of {len(unsatisfied)} unsatisfied runtime checks)",
            "linked_goal_completion.linked_runtime_checks",
        )
    if constraint_class == "goal_link_missing":
        if "missing_required_criteria" in linked:
            return None
        return str(linked.get("reason", "")), "linked_goal_completion.reason"
    return None


def validate_loop_constraint_assessment(value: object) -> list[str]:
    """Field-error list, same contract as validate_loopability_assessment."""
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["constraint_assessment must be an object"]
    if value.get("schema_version") != LOOP_CONSTRAINT_ASSESSMENT_SCHEMA:
        errors.append(f"constraint_assessment.schema_version must be {LOOP_CONSTRAINT_ASSESSMENT_SCHEMA}")
    candidates = value.get("candidates")
    if not isinstance(candidates, list) or not all(isinstance(candidate, dict) for candidate in candidates):
        errors.append("constraint_assessment.candidates must be an object list")
        candidates = []
    for index, candidate in enumerate(candidates, start=1):
        if candidate.get("constraint_class") not in LOOP_CONSTRAINT_CLASSES:
            errors.append(f"constraint_assessment.candidates[{index}].constraint_class is unsupported")
        if candidate.get("rank") != index:
            errors.append(f"constraint_assessment.candidates[{index}].rank must be {index}")
    binding = value.get("binding_constraint")
    if candidates:
        if binding != candidates[0]:
            errors.append("constraint_assessment.binding_constraint must be the first ranked candidate")
    elif binding is not None:
        errors.append("constraint_assessment.binding_constraint must be null when no candidate fired")
    reason = value.get("no_binding_constraint_reason")
    if not isinstance(reason, str):
        errors.append("constraint_assessment.no_binding_constraint_reason must be a string")
    elif binding is None and not reason.strip():
        errors.append("constraint_assessment.no_binding_constraint_reason must be non-empty when nothing binds")
    elif binding is not None and reason:
        errors.append("constraint_assessment.no_binding_constraint_reason must be empty when a constraint binds")
    for key in ("claim_boundary", "repeat_note", "next_action_relationship"):
        if not isinstance(value.get(key), str) or not str(value.get(key, "")).strip():
            errors.append(f"constraint_assessment.{key} must be a non-empty string")
    return errors


def declare_sticky_rule(
    paths: OmhPaths,
    loop_id: str,
    *,
    rule_id: str,
    text: str,
    repeat_mode: str = "after_gap",
    repeat_gap: int = LOOP_STICKY_RULE_DEFAULT_GAP,
    max_repeats: int = LOOP_STICKY_RULE_DEFAULT_MAX_REPEATS,
    expected_revision: int | None = None,
    mutation_id: str | None = None,
) -> dict[str, Any]:
    """Declare (or re-declare) a sticky rule for re-attachment on this loop.

    Declaring an existing `rule_id` again updates its text and policy in
    place - `sticky_rules` is deduplicated by rule id, never a growing list
    of near-duplicate reminders - and preserves its injected_count and
    last_injected_heartbeat, so re-declaring the same rule does not reset its
    bounded repeat budget.
    """
    safe_rule_id = _storage_id(rule_id, "rule_id")
    safe_text = _safe_summary(text, limit=500)
    if not safe_text:
        raise ValueError("sticky rule text is required")
    if repeat_mode not in LOOP_STICKY_RULE_REPEAT_MODES:
        raise ValueError(f"repeat_mode must be one of {LOOP_STICKY_RULE_REPEAT_MODES}")
    if isinstance(repeat_gap, bool) or not isinstance(repeat_gap, int) or repeat_gap < 1:
        raise ValueError("repeat_gap must be a positive integer")
    if isinstance(max_repeats, bool) or not isinstance(max_repeats, int) or max_repeats < 1:
        raise ValueError("max_repeats must be a positive integer")
    if max_repeats > LOOP_STICKY_RULE_MAX_REPEATS_CEILING:
        raise ValueError(f"max_repeats must not exceed {LOOP_STICKY_RULE_MAX_REPEATS_CEILING}")
    # "once" is a repeat budget of exactly one by definition; a caller-supplied
    # max_repeats never widens it, so the mode's own name stays true.
    effective_max_repeats = LOOP_STICKY_RULE_ONCE_MAX_REPEATS if repeat_mode == "once" else max_repeats

    def mutate(cycle: dict[str, Any]) -> dict[str, Any]:
        rules = _sticky_rules_list(cycle.get("sticky_rules"))
        heartbeat_count = int(_runtime_state(cycle.get("runtime")).get("heartbeat_count", 0) or 0)
        existing = next((rule for rule in rules if rule["rule_id"] == safe_rule_id), None)
        if existing is not None:
            existing["text"] = safe_text
            existing["repeat_mode"] = repeat_mode
            existing["repeat_gap"] = repeat_gap
            existing["max_repeats"] = effective_max_repeats
        else:
            rules.append(
                {
                    "schema_version": LOOP_STICKY_RULE_SCHEMA,
                    "rule_id": safe_rule_id,
                    "text": safe_text,
                    "repeat_mode": repeat_mode,
                    "repeat_gap": repeat_gap,
                    "max_repeats": effective_max_repeats,
                    "declared_at_heartbeat": heartbeat_count,
                    "injected_count": 0,
                    "last_injected_heartbeat": None,
                }
            )
        cycle["sticky_rules"] = rules
        cycle["updated_at"] = utc_now()
        return cycle

    return _guarded_cycle_update(
        paths,
        loop_id,
        mutate,
        operation="declare_sticky_rule",
        expected_revision=expected_revision,
        mutation_id=mutation_id,
        mutation_digest=_mutation_digest(
            "declare_sticky_rule", safe_rule_id, safe_text, repeat_mode, repeat_gap, effective_max_repeats
        ),
    )


def _sticky_rules_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(rule) for rule in value if isinstance(rule, dict)]


def _sticky_rule_due(rule: dict[str, Any], heartbeat_count: int) -> bool:
    """Whether `rule` is due for attachment at `heartbeat_count` ticks.

    Bounded by max_repeats regardless of mode. "once" fires only before its
    first injection. "after_gap" fires on the first tick after declaration
    (no prior injection to measure a gap from), then again only once
    `heartbeat_count - last_injected_heartbeat >= repeat_gap`.
    """
    injected_count = int(rule.get("injected_count", 0) or 0)
    max_repeats = int(rule.get("max_repeats", LOOP_STICKY_RULE_DEFAULT_MAX_REPEATS) or 0)
    if injected_count >= max_repeats:
        return False
    if rule.get("repeat_mode") == "once":
        return injected_count == 0
    last_injected = rule.get("last_injected_heartbeat")
    if last_injected is None:
        return True
    gap = int(rule.get("repeat_gap", LOOP_STICKY_RULE_DEFAULT_GAP) or LOOP_STICKY_RULE_DEFAULT_GAP)
    return heartbeat_count - int(last_injected) >= gap


def _advance_sticky_rule_attachment(rules: list[dict[str, Any]], heartbeat_count: int) -> dict[str, Any]:
    """Mark every due rule injected at `heartbeat_count` and build this tick's attachment.

    Mutates each due rule in `rules` in place (injected_count, last_injected_heartbeat)
    so the caller's own `cycle["sticky_rules"]` write carries the advanced state. Rule
    `text` is copied verbatim from its declaration - never reformatted - so the
    re-attached block stays byte-identical across repeats and is cache-friendly.
    """
    due: list[dict[str, Any]] = []
    for rule in rules:
        if not _sticky_rule_due(rule, heartbeat_count):
            continue
        rule["injected_count"] = int(rule.get("injected_count", 0) or 0) + 1
        rule["last_injected_heartbeat"] = heartbeat_count
        due.append(rule)
    due.sort(key=lambda rule: str(rule["rule_id"]))
    return {
        "schema_version": LOOP_STICKY_RULE_ATTACHMENT_SCHEMA,
        "heartbeat_count": heartbeat_count,
        "rules": [
            {
                "rule_id": str(rule["rule_id"]),
                "text": str(rule["text"]),
                "repeat_mode": str(rule["repeat_mode"]),
                "injected_count": int(rule["injected_count"]),
                "max_repeats": int(rule["max_repeats"]),
            }
            for rule in due
        ],
        "claim_boundary": LOOP_STICKY_RULE_CLAIM_BOUNDARY,
    }


def _empty_sticky_rule_attachment() -> dict[str, Any]:
    return {
        "schema_version": LOOP_STICKY_RULE_ATTACHMENT_SCHEMA,
        "heartbeat_count": 0,
        "rules": [],
        "claim_boundary": LOOP_STICKY_RULE_CLAIM_BOUNDARY,
    }


def validate_loop_sticky_rule(value: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["sticky_rule must be an object"]
    if value.get("schema_version") != LOOP_STICKY_RULE_SCHEMA:
        errors.append(f"sticky_rule.schema_version must be {LOOP_STICKY_RULE_SCHEMA}")
    rule_id = value.get("rule_id")
    if not isinstance(rule_id, str) or not STORAGE_ID_RE.fullmatch(rule_id):
        errors.append("sticky_rule.rule_id must be a storage id")
    if not isinstance(value.get("text"), str) or not str(value.get("text", "")).strip():
        errors.append("sticky_rule.text must be a non-empty string")
    if value.get("repeat_mode") not in LOOP_STICKY_RULE_REPEAT_MODES:
        errors.append("sticky_rule.repeat_mode is unsupported")
    for key in ("repeat_gap", "max_repeats", "injected_count"):
        count = value.get(key)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            errors.append(f"sticky_rule.{key} must be a non-negative integer")
    max_repeats = value.get("max_repeats")
    if value.get("repeat_mode") == "once" and max_repeats != LOOP_STICKY_RULE_ONCE_MAX_REPEATS:
        errors.append(f"sticky_rule.max_repeats must be {LOOP_STICKY_RULE_ONCE_MAX_REPEATS} when repeat_mode is once")
    injected_count = value.get("injected_count")
    if (
        isinstance(injected_count, int)
        and not isinstance(injected_count, bool)
        and isinstance(max_repeats, int)
        and not isinstance(max_repeats, bool)
        and injected_count > max_repeats
    ):
        errors.append("sticky_rule.injected_count must not exceed max_repeats")
    declared_at = value.get("declared_at_heartbeat")
    if isinstance(declared_at, bool) or not isinstance(declared_at, int) or declared_at < 0:
        errors.append("sticky_rule.declared_at_heartbeat must be a non-negative integer")
    last_injected = value.get("last_injected_heartbeat")
    if last_injected is not None and (isinstance(last_injected, bool) or not isinstance(last_injected, int) or last_injected < 0):
        errors.append("sticky_rule.last_injected_heartbeat must be null or a non-negative integer")
    return errors


def validate_loop_sticky_rule_attachment(value: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["sticky_rule_attachment must be an object"]
    if value.get("schema_version") != LOOP_STICKY_RULE_ATTACHMENT_SCHEMA:
        errors.append(f"sticky_rule_attachment.schema_version must be {LOOP_STICKY_RULE_ATTACHMENT_SCHEMA}")
    heartbeat_count = value.get("heartbeat_count")
    if isinstance(heartbeat_count, bool) or not isinstance(heartbeat_count, int) or heartbeat_count < 0:
        errors.append("sticky_rule_attachment.heartbeat_count must be a non-negative integer")
    rules = value.get("rules")
    if not isinstance(rules, list):
        errors.append("sticky_rule_attachment.rules must be a list")
        rules = []
    seen_ids: set[str] = set()
    previous_id = ""
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"sticky_rule_attachment.rules[{index}] must be an object")
            continue
        rule_id = str(rule.get("rule_id", ""))
        if not rule_id:
            errors.append(f"sticky_rule_attachment.rules[{index}].rule_id must be a non-empty string")
        elif rule_id in seen_ids:
            errors.append(f"sticky_rule_attachment.rules[{index}].rule_id duplicates an earlier entry")
        else:
            seen_ids.add(rule_id)
        if rule_id < previous_id:
            errors.append(f"sticky_rule_attachment.rules[{index}] is out of rule_id order")
        previous_id = rule_id
        if not isinstance(rule.get("text"), str) or not str(rule.get("text", "")).strip():
            errors.append(f"sticky_rule_attachment.rules[{index}].text must be a non-empty string")
        if rule.get("repeat_mode") not in LOOP_STICKY_RULE_REPEAT_MODES:
            errors.append(f"sticky_rule_attachment.rules[{index}].repeat_mode is unsupported")
        for key in ("injected_count", "max_repeats"):
            count = rule.get(key)
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                errors.append(f"sticky_rule_attachment.rules[{index}].{key} must be a positive integer")
        injected_count = rule.get("injected_count")
        max_repeats = rule.get("max_repeats")
        if (
            isinstance(injected_count, int)
            and not isinstance(injected_count, bool)
            and isinstance(max_repeats, int)
            and not isinstance(max_repeats, bool)
            and injected_count > max_repeats
        ):
            errors.append(f"sticky_rule_attachment.rules[{index}].injected_count must not exceed max_repeats")
    if not isinstance(value.get("claim_boundary"), str) or not str(value.get("claim_boundary", "")).strip():
        errors.append("sticky_rule_attachment.claim_boundary must be a non-empty string")
    return errors


def _small_loop_guidance() -> dict[str, Any]:
    return {
        "schema_version": LOOP_SMALL_LOOP_GUIDANCE_SCHEMA,
        "principles": [
            {
                "id": "test_as_stop_signal",
                "label": "test as stop signal",
                "guidance": "Name the cheapest check that decides whether this step is done before the loop starts.",
            },
            {
                "id": "plan_execute_verify",
                "label": "plan -> execute -> verify",
                "guidance": "Keep each cycle shaped as one planned step, one execution or handoff step, and one verification signal.",
            },
            {
                "id": "one_task_at_a_time",
                "label": "one task at a time",
                "guidance": "Queue one concrete task per tick so failures can be traced and repaired without losing the goal.",
            },
        ],
        "claim_boundary": "Small-loop guidance is a Hermes-facing operating recipe, not proof that work ran.",
    }


def _permission_profile_option(profile: str) -> dict[str, Any]:
    allowed = sorted(_PROFILE_ALLOWED_ACTIONS[profile])
    descriptions = {
        "observe_only": "Research and plan only; no executor/runtime dispatch, repo edits, PRs, merge, or publishing.",
        "handoff_only": "Prepare research, planning, ultragoal, handoff, and external-posting drafts without observed execution claims.",
        "execute_with_gates": "Allow executor/runtime dispatch, repo edits, PRs, review, CI, and release-note work while merge and external posting stay gated.",
        "full_loop": "Allow the broadest local loop path while still requiring observed evidence and explicit external-production authority.",
    }
    return {
        "id": profile,
        "label": profile.replace("_", " "),
        "description": descriptions.get(profile, ""),
        "allowed_action_count": len(allowed),
        "allowed_actions": allowed,
    }


def _queue_item_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "queue_id": str(item.get("queue_id", "")),
        "created_at": str(item.get("created_at", "")),
        "trigger": str(item.get("trigger", "")),
        "cadence": str(item.get("cadence", "")),
        "planned_action": str(item.get("planned_action", "")),
        "workflow_pattern": str(item.get("workflow_pattern", "")),
        "pipeline_step": str(item.get("pipeline_step", "")),
        "phase": str(item.get("phase", "")),
        "status": str(item.get("status", "")),
        "reason": str(item.get("reason", "")),
        "observed": bool(item.get("observed", False)),
        "observed_evidence_refs": _string_list(item.get("observed_evidence_refs", [])),
        "blocker_reason": str(item.get("blocker_reason", "")),
        "worktree_strategy": str(_dict_value(item, "worktree_plan").get("strategy", "")),
        "subagent_strategy": str(_dict_value(item, "subagent_plan").get("strategy", "")),
        "connector_strategy": str(_dict_value(item, "connector_plan").get("strategy", "")),
        "claim_boundary": str(item.get("claim_boundary", _runtime_claim_boundary())),
    }


def _queue_item_ref(cycle: dict[str, Any], queue_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    safe_queue_id = _storage_id(queue_id, "queue_id")
    runtime = _runtime_state(cycle.get("runtime"))
    queue = runtime.get("queue", [])
    for item in queue:
        if isinstance(item, dict) and str(item.get("queue_id", "")) == safe_queue_id:
            return runtime, item
    raise ValueError(f"loop queue item not found: {safe_queue_id}")


def _queue_handoff_text(cycle: dict[str, Any], item: dict[str, Any]) -> str:
    goal = _dict_value(cycle, "goal")
    worktree = _dict_value(item, "worktree_plan")
    subagent = _dict_value(item, "subagent_plan")
    connector = _dict_value(item, "connector_plan")
    lines = [
        f"Continue OMH loop `{cycle.get('loop_id', '')}`.",
        f"Goal: {goal.get('summary', '')}",
        f"Planned action: {item.get('planned_action', '')}",
        f"Workflow pattern: {item.get('workflow_pattern', 'single_step')}",
        f"Pipeline step: {_queue_item_pipeline_step(item)}",
        f"Phase: {item.get('phase', '')}",
        "",
        "Boundary:",
        _runtime_claim_boundary(),
    ]
    if worktree.get("strategy") != "none":
        lines.extend(
            [
                "",
                "Worktree plan:",
                f"- Path hint: {worktree.get('path_hint', '')}",
                f"- Branch hint: {worktree.get('branch_hint', '')}",
            ]
        )
    if subagent.get("strategy") != "none":
        lines.extend(
            [
                "",
                "Subagent plan:",
                f"- Role: {subagent.get('role', '')}",
                f"- Prompt seed: {subagent.get('prompt_seed', '')}",
                "- Result contract: return status, summary, evidence_refs, and next_actions; reference large outputs by path, hash, or evidence ref instead of pasting full context.",
            ]
        )
    if connector.get("strategy") != "none":
        lines.extend(
            [
                "",
                "Connector intent:",
                f"- Connector: {connector.get('connector', '')}",
                f"- Action: {connector.get('action', '')}",
            ]
        )
    verification = _dict_value(item, "verification_plan")
    if verification:
        lines.extend(
            [
                "",
                "Verification plan:",
                f"- Tier: {verification.get('tier', '')}",
                f"- Expected signal: {verification.get('expected_signal', '')}",
                f"- Failure action: {verification.get('failure_action', '')}",
                f"- Stop signal: {verification.get('stop_signal', '')}",
            ]
        )
    lines.extend(
        [
            "",
            "After an authorized wrapper or operator observes this work, record evidence with the loop queue observation contract. If it cannot proceed, block the queue item with a reason.",
        ]
    )
    return "\n".join(lines)


def _mark_queue_plans_observed(
    item: dict[str, Any],
    *,
    worktree_evidence_refs: list[str],
    subagent_evidence_refs: list[str],
    connector_evidence_refs: list[str],
) -> None:
    worktree = _dict_value(item, "worktree_plan")
    if worktree.get("strategy") != "none" and worktree_evidence_refs:
        worktree["created"] = True
        worktree["observed"] = True
        worktree["evidence_refs"] = list(worktree_evidence_refs)
    subagent = _dict_value(item, "subagent_plan")
    if subagent.get("strategy") != "none" and subagent_evidence_refs:
        subagent["dispatched"] = True
        subagent["observed"] = True
        subagent["evidence_refs"] = list(subagent_evidence_refs)
    connector = _dict_value(item, "connector_plan")
    if connector.get("strategy") != "none" and connector_evidence_refs:
        connector["dispatched"] = True
        connector["observed"] = True
        connector["evidence_refs"] = list(connector_evidence_refs)


def _validate_typed_plan_observation(
    errors: list[str],
    index: int,
    key: str,
    plan: dict[str, Any],
    *,
    primary_flag: str,
) -> None:
    refs = _string_list(plan.get("evidence_refs", []))
    if plan.get("strategy") == "none":
        if plan.get(primary_flag) is not False:
            errors.append(f"runtime.queue[{index}].{key}.{primary_flag} must be false when strategy is none")
        if plan.get("observed") is not False:
            errors.append(f"runtime.queue[{index}].{key}.observed must be false when strategy is none")
        if refs:
            errors.append(f"runtime.queue[{index}].{key}.evidence_refs must be empty when strategy is none")
        return
    primary_observed = plan.get(primary_flag) is True
    observed = plan.get("observed") is True
    if primary_observed != observed:
        errors.append(f"runtime.queue[{index}].{key}.{primary_flag} and observed must change together")
    if primary_observed or observed:
        if not refs:
            errors.append(f"runtime.queue[{index}].{key}.evidence_refs must include at least one typed evidence ref when observed")
        if plan.get(primary_flag) is not True:
            errors.append(f"runtime.queue[{index}].{key}.{primary_flag} must be true when typed evidence is observed")
        if plan.get("observed") is not True:
            errors.append(f"runtime.queue[{index}].{key}.observed must be true when typed evidence is observed")


def _validate_unobserved_plan(
    errors: list[str],
    index: int,
    key: str,
    plan: dict[str, Any],
    *,
    primary_flag: str,
) -> None:
    if plan.get(primary_flag) is not False:
        errors.append(f"runtime.queue[{index}].{key}.{primary_flag} must be false before observation")
    if plan.get("observed") is not False:
        errors.append(f"runtime.queue[{index}].{key}.observed must be false before observation")
    if _string_list(plan.get("evidence_refs", [])):
        errors.append(f"runtime.queue[{index}].{key}.evidence_refs must be empty before observation")


def _validate_runtime(runtime: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(runtime, dict):
        return ["runtime must be an object"]
    if runtime.get("schema_version") != LOOP_RUNTIME_SCHEMA:
        errors.append(f"runtime.schema_version must be {LOOP_RUNTIME_SCHEMA}")
    for key in ("heartbeat_count", "ledger_entry_count", "no_progress_ticks"):
        count = runtime.get(key)
        if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
            errors.append(f"runtime.{key} must be a non-negative integer")
    last_stop_reason = runtime.get("last_stop_reason")
    if last_stop_reason is not None and last_stop_reason not in set(LOOP_STOP_REASONS) | {"none", ""}:
        errors.append("runtime.last_stop_reason is unsupported")
    stop_ladder = runtime.get("stop_ladder")
    if stop_ladder is not None:
        errors.extend(f"runtime.{error}" for error in validate_loop_stop_ladder(stop_ladder))
    queue = runtime.get("queue", [])
    if not isinstance(queue, list):
        errors.append("runtime.queue must be a list")
        return errors
    allowed_runtime_actions = set(LOOP_ACTIONS) | set(LOOP_CONTROL_ACTIONS)
    for index, item in enumerate(queue):
        if not isinstance(item, dict):
            errors.append(f"runtime.queue[{index}] must be an object")
            continue
        if item.get("schema_version") != LOOP_QUEUE_ITEM_SCHEMA:
            errors.append(f"runtime.queue[{index}].schema_version must be {LOOP_QUEUE_ITEM_SCHEMA}")
        if item.get("status") not in LOOP_QUEUE_STATUSES:
            errors.append(f"runtime.queue[{index}].status is unsupported")
        if item.get("planned_action") not in allowed_runtime_actions:
            errors.append(f"runtime.queue[{index}].planned_action is unsupported")
        source_generation = item.get("source_phase_generation")
        if source_generation is not None and (
            isinstance(source_generation, bool)
            or not isinstance(source_generation, int)
            or source_generation < 0
        ):
            errors.append(
                f"runtime.queue[{index}].source_phase_generation must be a non-negative integer"
            )
        authority_digest = item.get("source_authority_sha256")
        if authority_digest is not None and (
            not isinstance(authority_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", authority_digest) is None
        ):
            errors.append(
                f"runtime.queue[{index}].source_authority_sha256 must be a lowercase 64-hex digest"
            )
        pattern = str(item.get("workflow_pattern", ""))
        if pattern and pattern not in LOOP_WORKFLOW_PATTERNS:
            errors.append(f"runtime.queue[{index}].workflow_pattern is unsupported")
        pipeline_step = str(item.get("pipeline_step", ""))
        if pipeline_step and pipeline_step not in LOOP_PIPELINE_STEPS:
            errors.append(f"runtime.queue[{index}].pipeline_step is unsupported")
        engineering = item.get("loop_engineering")
        if engineering is not None:
            if not isinstance(engineering, dict):
                errors.append(f"runtime.queue[{index}].loop_engineering must be an object")
            elif engineering.get("schema_version") != LOOP_ENGINEERING_SCHEMA:
                errors.append(f"runtime.queue[{index}].loop_engineering.schema_version must be {LOOP_ENGINEERING_SCHEMA}")
        plans: dict[str, dict[str, Any]] = {}
        for key in ("worktree_plan", "subagent_plan", "connector_plan"):
            plan = item.get(key)
            if not isinstance(plan, dict):
                errors.append(f"runtime.queue[{index}].{key} must be an object")
                continue
            plans[key] = plan
            if key == "subagent_plan" and plan.get("strategy") != "none":
                contract = plan.get("result_contract")
                if not isinstance(contract, dict):
                    errors.append(f"runtime.queue[{index}].subagent_plan.result_contract must be an object")
                elif contract.get("schema_version") != LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA:
                    errors.append(
                        f"runtime.queue[{index}].subagent_plan.result_contract.schema_version must be {LOOP_SUBAGENT_RESULT_CONTRACT_SCHEMA}"
                    )
        verification_plan = item.get("verification_plan")
        if verification_plan is not None:
            _validate_verification_plan(errors, index, verification_plan)
        executor_session = item.get("executor_session")
        if executor_session is not None:
            _validate_executor_dispatch_session(errors, index, item, executor_session)
        if item.get("status") == "observed":
            if item.get("observed") is not True:
                errors.append(f"runtime.queue[{index}].observed must be true when status is observed")
            evidence_refs = item.get("observed_evidence_refs")
            if not isinstance(evidence_refs, list) or not evidence_refs or not all(str(ref).strip() for ref in evidence_refs):
                errors.append(f"runtime.queue[{index}].observed_evidence_refs must include at least one evidence ref when observed")
            worktree_plan = plans.get("worktree_plan", {})
            _validate_typed_plan_observation(errors, index, "worktree_plan", worktree_plan, primary_flag="created")
            subagent_plan = plans.get("subagent_plan", {})
            _validate_typed_plan_observation(errors, index, "subagent_plan", subagent_plan, primary_flag="dispatched")
            connector_plan = plans.get("connector_plan", {})
            _validate_typed_plan_observation(errors, index, "connector_plan", connector_plan, primary_flag="dispatched")
        elif item.get("status") == "blocked":
            if not str(item.get("blocker_reason", "")).strip():
                errors.append(f"runtime.queue[{index}].blocker_reason is required when status is blocked")
            if item.get("observed") is not False:
                errors.append(f"runtime.queue[{index}].observed must be false unless status is observed")
            _validate_unobserved_plan(errors, index, "worktree_plan", plans.get("worktree_plan", {}), primary_flag="created")
            _validate_unobserved_plan(errors, index, "subagent_plan", plans.get("subagent_plan", {}), primary_flag="dispatched")
            _validate_unobserved_plan(errors, index, "connector_plan", plans.get("connector_plan", {}), primary_flag="dispatched")
        else:
            if item.get("observed") is not False:
                errors.append(f"runtime.queue[{index}].observed must be false unless status is observed")
            _validate_unobserved_plan(errors, index, "worktree_plan", plans.get("worktree_plan", {}), primary_flag="created")
            _validate_unobserved_plan(errors, index, "subagent_plan", plans.get("subagent_plan", {}), primary_flag="dispatched")
            _validate_unobserved_plan(errors, index, "connector_plan", plans.get("connector_plan", {}), primary_flag="dispatched")
        if item.get("status") in {"blocked_by_permission", "blocked_by_wait"}:
            for key, plan in plans.items():
                if plan.get("strategy") != "none":
                    errors.append(f"runtime.queue[{index}].{key}.strategy must be none while blocked")
    return errors


def _validate_executor_dispatch_session(
    errors: list[str],
    index: int,
    queue_item: Mapping[str, Any],
    value: object,
) -> None:
    prefix = f"runtime.queue[{index}].executor_session"
    if not isinstance(value, dict):
        errors.append(f"{prefix} must be an object")
        return
    if "dispatch_attempts" not in value:
        return
    attempts = value.get("dispatch_attempts")
    if not isinstance(attempts, list):
        errors.append(f"{prefix}.dispatch_attempts must be a list")
        return
    active_attempt_id = str(value.get("active_attempt_id", ""))
    if not attempts:
        if active_attempt_id:
            errors.append(f"{prefix}.active_attempt_id must be empty without dispatch attempts")
        if value.get("dispatch_status") == "dispatched":
            errors.append(f"{prefix}.dispatch_attempts must record dispatched executor metadata")
        return

    seen_attempt_ids: set[str] = set()
    attempts_by_id: dict[str, Mapping[str, Any]] = {}
    for attempt_index, attempt in enumerate(attempts, start=1):
        attempt_prefix = f"{prefix}.dispatch_attempts[{attempt_index - 1}]"
        if not isinstance(attempt, dict):
            errors.append(f"{attempt_prefix} must be an object")
            continue
        if attempt.get("schema_version") != LOOP_DISPATCH_ATTEMPT_SCHEMA:
            errors.append(f"{attempt_prefix}.schema_version must be {LOOP_DISPATCH_ATTEMPT_SCHEMA}")
        attempt_id = str(attempt.get("attempt_id", ""))
        if not attempt_id:
            errors.append(f"{attempt_prefix}.attempt_id is required")
        elif attempt_id in seen_attempt_ids:
            errors.append(f"{attempt_prefix}.attempt_id duplicates an earlier entry")
        else:
            seen_attempt_ids.add(attempt_id)
            attempts_by_id[attempt_id] = attempt
        if attempt.get("attempt_index") != attempt_index:
            errors.append(f"{attempt_prefix}.attempt_index must preserve ordered attempt history")
        if attempt.get("dispatch_status") != "dispatched":
            errors.append(f"{attempt_prefix}.dispatch_status must be dispatched")
        dispatch_refs = attempt.get("dispatch_evidence_refs")
        if not isinstance(dispatch_refs, list) or not all(str(ref).strip() for ref in dispatch_refs):
            errors.append(f"{attempt_prefix}.dispatch_evidence_refs must be a string list")
        if not dispatch_refs and not str(attempt.get("session_ref", "")).strip() and not str(attempt.get("thread_ref", "")).strip():
            errors.append(f"{attempt_prefix} must include dispatch identity or evidence")
        outcome = attempt.get("delivery_outcome")
        if outcome not in {"delivery_unknown", "delivery_confirmed", "delivery_failed"}:
            errors.append(f"{attempt_prefix}.delivery_outcome is unsupported")
        outcome_refs = attempt.get("outcome_evidence_refs")
        if not isinstance(outcome_refs, list) or not all(str(ref).strip() for ref in outcome_refs):
            errors.append(f"{attempt_prefix}.outcome_evidence_refs must be a string list")
        elif outcome in {"delivery_confirmed", "delivery_failed"} and not outcome_refs:
            errors.append(f"{attempt_prefix}.outcome_evidence_refs are required for a conclusive outcome")

    active_attempt = attempts_by_id.get(active_attempt_id)
    if active_attempt is None:
        errors.append(f"{prefix}.active_attempt_id must identify a recorded dispatch attempt")
        return
    if attempts and active_attempt_id != str(attempts[-1].get("attempt_id", "")):
        errors.append(f"{prefix}.active_attempt_id must identify the latest dispatch attempt")
    if value.get("dispatch_status") not in {"dispatched", "progress_observed"}:
        errors.append(f"{prefix}.dispatch_status must reflect recorded dispatch attempts")
    for key in (
        "executor",
        "loop_mode",
        "dispatch_owner",
        "session_ref",
        "thread_ref",
        "dispatch_evidence_refs",
    ):
        if value.get(key) != active_attempt.get(key):
            errors.append(f"{prefix}.{key} must match the active dispatch attempt")
    observed_attempt_id = str(queue_item.get("observed_dispatch_attempt_id", ""))
    if queue_item.get("status") == "observed":
        observed_attempt = attempts_by_id.get(observed_attempt_id)
        if observed_attempt is None:
            errors.append(
                f"runtime.queue[{index}].observed_dispatch_attempt_id must identify a recorded dispatch attempt"
            )
        elif observed_attempt.get("delivery_outcome") != "delivery_confirmed":
            errors.append(
                f"runtime.queue[{index}].observed_dispatch_attempt_id must identify a confirmed dispatch attempt"
            )
    elif observed_attempt_id:
        errors.append(f"runtime.queue[{index}].observed_dispatch_attempt_id requires observed queue status")


def _validate_verification_plan(errors: list[str], index: int, value: object) -> None:
    if not isinstance(value, dict):
        errors.append(f"runtime.queue[{index}].verification_plan must be an object")
        return
    if value.get("schema_version") != LOOP_VERIFICATION_PLAN_SCHEMA:
        errors.append(f"runtime.queue[{index}].verification_plan.schema_version must be {LOOP_VERIFICATION_PLAN_SCHEMA}")
    tier = str(value.get("tier", ""))
    if tier not in LOOP_VERIFICATION_TIERS:
        errors.append(f"runtime.queue[{index}].verification_plan.tier is unsupported")
    evidence = value.get("evidence_required")
    if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
        errors.append(f"runtime.queue[{index}].verification_plan.evidence_required must be a string list")
    for key in ("expected_signal", "failure_action", "stop_signal", "claim_boundary"):
        if not isinstance(value.get(key), str) or not str(value.get(key, "")).strip():
            errors.append(f"runtime.queue[{index}].verification_plan.{key} must be a non-empty string")


def _runtime_claim_boundary() -> str:
    return (
        "A loop runtime tick prepares local orchestration work only. It is not worktree creation, "
        "subagent dispatch, connector I/O, implementation, review, CI, merge, publication, or goal completion evidence."
    )


def _dict_value(value: dict[str, Any], key: str) -> dict[str, Any]:
    nested = value.get(key)
    return nested if isinstance(nested, dict) else {}


def _normalize_permission_state(cycle: dict[str, Any]) -> None:
    envelope = _dict_value(cycle, "authority_envelope")
    allowed_actions = envelope.get("allowed_actions", [])
    if not isinstance(allowed_actions, list) or not allowed_actions:
        if cycle.get("phase") != "waiting":
            set_loop_phase(
                cycle,
                to_phase="waiting",
                transition_kind="permission_wait",
                cause="authority_envelope",
                source_ref=f"authority-{cycle.get('loop_id', 'loop')}",
                observed_at=utc_now(),
            )
        cycle["wait_reason"] = "permission_required"
        cycle["next_action"] = "request_permission"
        return
    if cycle.get("wait_reason") == "permission_required":
        cycle["wait_reason"] = "none"
        if cycle.get("phase") == "waiting":
            set_loop_phase(
                cycle,
                to_phase="feedback" if cycle.get("cycles") else "interview",
                transition_kind="permission_resume",
                cause="authority_envelope",
                source_ref=f"authority-{cycle.get('loop_id', 'loop')}",
                observed_at=utc_now(),
            )
        if cycle.get("next_action") in {"", "request_permission"}:
            cycle["next_action"] = "continue_loop"


def _next_action(cycle: dict[str, Any]) -> str:
    wait_reason = str(cycle.get("wait_reason", "none"))
    if wait_reason == "waiting_external_observation":
        return "record_external_wait"
    if wait_reason in {"context_exhausted", "budget_exhausted"}:
        return "record_checkpoint"
    if wait_reason == "permission_required":
        return "request_permission"
    explicit = str(cycle.get("next_action", ""))
    if explicit:
        return explicit
    if _dict_value(cycle, "feedback_gate").get("clear"):
        return "continue_loop"
    return "show_loop_status"


def _completion_claim_allowed(linked_gate: dict[str, Any] | None) -> bool:
    return bool(linked_gate and linked_gate.get("ready") is True)


def _authority_summary(envelope: dict[str, Any]) -> str:
    allowed = list(envelope.get("allowed_actions", []))
    blocked = list(envelope.get("blocked_actions", []))
    return (
        f"Profile {envelope.get('permission_profile', 'custom')} allows {len(allowed)} loop actions "
        f"and keeps {len(blocked)} actions behind explicit approval."
    )


def _safe_status_copy(cycle: dict[str, Any], envelope: dict[str, Any]) -> dict[str, str]:
    phase = str(cycle.get("phase", "interview"))
    wait_reason = str(cycle.get("wait_reason", "none"))
    assessment = _loopability_for_cycle(cycle)
    loopability = str(assessment.get("loopability", ""))
    if wait_reason == "waiting_external_observation":
        next_step = "Record external evidence when it arrives; continue internal work only when a new gap is available."
    elif wait_reason in {"context_exhausted", "budget_exhausted"}:
        next_step = "Checkpoint this loop and resume from the recorded status when context or budget is available."
    elif cycle.get("next_action") == "observe_runtime_queue":
        next_step = "Review the prepared runtime queue item, then record observed worktree, subagent, connector, or executor evidence separately."
    elif loopability == "direct_task":
        next_step = "This looks like a direct task; use a single delivery workflow unless the user wants repeated discovery."
    elif loopability == "needs_reframe":
        next_step = "Treat the request as a north star, then confirm a bounded arena, observable problem, and next verification before cycling."
    elif "executor_dispatch" in envelope.get("allowed_actions", []):
        next_step = "Continue the next research, plan, handoff, or gated executor step within the authority envelope."
    else:
        next_step = "Prepare the next research, plan, or handoff artifact without claiming execution."
    return {
        "headline": f"Loop `{cycle.get('loop_id', '')}` is in `{phase}`.",
        "next_step": next_step,
        "boundary": _claim_boundary(),
    }


def _claim_boundary() -> str:
    return (
        "A loop cycle is orchestration state only. Goal completion still requires goal_ledger/v1 "
        "completion evidence, and prepared handoffs are not executor execution."
    )
