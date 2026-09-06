from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Iterable

from ..hashutil import sha256_text
from ..local_store import ensure_dir, read_json_object, utc_now
from ..quality.completion_integrity import classify_completion_integrity
from ..system.record_revision import (
    DuplicateMutationReplay,
    guarded_record_update,
    require_not_terminal,
    revision_field_errors,
)
from ..paths import OmhPaths
from ..runtime.artifacts import summarize_delegated_coding_status
from ..wrapper.message_gate import (
    RENDER_PROFILE_LIMITED_MARKDOWN,
    build_message_gate,
    render_message_gate_lines,
)


GOAL_LEDGER_SCHEMA = "goal_ledger/v1"
GOAL_COMPLETION_GATE_SCHEMA = "goal_completion_gate/v1"
GOAL_CONTINUATION_SCHEMA = "goal_continuation/v1"
GOAL_STATUS_CARD_SCHEMA = "goal_status_card/v1"

GOAL_STATUSES = {"active", "blocked", "failed", "complete", "cancelled"}
# `failed` is terminal alongside `complete` and `cancelled`: it is a negative
# but CONCLUSIVE verdict on the objective itself (the target does not exist,
# the request is refused by policy, the acceptance criteria are infeasible as
# specified), reached via `fail_goal_ledger`, and a retry cannot answer the
# same question differently. It is distinct from `blocked`, which stays
# non-terminal on purpose: a blocker is recoverable, and clearing it is
# exactly what further checkpoints on the goal are for.
GOAL_TERMINAL_STATUSES = ("complete", "cancelled", "failed")
# Closed reasons a failure verdict may cite. Required on every call to
# `fail_goal_ledger`, mirroring how `record_goal_blocker` requires a summary --
# a negative-conclusive verdict earns no less structure than a recoverable one.
GOAL_FAILURE_REASON_CODES = (
    "target_not_found",
    "infeasible_as_specified",
    "refused_by_policy",
    "superseded_by_existing_work",
    "other_declared",
)
CRITERION_STATUSES = {"pending", "satisfied"}
CHECKPOINT_STATUSES = {"pending", "in_progress", "done", "blocked", "failed"}
BLOCKER_STATUSES = {"active", "resolved"}
QUALITY_GATE_STATUSES = {"pending", "passed", "failed", "blocked"}
STORAGE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
RUNTIME_COMPLETION_ACTIONS = {"report_completion_with_evidence", "report_merge_ready", "report_merged"}


MERGE_OBLIGATION_ACTIONS = ("merge", "deploy")
MERGE_OBLIGATION_CRITERION_IDS = {"merge": "AC-MERGE", "deploy": "AC-DEPLOY"}


def merge_obligation_criterion(obligation: str, ref: str = "") -> dict[str, Any]:
    """A REQUIRED acceptance criterion for a post-verification merge/deploy.

    The obligation is met only when the merge (or deploy) is *observed* through
    an external-effect receipt -- a delegated subtask completing is not the
    parent obligation being met. The criterion is required and carries no
    evidence, so a fresh ledger stays not-ready until a checkpoint satisfies it
    with observed evidence; the goal ledger's completion-integrity classifier
    then refuses a hand-satisfying entry that names no observed command or
    receipt (placeholder, self-referential, or prepared-not-observed evidence),
    which is the reuse that keeps "merged" a claim rather than a proof.
    """
    if obligation not in MERGE_OBLIGATION_ACTIONS:
        raise ValueError(f"merge obligation must be one of {MERGE_OBLIGATION_ACTIONS}")
    target = re.sub(r"\s+", " ", str(ref)).strip()
    scope = f" {target}" if target else ""
    return {
        "id": MERGE_OBLIGATION_CRITERION_IDS[obligation],
        "summary": (
            f"{obligation}{scope} observed via an external-effect {obligation} receipt "
            "(a delegated subtask completing is not this obligation being met)"
        ),
        "required": True,
    }


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "goal")[:48].strip("-") or "goal"


def _stamp(value: datetime | None = None) -> str:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _new_item_id(prefix: str) -> str:
    return f"{prefix}-{_stamp().lower()}-{secrets.token_hex(3)}"


def new_goal_id(objective: str, now: datetime | None = None) -> str:
    return f"{_stamp(now).lower()}-{_slugify(objective)}-{secrets.token_hex(3)}"


def _storage_id(value: str, kind: str) -> str:
    item = str(value).strip()
    if not STORAGE_ID_RE.fullmatch(item):
        raise ValueError(f"{kind} must match {STORAGE_ID_RE.pattern}")
    if item in {".", ".."} or ".." in item or "/" in item or "\\" in item:
        raise ValueError(f"{kind} must be a storage id, not a path")
    return item


def _goal_dir(paths: OmhPaths, goal_id: str) -> Path:
    safe_goal_id = _storage_id(goal_id, "goal_id")
    root = paths.goals_dir.resolve()
    path = (root / safe_goal_id).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("goal_id escapes goals directory") from exc
    return path


def goal_ledger_path(paths: OmhPaths, goal_id: str) -> Path:
    return _goal_dir(paths, goal_id) / "goal.json"


def _safe_summary(value: str, *, limit: int = 240) -> str:
    summary = re.sub(r"\s+", " ", value).strip()
    if len(summary) <= limit:
        return summary
    return summary[: limit - 1].rstrip() + "..."


def _objective_summary(objective: str, explicit_summary: str | None) -> str:
    if explicit_summary:
        return _safe_summary(explicit_summary)
    digest = sha256_text(objective)[:12]
    return f"Objective stored by sha256 metadata ({digest})."


