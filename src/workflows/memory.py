from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..local_store import (
    append_jsonl_locked,
    atomic_write_json,
    ensure_dir,
    file_lock,
    read_json_object,
    read_json_object_result,
    read_jsonl_objects,
    utc_now,
)

from ..plugin_bundle.omh.hermes_memory import build_hermes_memory_bridge as _bundle_memory_bridge
from ..plugin_bundle.omh.hermes_memory import classify_record_expiry as _classify_record_expiry
from ..plugin_bundle.omh.memory_dreaming import consolidation_path as _consolidation_path
from ..plugin_bundle.omh.memory_governance import (
    ADMISSION_STATES,
    MEMORY_GOVERNANCE_POLICY_VERSION,
    MEMORY_SCOPE_SCHEMA_VERSION as _V2_MEMORY_SCOPE_SCHEMA_VERSION,
    PROJECT_MEMORY_RECORD_SCHEMA_VERSION as _V2_PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
    PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION as _V2_PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION,
    build_retention,
    canonical_payload_digest,
    classify_memory_admission,
    evaluate_memory_replay,
    stable_artifact_identity,
)
from ..paths import OmhPaths
from ..profiles.setup import read_setup_profile
from ..targets import summarize_target_registry


MEMORY_SNAPSHOT_SCHEMA_VERSION = "memory_snapshot/v1"
MEMORY_INSPECTION_SCHEMA_VERSION = "memory_inspection/v1"
MEMORY_REVIEW_CARD_SCHEMA_VERSION = "memory_review_card/v1"
HANDOFF_CONTEXT_PACK_SCHEMA_VERSION = "handoff_context_pack/v1"
MEMORY_UPDATE_BATCH_SCHEMA_VERSION = "memory_update_batch/v1"
MEMORY_SCOPE_SCHEMA_VERSION = _V2_MEMORY_SCOPE_SCHEMA_VERSION
LEGACY_MEMORY_SCOPE_SCHEMA_VERSION = "omh_memory_scope/v1"
MEMORY_INDEX_SCHEMA_VERSION = "omh_memory_index/v1"
PROJECT_MEMORY_POLICY_SCHEMA_VERSION = "project_memory_policy/v1"
PROJECT_MEMORY_STATUS_SCHEMA_VERSION = "project_memory_status/v1"
PROJECT_MEMORY_CAPTURE_SCHEMA_VERSION = "project_memory_capture/v1"
PROJECT_MEMORY_CANDIDATE_SCHEMA_VERSION = "project_memory_candidate/v1"
PROJECT_MEMORY_RECORD_SCHEMA_VERSION = _V2_PROJECT_MEMORY_RECORD_SCHEMA_VERSION
LEGACY_PROJECT_MEMORY_RECORD_SCHEMA_VERSION = "project_memory_record/v1"
PROJECT_MEMORY_REVIEW_CARD_SCHEMA_VERSION = "project_memory_review_card/v1"
PROJECT_MEMORY_REVIEW_QUEUE_SCHEMA_VERSION = "project_memory_review_queue/v1"
PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION = _V2_PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION
LEGACY_PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION = "project_memory_review_record/v1"
PROJECT_MEMORY_RECALL_PACK_SCHEMA_VERSION = "project_memory_recall_pack/v1"
MEMORY_RECALL_USAGE_SCHEMA_VERSION = "omh_memory_recall_usage/v1"
MEMORY_LINEAGE_SCHEMA_VERSION = "omh_memory_lineage/v1"
MEMORY_PERSPECTIVES_SCHEMA_VERSION = "omh_memory_perspectives/v1"
MEMORY_PINS_SCHEMA_VERSION = "omh_memory_pins/v1"
MEMORY_ROLLUP_SCHEMA_VERSION = "omh_memory_rollup/v1"
HERMES_MEMORY_BRIDGE_SCHEMA_VERSION = "hermes_memory_bridge/v1"

SOURCE_TRUTH_LEVELS = {
    "runtime_evidence": "observed_evidence",
    "runtime_state": "runtime_index_state",
    "wrapper_session": "chat_decision_state",
    "target_topology": "setup_evidence",
    "setup_profile": "preference_default",
    "omh_memory": "approved_context",
    "wiki_notes": "durable_knowledge",
    "catalog_hint": "capability_hint",
    "wrapper_snapshot": "supplied_hint",
}
SOURCE_PRECEDENCE = {
    "runtime_evidence": 100,
    "wrapper_session": 90,
    "runtime_state": 85,
    "target_topology": 80,
    "setup_profile": 70,
    "omh_memory": 60,
    "wiki_notes": 50,
    "catalog_hint": 40,
    "wrapper_snapshot": 30,
}
ALLOWED_UPDATE_OPS = {"keep", "forget", "update", "change_scope", "dismiss_conflict"}
ALLOWED_SCOPE_KINDS = {"project", "target", "thread", "run"}
PROJECT_MEMORY_MODES = ("off", "review-first", "auto-safe")
PROJECT_MEMORY_RECORD_TYPES = ("fact", "decision", "lesson", "procedure", "episode")
MEMORY_ACTION_IDS = (
    "keep_memory",
    "forget_memory",
    "update_memory",
    "change_memory_scope",
    "apply_memory_updates",
    "show_memory_status",
    "cancel",
)
_SAFE_REF = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
# Tags are recall-scoring keys, not filesystem refs, so they may carry CJK
# words. Running them through the ASCII-only _SAFE_REF silently dropped every
# Korean/Japanese/Chinese tag at capture time, which meant tag scoring could
# never fire for records written by CJK-speaking projects.
_SAFE_TAG = re.compile(r"^[\w.:/-]{1,120}$", re.UNICODE)
_PROMPTISH_KEYS = {"message", "prompt", "raw", "text", "body", "content", "prompt_template"}
_PROJECT_MEMORY_RECORD_KEYS = {
    "schema_version",
    "record_id",
    "candidate_id",
    "revision",
    "record_type",
    "summary",
    "scope",
    "tags",
    "source",
    "source_class",
    "source_ref",
    "source_evidence",
    "admission",
    "retention",
    "revalidation",
    "approved_at",
    "created_at",
    "updated_at",
    "ttl",
    "staleness",
    "safety",
    "derived_from",
    "perspective",
    "superseded_by",
    "redaction_policy",
    "claim_boundary",
}
_PROJECT_MEMORY_RECALL_PACK_KEYS = {
    "schema_version",
    "enabled",
    "executor_target",
    "session_id",
    "task_ref",
    "policy",
    "scope",
    "perspective",
    "query_intent",
    "included_records",
    "excluded_records",
    "freshness_warnings",
    "record_count",
    "truncated",
    "redaction_policy",
    "claim_boundary",
}
_FRESHNESS_WARNING_KEYS = {
    "record_id",
    "state",
    "reason_code",
    "review_due_at",
    "detail",
    "delivered",
    "next_action",
}
_PROJECT_MEMORY_RECALL_ITEM_KEYS = {
    "record_id",
    "record_type",
    "summary",
    "scope",
    "tags",
    "source",
    "approved_at",
    "staleness",
    "score",
    "ranking",
    "derived_from",
    "perspective",
    "revision",
    "admission_mode",
    "source_class",
    "retention_class",
    "evaluated_at",
    "eligibility_reason",
    "revalidation_evidence",
    "replay_evaluation",
}
_RECALL_RANKING_KEYS = {
    "rrf_score_micro",
    "decayed_score_micro",
    "relevance_rank",
    "recency_rank",
    "usage_rank",
    "times_recalled",
    "age_tier",
    "pinned",
    "veracity_weight_pct",
}
# Admission-mode veracity, mnemosyne-style: a human-reviewed record outranks
# an auto-safe one of equal relevance/age. The gap is deliberately small --
# both classes passed the same admission gates -- and it lands in the
# decayed score, never in eligibility. An unknown mode fails CLOSED to the
# lower weight: a trust signal must never default to maximum trust.
_ADMISSION_VERACITY_WEIGHT_PCT = {"approved_manual": 100, "approved_auto_safe": 90}
_ADMISSION_VERACITY_DEFAULT_PCT = 90
# Temporal query intent, conservative by construction: a fixed English cue
# set (no per-language tables, per the routing-language policy) that only
# doubles the RECENCY weight inside rank fusion. Relevance stays primary,
# so intent can never change which keyword matches win -- only how peers of
# equal relevance order. Single tokens must be unambiguous: "current",
# "latest", "now", and "newest" are ordinary engineering adjectives ("the
# current implementation") and live in the phrase list instead, where the
# surrounding words disambiguate them.
_TEMPORAL_QUERY_CUES = frozenset({"yesterday", "today", "recent", "recently", "ago"})
_TEMPORAL_QUERY_PHRASES = ("most recent", "right now", "as of now", "last week", "last month", "up to date")
# Age tiers degrade the fused score of old records inside an equal relevance
# rank, mnemosyne-style: 0-30 days full weight, 30-180 days half, older a
# quarter. Relevance stays the primary key, so a stale strong match still
# beats a fresh weak one; the tier only reorders peers.
_AGE_TIER_BOUNDS_DAYS = (30, 180)
_AGE_TIER_WEIGHTS = (1.0, 0.5, 0.25)
# Pins are guaranteed-inclusion anchors, not eligibility overrides: a pinned
# record still fails closed on expiry, scope, perspective, and review checks.
# The cap stays small because pins occupy recall budget first.
_MEMORY_PINS_LIMIT = 12
# Perspective is honcho's peer paradigm reinterpreted deterministically: an
# optional (observer, observed) pair naming whose view a record is and which
# actor it is about. Unscoped records behave exactly as before; a scoped
# record surfaces only through a matching lens, so an executor-specific
# lesson never leaks into another executor's handoff.
_PERSPECTIVE_KEYS = {"observer", "observed"}
_DEFAULT_PERSPECTIVE_OBSERVER = "hermes"
# Reciprocal rank fusion over deterministic signals, borrowed from hybrid
# retrieval systems: heterogeneous signals are combined by rank, not by raw
# score, so no signal needs scale normalization. Relevance rank stays the
# primary sort key; the fused score orders records only within an equal
# relevance rank, and it is stored as integer micro-units to stay valid
# scalar metadata. Usage ranks on saturating buckets so delivery counts
# cannot compound into a permanent head start.
_RECALL_RRF_K = 60
_RECALL_RRF_WEIGHTS = {"relevance": 2.0, "recency": 1.0, "usage": 1.0}
_RECALL_USAGE_MAX_ENTRIES = 500
_DERIVED_FROM_LIMIT = 8
_LINEAGE_MAX_DEPTH = 10
_PROJECT_MEMORY_EXCLUDED_KEYS = {
    "record_id",
    "reason",
    "staleness",
    "sibling_included",
    "revision",
    "admission_mode",
    "source_class",
    "retention_class",
    "evaluated_at",
    "eligibility_reason",
    "revalidation_evidence",
    "replay_evaluation",
}
_PROJECT_MEMORY_TASK_REF_KEYS = {"sha256", "length", "query_supplied"}
# Source-evidence freshness. Time deadlines alone cannot notice that the file
# a record cites was rewritten the day after approval, so a record may carry
# the digest of the local source observed at capture. Comparing that digest
# against the file as it reads now is the only way to make "the source moved"
# observable without a network call, which OMH never makes. Anything that
# cannot be digested locally -- a ref that is not an absolute path, a deleted
# or unreadable file, or one past the cheap-hash budget -- reads as `unknown`
# and never as `fresh`: a trust signal must fail closed, and "we could not
# look" is not "we looked and it was fine".
_SOURCE_EVIDENCE_MAX_BYTES = 4 * 1024 * 1024
# Freshness warnings are the pre-handoff surface: a recall pack used to drop a
# stale record silently, so the executor saw a smaller pack and no reason. The
# list is bounded like every other polled surface; the pack already says
# `truncated` when its own budget cuts records.
_FRESHNESS_WARNING_LIMIT = 12
_FRESHNESS_NEXT_ACTION = "Confirm, replace, or retire this record before it steers the plan."
_FRESHNESS_REASON_TEXT = {
    "stale_review_required": "Its revalidation deadline passed, so nobody has confirmed the record since then.",
    "source_changed": "The local source it cites changed after the record was approved.",
    "source_unverifiable": "The local source it cites cannot be read now, so its freshness is unobservable.",
    "superseded": "A newer revision supersedes this record.",
    "expired_standard": "Its retention deadline passed.",
    "expired_volatile": "Its retention deadline passed.",
    "expired_durable": "Its retention deadline passed.",
    "freshness_unconfirmed": "Its freshness could not be confirmed from stored metadata and local source evidence.",
}
# Reasons `--include-stale` may surface for inspection. They carry ineligible
# replay evidence, so the pack still cannot be attached as approved context.
_INSPECTABLE_STALE_REASONS = {"stale_review_required", "source_changed", "source_unverifiable"}
_HANDOFF_CONTEXT_PACK_KEYS = {
    "schema_version",
    "executor_target",
    "session_id",
    "scope",
    "source_refs",
    "included_context",
    "excluded_context",
    "blocked_by_conflicts",
    "metadata",
    "redaction_policy",
    "claim_boundary",
}
_HANDOFF_CONTEXT_SCOPE_KEYS = {"kind", "ref"}
_HANDOFF_CONTEXT_SOURCE_REF_KEYS = {"source", "truth_level", "precedence", "item_count"}
_HANDOFF_CONTEXT_INCLUDED_KEYS = {"item_id", "key", "summary", "source", "truth_level", "scope", "artifact_ref", "replay_evaluation"}
_HANDOFF_CONTEXT_EXCLUDED_KEYS = {"item_id", "source", "reason", "replay_evaluation"}
_HANDOFF_CONTEXT_CONFLICT_KEYS = {
    "item_id",
    "key",
    "severity",
    "current_value",
    "preferred_value",
    "current_source",
    "preferred_source",
    "reason",
    "claim_boundary",
}
_HANDOFF_CONTEXT_BLOCKED_KEYS = {"schema_version", "blocked_by_conflicts", "claim_boundary"}


def build_project_memory_policy(paths: OmhPaths, *, mode: str | None = None) -> dict[str, object]:
    normalized = _normalize_memory_mode(mode)
    return {
        "schema_version": PROJECT_MEMORY_POLICY_SCHEMA_VERSION,
        "mode": normalized,
        "capture_enabled": normalized != "off",
        "recall_enabled": normalized != "off",
        "review_required": normalized == "review-first",
        "auto_approve_safe": normalized == "auto-safe",
        "store_scope": "project_local",
        "store_dir": str(paths.memory_dir),
        "redaction_policy": "metadata_only",
        "backend": "local_json",
        "optional_backend_extension": True,
        "claim_boundary": "Project memory configures OMH-local prepared context only; it does not mutate Hermes global or internal memory.",
    }


def read_project_memory_policy(paths: OmhPaths) -> dict[str, object]:
    setup = read_setup_profile(paths)
    if not isinstance(setup, dict):
        return build_project_memory_policy(paths)
    if not _retain_knowledge_family_enabled(setup):
        # Disabling the `retain_knowledge` capability family has to actually
        # stop memory, not merely stop advertising it. Resolving to mode "off"
        # here reuses the capture gate in `record_project_memory` and the
        # recall gate's empty pack, so there is one disabled path rather than a
        # second one that could drift from it.
        return build_project_memory_policy(paths, mode="off")
    policy = setup.get("memory_policy")
    if isinstance(policy, dict):
        return build_project_memory_policy(paths, mode=str(policy.get("mode", "") or "review-first"))
    return build_project_memory_policy(paths, mode=str(setup.get("memory_mode", "") or "review-first"))


def _retain_knowledge_family_enabled(setup: dict[str, object]) -> bool:
    """Read the capability policy straight off the already-loaded profile.

    Deliberately not a call into `capabilities.toggles`: that module imports
    the skill catalog, and the memory path must not pull the catalog in just to
    answer a boolean.
    """
    policy = setup.get("capability_policy")
    if not isinstance(policy, dict):
        return True
    disabled = policy.get("disabled_families", [])
    if not isinstance(disabled, list):
        return True
    return "retain_knowledge" not in {str(value) for value in disabled}


def build_hermes_memory_bridge(paths: OmhPaths) -> dict[str, object]:
    """Relate OMH's approved records to what Hermes already remembers.

    One implementation, kept in the plugin bundle. The Hermes process cannot
    import this package, so a bundle that delegated here would answer "package
    absent" on the only host that matters; the dependency has to point the other
    way.
    """
    return _bundle_memory_bridge(paths.omh_home, paths.hermes_home)


def build_project_memory_status(paths: OmhPaths) -> dict[str, object]:
    candidates = _read_project_memory_candidates(paths)
    records = _read_project_memory_records(paths)
    reviews = _read_project_memory_reviews(paths)
    now = datetime.now(timezone.utc)
    evaluations = [_evaluate_memory_artifact(record, paths=paths, now=now, review_resolver=_project_memory_review_resolver(paths)) for record in records]
    expired_records = sum(1 for evaluation in evaluations if str(evaluation["reason_code"]).startswith("expired_"))
    candidate_status_counts: dict[str, int] = {}
    for candidate in candidates:
        status = str(candidate.get("status", "unknown"))
        candidate_status_counts[status] = candidate_status_counts.get(status, 0) + 1
    return {
        "schema_version": PROJECT_MEMORY_STATUS_SCHEMA_VERSION,
        "policy": read_project_memory_policy(paths),
        "store": {
            "schema_version": MEMORY_INDEX_SCHEMA_VERSION,
            "memory_dir": str(paths.memory_dir),
            "candidate_dir": str(_memory_candidates_dir(paths)),
            "record_dir": str(_memory_records_dir(paths)),
            "review_dir": str(_memory_reviews_dir(paths)),
            "index_path": str(paths.memory_index_path),
            "local_only": True,
        },
        "counts": {
            "candidates": len(candidates),
            "pending_review": sum(1 for candidate in candidates if str(candidate.get("status", "")) in {"pending_review", "blocked_review_required"}),
            "approved_records": sum(1 for record in records if record.get("schema_version") == PROJECT_MEMORY_RECORD_SCHEMA_VERSION),
            "expired_records": expired_records,
            "eligible_records": sum(1 for evaluation in evaluations if evaluation["eligible"]),
            "ineligible_records": sum(1 for evaluation in evaluations if not evaluation["eligible"]),
            "review_required_legacy": sum(1 for evaluation in evaluations if evaluation["reason_code"] == "review_required_legacy"),
            "review_records": len(reviews),
            "candidate_statuses": candidate_status_counts,
        },
        "hermes_memory": build_hermes_memory_bridge(paths),
        "redaction_policy": "metadata_only",
        "claim_boundary": "Project memory status is prepared local context only; it is not execution, review, CI, merge, or Hermes internal-memory evidence.",
    }


