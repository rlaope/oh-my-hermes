from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
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
from ..plugin_bundle.omh.hermes_memory import build_memory_demotion_plan as _bundle_demotion_plan
from ..plugin_bundle.omh.hermes_memory import classify_record_expiry as _classify_record_expiry
from ..plugin_bundle.omh.memory_dreaming import consolidation_path as _consolidation_path
from ..plugin_bundle.omh.memory_prefetch_receipt import prefetch_receipt_path as _prefetch_receipt_path
from ..plugin_bundle.omh.memory_prefetch_receipt import read_prefetch_receipt as _read_prefetch_receipt
from ..plugin_bundle.omh.memory_open_reminders import (
    mark_open_reminder_asked as _mark_open_reminder_asked,
    read_open_reminders as _read_open_reminders,
)
from ..plugin_bundle.omh.memory_governance import (
    PRINCIPAL_PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
    PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION as _V2_PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION,
    contains_credential_like_material,
)
from ..plugin_bundle.omh.memory_recall_support import normalized_summary_key
from ..plugin_bundle.omh.memory_recall_selector import (
    _evaluate_memory_artifact as _shared_evaluate_memory_artifact,
    effective_recall_configuration as effective_recall_configuration,
    select_memory_recall,
)
from ..plugin_bundle.omh.memory_recall_support import (
    LEGACY_MEMORY_SCOPE_SCHEMA_VERSION as LEGACY_MEMORY_SCOPE_SCHEMA_VERSION,
    LEGACY_PROJECT_MEMORY_RECORD_SCHEMA_VERSION as LEGACY_PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
    MEMORY_SCOPE_SCHEMA_VERSION as MEMORY_SCOPE_SCHEMA_VERSION,
    PROJECT_MEMORY_RECORD_SCHEMA_VERSION as PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
    _INSPECTABLE_STALE_REASONS as _INSPECTABLE_STALE_REASONS,
    ADVISORY_FRESHNESS_REASONS as ADVISORY_FRESHNESS_REASONS,
    DEFAULT_MEMORY_ATTENTION_TIER as DEFAULT_MEMORY_ATTENTION_TIER,
    MAX_RETENTION_DAYS as MAX_RETENTION_DAYS,
    MEMORY_ATTENTION_TIERS as MEMORY_ATTENTION_TIERS,
    PROJECT_MEMORY_RECALL_PACK_SCHEMA_VERSION as PROJECT_MEMORY_RECALL_PACK_SCHEMA_VERSION,
    _ADMISSION_VERACITY_DEFAULT_PCT as _ADMISSION_VERACITY_DEFAULT_PCT,
    _ADMISSION_VERACITY_WEIGHT_PCT as _ADMISSION_VERACITY_WEIGHT_PCT,
    _ADVISORY_NEXT_ACTIONS as _ADVISORY_NEXT_ACTIONS,
    _AGE_TIER_BOUNDS_DAYS as _AGE_TIER_BOUNDS_DAYS,
    _AGE_TIER_WEIGHTS as _AGE_TIER_WEIGHTS,
    _DEFAULT_PERSPECTIVE_OBSERVER as _DEFAULT_PERSPECTIVE_OBSERVER,
    _DUE_SOON_NEXT_ACTION as _DUE_SOON_NEXT_ACTION,
    _EPISODE_DEFAULT_TTL_DAYS as _EPISODE_DEFAULT_TTL_DAYS,
    _EXPIRES_SOON_DAYS as _EXPIRES_SOON_DAYS,
    _EXPIRES_SOON_NEXT_ACTION as _EXPIRES_SOON_NEXT_ACTION,
    _FRESHNESS_NEXT_ACTION as _FRESHNESS_NEXT_ACTION,
    _FRESHNESS_REASON_TEXT as _FRESHNESS_REASON_TEXT,
    _FRESHNESS_WARNING_LIMIT as _FRESHNESS_WARNING_LIMIT,
    _MEMORY_ATTENTION_RANK as _MEMORY_ATTENTION_RANK,
    _MEMORY_CADENCE_DEFAULTS as _MEMORY_CADENCE_DEFAULTS,
    _MEMORY_CADENCE_MAX as _MEMORY_CADENCE_MAX,
    _MEMORY_CJK_RUN as _MEMORY_CJK_RUN,
    _MEMORY_PINS_LIMIT as _MEMORY_PINS_LIMIT,
    _MEMORY_SHORT_ASCII_TOKEN as _MEMORY_SHORT_ASCII_TOKEN,
    _MEMORY_SHORT_STOPWORDS as _MEMORY_SHORT_STOPWORDS,
    _MEMORY_WORD_TOKEN as _MEMORY_WORD_TOKEN,
    _OPEN_ASK_DAYS as _OPEN_ASK_DAYS,
    _OPEN_MAX_DAYS as _OPEN_MAX_DAYS,
    _RECALL_RRF_K as _RECALL_RRF_K,
    _RECALL_RRF_WEIGHTS as _RECALL_RRF_WEIGHTS,
    _REVIEW_DEFAULT_DAYS as _REVIEW_DEFAULT_DAYS,
    _REVIEW_DUE_SOON_DAYS as _REVIEW_DUE_SOON_DAYS,
    _SAFE_TAG as _SAFE_TAG,
    _SOURCE_EVIDENCE_MAX_BYTES as _SOURCE_EVIDENCE_MAX_BYTES,
    _TEMPORAL_QUERY_CUES as _TEMPORAL_QUERY_CUES,
    _TEMPORAL_QUERY_PHRASES as _TEMPORAL_QUERY_PHRASES,
    _age_tier as _age_tier,
    _attach_recall_ranking as _attach_recall_ranking,
    _attention_disclosure as _attention_disclosure,
    _cadence_value as _cadence_value,
    _competition_ranks as _competition_ranks,
    _earliest_deadline as _earliest_deadline,
    _empty_recall_pack as _empty_recall_pack,
    _freshness_warnings as _freshness_warnings,
    _local_source_digest as _local_source_digest,
    _memory_recall_score as _memory_recall_score,
    _memory_tokens as _memory_tokens,
    _normalize_evaluator_timestamps as _normalize_evaluator_timestamps,
    _normalize_scope as _normalize_scope,
    _normalize_tags as _normalize_tags,
    _open_days as _open_days,
    _parse_utc as _parse_utc,
    _parse_utc_naive_as_utc as _parse_utc_naive_as_utc,
    _perspective_projection as _perspective_projection,
    _ranking_field as _ranking_field,
    _ranking_flag as _ranking_flag,
    _recall_evidence_fields as _recall_evidence_fields,
    _recall_exclusion as _recall_exclusion,
    _recall_item as _recall_item,
    _recall_query_intent as _recall_query_intent,
    _record_attention_tier as _record_attention_tier,
    _record_perspective_matches as _record_perspective_matches,
    _record_resolution as _record_resolution,
    _record_staleness as _record_staleness,
    _redact_admitted_text as _redact_admitted_text,
    _redact_nested_metadata as _redact_nested_metadata,
    _redacted_metadata_label as _redacted_metadata_label,
    _replay_evaluation as _replay_evaluation,
    _resolve_query_intent as _resolve_query_intent,
    _retention_class as _retention_class,
    _scope as _scope,
    _source_evidence_state as _source_evidence_state,
    _string_list as _string_list,
    _usage_bucket as _usage_bucket,
    freshness_reason_detail as freshness_reason_detail,
    normalize_memory_attention_tier as normalize_memory_attention_tier,
    open_resolution_marker as open_resolution_marker,
    record_attention_tier as record_attention_tier,
)
# Memory admission and the store files it writes are owned by the bundle; this
# module keeps every public name as a control-plane adapter that resolves
# `OmhPaths` and passes `omh_home`.
from ..plugin_bundle.omh import memory_admission as _admission
from ..plugin_bundle.omh import memory_store_io as _store
from ..plugin_bundle.omh.memory_admission import (
    ALLOWED_SCOPE_KINDS as ALLOWED_SCOPE_KINDS,
    CAPTURE_ON_DUPLICATE_CHOICES as CAPTURE_ON_DUPLICATE_CHOICES,
    MEMORY_ATTENTION_SCHEMA_VERSION as MEMORY_ATTENTION_SCHEMA_VERSION,
    PROJECT_MEMORY_CANDIDATE_SCHEMA_VERSION as PROJECT_MEMORY_CANDIDATE_SCHEMA_VERSION,
    PROJECT_MEMORY_CAPTURE_SCHEMA_VERSION as PROJECT_MEMORY_CAPTURE_SCHEMA_VERSION,
    PROJECT_MEMORY_DEFAULT_MODE as PROJECT_MEMORY_DEFAULT_MODE,
    PROJECT_MEMORY_MODE_SOURCES as PROJECT_MEMORY_MODE_SOURCES,
    PROJECT_MEMORY_MODES as PROJECT_MEMORY_MODES,
    PROJECT_MEMORY_POLICY_SCHEMA_VERSION as PROJECT_MEMORY_POLICY_SCHEMA_VERSION,
    PROJECT_MEMORY_RECORD_TYPES as PROJECT_MEMORY_RECORD_TYPES,
    PROJECT_MEMORY_REVIEW_CARD_SCHEMA_VERSION as PROJECT_MEMORY_REVIEW_CARD_SCHEMA_VERSION,
    LifecycleCandidateError as LifecycleCandidateError,
    StaleMemoryReviewError as StaleMemoryReviewError,
    _DERIVED_FROM_LIMIT as _DERIVED_FROM_LIMIT,
    _MEMORY_ATTENTION_REASON_LIMIT as _MEMORY_ATTENTION_REASON_LIMIT,
    _absolute_deadline as _absolute_deadline,
    _attention_metadata as _attention_metadata,
    _days_after as _days_after,
    _project_memory_review_card_projection as _project_memory_review_card_projection,
    _looks_sensitive as _looks_sensitive,
    _redact as _redact,
    _redacted_scope as _redacted_scope,
    _require_review_revision as _require_review_revision,
    _sanitize_project_memory_candidate as _sanitize_project_memory_candidate,
    _staleness_projection as _staleness_projection,
    _ttl_metadata as _ttl_metadata,
    _validated_day_count as _validated_day_count,
    project_memory_review_revision as project_memory_review_revision,
)
from ..plugin_bundle.omh.memory_store_io import (
    MEMORY_INDEX_SCHEMA_VERSION as MEMORY_INDEX_SCHEMA_VERSION,
    UNREADABLE_RECORD_REASONS as UNREADABLE_RECORD_REASONS,
    _SAFE_REF as _SAFE_REF,
    _contains_sensitive_text as _contains_sensitive_text,
    _validate_allowed_keys as _validate_allowed_keys,
    _validate_context_scope as _validate_context_scope,
    _validate_perspective as _validate_perspective,
    validate_project_memory_record as validate_project_memory_record,
)
from ..paths import OmhPaths
from ..plugin_bundle.omh.project_identity import resolve_project_identity
from ..profiles.setup import read_setup_profile
from ..targets import summarize_target_registry


