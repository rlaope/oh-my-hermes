from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..local_store import atomic_write_json, ensure_dir, ensure_file, read_json_object, read_jsonl_objects, utc_now
from ..paths import OmhPaths
from ..runtime.records import OBSERVED_RESULTS as RUNTIME_OBSERVED_RESULTS
from .context_safety import sanitize_user_facing_progress_text
from .owner_progress_normalization import (
    NORMALIZED_PROGRESS_EVENT_TYPES,
    UNMAPPED_NORMALIZED_EVENT,
    is_known_owner,
    normalize_owner_progress_event,
    normalize_shared_progress_event,
    progress_evidence_tier,
)


EXECUTOR_PROGRESS_BINDING_SCHEMA_VERSION = "omh_executor_progress_binding/v1"
EXECUTOR_PROGRESS_EVENT_SCHEMA_VERSION = "omh_progress_event/v1"
EXECUTOR_PROGRESS_REPORT_SCHEMA_VERSION = "omh_progress_report/v1"

# `omo_runtime` is one profile covering every omo host CLI (`pi`, `senpi`,
# `opencode`) because the binding answers "which lane is working", not "which
# binary was on PATH". Without it `fanout dispatch` spawns omo units into a lane
# that `normalize_executor_profile` rejects, so the units run entirely unobserved.
ALLOWED_EXECUTOR_PROFILES = ("codex", "claude_code", "hermes_local", "omo_runtime")
TARGET_TYPES = ("run", "wrapper_session")
BINDING_STATES = ("active", "stale", "expired", "closed")
# One definition, two names. The vocabulary now lives with the normalizer that
# translates owner words into it (`owner_progress_normalization`), because a
# second copy is exactly the drift the plugin-bundle mirror already had to be
# gated against. `PROGRESS_EVENT_TYPES` stays the public name every caller,
# validator, and CLI `--event` choice list already imports from here.
PROGRESS_EVENT_TYPES = NORMALIZED_PROGRESS_EVENT_TYPES
# Exempt from the volume rules -- an exact duplicate transition is still
# deduplicated. `reported_change_not_observed` belongs here because it only
# fires on a finished run whose claim the working tree contradicts, which is the
# failure mode that produced "4 file(s) were NOT modified this turn despite any
# wording above that may suggest otherwise" only at the end of a long session.
TERMINAL_EVENT_TYPES = {
    "executor_completed",
    "executor_blocked",
    "executor_failed",
    "executor_cancelled",
    "tests_failed",
    "tests_passed",
    "reported_change_not_observed",
}
# Observations that end a binding's life. Kept as its own name rather than
# reusing TERMINAL_EVENT_TYPES: `tests_failed` and `tests_passed` are reportable
# end states but the executor may still be working, so they must not close.
#
# `executor_cancelled` closes. A cancelled executor is not going to send
# anything else, and a binding left open after one is the "still looks active
# until it goes stale" reading a cancellation is supposed to replace: staleness
# says nobody has heard from this in a while, which is a different and weaker
# claim than "this stopped".
CLOSING_EVENT_TYPES = {
    "executor_completed",
    "executor_blocked",
    "executor_failed",
    "executor_cancelled",
    "reported_change_not_observed",
}
# What one closed binding means for the wait it was armed against. The wait
# contract (`wait_strategy.WAIT_TERMINAL_STATES`) and this vocabulary are two
# names for one ending, so the mapping is stated once here rather than being
# re-derived by every caller that holds both.
# The observed terminal results a run or wrapper session can hold, mirrored from
# `runtime.records.OBSERVED_RESULTS` and imported rather than restated so a
# fifth terminal result cannot appear there and leave a binding open here.
_OBSERVED_TERMINAL_RESULTS = frozenset(RUNTIME_OBSERVED_RESULTS)
_WAIT_OUTCOME_BY_CLOSING_EVENT = {
    "executor_completed": "completed",
    "executor_blocked": "failed",
    "executor_failed": "failed",
    "executor_cancelled": "cancelled",
    "reported_change_not_observed": "failed",
}
# Where a progress summary came from. Only a summary this repo derived itself,
# by parsing an executor stream it also hashed, can corroborate that executor's
# own end-state narration; a summary assembled from the caller's arguments is
# the same act of narration in a second field and corroborates nothing.
PARSED_STREAM_SUMMARY = "parsed_stream"
CALLER_REPORTED_SUMMARY = "caller_reported"
PROGRESS_SUMMARY_SOURCES = (PARSED_STREAM_SUMMARY, CALLER_REPORTED_SUMMARY)
DEFAULT_FRESHNESS_SECONDS = 900
DEFAULT_EXPIRY_SECONDS = 86400
DEFAULT_MINIMUM_REPEAT_INTERVAL_SECONDS = 120
CLAIM_BOUNDARY = (
    "Executor progress is metadata-only observed activity. It is not result, verification, "
    "review, CI, merge-readiness, or merge evidence."
)

# Metadata-only scalars that let a live row answer "which model, how long, how
# many tokens" without carrying any model output. They are identifiers and
# counts, never prompts, reasoning, or transcripts -- `_RAW_OR_HIDDEN_KEYS`
# still rejects those. `routed_reasoning_effort` names an effort *level*
# ("high"), not reasoning content; it survives that check because the check
# compares whole keys, and it must stay a whole-key comparison or this key
# starts failing on the "reasoning" substring.
ROUTING_METRIC_SIGNAL_KEYS = (
    "routed_model",
    "routed_reasoning_effort",
    "tokens_total",
    "elapsed_seconds",
    "category",
    "fallback_count",
    "turn_count",
    "tool_count",
    "cost_usd",
    "tokens_per_second",
    "cache_hit_percentage",
    "context_percentage",
)

_RAW_OR_HIDDEN_KEYS = {
    "analysis",
    "chain_of_thought",
    "cot",
    "hidden",
    "hidden_reasoning",
    "raw",
    "raw_log",
    "raw_logs",
    "raw_output",
    "reasoning",
    "think",
    "thinking",
    "transcript",
}


class ExecutorProgressError(ValueError):
    pass


def normalize_executor_profile(value: str, *, observed_hermes_execution: bool = False) -> str:
    normalized = value.strip().casefold().replace("_", "-")
    aliases = {
        "codex": "codex",
        "claude": "claude_code",
        "claude-code": "claude_code",
        "claude-code-cli": "claude_code",
        "claude_code": "claude_code",
        # The omo host CLIs collapse into one lane. `normalized` has already
        # folded "_" to "-", so "omo_runtime" arrives here as "omo-runtime".
        "omo-runtime": "omo_runtime",
        "pi": "omo_runtime",
        "senpi": "omo_runtime",
        "opencode": "omo_runtime",
    }
    if normalized == "hermes":
        if observed_hermes_execution:
            return "hermes_local"
        raise ExecutorProgressError("Hermes orchestration is not an active executor; use hermes_local only for observed local execution")
    if normalized in {"hermes-local", "hermes_local"}:
        if observed_hermes_execution:
            return "hermes_local"
        raise ExecutorProgressError("hermes_local requires explicit observed local execution evidence")
    profile = aliases.get(normalized, "")
    if profile not in ALLOWED_EXECUTOR_PROFILES:
        # The rejection says WHICH kind of unsupported this is. A known fanout
        # owner without a progress lane (omx-runtime, omc-runtime, generic) and
        # a name this repo has never heard of both stop here, but only the
        # first is answerable today, and only `owner_progress_normalization`
        # can answer it -- with a visible record instead of this exception.
        detail = (
            " (a known fanout owner with no progress lane; owner_progress_normalization returns a visible"
            " unmapped record for it)"
            if is_known_owner(value)
            else ""
        )
        raise ExecutorProgressError(f"unsupported executor profile for progress: {value}{detail}")
    return profile


def progress_dir_for_target(paths: OmhPaths, target_type: str, target_id: str) -> Path:
    target_id = _validated_target_id(target_id)
    if target_type == "run":
        return paths.runtime_runs_dir / target_id / "executor_progress"
    if target_type == "wrapper_session":
        return paths.runtime_wrapper_sessions_dir / target_id / "executor_progress"
    raise ExecutorProgressError(f"unsupported progress target type: {target_type}")


def _validated_target_id(value: str) -> str:
    target_id = value.strip()
    if (
        not target_id
        or target_id in {".", ".."}
        or "/" in target_id
        or "\\" in target_id
        or "\x00" in target_id
    ):
        raise ExecutorProgressError("target_id must be one safe path segment")
    return target_id


def binding_id_for(target_type: str, target_id: str, executor_profile: str) -> str:
    return f"{target_type}:{target_id}:{executor_profile}"


def progress_instance_id_for(binding_id: str) -> str:
    return f"{binding_id}:{uuid.uuid4().hex[:16]}"