def capture_project_memory_candidate(
    paths: OmhPaths,
    summary: str,
    *,
    content: str = "",
    record_type: str = "fact",
    scope_kind: str = "project",
    scope_ref: str = "default",
    source: str = "cli",
    source_ref: str = "",
    tags: list[str] | tuple[str, ...] | None = None,
    ttl_days: int | None = None,
    stale_after_days: int | None = None,
    retention_class: str = "standard",
    derived_from: list[str] | tuple[str, ...] | None = None,
    observer: str | None = None,
    observed: str | None = None,
    force_review: bool = False,
) -> dict[str, object]:
    policy = read_project_memory_policy(paths)
    if not bool(policy.get("capture_enabled", True)):
        return {
            "schema_version": PROJECT_MEMORY_CAPTURE_SCHEMA_VERSION,
            "captured": False,
            "auto_approved": False,
            "policy": policy,
            "reason": "project_memory_disabled",
            "claim_boundary": "Memory capture is disabled by OMH project policy; Hermes global or internal memory is not mutated.",
        }
    candidate = _build_project_memory_candidate(
        summary,
        content=content,
        record_type=record_type,
        scope_kind=scope_kind,
        scope_ref=scope_ref,
        source=source,
        source_ref=source_ref,
        tags=tags or [],
        ttl_days=ttl_days,
        stale_after_days=stale_after_days,
        retention_class=retention_class,
        derived_from=_normalize_derived_from(paths, derived_from),
        perspective=_normalize_perspective(observer, observed),
    )
    # Exact-summary duplicate detection, mnemosyne-style but review-first:
    # the match is surfaced on the candidate for the reviewer to decide, never
    # silently merged -- and a duplicate never auto-approves, because the
    # auto-safe path would otherwise mint identical records unreviewed. The
    # comparison uses the candidate's own summary, which already went through
    # the same redaction/truncation pipeline as every stored summary; the raw
    # input would miss any match past the redaction cap.
    duplicate_of = _find_duplicate_record(paths, str(candidate.get("summary", "")))
    if duplicate_of:
        candidate["duplicate_of"] = duplicate_of
    _write_project_memory_candidate(paths, candidate)
    auto_approved = False
    record: dict[str, object] = {}
    # force_review keeps derived aggregates (e.g. rollup episodes) on the
    # review path even under auto-safe: derived content is a curation act,
    # not a captured observation.
    if bool(policy.get("auto_approve_safe")) and candidate.get("safety", {}).get("status") == "safe" and not duplicate_of and not force_review:
        approved = approve_project_memory_candidate(paths, str(candidate["candidate_id"]), approved_by="auto-safe")
        record = approved.get("record", {}) if isinstance(approved.get("record"), dict) else {}
        candidate = approved.get("candidate", candidate) if isinstance(approved.get("candidate"), dict) else candidate
        auto_approved = True
    return {
        "schema_version": PROJECT_MEMORY_CAPTURE_SCHEMA_VERSION,
        "captured": True,
        "auto_approved": auto_approved,
        "candidate": candidate,
        "record": record,
        "policy": policy,
        "claim_boundary": (
            "Captured project memory is an OMH-local candidate or reviewed record only; "
            "it is not execution, review, CI, merge, or Hermes internal-memory evidence."
        ),
    }


def build_project_memory_review(
    paths: OmhPaths,
    *,
    candidate_id: str | None = None,
    limit: int = 20,
) -> dict[str, object]:
    candidates = _read_project_memory_candidates(paths)
    if candidate_id:
        candidates = [candidate for candidate in candidates if candidate.get("candidate_id") == candidate_id]
    else:
        candidates = [candidate for candidate in candidates if str(candidate.get("status", "")) in {"pending_review", "blocked_review_required"}]
    cards = [build_project_memory_review_card(candidate) for candidate in candidates[: max(limit, 0)]]
    return {
        "schema_version": PROJECT_MEMORY_REVIEW_QUEUE_SCHEMA_VERSION,
        "policy": read_project_memory_policy(paths),
        "cards": cards,
        "card_count": len(cards),
        "pending_count": len(candidates),
        "redaction_policy": "metadata_only",
        "claim_boundary": "Project memory review is prepared context review only; it is not execution, review, CI, merge, or Hermes internal-memory evidence.",
    }


def build_project_memory_review_card(candidate: dict[str, Any]) -> dict[str, object]:
    safety = candidate.get("safety", {}) if isinstance(candidate.get("safety"), dict) else {}
    safety_status = str(safety.get("status", "needs_review"))
    recommended_action = "reject" if safety_status == "blocked" else "approve_or_reject"
    return {
        "schema_version": PROJECT_MEMORY_REVIEW_CARD_SCHEMA_VERSION,
        "candidate_id": str(candidate.get("candidate_id", "")),
        "record_type": str(candidate.get("record_type", "")),
        "summary": str(candidate.get("summary", "")),
        "scope": _normalize_scope(candidate.get("scope", _scope("project", "default"))),
        "tags": _string_list(candidate.get("tags", [])),
        "created_at": str(candidate.get("created_at", "")),
        **({"duplicate_of": str(candidate["duplicate_of"])} if candidate.get("duplicate_of") else {}),
        "safety": safety,
        "recommended_action": recommended_action,
        "actions": [
            {"id": "approve_memory", "enabled": safety_status != "blocked"},
            {"id": "reject_memory", "enabled": True},
            {"id": "show_memory_status", "enabled": True},
        ],
        "redaction_policy": "metadata_only",
        "claim_boundary": (
            "Memory review cards are prepared project context only; "
            "they are not execution, review, CI, merge, or Hermes internal-memory evidence."
        ),
    }


class LifecycleCandidateError(ValueError):
    """A v2 lifecycle candidate reached the plain approval path."""


def approve_project_memory_candidate(paths: OmhPaths, candidate_id: str, *, approved_by: str = "operator") -> dict[str, object]:
    candidate = _read_project_memory_candidate(paths, candidate_id)
    if not candidate:
        raise FileNotFoundError(candidate_id)
    # Fail closed on correction/restore candidates: their payload lives under
    # "replacement", so the plain path would mint a record with an empty
    # summary and revision 1 -- and that garbage record then blocks the real
    # reapproval with newer_live_revision_conflict. The CLI catches this and
    # routes to the lifecycle reapproval executor instead.
    if str(candidate.get("schema_version", "")) == "project_memory_candidate/v2" or str(candidate.get("lifecycle", "") or ""):
        raise LifecycleCandidateError(
            f"candidate {candidate_id} is a lifecycle ({candidate.get('lifecycle', 'v2')}) candidate; "
            "it must be reapproved through the lifecycle path, not plain approval"
        )
    safety = candidate.get("safety", {}) if isinstance(candidate.get("safety"), dict) else {}
    if safety.get("status") == "blocked":
        raise ValueError("blocked memory candidates must be rejected or recaptured without protected raw content")
    approved_at = utc_now()
    review_id = f"review_{candidate_id}"
    admission_state = "approved_auto_safe" if approved_by == "auto-safe" else "approved_manual"
    record = _record_from_candidate(
        candidate,
        approved_by=approved_by,
        approved_at=approved_at,
        review_id=review_id,
        admission_state=admission_state,
    )
    review = _project_memory_review_record(record, review_id=review_id, reviewer=approved_by, decision=admission_state)
    # The whole mutate sequence holds the store lock so a concurrent retirement
    # cannot observe a half-written approval. Candidate writes go through the
    # unlocked helper: the public wrapper acquires this same non-reentrant lock.
    with file_lock(paths.memory_index_path, private=True):
        _write_project_memory_record(paths, record)
        candidate = {
            **candidate,
            "status": "approved",
            "reviewed_at": approved_at,
            "reviewed_by": approved_by,
            "record_id": record["record_id"],
            "review_id": review_id,
        }
        _write_project_memory_candidate_unlocked(paths, candidate)
        _write_project_memory_review_decision(paths, review)
        _write_memory_index_unlocked(paths)
    return {
        "schema_version": PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION,
        "decision": admission_state,
        "candidate": candidate,
        "record": record,
        "review": review,
        "claim_boundary": "Approved project memory is prepared context only; it is not execution, review, CI, merge, or Hermes internal-memory evidence.",
    }


def reject_project_memory_candidate(
    paths: OmhPaths,
    candidate_id: str,
    *,
    rejected_by: str = "operator",
    reason: str = "",
) -> dict[str, object]:
    candidate = _read_project_memory_candidate(paths, candidate_id)
    if not candidate:
        raise FileNotFoundError(candidate_id)
    now = utc_now()
    candidate = {**candidate, "status": "rejected", "reviewed_at": now, "reviewed_by": rejected_by, "rejection_reason": _redact(str(reason or ""))[:300]}
    with file_lock(paths.memory_index_path, private=True):
        _write_project_memory_candidate_unlocked(paths, candidate)
        review = _write_project_memory_review_decision(
            paths,
            {
                "schema_version": PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION,
                "review_id": f"review_{candidate_id}",
                "candidate_id": candidate_id,
                "decision": "rejected",
                "reviewer_claim": rejected_by,
                "reason": _redact(str(reason or ""))[:300],
                "reviewed_at": now,
                "claim_boundary": "Project memory review decisions are prepared governance only, never executor-use evidence.",
            },
        )
        _write_memory_index_unlocked(paths)
    return {
        "schema_version": PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION,
        "decision": "rejected",
        "candidate": candidate,
        "review": review,
        "claim_boundary": (
            "Rejected project memory is an OMH-local review decision only; "
            "it is not execution, review, CI, merge, or Hermes internal-memory evidence."
        ),
    }


def build_project_memory_recall_pack(
    paths: OmhPaths,
    query: str = "",
    *,
    executor_target: str = "generic",
    session_id: str = "",
    scope_kind: str | None = None,
    scope_ref: str | None = None,
    limit: int = 6,
    max_chars: int | None = None,
    include_stale: bool = False,
    now: datetime | None = None,
    stale_override: dict[str, object] | None = None,
    run_id: str | None = None,
    observer: str | None = None,
    observed: str | None = None,
) -> dict[str, object]:
    policy = read_project_memory_policy(paths)
    # Lens labels normalize exactly like capture labels: capture lowercases
    # and strips, so a raw "--observed Codex" here would silently match
    # nothing and read as "never captured".
    observer = str(observer or "").strip().lower() or None
    observed = str(observed or "").strip().lower() or None
    task_ref = {
        "sha256": hashlib.sha256(query.encode("utf-8")).hexdigest() if query else "",
        "length": len(query),
        "query_supplied": bool(query),
    }
    if not bool(policy.get("recall_enabled", True)):
        return _empty_recall_pack(
            policy,
            executor_target=executor_target,
            session_id=session_id,
            task_ref=task_ref,
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            reason="project_memory_disabled",
        )
    records = _read_project_memory_records(paths)
    requested_scope = _scope(scope_kind, scope_ref) if scope_kind and scope_ref else None
    pins = set(read_memory_pins(paths))
    review_resolver = _project_memory_review_resolver(paths)
    included: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    for record in records:
        if not _record_scope_matches(record, scope_kind=scope_kind, scope_ref=scope_ref):
            continue
        # Perspective mismatch skips silently, exactly like scope mismatch:
        # the record belongs to another actor's lens, not to this pack.
        if not _record_perspective_matches(record, observer=observer, observed=observed):
            continue
        evaluation = _evaluate_memory_artifact(
            record,
            paths=paths,
            now=now,
            requested_scope=requested_scope,
            review_resolver=review_resolver,
            stale_override=stale_override,
            run_id=run_id,
        )
        staleness = _record_staleness(record, now=now)
        # Source-evidence freshness gates recall exactly like the time
        # deadline does. The shared evaluator only knows deadlines, so the
        # verdict `_record_staleness` derived from the record's own recorded
        # digest is folded into the same eligibility decision here rather
        # than becoming a second, quieter notion of stale.
        source_state = str(staleness.get("source_state", ""))
        if bool(evaluation["eligible"]) and source_state in {"changed", "unreadable"}:
            evaluation = {
                **evaluation,
                "eligible": False,
                "reason_code": "source_changed" if source_state == "changed" else "source_unverifiable",
            }
        if not bool(evaluation["eligible"]):
            # --include-stale is an inspection affordance: it surfaces
            # records whose ONLY problem is unconfirmed freshness -- a passed
            # revalidation deadline or a moved source -- carrying their
            # ineligible replay evidence so the pack cannot be attached to a
            # handoff. Expired and otherwise-ineligible records stay excluded
            # regardless.
            if include_stale and str(evaluation.get("reason_code", "")) in _INSPECTABLE_STALE_REASONS:
                score = _memory_recall_score(record, query)
                if not query or score > 0 or str(record.get("record_id", "")) in pins:
                    included.append(_recall_item(record, score=score, staleness=staleness, evaluation=evaluation))
                    continue
            excluded.append(_recall_exclusion(record, evaluation, staleness=staleness))
            continue
        score = _memory_recall_score(record, query)
        # A pinned anchor is always in context: it skips only the
        # no_query_overlap cut, never an eligibility check above.
        if query and score <= 0 and str(record.get("record_id", "")) not in pins:
            excluded.append(_recall_exclusion(record, evaluation, staleness=staleness, reason="no_query_overlap"))
            continue
        included.append(_recall_item(record, score=score, staleness=staleness, evaluation=evaluation))
    query_intent = _recall_query_intent(query)
    _attach_recall_ranking(
        included,
        read_recall_usage(paths),
        pins=pins,
        now=now if now is not None else datetime.now(timezone.utc),
        recency_weight=2.0 if query_intent == "temporal" else _RECALL_RRF_WEIGHTS["recency"],
    )
    # Pinned anchors lead, then relevance; the decayed fused score orders
    # records only within an equal relevance rank. A weaker keyword match
    # can therefore never displace a stronger unpinned one -- including
    # across the budget cut below -- while recency, delivery usage, and age
    # tier decide ties and unqueried packs. Pins take priority within the
    # budget but never own it outright: at most limit-1 pinned slots lead
    # the pack (minimum one), and further pins compete as normal records,
    # so a fully-used pin budget cannot blank query-driven recall.
    ranked_key = lambda item: (  # noqa: E731 - shared by both sort passes below
        int(_ranking_field(item, "relevance_rank")),
        -int(_ranking_field(item, "decayed_score_micro")),
        str(item.get("record_id", "")),
    )
    privileged_pins = {
        str(item.get("record_id", ""))
        for item in sorted(
            (item for item in included if _ranking_flag(item, "pinned")),
            key=ranked_key,
        )[: max(max(limit, 0) - 1, 1)]
    }
    included.sort(key=lambda item: (0 if str(item.get("record_id", "")) in privileged_pins else 1, *ranked_key(item)))
    # Budget cut follows the priority ladder above: once either budget is
    # crossed, everything after that point is cut, so a lower-priority record
    # never displaces a higher-priority one. Cut records are recorded as
    # over_budget rather than dropped silently -- the pack must be able to say
    # "this is not everything".
    kept: list[dict[str, object]] = []
    kept_chars = 0
    budget_exhausted = False
    for item in included:
        summary_chars = len(str(item.get("summary", "")))
        if not budget_exhausted:
            over_records = len(kept) >= max(limit, 0)
            over_chars = max_chars is not None and kept_chars + summary_chars > max_chars
            budget_exhausted = over_records or over_chars
        if budget_exhausted:
            entry = {
                "record_id": str(item.get("record_id", "")),
                "reason": "over_budget",
                "staleness": item.get("staleness", {"state": "not_checked"}),
                **_recall_evidence_fields(item.get("replay_evaluation")),
            }
            # A cut record that shares a tag with a KEPT record may be the
            # other side of a same-topic disagreement; without this hint the
            # surviving record silently "wins" until curation runs. The hint
            # names the sibling only -- it never re-adds the record past the
            # budget and never guesses which side is right.
            cut_tags = {str(tag) for tag in item.get("tags", []) or []}
            for kept_item in kept:
                if cut_tags & {str(tag) for tag in kept_item.get("tags", []) or []}:
                    entry["sibling_included"] = str(kept_item.get("record_id", ""))
                    break
            excluded.append(entry)
            continue
        kept.append(item)
        kept_chars += summary_chars
    included = kept
    return {
        "schema_version": PROJECT_MEMORY_RECALL_PACK_SCHEMA_VERSION,
        "enabled": True,
        "executor_target": executor_target,
        "session_id": session_id,
        "task_ref": task_ref,
        "policy": policy,
        "scope": _scope(scope_kind or "project", scope_ref or "default"),
        "perspective": {"observer": observer or "", "observed": observed or ""},
        "query_intent": query_intent,
        "included_records": included,
        "excluded_records": excluded,
        "freshness_warnings": _freshness_warnings(included, excluded),
        "record_count": len(included),
        "truncated": budget_exhausted,
        "redaction_policy": "metadata_only",
        "claim_boundary": (
            "Memory recall packs contain reviewed OMH project summaries only; "
            "they are prepared context, not execution, review, CI, merge, or Hermes internal-memory evidence."
        ),
    }


def memory_recall_pack_for_handoff(
    paths: OmhPaths,
    query: str,
    *,
    executor_target: str = "generic",
    session_id: str = "",
    limit: int = 5,
) -> dict[str, object] | None:
    # The executor target is the handoff's perspective lens: unscoped records
    # pass as always, and records observed for this executor join them --
    # while a record about any other executor stays out of this pack.
    pack = build_project_memory_recall_pack(
        paths,
        query,
        executor_target=executor_target,
        session_id=session_id,
        limit=limit,
        observed=_handoff_perspective_lens(executor_target),
    )
    # A pack with no eligible records but a freshness warning still travels.
    # Dropping it here was the silent failure: the handoff went out with no
    # memory and no statement that a stale record had been held back, so the
    # operator never got the chance to confirm, replace, or retire it.
    if not pack.get("enabled") or not (pack.get("included_records") or pack.get("freshness_warnings")):
        return None
    return pack


def record_attached_recall_usage(paths: OmhPaths, payload: dict[str, object]) -> dict[str, object]:
    """Count delivery usage for recall packs actually attached to a handoff.

    Building a pack is speculative -- the delegation payload may reject it or
    end without a handoff -- so usage counts only records inside a
    ``memory_recall_pack`` that survived attachment. Callers invoke this after
    ``build_coding_delegation_payload`` returns; when no handoff carries a
    pack it is a no-op. Any store I/O failure -- lock timeout, read-only
    home, full disk -- drops the count instead of raising: usage is a
    ranking hint and must never cost the handoff itself.
    """
    record_ids: list[str] = []
    for handoff_key in ("executor_handoff", "runtime_handoff", "prompt_handoff"):
        handoff = payload.get(handoff_key)
        if not isinstance(handoff, dict):
            continue
        pack = handoff.get("memory_recall_pack")
        if not isinstance(pack, dict):
            continue
        for item in pack.get("included_records", []) or []:
            if isinstance(item, dict):
                record_ids.append(str(item.get("record_id", "")))
    if not record_ids:
        return {"schema_version": MEMORY_RECALL_USAGE_SCHEMA_VERSION, "recorded": 0, "records": {}}
    try:
        return record_recall_usage(paths, record_ids)
    except OSError:
        # FileLockTimeout is one leaf of the OSError family; ensure_dir and
        # atomic_write_json raise siblings (EROFS, ENOSPC) that must not
        # surface on a chat route that was pure-read before this counter.
        return {"schema_version": MEMORY_RECALL_USAGE_SCHEMA_VERSION, "recorded": 0, "records": {}}


def _memory_usage_path(paths: OmhPaths) -> Path:
    return paths.memory_dir / "usage.json"


def read_recall_usage(paths: OmhPaths) -> dict[str, dict[str, object]]:
    """Per-record delivery counters; a missing or corrupt store reads as empty.

    Usage is a ranking hint and a retirement-report annotation, never an
    eligibility input, so losing it must never cost a recall.
    """
    data, _error = read_json_object_result(_memory_usage_path(paths))
    if not isinstance(data, dict) or data.get("schema_version") != MEMORY_RECALL_USAGE_SCHEMA_VERSION:
        return {}
    entries = data.get("records")
    if not isinstance(entries, dict):
        return {}
    usage: dict[str, dict[str, object]] = {}
    for record_id, entry in entries.items():
        if not isinstance(entry, dict) or not _SAFE_REF.match(str(record_id)):
            continue
        times = entry.get("times_recalled")
        usage[str(record_id)] = {
            "times_recalled": times if isinstance(times, int) and not isinstance(times, bool) and times > 0 else 0,
            "last_recalled_at": str(entry.get("last_recalled_at", "")),
        }
    return usage