MEMORY_SNAPSHOT_SCHEMA_VERSION = "memory_snapshot/v1"
MEMORY_INSPECTION_SCHEMA_VERSION = "memory_inspection/v1"
MEMORY_REVIEW_CARD_SCHEMA_VERSION = "memory_review_card/v1"
HANDOFF_CONTEXT_PACK_SCHEMA_VERSION = "handoff_context_pack/v1"
MEMORY_UPDATE_BATCH_SCHEMA_VERSION = "memory_update_batch/v1"
PROJECT_MEMORY_STATUS_SCHEMA_VERSION = "project_memory_status/v1"
PROJECT_MEMORY_REVIEW_QUEUE_SCHEMA_VERSION = "project_memory_review_queue/v1"
PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION = _V2_PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION
LEGACY_PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION = "project_memory_review_record/v1"
MEMORY_RECALL_USAGE_SCHEMA_VERSION = "omh_memory_recall_usage/v1"
MEMORY_LINEAGE_SCHEMA_VERSION = "omh_memory_lineage/v1"
MEMORY_PERSPECTIVES_SCHEMA_VERSION = "omh_memory_perspectives/v1"
MEMORY_PINS_SCHEMA_VERSION = "omh_memory_pins/v1"
MEMORY_ATTENTION_CHANGE_SCHEMA_VERSION = "memory_attention_change/v1"
MEMORY_ATTENTION_JOURNAL_SCHEMA_VERSION = "omh_memory_attention_journal/v1"
MEMORY_ROLLUP_SCHEMA_VERSION = "omh_memory_rollup/v1"
HERMES_MEMORY_BRIDGE_SCHEMA_VERSION = "hermes_memory_bridge/v1"
MEMORY_CONFIRMATION_SCHEMA_VERSION = "memory_confirmation/v1"
MEMORY_CONFIRMATION_BATCH_SCHEMA_VERSION = "memory_confirmation_batch/v1"

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
MEMORY_ACTION_IDS = (
    "keep_memory",
    "forget_memory",
    "update_memory",
    "change_memory_scope",
    "apply_memory_updates",
    "show_memory_status",
    "cancel",
)
# Tags are recall-scoring keys, not filesystem refs, so they may carry CJK
# words. Running them through the ASCII-only _SAFE_REF silently dropped every
# Korean/Japanese/Chinese tag at capture time, which meant tag scoring could
# never fire for records written by CJK-speaking projects.
_PROMPTISH_KEYS = {"message", "prompt", "raw", "text", "body", "content", "prompt_template"}
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
    "query_fallback",
    "included_records",
    "excluded_records",
    "freshness_warnings",
    "attention",
    "record_count",
    "unresolved_delivered",
    "truncated",
    "redaction_policy",
    "claim_boundary",
}
_FRESHNESS_WARNING_KEYS = {
    "record_id",
    "state",
    "reason_code",
    "review_due_at",
    "expires_at",
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
    "resolution",
    "resolution_marker",
    "score",
    "ranking",
    "attention_tier",
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
    "attention_rank",
    "pinned",
    "veracity_weight_pct",
}
# Admission-mode veracity, mnemosyne-style: a human-reviewed record outranks
# an auto-safe one of equal relevance/age. The gap is deliberately small --
# both classes passed the same admission gates -- and it lands in the
# decayed score, never in eligibility. An unknown mode fails CLOSED to the
# lower weight: a trust signal must never default to maximum trust.
# Temporal query intent, conservative by construction: a fixed English cue
# set (no per-language tables, per the routing-language policy) that only
# doubles the RECENCY weight inside rank fusion. Relevance stays primary,
# so intent can never change which keyword matches win -- only how peers of
# equal relevance order. Single tokens must be unambiguous: "current",
# "latest", "now", and "newest" are ordinary engineering adjectives ("the
# current implementation") and live in the phrase list instead, where the
# surrounding words disambiguate them.
# Age tiers degrade the fused score of old records inside an equal relevance
# rank, mnemosyne-style: 0-30 days full weight, 30-180 days half, older a
# quarter. Relevance stays the primary key, so a stale strong match still
# beats a fresh weak one; the tier only reorders peers.
# Pins are guaranteed-inclusion anchors, not eligibility overrides: a pinned
# record still fails closed on expiry, scope, perspective, and review checks.
# The cap stays small because pins occupy recall budget first.
# Attention tiers are Letta's context hierarchy read deterministically. A tier
# says how much of the working context a record may occupy; it never says
# whether the record is true, approved, or fresh. `active` is the working set,
# `reference` stays recallable behind active peers, and `archive` leaves the
# default pack while the record stays in the store, readable, and answerable
# by an explicit archived query. Archive-the-tier is therefore NOT
# retirement-the-lifecycle: retirement moves an expired revision out of
# `records/` and writes a tombstone; a tier change moves nothing and deletes
# nothing. The tier feeds the one existing ranking ladder in
# `build_project_memory_recall_pack`, never a second ordering pass.
_RECALL_QUERY_FALLBACK_KEYS = {"mode", "reason", "readmitted_count"}
_RECALL_ATTENTION_KEYS = {
    "active_included",
    "reference_included",
    "archived_included",
    "archived_excluded",
    "include_archived",
    "detail",
}
# Matches `_redact`'s own cap so the bound stays true if either side moves;
# the reason is operator prose and must never become an unbounded field.
_MEMORY_ATTENTION_JOURNAL_LIMIT = 20
_MEMORY_ATTENTION_TIER_DETAIL = {
    "active": "Active records lead the working context.",
    "reference": "Reference records stay recallable but yield to active peers inside the same recall budget.",
    "archive": (
        "Archived records leave the default working context. They stay in the store, stay readable, "
        "and still answer an explicit archived query; nothing is deleted."
    ),
}
_MEMORY_ATTENTION_REFUSAL_DETAIL = {
    "record_not_found": "No approved OMH memory record carries that id, so there is no attention tier to change.",
    "record_unreadable": "That record file exists but could not be read as JSON, so its attention tier cannot be changed safely.",
    "unsupported_record_schema": "That file is not a current approved OMH memory record, so attention tiers do not apply to it.",
    "tier_unchanged": "The record already sits in the requested tier, so there is nothing to apply.",
}
_MEMORY_ATTENTION_CLAIM_BOUNDARY = (
    "An attention tier is an OMH-local recall-priority marker only. It never changes whether a record is "
    "true, approved, fresh, or eligible, it never deletes anything, and it is not execution, review, CI, "
    "merge, or Hermes internal-memory evidence."
)
_MEMORY_CONFIRMATION_REFUSAL_DETAIL = {
    "record_not_found": "No approved OMH memory record carries that id, so there is nothing to confirm.",
    "record_unreadable": "That record file exists but could not be read as JSON, so it cannot be confirmed safely.",
    "unsupported_record_schema": "That file is not a current approved OMH memory record, so confirmation does not apply to it.",
    "superseded": "A newer revision supersedes this record; confirm the live revision instead.",
    "retention_expired": "Its retention deadline passed; confirmation resets review deadlines, it does not resurrect expired records.",
    "source_requires_correction": (
        "The local source it cites changed or cannot be read now, and a new review deadline would not restore "
        "eligibility past that gate. Correct or retire the record instead."
    ),
    "no_review_deadline": "It carries no review deadline, so there is nothing to confirm.",
    "unresolved_expired": (
        "It was marked unresolved and stayed open past the open ceiling, so the question died unanswered; "
        "confirmation cannot resurrect it. Retire it (`omh memory retire <record-id>`) or re-capture the answer."
    ),
}
_MEMORY_CONFIRMATION_CLAIM_BOUNDARY = (
    "Confirmation resets one OMH-local review deadline only. It never changes the record's reviewed content, "
    "admission, or immutable review record, and it is not execution, review, CI, merge, or Hermes "
    "internal-memory evidence."
)
MEMORY_KEEP_OPEN_SCHEMA_VERSION = "memory_keep_open/v1"
_MEMORY_KEEP_OPEN_REFUSAL_DETAIL = {
    "record_not_found": "No approved OMH memory record carries that id, so there is nothing to keep open.",
    "record_unreadable": "That record file exists but could not be read as JSON, so it cannot be kept open safely.",
    "unsupported_record_schema": "That file is not a current approved OMH memory record, so keep-open does not apply to it.",
    "not_open": "The record is not marked unresolved; keep-open is the 'still open' answer and only applies to an open record.",
    "unresolved_expired": (
        "It stayed open past the open ceiling, so the question died unanswered and the record is expired; "
        "'still open' cannot resurrect it. Retire it or re-capture the question."
    ),
}
_MEMORY_KEEP_OPEN_CLAIM_BOUNDARY = (
    "Keep-open records the 'still open' answer in OMH's local ask ledger only. It never changes the record, its "
    "deadline, or its state, and it is not execution, review, CI, merge, or Hermes internal-memory evidence."
)
# Reciprocal rank fusion over deterministic signals, borrowed from hybrid
# retrieval systems: heterogeneous signals are combined by rank, not by raw
# score, so no signal needs scale normalization. Relevance rank stays the
# primary sort key; the fused score orders records only within an equal
# relevance rank, and it is stored as integer micro-units to stay valid
# scalar metadata. Usage ranks on saturating buckets so delivery counts
# cannot compound into a permanent head start.
_RECALL_USAGE_MAX_ENTRIES = 500
_LINEAGE_MAX_DEPTH = 10
_PROJECT_MEMORY_EXCLUDED_KEYS = {
    "record_id",
    "reason",
    "staleness",
    "sibling_included",
    "duplicate_of",
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
# Freshness warnings are the pre-handoff surface: a recall pack used to drop a
# stale record silently, so the executor saw a smaller pack and no reason. The
# list is bounded like every other polled surface; the pack already says
# `truncated` when its own budget cuts records.
# The pre-deadline window turns the 90-day cliff into a slope: for this many
# days before a record's review deadline, packs still deliver it but carry a
# named warning, so the operator hears about the deadline while confirming
# still keeps recall intact -- not on the first day the record is gone.
# The retention twin of the review window: an expiring record (an episode's
# 30-day TTL, most often) gets the same advance notice. Confirmation cannot
# extend a TTL -- the honest actions are a correction with a longer TTL or
# letting it expire and retiring it.
# Reasons `--include-stale` may surface for inspection. They carry ineligible
# replay evidence, so the pack still cannot be attached as approved context.
# Advisory freshness reasons describe a record that is still fresh and still
# delivered. Consumers that treat "has a freshness reason" as "this record is
# stale" (wrapper continuity, role-context-pack diffs) must subtract this set,
# or the advance notice would read as the failure it exists to prevent.
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
_HANDOFF_CONTEXT_SOURCE_REF_KEYS = {"source", "truth_level", "precedence", "item_count"}
_HANDOFF_CONTEXT_INCLUDED_KEYS = {
    "item_id",
    "key",
    "summary",
    "source",
    "source_kind",
    "truth_level",
    "scope",
    "artifact_ref",
    "replay_evaluation",
    "profile_id",
    "profile_revision",
    "profile_digest",
    "review_id",
}
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


def _store_lock(path: Path) -> Any:
    # Looked up at call time, so admission takes whatever `file_lock` this
    # module holds; it locks the same sidecar the bundle's store lock does.
    return file_lock(path, private=True)


def _clock() -> str:
    return utc_now()


def build_project_memory_policy(paths: OmhPaths, *, mode: str | None = None, mode_source: str = "default") -> dict[str, object]:
    return _admission.build_project_memory_policy(paths.omh_home, mode=mode, mode_source=mode_source)


def read_project_memory_policy(paths: OmhPaths) -> dict[str, object]:
    return _admission.read_project_memory_policy(paths.omh_home)


def capture_project_memory_candidate(
    paths: OmhPaths,
    summary: str,
    *,
    content: str = "",
    record_type: str = "fact",
    scope_kind: str = "project",
    scope_ref: str | None = None,
    source: str = "cli",
    source_ref: str = "",
    tags: list[str] | tuple[str, ...] | None = None,
    ttl_days: int | None = None,
    stale_after_days: int | None = None,
    stale_after: str = "",
    expires_at: str = "",
    retention_class: str = "standard",
    derived_from: list[str] | tuple[str, ...] | None = None,
    observer: str | None = None,
    observed: str | None = None,
    force_review: bool = False,
    principal_context: dict[str, object] | None = None,
    audience_principals: list[str] | tuple[str, ...] = (),
    executor_perspective: str = "hermes",
    unresolved: bool = False,
    on_duplicate: str = "candidate",
) -> dict[str, object]:
    return _admission.capture_project_memory_candidate(
        paths.omh_home,
        summary,
        content=content,
        record_type=record_type,
        scope_kind=scope_kind,
        scope_ref=scope_ref,
        source=source,
        source_ref=source_ref,
        tags=tags,
        ttl_days=ttl_days,
        stale_after_days=stale_after_days,
        stale_after=stale_after,
        expires_at=expires_at,
        retention_class=retention_class,
        derived_from=derived_from,
        observer=observer,
        observed=observed,
        force_review=force_review,
        principal_context=principal_context,
        audience_principals=audience_principals,
        executor_perspective=executor_perspective,
        unresolved=unresolved,
        on_duplicate=on_duplicate,
        clock=_clock,
        lock=_store_lock,
    )


def approve_project_memory_candidate(
    paths: OmhPaths,
    candidate_id: str,
    *,
    approved_by: str = "operator",
    retention_class: str | None = None,
    expected_revision: str = "",
    reviewer_principal: str | None = None,
    unresolved: bool = False,
) -> dict[str, object]:
    return _admission.approve_project_memory_candidate(
        paths.omh_home,
        candidate_id,
        approved_by=approved_by,
        retention_class=retention_class,
        expected_revision=expected_revision,
        reviewer_principal=reviewer_principal,
        unresolved=unresolved,
        clock=_clock,
        lock=_store_lock,
    )


def _recall_operation_states(paths: OmhPaths, records: list[dict[str, Any]]) -> dict[str, str]:
    return _store.recall_operation_states(paths.omh_home, records)


def _project_memory_review_resolver(paths: OmhPaths) -> dict[str, dict[str, object]]:
    return _store.project_memory_review_resolver(paths.omh_home)


def _read_project_memory_candidate(paths: OmhPaths, candidate_id: str) -> dict[str, Any] | None:
    return _store.read_project_memory_candidate(paths.omh_home, candidate_id)


def _read_project_memory_candidates(paths: OmhPaths) -> list[dict[str, Any]]:
    return _store.read_project_memory_candidates(paths.omh_home)


def _read_project_memory_records(paths: OmhPaths) -> list[dict[str, Any]]:
    return _store.read_project_memory_records(paths.omh_home)


def scan_project_memory_records(paths: OmhPaths) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    return _store.scan_project_memory_records(paths.omh_home)


def _read_project_memory_reviews(paths: OmhPaths) -> list[dict[str, Any]]:
    return _store.read_project_memory_reviews(paths.omh_home)


def _write_project_memory_candidate_unlocked(paths: OmhPaths, candidate: dict[str, object]) -> None:
    _store.write_project_memory_candidate_unlocked(paths.omh_home, candidate)


def _write_project_memory_record(paths: OmhPaths, record: dict[str, object]) -> None:
    _store.write_project_memory_record(paths.omh_home, record)


def _write_project_memory_review_decision(paths: OmhPaths, review: dict[str, object]) -> dict[str, object]:
    return _store.write_project_memory_review_decision(paths.omh_home, review)


def _write_memory_index(paths: OmhPaths) -> None:
    _store.write_memory_index(paths.omh_home, lock=_store_lock, clock=_clock)


def _write_memory_index_unlocked(paths: OmhPaths) -> None:
    _store.write_memory_index_unlocked(paths.omh_home, updated_at=utc_now())


def _memory_candidates_dir(paths: OmhPaths) -> Path:
    return _store.memory_candidates_dir(paths.omh_home)


def _memory_records_dir(paths: OmhPaths) -> Path:
    return _store.memory_records_dir(paths.omh_home)


def _memory_reviews_dir(paths: OmhPaths) -> Path:
    return _store.memory_reviews_dir(paths.omh_home)


def _memory_record_path(paths: OmhPaths, record_id: str) -> Path:
    return _store.memory_record_path(paths.omh_home, record_id)


def _memory_scope_paths(paths: OmhPaths) -> list[Path]:
    return _store.memory_scope_paths(paths.omh_home)


def _assert_under_memory_root(paths: OmhPaths, path: Path) -> None:
    _store.assert_under_memory_root(paths.omh_home, path)


def _find_duplicate_record(paths: OmhPaths, summary: str, *, now: datetime | None = None) -> str:
    return _admission._find_duplicate_record(paths.omh_home, summary, now=now)


# A notice window is not a retention period: a year is already generous, and
# accepting the 100-year retention ceiling here would let one config typo turn
# every record with any TTL into a permanent warning.


MEMORY_DEMOTION_STAGE_SCHEMA_VERSION = "memory_demotion_stage/v1"


def build_memory_demotion(paths: OmhPaths, *, file_label: str | None = None, max_entries: int = 5) -> dict[str, object]:
    """Plan L1->L2 demotions: which Hermes entries to move into the OMH store.

    Same delegation shape as the bridge: the planner lives in the plugin
    bundle because the Hermes host can only import that package, and this
    wrapper points the dependency the direction that works on both hosts.

    The wrapper annotates each planned row with its `staging_status` from the
    OMH candidate store -- `unstaged`, `already_staged`, or
    `previously_rejected` -- so the plan advertises exactly the work `--stage`
    would actually do instead of re-proposing rows staging will refuse.
    """
    plan = _bundle_demotion_plan(paths.omh_home, paths.hermes_home, file_label=file_label, max_entries=max_entries)
    rows = plan.get("rows") if isinstance(plan.get("rows"), list) else []
    if not rows:
        return plan
    status_by_ref = _demotion_status_by_ref(paths)
    annotated = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        annotated.append({**row, "staging_status": status_by_ref.get(_demotion_origin_ref(row), "unstaged")})
    return {**plan, "rows": annotated}


def _demotion_origin_ref(row: dict[str, object]) -> str:
    return f"hermes:{row.get('file', '')}#{str(row.get('sha256', ''))[:16]}"


def _demotion_status_by_ref(paths: OmhPaths) -> dict[str, str]:
    """Origin ref -> staging verdict, from the candidate store."""
    status_by_ref: dict[str, str] = {}
    for candidate in _read_project_memory_candidates(paths):
        ref = str(candidate.get("source_ref", ""))
        if not ref:
            continue
        status = str(candidate.get("status", "") or "")
        status_by_ref[ref] = "previously_rejected" if status == "rejected" else "already_staged"
    return status_by_ref


def _refused_demotion_row(row: dict[str, object], status: str, detail: str) -> dict[str, object]:
    return {
        "file": str(row.get("file", "")),
        "entry_index": int(row.get("entry_index", 0) or 0),
        "sha256": str(row.get("sha256", "")),
        "candidate_id": "",
        "status": status,
        "auto_approved": False,
        "detail": detail,
        "reference_line": str(row.get("reference_line", "")),
    }


def stage_memory_demotion(paths: OmhPaths, *, file_label: str | None = None, max_entries: int = 5) -> dict[str, object]:
    """Capture each planned demotion row as an OMH candidate (L2 side only).

    Staging is the half of a demotion OMH can actually do: the entry's
    content becomes a review-first candidate in the governed store, keyed
    back to its L1 origin through `source_ref` carrying the entry digest.
    The L1 half -- replacing the original entry with the short reference
    line -- stays with Hermes's own memory tool, so the plan's reference
    lines travel on this payload as prepared text and nothing else.

    Demotion moves content or it refuses; it never quietly damages it. An
    entry the summary bound would truncate, or one the sensitive-content
    redactor would collapse to `[redacted]`, is refused with a named status
    and STAYS IN L1 -- because the very next documented step is deleting the
    L1 original, which must never happen to a copy that is not intact.
    Staging is also idempotent: a ref already in the candidate store reports
    `already_staged`, or `previously_rejected` when a reviewer already said
    no to exactly this entry, and never mints a duplicate candidate.
    """
    plan = build_memory_demotion(paths, file_label=file_label, max_entries=max_entries)
    rows = plan.get("rows") if isinstance(plan.get("rows"), list) else []
    staged: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        entry_text = str(row.get("entry_text", "")).strip()
        origin_ref = _demotion_origin_ref(row)
        staging_status = str(row.get("staging_status", "unstaged"))
        if staging_status != "unstaged":
            staged.append(
                _refused_demotion_row(
                    row,
                    staging_status,
                    "A candidate for exactly this entry already exists in the OMH store."
                    if staging_status == "already_staged"
                    else "A reviewer already rejected exactly this entry; the refusal is the standing decision.",
                )
            )
            continue
        if _looks_sensitive(entry_text):
            # The capture redactor would store the literal string
            # "[redacted]" and the fact would exist nowhere but the L1
            # entry the workflow then says to delete.
            staged.append(
                _refused_demotion_row(
                    row,
                    "redacted_cannot_demote",
                    "The sensitive-content redactor would collapse this entry; it stays in L1 intact.",
                )
            )
            continue
        if len(entry_text) > _MEMORY_ATTENTION_REASON_LIMIT:
            staged.append(
                _refused_demotion_row(
                    row,
                    "summary_bound_exceeded",
                    f"The {_MEMORY_ATTENTION_REASON_LIMIT}-char summary bound would truncate this entry; it stays in L1 intact. "
                    "Split it into smaller entries to demote it.",
                )
            )
            continue
        captured = capture_project_memory_candidate(
            paths,
            entry_text,
            record_type="fact",
            tags=["hermes-demotion"],
            # Not screened for instruction-shaped text; the reason sits
            # at the screen in `capture_project_memory_candidate`.
            source="hermes_demotion",
            source_ref=origin_ref,
        )
        if not bool(captured.get("captured", True)):
            # Any refused capture ends the staging run honestly: nothing
            # after this row was attempted, and the payload says why.
            return {
                **captured,
                "schema_version": MEMORY_DEMOTION_STAGE_SCHEMA_VERSION,
                "staged": staged,
                "staged_count": len(staged),
            }
        candidate = captured.get("candidate") if isinstance(captured.get("candidate"), dict) else {}
        record = captured.get("record") if isinstance(captured.get("record"), dict) else {}
        stored_summary = str(candidate.get("summary", "") or record.get("summary", ""))
        if stored_summary != entry_text:
            # Belt over the two named guards above: if capture stored
            # anything other than the exact entry, the copy is not intact
            # and the row must say so rather than claim a clean stage.
            staged.append(
                _refused_demotion_row(
                    row,
                    "content_not_intact",
                    "Capture stored an altered copy of this entry; keep the L1 original.",
                )
            )
            continue
        staged.append(
            {
                "file": str(row.get("file", "")),
                "entry_index": int(row.get("entry_index", 0) or 0),
                "sha256": str(row.get("sha256", "")),
                "candidate_id": str(candidate.get("candidate_id", "") or record.get("candidate_id", "")),
                "status": str(candidate.get("status", "") or ("approved" if record else "")),
                "auto_approved": bool(captured.get("auto_approved", False)),
                "reference_line": str(row.get("reference_line", "")),
            }
        )
    captured_count = sum(1 for row in staged if str(row.get("status", "")) in {"pending_review", "approved"})
    return {
        "schema_version": MEMORY_DEMOTION_STAGE_SCHEMA_VERSION,
        **({"reason_code": str(plan["reason_code"])} if plan.get("reason_code") else {}),
        "staged": staged,
        "staged_count": len(staged),
        "captured_count": captured_count,
        "refused_count": len(staged) - captured_count,
        "files": plan.get("files", []),
        "already_covered": plan.get("already_covered", []),
        "redaction_policy": "local_content_plan",
        "next_action": (
            "Approve the staged candidates (`omh memory review`, `omh memory approve`), then ask Hermes to "
            "replace each cleanly staged entry with its reference line through Hermes's own memory tool. "
            "Refused rows were NOT copied to L2 -- leave their L1 entries in place."
        ),
        "claim_boundary": (
            "Staging captured OMH-local candidates only (prepared_not_observed). OMH reads Hermes memory and "
            "cannot change it; no Hermes entry was edited, and this payload is not execution, review, CI, or "
            "merge evidence."
        ),
    }


def build_hermes_memory_bridge(paths: OmhPaths) -> dict[str, object]:
    """Relate OMH's approved records to what Hermes already remembers.

    One implementation, kept in the plugin bundle. The Hermes process cannot
    import this package, so a bundle that delegated here would answer "package
    absent" on the only host that matters; the dependency has to point the other
    way.
    """
    return _bundle_memory_bridge(paths.omh_home, paths.hermes_home)


_OPEN_RECORDS_STATUS_LIMIT = 20


def _open_record_rows(paths: OmhPaths, records: list[dict[str, Any]], *, now: datetime) -> list[dict[str, object]]:
    """Every open record as one bounded row, oldest ``open_since`` first.

    ``state`` is the freshness verdict (``fresh`` inside the review deadline,
    ``open`` past it, ``expired`` past the open ceiling), ``open_days`` its
    age, and ``last_asked_at`` the newest ask in the local ledger -- "" when
    the provider has not asked yet. The summary is the same bounded,
    redacted projection a recall pack carries.
    """
    ledger = _read_open_reminders(paths.omh_home)
    rows: list[tuple[str, str, dict[str, object]]] = []
    for record in records:
        staleness = record.get("staleness") if isinstance(record.get("staleness"), dict) else {}
        if _record_resolution(staleness) != "open":
            continue
        verdict = _record_staleness(record, now=now)
        record_id = _redacted_metadata_label(record.get("record_id", ""))
        asked = ledger.get(str(record.get("record_id", "")), {})
        rows.append(
            (
                str(staleness.get("open_since", "") or ""),
                record_id,
                {
                    "record_id": record_id,
                    "summary": _redact_admitted_text(str(record.get("summary", "")))[:500],
                    "open_days": int(verdict.get("open_days", 0) or 0),
                    "open_since": _redact_admitted_text(str(staleness.get("open_since", "") or "")),
                    "open_expires_at": _redact_admitted_text(str(staleness.get("open_expires_at", "") or "")),
                    "review_due_at": str(verdict.get("review_due_at", "") or ""),
                    "state": str(verdict.get("state", "")),
                    "last_asked_at": str(asked.get("asked_at", "") or ""),
                },
            )
        )
    rows.sort(key=lambda item: (item[0], item[1]))
    return [row for _since, _record_id, row in rows]


def _last_prefetch_status(paths: OmhPaths, *, now: datetime) -> dict[str, object]:
    """Whether the provider has ever handed a pack to Hermes from this home.

    The store counts above say what COULD be recalled; this says what the
    last prefetch actually returned, read off the receipt the provider writes
    only when it serves a pack. For a month the store was empty and every
    prefetch returned "" (the hook-order defect), and no status surface could
    tell the two apart: both read as "nothing recalled". `never_served` is
    the state that must be loud -- an installed provider that has not served
    once is either unused or broken, never fine.
    """
    receipt_path = _prefetch_receipt_path(paths.omh_home)
    receipt = _read_prefetch_receipt(paths.omh_home)
    if receipt is None:
        # The reader returns None for a missing file and for one it refuses
        # (malformed, foreign schema, inconsistent). Only the first means
        # nothing was recorded; a refused receipt was written by a serve.
        present = receipt_path.is_file() and not receipt_path.is_symlink()
        return {
            "state": "unreadable" if present else "never_served",
            "served_at": None,
            "age_hours": None,
            "session_id": None,
            "rendered_record_count": None,
            "rendered_block_count": None,
            "receipt_path": str(receipt_path),
            "claim_boundary": (
                "A receipt file exists but does not validate; a pack was served and the record of it cannot be read."
                if present
                else "No receipt means no served pack was recorded from this home; it is not evidence that nothing was served elsewhere."
            ),
        }
    served_at = str(receipt.get("served_at", "") or "")
    age_hours: float | None = None
    try:
        served_moment = datetime.fromisoformat(served_at.replace("Z", "+00:00")) if served_at else None
    except ValueError:
        served_moment = None
    if served_moment is not None:
        age_hours = round(max((now - served_moment).total_seconds(), 0.0) / 3600, 1)
    rendering = receipt.get("rendering") if isinstance(receipt.get("rendering"), dict) else {}
    return {
        "state": str(receipt.get("state", "") or "prepared"),
        "served_at": served_at or None,
        "age_hours": age_hours,
        "session_id": str(receipt.get("session_id", "") or "") or None,
        "rendered_record_count": int(rendering.get("rendered_count", 0) or 0),
        "rendered_block_count": int(rendering.get("rendered_block_count", 0) or 0),
        "receipt_path": str(receipt_path),
        "claim_boundary": "A receipt records what the provider handed the host; it is not evidence that the model read or used it.",
    }


def build_project_memory_status(paths: OmhPaths) -> dict[str, object]:
    candidates = _read_project_memory_candidates(paths)
    records, unreadable_records = scan_project_memory_records(paths)
    reviews = _read_project_memory_reviews(paths)
    now = datetime.now(timezone.utc)
    evaluations = [_evaluate_memory_artifact(record, paths=paths, now=now, review_resolver=_project_memory_review_resolver(paths)) for record in records]
    # `unresolved_expired` is the evaluator's other expiry -- a question that
    # died past its open ceiling -- and counts here exactly like `expired_*`.
    expired_records = sum(
        1
        for evaluation in evaluations
        if str(evaluation["reason_code"]).startswith("expired_") or str(evaluation["reason_code"]) == "unresolved_expired"
    )
    candidate_status_counts: dict[str, int] = {}
    for candidate in candidates:
        status = _redact_admitted_text(str(candidate.get("status", "unknown")))
        candidate_status_counts[status] = candidate_status_counts.get(status, 0) + 1
    open_records = _open_record_rows(paths, records, now=now)
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
            "approved_records": sum(1 for record in records if record.get("schema_version") in {PROJECT_MEMORY_RECORD_SCHEMA_VERSION, PRINCIPAL_PROJECT_MEMORY_RECORD_SCHEMA_VERSION}),
            "principal_bound_records": sum(1 for record in records if record.get("schema_version") == PRINCIPAL_PROJECT_MEMORY_RECORD_SCHEMA_VERSION),
            "legacy_identity_unbound_records": sum(1 for record in records if record.get("schema_version") != PRINCIPAL_PROJECT_MEMORY_RECORD_SCHEMA_VERSION),
            "expired_records": expired_records,
            "eligible_records": sum(1 for evaluation in evaluations if evaluation["eligible"]),
            "ineligible_records": sum(1 for evaluation in evaluations if not evaluation["eligible"]),
            "review_required_legacy": sum(1 for evaluation in evaluations if evaluation["reason_code"] == "review_required_legacy"),
            # Record files on disk that this build cannot admit. They used to be
            # dropped by the reader with no count anywhere, so a store that had
            # silently shrunk looked exactly like a smaller store.
            "unreadable_records": len(unreadable_records),
            "review_records": len(reviews),
            "candidate_statuses": candidate_status_counts,
            # Records a person marked unresolved and nobody has answered yet.
            # They keep costing attention until confirm, correct, or retire.
            "unresolved": len(open_records),
        },
        "unreadable_records": unreadable_records,
        # Oldest first, bounded: the list a curation pass reads to ask the
        # three questions (resolved / still open / drop it) per record.
        "open_records": open_records[:_OPEN_RECORDS_STATUS_LIMIT],
        "last_prefetch": _last_prefetch_status(paths, now=now),
        "hermes_memory": build_hermes_memory_bridge(paths),
        "redaction_policy": "metadata_only",
        "claim_boundary": "Project memory status is prepared local context only; it is not execution, review, CI, merge, or Hermes internal-memory evidence.",
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
    # The displayed fields come from the same projection the revision hashes,
    # so a card cannot show a candidate-derived value the fingerprint missed.
    displayed = _project_memory_review_card_projection(candidate)
    safety = displayed["safety"] if isinstance(displayed["safety"], dict) else {}
    safety_status = str(safety.get("status", "needs_review"))
    recommended_action = "reject" if safety_status == "blocked" else "approve_or_reject"
    return {
        "schema_version": PROJECT_MEMORY_REVIEW_CARD_SCHEMA_VERSION,
        "review_revision": project_memory_review_revision(candidate),
        **displayed,
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


def candidate_is_review_card_backed(candidate: dict[str, Any]) -> bool:
    """True when `memory review` renders a card for this candidate.

    Only card-backed candidates can carry a review revision, because the
    revision IS the card's fingerprint. v2 lifecycle candidates (correction,
    restore) are staged by the lifecycle path and approved by id without a
    card ever being rendered, so demanding a revision for them would ask for
    a value no surface produces.
    """
    return (
        str(candidate.get("schema_version", "")) == PROJECT_MEMORY_CANDIDATE_SCHEMA_VERSION
        and not str(candidate.get("lifecycle", "") or "")
    )


def reject_project_memory_candidate(
    paths: OmhPaths,
    candidate_id: str,
    *,
    rejected_by: str = "operator",
    reason: str = "",
    expected_revision: str = "",
) -> dict[str, object]:
    # Same single-hold read-check-write as approval: a rejection that races a
    # recapture must refuse rather than reject text the reviewer never read.
    with file_lock(paths.memory_index_path, private=True):
        candidate = _read_project_memory_candidate(paths, candidate_id)
        if not candidate:
            raise FileNotFoundError(candidate_id)
        if expected_revision:
            _require_review_revision(candidate, expected_revision)
        now = utc_now()
        safe_rejected_by = _redacted_metadata_label(rejected_by)
        candidate = _sanitize_project_memory_candidate(
            {
                **candidate,
                "status": "rejected",
                "reviewed_at": now,
                "reviewed_by": safe_rejected_by,
                "rejection_reason": _redact(str(reason or ""))[:300],
            }
        )
        _write_project_memory_candidate_unlocked(paths, candidate)
        review = _write_project_memory_review_decision(
            paths,
            {
                "schema_version": PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION,
                "review_id": f"review_{candidate_id}",
                "candidate_id": candidate_id,
                "decision": "rejected",
                "reviewer_claim": safe_rejected_by,
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
    include_archived: bool = False,
    attention_override: dict[str, str] | None = None,
    now: datetime | None = None,
    stale_override: dict[str, object] | None = None,
    run_id: str | None = None,
    observer: str | None = None,
    observed: str | None = None,
    query_intent: str | None = None,
    allowed_scopes: list[dict[str, str]] | tuple[dict[str, str], ...] | None = None,
    required_scope_kinds: tuple[str, ...] | None = None,
    inspection: bool = True,
    principal_context: dict[str, object] | None = None,
    shared_surface: bool = False,
) -> dict[str, object]:
    """Read the local store, then delegate every selection decision to the plugin.

    Unscoped calls retain operator inspection semantics. Delivery callers use
    explicit allowlists and inspection=False; partial selectors fail closed.
    """
    if any(value is not None and contains_credential_like_material(str(value)) for value in (scope_kind, scope_ref)):
        raise ValueError("credential-like recall selector is not allowed")
    if allowed_scopes is not None and (scope_kind is not None or scope_ref is not None):
        raise ValueError("use either allowed_scopes or scope_kind/scope_ref")
    if scope_kind is not None or scope_ref is not None:
        allowed_scopes = [{"kind": str(scope_kind or ""), "ref": str(scope_ref or "")}]
    required = required_scope_kinds if required_scope_kinds is not None else ((scope_kind,) if scope_kind else ("project",))
    records = _read_project_memory_records(paths)
    return select_memory_recall(
        records, query,
        allowed_scopes=allowed_scopes,
        required_scope_kinds=required,
        inspection=inspection,
        review_resolver=_project_memory_review_resolver(paths),
        operation_states=_recall_operation_states(paths, records),
        policy=read_project_memory_policy(paths),
        usage=read_recall_usage(paths),
        pins=set(read_memory_pins(paths)),
        executor_target=executor_target,
        session_id=session_id,
        limit=limit,
        max_chars=max_chars,
        include_stale=include_stale,
        include_archived=include_archived,
        attention_override=attention_override,
        now=now,
        stale_override=stale_override,
        run_id=run_id,
        observer=observer,
        observed=observed,
        query_intent=query_intent,
        principal_context=principal_context,
        shared_surface=shared_surface,
    ).pack


def memory_recall_pack_for_handoff(
    paths: OmhPaths,
    query: str,
    *,
    executor_target: str = "generic",
    session_id: str = "",
    limit: int = 5,
    query_intent: str | None = None,
) -> dict[str, object] | None:
    # The executor target is the handoff's perspective lens: unscoped records
    # pass as always, and records observed for this executor join them --
    # while a record about any other executor stays out of this pack.
    pack_scope = _handoff_pack_scope(paths, scope_kind=None, scope_ref=None)
    allowed_scopes = [{"kind": "user-global", "ref": "default"}, pack_scope]
    if session_id:
        allowed_scopes.append({"kind": "thread", "ref": session_id})
    pack = build_project_memory_recall_pack(
        paths,
        query,
        executor_target=executor_target,
        session_id=session_id,
        allowed_scopes=allowed_scopes,
        required_scope_kinds=("project",),
        inspection=False,
        limit=limit,
        observed=_handoff_perspective_lens(executor_target),
        # Per the routing-language policy the cue table stays English-only;
        # a caller that read the message and knows the user asked for the
        # latest -- in any language -- states it here instead.
        query_intent=query_intent,
    )
    # A pack with no eligible records but a freshness warning still travels.
    # Dropping it here was the silent failure: the handoff went out with no
    # memory and no statement that a stale record had been held back, so the
    # operator never got the chance to confirm, replace, or retire it.
    if pack_scope["kind"] == "unresolved":
        return {**pack, "scope": pack_scope}
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


# One identity for "the same fact": capture's `duplicate_of` and recall's
# `duplicate_record` read the same function, so the two can never disagree.
# The bundle owns it because the bundle cannot import this package.
_normalized_summary_key = normalized_summary_key


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
                "summary": _redact_admitted_text(str(record.get("summary", "")))[:240],
                "approved_at": str(record.get("approved_at", "")),
            }
            for record in members
        ],
        "member_count": len(members),
        "considered_count": considered,
        "truncated_members": truncated_members,
        "proposed_summary": _redact_admitted_text(proposed_summary)[:240],
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
    key = _normalized_summary_key(_redact_admitted_text(summary.strip())[:500])
    if not key:
        return ""
    for candidate in _read_project_memory_candidates(paths):
        if str(candidate.get("status", "")) not in {"pending_review", "blocked_review_required"}:
            continue
        if _normalized_summary_key(str(candidate.get("summary", ""))) == key:
            return str(candidate.get("candidate_id", ""))
    return ""


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