def _criteria_objects(criteria: Iterable[str | dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, criterion in enumerate(criteria, start=1):
        if isinstance(criterion, dict):
            summary = _safe_summary(str(criterion.get("summary", "")).strip())
            criterion_id = str(criterion.get("id") or f"AC{index:03d}")
            required = bool(criterion.get("required", True))
        else:
            summary = _safe_summary(str(criterion).strip())
            criterion_id = f"AC{index:03d}"
            required = True
        if not summary:
            raise ValueError(f"acceptance criterion {criterion_id} requires a summary")
        result.append(
            {
                "id": criterion_id,
                "summary": summary,
                "required": required,
                "status": "pending",
                "evidence_refs": [],
            }
        )
    if not result:
        raise ValueError("at least one acceptance criterion is required")
    return result


_STATED_CRITERIA_MARKER_RE = re.compile(
    r"(?:done when|success (?:is|means)|complete when|completion means|"
    r"acceptance criteria|success criteria|completion criteria|definition of done|"
    r"완료\s*조건|성공\s*기준|완료\s*기준|끝나는\s*조건)"
    r"\s*(?:is|means|[:\-])?\s*(.+)",
    re.IGNORECASE,
)


def extract_stated_acceptance_criteria(text: str) -> list[str]:
    """Pull user-stated success/acceptance-criteria phrases out of free chat text.

    This only recognizes explicit "done when ...", "success is/means ...",
    "acceptance criteria: ...", "완료 조건: ..." style markers. Other surfaces
    (chat coaching, etc.) should call this -- or `goal_message_states_acceptance_criteria`
    below -- instead of re-implementing what counts as a stated criterion.
    """
    candidates: list[str] = []
    for line in re.split(r"[\r\n]+|(?<=[.!?])\s+", str(text)):
        match = _STATED_CRITERIA_MARKER_RE.search(line)
        if not match:
            continue
        candidate = match.group(1).strip(" .,:;-")
        if candidate:
            candidates.append(candidate)
    return candidates


def goal_message_states_acceptance_criteria(text: str) -> bool:
    """True when free chat text already states at least one valid acceptance criterion.

    Reuses `_criteria_objects` -- the same validation goal ledgers rely on --
    so "what counts as a criterion" has exactly one definition in this codebase.
    """
    candidates = extract_stated_acceptance_criteria(text)
    if not candidates:
        return False
    try:
        _criteria_objects(candidates)
    except ValueError:
        return False
    return True


def _evidence_refs(values: Iterable[str] | None) -> list[str]:
    return [_safe_summary(str(value), limit=320) for value in values or [] if str(value).strip()]


def _linked_runtime_runs(values: Iterable[str] | None) -> list[str]:
    return sorted({_storage_id(str(value), "linked_runtime_run_id") for value in values or [] if str(value).strip()})


def _read_goal(paths: OmhPaths, goal_id: str) -> dict[str, Any]:
    data = read_json_object(goal_ledger_path(paths, goal_id))
    if data is None:
        raise FileNotFoundError(goal_ledger_path(paths, goal_id))
    return data


def _guarded_goal_update(
    paths: OmhPaths,
    goal_id: str,
    mutate,
    *,
    operation: str,
    expected_revision: int | None = None,
    mutation_id: str | None = None,
    mutation_digest: str | None = None,
    default: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    """One locked read-check-write transaction on goal.json.

    Returns (goal_record, replayed). A replayed mutation_id returns the
    current goal without a write or revision bump, so a retried CLI call
    cannot append a duplicate item; replay is keyed on
    (operation, mutation_id), so the same client id reused for a different
    logical operation still applies.
    """
    path = goal_ledger_path(paths, goal_id)

    def _mutate(current: dict[str, Any]) -> dict[str, Any] | None:
        if default is None:
            _raise_goal_validation_errors(current)
        updated = mutate(current)
        if updated is None:
            return None
        updated["updated_at"] = utc_now()
        return updated

    result = guarded_record_update(
        path,
        mutate=_mutate,
        operation=operation,
        expected_revision=expected_revision,
        mutation_id=mutation_id,
        mutation_digest=mutation_digest,
        lock_name="goal.json",
        validate=_raise_goal_validation_errors,
        default=default,
    )
    if isinstance(result, DuplicateMutationReplay):
        return result.record, True
    return result, False


def _mutation_digest(*parts: object) -> str:
    """Digest of one operation's own arguments, for replay-conflict detection.

    The core helper compares this against the digest stored for the same
    (operation, mutation_id); a retry that carries different content is then
    refused instead of silently replaying somebody else's result.
    """
    return sha256_text(json.dumps(list(parts), sort_keys=True, separators=(",", ":"), default=str))


def _record_goal_outcome(
    outcome: dict[str, Any] | None,
    goal: dict[str, Any],
    *,
    replayed: bool,
    applied: bool,
) -> None:
    """Re-derive what actually landed in the persisted record for the caller.

    A replayed or refused mutation still returns a goal, so surfaces that
    report success must read `applied` here instead of assuming the call did
    what it asked for.
    """
    if outcome is None:
        return
    outcome.update({"replayed": replayed, "applied": applied, "goal_status": str(goal.get("status", ""))})


def _raise_goal_validation_errors(goal: dict[str, Any]) -> None:
    validation = validate_goal_ledger(goal)
    if not validation["ok"]:
        raise ValueError("; ".join(validation["errors"]))


def _mutation_item_id(mutation_id: str | None, prefix: str) -> str:
    """Derive the ledger item id a mutation_id owns, for any mutation_id.

    A mutation_id is a client-chosen retry token, not a storage id: wrapper
    sessions and loop cycles accept arbitrary strings, so connectors that
    derive ids from upstream message ids (snowflakes carrying ':' or '/')
    must not fail on goals alone. Filesystem-safe ids stay verbatim so the
    item id remains readable; anything else is hashed, which keeps the
    derivation deterministic - the same mutation_id always maps to the same
    item id - without ever putting caller text in a path segment.
    """
    item = str(mutation_id or "").strip()
    if not item:
        return _new_item_id(prefix)
    if _is_storage_id(item):
        return item
    return f"{prefix}-{sha256_text(item)[:24]}"


def _item_id_already_present(items: Any, id_key: str, item_id: str) -> bool:
    """True when the list already holds the item this mutation would append.

    The bounded applied_mutations map forgets an id after 128 later mutations,
    and the eviction floor only refuses a retry that also carried an
    expected_revision. A retry carrying nothing but --mutation-id therefore
    reached mutate() with no replay proof and appended a second item under the
    same derived id (issue #828). Because the id here is *materialized* from
    the mutation_id, the record itself is the proof: if the item is already
    there, the mutation already applied. This scan runs inside the lock, so it
    cannot race a concurrent append.
    """
    if not item_id or not isinstance(items, list):
        return False
    return any(isinstance(item, dict) and str(item.get(id_key, "")) == item_id for item in items)


def _is_storage_id(value: str) -> bool:
    if not STORAGE_ID_RE.fullmatch(value):
        return False
    return value not in {".", ".."} and ".." not in value and "/" not in value and "\\" not in value


def create_goal_ledger(
    paths: OmhPaths,
    objective: str,
    acceptance_criteria: Iterable[str | dict[str, Any]],
    *,
    source: str = "omh",
    goal_id: str | None = None,
    objective_summary: str | None = None,
    linked_runtime_runs: Iterable[str] | None = None,
) -> dict[str, Any]:
    if not objective.strip():
        raise ValueError("objective is required")
    goal_id = _storage_id(goal_id or new_goal_id(objective), "goal_id")
    now = utc_now()
    goal = {
        "schema_version": GOAL_LEDGER_SCHEMA,
        "goal_id": goal_id,
        "created_at": now,
        "updated_at": now,
        "status": "active",
        "source": _safe_summary(source, limit=120),
        "objective_storage": "sha256",
        "objective_hash": sha256_text(objective),
        "objective_summary": _objective_summary(objective, objective_summary),
        "acceptance_criteria": _criteria_objects(acceptance_criteria),
        "checkpoints": [],
        "current_checkpoint": None,
        "blockers": [],
        "quality_gates": [],
        "linked_runtime_runs": _linked_runtime_runs(linked_runtime_runs),
    }
    validation = validate_goal_ledger(goal)
    if not validation["ok"]:
        raise ValueError("; ".join(validation["errors"]))
    ensure_dir(_goal_dir(paths, goal_id), private=True)
    ensure_dir(_goal_dir(paths, goal_id) / "evidence", private=True)
    return _guarded_goal_update(
        paths, goal_id, lambda current: dict(goal), operation="create_goal_ledger", default={}
    )[0]


def read_goal_ledger(paths: OmhPaths, goal_id: str) -> dict[str, Any]:
    goal = _read_goal(paths, goal_id)
    validation = validate_goal_ledger(goal)
    if not validation["ok"]:
        raise ValueError("; ".join(validation["errors"]))
    return goal


def list_goal_ledgers(paths: OmhPaths) -> list[dict[str, Any]]:
    if not paths.goals_dir.exists():
        return []
    ledgers: list[dict[str, Any]] = []
    for goal_json in sorted(paths.goals_dir.glob("*/goal.json")):
        data = read_json_object(goal_json)
        if isinstance(data, dict):
            ledgers.append(data)
    return ledgers


def record_goal_checkpoint(
    paths: OmhPaths,
    goal_id: str,
    summary: str,
    *,
    criteria_refs: Iterable[str] | None = None,
    status: str = "done",
    evidence_refs: Iterable[str] | None = None,
    notes_summary: str = "",
    linked_runtime_run_id: str = "",
    observed_tree: str = "",
    expected_revision: int | None = None,
    mutation_id: str | None = None,
    outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one checkpoint to a goal ledger.

    `observed_tree` is the git tree hash the checkpoint's work was observed
    against, read by the caller (see `current_git_tree_hash`). It is stamped as
    recorded and never re-derived later: a checkpoint that carries no tree
    stores the empty string, exactly as before, and stays readable as such.
    """
    if status not in CHECKPOINT_STATUSES:
        raise ValueError(f"unsupported checkpoint status: {status}")
    if not summary.strip():
        raise ValueError("checkpoint summary is required")
    checkpoint_id = _mutation_item_id(mutation_id, "checkpoint")
    refs = [str(ref).strip() for ref in criteria_refs or [] if str(ref).strip()]
    evidence = _evidence_refs(evidence_refs)
    observed_tree_ref = _safe_summary(observed_tree, limit=64)
    linked_runtime_ref = (
        _storage_id(linked_runtime_run_id, "linked_runtime_run_id") if linked_runtime_run_id.strip() else ""
    )

    replay = {"deduped": False}

    def mutate(goal: dict[str, Any]) -> dict[str, Any] | None:
        # The materialized-id dedupe runs before every other check, exactly
        # like the applied_mutations replay path it backstops: that path
        # returns the record without running preconditions either, so a retry
        # must not start failing them once its id has been evicted.
        if _item_id_already_present(goal.get("checkpoints"), "checkpoint_id", checkpoint_id):
            replay["deduped"] = True
            return None
        # Every precondition runs inside the locked transaction and in the
        # original order: an unknown criterion ref is reported before the
        # missing-evidence rule, and a raise here leaves the record untouched.
        require_not_terminal(goal, "status", GOAL_TERMINAL_STATUSES, "record a checkpoint on this goal")
        criterion_ids = {str(criterion["id"]) for criterion in goal["acceptance_criteria"]}
        unknown_refs = [ref for ref in refs if ref not in criterion_ids]
        if unknown_refs:
            raise ValueError(f"unknown acceptance criteria: {', '.join(unknown_refs)}")
        if status == "done" and refs and not evidence:
            raise ValueError("done checkpoints that satisfy criteria require evidence_refs")
        checkpoint = {
            "checkpoint_id": checkpoint_id,
            "created_at": utc_now(),
            "status": status,
            "summary": _safe_summary(summary),
            "criteria_refs": refs,
            "evidence_refs": evidence,
            "notes_summary": _safe_summary(notes_summary) if notes_summary.strip() else "",
            "linked_runtime_run_id": linked_runtime_ref,
            "observed_tree": observed_tree_ref,
        }
        goal["checkpoints"].append(checkpoint)
        goal["current_checkpoint"] = checkpoint["checkpoint_id"]
        if status == "done":
            for criterion in goal["acceptance_criteria"]:
                if criterion["id"] in refs:
                    criterion["status"] = "satisfied"
                    criterion["evidence_refs"] = sorted(set(criterion["evidence_refs"] + evidence))
        if linked_runtime_ref:
            runs = set(goal.get("linked_runtime_runs", []))
            runs.add(linked_runtime_ref)
            goal["linked_runtime_runs"] = sorted(runs)
        return goal

    goal, replayed = _guarded_goal_update(
        paths,
        goal_id,
        mutate,
        operation="record_goal_checkpoint",
        expected_revision=expected_revision,
        mutation_id=mutation_id,
        # The observed tree is part of the checkpoint's content, so a retry
        # reusing this mutation_id against a different tree is a content
        # conflict to refuse, not a replay to serve from the stored record.
        mutation_digest=_mutation_digest(
            "record_goal_checkpoint", summary, status, refs, evidence, notes_summary, linked_runtime_ref,
            observed_tree_ref,
        ),
    )
    _record_goal_outcome(
        outcome,
        goal,
        replayed=replayed or replay["deduped"],
        applied=_item_id_already_present(goal.get("checkpoints"), "checkpoint_id", checkpoint_id),
    )
    return goal


def record_goal_blocker(
    paths: OmhPaths,
    goal_id: str,
    summary: str,
    *,
    attempted_recovery: str = "",
    missing_authority: str = "",
    evidence_refs: Iterable[str] | None = None,
    mark_goal_blocked: bool = False,
    expected_revision: int | None = None,
    mutation_id: str | None = None,
    outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not summary.strip():
        raise ValueError("blocker summary is required")
    blocker_id = _mutation_item_id(mutation_id, "blocker")
    replay = {"deduped": False}

    def mutate(goal: dict[str, Any]) -> dict[str, Any] | None:
        # See _item_id_already_present: this is the retry proof the bounded
        # applied_mutations map can no longer give once the id was evicted.
        if _item_id_already_present(goal.get("blockers"), "blocker_id", blocker_id):
            replay["deduped"] = True
            return None
        require_not_terminal(goal, "status", GOAL_TERMINAL_STATUSES, "record a blocker on this goal")
        goal["blockers"].append(
            {
                "blocker_id": blocker_id,
                "created_at": utc_now(),
                "status": "active",
                "summary": _safe_summary(summary),
                "attempted_recovery": _safe_summary(attempted_recovery) if attempted_recovery.strip() else "",
                "missing_authority": _safe_summary(missing_authority) if missing_authority.strip() else "",
                "evidence_refs": _evidence_refs(evidence_refs),
            }
        )
        if mark_goal_blocked:
            goal["status"] = "blocked"
        return goal

    goal, replayed = _guarded_goal_update(
        paths,
        goal_id,
        mutate,
        operation="record_goal_blocker",
        expected_revision=expected_revision,
        mutation_id=mutation_id,
        mutation_digest=_mutation_digest(
            "record_goal_blocker",
            summary,
            attempted_recovery,
            missing_authority,
            _evidence_refs(evidence_refs),
            mark_goal_blocked,
        ),
    )
    _record_goal_outcome(
        outcome,
        goal,
        replayed=replayed or replay["deduped"],
        applied=_item_id_already_present(goal.get("blockers"), "blocker_id", blocker_id),
    )
    return goal


def record_goal_quality_gate(
    paths: OmhPaths,
    goal_id: str,
    summary: str,
    *,
    status: str = "passed",
    evidence_refs: Iterable[str] | None = None,
    expected_revision: int | None = None,
    mutation_id: str | None = None,
    outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in QUALITY_GATE_STATUSES:
        raise ValueError(f"unsupported quality gate status: {status}")
    if not summary.strip():
        raise ValueError("quality gate summary is required")
    quality_gate_id = _mutation_item_id(mutation_id, "quality-gate")
    replay = {"deduped": False}

    def mutate(goal: dict[str, Any]) -> dict[str, Any] | None:
        # See _item_id_already_present: this is the retry proof the bounded
        # applied_mutations map can no longer give once the id was evicted.
        if _item_id_already_present(goal.get("quality_gates"), "quality_gate_id", quality_gate_id):
            replay["deduped"] = True
            return None
        require_not_terminal(goal, "status", GOAL_TERMINAL_STATUSES, "record a quality gate on this goal")
        goal["quality_gates"].append(
            {
                "quality_gate_id": quality_gate_id,
                "created_at": utc_now(),
                "status": status,
                "summary": _safe_summary(summary),
                "evidence_refs": _evidence_refs(evidence_refs),
            }
        )
        return goal

    goal, replayed = _guarded_goal_update(
        paths,
        goal_id,
        mutate,
        operation="record_goal_quality_gate",
        expected_revision=expected_revision,
        mutation_id=mutation_id,
        mutation_digest=_mutation_digest(
            "record_goal_quality_gate", summary, status, _evidence_refs(evidence_refs)
        ),
    )
    _record_goal_outcome(
        outcome,
        goal,
        replayed=replayed or replay["deduped"],
        applied=_item_id_already_present(goal.get("quality_gates"), "quality_gate_id", quality_gate_id),
    )
    return goal


def cancel_goal_ledger(
    paths: OmhPaths,
    goal_id: str,
    *,
    reason: str = "",
    expected_revision: int | None = None,
    mutation_id: str | None = None,
    outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Terminally cancel a goal; later checkpoints, blockers, and gates refuse."""

    def mutate(goal: dict[str, Any]) -> dict[str, Any]:
        require_not_terminal(goal, "status", GOAL_TERMINAL_STATUSES, "cancel this goal")
        goal["status"] = "cancelled"
        if reason.strip():
            goal["cancel_reason"] = _safe_summary(reason)
        return goal

    goal, replayed = _guarded_goal_update(
        paths,
        goal_id,
        mutate,
        operation="cancel_goal_ledger",
        expected_revision=expected_revision,
        mutation_id=mutation_id,
        mutation_digest=_mutation_digest("cancel_goal_ledger", reason),
    )
    # Re-derived from the persisted status, never from "the call returned":
    # a mutation replayed away leaves an uncancelled goal, and reporting that
    # as success is how a discarded cancel looks like a cancelled goal.
    _record_goal_outcome(outcome, goal, replayed=replayed, applied=goal.get("status") == "cancelled")
    return goal


def fail_goal_ledger(
    paths: OmhPaths,
    goal_id: str,
    summary: str,
    *,
    reason_code: str,
    evidence_refs: Iterable[str] | None = None,
    expected_revision: int | None = None,
    mutation_id: str | None = None,
    outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Terminally fail a goal: the objective was evaluated and cannot be met.

    Distinct from `cancel_goal_ledger` (an operator decided to stop, for any
    reason or none) and from `record_goal_blocker` (a recoverable obstacle
    that further checkpoints can clear): a failure is a negative but
    CONCLUSIVE verdict on the objective itself, reached because the target
    does not exist, the request is refused by policy, or the acceptance
    criteria are infeasible as specified. It is never a claim that the goal
    ran out of budget or attempts -- `record_goal_blocker` or a loop's own
    `wait_reason` cover that case, and stay recoverable.

    Terminal like `cancel_goal_ledger`: later checkpoints, blockers, and gates
    refuse via `require_not_terminal`, and a linked loop's stop ladder must
    not schedule further ticks against this goal (`_stop_rung_explicit_cancel`
    in `goal_loop` fires on `failed` for the same reason it fires on
    `cancelled`).
    """
    if reason_code not in GOAL_FAILURE_REASON_CODES:
        raise ValueError(f"unsupported goal failure reason_code: {reason_code}")
    if not summary.strip():
        raise ValueError("failure summary is required")
    evidence = _evidence_refs(evidence_refs)

    def mutate(goal: dict[str, Any]) -> dict[str, Any]:
        require_not_terminal(goal, "status", GOAL_TERMINAL_STATUSES, "fail this goal")
        goal["status"] = "failed"
        goal["failure_reason_code"] = reason_code
        goal["failure_summary"] = _safe_summary(summary)
        goal["failure_evidence_refs"] = evidence
        return goal

    goal, replayed = _guarded_goal_update(
        paths,
        goal_id,
        mutate,
        operation="fail_goal_ledger",
        expected_revision=expected_revision,
        mutation_id=mutation_id,
        mutation_digest=_mutation_digest("fail_goal_ledger", reason_code, summary, evidence),
    )
    # Re-derived from the persisted status, the same rule `cancel_goal_ledger`
    # follows: a mutation replayed away leaves an unfailed goal, and reporting
    # that as success is how a discarded failure verdict looks like a real one.
    _record_goal_outcome(outcome, goal, replayed=replayed, applied=goal.get("status") == "failed")
    return goal


def validate_goal_ledger(goal: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if goal.get("schema_version") != GOAL_LEDGER_SCHEMA:
        errors.append("schema_version must be goal_ledger/v1")
    if "objective" in goal:
        errors.append("raw objective field is not allowed")
    if not str(goal.get("goal_id", "")).strip():
        errors.append("goal_id is required")
    else:
        try:
            _storage_id(str(goal.get("goal_id", "")), "goal_id")
        except ValueError as exc:
            errors.append(str(exc))
    if goal.get("status") not in GOAL_STATUSES:
        errors.append("status must be active, blocked, failed, complete, or cancelled")
    if "cancel_reason" in goal and not isinstance(goal.get("cancel_reason"), str):
        errors.append("cancel_reason must be a string")
    errors.extend(_failure_fields_errors(goal))
    objective_hash = str(goal.get("objective_hash", ""))
    if len(objective_hash) != 64 or not re.fullmatch(r"[0-9a-f]+", objective_hash):
        errors.append("objective_hash must be a sha256 hex digest")
    if goal.get("objective_storage") != "sha256":
        errors.append("objective_storage must be sha256")
    _validate_criteria(goal.get("acceptance_criteria"), errors)
    _validate_checkpoints(goal.get("checkpoints"), errors)
    _validate_blockers(goal.get("blockers"), errors)
    _validate_quality_gates(goal.get("quality_gates"), errors)
    if not isinstance(goal.get("linked_runtime_runs"), list):
        errors.append("linked_runtime_runs must be a list")
    else:
        for index, run_id in enumerate(goal.get("linked_runtime_runs", []), start=1):
            try:
                _storage_id(str(run_id), "linked_runtime_run_id")
            except ValueError as exc:
                errors.append(f"linked_runtime_runs[{index}]: {exc}")
    errors.extend(revision_field_errors(goal, "goal_ledger"))
    return {"ok": not errors, "errors": errors}


def build_goal_completion_gate(paths: OmhPaths, goal_id: str) -> dict[str, Any]:
    goal = read_goal_ledger(paths, goal_id)
    missing_required = [
        {
            "id": criterion["id"],
            "summary": criterion["summary"],
        }
        for criterion in goal["acceptance_criteria"]
        if criterion["required"] and (criterion["status"] != "satisfied" or not criterion["evidence_refs"])
    ]
    active_blockers = [
        {
            "id": blocker["blocker_id"],
            "summary": blocker["summary"],
        }
        for blocker in goal["blockers"]
        if blocker.get("status") == "active"
    ]
    runtime_checks = [_linked_runtime_check(paths, run_id) for run_id in goal.get("linked_runtime_runs", [])]
    runtime_gaps = [check for check in runtime_checks if not check["satisfied"]]
    status_gaps = []
    if goal["status"] == "blocked":
        status_gaps.append("goal status is blocked")
    if goal["status"] == "failed":
        status_gaps.append("goal status is failed")
    if goal["status"] == "cancelled":
        status_gaps.append("goal status is cancelled")
    integrity_refusals = _completion_integrity_refusals(goal)
    ready = (
        not missing_required
        and not active_blockers
        and not runtime_gaps
        and not status_gaps
        and not integrity_refusals
    )
    next_action = _completion_next_action(
        missing_required=missing_required,
        active_blockers=active_blockers,
        runtime_gaps=runtime_gaps,
        status_gaps=status_gaps,
        integrity_refusals=integrity_refusals,
    )
    if goal["status"] in ("cancelled", "failed"):
        # Both are terminal: recording blockers or checkpoints on either is
        # refused (`require_not_terminal`), so the only safe next action is
        # showing status. Without this a `failed` goal fell through to
        # `_completion_next_action`'s `status_gaps` branch and suggested
        # `record_blocker`, which the goal would then refuse.
        next_action = "show_status"
    return {
        "schema_version": GOAL_COMPLETION_GATE_SCHEMA,
        "goal_id": goal_id,
        "goal_status": goal["status"],
        "ready": ready,
        "summary": _completion_gate_summary(
            missing_required=missing_required,
            active_blockers=active_blockers,
            runtime_gaps=runtime_gaps,
            status_gaps=status_gaps,
            integrity_refusals=integrity_refusals,
        ),
        "missing_required_criteria": missing_required,
        "active_blockers": active_blockers,
        "linked_runtime_checks": runtime_checks,
        "integrity_refusals": integrity_refusals,
        "next_action": next_action,
    }


def _completion_integrity_refusals(goal: dict[str, Any]) -> list[dict[str, str]]:
    """Refusals the goal's own completion claim earns, as blocking gaps.

    The ledger stores the claim, not the diff: satisfied criteria and done
    checkpoints carry the summaries that make the claim and the evidence refs
    that are supposed to prove it. Those are what get classified here, so a
    goal cannot pass the gate on the string "TBD" or on a summary asserting
    "tests passing" with nothing naming a command. Changed-file content is not
    stored in the ledger and is therefore not scanned at this call site; a
    caller holding a diff classifies it directly.
    """
    claim_lines = [
        checkpoint["summary"]
        for checkpoint in goal["checkpoints"]
        if checkpoint.get("status") == "done"
    ]
    claim_lines.extend(
        checkpoint["notes_summary"]
        for checkpoint in goal["checkpoints"]
        if checkpoint.get("status") == "done" and checkpoint.get("notes_summary")
    )
    evidence: list[str] = []
    for criterion in goal["acceptance_criteria"]:
        if criterion["required"] and criterion["status"] == "satisfied":
            evidence.extend(criterion["evidence_refs"])
    for checkpoint in goal["checkpoints"]:
        if checkpoint.get("status") == "done":
            evidence.extend(checkpoint.get("evidence_refs", []))
    verdict = classify_completion_integrity(
        summary=" ".join(claim_lines),
        evidence=list(dict.fromkeys(evidence)),
    )
    refusals = verdict["refusals"]
    return refusals if isinstance(refusals, list) else []


def complete_goal_ledger(
    paths: OmhPaths,
    goal_id: str,
    *,
    evidence_refs: Iterable[str] | None = None,
    expected_revision: int | None = None,
    mutation_id: str | None = None,
) -> dict[str, Any]:
    evidence = _evidence_refs(evidence_refs)
    quality_gate_id = _mutation_item_id(mutation_id, "quality-gate")
    outcome: dict[str, Any] = {}
    replay = {"deduped": False}

    def mutate(goal: dict[str, Any]) -> dict[str, Any] | None:
        # See _item_id_already_present: the completion quality gate is
        # materialized from the mutation_id too, so the gate itself proves the
        # retry even after the applied_mutations entry was evicted.
        if _item_id_already_present(goal.get("quality_gates"), "quality_gate_id", quality_gate_id):
            replay["deduped"] = True
            return None
        # The gate is evaluated inside the locked transaction so a concurrent
        # blocker or cancellation cannot slip in between the check and the
        # completion write.
        gate = build_goal_completion_gate(paths, goal_id)
        if not gate["ready"]:
            outcome.update({"completed": False, "goal": goal, "completion_gate": gate})
            return None
        if not evidence:
            adjusted = {
                **gate,
                "ready": False,
                "summary": "Completion requires final evidence_refs.",
                "next_action": "record_completion",
            }
            outcome.update({"completed": False, "goal": goal, "completion_gate": adjusted})
            return None
        outcome["completed"] = True
        if goal["status"] == "complete":
            outcome["goal"] = goal
            return None
        goal["status"] = "complete"
        goal["quality_gates"].append(
            {
                "quality_gate_id": quality_gate_id,
                "created_at": utc_now(),
                "status": "passed",
                "summary": "Completion gate passed.",
                "evidence_refs": evidence,
            }
        )
        outcome["goal"] = goal
        return goal

    goal, replayed = _guarded_goal_update(
        paths,
        goal_id,
        mutate,
        operation="complete_goal_ledger",
        expected_revision=expected_revision,
        mutation_id=mutation_id,
        mutation_digest=_mutation_digest("complete_goal_ledger", evidence),
    )
    replayed = replayed or replay["deduped"]
    if not outcome:
        # Replayed mutation_id: the completion already applied.
        return {
            "completed": goal.get("status") == "complete",
            "replayed": replayed,
            "goal": goal,
            "completion_gate": build_goal_completion_gate(paths, goal_id),
        }
    if outcome["completed"]:
        # Re-derived from the persisted status, not from the gate verdict the
        # mutate callable computed before the write.
        return {
            "completed": goal.get("status") == "complete",
            "replayed": replayed,
            "goal": goal,
            "completion_gate": build_goal_completion_gate(paths, goal_id),
        }
    return {**outcome, "replayed": replayed}


def build_goal_continuation(paths: OmhPaths, goal_id: str) -> dict[str, Any]:
    goal = read_goal_ledger(paths, goal_id)
    status_card = build_goal_status_card(paths, goal_id)
    actions = _allowed_goal_actions(status_card["completion_gate"])
    return {
        "schema_version": GOAL_CONTINUATION_SCHEMA,
        "goal_id": goal_id,
        "goal_status": goal["status"],
        "objective_summary": goal["objective_summary"],
        "next_action": status_card["next_action"],
        "actions": actions,
        "safe_copy": status_card["safe_copy"],
        "status_card": status_card,
        "action_plan": _goal_action_plan(goal_id, actions, status_card),
    }


def _checkpoint_id_short(checkpoint_id: str) -> str:
    # The trailing token from _new_item_id (secrets.token_hex(3)) is short,
    # stable, and unique enough to reference a checkpoint in a status line.
    segment = checkpoint_id.rsplit("-", 1)[-1]
    return segment or checkpoint_id[:8]


def _checkpoint_lines(checkpoints: list[dict[str, Any]]) -> list[str]:
    # Pre-rendered as dash lines, not left to the caller's judgment: a live
    # Slack session once rendered this same data as a markdown table, which
    # messenger surfaces (Slack, Telegram) silently drop. Handing back the
    # exact lines to print removes that choice entirely.
    lines = []
    for checkpoint in checkpoints:
        evidence = "observed" if checkpoint.get("evidence_refs") else "prepared"
        lines.append(
            f"- {_checkpoint_id_short(checkpoint['checkpoint_id'])}: "
            f"{checkpoint['summary']} — {checkpoint['status']}, {evidence}"
        )
    return lines


def build_goal_status_card(paths: OmhPaths, goal_id: str) -> dict[str, Any]:
    goal = read_goal_ledger(paths, goal_id)
    gate = build_goal_completion_gate(paths, goal_id)
    progress = _goal_progress(goal)
    card: dict[str, Any] = {
        "schema_version": GOAL_STATUS_CARD_SCHEMA,
        "goal_id": goal_id,
        "goal_status": goal["status"],
        "objective_summary": goal["objective_summary"],
        "progress": progress,
        "missing_criteria": gate["missing_required_criteria"],
        "active_blockers": gate["active_blockers"],
        "linked_runtime_checks": gate["linked_runtime_checks"],
        "next_action": gate["next_action"],
        "allowed_actions": _allowed_goal_actions(gate),
        "safe_copy": _goal_safe_copy(goal, gate, progress),
        "completion_gate": gate,
        "checkpoint_lines": _checkpoint_lines(goal["checkpoints"]),
        "render_guidance": (
            "Render checkpoints as the provided dash lines, one per line. "
            "Never render a markdown table: messenger surfaces (Slack, Telegram) drop tables."
        ),
    }
    # Additive, and only on a failed goal: a negative-conclusive verdict
    # carries its own structured reason, distinct from `active_blockers`
    # (recoverable) or a bare `goal_status` string a caller might miss.
    if goal["status"] == "failed":
        card["failure_reason_code"] = str(goal.get("failure_reason_code", ""))
        card["failure_summary"] = str(goal.get("failure_summary", ""))
    return card


GOAL_STATUS_CLAIM_BOUNDARY: Final[str] = (
    "A goal status card is ledger state. Satisfied criteria are recorded, not verified, "
    "and it is not execution, review, CI, or merge evidence."
)


def render_goal_status_text(
    card: dict[str, Any], *, render_profile: str = RENDER_PROFILE_LIMITED_MARKDOWN
) -> str:
    """The goal status card as exact lines, for a terminal or a messenger.

    `omh goal status` prints JSON by design -- it is a control-plane command and
    wrappers parse it. That contract is fine for a wrapper and hostile to a
    human: relayed straight into a chat client the payload arrives as one line
    of backslash-escaped Unicode. This renders the same card instead of
    changing what the command returns by default.

    The header goes through the message gate so a goal card and a coding handoff
    disclose their skill, status, and prompt reference in the identical shape,
    with MODEL declared absent because a goal ledger has no executor to name.
    """
    gate = build_message_gate(
        skill="ulw-goal",
        status=str(card.get("goal_status", "")),
        prompt_sha256=_objective_digest(card),
        prompt_chars=len(str(card.get("objective_summary", "") or "")),
        discloses_model=False,
        reference_kind="objective",
    )
    progress = card.get("progress") if isinstance(card.get("progress"), dict) else {}
    lines = [
        *render_message_gate_lines(gate, render_profile=render_profile),
        "",
        str(card.get("objective_summary", "") or "(no objective recorded)"),
        "",
        # `_goal_progress` keys are `criteria_satisfied` / `criteria_total`; the
        # shorter names render a six-criteria goal as `0 of 0`, which is worse
        # than no line at all because it reads as a real measurement.
        f"Criteria: {progress.get('criteria_satisfied', 0)} of "
        f"{progress.get('criteria_total', 0)} satisfied "
        f"({progress.get('percent_required_satisfied', 0)}% of required)",
        f"Next action: {card.get('next_action', '') or 'unknown'}",
    ]
    checkpoint_lines = card.get("checkpoint_lines")
    if isinstance(checkpoint_lines, list) and checkpoint_lines:
        lines.extend(["", "Checkpoints:", *(str(line) for line in checkpoint_lines)])
    else:
        lines.extend(["", "No checkpoints recorded."])
    for label, key in (("Missing criteria", "missing_criteria"), ("Active blockers", "active_blockers")):
        items = card.get(key)
        if isinstance(items, list) and items:
            lines.extend(["", f"{label}:", *(f"- {_goal_line_item(item)}" for item in items)])
    lines.extend(["", GOAL_STATUS_CLAIM_BOUNDARY])
    return "\n".join(lines).strip()


def _goal_line_item(item: Any) -> str:
    """One bounded line per entry, whether the ledger stored a string or a dict."""
    if isinstance(item, dict):
        for key in ("summary", "description", "criterion", "blocker", "id"):
            value = str(item.get(key, "") or "").strip()
            if value:
                return value
        return "unnamed"
    return " ".join(str(item or "").split()) or "unnamed"


def _objective_digest(card: dict[str, Any]) -> str:
    objective = str(card.get("objective_summary", "") or "")
    return sha256_text(objective) if objective else ""


def _linked_runtime_check(paths: OmhPaths, run_id: str) -> dict[str, Any]:
    run_id = _storage_id(run_id, "linked_runtime_run_id")
    return _goal_runtime_evidence_check(run_id, _delegated_runtime_status(paths, run_id))


def _delegated_runtime_status(paths: OmhPaths, run_id: str) -> dict[str, Any] | None:
    try:
        return summarize_delegated_coding_status(paths, run_id)
    except FileNotFoundError:
        return None


def _goal_runtime_evidence_check(run_id: str, status: dict[str, Any] | None) -> dict[str, Any]:
    if status is None:
        return {
            "schema_version": "goal_runtime_evidence_check/v1",
            "run_id": run_id,
            "satisfied": False,
            "summary": "Linked runtime run was not found.",
            "next_action": "record_runtime_evidence",
        }
    next_action = str(status.get("next_action", "unknown"))
    satisfied = next_action in RUNTIME_COMPLETION_ACTIONS
    return {
        "schema_version": "goal_runtime_evidence_check/v1",
        "run_id": run_id,
        "satisfied": satisfied,
        "summary": str(status.get("safe_summary") or f"Runtime next action is {next_action}."),
        "next_action": next_action,
    }


def _completion_gate_summary(
    *,
    missing_required: list[dict[str, Any]],
    active_blockers: list[dict[str, Any]],
    runtime_gaps: list[dict[str, Any]],
    status_gaps: list[str],
    integrity_refusals: list[dict[str, str]],
) -> str:
    if (
        not missing_required
        and not active_blockers
        and not runtime_gaps
        and not status_gaps
        and not integrity_refusals
    ):
        return "Goal is ready for completion."
    parts = []
    if missing_required:
        parts.append(f"{len(missing_required)} required acceptance criteria remain pending")
    if active_blockers:
        parts.append(f"{len(active_blockers)} active blockers remain")
    if runtime_gaps:
        parts.append(f"{len(runtime_gaps)} linked runtime runs still need observed evidence")
    if integrity_refusals:
        categories = ", ".join(sorted({item["category"] for item in integrity_refusals}))
        parts.append(f"{len(integrity_refusals)} completion-integrity refusals remain ({categories})")
    if status_gaps:
        parts.append("; ".join(status_gaps))
    return "; ".join(parts) + "."


def _completion_next_action(
    *,
    missing_required: list[dict[str, Any]],
    active_blockers: list[dict[str, Any]],
    runtime_gaps: list[dict[str, Any]],
    status_gaps: list[str],
    integrity_refusals: list[dict[str, str]],
) -> str:
    if active_blockers or status_gaps:
        return "record_blocker"
    if missing_required:
        return "record_checkpoint"
    if integrity_refusals:
        # The claim itself is the gap: a new checkpoint carrying a real command
        # and a summary that does not outrun it is what clears this.
        return "record_checkpoint"
    if runtime_gaps:
        return "show_status"
    return "record_completion"


def _goal_progress(goal: dict[str, Any]) -> dict[str, Any]:
    criteria = goal["acceptance_criteria"]
    required = [criterion for criterion in criteria if criterion["required"]]
    satisfied = [criterion for criterion in criteria if criterion["status"] == "satisfied"]
    required_satisfied = [criterion for criterion in required if criterion["status"] == "satisfied"]
    active_blockers = [blocker for blocker in goal["blockers"] if blocker.get("status") == "active"]
    percent = 100 if not required else int((len(required_satisfied) / len(required)) * 100)
    return {
        "criteria_total": len(criteria),
        "criteria_satisfied": len(satisfied),
        "required_total": len(required),
        "required_satisfied": len(required_satisfied),
        "active_blockers": len(active_blockers),
        "percent_required_satisfied": percent,
    }


def _allowed_goal_actions(gate: dict[str, Any]) -> list[str]:
    if gate.get("goal_status") in ("cancelled", "failed"):
        # Both terminal: checkpoints, blockers, and completion all refuse via
        # `require_not_terminal`. A `failed` goal offered `record_blocker`
        # here would advertise an action the ledger is about to raise on.
        return ["show_status"]
    actions = ["continue_goal", "show_status"]
    if gate["missing_required_criteria"]:
        actions.append("record_checkpoint")
    actions.append("record_blocker")
    if gate["ready"]:
        actions.append("record_completion")
    return actions


def _goal_safe_copy(goal: dict[str, Any], gate: dict[str, Any], progress: dict[str, Any]) -> dict[str, str]:
    if gate["ready"]:
        next_step = "Record completion with the final verification evidence."
    elif gate["active_blockers"] or goal["status"] == "blocked":
        next_step = "Resolve or update the active blocker before claiming completion."
    elif goal["status"] == "failed":
        # Terminal and negative-conclusive: unlike a blocker, there is nothing
        # left on this goal to clear. The reason lives on the record.
        reason = str(goal.get("failure_reason_code", "") or "unspecified")
        next_step = f"This goal failed conclusively ({reason}); no further checkpoint or blocker applies."
    elif goal["status"] == "cancelled":
        next_step = "This goal was cancelled; no further checkpoint or blocker applies."
    elif gate["missing_required_criteria"]:
        ids = ", ".join(item["id"] for item in gate["missing_required_criteria"])
        next_step = f"Record a checkpoint for the missing acceptance criteria: {ids}."
    elif gate["linked_runtime_checks"]:
        next_step = "Observe the explicitly linked runtime run before claiming completion."
    else:
        next_step = "Continue the goal and record fresh evidence."
    return {
        "headline": f"Goal {goal['goal_id']} is {goal['status']}.",
        "progress": f"{progress['required_satisfied']}/{progress['required_total']} required criteria satisfied.",
        "next_step": next_step,
        # A live Slack session rendered checkpoints as a markdown table, which
        # messenger surfaces drop; this hint steers callers back to bullets.
        "checkpoint_format": "- cpN: summary — status, evidence",
    }


def _goal_action_plan(goal_id: str, actions: list[str], status_card: dict[str, Any]) -> list[dict[str, str]]:
    commands = {
        "continue_goal": f"omh goal continue --goal {goal_id}",
        "show_status": f"omh goal status --goal {goal_id}",
        "record_checkpoint": f"omh goal checkpoint --goal {goal_id} --summary \"<summary>\" --criterion <AC-id> --evidence-ref <evidence>",
        "record_blocker": f"omh goal blocker --goal {goal_id} --summary \"<blocker>\" --evidence-ref <evidence>",
        "record_completion": f"omh goal complete --goal {goal_id} --evidence-ref <evidence>",
    }
    descriptions = {
        "continue_goal": status_card["safe_copy"]["next_step"],
        "show_status": "Show the current goal card without changing state.",
        "record_checkpoint": "Record work evidence and satisfy one or more acceptance criteria.",
        "record_blocker": "Record a blocker when progress cannot safely continue.",
        "record_completion": "Mark the goal complete only when the completion gate is ready.",
    }
    return [{"action": action, "command": commands[action], "summary": descriptions[action]} for action in actions]


def _validate_criteria(criteria: Any, errors: list[str]) -> None:
    if not isinstance(criteria, list) or not criteria:
        errors.append("acceptance_criteria must be a non-empty list")
        return
    seen: set[str] = set()
    for index, criterion in enumerate(criteria, start=1):
        if not isinstance(criterion, dict):
            errors.append(f"acceptance_criteria[{index}] must be an object")
            continue
        criterion_id = str(criterion.get("id", "")).strip()
        if not criterion_id:
            errors.append(f"acceptance_criteria[{index}].id is required")
        if criterion_id in seen:
            errors.append(f"duplicate acceptance criterion id: {criterion_id}")
        seen.add(criterion_id)
        if not str(criterion.get("summary", "")).strip():
            errors.append(f"acceptance_criteria[{index}].summary is required")
        if not isinstance(criterion.get("required"), bool):
            errors.append(f"acceptance_criteria[{index}].required must be boolean")
        if criterion.get("status") not in CRITERION_STATUSES:
            errors.append(f"acceptance_criteria[{index}].status is invalid")
        if not isinstance(criterion.get("evidence_refs"), list):
            errors.append(f"acceptance_criteria[{index}].evidence_refs must be a list")


def _validate_unique_item_ids(items: list[Any], id_key: str, label: str, errors: list[str]) -> None:
    """Reject two items in one list sharing an id.

    Item ids are materialized from mutation_id, so a duplicate is the exact
    shape of a retry that applied twice after its applied_mutations entry was
    evicted (issue #828). The validator runs inside the guarded write, so this
    refuses the duplicate before it is persisted rather than reporting a
    ledger that already lost the invariant as ok.
    """
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get(id_key, "")).strip()
        if not item_id:
            continue
        if item_id in seen:
            errors.append(f"duplicate {label} {id_key}: {item_id}")
        seen.add(item_id)


def _validate_checkpoints(checkpoints: Any, errors: list[str]) -> None:
    if not isinstance(checkpoints, list):
        errors.append("checkpoints must be a list")
        return
    _validate_unique_item_ids(checkpoints, "checkpoint_id", "checkpoint", errors)
    for index, checkpoint in enumerate(checkpoints, start=1):
        if not isinstance(checkpoint, dict):
            errors.append(f"checkpoints[{index}] must be an object")
            continue
        if checkpoint.get("status") not in CHECKPOINT_STATUSES:
            errors.append(f"checkpoints[{index}].status is invalid")
        if not str(checkpoint.get("summary", "")).strip():
            errors.append(f"checkpoints[{index}].summary is required")
        if not isinstance(checkpoint.get("criteria_refs"), list):
            errors.append(f"checkpoints[{index}].criteria_refs must be a list")
        if not isinstance(checkpoint.get("evidence_refs"), list):
            errors.append(f"checkpoints[{index}].evidence_refs must be a list")
        # Optional, so a checkpoint written before the field existed stays
        # valid; a present value still has to be a string.
        if not isinstance(checkpoint.get("observed_tree", ""), str):
            errors.append(f"checkpoints[{index}].observed_tree must be a string")


def _validate_blockers(blockers: Any, errors: list[str]) -> None:
    if not isinstance(blockers, list):
        errors.append("blockers must be a list")
        return
    _validate_unique_item_ids(blockers, "blocker_id", "blocker", errors)
    for index, blocker in enumerate(blockers, start=1):
        if not isinstance(blocker, dict):
            errors.append(f"blockers[{index}] must be an object")
            continue
        if blocker.get("status") not in BLOCKER_STATUSES:
            errors.append(f"blockers[{index}].status is invalid")
        if not str(blocker.get("summary", "")).strip():
            errors.append(f"blockers[{index}].summary is required")
        if not isinstance(blocker.get("evidence_refs"), list):
            errors.append(f"blockers[{index}].evidence_refs must be a list")


def _failure_fields_errors(goal: dict[str, Any]) -> list[str]:
    """The `fail_goal_ledger` fields, checked the way `cancel_reason` is: loosely
    typed when present, and required together once the status they explain is on
    the record -- a `failed` goal with no reason is the exact gap #H exists to close.
    """
    errors: list[str] = []
    if "failure_reason_code" in goal and goal.get("failure_reason_code") not in GOAL_FAILURE_REASON_CODES:
        errors.append("failure_reason_code is unsupported")
    if "failure_summary" in goal and not isinstance(goal.get("failure_summary"), str):
        errors.append("failure_summary must be a string")
    if "failure_evidence_refs" in goal and not isinstance(goal.get("failure_evidence_refs"), list):
        errors.append("failure_evidence_refs must be a list")
    if goal.get("status") == "failed" and (
        "failure_reason_code" not in goal or not str(goal.get("failure_summary", "")).strip()
    ):
        errors.append("a failed goal must carry failure_reason_code and a non-empty failure_summary")
    return errors


def _validate_quality_gates(quality_gates: Any, errors: list[str]) -> None:
    if not isinstance(quality_gates, list):
        errors.append("quality_gates must be a list")
        return
    _validate_unique_item_ids(quality_gates, "quality_gate_id", "quality gate", errors)
    for index, gate in enumerate(quality_gates, start=1):
        if not isinstance(gate, dict):
            errors.append(f"quality_gates[{index}] must be an object")
            continue
        if gate.get("status") not in QUALITY_GATE_STATUSES:
            errors.append(f"quality_gates[{index}].status is invalid")
        if not str(gate.get("summary", "")).strip():
            errors.append(f"quality_gates[{index}].summary is required")
        if not isinstance(gate.get("evidence_refs"), list):
            errors.append(f"quality_gates[{index}].evidence_refs must be a list")