def record_recall_usage(paths: OmhPaths, record_ids: list[str], *, now: str | None = None) -> dict[str, object]:
    delivered: list[str] = []
    for record_id in record_ids:
        normalized = str(record_id)
        if _SAFE_REF.match(normalized) and normalized not in delivered:
            delivered.append(normalized)
    if not delivered:
        return {"schema_version": MEMORY_RECALL_USAGE_SCHEMA_VERSION, "recorded": 0, "records": {}}
    recorded_at = now or utc_now()
    ensure_dir(paths.memory_dir)
    # Usage has its own file and its own lock: taking the shared memory-index
    # lock here would let an operator's approve/retire stall every
    # delegate-mode chat response for the full 10s default. The short timeout
    # is safe because the caller treats a timeout as a dropped count.
    with file_lock(_memory_usage_path(paths), timeout_seconds=1.0, private=True):
        usage = read_recall_usage(paths)
        for record_id in delivered:
            entry = usage.get(record_id, {"times_recalled": 0, "last_recalled_at": ""})
            entry["times_recalled"] = int(entry.get("times_recalled", 0) or 0) + 1
            entry["last_recalled_at"] = recorded_at
            usage[record_id] = entry
        if len(usage) > _RECALL_USAGE_MAX_ENTRIES:
            # Trim never evicts a just-delivered id: utc_now() is second-
            # granular, so "newest first" can degenerate to record-id order
            # and would otherwise drop the very entry this call added. This
            # makes the cap soft -- a delivery larger than the cap keeps all
            # its own entries -- which is fine while recall limits stay far
            # below _RECALL_USAGE_MAX_ENTRIES.
            delivered_set = set(delivered)
            trimmable = [item for item in usage.items() if item[0] not in delivered_set]
            trimmable.sort(key=lambda item: (str(item[1].get("last_recalled_at", "")), item[0]), reverse=True)
            keep = max(_RECALL_USAGE_MAX_ENTRIES - len(delivered_set), 0)
            usage = dict(sorted(trimmable[:keep] + [(record_id, usage[record_id]) for record_id in delivered]))
        atomic_write_json(
            _memory_usage_path(paths),
            {"schema_version": MEMORY_RECALL_USAGE_SCHEMA_VERSION, "updated_at": recorded_at, "records": usage},
            private=True,
        )
    return {
        "schema_version": MEMORY_RECALL_USAGE_SCHEMA_VERSION,
        "recorded": len(delivered),
        "records": {record_id: usage[record_id] for record_id in delivered},
    }


def _ranking_field(item: dict[str, object], key: str) -> int:
    ranking = item.get("ranking")
    value = ranking.get(key, 0) if isinstance(ranking, dict) else 0
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _ranking_flag(item: dict[str, object], key: str) -> bool:
    ranking = item.get("ranking")
    return bool(ranking.get(key, False)) if isinstance(ranking, dict) else False


def _competition_ranks(items: list[dict[str, object]], value_fn: Any) -> dict[str, int]:
    """1-based competition ranks, best first; equal values share a rank."""
    ordered = sorted(items, key=lambda item: str(item.get("record_id", "")))
    ordered.sort(key=value_fn, reverse=True)
    ranks: dict[str, int] = {}
    previous_value: object = object()
    previous_rank = 1
    for position, item in enumerate(ordered, start=1):
        value = value_fn(item)
        if value != previous_value:
            previous_rank = position
            previous_value = value
        ranks[str(item.get("record_id", ""))] = previous_rank
    return ranks


def _attach_recall_ranking(
    items: list[dict[str, object]],
    usage: dict[str, dict[str, object]],
    *,
    pins: set[str] | None = None,
    now: datetime | None = None,
    recency_weight: float | None = None,
) -> None:
    """Fuse relevance, recency, and delivery usage into one recall order.

    Without a query every relevance score ties at 1, so recency and usage
    decide the order instead of the record-id accident the pure keyword sort
    fell back to. Recency ranks on the approved_at ISO string, which sorts
    lexicographically; a record missing approved_at ranks oldest. The fused
    score is then degraded by age tier so old records reorder below young
    peers of equal relevance.
    """
    if not items:
        return
    pins = pins or set()
    now = now if now is not None else datetime.now(timezone.utc)
    recency_weight = recency_weight if recency_weight is not None else _RECALL_RRF_WEIGHTS["recency"]
    def _times_recalled(item: dict[str, object]) -> int:
        entry = usage.get(str(item.get("record_id", "")), {})
        times = entry.get("times_recalled", 0)
        return times if isinstance(times, int) and not isinstance(times, bool) else 0

    relevance = _competition_ranks(items, lambda item: int(item.get("score", 0) or 0))
    recency = _competition_ranks(items, lambda item: str(item.get("approved_at", "")))
    usage_ranks = _competition_ranks(items, lambda item: _usage_bucket(_times_recalled(item)))
    for item in items:
        record_id = str(item.get("record_id", ""))
        fused = (
            _RECALL_RRF_WEIGHTS["relevance"] / (_RECALL_RRF_K + relevance[record_id])
            + recency_weight / (_RECALL_RRF_K + recency[record_id])
            + _RECALL_RRF_WEIGHTS["usage"] / (_RECALL_RRF_K + usage_ranks[record_id])
        )
        tier = _age_tier(str(item.get("approved_at", "")), now=now)
        veracity_pct = _ADMISSION_VERACITY_WEIGHT_PCT.get(str(item.get("admission_mode", "")), _ADMISSION_VERACITY_DEFAULT_PCT)
        item["ranking"] = {
            # rrf_score_micro is undecayed rank fusion under THIS pack's
            # weights (a temporal query raises the recency weight, so scores
            # compare within a pack, not across packs); age decay and
            # veracity land in decayed_score_micro, which is what the sort
            # uses.
            "rrf_score_micro": round(fused * 1_000_000),
            "decayed_score_micro": round(fused * _AGE_TIER_WEIGHTS[tier] * (veracity_pct / 100) * 1_000_000),
            "relevance_rank": relevance[record_id],
            "recency_rank": recency[record_id],
            "usage_rank": usage_ranks[record_id],
            "times_recalled": _times_recalled(item),
            "age_tier": tier,
            "pinned": record_id in pins,
            "veracity_weight_pct": veracity_pct,
        }


def _usage_bucket(times_recalled: int) -> int:
    """Saturating ordinal for the usage signal: 0, 1-2, 3-9, 10+.

    Raw counts self-reinforce -- every delivery improves the rank that earns
    the next delivery -- so the signal saturates instead of compounding.
    """
    if times_recalled >= 10:
        return 3
    if times_recalled >= 3:
        return 2
    if times_recalled >= 1:
        return 1
    return 0


def _normalized_summary_key(summary: str) -> str:
    return " ".join(unicodedata.normalize("NFC", str(summary or "")).lower().split())


def _find_duplicate_record(paths: OmhPaths, summary: str, *, now: datetime | None = None) -> str:
    """Record id of a non-expired record with the same normalized summary.

    Normalization is NFC + casefold-by-lower + whitespace collapse -- exact
    content match like mnemosyne's dedup, not similarity, so it can never
    merge two facts that merely look alike. TTL-expired records are skipped:
    re-capturing an expiring fact is the normal refresh path and must not be
    denied auto-approval by its own dying predecessor.
    """
    key = _normalized_summary_key(summary)
    if not key:
        return ""
    now = now if now is not None else datetime.now(timezone.utc)
    for record in _read_project_memory_records(paths):
        if _classify_record_expiry(record, now=now) == "expired":
            continue
        if _normalized_summary_key(str(record.get("summary", ""))) == key:
            return str(record.get("record_id", ""))
    return ""