def _memory_attention_journal_path(paths: OmhPaths) -> Path:
    return paths.memory_dir / "attention.jsonl"


def read_memory_attention_journal(
    paths: OmhPaths,
    *,
    record_id: str | None = None,
    limit: int = _MEMORY_ATTENTION_JOURNAL_LIMIT,
) -> list[dict[str, object]]:
    """Most recent tier changes, oldest first, bounded like every polled surface.

    This is the reversibility surface: every applied change records the tier it
    came from, so an archive is always undoable from local evidence alone.
    """
    # A corrupt line costs only itself: the journal is an audit trail, and a
    # single bad append must never make the tier surface unreadable.
    lines, _errors = read_jsonl_objects(_memory_attention_journal_path(paths))
    entries = [
        entry
        for entry in lines
        if isinstance(entry, dict)
        and entry.get("schema_version") == MEMORY_ATTENTION_JOURNAL_SCHEMA_VERSION
        and (record_id is None or str(entry.get("record_id", "")) == str(record_id))
    ]
    return entries[-max(limit, 0):] if limit > 0 else []


def _attention_stamp(now: datetime | None) -> str:
    if now is None:
        return utc_now()
    moment = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _attention_working_context(pack: dict[str, object]) -> dict[str, object]:
    included = pack.get("included_records")
    items = included if isinstance(included, list) else []
    return {
        "record_ids": [str(item.get("record_id", "")) for item in items if isinstance(item, dict)],
        "record_count": len(items),
        "truncated": bool(pack.get("truncated", False)),
        "attention": dict(pack.get("attention", {})) if isinstance(pack.get("attention"), dict) else {},
    }