def build_progress_binding(
    *,
    target_type: str,
    target_id: str,
    executor_profile: str,
    now: str | None = None,
    state: str = "active",
    existing_correlation_root: str = "",
    codex_session_ref: str = "",
    codex_thread_ref: str = "",
    claude_session_ref: str = "",
    process_session_id: str = "",
    worktree: str = "",
    branch: str = "",
    pid: int | str | None = None,
    source: str = "",
    channel_ref: str = "",
    thread_ref: str = "",
    delivery_target: str = "",
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    observed_hermes_execution: bool = False,
    freshness_seconds: int = DEFAULT_FRESHNESS_SECONDS,
    expiry_seconds: int = DEFAULT_EXPIRY_SECONDS,
    minimum_repeat_interval_seconds: int = DEFAULT_MINIMUM_REPEAT_INTERVAL_SECONDS,
) -> dict[str, Any]:
    target_type = target_type.strip()
    target_id = _validated_target_id(target_id)
    if target_type not in TARGET_TYPES:
        raise ExecutorProgressError(f"target_type must be one of {', '.join(TARGET_TYPES)}")
    profile = normalize_executor_profile(executor_profile, observed_hermes_execution=observed_hermes_execution)
    timestamp = now or utc_now()
    binding_id = binding_id_for(target_type, target_id, profile)
    instance_id = progress_instance_id_for(binding_id)
    aliases = _correlation_aliases(
        codex_session_ref=codex_session_ref,
        codex_thread_ref=codex_thread_ref,
        claude_session_ref=claude_session_ref,
        process_session_id=process_session_id,
        worktree=worktree,
        branch=branch,
    )
    binding = {
        "schema_version": EXECUTOR_PROGRESS_BINDING_SCHEMA_VERSION,
        "binding_id": binding_id,
        "instance_id": instance_id,
        "target": {"type": target_type, "id": target_id},
        "target_type": target_type,
        "target_id": target_id,
        "executor": profile,
        "executor_profile": profile,
        "correlation_root": existing_correlation_root
        or correlation_root_for(
            binding_id=binding_id,
            instance_id=instance_id,
            codex_session_ref=codex_session_ref,
            codex_thread_ref=codex_thread_ref,
            claude_session_ref=claude_session_ref,
            process_session_id=process_session_id,
            worktree=worktree,
            branch=branch,
        ),
        "correlation_aliases": aliases,
        "process": _clean_object(
            {
                "process_session_id": process_session_id.strip(),
                "pid": _optional_pid(pid),
                "worktree": worktree.strip(),
                "branch": branch.strip(),
            }
        ),
        "delivery": _clean_object(
            {
                "source": source.strip(),
                "channel_ref": channel_ref.strip(),
                "thread_ref": thread_ref.strip(),
                "delivery_target": delivery_target.strip(),
            }
        ),
        "state": state,
        "created_at": timestamp,
        "updated_at": timestamp,
        "last_observed_at": timestamp,
        "last_reported_at": "",
        "last_observed_signal_hash": "",
        "last_observed_event_count": 0,
        "last_observed_artifact_sha256": "",
        "freshness_seconds": int(freshness_seconds),
        "expiry_seconds": int(expiry_seconds),
        "last_transition_fingerprint": "",
        "last_reported_event_type": "",
        "last_reported_state": "",
        "last_reported_summary_hash": "",
        "last_reported_artifact_sha256": "",
        "report_count": 0,
        "reported_event_types": [],
        "suppressed_duplicate_count": 0,
        "minimum_repeat_interval_seconds": int(minimum_repeat_interval_seconds),
        "evidence_refs": _compact_strings(evidence_refs or []),
        "privacy": "metadata_only",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    _require_valid("binding", validate_progress_binding(binding))
    return binding


def correlation_root_for(
    *,
    binding_id: str,
    instance_id: str = "",
    existing_correlation_root: str = "",
    codex_session_ref: str = "",
    codex_thread_ref: str = "",
    claude_session_ref: str = "",
    process_session_id: str = "",
    worktree: str = "",
    branch: str = "",
) -> str:
    if existing_correlation_root.strip():
        return existing_correlation_root.strip()
    if claude_session_ref.strip():
        return f"claude_session:{claude_session_ref.strip()}"
    if codex_session_ref.strip():
        return f"codex_session:{codex_session_ref.strip()}"
    if codex_thread_ref.strip():
        return f"codex_thread:{codex_thread_ref.strip()}"
    if process_session_id.strip():
        return f"process_session:{process_session_id.strip()}"
    if instance_id.strip():
        return f"binding_instance:{instance_id.strip()}"
    return f"binding:{binding_id}"


def write_progress_binding(paths: OmhPaths, binding: dict[str, Any]) -> dict[str, Any]:
    _require_valid("binding", validate_progress_binding(binding))
    target = _binding_target(binding)
    progress_dir = progress_dir_for_target(paths, target["type"], target["id"])
    ensure_dir(progress_dir, private=True)
    atomic_write_json(progress_dir / "binding.json", binding, private=True)
    return binding


def read_progress_binding(paths: OmhPaths, target_type: str, target_id: str) -> dict[str, Any] | None:
    binding = read_json_object(progress_dir_for_target(paths, target_type, target_id) / "binding.json")
    if not binding:
        return None
    _require_valid("binding", validate_progress_binding(binding))
    return binding


def list_progress_bindings(paths: OmhPaths, *, limit: int | None = None) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for root, target_type in (
        (paths.runtime_runs_dir, "run"),
        (paths.runtime_wrapper_sessions_dir, "wrapper_session"),
    ):
        if not root.exists():
            continue
        for binding_path in sorted(root.glob("*/executor_progress/binding.json")):
            try:
                binding = read_json_object(binding_path)
                if not binding:
                    continue
                _require_valid("binding", validate_progress_binding(binding))
            except (OSError, ValueError, ExecutorProgressError):
                continue
            target = _binding_target(binding)
            if target["type"] == target_type:
                bindings.append(binding)
    bindings.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
    if limit is not None:
        return bindings[: max(0, limit)]
    return bindings


def build_progress_event(
    binding: dict[str, Any],
    *,
    event_type: str,
    status: str = "",
    summary: str = "",
    observed_at: str | None = None,
    severity: str = "info",
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    signal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_valid("binding", validate_progress_binding(binding))
    if event_type not in PROGRESS_EVENT_TYPES:
        raise ExecutorProgressError(f"unsupported progress event type: {event_type}")
    timestamp = observed_at or utc_now()
    event = {
        "schema_version": EXECUTOR_PROGRESS_EVENT_SCHEMA_VERSION,
        "binding_id": str(binding["binding_id"]),
        "instance_id": str(binding["instance_id"]),
        "target": dict(binding["target"]),
        "target_type": binding["target_type"],
        "target_id": binding["target_id"],
        "executor": binding["executor_profile"],
        "executor_profile": binding["executor_profile"],
        "correlation_root": binding["correlation_root"],
        "event_type": event_type,
        "status": status or _status_for_event_type(event_type),
        "severity": severity,
        "summary": _compact_text(
            _sanitize_progress_copy(summary) or _summary_for_event_type(event_type),
            280,
        ),
        "observed_at": timestamp,
        "evidence_refs": _compact_strings(evidence_refs or binding.get("evidence_refs", [])),
        "signal": _safe_signal(signal or {}),
        "privacy": "metadata_only",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    event["transition_fingerprint"] = transition_fingerprint(event)
    _require_valid("event", validate_progress_event(event))
    return event


_ROUTING_CATEGORIES = frozenset(
    {
        "architect",
        "artistry",
        "deep",
        "quick",
        "unspecified-high",
        "unspecified-low",
        "ultrabrain",
        "visual-engineering",
        "writing",
    }
)


def _observed_category(value: str) -> str:
    category = str(value or "").strip()
    return category if category in _ROUTING_CATEGORIES else ""


def build_safe_progress_signal(
    *,
    executor_profile: str,
    process_status: str = "",
    codex_progress_summary: dict[str, Any] | None = None,
    profile_progress_summary: dict[str, Any] | None = None,
    git_status_short: str | None = None,
    git_diff_stat: str | None = None,
    explicit_event_type: str = "",
    explicit_summary: str = "",
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    observed_hermes_execution: bool = False,
    routed_model: str = "",
    routed_reasoning_effort: str = "",
    tokens_total: int | None = None,
    elapsed_seconds: int | None = None,
    category: str = "",
    fallback_count: int | None = None,
    turn_count: int | None = None,
    tool_count: int | None = None,
    cost_usd: float | None = None,
    tokens_per_second: float | None = None,
    cache_hit_percentage: float | None = None,
    context_percentage: float | None = None,
) -> dict[str, Any]:
    profile = normalize_executor_profile(executor_profile, observed_hermes_execution=observed_hermes_execution)
    codex_profile = profile == "codex"
    summary_input = codex_progress_summary if codex_profile else profile_progress_summary
    progress = _safe_progress_summary(summary_input, codex_profile=codex_profile)
    # A caller-declared event is an owner word like any other, so it goes
    # through the same normalizer rather than a hand-rolled membership test.
    # The old test RAISED, which dropped the whole observation: the caller was
    # told nothing, and no record survived to say a word had been refused.
    # Normalizing keeps the observation and keeps the word -- an unrecognized
    # one becomes `unmapped_source_event` with the raw retained beside it.
    explicit_source = explicit_event_type.strip()
    explicit_normalization = normalize_owner_progress_event(profile, explicit_source)
    explicit = str(explicit_normalization["normalized_event"]) if explicit_source else ""
    signal = {
        "executor_profile": profile,
        "process_status": _compact_text(process_status, 80),
        "git_status_hash": _hash_if_present(git_status_short or ""),
        "git_diff_stat_hash": _hash_if_present(git_diff_stat or ""),
        # A missing hash is ambiguous on its own: the caller may have looked at
        # git and seen nothing, or may never have looked. Only the first case
        # can contradict a reported change, so record which one it was.
        "git_observed": git_status_short is not None or git_diff_stat is not None,
        # WHERE the summary block below came from, recorded because the ladder's
        # answer depends on it. A codex summary is derived by `codex_progress`
        # from a stream this repo parsed and hashed; every other profile's
        # summary is built verbatim from the caller's own `--profile-*`
        # arguments. Without this key the two are indistinguishable once
        # written, and the caller's word reads as an observation.
        "progress_summary_source": _progress_summary_source(summary_input, codex_profile=codex_profile),
        "progress_status": progress.get("status", ""),
        "progress_event_count": progress.get("event_count", 0),
        "latest_progress_event_type": progress.get("latest_progress_event_type", ""),
        "observable_activity": progress.get("observable_activity", []),
        "assistant_visible_summary": progress.get("assistant_visible_summary", ""),
        "progress_snapshot_hash": progress.get("summary_hash", ""),
        "codex_artifact_sha256": progress.get("artifact_sha256", "") if profile == "codex" else "",
        "codex_artifact_byte_count": progress.get("artifact_byte_count", 0) if profile == "codex" else 0,
        "codex_malformed_event_count": progress.get("malformed_event_count", 0) if profile == "codex" else 0,
        "explicit_event_type": explicit,
        # The word the caller actually said, kept only when the vocabulary
        # could not map it. Without this the signal would record
        # `unmapped_source_event` and nothing else, which names the failure but
        # not the input that caused it. `_safe_signal` drops it when empty, so
        # a mapped event carries no extra key.
        "unmapped_source_event": str(explicit_normalization["source_event"])
        if explicit == UNMAPPED_NORMALIZED_EVENT
        else "",
        # The raw explicit word when the normalizer TRANSLATED it -- an owner
        # word (`workflow_completed`, `result`, `turn.completed`) that the
        # caller passed as its own declared event. `--event` is bounded to this
        # repo's vocabulary, so only a library caller can arrive here, and the
        # translated word is owner narration wearing the caller's hat: the lane
        # has to be able to tell it apart from a caller that stated the OMH
        # word itself. Empty (and dropped) when the caller's word already WAS
        # the normalized event.
        "explicit_source_event": explicit_source
        if explicit and explicit != UNMAPPED_NORMALIZED_EVENT and explicit != explicit_source
        else "",
        "explicit_summary": _compact_text(_sanitize_progress_copy(explicit_summary), 280),
        "evidence_ref_count": len(evidence_refs or []),
        # The routed model is what a live row needs to answer "which model is
        # this"; the runtime alone cannot, because one profile (omo_runtime
        # especially) fronts many models.
        "routed_model": _compact_text(routed_model, 120),
        "routed_reasoning_effort": _compact_text(routed_reasoning_effort, 40),
        "tokens_total": _observed_count(tokens_total),
        "elapsed_seconds": _observed_count(elapsed_seconds),
        "category": _observed_category(category),
        "fallback_count": _observed_count(fallback_count),
        "turn_count": _observed_count(turn_count),
        "tool_count": _observed_count(tool_count),
        "cost_usd": _observed_number(cost_usd),
        "tokens_per_second": _observed_number(tokens_per_second),
        "cache_hit_percentage": _observed_percentage(cache_hit_percentage),
        "context_percentage": _observed_percentage(context_percentage),
    }
    return _safe_signal(signal)


# Only a confirmed edit counts as a claim worth contradicting. "Codex changed
# files." comes from a bucket that also matches a line merely mentioning a diff,
# so it stays out: over-matching is free for the benign `diff_started` label and
# expensive here.
_CHANGE_CLAIM_ACTIVITY = {"Codex applied a file change."}
# An explicit `--event diff_started` is the caller stating the claim outright.
_CHANGE_CLAIM_EVENT_TYPES = {"diff_started"}
_SUCCESS_PROCESS_STATUSES = {"completed", "complete", "done", "success", "succeeded", "exited_zero"}
_FAILURE_PROCESS_STATUSES = {"failed", "failure", "error", "errored", "exited_nonzero"}
# Process outcomes the HOST observed, not words an executor chose. Each one
# names a stop that something outside the executor performed: the operator
# interrupted the batch, a supervisor sent a signal, the dispatcher terminated
# the unit group. This is the only corroboration a cancellation can have --
# nothing an executor says about itself reaches `executor_cancelled` without one
# of these, exactly as no executor reaches `executor_completed` on its own word.
_CANCELLED_PROCESS_STATUSES = {
    "cancelled",
    "canceled",
    "interrupted",
    "killed",
    "signal_terminated",
    "terminated",
}
_BLOCKED_PROCESS_STATUSES = {"blocked", "blocker"}

# Everything that can corroborate an owner's own end-state narration, and
# nothing that IS that narration. `process_status` is the state of the process
# the wrapper spawned; `progress_status` is the verdict a progress summary
# reached about the stream and the activity lines are past-tense observations,
# but both of those only corroborate when THIS repo derived them from a parsed
# stream (`PARSED_STREAM_SUMMARY`) rather than being handed them by the caller.
# `latest_progress_event_type` is deliberately absent: it is the word being
# corroborated.
_END_STATE_PROGRESS_STATUSES = {"completed_or_passed_observed", "failed_or_error_observed", "blocked"}
_END_STATE_PROCESS_STATUSES = {
    *_SUCCESS_PROCESS_STATUSES,
    *_FAILURE_PROCESS_STATUSES,
    *_BLOCKED_PROCESS_STATUSES,
    *_CANCELLED_PROCESS_STATUSES,
}
# Past tense only. "Codex is running tests." says a run started, which cannot
# corroborate that one finished.
_END_STATE_ACTIVITY = {"Codex ran tests."}


def _change_reported_but_not_observed(
    signal: dict[str, Any],
    *,
    latest: str,
    activity: set[str],
    process_status: str,
    progress_status: str,
) -> bool:
    """The executor finished claiming it changed files, and the tree disagrees.

    Three guards, each load-bearing:

    `git_observed` -- without it a missing hash only means nobody looked, so a
    mismatch inferred from it would cry wolf on every caller that does not
    collect git state.

    A finished run -- the upstream change claim is a coarse bucket. Codex sets
    it from any log line containing `patch`, `write`, `edit`, or `diff`, so a
    mid-flight "let me run git diff to see the state" reads as a change claim
    against a tree that is legitimately still clean. Only a run that has stopped
    can actually contradict itself, and `progress_status` arrives here already
    blanked when it was the caller's own claim that the run had stopped: this
    label closes a binding, so its "finished" leg has to be observed too.

    An empty tree -- both hashes absent.
    """
    if not bool(signal.get("git_observed", False)):
        return False
    finished = process_status in _SUCCESS_PROCESS_STATUSES or progress_status == "completed_or_passed_observed"
    if not finished:
        return False
    if not (latest in _CHANGE_CLAIM_EVENT_TYPES or activity.intersection(_CHANGE_CLAIM_ACTIVITY)):
        return False
    return not signal.get("git_status_hash") and not signal.get("git_diff_stat_hash")


def _normalize_signal_source_event(signal: dict[str, Any], source_event: str) -> dict[str, object]:
    """The normalization record for one owner word carried by this signal.

    The owner comes from the signal itself, so the same word is allowed to mean
    different things for different owners. A signal that names no owner falls
    back to the dialect every lane-carrying owner SHARES: that is not a guess,
    because a shared word means the same thing whichever of them said it, and
    the shared resolver caps it at the strictest ceiling any of them carries.
    Refusing to answer instead would silently weaken re-inference over a stored
    signal whose profile did not survive the round trip.
    """
    owner = str(signal.get("executor_profile", "")).strip()
    if not owner:
        return normalize_shared_progress_event(source_event)
    return normalize_owner_progress_event(owner, source_event)


def _normalized_source_event(signal: dict[str, Any], source_event: str) -> str:
    """Just the normalized event name for one owner word carried by this signal."""
    return str(_normalize_signal_source_event(signal, source_event)["normalized_event"])


def _progress_summary_source(summary: dict[str, Any] | None, *, codex_profile: bool) -> str:
    """Which kind of progress summary this signal carries, or "" when it carries none.

    The codex path is the one that earns `parsed_stream`: its summary is built
    by `codex_progress` from a JSONL stream this repo read, counted, and hashed
    (`codex_artifact_sha256`), and `_safe_progress_summary` refuses anything not
    stamped `codex_progress_summary/v1`. Every other profile's summary is
    assembled in `commands.runtime._profile_progress_summary` out of the
    caller's own `--profile-*` arguments, so it is `caller_reported` no matter
    how confident its wording is.
    """
    if not isinstance(summary, dict):
        return ""
    return PARSED_STREAM_SUMMARY if codex_profile else CALLER_REPORTED_SUMMARY


def _summary_parsed_by_omh(signal: dict[str, Any]) -> bool:
    """True only when this repo derived the summary itself.

    Fail-closed on absence: a signal without the marker -- hand-built, or
    written before the marker existed -- is treated as caller-reported, because
    the alternative is to grant corroborating standing to a field whose
    provenance nobody recorded.
    """
    return str(signal.get("progress_summary_source", "")) == PARSED_STREAM_SUMMARY


def _signal_activity(signal: dict[str, Any]) -> set[str]:
    activity = signal.get("observable_activity")
    return set(activity) if isinstance(activity, list) else set()


def _end_state_corroborated(
    *,
    progress_status: str,
    process_status: str,
    activity: set[str],
    summary_parsed_by_omh: bool,
) -> bool:
    """True when something the LANE observed says the run reached an end state.

    The rule this enforces is narrower than "not the narrated event type", which
    was the previous reading and left the leak this closes: for every profile
    whose summary is built from the caller's arguments, the same
    `omh runtime progress observe` invocation supplied both the narration word
    and the `progress_status` that corroborated it, so the caller corroborated
    itself and closed its own binding.

    What survives as corroboration is what OMH observes rather than is told:
    the state of the process (`process_status`), and -- only when this repo
    parsed the stream itself -- the summary's own verdict and its past-tense
    activity lines. Git facts corroborate elsewhere (`_change_reported_but_not
    _observed`), where a clean tree CONTRADICTS a claim rather than granting it.
    """
    if summary_parsed_by_omh and (
        progress_status in _END_STATE_PROGRESS_STATUSES or bool(activity.intersection(_END_STATE_ACTIVITY))
    ):
        return True
    return process_status in _END_STATE_PROCESS_STATUSES


def _claims_an_end_state(signal: dict[str, Any], *, normalized_latest: str) -> bool:
    """Everything in one observation that asserts the run ended, in the caller's own words.

    Three fields, one act. The narrated event type is the obvious one; the
    summary's `status` is the same claim one field down; and an explicit event
    the normalizer TRANSLATED out of an owner word is that word again, declared
    through `--event`. A caller that states this repo's own vocabulary
    (`--event executor_completed`) is deliberately absent -- see
    `infer_progress_event_type`.
    """
    return (
        normalized_latest in TERMINAL_EVENT_TYPES
        or str(signal.get("progress_status", "")) in _END_STATE_PROGRESS_STATUSES
        or (
            bool(str(signal.get("explicit_source_event", "")))
            and str(signal.get("explicit_event_type", "")) in TERMINAL_EVENT_TYPES
        )
    )


def _self_reported_end_state(signal: dict[str, Any]) -> bool:
    """True when the only support for an end state is what the caller said.

    Shared by the ladder, which withholds the end state, and by
    `progress_event_normalization`, which has to say why, so the verdict and its
    stated reason cannot drift apart.
    """
    normalized_latest = _normalized_source_event(signal, str(signal.get("latest_progress_event_type", "")))
    if not _claims_an_end_state(signal, normalized_latest=normalized_latest):
        return False
    return not _end_state_corroborated(
        progress_status=str(signal.get("progress_status", "")),
        process_status=str(signal.get("process_status", "")).casefold(),
        activity=_signal_activity(signal),
        summary_parsed_by_omh=_summary_parsed_by_omh(signal),
    )


def infer_progress_event_type(signal: dict[str, Any]) -> str:
    """Classify a safe progress signal into one normalized event type.

    A thin adapter over `owner_progress_normalization` for everything that is
    an owner WORD, plus the ordering that only this module can own: liveness
    and claim/observation conflicts are read from process status, observable
    activity, and git hashes, which are not vocabulary at all. The order is
    load-bearing -- blocked and failed outrank the claim mismatch, which
    outranks the benign completion reading.

    One rule sits above the ladder: an END STATE is the lane's verdict, never
    the owner's, and the owner does not get to be its own witness. Everything in
    one observation that ASSERTS an end state -- the narrated event type, the
    summary's own `status`, and an explicit event the normalizer translated out
    of an owner word -- is admitted only when `_end_state_corroborated` finds
    something the lane OBSERVED agreeing; otherwise all of it is held back and
    the observation lands on `unmapped_source_event`, which is visible, keeps
    the raw word readable in `latest_progress_event_type`, and -- unlike
    `executor_completed` -- neither ends nor closes anything. Without that rule
    a wrapper that merely narrated `workflow_completed` (or a codex
    `turn.completed`, or a claude-code `result` envelope) closed its own
    binding while the executor was still running; and with the rule applied to
    the event type alone, the same single `omh runtime progress observe` call
    still closed it by passing `--profile-status completed_or_passed_observed`
    beside the word, because that status was read as an independent witness
    when it is the caller's own sentence in a second field. Rounding any of it
    to `progress_observed` instead would hide the word, which is the collapse
    this whole lane exists to stop.

    One caller statement is deliberately still authoritative: an explicit
    `--event` naming this repo's own vocabulary. That is the caller declaring
    the observation in OMH's terms and standing behind it -- the same standing
    `_CHANGE_CLAIM_EVENT_TYPES` gives an explicit `diff_started`, and the
    standing the wrapper's observed-result path (`record_codex_result`, behind
    `omh coding lifecycle result`) depends on. `--event` choices are
    bounded to `PROGRESS_EVENT_TYPES`, so an executor's own end-state word
    cannot be relayed through it verbatim; when a library caller passes one
    anyway, `explicit_source_event` records the translation and the rule above
    applies to it.
    """
    progress_status = str(signal.get("progress_status", ""))
    latest = str(signal.get("latest_progress_event_type", ""))
    normalized_latest = _normalized_source_event(signal, latest)
    activity = _signal_activity(signal)
    process_status = str(signal.get("process_status", "")).casefold()
    test_activity = bool(activity.intersection({"Codex ran tests.", "Codex is running tests."}))
    inspect_activity = bool(activity.intersection({"Codex inspected the repo.", "Codex is inspecting files/tests."}))
    end_state_observed = _end_state_corroborated(
        progress_status=progress_status,
        process_status=process_status,
        activity=activity,
        summary_parsed_by_omh=_summary_parsed_by_omh(signal),
    )
    self_reported_end_state = not end_state_observed and _claims_an_end_state(
        signal,
        normalized_latest=normalized_latest,
    )
    explicit = str(signal.get("explicit_event_type", ""))
    if explicit:
        if self_reported_end_state and str(signal.get("explicit_source_event", "")):
            # An owner word declared through `--event`. It is the executor's
            # sentence either way, so it gets the executor's treatment.
            return UNMAPPED_NORMALIZED_EVENT
        # `build_safe_progress_signal` already normalized it, so the common path
        # is a membership check; a hand-built signal is normalized here.
        return explicit if explicit in PROGRESS_EVENT_TYPES else _normalized_source_event(signal, explicit)
    # The owner's word as the ladder is allowed to read it, and the summary's
    # own verdict beside it. Both are blanked only when they would end something
    # on the caller's say-so; a non-terminal word is never withheld, because
    # nothing about it needs corroborating.
    narrated = "" if self_reported_end_state else normalized_latest
    verdict = "" if self_reported_end_state and progress_status in _END_STATE_PROGRESS_STATUSES else progress_status
    # Ahead of blocked and failed, because an observed cancellation explains
    # both of the shapes they would otherwise claim. A group-terminated child
    # exits non-zero, so a lane reading only the exit code files an operator's
    # own stop as a model failure and sends the next reader looking for a defect
    # that does not exist. Only the host's observed process outcome gets here:
    # `narrated` is already blank whenever the word was the executor's alone.
    if process_status in _CANCELLED_PROCESS_STATUSES or narrated == "executor_cancelled":
        return "executor_cancelled"
    if narrated == "executor_blocked" or verdict == "blocked" or process_status in _BLOCKED_PROCESS_STATUSES:
        return "executor_blocked"
    if verdict == "failed_or_error_observed" or narrated == "tests_failed":
        return "tests_failed" if test_activity or narrated == "tests_failed" else "executor_failed"
    if narrated == "executor_failed" or process_status in _FAILURE_PROCESS_STATUSES:
        return "executor_failed"
    # After blocked/failed, before completed. A blocker whose text also mentions
    # a patch is a blocker, not a contradiction, and blocked/failed carry the
    # more actionable classification. What this preempts is the benign reading:
    # a run that claims it changed files and is about to be called completed.
    if _change_reported_but_not_observed(
        signal,
        latest=latest,
        activity=activity,
        process_status=process_status,
        progress_status=verdict,
    ):
        return "reported_change_not_observed"
    if verdict == "completed_or_passed_observed":
        return "tests_passed" if (test_activity or narrated == "tests_passed") else "executor_completed"
    if narrated == "tests_passed":
        return "tests_passed"
    if narrated == "tests_started" or test_activity:
        return "tests_started"
    if narrated == "diff_started" or signal.get("git_diff_stat_hash") or signal.get("git_status_hash"):
        return "diff_started"
    if "Codex changed files." in activity:
        return "diff_started"
    if inspect_activity:
        return "repo_exploration"
    if process_status in {"completed", "complete", "done", "success", "succeeded", "exited_zero"}:
        return "executor_completed"
    if process_status in {"dispatched", "launched", "started", "spawned"}:
        return "executor_dispatched"
    if process_status in {"running", "active", "in_progress", "working"}:
        return "running_no_diff_observed"
    # The owner said something and nothing above read anything more specific
    # from liveness, activity, or git. Falling through to `progress_observed`
    # here used to discard the word silently -- including a word this
    # vocabulary does not know, which then read as ordinary observed progress.
    # Deferring to the normalized word keeps a mapped one (and can never
    # outrank what it declared) and surfaces an unmapped one as itself; the raw
    # value stays readable in the signal's `latest_progress_event_type`.
    if self_reported_end_state:
        # The claim DOES map -- to an end state nothing observed supports.
        # Emitting it would let the caller close its own binding, so the
        # observation is reported as the one event type that ends nothing. This
        # also catches the shape that carries no word at all, a bare
        # `--profile-status completed_or_passed_observed`: reporting that as
        # `progress_observed` would drop the caller's claim silently.
        return UNMAPPED_NORMALIZED_EVENT
    if latest:
        return normalized_latest
    return "progress_observed"


def progress_event_normalization(event: dict[str, Any]) -> dict[str, object]:
    """Read-only: the normalization record behind one stored progress event.

    Returns `{}` for every event type other than `unmapped_source_event`,
    because for those the event type IS the answer and a record restating it
    would be noise on every row. For an unmapped one it recovers what an
    operator otherwise cannot get: the raw word, the confidence, the closed
    note that says WHY, and the two evidence tiers the decision compared.

    Pure: it re-derives from the stored signal rather than reading anything the
    event does not already carry, so an event read back off disk explains itself
    the same way it did when it was written.

    Two different refusals reach the same event type and must not read the same.
    The pure normalizer answers the first (the word is not in this owner's
    dialect, or its stream cannot carry the tier). The second belongs to the
    lane: the word maps perfectly well, and `infer_progress_event_type` refused
    it because nothing the lane observed corroborated the end state it claims.
    Only the signal can tell those apart, so the lane stamps its own note here,
    from the same `_self_reported_end_state` predicate that produced the verdict
    -- including the shape that carried no word at all and claimed the end state
    through the summary's `status` alone, where the pure normalizer can only
    report that nothing was said.
    """
    if str(event.get("event_type", "")) != UNMAPPED_NORMALIZED_EVENT:
        return {}
    signal = event.get("signal")
    signal = signal if isinstance(signal, dict) else {}
    source_event = str(
        signal.get("unmapped_source_event", "")
        or signal.get("latest_progress_event_type", "")
        or signal.get("explicit_source_event", "")
        or signal.get("explicit_event_type", "")
    )
    record = dict(_normalize_signal_source_event(signal, source_event))
    # The pure refusal wins when there was a word and the normalizer refused it
    # on its own terms: "this word is not in the owner's dialect" is the more
    # precise answer, and the end-state rule would have refused it anyway. The
    # lane's note is stamped when the word mapped perfectly well, and when the
    # claim arrived with no word at all -- a bare caller-reported end-state
    # `status`, which the pure normalizer can only describe as nothing said.
    if str(record.get("normalized_event", "")) != UNMAPPED_NORMALIZED_EVENT or (
        not source_event and _self_reported_end_state(signal)
    ):
        record["normalized_event"] = UNMAPPED_NORMALIZED_EVENT
        record["normalized_evidence_tier"] = progress_evidence_tier(UNMAPPED_NORMALIZED_EVENT)
        record["mapping_confidence"] = "unmapped"
        record["mapping_note"] = "self_reported_end_state_not_corroborated"
    return record


def summary_for_signal(signal: dict[str, Any], event_type: str) -> str:
    explicit = str(signal.get("explicit_summary", "")).strip()
    if explicit:
        return _sanitize_progress_copy(explicit) or _summary_for_event_type(event_type)
    visible = str(signal.get("assistant_visible_summary", "")).strip()
    if visible and event_type in {
        "repo_exploration",
        "diff_started",
        "tests_started",
        "tests_failed",
        "tests_passed",
        "executor_completed",
        "executor_blocked",
        "executor_failed",
    }:
        return _compact_text(_sanitize_progress_copy(visible) or _summary_for_event_type(event_type), 240)
    return _summary_for_event_type(event_type)


def wait_outcome_for_progress_event(event_type: str) -> str:
    """The `omh_execution_wait_strategy/v1` terminal state one closing event means.

    Returns "" for an event that does not close a binding, so a caller can tell
    "this progress event ends the wait" from "this one does not" without
    restating `CLOSING_EVENT_TYPES`. The two contracts describe one ending from
    two sides: a cancelled executor closes its progress binding here and closes
    its wait as `cancelled` there, and they must not be able to disagree about
    which of the two it was.
    """
    return _WAIT_OUTCOME_BY_CLOSING_EVENT.get(str(event_type), "")


def observe_executor_progress(
    paths: OmhPaths,
    binding: dict[str, Any],
    signal: dict[str, Any],
    *,
    source_language: str = "",
    observed_at: str | None = None,
) -> dict[str, Any]:
    event_type = infer_progress_event_type(signal)
    event = build_progress_event(
        binding,
        event_type=event_type,
        summary=summary_for_signal(signal, event_type),
        observed_at=observed_at,
        evidence_refs=binding.get("evidence_refs", []),
        signal=signal,
    )
    should_report, reason = should_report_event(binding, event, now=observed_at)
    if not should_report:
        updated = update_binding_reporter_state(binding, event, reported=False, reported_at=observed_at)
        write_progress_binding(paths, updated)
        return {
            "schema_version": "omh_executor_progress_observation/v1",
            "binding": updated,
            "event": {},
            "report": {},
            "reported": False,
            "suppressed_reason": reason,
            "reporting_action": "suppress",
            "chat_report": "",
            "claim_boundary": CLAIM_BOUNDARY,
        }
    append_progress_event(paths, binding, event)
    report = build_progress_report(binding, event, source_language=source_language, reported_at=observed_at)
    append_progress_report(paths, binding, report)
    updated = update_binding_reporter_state(binding, event, reported=True, reported_at=report["reported_at"])
    write_progress_binding(paths, updated)
    return {
        "schema_version": "omh_executor_progress_observation/v1",
        "binding": updated,
        "event": event,
        "report": report,
        "reported": True,
        "suppressed_reason": "",
        "reporting_action": "send_report",
        "chat_report": report["summary"],
        "claim_boundary": CLAIM_BOUNDARY,
    }


def compact_suppressed_observation(payload: dict[str, Any]) -> dict[str, Any]:
    """Shrink an observation that reported nothing, for emission only.

    A suppressed observation still returned the whole binding record -- hashes,
    instance ids, correlation aliases, transition fingerprints -- which measured
    at 1,728 of its 2,096 bytes. None of that helps a caller who was just told
    there is nothing to report, and a polling agent pays it on every quiet call.

    Only the emission path is trimmed. `observe_executor_progress` keeps
    returning the full binding, because in-process callers feed it straight back
    into the next observation.
    """
    binding = payload.get("binding") if isinstance(payload.get("binding"), dict) else {}
    return {
        **{key: value for key, value in payload.items() if key != "binding"},
        "binding_ref": {
            "binding_id": str(binding.get("binding_id", "")),
            "target_type": str(binding.get("target_type", "")),
            "target_id": str(binding.get("target_id", "")),
            "executor_profile": str(binding.get("executor_profile", "")),
            "state": str(binding.get("state", "")),
            "report_count": int(binding.get("report_count", 0) or 0),
            "last_reported_event_type": str(binding.get("last_reported_event_type", "")),
        },
        "full_output_hint": "re-run with --full for the complete binding record",
    }


def append_progress_event(paths: OmhPaths, binding: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    _require_valid("binding", validate_progress_binding(binding))
    _require_valid("event", validate_progress_event(event))
    target = _binding_target(binding)
    progress_dir = progress_dir_for_target(paths, target["type"], target["id"])
    ensure_dir(progress_dir, private=True)
    events_path = progress_dir / "events.jsonl"
    ensure_file(events_path, private=True)
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    return event


def latest_progress_event(paths: OmhPaths, binding: dict[str, Any]) -> dict[str, Any]:
    target = _binding_target(binding)
    events, _errors = read_jsonl_objects(progress_dir_for_target(paths, target["type"], target["id"]) / "events.jsonl")
    valid = [event for event in events if not validate_progress_event(event) and _payload_matches_binding_instance(event, binding)]
    return valid[-1] if valid else {}


def build_progress_report(
    binding: dict[str, Any],
    event: dict[str, Any],
    *,
    source_language: str = "",
    reported_at: str | None = None,
) -> dict[str, Any]:
    _require_valid("binding", validate_progress_binding(binding))
    _require_valid("event", validate_progress_event(event))
    sentence = _report_sentence(event, source_language=source_language)
    report = {
        "schema_version": EXECUTOR_PROGRESS_REPORT_SCHEMA_VERSION,
        "binding_id": binding["binding_id"],
        "instance_id": str(binding["instance_id"]),
        "target": dict(binding["target"]),
        "target_type": binding["target_type"],
        "target_id": binding["target_id"],
        "executor": binding["executor_profile"],
        "executor_profile": binding["executor_profile"],
        "correlation_root": binding["correlation_root"],
        "event_type": event["event_type"],
        "status": event["status"],
        "summary": sentence,
        "reported_at": reported_at or utc_now(),
        "event_ref": {
            "event_type": event["event_type"],
            "observed_at": event["observed_at"],
            "transition_fingerprint": event["transition_fingerprint"],
        },
        "privacy": "metadata_only",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    _require_valid("report", validate_progress_report(report))
    return report


def append_progress_report(paths: OmhPaths, binding: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    _require_valid("binding", validate_progress_binding(binding))
    _require_valid("report", validate_progress_report(report))
    target = _binding_target(binding)
    progress_dir = progress_dir_for_target(paths, target["type"], target["id"])
    ensure_dir(progress_dir, private=True)
    reports_path = progress_dir / "reports.jsonl"
    ensure_file(reports_path, private=True)
    with reports_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True) + "\n")
    return report


def latest_progress_report(paths: OmhPaths, binding: dict[str, Any]) -> dict[str, Any]:
    target = _binding_target(binding)
    reports, _errors = read_jsonl_objects(progress_dir_for_target(paths, target["type"], target["id"]) / "reports.jsonl")
    valid = [report for report in reports if not validate_progress_report(report) and _payload_matches_binding_instance(report, binding)]
    return valid[-1] if valid else {}


def reported_event_types(binding: dict[str, Any]) -> list[str]:
    recorded = binding.get("reported_event_types")
    if not isinstance(recorded, list):
        return []
    return [str(value) for value in recorded if str(value)]


def _legacy_reported_seed(binding: dict[str, Any]) -> list[str]:
    """Best-known history for a binding written before `reported_event_types`.

    Migrating with an empty list would discard everything the binding already
    reported, so the next event writes a one-entry list and every other type
    then looks like a first occurrence -- a burst of un-suppression on a run
    already in flight. The last reported type is the only history such a binding
    kept, so seed from it.
    """
    last = str(binding.get("last_reported_event_type", ""))
    if last and int(binding.get("report_count", 0) or 0) > 0:
        return [last]
    return []


def _is_first_occurrence(binding: dict[str, Any], event_type: str) -> bool:
    """True when this event type has never been reported for this binding.

    A first occurrence is always worth reporting: the interesting signal is that
    a new kind of thing happened, and no volume budget should be able to swallow
    it. Callers that add their own suppression on top of `should_report_event`
    must preserve this.

    Bindings written before `reported_event_types` existed cannot answer the
    question. Rather than treat every type as new -- which would un-suppress a
    live run mid-flight -- fall through to the interval rules for them.
    """
    if not isinstance(binding.get("reported_event_types"), list):
        return int(binding.get("report_count", 0) or 0) == 0
    return event_type not in reported_event_types(binding)


def should_report_event(binding: dict[str, Any], event: dict[str, Any], *, now: str | None = None) -> tuple[bool, str]:
    _require_valid("binding", validate_progress_binding(binding))
    _require_valid("event", validate_progress_event(event))
    fingerprint = str(event.get("transition_fingerprint", ""))
    if fingerprint and fingerprint == str(binding.get("last_transition_fingerprint", "")):
        return False, "duplicate_transition"
    event_type = str(event.get("event_type", ""))
    if event_type in TERMINAL_EVENT_TYPES:
        return True, "terminal_or_blocker"
    if _is_first_occurrence(binding, event_type):
        return True, "first_occurrence"
    last_type = str(binding.get("last_reported_event_type", ""))
    if last_type == event_type and not _minimum_interval_elapsed(
        str(binding.get("last_reported_at", "")),
        now or utc_now(),
        int(binding.get("minimum_repeat_interval_seconds", DEFAULT_MINIMUM_REPEAT_INTERVAL_SECONDS) or 0),
    ):
        return False, "repeat_interval"
    return True, "meaningful_transition"


def update_binding_reporter_state(
    binding: dict[str, Any],
    event: dict[str, Any],
    *,
    reported: bool,
    reported_at: str | None = None,
) -> dict[str, Any]:
    _require_valid("binding", validate_progress_binding(binding))
    _require_valid("event", validate_progress_event(event))
    updated = dict(binding)
    now = reported_at or utc_now()
    signal = event.get("signal", {}) if isinstance(event.get("signal"), dict) else {}
    updated["updated_at"] = now
    updated["last_observed_at"] = str(event.get("observed_at", now))
    updated["last_observed_signal_hash"] = _signal_fingerprint(signal)
    updated["last_observed_event_count"] = _safe_int(signal.get("progress_event_count"), 0)
    updated["last_observed_artifact_sha256"] = str(signal.get("codex_artifact_sha256", ""))
    if str(event.get("event_type", "")) in CLOSING_EVENT_TYPES:
        updated["state"] = "closed"
    else:
        updated["state"] = "active"
    if reported:
        event_type = str(event.get("event_type", ""))
        updated["last_reported_at"] = now
        updated["last_transition_fingerprint"] = str(event.get("transition_fingerprint", ""))
        updated["last_reported_event_type"] = event_type
        seen = reported_event_types(binding) or _legacy_reported_seed(binding)
        updated["reported_event_types"] = seen if event_type in seen else [*seen, event_type]
        updated["last_reported_state"] = str(event.get("status", ""))
        updated["last_reported_summary_hash"] = hashlib.sha256(str(event.get("summary", "")).encode("utf-8")).hexdigest()
        updated["last_reported_artifact_sha256"] = str(signal.get("codex_artifact_sha256", ""))
        updated["report_count"] = int(updated.get("report_count", 0) or 0) + 1
    else:
        updated["suppressed_duplicate_count"] = int(updated.get("suppressed_duplicate_count", 0) or 0) + 1
    _require_valid("binding", validate_progress_binding(updated))
    return updated


def refresh_binding_freshness(
    binding: dict[str, Any],
    *,
    now: str | None = None,
    result_status: str = "",
) -> dict[str, Any]:
    _require_valid("binding", validate_progress_binding(binding))
    updated = dict(binding)
    if result_status in _OBSERVED_TERMINAL_RESULTS or updated.get("state") == "closed":
        updated["state"] = "closed"
        return updated
    reference = str(updated.get("last_observed_at") or updated.get("updated_at") or updated.get("created_at") or "")
    age = _seconds_between(reference, now or utc_now())
    if age is None:
        updated["state"] = "stale"
    elif age > int(updated.get("expiry_seconds", DEFAULT_EXPIRY_SECONDS) or DEFAULT_EXPIRY_SECONDS):
        updated["state"] = "expired"
    elif age > int(updated.get("freshness_seconds", DEFAULT_FRESHNESS_SECONDS) or DEFAULT_FRESHNESS_SECONDS):
        updated["state"] = "stale"
    else:
        updated["state"] = "active"
    return updated


def project_active_executor_status(paths: OmhPaths, *, limit: int | None = 50, now: str | None = None) -> dict[str, Any]:
    bindings = [
        refresh_binding_freshness(binding, now=now, result_status=_terminal_result_status(paths, binding))
        for binding in list_progress_bindings(paths, limit=limit)
    ]
    groups: dict[str, list[dict[str, Any]]] = {}
    for binding in bindings:
        if str(binding.get("state", "")) == "expired":
            continue
        groups.setdefault(str(binding.get("correlation_root", "")), []).append(binding)

    active_rows: list[dict[str, Any]] = []
    stale_rows: list[dict[str, Any]] = []
    latest_events: list[dict[str, Any]] = []
    for group in groups.values():
        primary = _choose_primary_binding(group)
        event = _latest_group_payload(paths, group, kind="event")
        report = _latest_group_payload(paths, group, kind="report")
        if not event and not report:
            continue
        if event:
            latest_events.append(_compact_event_projection(event, primary))
        row = _project_binding_row(primary, group, event=event, report=report)
        if str(primary.get("state")) == "active":
            active_rows.append(row)
        elif str(primary.get("state")) == "stale":
            stale_rows.append(row)
    active_rows.sort(key=lambda item: str(item.get("latest_observed_at", "")), reverse=True)
    stale_rows.sort(key=lambda item: str(item.get("latest_observed_at", "")), reverse=True)
    latest_events.sort(key=lambda item: str(item.get("observed_at", "")), reverse=True)
    return {
        "schema_version": "omh_executor_progress_projection/v1",
        "active_executors": active_rows,
        "stale_executors": stale_rows,
        "latest_progress_events": latest_events[: limit or len(latest_events)],
        "claim_boundary": CLAIM_BOUNDARY,
    }


def _unsupported_profile_error() -> str:
    """Render the profile-rejection message from the tuple the check reads.

    All three validators shared a hand-written "codex, claude_code, or
    hermes_local" sentence, so widening the tuple left every message naming a
    profile set that no longer matched what the code accepted.
    """
    return f"executor_profile must be one of {', '.join(ALLOWED_EXECUTOR_PROFILES)}"


def validate_progress_binding(record: dict[str, Any]) -> list[str]:
    errors = _raw_or_hidden_errors(record)
    if record.get("schema_version") != EXECUTOR_PROGRESS_BINDING_SCHEMA_VERSION:
        errors.append("schema_version must be omh_executor_progress_binding/v1")
    target = record.get("target")
    if not isinstance(target, dict):
        errors.append("target must be an object")
        target = {}
    target_type = str(record.get("target_type") or target.get("type") or "")
    target_id = str(record.get("target_id") or target.get("id") or "")
    if target_type not in TARGET_TYPES:
        errors.append("target_type must be run or wrapper_session")
    if not target_id:
        errors.append("target_id is required")
    elif any(separator in target_id for separator in ("/", "\\", "\x00")) or target_id in {".", ".."}:
        errors.append("target_id must be one safe path segment")
    profile = str(record.get("executor_profile") or record.get("executor") or "")
    if profile not in ALLOWED_EXECUTOR_PROFILES:
        errors.append(_unsupported_profile_error())
    if str(record.get("binding_id", "")) != binding_id_for(target_type, target_id, profile):
        errors.append("binding_id must be target_type:target_id:executor_profile")
    if not str(record.get("instance_id", "")).strip():
        errors.append("instance_id is required")
    if not str(record.get("correlation_root", "")):
        errors.append("correlation_root is required")
    if str(record.get("state", "")) not in BINDING_STATES:
        errors.append("state must be active, stale, expired, or closed")
    if "result" in record or "verification" in record or "review" in record or "ci" in record or "merge" in record:
        errors.append("progress binding must not store result, verification, review, CI, or merge evidence")
    if "not result" not in str(record.get("claim_boundary", "")):
        errors.append("claim_boundary must state progress is not result/gate evidence")
    return errors


def validate_progress_event(record: dict[str, Any]) -> list[str]:
    errors = _raw_or_hidden_errors(record)
    if record.get("schema_version") != EXECUTOR_PROGRESS_EVENT_SCHEMA_VERSION:
        errors.append("schema_version must be omh_progress_event/v1")
    if str(record.get("event_type", "")) not in PROGRESS_EVENT_TYPES:
        errors.append("event_type is unsupported")
    if str(record.get("executor_profile", "")) not in ALLOWED_EXECUTOR_PROFILES:
        errors.append(_unsupported_profile_error())
    if not str(record.get("binding_id", "")):
        errors.append("binding_id is required")
    if not str(record.get("instance_id", "")).strip():
        errors.append("instance_id is required")
    if not str(record.get("summary", "")).strip():
        errors.append("summary is required")
    if not str(record.get("transition_fingerprint", "")):
        errors.append("transition_fingerprint is required")
    if "not result" not in str(record.get("claim_boundary", "")):
        errors.append("claim_boundary must state progress is not result/gate evidence")
    return errors


def validate_progress_report(record: dict[str, Any]) -> list[str]:
    errors = _raw_or_hidden_errors(record)
    if record.get("schema_version") != EXECUTOR_PROGRESS_REPORT_SCHEMA_VERSION:
        errors.append("schema_version must be omh_progress_report/v1")
    if str(record.get("executor_profile", "")) not in ALLOWED_EXECUTOR_PROFILES:
        errors.append(_unsupported_profile_error())
    if not str(record.get("binding_id", "")):
        errors.append("binding_id is required")
    if not str(record.get("instance_id", "")).strip():
        errors.append("instance_id is required")
    if not str(record.get("summary", "")).strip():
        errors.append("summary is required")
    if len(str(record.get("summary", ""))) > 360:
        errors.append("summary must be compact")
    if "not result" not in str(record.get("claim_boundary", "")):
        errors.append("claim_boundary must state progress is not result/gate evidence")
    return errors


def transition_fingerprint(event: dict[str, Any]) -> str:
    signal = event.get("signal", {}) if isinstance(event.get("signal"), dict) else {}
    payload = {
        "event_type": event.get("event_type", ""),
        "status": event.get("status", ""),
        "summary": event.get("summary", ""),
        "evidence_refs": event.get("evidence_refs", []),
        "signal_hashes": {
            key: signal.get(key)
            for key in (
                "git_status_hash",
                "git_diff_stat_hash",
                "progress_status",
                "progress_event_count",
                "latest_progress_event_type",
                "progress_snapshot_hash",
                "codex_artifact_sha256",
                # A moved token counter IS a transition: without it, a unit's
                # mid-run token updates (identical type, status, and summary)
                # collapse into `duplicate_transition` after the first one and
                # the HUD row's count freezes. Lanes that do not want
                # token-drift cadence are still gated by their binding's
                # `minimum_repeat_interval_seconds`.
                "tokens_total",
            )
            if signal.get(key) not in (None, "")
        },
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _choose_primary_binding(group: list[dict[str, Any]]) -> dict[str, Any]:
    def key(binding: dict[str, Any]) -> tuple[int, str]:
        target_type = str(binding.get("target_type", ""))
        state = str(binding.get("state", ""))
        precedence = {
            ("wrapper_session", "active"): 5,
            ("run", "active"): 4,
            ("wrapper_session", "stale"): 3,
            ("run", "stale"): 2,
        }.get((target_type, state), 1)
        return precedence, str(binding.get("updated_at", ""))

    return sorted(group, key=key, reverse=True)[0]


def _latest_group_payload(paths: OmhPaths, group: list[dict[str, Any]], *, kind: str) -> dict[str, Any]:
    payloads = []
    for binding in group:
        payload = latest_progress_event(paths, binding) if kind == "event" else latest_progress_report(paths, binding)
        if payload:
            payloads.append(payload)
    timestamp_key = "observed_at" if kind == "event" else "reported_at"
    payloads.sort(key=lambda item: str(item.get(timestamp_key, "")), reverse=True)
    return payloads[0] if payloads else {}


def _terminal_result_status(paths: OmhPaths, binding: dict[str, Any]) -> str:
    target = _binding_target(binding)
    target_type = target["type"]
    target_id = target["id"]
    if target_type == "run":
        delegation = read_json_object(paths.runtime_runs_dir / target_id / "delegation.json") or {}
        if bool(delegation.get("observed")):
            result = str(delegation.get("result", ""))
            if result in _OBSERVED_TERMINAL_RESULTS:
                return result
    if target_type == "wrapper_session":
        record = read_json_object(paths.runtime_wrapper_sessions_dir / target_id / "executor_session.json") or {}
        if bool(record.get("result_observed")):
            result = str(record.get("result", ""))
            if result in _OBSERVED_TERMINAL_RESULTS:
                return result
    return ""


def _project_binding_row(
    primary: dict[str, Any],
    group: list[dict[str, Any]],
    *,
    event: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    linked = [
        {
            "binding_id": binding.get("binding_id", ""),
            "instance_id": binding.get("instance_id", ""),
            "target_type": binding.get("target_type", ""),
            "target_id": binding.get("target_id", ""),
            "correlation_root": binding.get("correlation_root", ""),
            "state": binding.get("state", ""),
        }
        for binding in group
        if binding.get("binding_id") != primary.get("binding_id")
    ]
    row = {
        "primary_binding_id": primary.get("binding_id", ""),
        "primary_instance_id": primary.get("instance_id", ""),
        "binding_id": primary.get("binding_id", ""),
        "instance_id": primary.get("instance_id", ""),
        "target_type": primary.get("target_type", ""),
        "target_id": primary.get("target_id", ""),
        "executor": primary.get("executor_profile", ""),
        "executor_profile": primary.get("executor_profile", ""),
        "correlation_root": primary.get("correlation_root", ""),
        "state": primary.get("state", ""),
        "latest_event": _compact_event_projection(event, primary) if event else {},
        "latest_report": _compact_report_projection(report) if report else {},
        "latest_observed_at": str(event.get("observed_at") or primary.get("last_observed_at") or primary.get("updated_at") or ""),
        "linked_bindings": linked,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    # Who opened the binding, projected from `delivery.source` -- absent for
    # every binding source that predates this field. `fanout_dispatch` is the
    # one value the HUD reader currently keys off of, to tell a fanout-unit
    # binding apart from a Hermes-native or wrapper-session one that happens
    # to share the same executor profile.
    delivery = primary.get("delivery")
    source = str(delivery.get("source", "")) if isinstance(delivery, dict) else ""
    if source:
        row["source"] = source
    # Promoted to the row itself, not left nested in `latest_event`: the status
    # board renders one line per executor and had no way to say which model was
    # running, because the profile alone does not identify it.
    row.update(_observed_routing_metrics(event.get("signal") if event else {}))
    return row


def _compact_event_projection(event: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    projection = {
        "binding_id": event.get("binding_id") or binding.get("binding_id", ""),
        "instance_id": event.get("instance_id") or binding.get("instance_id", ""),
        "executor_profile": event.get("executor_profile") or binding.get("executor_profile", ""),
        "event_type": event.get("event_type", ""),
        "status": event.get("status", ""),
        "summary": event.get("summary", ""),
        "observed_at": event.get("observed_at", ""),
        "claim_boundary": event.get("claim_boundary", CLAIM_BOUNDARY),
    }
    projection.update(_observed_routing_metrics(event.get("signal")))
    # Present only on an event whose owner word was refused. An operator seeing
    # `unmapped_source_event` on `omh runtime progress-status` otherwise has the
    # verdict and none of the reasoning: not the raw word, not the confidence,
    # not the note that says which refusal it was.
    normalization = progress_event_normalization(event)
    if normalization:
        projection["normalization"] = normalization
    return projection


def _compact_report_projection(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "binding_id": report.get("binding_id", ""),
        "instance_id": report.get("instance_id", ""),
        "event_type": report.get("event_type", ""),
        "status": report.get("status", ""),
        "summary": report.get("summary", ""),
        "reported_at": report.get("reported_at", ""),
        "claim_boundary": report.get("claim_boundary", CLAIM_BOUNDARY),
    }


def _binding_target(binding: dict[str, Any]) -> dict[str, str]:
    target_value = binding.get("target")
    target = target_value if isinstance(target_value, dict) else {}
    return {
        "type": str(binding.get("target_type") or target.get("type") or ""),
        "id": str(binding.get("target_id") or target.get("id") or ""),
    }


def _payload_matches_binding_instance(payload: dict[str, Any], binding: dict[str, Any]) -> bool:
    return str(payload.get("binding_id", "")) == str(binding.get("binding_id", "")) and str(
        payload.get("instance_id", "")
    ) == str(binding.get("instance_id", ""))


def _correlation_aliases(
    *,
    codex_session_ref: str,
    codex_thread_ref: str,
    claude_session_ref: str,
    process_session_id: str,
    worktree: str,
    branch: str,
) -> list[dict[str, str]]:
    aliases = []
    for kind, value in (
        ("codex_session_ref", codex_session_ref),
        ("codex_thread_ref", codex_thread_ref),
        ("claude_session_ref", claude_session_ref),
        ("process_session_id", process_session_id),
        ("worktree", worktree),
        ("branch", branch),
    ):
        if str(value).strip():
            aliases.append({"kind": kind, "value": str(value).strip()})
    return aliases


# A TUPLE, not a set. `_safe_signal` iterates it to build the persisted signal,
# so a set literal put the keys of every written record in string-hash order --
# which changes with `PYTHONHASHSEED`, i.e. per process. The record round-trips
# fine either way, but any byte comparison or golden file over a stored signal
# would flake between runs on nothing. The order here is the order a reader
# meets the fields in.
_SAFE_SIGNAL_KEYS = (
    "executor_profile",
    "process_status",
    "git_status_hash",
    "git_diff_stat_hash",
    "git_observed",
    "progress_summary_source",
    "progress_status",
    "progress_event_count",
    "latest_progress_event_type",
    "observable_activity",
    "assistant_visible_summary",
    "progress_snapshot_hash",
    "codex_artifact_sha256",
    "codex_artifact_byte_count",
    "codex_malformed_event_count",
    "evidence_ref_count",
    "explicit_event_type",
    "explicit_summary",
    # Bounded, single-line, printable owner word that the shared vocabulary
    # could not map. It keeps `unmapped_source_event` events auditable
    # without widening the omh_progress_event/v1 record itself.
    "unmapped_source_event",
    # The owner word behind a caller-declared event the normalizer translated.
    # Same purpose one field over: without it, a stored signal cannot say
    # whether `explicit_event_type: executor_completed` was the caller's own
    # sentence or an executor's `workflow_completed` wearing it.
    "explicit_source_event",
    *ROUTING_METRIC_SIGNAL_KEYS,
)


def _safe_signal(signal: dict[str, Any]) -> dict[str, Any]:
    cleaned = {key: signal.get(key) for key in _SAFE_SIGNAL_KEYS if signal.get(key) not in (None, "", [], {})}
    _require_valid("signal", _raw_or_hidden_errors(cleaned))
    return cleaned


def _raw_or_hidden_errors(value: Any, *, path: str = "") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_string = str(key)
            lowered = key_string.casefold()
            if lowered in _RAW_OR_HIDDEN_KEYS:
                errors.append(f"{path + '.' if path else ''}{key_string} is not allowed in progress artifacts")
            errors.extend(_raw_or_hidden_errors(item, path=f"{path}.{key_string}" if path else key_string))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(_raw_or_hidden_errors(item, path=f"{path}[{index}]"))
    elif isinstance(value, str):
        if len(value) > 2000:
            errors.append(f"{path or 'value'} is too large for metadata-only progress")
    return errors


def _require_valid(kind: str, errors: list[str]) -> None:
    if errors:
        raise ExecutorProgressError(f"invalid progress {kind}: {'; '.join(errors)}")


def _compact_strings(values: list[str] | tuple[str, ...]) -> list[str]:
    compacted = []
    for value in values:
        text = _compact_text(str(value), 160)
        if text:
            compacted.append(text)
    return compacted[:8]


def _compact_text(value: str, limit: int) -> str:
    cleaned = " ".join(str(value).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "…"


def _sanitize_progress_copy(value: str) -> str:
    return sanitize_user_facing_progress_text(value)


def _clean_object(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in ("", None, [], {})}


def _optional_pid(value: int | str | None) -> int | str:
    if value in (None, ""):
        return ""
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)


def _status_for_event_type(event_type: str) -> str:
    if event_type == "executor_completed":
        return "completed"
    if event_type == "executor_blocked":
        return "blocked"
    if event_type == "executor_failed":
        return "failed"
    if event_type == "tests_failed":
        return "failed"
    if event_type == "tests_passed":
        return "passed"
    if event_type == UNMAPPED_NORMALIZED_EVENT:
        # Not "running": an unrecognized word says nothing about liveness, and
        # the default would assert an executor is working on this owner's say-so.
        return "observed"
    return "running"


def _safe_progress_summary(summary: dict[str, Any] | None, *, codex_profile: bool) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {}
    _require_valid("progress summary", _raw_or_hidden_errors(summary))
    if codex_profile and summary.get("schema_version") != "codex_progress_summary/v1":
        raise ExecutorProgressError("Codex progress signals must use codex_progress_summary/v1")
    latest = summary.get("latest_progress_event", {}) if isinstance(summary.get("latest_progress_event"), dict) else {}
    raw_artifact = summary.get("raw_output_artifact", {}) if isinstance(summary.get("raw_output_artifact"), dict) else {}
    status = _compact_text(str(summary.get("status", "")), 80)
    event_count = _safe_int(summary.get("event_count"), 0)
    observable_activity = [
        _compact_text(str(item), 120)
        for item in summary.get("observable_activity", [])
        if isinstance(summary.get("observable_activity", []), list)
    ][:8]
    assistant_visible_summary = _compact_text(
        _sanitize_progress_copy(
            str(summary.get("latest_assistant_visible_message") or summary.get("chat_summary") or summary.get("summary") or "")
        ),
        240,
    )
    latest_event_type = _compact_text(str(latest.get("event_type", "")), 80)
    artifact_sha256 = _compact_text(str(raw_artifact.get("sha256", "")), 80)
    normalized = {
        "status": status,
        "event_count": event_count,
        "malformed_event_count": _safe_int(summary.get("malformed_event_count"), 0),
        "latest_progress_event_type": latest_event_type,
        "observable_activity": observable_activity,
        "assistant_visible_summary": assistant_visible_summary,
        "artifact_sha256": artifact_sha256,
        "artifact_byte_count": _safe_int(raw_artifact.get("byte_count"), 0),
    }
    normalized["summary_hash"] = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        **normalized,
    }


def _observed_count(value: Any) -> int | None:
    """Return a non-negative int, or None when nothing was observed.

    None is the whole point: `_safe_signal` drops None but keeps 0, so a
    defaulted 0 would be persisted and then read back as "observed zero tokens"
    when the truth is that no token count was ever collected. Floats are
    truncated so the stored value stays a scalar int -- the setup-profile
    correct/restore path drops non-scalar and float leaves.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


def _observed_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return int(number) if number.is_integer() else number


def _observed_percentage(value: Any) -> int | float | None:
    number = _observed_number(value)
    if number is None or number > 100:
        return None
    return number


def _observed_routing_metrics(signal: Any) -> dict[str, Any]:
    """Lift the routed-model metrics out of an event signal for a live row.

    Absent keys stay absent rather than being filled with "" or 0, so a row
    never claims an observation the signal did not carry.
    """
    if not isinstance(signal, dict):
        return {}
    return {key: signal[key] for key in ROUTING_METRIC_SIGNAL_KEYS if signal.get(key) not in (None, "")}


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _hash_if_present(value: str) -> str:
    if not value.strip():
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _signal_fingerprint(signal: dict[str, Any]) -> str:
    if not signal:
        return ""
    safe = _safe_signal(signal)
    return hashlib.sha256(json.dumps(safe, sort_keys=True).encode("utf-8")).hexdigest()


def _summary_for_event_type(event_type: str) -> str:
    summaries = {
        "executor_dispatched": "The coding executor was dispatched; no result is observed yet.",
        "repo_exploration": "The coding executor is inspecting the repository; no result is observed yet.",
        "running_no_diff_observed": "The coding executor is active, but no file diff is observed yet.",
        "diff_started": "The coding executor has started changing files; no verification result is observed yet.",
        "tests_started": "The coding executor has started verification; no test result is observed yet.",
        "tests_failed": "The coding executor observed a failing verification signal.",
        "tests_passed": "The coding executor observed a passing verification signal.",
        "executor_completed": "The coding executor reported completion, but separate result evidence is still required.",
        "executor_blocked": "The coding executor reported a blocker.",
        "executor_failed": "The coding executor reported a failure.",
        "reported_change_not_observed": (
            "The coding executor reported applying a change, but no file change was observed."
        ),
        "progress_observed": "The coding executor emitted a safe progress signal.",
        UNMAPPED_NORMALIZED_EVENT: (
            "The coding executor reported a progress event this lane did not accept as observed; "
            "the source event name is retained unchanged and no activity, completion, or "
            "verification is claimed from it."
        ),
    }
    return summaries.get(event_type, "Executor progress was observed.")


def _report_sentence(event: dict[str, Any], *, source_language: str = "") -> str:
    summary = _compact_text(str(event.get("summary", "")), 240)
    if source_language.casefold().startswith("ko"):
        return f"코딩 실행자가 진행 중입니다: {summary}"
    return summary


def _minimum_interval_elapsed(previous: str, current: str, seconds: int) -> bool:
    if seconds <= 0 or not previous:
        return True
    age = _seconds_between(previous, current)
    return age is None or age >= seconds


def _seconds_between(previous: str, current: str) -> float | None:
    try:
        prev_dt = _parse_time(previous)
        current_dt = _parse_time(current)
    except ValueError:
        return None
    return (current_dt - prev_dt).total_seconds()


def _parse_time(value: str) -> datetime:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("empty timestamp")
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    parsed = datetime.fromisoformat(cleaned)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