def build_memory_rollup(
    paths: OmhPaths,
    *,
    tag: str | None = None,
    scope_kind: str | None = None,
    scope_ref: str | None = None,
    apply: bool = False,
    now: datetime | None = None,
) -> dict[str, object]:
    """Additive episode rollup, mnemosyne's consolidation without the model.

    Report-first: the report names the member records and the deterministic
    summary an episode candidate would carry; ``apply`` routes that candidate
    through the normal capture pipeline (safety, duplicate detection, review,
    ``derived_from`` provenance to every member). Originals are never touched
    -- consolidation here is additive bookkeeping, curation stays a separate
    reviewed act, and summarizing prose stays Hermes' job: the rollup summary
    is a mechanical join, not a synthesis.
    """
    if bool(scope_kind) != bool(scope_ref):
        raise ValueError("memory rollup needs both --scope-kind and --scope-ref, or neither")
    if not (tag or (scope_kind and scope_ref)):
        raise ValueError("memory rollup requires --tag and/or a full --scope-kind/--scope-ref pair")
    normalized_tags = _normalize_tags([tag]) if tag else []
    normalized_tag = normalized_tags[0] if normalized_tags else ""
    if tag and not normalized_tag:
        raise ValueError(f"unsafe rollup tag: {tag!r}")
    now = now if now is not None else datetime.now(timezone.utc)
    members: list[dict[str, Any]] = []
    considered = 0
    for record in _read_project_memory_records(paths):
        if str(record.get("record_type", "")) == "episode":
            continue
        if not _record_scope_matches(record, scope_kind=scope_kind, scope_ref=scope_ref):
            continue
        if normalized_tag and normalized_tag not in _normalize_tags(record.get("tags", [])):
            continue
        considered += 1
        if _classify_record_expiry(record, now=now) == "expired":
            continue
        members.append(record)
    # Oldest first; created_at and candidate_id sharpen the second-granular
    # approved_at ties before the record-id fallback so the selection is
    # stable for a given store, and the contract is named in the report.
    members.sort(
        key=lambda record: (
            str(record.get("approved_at", "")),
            str(record.get("created_at", "")),
            str(record.get("candidate_id", "")),
            str(record.get("record_id", "")),
        )
    )
    truncated_members = max(len(members) - _DERIVED_FROM_LIMIT, 0)
    members = members[:_DERIVED_FROM_LIMIT]
    # The episode inherits its members' confinement, strictest-wins, and
    # refuses on conflict: mixed perspectives or mixed scopes would launder
    # one actor's or one target's content into a wider audience, which is
    # exactly what those boundaries exist to prevent.
    member_scopes = {(scope["kind"], scope["ref"]) for scope in (_normalize_scope(record.get("scope", _scope("project", "default"))) for record in members)}
    member_perspectives = {
        (projection.get("observer", ""), projection.get("observed", ""))
        for projection in (_perspective_projection(record.get("perspective")) for record in members)
    }
    reason_code = "planned"
    if len(members) < 2:
        reason_code = "not_enough_members"
    elif len(member_scopes) > 1:
        reason_code = "mixed_scope"
    elif len(member_perspectives) > 1:
        reason_code = "mixed_perspective"
    eligible = reason_code == "planned"
    episode_scope = _scope(*next(iter(member_scopes))) if len(member_scopes) == 1 else _scope(scope_kind or "project", scope_ref or "default")
    episode_perspective = next(iter(member_perspectives)) if len(member_perspectives) == 1 else ("", "")
    volatile_ttls = [
        ttl_days
        for record in members
        if _retention_class(record) == "volatile"
        for ttl_days in [record.get("retention", {}).get("ttl_days") if isinstance(record.get("retention"), dict) else None]
        if isinstance(ttl_days, int) and not isinstance(ttl_days, bool)
    ]
    episode_retention = "volatile" if any(_retention_class(record) == "volatile" for record in members) else "standard"
    episode_ttl_days = max(min(volatile_ttls), 1) if volatile_ttls else (1 if episode_retention == "volatile" else None)
    selector = {"tag": normalized_tag, "scope": episode_scope, "selection": "oldest_first"}
    selector_label = normalized_tag or f"{episode_scope['kind']}/{episode_scope['ref']}"
    # Budget the join so every member is represented: an unbudgeted join of
    # 240-char summaries would truncate mid-list while derived_from still
    # names all members.
    prefix = f"Episode rollup ({len(members)} records, {selector_label}): "
    per_member = max((240 - len(prefix)) // max(len(members), 1) - 2, 12)
    parts: list[str] = []
    for record in members:
        text = str(record.get("summary", ""))
        if len(text) > per_member:
            text = (text[:per_member].rsplit(" ", 1)[0] or text[:per_member]).rstrip() + "..."
        parts.append(text)
    proposed_summary = prefix + "; ".join(parts)
    report: dict[str, object] = {
        "schema_version": MEMORY_ROLLUP_SCHEMA_VERSION,
        "applied": False,
        "eligible": eligible,
        "reason_code": reason_code,
        "selector": selector,
        "episode_perspective": {"observer": episode_perspective[0], "observed": episode_perspective[1]},
        "episode_retention": {"class": episode_retention, "ttl_days": episode_ttl_days},
        "members": [
            {
                "record_id": str(record.get("record_id", "")),
                "record_type": str(record.get("record_type", "")),
                "summary": _redact(str(record.get("summary", "")))[:240],
                "approved_at": str(record.get("approved_at", "")),
            }
            for record in members
        ],
        "member_count": len(members),
        "considered_count": considered,
        "truncated_members": truncated_members,
        "proposed_summary": _redact(proposed_summary)[:240],
        "next_action": _rollup_next_action(reason_code),
        "redaction_policy": "metadata_only",
        "claim_boundary": (
            "A rollup prepares one reviewable episode candidate over existing OMH records; "
            "originals are unchanged, and nothing here is execution, review, CI, merge, or "
            "Hermes internal-memory evidence."
        ),
    }
    if apply and eligible:
        already_staged = _find_pending_candidate_by_summary(paths, proposed_summary)
        if already_staged:
            report["reason_code"] = "already_staged"
            report["staged_candidate_id"] = already_staged
            report["next_action"] = "An identical episode candidate is already pending review; approve or reject it first."
            return report
        capture = capture_project_memory_candidate(
            paths,
            proposed_summary,
            record_type="episode",
            scope_kind=episode_scope["kind"],
            scope_ref=episode_scope["ref"],
            source="rollup",
            tags=[normalized_tag] if normalized_tag else [],
            ttl_days=episode_ttl_days,
            retention_class=episode_retention,
            derived_from=[str(record.get("record_id", "")) for record in members],
            observer=episode_perspective[0] or None,
            observed=episode_perspective[1] or None,
            force_review=True,
        )
        candidate_status = str(capture.get("candidate", {}).get("status", "")) if isinstance(capture.get("candidate"), dict) else ""
        report["applied"] = bool(capture.get("captured")) and candidate_status == "pending_review"
        report["candidate_status"] = candidate_status
        report["capture"] = capture
        report["next_action"] = (
            "Review and approve the staged episode candidate; member records remain active."
            if report["applied"]
            else "The episode candidate did not reach pending review; inspect the capture payload."
        )
    return report


def _rollup_next_action(reason_code: str) -> str:
    return {
        "planned": "Run with --apply to stage the episode candidate for review.",
        "not_enough_members": "Nothing to roll up: fewer than two eligible member records matched.",
        "mixed_scope": "Members span multiple scopes; narrow the selector so one scope remains.",
        "mixed_perspective": "Members span multiple perspectives; narrow the selector so one perspective remains.",
    }[reason_code]


def _find_pending_candidate_by_summary(paths: OmhPaths, summary: str) -> str:
    key = _normalized_summary_key(_redact(summary.strip())[:500])
    if not key:
        return ""
    for candidate in _read_project_memory_candidates(paths):
        if str(candidate.get("status", "")) not in {"pending_review", "blocked_review_required"}:
            continue
        if _normalized_summary_key(str(candidate.get("summary", ""))) == key:
            return str(candidate.get("candidate_id", ""))
    return ""


def _recall_query_intent(query: str) -> str:
    """Return "temporal" for an unambiguous time cue, else "default".

    Token cues use the recall tokenizer, so matching is exact token overlap,
    never substring guessing ("nowhere" and "knownHosts" stay default).
    Known limitation: hyphenated compounds tokenize whole ("recently-requested"),
    so a cue inside one does not fire. Phrase cues match on whitespace-
    normalized lowercase text.
    """
    if not query.strip():
        return "default"
    if _memory_tokens(query) & _TEMPORAL_QUERY_CUES:
        return "temporal"
    normalized = f" {' '.join(query.lower().split())} "
    return "temporal" if any(f" {phrase} " in normalized for phrase in _TEMPORAL_QUERY_PHRASES) else "default"


def _memory_pins_path(paths: OmhPaths) -> Path:
    return paths.memory_dir / "pins.json"


def read_memory_pins(paths: OmhPaths) -> list[str]:
    """Pinned record ids; a missing or corrupt store reads as no pins.

    Pins are a delivery-priority hint like usage counters, never an
    eligibility input, so losing the sidecar must never cost a recall.
    """
    data, _error = read_json_object_result(_memory_pins_path(paths))
    if not isinstance(data, dict) or data.get("schema_version") != MEMORY_PINS_SCHEMA_VERSION:
        return []
    record_ids = data.get("record_ids")
    if not isinstance(record_ids, list):
        return []
    return sorted({str(record_id) for record_id in record_ids if _SAFE_REF.match(str(record_id))})


def set_memory_pin(paths: OmhPaths, record_id: str, *, pinned: bool) -> dict[str, object]:
    """Pin or unpin one record. Pinning requires the record to exist; an
    unpin is always allowed so stale pin entries can be cleaned up."""
    normalized = str(record_id).strip()
    if not _SAFE_REF.match(normalized):
        raise ValueError(f"unsafe memory record id: {record_id!r}")
    if pinned:
        known = {str(record.get("record_id", "")) for record in _read_project_memory_records(paths)}
        if normalized not in known:
            raise ValueError(f"memory record not found: {normalized}")
    ensure_dir(paths.memory_dir)
    with file_lock(_memory_pins_path(paths), timeout_seconds=1.0, private=True):
        pins = set(read_memory_pins(paths))
        if pinned:
            pins.add(normalized)
            if len(pins) > _MEMORY_PINS_LIMIT:
                raise ValueError(f"at most {_MEMORY_PINS_LIMIT} records can be pinned; unpin one first")
        else:
            pins.discard(normalized)
        atomic_write_json(
            _memory_pins_path(paths),
            {"schema_version": MEMORY_PINS_SCHEMA_VERSION, "updated_at": utc_now(), "record_ids": sorted(pins)},
            private=True,
        )
    return {
        "schema_version": MEMORY_PINS_SCHEMA_VERSION,
        "record_id": normalized,
        "pinned": pinned,
        "pinned_record_ids": sorted(pins),
        "pin_count": len(pins),
        "redaction_policy": "metadata_only",
        "claim_boundary": (
            "A pin is an OMH-local delivery-priority marker only; it never overrides expiry, scope, "
            "perspective, or review eligibility, and it is not execution or Hermes internal-memory evidence."
        ),
    }


def _age_tier(approved_at: str, *, now: datetime) -> int:
    """0 for young, 1 for aging, 2 for old; unparseable timestamps stay 0 so
    a malformed record is never silently downweighted."""
    # Naive timestamps read as UTC, matching the expiry classifier: the
    # plain _parse_utc would read them as host-local and shift the tier by
    # up to +/-14 hours at the 30/180-day boundaries.
    approved = _parse_utc_naive_as_utc(str(approved_at or ""))
    if approved is None:
        return 0
    age_days = max((now - approved).total_seconds(), 0.0) / 86400.0
    if age_days >= _AGE_TIER_BOUNDS_DAYS[1]:
        return 2
    if age_days >= _AGE_TIER_BOUNDS_DAYS[0]:
        return 1
    return 0


def _handoff_perspective_lens(executor_target: str | None) -> str:
    """Lens every handoff surface applies: scoped records reach only the
    executor they are about. An unresolved target ('' or 'choose') stays a
    lens that matches no scoped record: until an executor is actually
    selected, a handoff carries unscoped records only, never a leak of some
    other actor's lessons."""
    return str(executor_target or "").strip().lower() or "choose"


def _validate_perspective(value: Any, errors: list[str], label: str, *, require_observed: bool = False) -> None:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return
    _validate_allowed_keys(value, _PERSPECTIVE_KEYS, errors, label)
    for key in ("observer", "observed"):
        actor = value.get(key, "")
        if not isinstance(actor, str) or (actor and not _SAFE_REF.match(actor)):
            errors.append(f"{label}.{key} must be a safe actor label")
    if require_observed and not str(value.get("observed", "") or ""):
        errors.append(f"{label}.observed must name an actor")


def _normalize_perspective(observer: str | None, observed: str | None) -> dict[str, str] | None:
    """Optional (observer, observed) pair; absent means an unscoped record.

    The observed actor is the interesting axis in OMH -- which executor or
    role a fact is about -- so it is the only required half: an omitted
    observer defaults to Hermes, the retained-cognition owner. Supplying an
    observer without an observed actor has no lens to match against and is
    rejected rather than guessed.
    """
    observer_label = str(observer or "").strip().lower()
    observed_label = str(observed or "").strip().lower()
    if not observer_label and not observed_label:
        return None
    if not observed_label:
        raise ValueError("a memory perspective requires --observed; --observer alone names no target actor")
    observer_label = observer_label or _DEFAULT_PERSPECTIVE_OBSERVER
    for label in (observer_label, observed_label):
        if not _SAFE_REF.match(label):
            raise ValueError(f"unsafe perspective actor label: {label!r}")
    return {"observer": observer_label, "observed": observed_label}


def _perspective_projection(value: Any) -> dict[str, str]:
    """Projection of a stored perspective; {} when there is nothing observed.

    An empty observed actor is not a perspective -- the lens ignores it -- so
    projecting it would advertise scoping the filter does not apply.
    """
    perspective = value if isinstance(value, dict) else {}
    observed = str(perspective.get("observed", ""))
    if not observed:
        return {}
    return {"observer": str(perspective.get("observer", "") or _DEFAULT_PERSPECTIVE_OBSERVER), "observed": observed}


def _record_perspective_matches(record: dict[str, Any], *, observer: str | None, observed: str | None) -> bool:
    """Lens semantics: unscoped records always pass; scoped need a match.

    No lens (both None) also passes scoped records -- a plain recall is an
    inspection surface and hides nothing. Filtering both ways (a lens that
    excludes unscoped records) is deliberately not offered: unscoped is the
    compatibility default, not a perspective of its own.
    """
    perspective = record.get("perspective")
    if not isinstance(perspective, dict) or not str(perspective.get("observed", "")):
        return True
    if observer is None and observed is None:
        return True
    if observer is not None and str(perspective.get("observer", "")) != observer:
        return False
    if observed is not None and str(perspective.get("observed", "")) != observed:
        return False
    return True


def build_memory_perspectives(paths: OmhPaths) -> dict[str, object]:
    """Deterministic inventory of (observer, observed) pairs -- honcho's
    collections listing reinterpreted as a report over the records store."""
    pairs: dict[tuple[str, str], int] = {}
    unscoped = 0
    for record in _read_project_memory_records(paths):
        perspective = record.get("perspective")
        if isinstance(perspective, dict) and str(perspective.get("observed", "")):
            key = (str(perspective.get("observer", "")), str(perspective.get("observed", "")))
            pairs[key] = pairs.get(key, 0) + 1
        else:
            unscoped += 1
    return {
        "schema_version": MEMORY_PERSPECTIVES_SCHEMA_VERSION,
        "pairs": [
            {"observer": observer, "observed": observed, "record_count": count}
            for (observer, observed), count in sorted(pairs.items())
        ],
        "pair_count": len(pairs),
        "unscoped_count": unscoped,
        "redaction_policy": "metadata_only",
        "claim_boundary": (
            "A perspectives report counts OMH-local reviewed records per observer/observed pair, "
            "regardless of expiry or replay eligibility; it is prepared context, not execution, "
            "review, CI, merge, or Hermes internal-memory evidence."
        ),
    }


def _normalize_derived_from(paths: OmhPaths, derived_from: list[str] | tuple[str, ...] | None) -> list[str]:
    """Validate provenance refs at capture: bounded, safe, and resolvable.

    A ref must name an existing approved record when the link is written --
    dangling links would make every lineage report start from guesswork. A
    referenced record that is later retired shows up as unresolved in the
    lineage report instead; that asymmetry is deliberate.
    """
    refs: list[str] = []
    for ref in derived_from or []:
        normalized = str(ref).strip()
        if normalized and normalized not in refs:
            refs.append(normalized)
    if not refs:
        return []
    if len(refs) > _DERIVED_FROM_LIMIT:
        raise ValueError(f"derived-from accepts at most {_DERIVED_FROM_LIMIT} record ids")
    known = {str(record.get("record_id", "")) for record in _read_project_memory_records(paths)}
    for ref in refs:
        if not _SAFE_REF.match(ref):
            raise ValueError(f"unsafe derived-from record id: {ref!r}")
        if ref not in known:
            # The records reader skips unreadable files, so distinguish a
            # crash-corrupted record from a genuinely absent one -- "not
            # found" would send the operator hunting for a file that exists.
            if (_memory_records_dir(paths) / f"{ref}.json").is_file():
                raise ValueError(f"derived-from record is unreadable: {ref}")
            raise ValueError(f"derived-from record not found: {ref}")
    return refs


def build_memory_lineage(paths: OmhPaths, record_id: str, *, depth: int = 3) -> dict[str, object]:
    """Trace derived-from links up (ancestors) and down (descendants).

    Report-only graph traversal over the active records directory: archived
    or pruned records surface as unresolved refs rather than errors, cycles
    are cut by the visited set, and depth is capped so a pathological chain
    cannot make the report unbounded.
    """
    depth = max(1, min(int(depth), _LINEAGE_MAX_DEPTH))
    records = {
        str(record.get("record_id", "")): record
        for record in _read_project_memory_records(paths)
        if str(record.get("record_id", ""))
    }
    base = {
        "schema_version": MEMORY_LINEAGE_SCHEMA_VERSION,
        "record_id": str(record_id),
        "depth": depth,
        "redaction_policy": "metadata_only",
        "claim_boundary": (
            "A lineage report traces OMH-local derived-from links only; "
            "it is prepared context, not execution, review, CI, merge, or Hermes internal-memory evidence."
        ),
    }
    root = records.get(str(record_id))
    if root is None:
        return {
            **base,
            "found": False,
            "record": {},
            "ancestors": [],
            "descendants": [],
            "unresolved_refs": [],
            "truncated": False,
            "counts": {"ancestors": 0, "descendants": 0, "unresolved": 0},
        }
    children_of: dict[str, list[str]] = {}
    for child_id in sorted(records):
        for ref in _string_list(records[child_id].get("derived_from", [])):
            children_of.setdefault(ref, []).append(child_id)
    ancestors: list[dict[str, object]] = []
    unresolved: list[dict[str, object]] = []
    seen_unresolved: set[tuple[str, str]] = set()
    truncated = False
    visited = {str(record_id)}
    frontier = [str(record_id)]
    for hop in range(1, depth + 1):
        next_frontier: list[str] = []
        for node_id in frontier:
            for ref in _string_list(records[node_id].get("derived_from", [])):
                if ref in visited:
                    continue
                if ref not in records:
                    if (ref, node_id) not in seen_unresolved:
                        seen_unresolved.add((ref, node_id))
                        unresolved.append({"record_id": ref, "referenced_by": node_id})
                    continue
                visited.add(ref)
                ancestors.append(_lineage_card(records[ref], depth=hop))
                next_frontier.append(ref)
        frontier = next_frontier
    # Any unexpanded ref past the horizon -- resolvable or dangling -- means
    # the traversal is incomplete; a dangling parent one hop past --depth
    # must not read as a complete report.
    truncated = truncated or any(
        ref not in visited
        for node_id in frontier
        for ref in _string_list(records[node_id].get("derived_from", []))
    )
    descendants: list[dict[str, object]] = []
    visited_down = {str(record_id)}
    frontier = [str(record_id)]
    for hop in range(1, depth + 1):
        next_frontier = []
        for node_id in frontier:
            for child_id in children_of.get(node_id, []):
                if child_id in visited_down:
                    continue
                visited_down.add(child_id)
                descendants.append(_lineage_card(records[child_id], depth=hop))
                next_frontier.append(child_id)
        frontier = next_frontier
    truncated = truncated or any(
        child_id not in visited_down
        for node_id in frontier
        for child_id in children_of.get(node_id, [])
    )
    return {
        **base,
        "found": True,
        "record": _lineage_card(root, depth=0),
        "ancestors": ancestors,
        "descendants": descendants,
        "unresolved_refs": unresolved,
        "truncated": truncated,
        "counts": {"ancestors": len(ancestors), "descendants": len(descendants), "unresolved": len(unresolved)},
    }


def _lineage_card(record: dict[str, Any], *, depth: int) -> dict[str, object]:
    return {
        "record_id": str(record.get("record_id", "")),
        "depth": depth,
        "record_type": str(record.get("record_type", "")),
        "summary": _redact(str(record.get("summary", "")))[:500],
        "scope": _normalize_scope(record.get("scope", _scope("project", "default"))),
        "tags": _normalize_tags(record.get("tags", [])),
        "approved_at": str(record.get("approved_at", "")),
        "staleness": _record_staleness(record),
        "derived_from": _string_list(record.get("derived_from", [])),
    }


RETIREMENT_REPORT_SCHEMA_VERSION = "omh_memory_retirement_report/v1"
RETIREMENT_JOURNAL_SCHEMA_VERSION = "omh_memory_retirement_journal/v1"
_RETIREMENT_JOURNAL_CLAIM_BOUNDARY = (
    "A retirement journal line records that OMH moved one of its own expired records to its "
    "local archive. It is not a deletion and not Hermes internal-memory evidence."
)
_ARCHIVE_COMPACT_FORMAT = "%Y%m%dT%H%M%SZ"


def _compact_retired_at(retired_at: str) -> str:
    return retired_at.replace("-", "").replace(":", "")


def _iso_from_compact(compact: str) -> str | None:
    try:
        parsed = datetime.strptime(compact, _ARCHIVE_COMPACT_FORMAT)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _retirements_journal_path(paths: OmhPaths) -> Path:
    return _memory_archive_dir(paths) / "retirements.jsonl"


def _append_retirement_journal(paths: OmhPaths, record_id: str, retired_at: str, expires_at: str) -> dict[str, object]:
    entry = {
        "schema_version": RETIREMENT_JOURNAL_SCHEMA_VERSION,
        "record_id": record_id,
        "retired_at": retired_at,
        "expires_at": expires_at,
        "redaction_policy": "metadata_only",
        "claim_boundary": _RETIREMENT_JOURNAL_CLAIM_BOUNDARY,
    }
    append_jsonl_locked(_retirements_journal_path(paths), entry)
    return entry


def _mark_candidate_retired(paths: OmhPaths, record_id: str) -> bool:
    """Flip the approved candidate that produced ``record_id`` to retired.

    Without this, the candidate keeps claiming an approval whose record no
    longer exists, and re-approving it resurrects the retired record silently.
    """
    for candidate in _read_project_memory_candidates(paths):
        if str(candidate.get("record_id", "")) == record_id and str(candidate.get("status", "")) == "approved":
            _write_project_memory_candidate_unlocked(paths, {**candidate, "status": "retired", "retired_at": utc_now()})
            return True
    return False


def _journal_pairs(paths: OmhPaths) -> set[tuple[str, str]]:
    entries, _errors = read_jsonl_objects(_retirements_journal_path(paths))
    return {
        (str(entry.get("record_id", "")), str(entry.get("retired_at", "")))
        for entry in entries
        if entry.get("schema_version") == RETIREMENT_JOURNAL_SCHEMA_VERSION
    }


def _reconcile_retirement_archive(paths: OmhPaths) -> list[dict[str, object]]:
    """Heal archives a crash left half-recorded. Runs inside the store lock.

    Each invariant is repaired independently: a missing journal line is
    appended, a still-approved source candidate is flipped to retired, and the
    index is covered by the transaction's final rewrite. A fully consistent
    entry produces no row, so a post-recovery rerun reports nothing.
    """
    archive_dir = _memory_archive_dir(paths)
    if not archive_dir.exists():
        return []
    pairs = _journal_pairs(paths)
    reconciled: list[dict[str, object]] = []
    for path in sorted(archive_dir.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        stem = path.name[: -len(".json")]
        record_id, _, compact = stem.rpartition(".")
        retired_at = _iso_from_compact(compact) if record_id else None
        if not record_id or retired_at is None or not _SAFE_REF.match(record_id):
            continue
        repaired: list[str] = []
        if (record_id, retired_at) not in pairs:
            data, _error = read_json_object_result(path)
            ttl = data.get("ttl", {}) if isinstance(data, dict) and isinstance(data.get("ttl"), dict) else {}
            _append_retirement_journal(paths, record_id, retired_at, str(ttl.get("expires_at", "") or ""))
            repaired.append("journal")
        if _mark_candidate_retired(paths, record_id):
            repaired.append("candidate")
        if repaired:
            reconciled.append({"record_id": record_id, "retired_at": retired_at, "repaired": repaired})
    return reconciled


def _clear_expiring_only_brief(paths: OmhPaths) -> bool:
    """Retire a brief whose only ask was the retirement that just ran."""
    brief_path = _consolidation_path(paths.omh_home)
    brief, _error = read_json_object_result(brief_path)
    if not isinstance(brief, dict) or brief.get("schema_version") != "omh_memory_consolidation_handoff/v1":
        return False
    reasons = [str(reason) for reason in brief.get("reasons", []) if isinstance(reason, str)]
    if not brief.get("due") or not reasons or not all(reason.startswith("expiring_records:") for reason in reasons):
        return False
    retired = dict(brief)
    retired["due"] = False
    retired["superseded_at"] = utc_now()
    retired["superseded_by"] = "omh memory retire --apply"
    atomic_write_json(brief_path, retired, private=True)
    return True


def apply_memory_retirement(
    paths: OmhPaths,
    *,
    now: datetime | None = None,
    window_days: int = 7,
) -> dict[str, object]:
    """Move expired records into the archive. The only mover in the store.

    One store-lock acquisition covers reconciliation, the scan, every move,
    the journal appends, the candidate flips, and the index rewrite --
    ``file_lock`` is not reentrant, so everything inside goes through the
    unlocked helpers. Files are moved with ``os.replace`` and never deleted;
    a crash at any point heals on the next run via the reconciliation pass.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    retired_at = now.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    archive_dir = _memory_archive_dir(paths)
    ensure_dir(archive_dir, private=True)
    records_dir = _memory_records_dir(paths)
    with file_lock(paths.memory_index_path, private=True):
        reconciled = _reconcile_retirement_archive(paths)
        report = build_memory_retirement(paths, now=now, window_days=window_days)
        moved: list[dict[str, object]] = []
        skipped = list(report["skipped"])
        for row in report["expired"]:
            source = records_dir / str(row["path_name"])
            if source.is_symlink() or not source.is_file():
                skipped.append({"path_name": str(row["path_name"]), "reason": "symlink_or_not_file"})
                continue
            destination = archive_dir / f"{row['record_id']}.{_compact_retired_at(retired_at)}.json"
            _assert_under_memory_root(paths, destination)
            if destination.exists():
                skipped.append({"path_name": str(row["path_name"]), "reason": "archive_collision"})
                continue
            os.replace(source, destination)
            os.chmod(destination, 0o600)
            _append_retirement_journal(paths, str(row["record_id"]), retired_at, str(row["expires_at"]))
            _mark_candidate_retired(paths, str(row["record_id"]))
            moved.append({**row, "archived_as": destination.name, "retired_at": retired_at})
        _write_memory_index_unlocked(paths)
        brief_cleared = bool(moved or reconciled) and _clear_expiring_only_brief(paths)
    payload = dict(report)
    payload["applied"] = True
    payload["moved"] = moved
    payload["reconciled"] = reconciled
    payload["skipped"] = skipped
    payload["brief_cleared"] = brief_cleared
    payload["claim_boundary"] = (
        "A retirement apply moves OMH's own expired records into OMH's local archive. It never "
        "deletes, and it is not evidence that Hermes memory changed."
    )
    payload["next_action"] = "Archived records stay readable under .omh/memory/archive/."
    return payload


def _memory_archive_dir(paths: OmhPaths) -> Path:
    return paths.memory_dir / "archive"


def build_memory_retirement(
    paths: OmhPaths,
    *,
    now: datetime | None = None,
    window_days: int = 7,
) -> dict[str, object]:
    """Which approved records are past or near their deadline. Report only.

    Scans the records directory directly rather than through
    ``_read_project_memory_records`` because that reader raises on the first
    corrupt file -- and corrupt files are exactly what accumulates in a store
    nothing ever cleans. Here one unreadable file costs one ``skipped`` row,
    never the run.

    Fail-closed: only canonical records (right schema, approved, safe
    ``record_id`` matching the filename) are classified, and only the
    classifier's ``expired`` verdict can ever nominate a move. A missing or
    empty TTL is a healthy record that never expires; a present-but-unreadable
    one is surfaced as ``malformed_expires_at`` and left alone.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    records_dir = _memory_records_dir(paths)
    recall_usage = read_recall_usage(paths)
    pinned_ids = set(read_memory_pins(paths))
    expired: list[dict[str, object]] = []
    expiring_soon: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    candidates = sorted(records_dir.glob("*.json")) if records_dir.exists() else []
    for path in candidates:
        if path.is_symlink() or not path.is_file():
            skipped.append({"path_name": path.name, "reason": "symlink_or_not_file"})
            continue
        data, _error = read_json_object_result(path)
        if data is None:
            skipped.append({"path_name": path.name, "reason": "corrupt_json"})
            continue
        is_v2_approved = (
            data.get("schema_version") == PROJECT_MEMORY_RECORD_SCHEMA_VERSION
            and isinstance(data.get("admission"), dict)
            and data["admission"].get("state") in {"approved_manual", "approved_auto_safe"}
            and data.get("review_status", "approved") == "approved"
        )
        is_v1_approved = (
            data.get("schema_version") == LEGACY_PROJECT_MEMORY_RECORD_SCHEMA_VERSION
            and data.get("review_status") == "approved"
        )
        if not (is_v2_approved or is_v1_approved):
            skipped.append({"path_name": path.name, "reason": "not_canonical"})
            continue
        record_id = str(data.get("record_id", ""))
        if not _SAFE_REF.match(record_id) or record_id != path.stem:
            skipped.append({"path_name": path.name, "reason": "unsafe_record_id"})
            continue
        state = _classify_record_expiry(data, now=now, window_days=window_days)
        ttl = data.get("ttl", {}) if isinstance(data.get("ttl"), dict) else {}
        row = {
            "record_id": record_id,
            "expires_at": str(ttl.get("expires_at", "") or ""),
            "path_name": path.name,
            # Delivery-usage annotation only: a never-delivered record is a
            # cheaper retire call than one executors keep receiving. A pin
            # likewise annotates, never blocks: expiry still wins.
            "recall_usage": recall_usage.get(record_id, {"times_recalled": 0, "last_recalled_at": ""}),
            "pinned": record_id in pinned_ids,
        }
        if state == "expired":
            expired.append(row)
        elif state == "expiring":
            expiring_soon.append(row)
        elif state == "malformed":
            skipped.append({"path_name": path.name, "reason": "malformed_expires_at"})
    return {
        "schema_version": RETIREMENT_REPORT_SCHEMA_VERSION,
        "applied": False,
        "window_days": window_days,
        "expired": expired,
        "expiring_soon": expiring_soon,
        "skipped": skipped,
        "reconciled": [],
        "counts": {"expired": len(expired), "expiring_soon": len(expiring_soon), "skipped": len(skipped)},
        "archive_dir": str(_memory_archive_dir(paths)),
        "redaction_policy": "metadata_only",
        "claim_boundary": (
            "A retirement report proposes what is past its deadline. It is not a deletion, not a move, "
            "and not evidence that Hermes memory or OMH records changed."
        ),
        "next_action": "Run `omh memory retire --apply` to move expired records into the archive.",
    }


def build_memory_inspection(
    paths: OmhPaths,
    *,
    wrapper_snapshot: dict[str, Any] | None = None,
    scope_kind: str | None = None,
    scope_ref: str | None = None,
    session_limit: int | None = None,
    summary: bool = False,
    review_item_limit: int | None = None,
) -> dict[str, object]:
    snapshots = _local_snapshots(paths, scope_kind=scope_kind, scope_ref=scope_ref, session_limit=session_limit)
    if wrapper_snapshot:
        snapshots.append(_normalize_wrapper_snapshot(wrapper_snapshot))
    conflicts = _detect_conflicts(snapshots)
    stale_candidates = [conflict for conflict in conflicts if conflict["severity"] in {"warning", "blocker"}]
    all_review_items = _review_items(snapshots, conflicts)
    review_items = _limited_items(all_review_items, review_item_limit)
    payload: dict[str, object] = {
        "schema_version": MEMORY_INSPECTION_SCHEMA_VERSION,
        "created_at": utc_now(),
        "snapshots": [] if summary else snapshots,
        "snapshot_summary": _snapshot_summary(snapshots) if summary else [],
        "snapshot_count": len(snapshots),
        "review_items": review_items,
        "review_item_count": len(all_review_items),
        "conflicts": conflicts,
        "stale_candidates": stale_candidates,
        "recommended_actions": _recommended_actions(conflicts),
        "handoff_context_preview": _handoff_preview(snapshots, conflicts),
        "redaction_policy": "metadata_only",
        "claim_boundary": (
            "Memory inspection reviews OMH-local or wrapper-supplied context only; it is not proof that Hermes internal memory was read or changed."
        ),
    }
    payload["review_card"] = build_memory_review_card(payload)
    return payload


def build_memory_review_card(inspection: dict[str, Any]) -> dict[str, object]:
    review_items = list(inspection.get("review_items", []) if isinstance(inspection.get("review_items"), list) else [])
    conflicts = list(inspection.get("conflicts", []) if isinstance(inspection.get("conflicts"), list) else [])
    blocker_count = sum(1 for conflict in conflicts if isinstance(conflict, dict) and conflict.get("severity") == "blocker")
    headline = "Review Hermes memory assumptions."
    if blocker_count:
        headline = f"Review {blocker_count} stale or conflicting memory assumption(s)."
    return {
        "schema_version": MEMORY_REVIEW_CARD_SCHEMA_VERSION,
        "headline": headline,
        "summary": f"{len(review_items)} memory/context item(s) are available for review; {len(conflicts)} conflict(s) are flagged.",
        "primary_action": "apply_memory_updates" if review_items else "show_memory_status",
        "actions": [_memory_action(action_id) for action_id in MEMORY_ACTION_IDS],
        "review_items": review_items,
        "conflicts": conflicts,
        "redaction_policy": "metadata_only",
        "claim_boundary": "Memory review is not runtime execution evidence and does not mutate opaque Hermes memory.",
    }


def build_handoff_context_pack(
    paths: OmhPaths,
    *,
    inspection: dict[str, Any] | None = None,
    executor_target: str = "generic",
    session_id: str = "",
    scope_kind: str | None = None,
    scope_ref: str | None = None,
    session_limit: int | None = None,
    context_limit: int = 12,
    now: datetime | None = None,
    stale_override: dict[str, object] | None = None,
    run_id: str | None = None,
) -> dict[str, object]:
    if inspection is None:
        snapshots = _local_snapshots(paths, scope_kind=scope_kind, scope_ref=scope_ref, session_limit=session_limit, now=now)
        inspection = {"snapshots": snapshots, "conflicts": _detect_conflicts(snapshots)}
    conflicts = [conflict for conflict in inspection.get("conflicts", []) if isinstance(conflict, dict)]
    blocking_conflicts = [conflict for conflict in conflicts if conflict.get("severity") == "blocker"]
    conflict_ids = {str(conflict.get("item_id", "")) for conflict in blocking_conflicts}
    perspective_lens = _handoff_perspective_lens(executor_target)
    review_resolver = _project_memory_review_resolver(paths)
    included: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    for snapshot in inspection.get("snapshots", []):
        if not isinstance(snapshot, dict):
            continue
        source = str(snapshot.get("source", ""))
        for item in snapshot.get("items", []) if isinstance(snapshot.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("item_id", ""))
            if source == "omh_memory":
                artifact = _memory_artifact_for_snapshot_item(paths, item)
                # Context packs are executor-facing exactly like recall
                # packs, so they apply the same lens: a record about another
                # executor is excluded here, not silently skipped, because
                # this surface enumerates its exclusions.
                if not _record_perspective_matches(artifact, observer=None, observed=perspective_lens):
                    excluded.append({"item_id": item_id, "source": source, "reason": "perspective_mismatch"})
                    continue
                if _item_conflicts(item, blocking_conflicts):
                    artifact = {**artifact, "conflict_ids": [item_id]}
                evaluation = _evaluate_memory_artifact(
                    artifact,
                    paths=paths,
                    now=now,
                    review_resolver=review_resolver,
                    conflict_ids=conflict_ids,
                    stale_override=stale_override,
                    run_id=run_id,
                )
                if not evaluation["eligible"]:
                    excluded.append(
                        {
                            "item_id": item_id,
                            "source": source,
                            "reason": str(evaluation["reason_code"]),
                            "replay_evaluation": evaluation,
                        }
                    )
                    continue
            elif _item_conflicts(item, blocking_conflicts):
                excluded.append({"item_id": item_id, "source": source, "reason": "blocked_by_unresolved_conflict"})
                continue
            else:
                evaluation = {}
            if _is_packable(item, snapshot):
                context_item: dict[str, object] = {
                    "item_id": item_id,
                    "key": str(item.get("key", "")),
                    "summary": str(item.get("summary", "")),
                    "source": source,
                    "truth_level": str(snapshot.get("truth_level", "")),
                    "scope": item.get("scope", snapshot.get("scope", _scope("project", "default"))),
                }
                if evaluation:
                    context_item["replay_evaluation"] = evaluation
                included.append(context_item)
            else:
                excluded.append({"item_id": item_id, "source": source, "reason": "not_packable"})
    kept = included[: max(context_limit, 0)]
    for item in included[len(kept) :]:
        excluded.append(
            {
                "item_id": str(item.get("item_id", "")),
                "source": str(item.get("source", "")),
                "reason": "over_budget",
                **({"replay_evaluation": item["replay_evaluation"]} if "replay_evaluation" in item else {}),
            }
        )
    return {
        "schema_version": HANDOFF_CONTEXT_PACK_SCHEMA_VERSION,
        "executor_target": executor_target,
        "session_id": session_id,
        "scope": _scope("project", "default"),
        "source_refs": _source_refs(inspection),
        "included_context": kept,
        "excluded_context": excluded,
        "blocked_by_conflicts": blocking_conflicts,
        "redaction_policy": "metadata_only",
        "claim_boundary": "Context packs contain evaluator-approved summaries only; they are prepared context, not observed executor or model use.",
    }


def apply_memory_update_batch(paths: OmhPaths, batch: dict[str, Any], *, dry_run: bool = False) -> dict[str, object]:
    """Compatibility entry point: legacy direct batches never mutate memory."""
    return legacy_batch_review_required(paths, batch, dry_run=dry_run)


def read_memory_snapshot_file(path: str | Path) -> dict[str, Any]:
    data = read_json_object(Path(path).expanduser().resolve())
    if not isinstance(data, dict):
        raise ValueError("memory snapshot fixture must be a JSON object")
    return data


def read_handoff_context_pack_file(path: str | Path) -> dict[str, Any]:
    data = read_json_object(Path(path).expanduser().resolve())
    if not isinstance(data, dict):
        raise ValueError("context pack must be a JSON object")
    errors = validate_handoff_context_pack(data, require_conflict_free=False, label="context pack")
    if errors:
        raise ValueError("; ".join(errors))
    return data


def validate_handoff_context_pack(value: Any, *, require_conflict_free: bool, label: str = "context_pack") -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    _validate_allowed_keys(value, _HANDOFF_CONTEXT_PACK_KEYS, errors, label)
    if value.get("schema_version") != HANDOFF_CONTEXT_PACK_SCHEMA_VERSION:
        errors.append(f"{label} schema_version must be {HANDOFF_CONTEXT_PACK_SCHEMA_VERSION}")
    if value.get("redaction_policy") != "metadata_only":
        errors.append(f"{label} redaction_policy must be metadata_only")
    if not isinstance(value.get("claim_boundary"), str):
        errors.append(f"{label} claim_boundary must be a string")
    if not isinstance(value.get("executor_target"), str):
        errors.append(f"{label} executor_target must be a string")
    if not isinstance(value.get("session_id"), str):
        errors.append(f"{label} session_id must be a string")
    _validate_context_scope(value.get("scope"), errors, f"{label}.scope")
    _validate_context_list(value.get("source_refs"), _HANDOFF_CONTEXT_SOURCE_REF_KEYS, errors, f"{label}.source_refs")
    _validate_context_list(value.get("included_context"), _HANDOFF_CONTEXT_INCLUDED_KEYS, errors, f"{label}.included_context", scope_key="scope")
    _validate_context_list(value.get("excluded_context"), _HANDOFF_CONTEXT_EXCLUDED_KEYS, errors, f"{label}.excluded_context")
    _validate_context_list(value.get("blocked_by_conflicts"), _HANDOFF_CONTEXT_CONFLICT_KEYS, errors, f"{label}.blocked_by_conflicts")
    if require_conflict_free and value.get("blocked_by_conflicts") != []:
        errors.append(f"{label} must be conflict-free when attached")
    if _contains_sensitive_text(value):
        errors.append(f"{label} contains sensitive-looking text and cannot be attached")
    return errors


def validate_handoff_context_blocked(value: Any, *, label: str = "context_pack_blocked") -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    _validate_allowed_keys(value, _HANDOFF_CONTEXT_BLOCKED_KEYS, errors, label)
    if value.get("schema_version") != "handoff_context_blocked/v1":
        errors.append(f"{label} schema_version must be handoff_context_blocked/v1")
    _validate_context_list(value.get("blocked_by_conflicts"), _HANDOFF_CONTEXT_CONFLICT_KEYS, errors, f"{label}.blocked_by_conflicts")
    if not value.get("blocked_by_conflicts"):
        errors.append(f"{label} requires at least one conflict")
    if not isinstance(value.get("claim_boundary"), str):
        errors.append(f"{label} claim_boundary must be a string")
    if _contains_sensitive_text(value):
        errors.append(f"{label} contains sensitive-looking text and cannot be attached")
    return errors


def validate_project_memory_recall_pack(value: Any, *, label: str = "memory_recall_pack") -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    _validate_allowed_keys(value, _PROJECT_MEMORY_RECALL_PACK_KEYS, errors, label)
    if value.get("schema_version") != PROJECT_MEMORY_RECALL_PACK_SCHEMA_VERSION:
        errors.append(f"{label} schema_version must be {PROJECT_MEMORY_RECALL_PACK_SCHEMA_VERSION}")
    if not isinstance(value.get("enabled"), bool):
        errors.append(f"{label}.enabled must be a boolean")
    if not isinstance(value.get("executor_target"), str):
        errors.append(f"{label}.executor_target must be a string")
    if not isinstance(value.get("session_id"), str):
        errors.append(f"{label}.session_id must be a string")
    _validate_context_scope(value.get("scope"), errors, f"{label}.scope")
    if "perspective" in value:
        _validate_perspective(value.get("perspective"), errors, f"{label}.perspective")
    if value.get("query_intent", "default") not in {"default", "temporal"}:
        errors.append(f"{label}.query_intent must be default or temporal")
    _validate_context_list(value.get("included_records"), _PROJECT_MEMORY_RECALL_ITEM_KEYS, errors, f"{label}.included_records", scope_key="scope")
    _validate_context_list(value.get("excluded_records"), _PROJECT_MEMORY_EXCLUDED_KEYS, errors, f"{label}.excluded_records")
    # Optional so a wrapper-supplied pack written before freshness warnings
    # existed still validates; present warnings are held to the full shape.
    if "freshness_warnings" in value:
        _validate_context_list(value.get("freshness_warnings"), _FRESHNESS_WARNING_KEYS, errors, f"{label}.freshness_warnings")
    _validate_context_map(value.get("task_ref"), _PROJECT_MEMORY_TASK_REF_KEYS, errors, f"{label}.task_ref")
    if not isinstance(value.get("truncated"), bool):
        errors.append(f"{label}.truncated must be a boolean")
    if not isinstance(value.get("policy"), dict):
        errors.append(f"{label}.policy must be an object")
    if value.get("redaction_policy") != "metadata_only":
        errors.append(f"{label}.redaction_policy must be metadata_only")
    if not isinstance(value.get("claim_boundary"), str):
        errors.append(f"{label}.claim_boundary must be a string")
    if _contains_sensitive_text(value):
        errors.append(f"{label} contains sensitive-looking text and cannot be attached")
    return errors


def _build_project_memory_candidate(
    summary: str,
    *,
    content: str,
    record_type: str,
    scope_kind: str,
    scope_ref: str,
    source: str,
    source_ref: str,
    tags: list[str] | tuple[str, ...],
    ttl_days: int | None,
    stale_after_days: int | None,
    retention_class: str,
    derived_from: list[str] | tuple[str, ...] = (),
    perspective: dict[str, str] | None = None,
) -> dict[str, object]:
    normalized_type = _normalize_record_type(record_type)
    scope = _scope_for_project_memory(scope_kind, scope_ref)
    normalized_tags = _normalize_tags(tags)
    content_text = str(content or "")
    safety = _project_memory_safety(summary, content_text, tags=normalized_tags)
    now = utc_now()
    ttl = _ttl_metadata(ttl_days, record_type=normalized_type, created_at=now)
    staleness = _staleness_metadata(stale_after_days, record_type=normalized_type, created_at=now)
    candidate_id = "cand_" + os.urandom(8).hex()
    status = "blocked_review_required" if safety["status"] == "blocked" else "pending_review"
    # Digest the ref exactly as it will be stored, not as it was passed:
    # redaction and truncation can change the string, and the freshness check
    # later reads the stored one.
    stored_source_ref = _redact(str(source_ref or ""))[:160]
    source_evidence = _source_evidence(stored_source_ref, captured_at=now)
    return {
        "schema_version": PROJECT_MEMORY_CANDIDATE_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "status": status,
        "record_type": normalized_type,
        "summary": _redact(summary.strip())[:500],
        "scope": scope,
        "tags": normalized_tags,
        "source": str(source or "cli"),
        "source_ref": stored_source_ref,
        **({"source_evidence": source_evidence} if source_evidence else {}),
        "created_at": now,
        "ttl": ttl,
        "staleness": staleness,
        "retention_class": str(retention_class),
        "derived_from": [str(ref) for ref in derived_from],
        **({"perspective": dict(perspective)} if perspective else {}),
        "content_ref": {
            "sha256": hashlib.sha256(content_text.encode("utf-8")).hexdigest() if content_text else "",
            "length": len(content_text),
            "raw_persisted": False,
        },
        "safety": safety,
        "redaction_policy": "metadata_only",
        "claim_boundary": "Memory candidates are OMH-local prepared context only; they are not approved memory or execution/review/CI/merge evidence.",
    }


def _record_from_candidate(
    candidate: dict[str, Any],
    *,
    approved_by: str,
    approved_at: str,
    review_id: str,
    admission_state: str,
) -> dict[str, object]:
    if admission_state not in ADMISSION_STATES:
        raise ValueError(f"unsupported memory admission state: {admission_state}")
    approved_at_value = _parse_utc(approved_at)
    if approved_at_value is None:
        raise ValueError("approved_at must be an ISO timestamp")
    record_type = _normalize_record_type(str(candidate.get("record_type", "fact")))
    retention = build_retention(
        str(candidate.get("retention_class", "standard")),
        record_type=record_type,
        admitted_at=approved_at_value,
        ttl_days=_candidate_ttl_days(candidate),
    )
    record_id = "mem_" + os.urandom(8).hex()
    scope = _normalize_scope(candidate.get("scope", _scope("project", "default")))
    revalidation = _candidate_revalidation(candidate)
    record: dict[str, object] = {
        "schema_version": PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
        "record_id": record_id,
        "candidate_id": str(candidate.get("candidate_id", "")),
        "revision": 1,
        "record_type": record_type,
        "summary": _redact(str(candidate.get("summary", "")))[:500],
        "scope": scope,
        "tags": _normalize_tags(candidate.get("tags", [])),
        "source": str(candidate.get("source", "cli")),
        "source_class": "omh_local",
        "source_ref": _redact(str(candidate.get("source_ref", "")))[:160],
        # The digest is carried over as observed at capture, never recomputed
        # here: approval must not silently re-bless a source that changed
        # while the candidate sat in the review queue.
        **({"source_evidence": evidence} if (evidence := _source_evidence_projection(candidate)) else {}),
        "derived_from": _string_list(candidate.get("derived_from", [])),
        **(
            {"perspective": projection}
            if (projection := _perspective_projection(candidate.get("perspective")))
            else {}
        ),
        "admission": {
            "state": admission_state,
            "review_id": review_id,
            "reviewer_claim": str(approved_by or "operator"),
            "admitted_at": approved_at,
            "policy_version": MEMORY_GOVERNANCE_POLICY_VERSION,
        },
        "retention": retention,
        "revalidation": revalidation,
        "approved_at": approved_at,
        "created_at": str(candidate.get("created_at", approved_at)),
        "updated_at": approved_at,
        "ttl": _ttl_projection(retention),
        "staleness": _staleness_projection(revalidation),
        "safety": candidate.get("safety", {}),
        "redaction_policy": "metadata_only",
        "claim_boundary": "Reviewed OMH project memory is prepared context only; it is not execution, review, CI, merge, or Hermes internal-memory evidence.",
    }
    admission = record["admission"]
    if isinstance(admission, dict):
        admission["payload_digest"] = canonical_payload_digest(record)
    return record


def _project_memory_review_record(
    record: dict[str, object],
    *,
    review_id: str,
    reviewer: str,
    decision: str,
) -> dict[str, object]:
    return {
        "schema_version": PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION,
        "review_id": review_id,
        "artifact_identity": stable_artifact_identity(record),
        "decision": decision,
        "reviewer_claim": str(reviewer or "operator"),
        "payload_digest": canonical_payload_digest(record),
        "policy_version": MEMORY_GOVERNANCE_POLICY_VERSION,
        "reviewed_at": str(record.get("approved_at", "")),
        "claim_boundary": "Project memory review decisions are prepared governance only, never executor-use evidence.",
    }


def _write_project_memory_review_decision(paths: OmhPaths, review: dict[str, object]) -> dict[str, object]:
    review_id = str(review.get("review_id", ""))
    if not _SAFE_REF.match(review_id):
        raise ValueError(f"unsafe memory review id: {review_id!r}")
    atomic_write_json(_memory_review_path(paths, review_id), review, private=True)
    return review


def _candidate_ttl_days(candidate: dict[str, Any]) -> int | None:
    ttl = candidate.get("ttl")
    ttl_days = ttl.get("ttl_days") if isinstance(ttl, dict) else None
    return ttl_days if isinstance(ttl_days, int) and not isinstance(ttl_days, bool) else None


def _candidate_revalidation(candidate: dict[str, Any]) -> dict[str, object]:
    staleness = candidate.get("staleness")
    deadline = staleness.get("stale_after") if isinstance(staleness, dict) else ""
    return {"deadline": str(deadline)} if deadline else {}


def _ttl_projection(retention: dict[str, object]) -> dict[str, object]:
    return {
        "ttl_days": retention.get("ttl_days"),
        "expires_at": str(retention.get("expires_at", "")),
    }


def _staleness_projection(revalidation: dict[str, object]) -> dict[str, object]:
    deadline = str(revalidation.get("deadline", ""))
    return {"stale_after": deadline, "stale_after_days": None, "review_due_at": deadline}


def _empty_recall_pack(
    policy: dict[str, object],
    *,
    executor_target: str,
    session_id: str,
    task_ref: dict[str, object],
    scope_kind: str | None,
    scope_ref: str | None,
    reason: str,
) -> dict[str, object]:
    return {
        "schema_version": PROJECT_MEMORY_RECALL_PACK_SCHEMA_VERSION,
        "enabled": False,
        "executor_target": executor_target,
        "session_id": session_id,
        "task_ref": task_ref,
        "policy": policy,
        "scope": _scope(scope_kind or "project", scope_ref or "default"),
        "perspective": {"observer": "", "observed": ""},
        "query_intent": "default",
        "included_records": [],
        "excluded_records": [{"record_id": "", "reason": reason, "staleness": {"state": "not_checked"}}],
        "freshness_warnings": [],
        "record_count": 0,
        "truncated": False,
        "redaction_policy": "metadata_only",
        "claim_boundary": "Memory recall is disabled or empty; no execution, review, CI, merge, or Hermes internal-memory evidence is produced.",
    }


def _recall_item(
    record: dict[str, Any],
    *,
    score: int,
    staleness: dict[str, object],
    evaluation: dict[str, object],
) -> dict[str, object]:
    evidence = _replay_evaluation(record, evaluation)
    return {
        "record_id": str(record.get("record_id", "")),
        "record_type": str(record.get("record_type", "")),
        "summary": _redact(str(record.get("summary", "")))[:500],
        "scope": _normalize_scope(record.get("scope", _scope("project", "default"))),
        "tags": _normalize_tags(record.get("tags", [])),
        "source": str(record.get("source", "")),
        "approved_at": str(record.get("approved_at", "")),
        "staleness": staleness,
        "score": int(score),
        "derived_from": _string_list(record.get("derived_from", [])),
        "perspective": _perspective_projection(record.get("perspective")),
        **_recall_evidence_fields(evidence),
    }


def _recall_exclusion(
    record: dict[str, Any],
    evaluation: dict[str, object],
    *,
    staleness: dict[str, object],
    reason: str | None = None,
) -> dict[str, object]:
    evidence = _replay_evaluation(record, evaluation)
    return {
        "record_id": str(record.get("record_id", "")),
        "reason": reason or str(evidence["reason_code"]),
        "staleness": staleness,
        **_recall_evidence_fields(evidence),
    }


def _freshness_warnings(
    included: list[dict[str, object]],
    excluded: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Name every record in this pack whose freshness is not confirmed.

    This is the surface acceptance criterion 1 asks for: before a stale,
    expired, superseded, or source-moved record can influence a plan or a
    handoff, the pack says which record it is, why revalidation is due, and
    that the operator must confirm, replace, or retire it. A held-back record
    warns exactly like a delivered one -- ``delivered`` says which happened --
    because a record silently missing from a pack is the failure this
    replaces, not the fix.

    Records excluded for reasons that are not about freshness
    (``no_query_overlap``, ``over_budget`` on a fresh record) never warn:
    a warning that fires for everything is read as noise and stops working.
    """
    warnings: list[dict[str, object]] = []
    seen: set[str] = set()
    for delivered, entry in [*((True, item) for item in included), *((False, item) for item in excluded)]:
        record_id = str(entry.get("record_id", ""))
        staleness = entry.get("staleness") if isinstance(entry.get("staleness"), dict) else {}
        state = str(staleness.get("state", ""))
        reason_code = str(entry.get("eligibility_reason", "") or "")
        known_reason = reason_code in _FRESHNESS_REASON_TEXT
        if not known_reason and state in {"", "fresh", "not_checked"}:
            continue
        if not record_id or record_id in seen:
            continue
        seen.add(record_id)
        if not known_reason:
            reason_code = "freshness_unconfirmed"
        warnings.append(
            {
                "record_id": record_id,
                "state": state or "unknown",
                "reason_code": reason_code,
                "review_due_at": str(staleness.get("review_due_at", "") or ""),
                "detail": _FRESHNESS_REASON_TEXT[reason_code],
                "delivered": bool(delivered),
                "next_action": _FRESHNESS_NEXT_ACTION,
            }
        )
        if len(warnings) >= _FRESHNESS_WARNING_LIMIT:
            break
    return warnings


def freshness_reason_detail(reason_code: str) -> str:
    """Human text for one recall-pack freshness reason code, or "" when unknown.

    Public so other handoff surfaces can explain a record with the vocabulary
    the recall pack already emits instead of growing a parallel table that
    drifts from it. Read-only on purpose: adding a code to `_FRESHNESS_REASON_TEXT`
    also changes what `_freshness_warnings` treats as a freshness reason, so
    the table stays owned by recall.
    """
    return _FRESHNESS_REASON_TEXT.get(str(reason_code), "")


def _recall_evidence_fields(value: Any) -> dict[str, object]:
    evidence = value if isinstance(value, dict) else {}
    return {
        "revision": int(evidence.get("revision", 0) or 0),
        "admission_mode": str(evidence.get("admission_mode") or ""),
        "source_class": str(evidence.get("source_class") or ""),
        "retention_class": str(evidence.get("retention_class") or ""),
        "evaluated_at": str(evidence.get("evaluated_at") or ""),
        "eligibility_reason": str(evidence.get("reason_code") or ""),
        "revalidation_evidence": evidence.get("revalidation_evidence", {}),
        "replay_evaluation": evidence,
    }


def _project_memory_review_resolver(paths: OmhPaths) -> dict[str, dict[str, object]]:
    return {
        str(review.get("review_id", "")): review
        for review in _read_project_memory_reviews(paths)
        if str(review.get("review_id", ""))
    }


def _evaluate_memory_artifact(
    artifact: dict[str, Any],
    *,
    paths: OmhPaths | None = None,
    now: datetime | None = None,
    requested_scope: dict[str, object] | None = None,
    review_resolver: dict[str, dict[str, object]] | None = None,
    conflict_ids: set[str] | None = None,
    stale_override: dict[str, object] | None = None,
    run_id: str | None = None,
) -> dict[str, object]:
    evaluator_artifact = _normalize_evaluator_timestamps(artifact)
    if evaluator_artifact.get("schema_version") == LEGACY_MEMORY_SCOPE_SCHEMA_VERSION:
        # Governance has one legacy reason code for v1 project records. Map
        # the preserved v1 scope schema into that read-only compatibility
        # classification rather than coercing it into an invalid v2 artifact.
        evaluator_artifact = {**evaluator_artifact, "schema_version": LEGACY_PROJECT_MEMORY_RECORD_SCHEMA_VERSION}
    result = evaluate_memory_replay(
        evaluator_artifact,
        now=now,
        requested_scope=requested_scope,
        review_resolver=review_resolver,
        conflict_ids=conflict_ids,
        stale_override=stale_override,
        run_id=run_id,
    )
    admission = artifact.get("admission")
    review_id = admission.get("review_id") if isinstance(admission, dict) else ""
    if (
        result.get("eligible") is True
        and artifact.get("schema_version") in {PROJECT_MEMORY_RECORD_SCHEMA_VERSION, MEMORY_SCOPE_SCHEMA_VERSION}
        and (not isinstance(review_id, str) or not review_id or not review_resolver or review_id not in review_resolver)
    ):
        # The core boundary supplies a resolver, so an approval without its
        # immutable review record cannot become eligible through an omitted id.
        result = {**result, "eligible": False, "reason_code": "review_not_found"}
    operation_id = artifact.get("operation_id")
    if result.get("eligible") is True and paths and isinstance(operation_id, str) and operation_id:
        operation, error = read_json_object_result(paths.memory_operations_dir / f"{operation_id}.json")
        if error or not isinstance(operation, dict) or operation.get("state") != "completed":
            result = {**result, "eligible": False, "reason_code": "operation_incomplete"}
    return _replay_evaluation(artifact, result)


def _normalize_evaluator_timestamps(artifact: dict[str, Any]) -> dict[str, Any]:
    """Present legacy-naive ISO deadlines to the shared evaluator as UTC."""
    normalized = dict(artifact)
    for field, timestamp_key in (("retention", "expires_at"), ("revalidation", "deadline")):
        metadata = artifact.get(field)
        if not isinstance(metadata, dict) or not metadata.get(timestamp_key):
            continue
        parsed = _parse_utc_naive_as_utc(str(metadata[timestamp_key]))
        if parsed is None:
            continue
        normalized[field] = {**metadata, timestamp_key: parsed.isoformat().replace("+00:00", "Z")}
    return normalized


def _parse_utc_naive_as_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _replay_evaluation(artifact: dict[str, Any], result: dict[str, object]) -> dict[str, object]:
    try:
        identity = stable_artifact_identity(artifact)
    except ValueError:
        identity = {}
    revalidation = artifact.get("revalidation")
    return {
        "schema_version": "omh_memory_replay_evaluation/v1",
        "artifact_identity": identity,
        "revision": int(artifact.get("revision", 0) or 0),
        "admission_mode": str(result.get("admission_mode") or ""),
        "source_class": str(artifact.get("source_class", "")),
        "retention_class": str(result.get("retention_class") or _retention_class(artifact)),
        "evaluated_at": str(result.get("evaluated_at", "")),
        "eligible": bool(result.get("eligible", False)),
        "reason_code": str(result.get("reason_code", "unknown")),
        "revalidation_evidence": {"deadline": str(revalidation.get("deadline", ""))} if isinstance(revalidation, dict) else {},
    }


def _retention_class(artifact: dict[str, Any]) -> str:
    retention = artifact.get("retention")
    return str(retention.get("class", "")) if isinstance(retention, dict) else ""


def _memory_recall_score(record: dict[str, Any], query: str) -> int:
    if not query.strip():
        return 1
    query_tokens = _memory_tokens(query)
    if not query_tokens:
        # The query carries no indexable tokens at all (emoji-only, an
        # unsupported script, or only sub-length words). Scoring it as zero
        # overlap used to exclude every record as no_query_overlap and hand
        # the executor an empty pack; fall back to unqueried recall so the
        # budget ladder still surfaces approved records.
        return 1
    record_tokens = _memory_tokens(
        " ".join(
            [
                str(record.get("summary", "")),
                str(record.get("record_type", "")),
                " ".join(_normalize_tags(record.get("tags", []))),
            ]
        )
    )
    overlap = query_tokens & record_tokens
    tag_overlap = query_tokens & set(_normalize_tags(record.get("tags", [])))
    return len(overlap) * 10 + len(tag_overlap) * 5


_MEMORY_ASCII_TOKEN = re.compile(r"[a-z0-9_/-]{3,}")
_MEMORY_CJK_RUN = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7a3]+")


def _memory_tokens(value: str) -> set[str]:
    """Index tokens for recall scoring, covering ASCII and CJK text.

    ASCII words keep the >=3 length floor. CJK runs are indexed as the whole
    run plus its character bigrams: Korean particles glue to the noun
    ("배포는"), so whole-word overlap alone would miss "배포" in a query.
    The previous ASCII-only split tokenized any CJK query to the empty set,
    which excluded every record as no_query_overlap and silently emptied
    recall packs for projects that chat in Korean, Japanese, or Chinese.
    """
    lowered = unicodedata.normalize("NFC", value).lower()
    tokens = set(_MEMORY_ASCII_TOKEN.findall(lowered))
    for run in _MEMORY_CJK_RUN.findall(lowered):
        if len(run) >= 2:
            tokens.add(run)
        tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def _record_scope_matches(record: dict[str, Any], *, scope_kind: str | None, scope_ref: str | None) -> bool:
    scope = _normalize_scope(record.get("scope", _scope("project", "default")))
    return (not scope_kind or scope["kind"] == scope_kind) and (not scope_ref or scope["ref"] == scope_ref)


def _record_staleness(record: dict[str, Any], *, now: datetime | None = None) -> dict[str, object]:
    """The one freshness verdict: TTL, review-due date, and source evidence.

    The TTL half is decided by the bundle classifier, the single source of
    truth for what "expired" means: it reads naive timestamps as UTC, where
    the local ``_parse_utc`` would read them as host-local time and move the
    verdict by up to +/-14 hours depending on where the host happens to be.

    The review-due half reads ``review_due_at`` and the older ``stale_after``
    spelling of the same date, taking whichever comes first, so records
    written before the field was named keep their deadline and a record with
    only one spelling edited cannot read as fresh.

    The source half compares the digest recorded at capture against the cited
    local file as it reads now. It only ever makes a record less trusted: a
    moved source is ``stale``, an unreadable one is ``unknown``, and neither
    can turn into ``fresh``. Every input is stored metadata plus the caller's
    ``now`` plus locally observable bytes, so the verdict is reproducible.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    ttl = record.get("ttl", {}) if isinstance(record.get("ttl"), dict) else {}
    staleness = record.get("staleness", {}) if isinstance(record.get("staleness"), dict) else {}
    expires_at = str(ttl.get("expires_at", ""))
    stale_after = str(staleness.get("stale_after", ""))
    review_due_at = _earliest_deadline(str(staleness.get("review_due_at", "") or ""), stale_after)
    source_state = _source_evidence_state(record)
    fields = {
        "stale_after": stale_after,
        "review_due_at": review_due_at,
        "expires_at": expires_at,
        "source_state": source_state,
    }
    if _classify_record_expiry(record, now=now) == "expired":
        return {"state": "expired", "reason": "retention_expired", **fields}
    deadline = _parse_utc(review_due_at)
    if deadline and deadline <= now:
        return {"state": "stale", "reason": "review_due", **fields}
    if source_state == "changed":
        return {"state": "stale", "reason": "source_changed", **fields}
    if source_state == "unreadable":
        return {"state": "unknown", "reason": "source_unreadable", **fields}
    return {"state": "fresh", "reason": "", **fields}


def _earliest_deadline(*values: str) -> str:
    """The soonest parseable deadline among equivalent spellings, fail-closed.

    ``review_due_at`` and ``stale_after`` are two names for one date, so they
    normally agree. When something edits only one of them they must not cancel
    each other out: whichever deadline has already passed decides, so a
    half-updated record reads as due for review rather than as fresh.
    """
    best_value = ""
    best_time: datetime | None = None
    for value in values:
        if not value:
            continue
        if not best_value:
            best_value = value
        parsed = _parse_utc(value)
        if parsed is not None and (best_time is None or parsed < best_time):
            best_time, best_value = parsed, value
    return best_value


def _source_evidence(source_ref: str, *, captured_at: str) -> dict[str, object]:
    """Digest a cited local source so a later change to it becomes observable.

    Only an absolute path to a readable local file earns evidence. A relative
    ref would resolve against whatever directory the caller happened to be in,
    which would make the same stored record read differently per invocation;
    a ref that is not a path at all (a PR number, a decision name) has nothing
    to digest. Both simply carry no evidence and stay on the deadline-only
    path, exactly as records did before.
    """
    digest = _local_source_digest(source_ref)
    return {"path": source_ref, "sha256": digest, "captured_at": captured_at} if digest else {}


def _source_evidence_projection(value: Any) -> dict[str, object]:
    """Scalar-only projection of recorded source evidence, or {}."""
    evidence = value.get("source_evidence") if isinstance(value, dict) else None
    if not isinstance(evidence, dict) or not str(evidence.get("sha256", "") or ""):
        return {}
    return {key: str(evidence.get(key, "") or "") for key in ("path", "sha256", "captured_at")}


def _local_source_digest(source_ref: str) -> str:
    """SHA-256 of a local file, or "" when it cannot be digested here."""
    if not source_ref:
        return ""
    try:
        path = Path(source_ref)
        if not path.is_absolute() or not path.is_file() or path.stat().st_size > _SOURCE_EVIDENCE_MAX_BYTES:
            return ""
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, ValueError):
        # Unreadable, gone, a directory, or a path this platform rejects. The
        # caller turns an empty digest into `unreadable`, never into `fresh`.
        return ""


def _source_evidence_state(record: dict[str, Any]) -> str:
    """"" (no evidence recorded) | unchanged | changed | unreadable."""
    evidence = record.get("source_evidence")
    if not isinstance(evidence, dict):
        return ""
    recorded = str(evidence.get("sha256", "") or "")
    if not recorded:
        return ""
    current = _local_source_digest(str(evidence.get("path", "") or ""))
    if not current:
        return "unreadable"
    return "unchanged" if current == recorded else "changed"


def _project_memory_safety(summary: str, content: str, *, tags: list[str]) -> dict[str, object]:
    classification = classify_memory_admission("\n".join([summary, content, " ".join(tags)]))
    status = str(classification.get("status", "blocked"))
    return {
        "schema_version": "project_memory_safety/v2",
        "status": status,
        "safe_to_auto_approve": status == "safe",
        "review_reasons": [] if status == "safe" else [status],
        "protected_inputs": ["credentials", "raw_logs", "full_transcripts", "temporary_task_progress"],
    }


def _looks_like_raw_log(value: str) -> bool:
    lowered = value.lower()
    markers = ("traceback (most recent call last)", "\nstderr", "\nstdout", "[error]", "exception:", "raw log", "full log")
    timestamp_lines = len(re.findall(r"^\d{4}-\d{2}-\d{2}[ t]\d{2}:\d{2}:\d{2}", value, flags=re.MULTILINE))
    return any(marker in lowered for marker in markers) or timestamp_lines >= 3


def _looks_like_full_transcript(value: str) -> bool:
    lowered = value.lower()
    speaker_lines = len(re.findall(r"^(user|assistant|system|developer|human|agent):", value, flags=re.IGNORECASE | re.MULTILINE))
    return "full transcript" in lowered or "chat transcript" in lowered or speaker_lines >= 4


def _ttl_metadata(ttl_days: int | None, *, record_type: str, created_at: str) -> dict[str, object]:
    default_days = 30 if record_type == "episode" and ttl_days is None else ttl_days
    return {
        "ttl_days": default_days,
        "expires_at": _days_after(created_at, default_days) if default_days else "",
    }


def _staleness_metadata(stale_after_days: int | None, *, record_type: str, created_at: str) -> dict[str, object]:
    default_days = 90 if record_type in {"fact", "decision", "lesson", "procedure"} and stale_after_days is None else stale_after_days
    deadline = _days_after(created_at, default_days) if default_days else ""
    # `review_due_at` is the readable name for the date `stale_after` always
    # held. Both are written so older readers keep working; nothing derives a
    # second deadline from the new spelling.
    return {
        "stale_after_days": default_days,
        "stale_after": deadline,
        "review_due_at": deadline,
    }


def _days_after(created_at: str, days: int | None) -> str:
    if not days:
        return ""
    base = _parse_utc(created_at) or datetime.now(timezone.utc)
    return (base + timedelta(days=int(days))).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _normalize_memory_mode(value: str | None) -> str:
    mode = str(value or "review-first").strip()
    if mode not in PROJECT_MEMORY_MODES:
        raise ValueError(f"unsupported memory mode: {mode}; expected one of {', '.join(PROJECT_MEMORY_MODES)}")
    return mode


def _normalize_record_type(value: str) -> str:
    record_type = str(value or "fact").strip()
    if record_type not in PROJECT_MEMORY_RECORD_TYPES:
        raise ValueError(f"unsupported memory record type: {record_type}; expected one of {', '.join(PROJECT_MEMORY_RECORD_TYPES)}")
    return record_type


def _scope_for_project_memory(kind: str, ref: str) -> dict[str, str]:
    scope = _scope(str(kind or "project"), str(ref or "default"))
    if scope["kind"] not in ALLOWED_SCOPE_KINDS:
        raise ValueError(f"unsupported memory scope kind: {scope['kind']}")
    if not _SAFE_REF.match(scope["ref"]):
        raise ValueError(f"unsafe memory scope ref: {scope['ref']!r}")
    return scope


def _normalize_tags(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = unicodedata.normalize("NFC", str(value)).strip().lower()
        if not tag or not _SAFE_TAG.match(tag):
            continue
        if tag not in seen:
            tags.append(tag)
            seen.add(tag)
    return tags[:12]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _read_project_memory_candidate(paths: OmhPaths, candidate_id: str) -> dict[str, Any] | None:
    if not _SAFE_REF.match(candidate_id):
        raise ValueError(f"unsafe memory candidate id: {candidate_id!r}")
    return read_json_object(_memory_candidate_path(paths, candidate_id))


def _read_project_memory_candidates(paths: OmhPaths) -> list[dict[str, Any]]:
    return _read_memory_json_files(paths, _memory_candidates_dir(paths))


def _read_project_memory_records(paths: OmhPaths) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for record in _read_memory_json_files(paths, _memory_records_dir(paths)):
        schema_version = record.get("schema_version")
        if schema_version == PROJECT_MEMORY_RECORD_SCHEMA_VERSION:
            records.append(record)
        elif schema_version == LEGACY_PROJECT_MEMORY_RECORD_SCHEMA_VERSION and record.get("review_status") == "approved":
            # Legacy records stay review/status visible, but the evaluator will
            # fail them closed as review_required_legacy before any replay.
            records.append(record)
    return records


def _read_project_memory_reviews(paths: OmhPaths) -> list[dict[str, Any]]:
    return _read_memory_json_files(paths, _memory_reviews_dir(paths))


def _read_memory_json_files(paths: OmhPaths, directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        _assert_under_memory_root(paths, path)
        # A corrupt store file must cost only itself, not the whole read: a
        # crash mid-write or disk fault used to make every recall, review,
        # and status call raise on the first unreadable file until someone
        # hand-deleted it. Retirement already scans this way.
        data, _error = read_json_object_result(path)
        if isinstance(data, dict):
            items.append(data)
    return items


def _write_project_memory_candidate_unlocked(paths: OmhPaths, candidate: dict[str, object]) -> None:
    """Candidate write with NO index rewrite: for callers already holding the store lock."""
    path = _memory_candidate_path(paths, str(candidate.get("candidate_id", "")))
    atomic_write_json(path, candidate, private=True)


def _write_project_memory_candidate(paths: OmhPaths, candidate: dict[str, object]) -> None:
    _write_project_memory_candidate_unlocked(paths, candidate)
    _write_memory_index(paths)


def _write_project_memory_record(paths: OmhPaths, record: dict[str, object]) -> None:
    errors = validate_project_memory_record(record)
    if errors:
        raise ValueError("; ".join(errors))
    atomic_write_json(_memory_record_path(paths, str(record.get("record_id", ""))), record, private=True)


def validate_project_memory_record(value: Any, *, label: str = "project_memory_record") -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    _validate_allowed_keys(value, _PROJECT_MEMORY_RECORD_KEYS, errors, label)
    if value.get("schema_version") != PROJECT_MEMORY_RECORD_SCHEMA_VERSION:
        errors.append(f"{label}.schema_version must be {PROJECT_MEMORY_RECORD_SCHEMA_VERSION}")
    if not isinstance(value.get("revision"), int) or int(value.get("revision", 0)) <= 0:
        errors.append(f"{label}.revision must be a positive integer")
    admission = value.get("admission")
    if not isinstance(admission, dict) or admission.get("state") not in {"approved_manual", "approved_auto_safe"}:
        errors.append(f"{label}.admission must carry an approved v2 decision")
    if not isinstance(value.get("retention"), dict):
        errors.append(f"{label}.retention must be an object")
    _validate_context_scope(value.get("scope"), errors, f"{label}.scope")
    if "perspective" in value:
        _validate_perspective(value.get("perspective"), errors, f"{label}.perspective", require_observed=True)
    if value.get("redaction_policy") != "metadata_only":
        errors.append(f"{label}.redaction_policy must be metadata_only")
    if _contains_sensitive_text(value):
        errors.append(f"{label} contains sensitive-looking text")
    return errors


def _memory_candidates_dir(paths: OmhPaths) -> Path:
    return paths.memory_dir / "candidates"


def _memory_records_dir(paths: OmhPaths) -> Path:
    return paths.memory_dir / "records"


def _memory_reviews_dir(paths: OmhPaths) -> Path:
    return paths.memory_dir / "reviews"


def _memory_candidate_path(paths: OmhPaths, candidate_id: str) -> Path:
    if not _SAFE_REF.match(candidate_id):
        raise ValueError(f"unsafe memory candidate id: {candidate_id!r}")
    path = _memory_candidates_dir(paths) / f"{candidate_id}.json"
    _assert_under_memory_root(paths, path)
    return path


def _memory_record_path(paths: OmhPaths, record_id: str) -> Path:
    if not _SAFE_REF.match(record_id):
        raise ValueError(f"unsafe memory record id: {record_id!r}")
    path = _memory_records_dir(paths) / f"{record_id}.json"
    _assert_under_memory_root(paths, path)
    return path


def _memory_review_path(paths: OmhPaths, review_id: str) -> Path:
    if not _SAFE_REF.match(review_id):
        raise ValueError(f"unsafe memory review id: {review_id!r}")
    path = _memory_reviews_dir(paths) / f"{review_id}.json"
    _assert_under_memory_root(paths, path)
    return path


def _validate_context_map(value: Any, allowed: set[str], errors: list[str], label: str) -> None:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return
    _validate_allowed_keys(value, allowed, errors, label)
    for key, nested in value.items():
        if isinstance(nested, (str, int, bool)) or nested is None:
            continue
        errors.append(f"{label}.{key} must be scalar metadata")


def _validate_replay_evaluation(value: dict[str, Any], errors: list[str], label: str) -> None:
    allowed = {
        "schema_version",
        "artifact_identity",
        "revision",
        "admission_mode",
        "source_class",
        "retention_class",
        "evaluated_at",
        "eligible",
        "reason_code",
        "revalidation_evidence",
    }
    _validate_allowed_keys(value, allowed, errors, label)
    if value.get("schema_version") != "omh_memory_replay_evaluation/v1":
        errors.append(f"{label}.schema_version must be omh_memory_replay_evaluation/v1")
    for key in ("revision",):
        if not isinstance(value.get(key), int):
            errors.append(f"{label}.{key} must be an integer")
    for key in ("admission_mode", "source_class", "retention_class", "evaluated_at", "reason_code"):
        if not isinstance(value.get(key), str):
            errors.append(f"{label}.{key} must be a string")
    if not isinstance(value.get("eligible"), bool):
        errors.append(f"{label}.eligible must be a boolean")
    if not isinstance(value.get("artifact_identity"), dict):
        errors.append(f"{label}.artifact_identity must be an object")
    if not isinstance(value.get("revalidation_evidence"), dict):
        errors.append(f"{label}.revalidation_evidence must be an object")
    forbidden = {"summary", "value", "label", "content", "text", "prompt", "body"}
    found = forbidden & set(value)
    if found:
        errors.append(f"{label} contains content fields: {sorted(found)}")


def _jsonish(value: Any) -> str:
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _local_snapshots(
    paths: OmhPaths,
    *,
    scope_kind: str | None = None,
    scope_ref: str | None = None,
    session_limit: int | None = None,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    snapshots: list[dict[str, object]] = []
    setup = read_setup_profile(paths)
    if setup:
        snapshots.append(_setup_snapshot(setup))
    topology = summarize_target_registry(paths)
    if topology.get("status") == "available":
        snapshots.append(_target_snapshot(topology))
    runtime_state, runtime_error = read_json_object_result(paths.runtime_state_path)
    if runtime_state:
        snapshots.append(_runtime_state_snapshot(runtime_state))
    elif runtime_error:
        snapshots.append(_snapshot("runtime_state", _scope("project", "default"), [{"item_id": "runtime-state-error", "key": "runtime_state", "summary": runtime_error}]))
    memory_snapshots = _memory_snapshots(paths, now=now)
    snapshots.extend(memory_snapshots)
    snapshots.extend(_wrapper_session_snapshots(paths, limit=session_limit))
    snapshots.append(_catalog_hint_snapshot())
    return _filter_snapshots_by_scope(snapshots, scope_kind=scope_kind, scope_ref=scope_ref)


def _setup_snapshot(setup: dict[str, Any]) -> dict[str, object]:
    return _snapshot(
        "setup_profile",
        _scope("project", "default"),
        [
            {
                "item_id": "setup-default-executor",
                "key": "default_executor",
                "value": str(setup.get("default_executor", "")),
                "summary": f"default executor: {setup.get('default_executor', '')}",
            },
            {
                "item_id": "setup-dispatch-policy",
                "key": "dispatch_policy",
                "value": str(setup.get("dispatch_policy", "")),
                "summary": f"dispatch policy: {setup.get('dispatch_policy', '')}",
            },
            {
                "item_id": "setup-operating-model",
                "key": "operating_model_id",
                "value": str(setup.get("operating_model_id", "")),
                "summary": f"operating model: {setup.get('operating_model_id', '')}",
            },
        ],
    )


def _target_snapshot(topology: dict[str, Any]) -> dict[str, object]:
    return _snapshot(
        "target_topology",
        _scope("target", str(topology.get("current_target_id") or "default")),
        [
            {
                "item_id": "target-mode",
                "key": "target_mode",
                "value": str(topology.get("mode", "")),
                "summary": f"target mode: {topology.get('mode', '')}; active agents: {topology.get('active_agent_count', 0)}",
            },
            {
                "item_id": "target-active-agent-count",
                "key": "active_agent_count",
                "value": str(topology.get("active_agent_count", 0)),
                "summary": f"active Hermes agents: {topology.get('active_agent_count', 0)}",
            },
        ],
    )


def _runtime_state_snapshot(state: dict[str, Any]) -> dict[str, object]:
    items: list[dict[str, object]] = []
    last_run = str(state.get("last_run_id", ""))
    if last_run:
        items.append({"item_id": "runtime-last-run", "key": "last_run_id", "value": last_run, "summary": f"last runtime run: {last_run}"})
    last_setup = state.get("last_setup")
    if isinstance(last_setup, dict):
        items.append({"item_id": "runtime-last-setup", "key": "last_setup", "summary": f"last setup ok: {bool(last_setup.get('ok', False))}"})
    return _snapshot("runtime_state", _scope("project", "default"), items)


def _memory_snapshots(paths: OmhPaths, *, now: datetime | None = None) -> list[dict[str, object]]:
    """Return review-visible OMH items with evaluator evidence before packing.

    Ineligible artifacts deliberately remain inspectable here, but no value or
    summary can reach ``build_handoff_context_pack`` without a second final
    evaluator decision.
    """
    snapshots: list[dict[str, object]] = []
    review_resolver = _project_memory_review_resolver(paths)
    reviewed_items: list[dict[str, object]] = []
    for record in _read_project_memory_records(paths):
        reviewed_items.append(
            {
                "item_id": str(record.get("record_id", "")),
                "key": str(record.get("record_type", "memory")),
                "summary": _safe_summary(record),
                "scope": record.get("scope", _scope("project", "default")),
                "replay_evaluation": _evaluate_memory_artifact(record, paths=paths, now=now, review_resolver=review_resolver),
            }
        )
    if reviewed_items:
        snapshots.append(_snapshot("omh_memory", _scope("project", "default"), reviewed_items))
    for path in _memory_scope_paths(paths):
        data = read_json_object(path)
        if not isinstance(data, dict):
            continue
        items: list[dict[str, object]] = []
        for item_id, item in (data.get("items", {}) if isinstance(data.get("items"), dict) else {}).items():
            if isinstance(item, dict):
                artifact = _scope_item_artifact(data, item, item_id)
                items.append(
                    {
                        "item_id": str(item_id),
                        "key": str(item.get("key", item_id)),
                        "value": str(item.get("value", "")),
                        "summary": _safe_summary(item),
                        "scope": data.get("scope", _scope("project", "default")),
                        "replay_evaluation": _evaluate_memory_artifact(artifact, paths=paths, now=now, review_resolver=review_resolver),
                    }
                )
        if items:
            snapshots.append(_snapshot("omh_memory", data.get("scope", _scope("project", "default")), items))
    return snapshots


def _scope_item_artifact(data: dict[str, Any], item: dict[str, Any], item_id: Any) -> dict[str, Any]:
    """Preserve legacy scope artifacts so the shared evaluator can classify them."""
    schema_version = item.get("schema_version", data.get("schema_version", LEGACY_MEMORY_SCOPE_SCHEMA_VERSION))
    artifact = {
        **item,
        "schema_version": schema_version,
        "item_id": str(item_id),
        "scope": _normalize_scope(data.get("scope", _scope("project", "default"))),
        "source_class": str(item.get("source_class", "omh_local")),
    }
    if schema_version == MEMORY_SCOPE_SCHEMA_VERSION:
        artifact["revision"] = int(item.get("revision", 1) or 1)
    return artifact


def _memory_artifact_for_snapshot_item(paths: OmhPaths, item: dict[str, Any]) -> dict[str, Any]:
    item_id = str(item.get("item_id", ""))
    for record in _read_project_memory_records(paths):
        if str(record.get("record_id", "")) == item_id:
            return record
    for path in _memory_scope_paths(paths):
        data = read_json_object(path)
        items = data.get("items") if isinstance(data, dict) else None
        scope_item = items.get(item_id) if isinstance(items, dict) else None
        if isinstance(data, dict) and isinstance(scope_item, dict):
            return _scope_item_artifact(data, scope_item, item_id)
    return {"schema_version": "unknown", "record_id": item_id}


def _wrapper_session_snapshots(paths: OmhPaths, *, limit: int | None = None) -> list[dict[str, object]]:
    if not paths.runtime_wrapper_sessions_dir.exists():
        return []
    snapshots: list[dict[str, object]] = []
    session_paths = sorted(paths.runtime_wrapper_sessions_dir.glob("*/session.json"))
    if limit is not None and limit > 0:
        session_paths = session_paths[-limit:]
    for session_json in session_paths:
        session = read_json_object(session_json)
        if not isinstance(session, dict):
            continue
        session_id = str(session.get("session_id", session_json.parent.name))
        items = [
            {
                "item_id": f"wrapper-session-{session_id}",
                "key": "wrapper_session_status",
                "value": str(session.get("status", "")),
                "summary": f"wrapper session {session_id}: {session.get('status', '')}",
            }
        ]
        selected_executor = str(session.get("selected_executor_profile") or "")
        if selected_executor:
            items.append(
                {
                    "item_id": f"wrapper-session-{session_id}-executor",
                    "key": "default_executor",
                    "value": selected_executor,
                    "summary": f"session executor: {selected_executor}",
                }
            )
        snapshots.append(_snapshot("wrapper_session", _scope("thread", _stable_ref(session.get("thread_key", session_id))), items))
    return snapshots


def _filter_snapshots_by_scope(
    snapshots: list[dict[str, object]],
    *,
    scope_kind: str | None,
    scope_ref: str | None,
) -> list[dict[str, object]]:
    if not scope_kind and not scope_ref:
        return snapshots
    filtered: list[dict[str, object]] = []
    for snapshot in snapshots:
        scope = _normalize_scope(snapshot.get("scope", _scope("project", "default")))
        kind_matches = not scope_kind or scope["kind"] == scope_kind
        ref_matches = not scope_ref or scope["ref"] == scope_ref
        if kind_matches and ref_matches:
            filtered.append(snapshot)
    return filtered


def _limited_items(items: list[dict[str, object]], limit: int | None) -> list[dict[str, object]]:
    if limit is None:
        return items
    if limit < 1:
        return []
    return items[:limit]


def _snapshot_summary(snapshots: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "source": str(snapshot.get("source", "")),
            "truth_level": str(snapshot.get("truth_level", "")),
            "precedence": int(snapshot.get("precedence", 0) or 0),
            "scope": snapshot.get("scope", _scope("project", "default")),
            "item_count": len(snapshot.get("items", [])) if isinstance(snapshot.get("items"), list) else 0,
        }
        for snapshot in snapshots
    ]


def _catalog_hint_snapshot() -> dict[str, object]:
    return _snapshot(
        "catalog_hint",
        _scope("project", "default"),
        [
            {
                "item_id": "catalog-memory-boundary",
                "key": "memory_boundary",
                "summary": "OMH can inspect local state and wrapper snapshots; opaque Hermes memory requires explicit source evidence.",
            }
        ],
    )


def _normalize_wrapper_snapshot(snapshot: dict[str, Any]) -> dict[str, object]:
    if snapshot.get("schema_version") != MEMORY_SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("wrapper memory snapshot schema_version must be memory_snapshot/v1")
    source = "wrapper_snapshot"
    scope = _normalize_scope(snapshot.get("scope", _scope("project", "default")))
    items = [_sanitize_item(item, default_scope=scope) for item in snapshot.get("items", []) if isinstance(item, dict)]
    return _snapshot(source, scope, items, claim_boundary=str(snapshot.get("claim_boundary", "Wrapper supplied memory candidates are not trusted until reviewed.")))


def _snapshot(source: str, scope: Any, items: list[dict[str, object]], *, claim_boundary: str = "") -> dict[str, object]:
    normalized_scope = _normalize_scope(scope)
    return {
        "schema_version": MEMORY_SNAPSHOT_SCHEMA_VERSION,
        "source": source,
        "truth_level": SOURCE_TRUTH_LEVELS[source],
        "precedence": SOURCE_PRECEDENCE[source],
        "scope": normalized_scope,
        "items": [_sanitize_item(item, default_scope=normalized_scope) for item in items],
        "observed_at": utc_now(),
        "redaction_policy": "metadata_only",
        "claim_boundary": claim_boundary or _claim_boundary_for_source(source),
    }


def _sanitize_item(item: dict[str, Any], *, default_scope: dict[str, str]) -> dict[str, object]:
    item_id = str(item.get("item_id") or _stable_ref(item.get("key", "item")))
    key = str(item.get("key", item_id))
    summary = _safe_summary(item)
    sanitized: dict[str, object] = {
        "item_id": item_id,
        "key": key,
        "summary": summary,
        "scope": _normalize_scope(item.get("scope", default_scope)),
        "sensitive": bool(item.get("sensitive", False)),
    }
    value = item.get("value")
    if _safe_to_expose_value(key, value, item):
        sanitized["value"] = str(value)
    replay_evaluation = item.get("replay_evaluation")
    if isinstance(replay_evaluation, dict):
        sanitized["replay_evaluation"] = replay_evaluation
    return sanitized


def _safe_summary(item: dict[str, Any]) -> str:
    summary = str(item.get("summary", ""))
    if summary:
        return _redact(summary)
    key = str(item.get("key", item.get("item_id", "item")))
    value = str(item.get("value", ""))
    if key in _PROMPTISH_KEYS or item.get("sensitive"):
        return f"{key}: redacted"
    return _redact(f"{key}: {value}")[:240]


def _safe_to_expose_value(key: str, value: Any, item: dict[str, Any]) -> bool:
    if value is None or item.get("sensitive"):
        return False
    text = str(value)
    if key in _PROMPTISH_KEYS:
        return False
    if _looks_sensitive(text):
        return False
    return len(text) <= 240


def _redact(value: str) -> str:
    if _looks_sensitive(value):
        return "[redacted]"
    return value[:240]


def _looks_sensitive(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in ("secret", "token", "password", "private-key", "api_key", "apikey"))


def _validate_allowed_keys(value: dict[str, Any], allowed: set[str], errors: list[str], label: str) -> None:
    extra_keys = sorted(set(value) - allowed)
    if extra_keys:
        errors.append(f"{label} has unsupported keys: {extra_keys}")


def _validate_context_scope(value: Any, errors: list[str], label: str) -> None:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return
    _validate_allowed_keys(value, _HANDOFF_CONTEXT_SCOPE_KEYS, errors, label)
    kind = value.get("kind")
    ref = value.get("ref")
    if not isinstance(kind, str) or not kind:
        errors.append(f"{label}.kind must be a non-empty string")
    if not isinstance(ref, str) or not ref:
        errors.append(f"{label}.ref must be a non-empty string")


def _validate_context_list(
    value: Any,
    allowed: set[str],
    errors: list[str],
    label: str,
    *,
    scope_key: str | None = None,
) -> None:
    if not isinstance(value, list):
        errors.append(f"{label} must be a list")
        return
    for index, item in enumerate(value):
        item_label = f"{label}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_label} must be an object")
            continue
        _validate_allowed_keys(item, allowed, errors, item_label)
        for key, nested in item.items():
            nested_label = f"{item_label}.{key}"
            if scope_key and key == scope_key:
                _validate_context_scope(nested, errors, nested_label)
            elif key == "tags" and isinstance(nested, list):
                if any(not isinstance(tag, str) for tag in nested):
                    errors.append(f"{nested_label} must contain string tags")
            elif key == "derived_from" and isinstance(nested, list):
                if any(not isinstance(ref, str) for ref in nested):
                    errors.append(f"{nested_label} must contain string record ids")
            elif key == "ranking" and isinstance(nested, dict):
                _validate_context_map(nested, _RECALL_RANKING_KEYS, errors, nested_label)
            elif key == "perspective" and isinstance(nested, dict):
                _validate_perspective(nested, errors, nested_label)
            elif key == "staleness" and isinstance(nested, dict):
                _validate_context_map(nested, set(nested), errors, nested_label)
            elif key == "replay_evaluation" and isinstance(nested, dict):
                _validate_replay_evaluation(nested, errors, nested_label)
            elif key == "revalidation_evidence" and isinstance(nested, dict):
                _validate_context_map(nested, {"deadline"}, errors, nested_label)
            elif isinstance(nested, (str, int, bool)) or nested is None:
                continue
            else:
                errors.append(f"{nested_label} must be scalar metadata")


def _contains_sensitive_text(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_sensitive_text(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_sensitive_text(item) for item in value)
    if isinstance(value, str):
        return _looks_sensitive(value)
    return False


def _detect_conflicts(snapshots: list[dict[str, object]]) -> list[dict[str, object]]:
    conflicts: list[dict[str, object]] = []
    values = _values_by_key(snapshots)
    conflicts.extend(_pairwise_conflict(values, "default_executor", preferred_source="setup_profile"))
    conflicts.extend(_pairwise_conflict(values, "target_mode", preferred_source="target_topology"))
    if any(value["key"] == "verification_status" and str(value.get("value", "")).lower() in {"verified", "passed"} for value in values):
        has_runtime_verification = any(value["source"] == "runtime_evidence" and value["key"] in {"verification_status", "verification_observed"} for value in values)
        if not has_runtime_verification:
            conflicts.append(
                {
                    "item_id": "verification-status-conflict",
                    "key": "verification_status",
                    "severity": "blocker",
                    "preferred_source": "runtime_evidence",
                    "reason": "Remembered verification cannot be used as runtime evidence without a run-ledger verification record.",
                    "claim_boundary": "Remembered verification is not observed verification evidence.",
                }
            )
    return conflicts


def _pairwise_conflict(values: list[dict[str, Any]], key: str, *, preferred_source: str) -> list[dict[str, object]]:
    keyed = [value for value in values if value["key"] == key and value.get("value") not in {None, ""}]
    preferred = [value for value in keyed if value["source"] == preferred_source]
    if not preferred:
        return []
    preferred_value = str(preferred[0].get("value", ""))
    conflicts = []
    for value in keyed:
        if value["source"] == preferred_source:
            continue
        if str(value.get("value", "")) and str(value.get("value", "")) != preferred_value:
            conflicts.append(
                {
                    "item_id": str(value.get("item_id", "")),
                    "key": key,
                    "severity": "blocker",
                    "current_value": str(value.get("value", "")),
                    "preferred_value": preferred_value,
                    "current_source": value["source"],
                    "preferred_source": preferred_source,
                    "reason": f"{key} from {value['source']} conflicts with {preferred_source}.",
                    "claim_boundary": "Conflicting memory-like context must be reviewed before it is reused in a handoff.",
                }
            )
    return conflicts


def _values_by_key(snapshots: list[dict[str, object]]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for snapshot in snapshots:
        source = str(snapshot.get("source", ""))
        for item in snapshot.get("items", []) if isinstance(snapshot.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            values.append({**item, "source": source, "precedence": snapshot.get("precedence", 0)})
    return values


def _review_items(snapshots: list[dict[str, object]], conflicts: list[dict[str, object]]) -> list[dict[str, object]]:
    conflict_ids = {str(conflict.get("item_id", "")) for conflict in conflicts}
    synthetic_conflict_keys = {
        str(conflict.get("key", ""))
        for conflict in conflicts
        if str(conflict.get("item_id", "")).endswith("-conflict") and str(conflict.get("key", ""))
    }
    items: list[dict[str, object]] = []
    for snapshot in snapshots:
        for item in snapshot.get("items", []) if isinstance(snapshot.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("item_id", ""))
            blocked = item_id in conflict_ids or str(item.get("key", "")) in synthetic_conflict_keys
            items.append(
                {
                    "item_id": item_id,
                    "source": snapshot.get("source", ""),
                    "truth_level": snapshot.get("truth_level", ""),
                    "key": item.get("key", ""),
                    "summary": item.get("summary", ""),
                    "scope": item.get("scope", snapshot.get("scope", _scope("project", "default"))),
                    "suggested_action": "update_memory" if blocked else "keep_memory",
                    "blocked": blocked,
                }
            )
    return items


def _recommended_actions(conflicts: list[dict[str, object]]) -> list[str]:
    if conflicts:
        return ["update_memory", "change_memory_scope", "dismiss_conflict", "apply_memory_updates"]
    return ["keep_memory", "show_memory_status"]


def _handoff_preview(snapshots: list[dict[str, object]], conflicts: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": HANDOFF_CONTEXT_PACK_SCHEMA_VERSION,
        "included_candidate_count": sum(len(snapshot.get("items", [])) for snapshot in snapshots if isinstance(snapshot.get("items"), list)),
        "blocked_by_conflict_count": len(conflicts),
        "claim_boundary": "Preview only; use handoff_context_pack/v1 before embedding context in a handoff.",
    }


def _prepare_update(paths: OmhPaths, update: Any, touched: dict[Path, dict[str, Any]]) -> dict[str, object]:
    if not isinstance(update, dict):
        raise ValueError("memory update must be an object")
    op = str(update.get("op", ""))
    if op not in ALLOWED_UPDATE_OPS:
        raise ValueError(f"unsupported memory update op: {op}")
    item_id = str(update.get("item_id", ""))
    if not _SAFE_REF.match(item_id):
        raise ValueError(f"unsafe memory item id: {item_id!r}")
    scope = _scope_for_update(update, "scope")
    path = _scope_path(paths, scope)
    data = touched.setdefault(path, _read_scope_file(path, scope))
    status = "prepared"
    if op in {"keep", "update", "dismiss_conflict"}:
        status = _upsert_item(data, item_id, update, op=op)
    elif op == "forget":
        status = _forget_item(data, item_id, update)
    elif op == "change_scope":
        from_scope = _scope_for_update(update, "from_scope")
        to_scope = _scope_for_update(update, "to_scope")
        from_path = _scope_path(paths, from_scope)
        to_path = _scope_path(paths, to_scope)
        from_data = touched.setdefault(from_path, _read_scope_file(from_path, from_scope))
        to_data = touched.setdefault(to_path, _read_scope_file(to_path, to_scope))
        status = _move_item(from_data, to_data, item_id, update)
        path = to_path
    return {"item_id": item_id, "op": op, "scope": scope, "status": status, "path": str(path)}


def _upsert_item(data: dict[str, Any], item_id: str, update: dict[str, Any], *, op: str) -> str:
    items = data.setdefault("items", {})
    existing = items.get(item_id)
    value = str(update.get("value", existing.get("value", "") if isinstance(existing, dict) else ""))
    key = str(update.get("key", item_id))
    item = {
        "item_id": item_id,
        "key": key,
        "summary": _safe_summary(update),
        "reason": str(update.get("reason", "")),
        "operation": op,
        "updated_at": utc_now(),
    }
    if _safe_to_expose_value(key, value, update):
        item["value"] = value
    if op == "keep":
        item["confirmed_at"] = item["updated_at"]
    if op == "dismiss_conflict":
        item["dismissed_at"] = item["updated_at"]
    if isinstance(existing, dict) and existing.get("value", "") == item.get("value", "") and existing.get("summary") == item["summary"]:
        items[item_id] = {**existing, **item}
        return "noop"
    items[item_id] = item
    return "prepared"


def _forget_item(data: dict[str, Any], item_id: str, update: dict[str, Any]) -> str:
    items = data.setdefault("items", {})
    tombstones = data.setdefault("tombstones", {})
    existed = item_id in items
    if existed:
        items.pop(item_id)
    tombstones[item_id] = {
        "item_id": item_id,
        "reason": str(update.get("reason", "")),
        "tombstoned_at": utc_now(),
    }
    return "prepared" if existed else "noop"


def _move_item(from_data: dict[str, Any], to_data: dict[str, Any], item_id: str, update: dict[str, Any]) -> str:
    from_items = from_data.setdefault("items", {})
    to_items = to_data.setdefault("items", {})
    item = from_items.pop(item_id, None)
    if not isinstance(item, dict):
        value = str(update.get("value", ""))
        key = str(update.get("key", item_id))
        item = {
            "item_id": item_id,
            "key": key,
            "summary": _safe_summary(update),
        }
        if _safe_to_expose_value(key, value, update):
            item["value"] = value
    if to_items.get(item_id) == item:
        return "noop"
    to_items[item_id] = {**item, "moved_at": utc_now(), "reason": str(update.get("reason", ""))}
    return "prepared"


def _scope_for_update(update: dict[str, Any], key: str) -> dict[str, str]:
    scope = _normalize_scope(update.get(key, update.get("scope", _scope("project", "default"))))
    if scope["kind"] not in ALLOWED_SCOPE_KINDS:
        raise ValueError(f"unsupported memory scope kind: {scope['kind']}")
    if not _SAFE_REF.match(scope["ref"]):
        raise ValueError(f"unsafe memory scope ref: {scope['ref']!r}")
    return scope


def _read_scope_file(path: Path, scope: dict[str, str]) -> dict[str, Any]:
    data = read_json_object(path)
    if isinstance(data, dict):
        return data
    return {
        "schema_version": MEMORY_SCOPE_SCHEMA_VERSION,
        "scope": scope,
        "items": {},
        "tombstones": {},
        "updated_at": utc_now(),
    }


def _write_memory_index(paths: OmhPaths) -> None:
    ensure_dir(paths.memory_dir, private=True)
    with file_lock(paths.memory_index_path, private=True):
        _write_memory_index_unlocked(paths)


def _write_memory_index_unlocked(paths: OmhPaths) -> None:
    """Index rewrite for callers already inside the store lock.

    ``file_lock`` flocks a fresh handle, so it is not reentrant: the retirement
    and approval transactions that already hold the lock must come through
    here, or they wait out the full timeout against themselves.
    """
    ensure_dir(paths.memory_dir, private=True)
    scopes = [path.relative_to(paths.memory_dir).as_posix() for path in _memory_scope_paths(paths)]
    candidates = [path.relative_to(paths.memory_dir).as_posix() for path in _safe_memory_files(paths, _memory_candidates_dir(paths))]
    records = [path.relative_to(paths.memory_dir).as_posix() for path in _safe_memory_files(paths, _memory_records_dir(paths))]
    reviews = [path.relative_to(paths.memory_dir).as_posix() for path in _safe_memory_files(paths, _memory_reviews_dir(paths))]
    atomic_write_json(
        paths.memory_index_path,
        {
            "schema_version": MEMORY_INDEX_SCHEMA_VERSION,
            "updated_at": utc_now(),
            "scope_files": sorted(scopes),
            "candidate_files": sorted(candidates),
            "record_files": sorted(records),
            "review_files": sorted(reviews),
            "claim_boundary": "OMH local memory only; this index is not Hermes internal memory.",
        },
        private=True,
    )


def _safe_memory_files(paths: OmhPaths, directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    safe_paths: list[Path] = []
    for path in directory.glob("*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        _assert_under_memory_root(paths, path)
        safe_paths.append(path)
    return sorted(safe_paths)


def _memory_scope_paths(paths: OmhPaths) -> list[Path]:
    scopes_dir = paths.memory_dir / "scopes"
    if not scopes_dir.exists():
        return []
    safe_paths: list[Path] = []
    for path in scopes_dir.rglob("*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        _assert_under_memory_root(paths, path)
        safe_paths.append(path)
    return sorted(safe_paths)


def _scope_path(paths: OmhPaths, scope: dict[str, str]) -> Path:
    kind = scope["kind"]
    ref = scope["ref"]
    if kind == "project":
        relative = Path("scopes/project.json")
    else:
        relative = Path("scopes") / f"{kind}s" / f"{ref}.json"
    path = paths.memory_dir / relative
    _assert_under_memory_root(paths, path)
    return path


def _assert_under_memory_root(paths: OmhPaths, path: Path) -> None:
    root = _memory_root(paths)
    candidate = path.resolve(strict=False)
    if root != candidate and root not in candidate.parents:
        raise ValueError(f"memory write path escapes .omh/memory: {path}")


def _memory_root(paths: OmhPaths) -> Path:
    return paths.memory_dir.resolve(strict=False)


def _normalize_scope(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        kind = str(value.get("kind", "project") or "project")
        ref = str(value.get("ref", "default") or "default")
        return _scope(kind, ref)
    if isinstance(value, str) and value:
        return _scope("project", value)
    return _scope("project", "default")


def _scope(kind: str, ref: str) -> dict[str, str]:
    return {"kind": kind, "ref": ref}


def _source_refs(inspection: dict[str, Any]) -> list[dict[str, object]]:
    refs = []
    for snapshot in inspection.get("snapshots", []) if isinstance(inspection.get("snapshots"), list) else []:
        if isinstance(snapshot, dict):
            refs.append(
                {
                    "source": str(snapshot.get("source", "")),
                    "truth_level": str(snapshot.get("truth_level", "")),
                    "precedence": int(snapshot.get("precedence", 0) or 0),
                    "item_count": len(snapshot.get("items", [])) if isinstance(snapshot.get("items"), list) else 0,
                }
            )
    return refs


def _item_conflicts(item: dict[str, Any], conflicts: list[dict[str, object]]) -> bool:
    item_id = str(item.get("item_id", ""))
    key = str(item.get("key", ""))
    return any(conflict.get("item_id") == item_id or conflict.get("key") == key for conflict in conflicts)


def _is_packable(item: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    source = str(snapshot.get("source", ""))
    if source == "wrapper_snapshot":
        return False
    key = str(item.get("key", ""))
    return key not in {"verification_status"} and bool(item.get("summary"))


def _memory_action(action_id: str) -> dict[str, object]:
    labels = {
        "keep_memory": "Keep",
        "forget_memory": "Forget",
        "update_memory": "Update",
        "change_memory_scope": "Change scope",
        "apply_memory_updates": "Apply updates",
        "show_memory_status": "Show memory status",
        "cancel": "Cancel",
    }
    return {"id": action_id, "label": labels[action_id], "enabled": True}


def _claim_boundary_for_source(source: str) -> str:
    return {
        "runtime_evidence": "Runtime ledger evidence is the source of execution/review/CI/merge claims.",
        "runtime_state": "Runtime state is an index of local OMH activity, not execution/review/CI/merge evidence.",
        "wrapper_session": "Wrapper sessions own chat continuity and plan decisions only.",
        "target_topology": "Target topology is setup evidence only.",
        "setup_profile": "Setup profile records defaults and preferences only.",
        "omh_memory": "OMH memory is user-approved local context only.",
        "wiki_notes": "Wiki/notes are durable knowledge and can become stale.",
        "catalog_hint": "Catalog hints describe capabilities, not observed runtime behavior.",
        "wrapper_snapshot": "Wrapper snapshots are supplied hints until reviewed.",
    }[source]


def _stable_ref(value: Any) -> str:
    text = str(value or "default")
    if _SAFE_REF.match(text):
        return text
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


from .memory_batches import (  # noqa: E402,F401
    apply_approved_memory_update_batch,
    legacy_batch_review_required,
    review_memory_update_batch,
    stage_memory_update_batch,
)
from .rejected_decision_recall import RejectedDecisionRecallRequest, build_rejected_decision_recall  # noqa: E402,F401