def _refused_attention_change(record_id: str, requested: str, reason: str, reason_code: str) -> dict[str, object]:
    return {
        "schema_version": MEMORY_ATTENTION_CHANGE_SCHEMA_VERSION,
        "record_id": record_id,
        "current_tier": "",
        "requested_tier": requested,
        "reason": _redact(str(reason or ""))[:_MEMORY_ATTENTION_REASON_LIMIT],
        "eligible": False,
        "applied": False,
        "reason_code": reason_code,
        "detail": _MEMORY_ATTENTION_REFUSAL_DETAIL[reason_code],
        "tier_detail": _MEMORY_ATTENTION_TIER_DETAIL[requested],
        "working_context_before": {"record_ids": [], "record_count": 0, "truncated": False, "attention": {}},
        "working_context_after": {"record_ids": [], "record_count": 0, "truncated": False, "attention": {}},
        "leaving_working_context": [],
        "entering_working_context": [],
        "recent_changes": [],
        "redaction_policy": "metadata_only",
        "next_action": "No tier change is possible: resolve the reported reason first.",
        "claim_boundary": _MEMORY_ATTENTION_CLAIM_BOUNDARY,
    }


def build_memory_attention_change(
    paths: OmhPaths,
    record_id: str,
    *,
    tier: str,
    reason: str = "",
    query: str = "",
    limit: int = 6,
    now: datetime | None = None,
) -> dict[str, object]:
    """Preview one tier change: what the working context holds now, and after.

    Nothing on disk moves. The projected "after" context is built by the same
    recall builder with the requested tier substituted in memory, so the
    preview is the pack the operator will actually get -- not a description of
    one. Pass ``now`` to keep repeated previews byte-identical.
    """
    requested = normalize_memory_attention_tier(tier)
    normalized_id = str(record_id).strip()
    if not _SAFE_REF.match(normalized_id):
        raise ValueError(f"unsafe memory record id: {record_id!r}")
    record, error = read_json_object_result(_memory_record_path(paths, normalized_id))
    if error:
        return _refused_attention_change(normalized_id, requested, reason, "record_unreadable")
    if not isinstance(record, dict) or str(record.get("record_id", "")) != normalized_id:
        return _refused_attention_change(normalized_id, requested, reason, "record_not_found")
    if record.get("schema_version") != PROJECT_MEMORY_RECORD_SCHEMA_VERSION:
        return _refused_attention_change(normalized_id, requested, reason, "unsupported_record_schema")
    current = record_attention_tier(record)
    if current == requested:
        return {
            **_refused_attention_change(normalized_id, requested, reason, "tier_unchanged"),
            "current_tier": current,
        }
    before = build_project_memory_recall_pack(paths, query, limit=limit, now=now)
    after = build_project_memory_recall_pack(
        paths,
        query,
        limit=limit,
        now=now,
        attention_override={normalized_id: requested},
    )
    before_context = _attention_working_context(before)
    after_context = _attention_working_context(after)
    before_ids = list(before_context["record_ids"]) if isinstance(before_context["record_ids"], list) else []
    after_ids = list(after_context["record_ids"]) if isinstance(after_context["record_ids"], list) else []
    return {
        "schema_version": MEMORY_ATTENTION_CHANGE_SCHEMA_VERSION,
        "record_id": normalized_id,
        "current_tier": current,
        "requested_tier": requested,
        "reason": _redact(str(reason or ""))[:_MEMORY_ATTENTION_REASON_LIMIT],
        "eligible": True,
        "applied": False,
        "reason_code": "planned",
        "detail": (
            f"Moving this record from {current} to {requested} leaves "
            f"{after_context['record_count']} record(s) in the working context, was {before_context['record_count']}."
        ),
        "tier_detail": _MEMORY_ATTENTION_TIER_DETAIL[requested],
        "working_context_before": before_context,
        "working_context_after": after_context,
        "leaving_working_context": [item for item in before_ids if item not in set(after_ids)],
        "entering_working_context": [item for item in after_ids if item not in set(before_ids)],
        "recent_changes": read_memory_attention_journal(paths, record_id=normalized_id),
        "redaction_policy": "metadata_only",
        "next_action": (
            f"Apply with `omh memory attention {normalized_id} --tier {requested} --apply`. "
            "Nothing has changed yet."
        ),
        "claim_boundary": _MEMORY_ATTENTION_CLAIM_BOUNDARY,
    }


def apply_memory_attention_change(
    paths: OmhPaths,
    record_id: str,
    *,
    tier: str,
    reason: str = "",
    query: str = "",
    limit: int = 6,
    now: datetime | None = None,
) -> dict[str, object]:
    """Apply the previewed tier change to the local record and journal it.

    Apply re-derives the preview so both steps share one guard set, then
    re-reads the record under the store lock: a tier change that raced another
    operator would otherwise journal a previous tier that was never true.
    """
    report = build_memory_attention_change(paths, record_id, tier=tier, reason=reason, query=query, limit=limit, now=now)
    if not bool(report.get("eligible")):
        raise ValueError(f"{report['reason_code']}: {report['detail']}")
    normalized_id = str(report["record_id"])
    requested = str(report["requested_tier"])
    current = str(report["current_tier"])
    changed_at = _attention_stamp(now)
    entry = {
        "schema_version": MEMORY_ATTENTION_JOURNAL_SCHEMA_VERSION,
        "record_id": normalized_id,
        "previous_tier": current,
        "tier": requested,
        "reason": str(report["reason"]),
        "changed_at": changed_at,
        "actor_class": "operator",
        "redaction_policy": "metadata_only",
        "claim_boundary": _MEMORY_ATTENTION_CLAIM_BOUNDARY,
    }
    with file_lock(paths.memory_index_path, private=True):
        stored, error = read_json_object_result(_memory_record_path(paths, normalized_id))
        if error or not isinstance(stored, dict) or record_attention_tier(stored) != current:
            raise ValueError(f"memory record {normalized_id} changed attention tier concurrently; re-run the preview")
        _write_project_memory_record(
            paths,
            {
                **stored,
                "attention": _attention_metadata(requested, reason=reason, previous_tier=current, changed_at=changed_at),
            },
        )
        append_jsonl_locked(_memory_attention_journal_path(paths), entry)
        _write_memory_index_unlocked(paths)
    return {
        **report,
        "applied": True,
        "reason_code": "applied",
        "changed_at": changed_at,
        "journal_entry": entry,
        "next_action": (
            f"Reverse it with `omh memory attention {normalized_id} --tier {current} --apply`. "
            "The record itself was never moved or deleted."
        ),
    }


def confirm_project_memory_record(
    paths: OmhPaths,
    record_id: str,
    *,
    confirmed_by: str = "operator",
    stale_after_days: int | None = None,
    stale_after: str = "",
    now: datetime | None = None,
) -> dict[str, object]:
    """Reset one approved record's review deadline after a human confirmed it.

    This is the verb the freshness warning has always instructed ("Confirm,
    replace, or retire") without a command behind it: replacing is the
    correction path and retiring exists, but confirming -- the record is
    still true, keep it recalling -- required a full correction plan plus
    reapproval per record. Confirmation rewrites only revalidation metadata;
    the canonical payload digest deliberately excludes revalidation, so the
    record's identity, admission, and immutable review record are untouched.

    Refusals are fail-closed and mirror recall's own gates: an expired record
    is not resurrected here, a superseded one stays superseded, and a record
    whose cited source changed or became unreadable needs a correction --
    a new deadline would not make it eligible past the source gate anyway.
    A record with no deadline (declared durable) has nothing to confirm.
    """
    normalized_id = str(record_id).strip()
    if not _SAFE_REF.match(normalized_id):
        raise ValueError(f"unsafe memory record id: {record_id!r}")
    stale_after = str(stale_after or "").strip()
    if stale_after and stale_after_days is not None:
        raise ValueError("pass at most one of stale_after and stale_after_days")
    days = _validated_day_count(stale_after_days, field="stale_after_days")
    # The actor claim is bounded and redacted exactly like the attention
    # reason: operator prose must never become an unbounded stored field, and
    # a sensitive-looking value must degrade to `[redacted]` here rather than
    # fail the whole record write with an error naming a field the operator
    # cannot see.
    actor = _redact(str(confirmed_by or "operator"))[:_MEMORY_ATTENTION_REASON_LIMIT]
    stamp = _attention_stamp(now)
    moment = _parse_utc(stamp) or datetime.now(timezone.utc)
    # An absolute date confirms a record TO a date -- the shape a
    # contract-pinned deadline needs, which a day-count fallback would
    # silently push past the date it was pinned to.
    absolute_deadline = _absolute_deadline(stale_after, field="stale_after", now=moment)
    with file_lock(paths.memory_index_path, private=True):
        record, error = read_json_object_result(_memory_record_path(paths, normalized_id))
        if error:
            return _refused_confirmation(normalized_id, "record_unreadable")
        if not isinstance(record, dict) or str(record.get("record_id", "")) != normalized_id:
            return _refused_confirmation(normalized_id, "record_not_found")
        if record.get("schema_version") != PROJECT_MEMORY_RECORD_SCHEMA_VERSION:
            return _refused_confirmation(normalized_id, "unsupported_record_schema")
        if str(record.get("superseded_by", "") or ""):
            return _refused_confirmation(normalized_id, "superseded")
        staleness = _record_staleness(record, now=moment)
        state = str(staleness.get("state", ""))
        if state == "expired":
            # A question that stayed open past its ceiling died unanswered;
            # the refusal says so rather than calling it a fact that aged out.
            return _refused_confirmation(
                normalized_id,
                "unresolved_expired" if str(staleness.get("reason", "")) == "unresolved_expired" else "retention_expired",
            )
        if str(staleness.get("source_state", "")) in {"changed", "unreadable"}:
            return _refused_confirmation(normalized_id, "source_requires_correction")
        previous_due = str(staleness.get("review_due_at", "") or "")
        was_open = str(staleness.get("resolution", "")) == "open"
        if not previous_due and not was_open:
            return _refused_confirmation(normalized_id, "no_review_deadline")
        cadence_reset = False
        if absolute_deadline:
            new_deadline = absolute_deadline
            days = None
        elif not previous_due and days is None:
            # An open record with no deadline -- restored from the archive, or
            # written before open records always minted one -- can still be
            # answered "resolved"; that is the whole point of confirm on an
            # open record. Resolving mints no clock nobody asked for: the
            # record becomes an ordinary deadline-less record, and an
            # explicit --stale-after / --stale-after-days still sets one.
            new_deadline = ""
        else:
            if days is None:
                # No explicit cadence: honour the one stored on the record
                # (set at capture or by an earlier confirm), so `--all-due`
                # cannot silently pull a record confirmed at 180 days back
                # to the default -- then the policy's default cadence, then
                # the built-in 90 days. A record with no stored day count
                # (an absolute-date cadence, or a legacy record) falls back
                # to a relative cadence; `cadence_reset` says so out loud.
                stored_days = record.get("staleness", {}).get("stale_after_days") if isinstance(record.get("staleness"), dict) else None
                if isinstance(stored_days, int) and not isinstance(stored_days, bool) and stored_days > 0:
                    days = stored_days
                else:
                    days = _cadence_value(read_project_memory_policy(paths), "stale_after_days_default") or _REVIEW_DEFAULT_DAYS
                    cadence_reset = True
            new_deadline = _days_after(stamp, days)
        revalidation = record.get("revalidation") if isinstance(record.get("revalidation"), dict) else {}
        updated_revalidation = {
            **{key: value for key, value in revalidation.items() if key != "deadline"},
            **({"deadline": new_deadline} if new_deadline else {}),
            "confirmed_at": stamp,
            "confirmed_by": actor,
        }
        stored_staleness = record.get("staleness") if isinstance(record.get("staleness"), dict) else {}
        _write_project_memory_record(
            paths,
            {
                **record,
                "revalidation": updated_revalidation,
                "staleness": {
                    **_staleness_projection(updated_revalidation),
                    "stale_after_days": days,
                    # Confirming an open record IS the answer "resolved": the
                    # one of two writers (with correct) that may clear open.
                    **_resolved_staleness_fields(stored_staleness, resolved_at=stamp),
                },
                "updated_at": stamp,
            },
        )
        _write_memory_index_unlocked(paths)
    previous_deadline = _parse_utc(previous_due)
    shortened = previous_deadline is not None and (_parse_utc(new_deadline) or previous_deadline) < previous_deadline
    return {
        "schema_version": MEMORY_CONFIRMATION_SCHEMA_VERSION,
        "record_id": normalized_id,
        "applied": True,
        "reason_code": "confirmed",
        "was_stale": state == "stale",
        "was_open": was_open,
        "shortened": shortened,
        "cadence_reset": cadence_reset,
        "previous_review_due_at": previous_due,
        "review_due_at": new_deadline,
        "stale_after_days": days,
        "confirmed_at": stamp,
        "confirmed_by": actor,
        "redaction_policy": "metadata_only",
        "next_action": (
            (
                f"The record recalls normally until {new_deadline}; confirm, correct, or retire it again by then."
                if new_deadline
                else "The record carries no review deadline, so it recalls as a settled record until corrected or retired."
            )
            + (" It was marked unresolved; this confirmation resolved it, so it now reads as settled." if was_open else "")
            + (f" Note: this moved the deadline earlier than {previous_due}." if shortened else "")
            + (
                " Note: the record had no day-count cadence (an absolute or legacy deadline); this confirm"
                " re-anchored it to a relative cadence -- pass --stale-after DATE to pin a date instead."
                if cadence_reset
                else ""
            )
        ),
        "claim_boundary": _MEMORY_CONFIRMATION_CLAIM_BOUNDARY,
    }


def confirm_due_project_memory_records(
    paths: OmhPaths,
    *,
    confirmed_by: str = "operator",
    stale_after_days: int | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Confirm every approved record whose review deadline has passed.

    Default deadlines land 90 days after capture, so the store tends to go
    review-due all at once -- the operator who ignored it for a season faces
    dozens of one-by-one confirmations, which is how the warnings get ignored
    for another season. The batch confirms only records whose sole problem is
    the passed deadline: every record still goes through the single-record
    gates, so an expired, superseded, or source-changed record is reported as
    skipped with its refusal reason, never silently re-blessed.
    """
    # Validate the cadence before touching the store: an invalid value must
    # fail the same way on an empty store as on a full one, never depend on
    # whether a due record happened to exist.
    _validated_day_count(stale_after_days, field="stale_after_days")
    moment = _parse_utc(_attention_stamp(now)) or datetime.now(timezone.utc)
    due: list[str] = []
    expired_count = 0
    open_count = 0
    for record in _read_project_memory_records(paths):
        verdict = _record_staleness(record, now=moment)
        if verdict.get("reason") == "review_due":
            due.append(str(record.get("record_id", "")))
        elif verdict.get("state") == "expired":
            # Expired records never enter the batch -- their fix is retire,
            # not confirmation -- but a batch that stays silent about them
            # reads as "everything is handled" over a store that still holds
            # dead records. The count keeps the report honest.
            expired_count += 1
        elif verdict.get("state") == "open":
            # An open record past its deadline is a question, and a batch
            # re-bless must not answer questions nobody read: each one is
            # confirmed, kept open, or retired on its own. Counted, so the
            # batch cannot read as "everything is handled".
            open_count += 1
    due.sort()
    confirmed: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    for due_id in due:
        try:
            result = confirm_project_memory_record(
                paths,
                due_id,
                confirmed_by=confirmed_by,
                stale_after_days=stale_after_days,
                now=now,
            )
        except (OSError, ValueError) as exc:
            # A write-time rejection on one record must not abandon the batch
            # mid-flight: earlier records are already committed, so the report
            # -- who was confirmed, who was not, and why -- is the only
            # containment the batch can offer.
            skipped.append({"record_id": due_id, "reason_code": "write_rejected", "detail": str(exc)})
            continue
        if bool(result.get("applied")):
            confirmed.append({"record_id": due_id, "review_due_at": str(result.get("review_due_at", ""))})
        else:
            skipped.append(
                {
                    "record_id": due_id,
                    "reason_code": str(result.get("reason_code", "")),
                    "detail": str(result.get("detail", "")),
                }
            )
    next_action = (
        "Review the skipped records individually; each carries the refusal reason."
        if skipped
        else (
            "Every review-due record was confirmed; recall packs deliver them again."
            if confirmed
            else "No review-due record required confirmation."
        )
    )
    if expired_count:
        next_action += f" {expired_count} expired record(s) were not touched; expiry needs `omh memory retire`, not confirmation."
    if open_count:
        next_action += (
            f" {open_count} unresolved record(s) were not touched; an open question is answered one at a time"
            " (`omh memory confirm <id>` / `keep-open <id>` / `retire <id>`), never by a batch."
        )
    return {
        "schema_version": MEMORY_CONFIRMATION_BATCH_SCHEMA_VERSION,
        "due_count": len(due),
        "expired_count": expired_count,
        "open_count": open_count,
        "confirmed": confirmed,
        "skipped": skipped,
        "confirmed_count": len(confirmed),
        "skipped_count": len(skipped),
        "confirmed_by": _redact(str(confirmed_by or "operator"))[:_MEMORY_ATTENTION_REASON_LIMIT],
        "redaction_policy": "metadata_only",
        "next_action": next_action,
        "claim_boundary": _MEMORY_CONFIRMATION_CLAIM_BOUNDARY,
    }


def _refused_confirmation(record_id: str, reason_code: str) -> dict[str, object]:
    return {
        "schema_version": MEMORY_CONFIRMATION_SCHEMA_VERSION,
        "record_id": record_id,
        "applied": False,
        "reason_code": reason_code,
        "detail": _MEMORY_CONFIRMATION_REFUSAL_DETAIL[reason_code],
        "redaction_policy": "metadata_only",
        "next_action": f"Inspect the record with `omh memory inspect {record_id}`; nothing was changed.",
        "claim_boundary": _MEMORY_CONFIRMATION_CLAIM_BOUNDARY,
    }


def keep_memory_record_open(
    paths: OmhPaths,
    record_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """The "still open" answer to a reminder: reset the ask clock, touch nothing else.

    Three answers exist for an open record. `confirm` says it is resolved,
    `retire` drops it, and this one says the question is still open -- so the
    provider stops asking for another ``open_ask_days`` and the record stays
    exactly as it was: same state, same deadline, same ceiling. Only the
    local ask ledger is written. That is the boundary the reminder promises
    -- it can never promote or retire a record -- and keep-open is its
    mirror image on the answering side.

    Refusals fail closed and name why: a record that is not open has no
    clock to reset, and a question that already died past its ceiling
    cannot be kept open; it needs `omh memory retire`.
    """
    normalized_id = str(record_id).strip()
    if not _SAFE_REF.match(normalized_id):
        raise ValueError(f"unsafe memory record id: {record_id!r}")
    stamp = _attention_stamp(now)
    moment = _parse_utc(stamp) or datetime.now(timezone.utc)
    record, error = read_json_object_result(_memory_record_path(paths, normalized_id))
    if error:
        return _refused_keep_open(normalized_id, "record_unreadable")
    if not isinstance(record, dict) or str(record.get("record_id", "")) != normalized_id:
        return _refused_keep_open(normalized_id, "record_not_found")
    if record.get("schema_version") not in {PROJECT_MEMORY_RECORD_SCHEMA_VERSION, PRINCIPAL_PROJECT_MEMORY_RECORD_SCHEMA_VERSION}:
        return _refused_keep_open(normalized_id, "unsupported_record_schema")
    staleness = record.get("staleness") if isinstance(record.get("staleness"), dict) else {}
    if _record_resolution(staleness) != "open":
        return _refused_keep_open(normalized_id, "not_open")
    verdict = _record_staleness(record, now=moment)
    if str(verdict.get("reason", "")) == "unresolved_expired":
        return _refused_keep_open(normalized_id, "unresolved_expired")
    entry = _mark_open_reminder_asked(paths.omh_home, normalized_id, asked_at=stamp)
    ask_days = _cadence_value(read_project_memory_policy(paths), "open_ask_days") or _OPEN_ASK_DAYS
    next_ask = _days_after(stamp, ask_days)
    return {
        "schema_version": MEMORY_KEEP_OPEN_SCHEMA_VERSION,
        "record_id": normalized_id,
        "applied": True,
        "reason_code": "kept_open",
        "state": str(verdict.get("state", "")),
        "open_days": int(verdict.get("open_days", 0) or 0),
        "open_since": str(staleness.get("open_since", "") or ""),
        "open_expires_at": str(staleness.get("open_expires_at", "") or ""),
        "review_due_at": str(verdict.get("review_due_at", "") or ""),
        "asked_at": stamp,
        "asked_count": int(entry.get("asked_count", 0) or 0),
        "next_ask_after": next_ask,
        "redaction_policy": "metadata_only",
        "next_action": (
            f"The record stays open and delivered as unresolved; OMH will not ask about it again before {next_ask}. "
            "Answer it for good with `omh memory confirm <record-id>` (resolved) or `omh memory retire <record-id>` (drop it)."
        ),
        "claim_boundary": _MEMORY_KEEP_OPEN_CLAIM_BOUNDARY,
    }


def _refused_keep_open(record_id: str, reason_code: str) -> dict[str, object]:
    return {
        "schema_version": MEMORY_KEEP_OPEN_SCHEMA_VERSION,
        "record_id": record_id,
        "applied": False,
        "reason_code": reason_code,
        "detail": _MEMORY_KEEP_OPEN_REFUSAL_DETAIL[reason_code],
        "redaction_policy": "metadata_only",
        "next_action": f"Inspect the record with `omh memory inspect {record_id}`; nothing was changed.",
        "claim_boundary": _MEMORY_KEEP_OPEN_CLAIM_BOUNDARY,
    }


def _handoff_perspective_lens(executor_target: str | None) -> str:
    """Lens every handoff surface applies: scoped records reach only the
    executor they are about. An unresolved target ('' or 'choose') stays a
    lens that matches no scoped record: until an executor is actually
    selected, a handoff carries unscoped records only, never a leak of some
    other actor's lessons."""
    return str(executor_target or "").strip().lower() or "choose"


def build_memory_perspectives(paths: OmhPaths) -> dict[str, object]:
    """Deterministic inventory of (observer, observed) pairs -- honcho's
    collections listing reinterpreted as a report over the records store."""
    pairs: dict[tuple[str, str], int] = {}
    unscoped = 0
    for record in _read_project_memory_records(paths):
        perspective = record.get("perspective")
        if isinstance(perspective, dict) and str(perspective.get("observed", "")):
            key = (
                _redacted_metadata_label(perspective.get("observer", "")),
                _redacted_metadata_label(perspective.get("observed", "")),
            )
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


def build_memory_lineage(paths: OmhPaths, record_id: str, *, depth: int = 3) -> dict[str, object]:
    """Trace derived-from links up (ancestors) and down (descendants).

    Report-only graph traversal over the active records directory: archived
    or pruned records surface as unresolved refs rather than errors, cycles
    are cut by the visited set, and depth is capped so a pathological chain
    cannot make the report unbounded.
    """
    depth = max(1, min(int(depth), _LINEAGE_MAX_DEPTH))
    # The same advance-notice window recall uses, so lineage and recall never
    # disagree about whether one record is due soon.
    window = _cadence_value(read_project_memory_policy(paths), "due_soon_days")
    records = {
        str(record.get("record_id", "")): record
        for record in _read_project_memory_records(paths)
        if str(record.get("record_id", ""))
    }
    base = {
        "schema_version": MEMORY_LINEAGE_SCHEMA_VERSION,
        "record_id": _redacted_metadata_label(record_id),
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
                        unresolved.append(
                            {
                                "record_id": _redacted_metadata_label(ref),
                                "referenced_by": _redacted_metadata_label(node_id),
                            }
                        )
                    continue
                visited.add(ref)
                ancestors.append(_lineage_card(records[ref], depth=hop, due_soon_days=window))
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
                descendants.append(_lineage_card(records[child_id], depth=hop, due_soon_days=window))
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
        "record": _lineage_card(root, depth=0, due_soon_days=window),
        "ancestors": ancestors,
        "descendants": descendants,
        "unresolved_refs": unresolved,
        "truncated": truncated,
        "counts": {"ancestors": len(ancestors), "descendants": len(descendants), "unresolved": len(unresolved)},
    }


def _lineage_card(record: dict[str, Any], *, depth: int, due_soon_days: int | None = None) -> dict[str, object]:
    return {
        "record_id": _redacted_metadata_label(record.get("record_id", "")),
        "depth": depth,
        "record_type": _redact_admitted_text(str(record.get("record_type", ""))),
        "summary": _redact_admitted_text(str(record.get("summary", "")))[:500],
        "scope": _redacted_scope(record.get("scope", _scope("project", "default"))),
        "tags": _normalize_tags(record.get("tags", [])),
        "approved_at": _redact_admitted_text(str(record.get("approved_at", ""))),
        "staleness": _redact_nested_metadata(_record_staleness(record, due_soon_days=due_soon_days)),
        "derived_from": [
            _redacted_metadata_label(ref) for ref in _string_list(record.get("derived_from", []))
        ],
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


def _append_retirement_journal(
    paths: OmhPaths, record_id: str, retired_at: str, expires_at: str, *, reason: str = ""
) -> dict[str, object]:
    entry = {
        "schema_version": RETIREMENT_JOURNAL_SCHEMA_VERSION,
        "record_id": record_id,
        "retired_at": retired_at,
        "expires_at": expires_at,
        # Why it was archived: a fact that aged out (`retention_expired`), a
        # question that died unanswered (`unresolved_expired`), or a question
        # the operator dropped on purpose (`unresolved_dropped`).
        **({"reason": reason} if reason else {}),
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
        if (
            not record_id
            or retired_at is None
            or not _SAFE_REF.match(record_id)
            or contains_credential_like_material(record_id)
        ):
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
    record_id: str | None = None,
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
        report = build_memory_retirement(paths, now=now, window_days=window_days, record_id=record_id)
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
            _append_retirement_journal(paths, str(row["record_id"]), retired_at, str(row["expires_at"]), reason=str(row.get("reason", "")))
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
    record_id: str | None = None,
) -> dict[str, object]:
    """Which approved records are past or near their deadline. Report only.

    Scans the records directory directly rather than through
    ``_read_project_memory_records`` because that reader raises on the first
    corrupt file -- and corrupt files are exactly what accumulates in a store
    nothing ever cleans. Here one unreadable file costs one ``skipped`` row,
    never the run.

    Fail-closed: only canonical records (right schema, approved, safe
    ``record_id`` matching the filename) are classified, and only two
    verdicts can nominate a move: the classifier's ``expired`` (reason
    ``retention_expired``) and the freshness verdict's ``unresolved_expired``
    -- an open record that stayed open past ``open_max_days``, named as a
    question that died unanswered rather than a fact that aged out. A
    missing or empty TTL is a healthy record that never expires; a
    present-but-unreadable one is surfaced as ``malformed_expires_at`` and
    left alone.

    With ``record_id`` the scan narrows to that one record and gains the
    third answer to a reminder: an open record that is not yet expired is
    nominated as ``unresolved_dropped`` -- the operator chose to drop the
    question -- while a settled, unexpired record is refused as
    ``not_expired``; retire never quietly archives a live fact.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    target = str(record_id or "").strip()
    if target and (not _SAFE_REF.match(target) or contains_credential_like_material(target)):
        raise ValueError(f"unsafe memory record id: {record_id!r}")
    records_dir = _memory_records_dir(paths)
    recall_usage = read_recall_usage(paths)
    pinned_ids = set(read_memory_pins(paths))
    expired: list[dict[str, object]] = []
    expiring_soon: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    candidates = sorted(records_dir.glob("*.json")) if records_dir.exists() else []
    if target:
        candidates = [path for path in candidates if path.name == f"{target}.json"]
        if not candidates:
            skipped.append({"path_name": f"{target}.json", "reason": "record_not_found"})
    for path in candidates:
        safe_path_name = _redacted_metadata_label(path.name)
        if path.is_symlink() or not path.is_file():
            skipped.append({"path_name": safe_path_name, "reason": "symlink_or_not_file"})
            continue
        data, _error = read_json_object_result(path)
        if data is None:
            skipped.append({"path_name": safe_path_name, "reason": "corrupt_json"})
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
            skipped.append({"path_name": safe_path_name, "reason": "not_canonical"})
            continue
        record_id = str(data.get("record_id", ""))
        if not _SAFE_REF.match(record_id) or record_id != path.stem or contains_credential_like_material(record_id):
            skipped.append({"path_name": safe_path_name, "reason": "unsafe_record_id"})
            continue
        state = _classify_record_expiry(data, now=now, window_days=window_days)
        ttl = data.get("ttl", {}) if isinstance(data.get("ttl"), dict) else {}
        staleness = data.get("staleness", {}) if isinstance(data.get("staleness"), dict) else {}
        verdict = _record_staleness(data, now=now)
        row = {
            "record_id": record_id,
            "expires_at": str(ttl.get("expires_at", "") or ""),
            "path_name": safe_path_name,
            # Delivery-usage annotation only: a never-delivered record is a
            # cheaper retire call than one executors keep receiving. A pin
            # likewise annotates, never blocks: expiry still wins.
            "recall_usage": recall_usage.get(record_id, {"times_recalled": 0, "last_recalled_at": ""}),
            "pinned": record_id in pinned_ids,
        }
        if state == "expired":
            expired.append({**row, "reason": "retention_expired"})
        elif str(verdict.get("reason", "")) == "unresolved_expired":
            expired.append({**row, "expires_at": str(staleness.get("open_expires_at", "") or ""), "reason": "unresolved_expired"})
        elif target and str(verdict.get("resolution", "")) == "open":
            expired.append({**row, "expires_at": str(staleness.get("open_expires_at", "") or ""), "reason": "unresolved_dropped"})
        elif target and state != "malformed":
            skipped.append({"path_name": safe_path_name, "reason": "not_expired"})
        elif state == "expiring":
            expiring_soon.append(row)
        elif state == "malformed":
            skipped.append({"path_name": safe_path_name, "reason": "malformed_expires_at"})
    return {
        "schema_version": RETIREMENT_REPORT_SCHEMA_VERSION,
        "applied": False,
        "window_days": window_days,
        "target_record_id": target,
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
    pack_scope = _handoff_pack_scope(paths, scope_kind=scope_kind, scope_ref=scope_ref)
    if pack_scope["kind"] == "unresolved":
        inspection = {"snapshots": [], "conflicts": []}
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
                artifact_scope = artifact.get("scope")
                if isinstance(artifact_scope, dict) and artifact_scope.get("kind") == "project" and artifact_scope != pack_scope:
                    # A record or legacy scope item under another project scope
                    # -- including the unbound `project/default` label once this
                    # home's identity has resolved -- is listed, like the thread
                    # case below, because this surface enumerates its exclusions.
                    excluded.append({"item_id": item_id, "source": source, "reason": "scope_mismatch"})
                    continue
                if (
                    isinstance(artifact_scope, dict)
                    and artifact_scope.get("kind") == "thread"
                    and artifact_scope != pack_scope
                    and str(artifact_scope.get("ref", "")) != str(session_id or "")
                ):
                    # The recall pack's rule: a thread record travels with its
                    # own session only. Listed by record id rather than skipped,
                    # like the perspective exclusion below, because this surface
                    # enumerates its exclusions. (An empty ref would equal an
                    # empty session here; the evaluator below refuses such a
                    # record as `scope_invalid` before it can be included.)
                    excluded.append({"item_id": item_id, "source": source, "reason": "scope_mismatch"})
                    continue
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
                    "scope": item.get("scope", snapshot.get("scope", pack_scope)) if source == "omh_memory" else pack_scope,
                }
                if evaluation:
                    context_item["replay_evaluation"] = evaluation
                included.append(context_item)
            else:
                excluded.append({"item_id": item_id, "source": source, "reason": "not_packable"})

    # Reviewed domain profiles share the existing OMH-memory handoff lane, but
    # are resolved directly from their own validated store rather than trusted
    # from a caller-supplied inspection snapshot.
    if pack_scope["kind"] == "project":
        from .domain_handoff_projection import build_domain_handoff_projection

        domain_included, domain_excluded = build_domain_handoff_projection(paths)
        if scope_ref:
            domain_included = [
                item
                for item in domain_included
                if isinstance(item.get("scope"), dict) and item["scope"].get("ref") == scope_ref
            ]
            if not domain_included:
                domain_excluded = []
        included.extend(domain_included)
        excluded.extend(domain_excluded)

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
    pack = {
        "schema_version": HANDOFF_CONTEXT_PACK_SCHEMA_VERSION,
        "executor_target": executor_target,
        "session_id": session_id,
        "scope": pack_scope,
        "source_refs": _source_refs(inspection),
        **({"metadata": {"scope_status": "scope_unresolved"}} if pack_scope["kind"] == "unresolved" else {}),
        "included_context": kept,
        "excluded_context": excluded,
        "blocked_by_conflicts": blocking_conflicts,
        "redaction_policy": "metadata_only",
        "claim_boundary": "Context packs contain evaluator-approved summaries only; they are prepared context, not observed executor or model use.",
    }
    errors = validate_handoff_context_pack(pack, require_conflict_free=False)
    if errors:
        raise ValueError("; ".join(errors))
    return pack


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
    included_context = value.get("included_context")
    _validate_context_list(included_context, _HANDOFF_CONTEXT_INCLUDED_KEYS, errors, f"{label}.included_context", scope_key="scope")
    _validate_handoff_item_scopes(value.get("scope"), included_context, errors, label)
    _validate_domain_handoff_items(included_context, errors, f"{label}.included_context")
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
    # Optional for the same reason as freshness warnings: a pack written before
    # attention tiers existed still validates, and a present block is held to
    # the full scalar-only shape.
    if "attention" in value:
        _validate_context_map(value.get("attention"), _RECALL_ATTENTION_KEYS, errors, f"{label}.attention")
    # Present only when the active-tier fallback served the pack.
    if "query_fallback" in value:
        _validate_context_map(value.get("query_fallback"), _RECALL_QUERY_FALLBACK_KEYS, errors, f"{label}.query_fallback")
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


def _resolved_staleness_fields(staleness: dict[str, Any], *, resolved_at: str) -> dict[str, object]:
    """Carry an open/resolved marker through a rewrite, answering an open one.

    Confirm and correct are the only two writers of ``resolved``. The
    ceiling is dropped with the answer -- a resolved record is an ordinary
    fact again, bounded by its review deadline and TTL like any other -- and
    ``open_since`` stays as the record of how long the question was open.
    """
    resolution = _record_resolution(staleness)
    if not resolution:
        return {}
    fields: dict[str, object] = {"resolution": "resolved", "open_since": str(staleness.get("open_since", "") or "")}
    fields["resolved_at"] = str(resolved_at) if resolution == "open" else str(staleness.get("resolved_at", "") or resolved_at)
    return fields


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
    return _shared_evaluate_memory_artifact(
        artifact,
        operation_states=_recall_operation_states(paths, [artifact]) if paths is not None else None,
        now=now,
        requested_scope=requested_scope,
        review_resolver=review_resolver,
        conflict_ids=conflict_ids,
        stale_override=stale_override,
        run_id=run_id,
    )


# A whole two-character word, never a fragment of a longer one: the lookarounds
# keep "ru" out of "runs" while letting "ci" out of "ci failures".
# The length floor was doing two jobs: keeping English function words out of the
# index, and -- as a side effect nobody chose -- keeping every two-letter
# technical term out with them. Only the first job is wanted, so it is done by
# naming the function words rather than by measuring length.
#
# The list is deliberately short and holds only words that are never a subject.
# `go`, `id`, `db`, `ci`, `ui`, `qa`, `ml`, `pr`, `js`, `ts`, `vm`, `s3`, `k8`,
# `ai`, `ux`, and `vs` are all real terms in some project and stay indexable: a
# stopword that costs a real search is worse than the noise it removes.


def _record_scope_matches(record: dict[str, Any], *, scope_kind: str | None, scope_ref: str | None) -> bool:
    scope = _normalize_scope(record.get("scope", _scope("project", "default")))
    return (not scope_kind or scope["kind"] == scope_kind) and (not scope_ref or scope["ref"] == scope_ref)


def _looks_like_raw_log(value: str) -> bool:
    lowered = value.lower()
    markers = ("traceback (most recent call last)", "\nstderr", "\nstdout", "[error]", "exception:", "raw log", "full log")
    timestamp_lines = len(re.findall(r"^\d{4}-\d{2}-\d{2}[ t]\d{2}:\d{2}:\d{2}", value, flags=re.MULTILINE))
    return any(marker in lowered for marker in markers) or timestamp_lines >= 3


def _looks_like_full_transcript(value: str) -> bool:
    lowered = value.lower()
    speaker_lines = len(re.findall(r"^(user|assistant|system|developer|human|agent):", value, flags=re.IGNORECASE | re.MULTILINE))
    return "full transcript" in lowered or "chat transcript" in lowered or speaker_lines >= 4


# The longest deadline a retention policy can express. Past this the value is a
# typo rather than an intent, and `created_at + timedelta(days=N)` starts
# raising OverflowError out of `_days_after` -- which reached the CLI as a raw
# Python traceback instead of an `omh:` error.

# The three memory clocks, as product tunables rather than constants baked
# into one machine's build: the default review cadence, the episode TTL, and
# the advance-notice window recall packs warn inside (shared by review-due
# and expiry notices). Stored setup profiles may carry them inside
# `memory_policy` -- additive and optional, exactly like the rest of that
# block -- and an absent or invalid value falls back to the named default
# while the effective value is always disclosed on the policy payload.


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
    # An explicit request for the scope this home resolves to is the default
    # pack under its own name, so it is not filtered at all: the setup,
    # runtime-state and catalog-hint snapshots are labelled project/default,
    # the wrapper-session and target snapshots carry their own scopes, and the
    # conflicts `_detect_conflicts` finds between them need every one present
    # (#2016). Another identity keeps only the records captured under it.
    if scope_kind and scope_ref and _handoff_pack_scope(paths, scope_kind=None, scope_ref=None) == _scope(str(scope_kind), str(scope_ref)):
        scope_kind = scope_ref = None
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

    This is a read-only projection: reviewed records plus the scope items that
    ``batch-apply`` and ``reactivate`` write. The snapshot surfaces have no
    write path of their own; legacy v1 scope items appear here as
    ``review_required_legacy`` until ``omh memory reactivate`` migrates them.

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
        if _scope_requested(scope, scope_kind=scope_kind, scope_ref=scope_ref):
            filtered.append(snapshot)
            continue
        # The reviewed-records snapshot is labelled project/default while each
        # item carries the scope its record was captured under, so a pack asked
        # for one thread or one project identity matched no label and came
        # back empty. An item that carries a scope is matched on that scope.
        items = [
            item
            for item in (snapshot.get("items", []) if isinstance(snapshot.get("items"), list) else [])
            if isinstance(item, dict)
            and isinstance(item.get("scope"), dict)
            and _scope_requested(_normalize_scope(item["scope"]), scope_kind=scope_kind, scope_ref=scope_ref)
        ]
        if items:
            filtered.append({**snapshot, "items": items})
    return filtered


def _scope_requested(scope: dict[str, str], *, scope_kind: str | None, scope_ref: str | None) -> bool:
    kind_matches = not scope_kind or scope["kind"] == scope_kind
    ref_matches = not scope_ref or scope["ref"] == scope_ref
    return kind_matches and ref_matches


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
    scope = _redacted_scope(snapshot.get("scope", _scope("project", "default")))
    items = [_sanitize_item(item, default_scope=scope) for item in snapshot.get("items", []) if isinstance(item, dict)]
    return _snapshot(
        source,
        scope,
        items,
        claim_boundary=_redact_admitted_text(
            str(snapshot.get("claim_boundary", "Wrapper supplied memory candidates are not trusted until reviewed."))
        ),
    )


def _snapshot(source: str, scope: Any, items: list[dict[str, object]], *, claim_boundary: str = "") -> dict[str, object]:
    normalized_scope = _redacted_scope(scope)
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
    item_id = _redact_admitted_text(str(item.get("item_id") or _stable_ref(item.get("key", "item"))))
    key = _redact_admitted_text(str(item.get("key", item_id)))
    summary = _safe_summary(item)
    sanitized: dict[str, object] = {
        "item_id": item_id,
        "key": key,
        "summary": summary,
        "scope": _redacted_scope(item.get("scope", default_scope)),
        "sensitive": bool(item.get("sensitive", False)),
    }
    value = item.get("value")
    if _safe_to_expose_value(key, value, item):
        sanitized["value"] = str(value)
    replay_evaluation = item.get("replay_evaluation")
    if isinstance(replay_evaluation, dict):
        sanitized["replay_evaluation"] = _redact_nested_metadata(replay_evaluation)
    return sanitized


def _safe_summary(item: dict[str, Any]) -> str:
    summary = str(item.get("summary", ""))
    if summary:
        return _redact_admitted_text(summary)
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
    if contains_credential_like_material(text):
        return False
    return len(text) <= 240


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


def _validate_handoff_item_scopes(pack_scope: Any, value: Any, errors: list[str], label: str) -> None:
    if not isinstance(pack_scope, dict) or not isinstance(value, list):
        return
    expected = {"kind": pack_scope.get("kind"), "ref": pack_scope.get("ref")}
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        if item.get("source") != "omh_memory" and item.get("source_kind") != "domain_intelligence_profile":
            continue
        item_scope = item.get("scope")
        actual = (
            {"kind": item_scope.get("kind"), "ref": item_scope.get("ref")}
            if isinstance(item_scope, dict)
            else None
        )
        # Target/thread/run memory remains task-local context inside a project
        # handoff. The isolation boundary here is repository identity: every
        # project-scoped reviewed item must name the same repository as the
        # pack, and a domain profile is always project-scoped.
        project_scoped = bool(actual and actual.get("kind") == "project")
        if (item.get("source_kind") == "domain_intelligence_profile" or project_scoped) and actual != expected:
            errors.append(f"{label}.included_context[{index}].scope must match {label}.scope")


def _validate_domain_handoff_items(value: Any, errors: list[str], label: str) -> None:
    if not isinstance(value, list):
        return
    domain_fields = {
        "source_kind",
        "profile_id",
        "profile_revision",
        "profile_digest",
        "review_id",
    }
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        item_label = f"{label}[{index}]"
        present = domain_fields & set(item)
        if not present:
            continue
        if item.get("source_kind") != "domain_intelligence_profile" or present != domain_fields:
            errors.append(f"{item_label} must carry the complete domain profile projection")
            continue
        if item.get("source") != "omh_memory" or item.get("truth_level") != "approved_context":
            errors.append(f"{item_label} domain profile must be approved omh_memory context")
        for key in ("profile_id", "review_id"):
            if not isinstance(item.get(key), str) or not item.get(key):
                errors.append(f"{item_label}.{key} must be a non-empty string")
        revision = item.get("profile_revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            errors.append(f"{item_label}.profile_revision must be a positive integer")
        digest = item.get("profile_digest")
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            errors.append(f"{item_label}.profile_digest must be a lowercase sha256 hex digest")
        evaluation = item.get("replay_evaluation")
        if not isinstance(evaluation, dict) or evaluation.get("eligible") is not True or evaluation.get("reason_code") != "eligible":
            errors.append(f"{item_label}.replay_evaluation must mark the reviewed profile eligible")


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


def _handoff_pack_scope(paths: OmhPaths, *, scope_kind: str | None, scope_ref: str | None) -> dict[str, str]:
    if bool(scope_kind) != bool(scope_ref):
        raise ValueError("handoff context scope_kind and scope_ref must be supplied together")
    if scope_kind and scope_ref:
        return _scope(str(scope_kind), str(scope_ref))
    project_root = paths.omh_home.parent
    resolution = resolve_project_identity(project_root)
    return _scope("project", resolution.identity) if resolution.state == "resolved" else _scope("unresolved", "scope_unresolved")


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
