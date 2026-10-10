"""Memory admission: the one path from a stated fact to a replay-ready record.

Capture, the confinement-scoped duplicate check, the candidate write, auto-safe
approval and the durability receipt live here, once. Two callers reach it:
the ``omh_memory`` tool calls it in-process from a Hermes session, and the
``omh memory`` CLI reaches it through the adapters in ``omh.workflows.memory``,
which resolve ``OmhPaths`` and pass ``omh_home``. Before this module the tool
spawned the installed ``omh`` console script for every capture, because the
path was too large to vendor -- so a session whose ``omh`` was missing, older,
or off PATH could not remember anything, and the result it reported was a
parse of another process's stdout.

The control plane passes its own ``file_lock`` and ``utc_now`` through
``lock`` and ``clock`` so its existing seams keep holding; both locks take the
same OS lock on the same ``.<name>.lock`` sidecar, so a CLI and a plugin
session against one home exclude each other. Stdlib only; no import of the
``omh`` control plane.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
import unicodedata

from .hermes_memory import classify_record_expiry as _classify_record_expiry
from .memory_governance import (
    ADMISSION_STATES,
    MEMORY_GOVERNANCE_POLICY_VERSION,
    PRINCIPAL_PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
    PRINCIPAL_PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION,
    PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION,
    build_retention,
    canonical_payload_digest,
    classify_memory_admission,
    contains_credential_like_material,
    evaluate_renderable_strings,
    stable_artifact_identity,
)
from .memory_principals import build_memory_identity, parse_principal_context
from .memory_recall_selector import _evaluate_memory_artifact as _shared_evaluate_memory_artifact
from .memory_recall_support import (
    DEFAULT_MEMORY_ATTENTION_TIER,
    MAX_RETENTION_DAYS,
    PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
    _DEFAULT_PERSPECTIVE_OBSERVER,
    _EPISODE_DEFAULT_TTL_DAYS,
    _MEMORY_CADENCE_DEFAULTS,
    _OPEN_MAX_DAYS,
    _REVIEW_DEFAULT_DAYS,
    _cadence_value,
    _local_source_digest,
    _normalize_scope,
    _normalize_tags,
    _parse_utc,
    _parse_utc_naive_as_utc,
    _perspective_projection,
    _record_resolution,
    _redact_admitted_text,
    _redact_nested_metadata,
    _redacted_metadata_label,
    _scope,
    _string_list,
    normalized_summary_key,
)
from .memory_store_io import (
    _SAFE_REF,
    Clock,
    StoreLock,
    memory_capture_lock_path,
    memory_dir,
    memory_index_path,
    memory_record_path,
    memory_records_dir,
    memory_store_lock,
    project_memory_review_resolver,
    read_json_object,
    read_json_object_result,
    read_project_memory_candidate,
    read_project_memory_records,
    recall_operation_states,
    utc_now,
    write_memory_index,
    write_memory_index_unlocked,
    write_project_memory_candidate_unlocked,
    write_project_memory_record,
    write_project_memory_review_decision,
)
from .project_identity import require_project_identity

PROJECT_MEMORY_POLICY_SCHEMA_VERSION = "project_memory_policy/v1"
PROJECT_MEMORY_CAPTURE_SCHEMA_VERSION = "project_memory_capture/v1"
PROJECT_MEMORY_CANDIDATE_SCHEMA_VERSION = "project_memory_candidate/v1"
PROJECT_MEMORY_REVIEW_CARD_SCHEMA_VERSION = "project_memory_review_card/v1"
MEMORY_ATTENTION_SCHEMA_VERSION = "omh_memory_attention/v1"
ALLOWED_SCOPE_KINDS = {"user-global", "user", "project", "target", "thread", "run"}
PROJECT_MEMORY_MODES = ("off", "review-first", "auto-safe")
# The mode a profile gets when nobody chose one. Auto-safe because the model
# captures through `omh_memory(action="capture")` with no operator in the loop;
# under review-first every capture would wait on an approval nobody runs.
PROJECT_MEMORY_DEFAULT_MODE = "auto-safe"
# Where the effective mode came from, disclosed on the policy payload:
# `explicit` (setup --memory-mode wrote it), `legacy_explicit` (a profile
# written before `mode_source` existed whose stored mode differs from the old
# review-first default, so an operator must have chosen it), `default`, and
# `capability_policy` (the retain_knowledge family is disabled).
PROJECT_MEMORY_MODE_SOURCES = ("explicit", "legacy_explicit", "default", "capability_policy")
_LEGACY_DEFAULT_MEMORY_MODE = "review-first"
PROJECT_MEMORY_RECORD_TYPES = ("fact", "decision", "lesson", "procedure", "episode")
# `candidate` keeps a duplicate as a pending candidate stamped duplicate_of;
# `skip` persists nothing and names the existing record instead.
CAPTURE_ON_DUPLICATE_CHOICES = ("candidate", "skip")
_MEMORY_ATTENTION_REASON_LIMIT = 240
_DERIVED_FROM_LIMIT = 8


def build_project_memory_policy(omh_home: Path, *, mode: str | None = None, mode_source: str = "default") -> dict[str, object]:
    normalized = _normalize_memory_mode(mode)
    return {
        "schema_version": PROJECT_MEMORY_POLICY_SCHEMA_VERSION,
        "mode": normalized,
        "mode_source": mode_source if mode_source in PROJECT_MEMORY_MODE_SOURCES else "default",
        "capture_enabled": normalized != "off",
        "recall_enabled": normalized != "off",
        "review_required": normalized == "review-first",
        "auto_approve_safe": normalized == "auto-safe",
        "store_scope": "project_local",
        "store_dir": str(memory_dir(omh_home)),
        "redaction_policy": "metadata_only",
        "backend": "local_json",
        "optional_backend_extension": True,
        **dict(_MEMORY_CADENCE_DEFAULTS),
        "claim_boundary": "Project memory configures OMH-local prepared context only; it does not mutate Hermes global or internal memory.",
    }


def _policy_cadence_overrides(stored_policy: dict[str, object]) -> dict[str, int]:
    """Validated cadence overrides from a stored profile's memory_policy."""
    overrides: dict[str, int] = {}
    for key in _MEMORY_CADENCE_DEFAULTS:
        value = _cadence_value(stored_policy, key)
        if value is not None:
            overrides[key] = value
    return overrides


def read_project_memory_policy(omh_home: Path) -> dict[str, object]:
    """The effective policy from ``<omh_home>/setup-profile.json``.

    Resolved here rather than in the control plane so the tool and the CLI
    read one policy the same way; a profile that is not valid JSON raises,
    exactly as the control plane's setup-profile reader does.
    """
    setup = read_json_object(Path(omh_home) / "setup-profile.json")
    if not isinstance(setup, dict):
        return build_project_memory_policy(omh_home)
    if not _retain_knowledge_family_enabled(setup):
        # Disabling the `retain_knowledge` capability family has to actually
        # stop memory, not merely stop advertising it. Resolving to mode "off"
        # here reuses the capture gate in `record_project_memory` and the
        # recall gate's empty pack, so there is one disabled path rather than a
        # second one that could drift from it.
        return build_project_memory_policy(omh_home, mode="off", mode_source="capability_policy")
    policy = setup.get("memory_policy")
    if isinstance(policy, dict):
        mode, source = _stored_memory_mode(str(policy.get("mode", "") or ""), str(policy.get("mode_source", "") or ""))
        base = build_project_memory_policy(omh_home, mode=mode, mode_source=source)
        return {**base, **_policy_cadence_overrides(policy)}
    mode, source = _stored_memory_mode(str(setup.get("memory_mode", "") or ""), "")
    return build_project_memory_policy(omh_home, mode=mode, mode_source=source)


def _stored_memory_mode(stored_mode: str, stored_source: str) -> tuple[str | None, str]:
    """The mode a stored profile actually chose, or None for the current default.

    A profile written before `mode_source` existed stored the old review-first
    default whether or not anyone chose it, so that value is read as defaulted
    and follows the current default without a re-setup. Any other stored mode
    could only have come from an operator's `--memory-mode`, so it is kept.
    """
    if not stored_mode:
        return None, "default"
    if stored_source == "explicit":
        return stored_mode, "explicit"
    if stored_source or stored_mode == _LEGACY_DEFAULT_MEMORY_MODE:
        return None, "default"
    return stored_mode, "legacy_explicit"


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


def capture_project_memory_candidate(
    omh_home: Path,
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
    clock: Clock = utc_now,
    lock: StoreLock = memory_store_lock,
) -> dict[str, object]:
    omh_home = Path(omh_home)
    if on_duplicate not in CAPTURE_ON_DUPLICATE_CHOICES:
        raise ValueError(f"unsupported on_duplicate: {on_duplicate}; expected one of {', '.join(CAPTURE_ON_DUPLICATE_CHOICES)}")
    policy = read_project_memory_policy(omh_home)
    if not bool(policy.get("capture_enabled", True)):
        return {
            "schema_version": PROJECT_MEMORY_CAPTURE_SCHEMA_VERSION,
            "captured": False,
            "auto_approved": False,
            "policy": policy,
            "reason": "project_memory_disabled",
            "claim_boundary": "Memory capture is disabled by OMH project policy; Hermes global or internal memory is not mutated.",
        }
    # Structural metadata cannot be safely replaced with a redaction marker:
    # scope and lineage values participate in lookup semantics, while actor
    # labels participate in perspective filtering. Reject protected shapes
    # before normalizers can lowercase them or include them in an exception.
    structural_values = [
        str(record_type or ""),
        str(scope_kind or ""),
        str(scope_ref or ""),
        str(retention_class or ""),
        str(stale_after or ""),
        str(expires_at or ""),
        str(observer or ""),
        str(observed or ""),
    ]
    if isinstance(derived_from, (list, tuple)):
        structural_values.extend(str(ref) for ref in derived_from)
    elif derived_from is not None:
        structural_values.append(str(derived_from))
    structural_safety = _project_memory_safety(
        "",
        "",
        tags=[],
        source="",
        source_ref="\n".join(structural_values),
    )
    if structural_safety["status"] != "safe":
        return {
            "schema_version": PROJECT_MEMORY_CAPTURE_SCHEMA_VERSION,
            "captured": False,
            "auto_approved": False,
            "policy": policy,
            "reason": "unsafe_project_memory_metadata",
            "safety": structural_safety,
            "redaction_policy": "metadata_only",
            "claim_boundary": "Credential-like structural metadata is rejected before project-memory persistence.",
        }
    # Absolute deadlines: "the contract ends on the 18th" is a date, not a
    # day count, and forcing the captor to do the subtraction moved the
    # anchor to whenever they happened to run the command. Each absolute
    # form is mutually exclusive with its day-count twin. The class gates
    # live HERE, not only in argparse: this function is the plugin-bundle
    # and wrapper-facing API, and a guard that lives only at the CLI is the
    # exact failure mode `_validated_day_count` already documents -- which
    # is how a durable candidate once reached approval carrying a TTL.
    stale_after = str(stale_after or "").strip()
    expires_at = str(expires_at or "").strip()
    if stale_after and stale_after_days is not None:
        raise ValueError("pass at most one of stale_after and stale_after_days")
    if expires_at and ttl_days is not None:
        raise ValueError("pass at most one of expires_at and ttl_days")
    if retention_class == "volatile" and (stale_after or expires_at):
        raise ValueError("volatile memory keeps its 1-7 day TTL; absolute deadlines do not apply")
    if retention_class == "volatile" and stale_after_days is not None:
        raise ValueError("volatile memory cannot set stale_after_days")
    if retention_class == "durable" and expires_at:
        raise ValueError("durable memory cannot set expires_at")
    if retention_class == "durable" and ttl_days is not None:
        raise ValueError("durable memory cannot set ttl_days")
    stale_after_value = _absolute_deadline(stale_after, field="stale_after")
    expires_at_value = _absolute_deadline(expires_at, field="expires_at")
    parsed_principal = parse_principal_context(principal_context)
    if scope_kind == "user" and parsed_principal is None:
        return {
            "schema_version": PROJECT_MEMORY_CAPTURE_SCHEMA_VERSION,
            "captured": False,
            "auto_approved": False,
            "policy": policy,
            "reason": "principal_context_required",
            "redaction_policy": "metadata_only",
            "claim_boundary": "User-scoped memory admission fails closed without a validated acting principal.",
        }
    if audience_principals and parsed_principal is None:
        raise ValueError("shared memory admission requires a validated acting principal")
    if scope_ref is None:
        scope_ref = require_project_identity(omh_home.parent) if scope_kind == "project" else "default"
    effective_scope_ref = str(parsed_principal["principal"]) if scope_kind == "user" and parsed_principal is not None else scope_ref
    candidate = _build_project_memory_candidate(
        summary,
        content=content,
        record_type=record_type,
        scope_kind=scope_kind,
        scope_ref=effective_scope_ref,
        source=source,
        source_ref=source_ref,
        tags=tags or [],
        ttl_days=ttl_days,
        stale_after_days=stale_after_days,
        stale_after_at=stale_after_value,
        expires_at_value=expires_at_value,
        retention_class=retention_class,
        derived_from=_normalize_derived_from(omh_home, derived_from),
        perspective=_normalize_perspective(observer, observed),
        default_stale_after_days=_cadence_value(policy, "stale_after_days_default"),
        episode_ttl_days=_cadence_value(policy, "episode_ttl_days"),
        unresolved=bool(unresolved),
        open_max_days=_cadence_value(policy, "open_max_days"),
        clock=clock,
    )
    if parsed_principal is not None and (scope_kind == "user" or audience_principals):
        candidate["schema_version"] = "project_memory_candidate/v2"
        candidate["identity"] = build_memory_identity(
            parsed_principal,
            scope_kind=scope_kind,
            executor_perspective=executor_perspective,
            audience_principals=audience_principals,
        )
    # Exact-summary duplicate detection, mnemosyne-style but review-first:
    # the match is surfaced on the candidate for the reviewer to decide, never
    # silently merged -- and a duplicate never auto-approves, because the
    # auto-safe path would otherwise mint identical records unreviewed. The
    # comparison uses the candidate's own summary, which already went through
    # the same redaction/truncation pipeline as every stored summary; the raw
    # input would miss any match past the redaction cap.
    # Duplicate check, candidate write and auto-safe approval happen under
    # one capture lock: two captures of the same fact arriving together both
    # passed the check and both persisted. The store (index) lock inside
    # `approve_project_memory_candidate` is a different file, so holding this
    # one across the call is not a re-entry.
    with lock(memory_capture_lock_path(omh_home)):
        if on_duplicate == "skip":
            # The model-driven capture path: a candidate stamped duplicate_of
            # would wait for a reviewer who is not in that loop, so it names the
            # record already held and persists nothing -- but only a record held
            # under the SAME confinement counts as held. The review-first stamp
            # below may point across scopes because a reviewer sees it; here
            # nothing is persisted, and a match in another project or for another
            # principal would never be recalled under this lens, so it is not
            # "already remembered" and the capture goes through.
            duplicate_of = _duplicate_held_in_confinement(omh_home, candidate)
        else:
            duplicate_of = _find_duplicate_record(omh_home, str(candidate.get("summary", "")))
        if duplicate_of and on_duplicate == "skip":
            return {
                "schema_version": PROJECT_MEMORY_CAPTURE_SCHEMA_VERSION,
                "captured": False,
                "auto_approved": False,
                "policy": policy,
                "reason": "duplicate",
                "duplicate_of": duplicate_of,
                "receipt_state": None,
                "redaction_policy": "metadata_only",
                "claim_boundary": (
                    "An existing OMH-local record already carries this summary; nothing was persisted. "
                    "This is not evidence that Hermes recalled or used that record."
                ),
            }
        if duplicate_of:
            candidate["duplicate_of"] = duplicate_of
        # Relative-time prose is detected on the summary as it will be STORED
        # (post-redaction), because that is the text that will lie later. The
        # verdict rides on the candidate for the review card, and it suppresses
        # auto-approval below: a fact with a hidden expiry needs a human to
        # either accept the rot or restate it with an absolute date.
        relative_phrase = _relative_time_phrase(str(candidate.get("summary", "")))
        if relative_phrase:
            candidate["time_sensitivity"] = {
                "relative_phrase": relative_phrase,
                "detail": (
                    "The summary contains a relative-time phrase whose anchor (the moment of capture) "
                    "is not part of the stored content, so it will read wrong once time passes."
                ),
                "next_action": (
                    "Restate the fact with an absolute date, or set the deadline structurally "
                    "(--stale-after YYYY-MM-DD / --stale-after-days N) and approve as-is."
                ),
            }
        write_project_memory_candidate_unlocked(omh_home, candidate)
        write_memory_index(omh_home, lock=lock, clock=clock)
        auto_approved = False
        record: dict[str, object] = {}
        # force_review keeps derived aggregates (e.g. rollup episodes) on the
        # review path even under auto-safe: derived content is a curation act,
        # not a captured observation.
        if bool(policy.get("auto_approve_safe")) and candidate.get("safety", {}).get("status") == "safe" and not duplicate_of and not force_review and not relative_phrase:
            # Auto-safe binds to the candidate it just wrote: the revision comes
            # from that object, so this path proves the same payload it approved
            # rather than skipping the guard it asks reviewers to carry.
            approved = approve_project_memory_candidate(
                omh_home,
                str(candidate["candidate_id"]),
                approved_by="auto-safe",
                expected_revision=project_memory_review_revision(candidate),
                clock=clock,
                lock=lock,
            )
            record = approved.get("record", {}) if isinstance(approved.get("record"), dict) else {}
            candidate = approved.get("candidate", candidate) if isinstance(approved.get("candidate"), dict) else candidate
            auto_approved = True
    review_reason = "" if auto_approved else _capture_review_reason(
        candidate, policy, duplicate_of=duplicate_of, relative_phrase=relative_phrase, force_review=force_review
    )
    return {
        "schema_version": PROJECT_MEMORY_CAPTURE_SCHEMA_VERSION,
        "captured": True,
        "auto_approved": auto_approved,
        "candidate": candidate,
        "record": record,
        "policy": policy,
        "receipt_state": _capture_receipt_state(omh_home, record),
        **({"review_reason": review_reason} if review_reason else {}),
        "capture_receipt": {
            "schema_version": "memory_capture_receipt/v1",
            "subject_principal": candidate.get("identity", {}).get("subject_principal") if isinstance(candidate.get("identity"), dict) else None,
            "event_actor": candidate.get("identity", {}).get("event_actor") if isinstance(candidate.get("identity"), dict) else None,
            "reviewer": None,
            "executor_perspective": candidate.get("identity", {}).get("executor_perspective") if isinstance(candidate.get("identity"), dict) else _redacted_metadata_label(executor_perspective),
            "content_digest": str(candidate.get("content_ref", {}).get("sha256", "")) if isinstance(candidate.get("content_ref"), dict) else "",
            "redaction_policy": "metadata_only",
        },
        "claim_boundary": (
            "Captured project memory is an OMH-local candidate or reviewed record only; "
            "it is not execution, review, CI, merge, or Hermes internal-memory evidence."
        ),
    }


def _capture_review_reason(
    candidate: dict[str, Any],
    policy: dict[str, object],
    *,
    duplicate_of: str,
    relative_phrase: str,
    force_review: bool,
) -> str:
    """Why a captured candidate stopped short of auto-safe approval, first match wins."""
    safety = candidate.get("safety", {}) if isinstance(candidate.get("safety"), dict) else {}
    if safety.get("status") != "safe":
        return "unsafe_content"
    if relative_phrase:
        return "relative_time_phrase"
    if duplicate_of:
        return "duplicate"
    if force_review:
        return "derived_content"
    if not bool(policy.get("auto_approve_safe")):
        return "policy_review_first"
    return "unknown"


def _capture_receipt_state(omh_home: Path, record: dict[str, object]) -> str:
    """The furthest durability receipt this capture observed (docs/MEMORY.md).

    Each step is re-read from disk rather than inferred from the call that
    wrote it: the record file, then the index entry addressing it, then the
    same replay evaluator recall uses. A step that cannot be confirmed stops
    the receipt at the state before it.
    """
    record_id = str(record.get("record_id", "") or "")
    if not record_id:
        return "candidate_persisted"
    record_path = memory_record_path(omh_home, record_id)
    stored, error = read_json_object_result(record_path)
    if stored is None or error is not None:
        return "candidate_persisted"
    index, error = read_json_object_result(memory_index_path(omh_home))
    record_files = index.get("record_files", []) if isinstance(index, dict) and error is None else []
    if record_path.relative_to(memory_dir(omh_home)).as_posix() not in record_files:
        return "approved_record_persisted"
    evaluation = _shared_evaluate_memory_artifact(
        stored,
        operation_states=recall_operation_states(omh_home, [stored]),
        now=datetime.now(timezone.utc),
        review_resolver=project_memory_review_resolver(omh_home),
    )
    return "replay_ready" if evaluation.get("eligible") is True else "indexes_refreshed"


def project_memory_review_revision(candidate: dict[str, Any]) -> str:
    """Fingerprint the candidate payload a review card displays.

    A candidate id is a stable file name, not a version: a recapture, an
    overwrite, or a supersession leaves the id resolvable while the payload
    underneath it changed, so a card held open across that change could
    approve text its reviewer never read. The revision is derived from the
    displayed projection only -- summary, scope, tags, type, safety verdict,
    status, creation time, and the content digest that already stands in for
    the raw content -- so it moves exactly when what the reviewer saw moves,
    and it stays metadata-only: no raw content ever reaches the digest.

    Deliberately NOT named candidate_revision: that name is already taken
    repo-wide for the integer record revision on v2 lifecycle candidates and
    batch items. This is a content fingerprint of one rendered card, not a
    revision counter, and the two must not be read as the same field.

    The projection is derived FROM the rendered card rather than re-listed
    here. A hand-maintained field list is the bug this shape removes: it
    already drifted once -- `time_sensitivity` (the warning that tells a
    reviewer a fact has a hidden expiry, and what to do about it) was
    displayed on every card while the fingerprint ignored it, so rewriting
    that guidance under a candidate id left the revision frozen and a stale
    card still passed the guard. Building from the card makes "displayed"
    and "bound" the same set by construction, so a field added to the card
    tomorrow is covered without anyone remembering this function.
    """
    card = _project_memory_review_card_projection(candidate)
    content_ref = candidate.get("content_ref", {}) if isinstance(candidate.get("content_ref"), dict) else {}
    projection = {
        "card": card,
        # Not displayed, but part of what approval will store, and the digest
        # already stands in for raw content the card never shows.
        "schema_version": str(candidate.get("schema_version", "")),
        "status": str(candidate.get("status", "")),
        "source_ref": str(candidate.get("source_ref", "")),
        "retention_class": str(candidate.get("retention_class", "")),
        "content_sha256": str(content_ref.get("sha256", "")),
        "content_length": int(content_ref.get("length", 0) or 0),
    }
    canonical = json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "rev_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _project_memory_review_card_projection(candidate: dict[str, Any]) -> dict[str, object]:
    """The candidate-derived half of a review card: everything a reviewer reads.

    Static scaffolding -- schema version, the action list, the redaction and
    claim-boundary labels, and `recommended_action`, which is a pure function
    of the safety status already here -- is excluded on purpose: those cannot
    differ between two cards for the same candidate, so binding them would
    add noise to the fingerprint without adding any guarantee.
    """
    candidate = _sanitize_project_memory_candidate(candidate)
    safety = candidate.get("safety", {}) if isinstance(candidate.get("safety"), dict) else {}
    return {
        "candidate_id": str(candidate.get("candidate_id", "")),
        "record_type": str(candidate.get("record_type", "")),
        "summary": str(candidate.get("summary", "")),
        "scope": _normalize_scope(candidate.get("scope", _scope("project", "default"))),
        "tags": _string_list(candidate.get("tags", [])),
        "created_at": str(candidate.get("created_at", "")),
        **({"duplicate_of": str(candidate["duplicate_of"])} if candidate.get("duplicate_of") else {}),
        **(
            {"time_sensitivity": candidate["time_sensitivity"]}
            if isinstance(candidate.get("time_sensitivity"), dict)
            else {}
        ),
        # A reviewer must see that approval mints an open question, not a
        # fact -- and the ceiling it will expire under -- before deciding.
        **(
            {
                "unresolved": True,
                "review_due_at": str(_candidate_staleness(candidate).get("review_due_at", "") or ""),
                "open_expires_at": str(_candidate_staleness(candidate).get("open_expires_at", "") or ""),
            }
            if candidate.get("unresolved") is True
            else {}
        ),
        "safety": safety,
        **({"identity": candidate["identity"]} if isinstance(candidate.get("identity"), dict) else {}),
    }


class LifecycleCandidateError(ValueError):
    """A v2 lifecycle candidate reached the plain approval path."""


class StaleMemoryReviewError(ValueError):
    """A review decision named a candidate revision the store no longer holds."""


def _require_review_revision(candidate: dict[str, Any], expected_revision: str) -> None:
    """Refuse a decision whose card no longer describes the stored candidate.

    Called before any write, and only when the caller supplied a revision:
    an omitted revision keeps the in-process API working for callers that
    never rendered a card (auto-safe capture, lifecycle paths, wrappers that
    predate the field). The CLI is where the revision is required, so an
    interactive reviewer cannot approve unproven text.
    """
    actual = project_memory_review_revision(candidate)
    if expected_revision != actual:
        raise StaleMemoryReviewError(
            "stale_review: the candidate changed after the reviewed card was rendered; re-read it and decide again"
        )


def approve_project_memory_candidate(
    omh_home: Path,
    candidate_id: str,
    *,
    approved_by: str = "operator",
    retention_class: str | None = None,
    expected_revision: str = "",
    reviewer_principal: str | None = None,
    unresolved: bool = False,
    clock: Clock = utc_now,
    lock: StoreLock = memory_store_lock,
) -> dict[str, object]:
    omh_home = Path(omh_home)
    reviewer_safety = classify_memory_admission(
        "\n".join((str(approved_by or ""), str(retention_class or "")))
    )
    if reviewer_safety["status"] != "safe":
        raise ValueError("credential-like project-memory approval metadata is not allowed")
    # Read, validate, and write under ONE hold of the store lock. Reading the
    # candidate outside the lock made the guard advisory: a recapture landing
    # between the revision check and the record write would be approved on the
    # reviewer's behalf, with the stale check having already passed. The
    # guarantee is "no write on a stale card", and only a read-check-write that
    # cannot be interleaved can offer it. Everything derived from the candidate
    # is derived in here too, so nothing is computed from a payload the write
    # will not match. Candidate writes go through the unlocked helper: the
    # locked index refresh acquires this same non-reentrant lock.
    with lock(memory_index_path(omh_home)):
        candidate = read_project_memory_candidate(omh_home, candidate_id)
        if not candidate:
            raise FileNotFoundError(candidate_id)
        if expected_revision:
            _require_review_revision(candidate, expected_revision)
        # Fail closed on correction/restore candidates: their payload lives under
        # "replacement", so the plain path would mint a record with an empty
        # summary and revision 1 -- and that garbage record then blocks the real
        # reapproval with newer_live_revision_conflict. The CLI catches this and
        # routes to the lifecycle reapproval executor instead.
        if str(candidate.get("lifecycle", "") or ""):
            raise LifecycleCandidateError(
                f"candidate {candidate_id} is a lifecycle ({candidate.get('lifecycle', 'v2')}) candidate; "
                "it must be reapproved through the lifecycle path, not plain approval"
            )
        current_safety = evaluate_renderable_strings(candidate)
        if current_safety.get("status") != "safe":
            raise ValueError("project memory candidate no longer passes the current safety policy")
        candidate = _sanitize_project_memory_candidate(candidate)
        safety = candidate.get("safety", {}) if isinstance(candidate.get("safety"), dict) else {}
        if safety.get("status") == "blocked":
            raise ValueError("blocked memory candidates must be rejected or recaptured without protected raw content")
        approved_at = clock()
        review_id = f"review_{candidate_id}"
        admission_state = "approved_auto_safe" if approved_by == "auto-safe" else "approved_manual"
        policy = read_project_memory_policy(omh_home)
        record = _record_from_candidate(
            candidate,
            approved_by=approved_by,
            approved_at=approved_at,
            review_id=review_id,
            admission_state=admission_state,
            retention_class=retention_class,
            default_stale_after_days=_cadence_value(policy, "stale_after_days_default"),
            reviewer_principal=reviewer_principal,
            unresolved=bool(unresolved),
            open_max_days=_cadence_value(policy, "open_max_days"),
        )
        review = _project_memory_review_record(record, review_id=review_id, reviewer=approved_by, decision=admission_state)
        write_project_memory_record(omh_home, record)
        candidate = {
            **candidate,
            "status": "approved",
            "reviewed_at": approved_at,
            "reviewed_by": approved_by,
            "record_id": record["record_id"],
            "review_id": review_id,
        }
        write_project_memory_candidate_unlocked(omh_home, candidate)
        write_project_memory_review_decision(omh_home, review)
        write_memory_index_unlocked(omh_home, updated_at=clock())
    return {
        "schema_version": PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION,
        "decision": admission_state,
        "candidate": candidate,
        "record": record,
        "review": review,
        "claim_boundary": "Approved project memory is prepared context only; it is not execution, review, CI, merge, or Hermes internal-memory evidence.",
    }


def _find_duplicate_record(omh_home: Path, summary: str, *, now: datetime | None = None) -> str:
    """Record id of a non-expired record with the same normalized summary.

    Normalization is NFC + casefold-by-lower + whitespace collapse -- exact
    content match like mnemosyne's dedup, not similarity, so it can never
    merge two facts that merely look alike. TTL-expired records are skipped:
    re-capturing an expiring fact is the normal refresh path and must not be
    denied auto-approval by its own dying predecessor. One identity for "the
    same fact": recall's `duplicate_record` reads the same key function.
    """
    key = normalized_summary_key(summary)
    if not key:
        return ""
    now = now if now is not None else datetime.now(timezone.utc)
    for record in read_project_memory_records(omh_home):
        if _classify_record_expiry(record, now=now) == "expired":
            continue
        if normalized_summary_key(str(record.get("summary", ""))) == key:
            return str(record.get("record_id", ""))
    return ""


def _duplicate_held_in_confinement(omh_home: Path, candidate: dict[str, object], *, now: datetime | None = None) -> str:
    """Record id of a non-expired same-summary record in the candidate's own scope and principal.

    The cross-scope match `_find_duplicate_record` returns is a reviewer's
    hint; it is the wrong answer for a path that persists nothing on a match,
    because a record confined to another project or another principal is
    never recalled under this candidate's lens. Same scope (kind and ref) and
    same subject principal (both absent, or equal) is what "held" means here.
    """
    key = normalized_summary_key(str(candidate.get("summary", "")))
    if not key:
        return ""
    now = now if now is not None else datetime.now(timezone.utc)
    scope = candidate.get("scope") if isinstance(candidate.get("scope"), dict) else {}
    principal = _subject_principal(candidate)
    for record in read_project_memory_records(omh_home):
        if _classify_record_expiry(record, now=now) == "expired":
            continue
        if normalized_summary_key(str(record.get("summary", ""))) != key:
            continue
        record_scope = record.get("scope") if isinstance(record.get("scope"), dict) else {}
        if record_scope != scope or _subject_principal(record) != principal:
            continue
        return str(record.get("record_id", ""))
    return ""


def _subject_principal(artifact: dict[str, object]) -> str | None:
    identity = artifact.get("identity")
    if not isinstance(identity, dict):
        return None
    value = identity.get("subject_principal")
    return str(value) if value else None


def _attention_metadata(tier: str, *, reason: str, previous_tier: str, changed_at: str) -> dict[str, str]:
    """Scalar-only tier metadata; nested non-scalars would be dropped by
    correction/restore and by the recall-pack validators."""
    return {
        "schema_version": MEMORY_ATTENTION_SCHEMA_VERSION,
        "tier": tier,
        "reason": _redact(str(reason or ""))[:_MEMORY_ATTENTION_REASON_LIMIT],
        "previous_tier": str(previous_tier or ""),
        "changed_at": str(changed_at or ""),
    }


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


def _normalize_derived_from(omh_home: Path, derived_from: list[str] | tuple[str, ...] | None) -> list[str]:
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
    known = {str(record.get("record_id", "")) for record in read_project_memory_records(omh_home)}
    for ref in refs:
        if not _SAFE_REF.match(ref):
            raise ValueError(f"unsafe derived-from record id: {ref!r}")
        if ref not in known:
            # The records reader skips unreadable files, so distinguish a
            # crash-corrupted record from a genuinely absent one -- "not
            # found" would send the operator hunting for a file that exists.
            if (memory_records_dir(omh_home) / f"{ref}.json").is_file():
                raise ValueError(f"derived-from record is unreadable: {ref}")
            raise ValueError(f"derived-from record not found: {ref}")
    return refs


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
    default_stale_after_days: int | None = None,
    episode_ttl_days: int | None = None,
    stale_after_at: str = "",
    expires_at_value: str = "",
    unresolved: bool = False,
    open_max_days: int | None = None,
    clock: Clock = utc_now,
) -> dict[str, object]:
    normalized_type = _normalize_record_type(record_type)
    scope = _scope_for_project_memory(scope_kind, scope_ref)
    raw_tags = [unicodedata.normalize("NFC", str(value)).strip() for value in tags]
    normalized_tags = _normalize_tags(raw_tags)
    content_text = str(content or "")
    safety = _project_memory_safety(
        summary,
        content_text,
        tags=raw_tags,
        source=str(source or "cli"),
        source_ref=str(source_ref or ""),
    )
    now = clock()
    if expires_at_value:
        # An absolute expiry carries no day count -- the date IS the policy.
        ttl: dict[str, object] = {"ttl_days": None, "expires_at": expires_at_value}
    else:
        ttl = _ttl_metadata(ttl_days, record_type=normalized_type, created_at=now, episode_ttl_days=episode_ttl_days)
    # `cadence_source` records whether the captor chose the cadence or the
    # default supplied it -- the one fact an approval-time re-class needs to
    # honour an explicit deadline without freezing a defaulted one. An
    # absolute review date is explicit by definition.
    if stale_after_at:
        staleness: dict[str, object] = {
            "stale_after_days": None,
            "stale_after": stale_after_at,
            "review_due_at": stale_after_at,
            "cadence_source": "explicit",
        }
    else:
        staleness = {
            **_staleness_metadata(
                stale_after_days,
                record_type=normalized_type,
                retention_class=retention_class,
                created_at=now,
                default_days=default_stale_after_days,
            ),
            "cadence_source": "explicit" if stale_after_days is not None else "default",
        }
    if unresolved:
        # The open clock starts at capture: the question has been open since
        # the moment it was written down, not since a reviewer got to it.
        staleness = {**staleness, **_open_staleness_fields(now, retention_class=retention_class, open_max_days=open_max_days)}
        if not str(staleness.get("stale_after", "") or ""):
            # "Unresolved" means "needs an answer by then". A durable record
            # or an episode mints no review deadline on its own, and an open
            # record with no deadline could never reach the `open` verdict,
            # never be asked about, and (before confirm learned better) never
            # be answered. So an open record always carries one: the default
            # cadence, marked default, shown on the card.
            staleness = {**staleness, **_open_review_deadline(now, default_days=default_stale_after_days), "cadence_source": "default"}
    candidate_id = "cand_" + os.urandom(8).hex()
    status = "blocked_review_required" if safety["status"] == "blocked" else "pending_review"
    # Digest the ref exactly as it will be stored, not as it was passed:
    # redaction and truncation can change the string, and the freshness check
    # later reads the stored one.
    stored_source_ref = _redact_admitted_text(str(source_ref or ""))[:160]
    source_evidence = _source_evidence(stored_source_ref, captured_at=now)
    return {
        "schema_version": PROJECT_MEMORY_CANDIDATE_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "status": status,
        "record_type": normalized_type,
        "summary": _redact_admitted_text(summary.strip())[:500],
        "scope": scope,
        "tags": normalized_tags,
        "source": _redact_admitted_text(str(source or "cli")),
        "source_ref": stored_source_ref,
        **({"source_evidence": source_evidence} if source_evidence else {}),
        "created_at": now,
        "ttl": ttl,
        "staleness": staleness,
        **({"unresolved": True} if unresolved else {}),
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
    retention_class: str | None = None,
    default_stale_after_days: int | None = None,
    reviewer_principal: str | None = None,
    unresolved: bool = False,
    open_max_days: int | None = None,
) -> dict[str, object]:
    if admission_state not in ADMISSION_STATES:
        raise ValueError(f"unsupported memory admission state: {admission_state}")
    approved_at_value = _parse_utc(approved_at)
    if approved_at_value is None:
        raise ValueError("approved_at must be an ISO timestamp")
    record_type = _normalize_record_type(str(candidate.get("record_type", "fact")))
    # The reviewer may re-class the record at approval -- most usefully
    # promoting a settled decision to `durable` so it does not inherit the
    # 90-day review clock nobody chose for it. The override re-derives
    # retention AND the review deadline with the new class's own defaults;
    # a captor who wants a specific cadence on a durable record sets it at
    # capture, where the explicit value is recorded.
    requested_class = str(candidate.get("retention_class", "standard"))
    override = None
    if retention_class is not None:
        supplied = str(retention_class)
        if supplied not in {"volatile", "standard", "durable"}:
            raise ValueError(f"unsupported retention class: {supplied}")
        # An identity override (the class the candidate already has) is a
        # validated no-op: the record mints exactly as a plain approval
        # would, carry-overs included.
        if supplied != requested_class:
            override = supplied
            requested_class = supplied
    retention = build_retention(
        requested_class,
        record_type=record_type,
        admitted_at=approved_at_value,
        ttl_days=_candidate_ttl_days(candidate) if override is None else None,
    )
    # Approval must not silently extend the deadline shown to the reviewer.
    # `utc_now` is second-truncated, so deriving it again from `approved_at`
    # made this record expire one second later whenever review crossed a clock
    # boundary. The candidate's stored deadline is the authoritative value --
    # including an absolute `expires_at` captured without a day count, which
    # `build_retention` cannot re-derive (there is no ttl_days to hand it) and
    # which would otherwise vanish at approval. An overridden class skips the
    # carry-over on purpose: that deadline was minted for the class the
    # reviewer just rejected.
    # A durable record must never gain an expiry through the carry-over: the
    # class exists to say "this does not expire", the workflow gate refuses
    # durable+ttl at capture, and a legacy candidate that slipped one in is
    # exactly the record this guard must not resurrect a deadline onto.
    candidate_ttl = candidate.get("ttl")
    if override is None and requested_class != "durable" and isinstance(candidate_ttl, dict) and candidate_ttl.get("expires_at"):
        retention["expires_at"] = str(candidate_ttl["expires_at"])
    record_id = "mem_" + os.urandom(8).hex()
    scope = _normalize_scope(candidate.get("scope", _scope("project", "default")))
    revalidation = _candidate_revalidation(candidate)
    staleness_days = _candidate_stale_after_days(candidate)
    if override is not None:
        candidate_staleness = candidate.get("staleness") if isinstance(candidate.get("staleness"), dict) else {}
        # Explicit is explicit in either shape: a day count (staleness_days)
        # or an absolute review date, which mints no day count but does mint
        # a revalidation deadline. Requiring the day count made the absolute
        # form strictly weaker -- a re-class silently dropped a date the
        # reviewer saw on the card.
        explicit_cadence = str(candidate_staleness.get("cadence_source", "") or "") == "explicit" and (
            staleness_days is not None or bool(_candidate_revalidation(candidate))
        )
        if explicit_cadence:
            # A cadence the captor explicitly chose survives the re-class:
            # `_staleness_metadata` is explicit that durable makes the
            # deadline optional, not forbidden, and the reviewer's flag was
            # about retention, not about removing a review date they saw on
            # the card. The candidate's revalidation carries over untouched.
            pass
        else:
            refreshed = _staleness_metadata(
                None,
                record_type=record_type,
                created_at=str(candidate.get("created_at", approved_at)),
                retention_class=override,
                default_days=default_stale_after_days,
            )
            revalidation = {"deadline": str(refreshed["stale_after"])} if refreshed["stale_after"] else {}
            staleness_days = refreshed["stale_after_days"]
    # The open marker a person set -- at capture (the candidate's clock
    # carries over) or here at approval (the approval clock starts it). Only
    # confirm or correct ever writes `resolved`.
    open_fields = _record_open_fields(
        candidate,
        approved_at=approved_at,
        unresolved=unresolved,
        retention_class=requested_class,
        open_max_days=open_max_days,
    )
    if open_fields and not revalidation:
        # An open record always carries a review deadline ("needs an answer
        # by then"): a durable re-class dropped the one the card showed, or
        # `approve --unresolved` landed on a candidate that minted none. Keep
        # the candidate's own deadline when it has one -- approval must not
        # move a date the reviewer saw -- else start the default cadence now.
        carried = _candidate_revalidation(candidate)
        if carried:
            revalidation = carried
            staleness_days = _candidate_stale_after_days(candidate)
        else:
            minted = _open_review_deadline(approved_at, default_days=default_stale_after_days)
            revalidation = {"deadline": str(minted["stale_after"])}
            staleness_days = minted["stale_after_days"]
    identity = candidate.get("identity") if isinstance(candidate.get("identity"), dict) else None
    if identity is not None:
        reviewer = {"principal": reviewer_principal, "review_ref": review_id}
        audience = identity.get("audience") if isinstance(identity.get("audience"), dict) else {}
        identity = {**identity, "reviewer": reviewer, "audience": {**audience, "review_ref": review_id}}
    record: dict[str, object] = {
        "schema_version": PRINCIPAL_PROJECT_MEMORY_RECORD_SCHEMA_VERSION if identity is not None else PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
        "record_id": record_id,
        "candidate_id": str(candidate.get("candidate_id", "")),
        "revision": 1,
        "record_type": record_type,
        "summary": _redact_admitted_text(str(candidate.get("summary", "")))[:500],
        "scope": scope,
        "tags": _normalize_tags(candidate.get("tags", [])),
        "source": _redact_admitted_text(str(candidate.get("source", "cli"))),
        "source_class": "omh_local",
        "source_ref": _redact_admitted_text(str(candidate.get("source_ref", "")))[:160],
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
        # The projection alone nulls `stale_after_days`, which lost the
        # cadence the captor chose: a record captured at 365 days silently
        # fell back to the 90-day default on its first flagless confirm.
        # Carrying the candidate's cadence onto the record keeps `omh memory
        # confirm` honouring it.
        "staleness": {
            **_staleness_projection(revalidation),
            "stale_after_days": staleness_days,
            **open_fields,
        },
        # Every approved record states its tier explicitly. An implicit
        # default would make "this record is active" and "nobody ever set a
        # tier" the same fact, and the operator could not tell an intentional
        # promotion from a record the tier system never touched.
        "attention": _attention_metadata(
            DEFAULT_MEMORY_ATTENTION_TIER,
            reason="approved_default",
            previous_tier="",
            changed_at=approved_at,
        ),
        "safety": candidate.get("safety", {}),
        **({"identity": identity} if identity is not None else {}),
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
        "schema_version": PRINCIPAL_PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION if record.get("schema_version") == PRINCIPAL_PROJECT_MEMORY_RECORD_SCHEMA_VERSION else PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION,
        "review_id": review_id,
        "artifact_identity": stable_artifact_identity(record),
        "decision": decision,
        "reviewer_claim": str(reviewer or "operator"),
        **({"identity": record["identity"]} if isinstance(record.get("identity"), dict) else {}),
        "payload_digest": canonical_payload_digest(record),
        "policy_version": MEMORY_GOVERNANCE_POLICY_VERSION,
        "reviewed_at": str(record.get("approved_at", "")),
        "claim_boundary": "Project memory review decisions are prepared governance only, never executor-use evidence.",
    }


def _candidate_stale_after_days(candidate: dict[str, Any]) -> int | None:
    staleness = candidate.get("staleness")
    days = staleness.get("stale_after_days") if isinstance(staleness, dict) else None
    return days if isinstance(days, int) and not isinstance(days, bool) and days > 0 else None


def _candidate_ttl_days(candidate: dict[str, Any]) -> int | None:
    ttl = candidate.get("ttl")
    ttl_days = ttl.get("ttl_days") if isinstance(ttl, dict) else None
    return ttl_days if isinstance(ttl_days, int) and not isinstance(ttl_days, bool) else None


def _candidate_revalidation(candidate: dict[str, Any]) -> dict[str, object]:
    staleness = candidate.get("staleness")
    deadline = staleness.get("stale_after") if isinstance(staleness, dict) else ""
    return {"deadline": str(deadline)} if deadline else {}


def _candidate_staleness(candidate: dict[str, Any]) -> dict[str, object]:
    staleness = candidate.get("staleness")
    return dict(staleness) if isinstance(staleness, dict) else {}


def _open_staleness_fields(open_since: str, *, retention_class: str, open_max_days: int | None) -> dict[str, object]:
    """The marker an unresolved record carries: ``open`` since when, and until when.

    ``open_expires_at`` is the ceiling that keeps "open" from becoming
    "forever": ``open_since`` plus ``open_max_days`` (policy tunable, default
    a year). A durable record has no ceiling, the class exists to say it does
    not expire; volatile and episode TTLs still apply unchanged on top.
    """
    fields: dict[str, object] = {"resolution": "open", "open_since": str(open_since)}
    if retention_class != "durable":
        fields["open_expires_at"] = _days_after(str(open_since), open_max_days if open_max_days is not None else _OPEN_MAX_DAYS)
    return fields


def _open_review_deadline(open_since: str, *, default_days: int | None) -> dict[str, object]:
    """The review deadline every open record carries: the default cadence from ``open_since``.

    An open record with no deadline would never reach the ``open`` verdict
    and never be asked about, so "unresolved" always means "needs an answer
    by then" -- including for durable records and episodes, which mint no
    deadline of their own. Same shape as ``_staleness_metadata``.
    """
    days = default_days if default_days is not None else _REVIEW_DEFAULT_DAYS
    deadline = _days_after(str(open_since), days)
    return {"stale_after_days": days, "stale_after": deadline, "review_due_at": deadline}


def _record_open_fields(
    candidate: dict[str, Any],
    *,
    approved_at: str,
    unresolved: bool,
    retention_class: str,
    open_max_days: int | None,
) -> dict[str, object]:
    """Open marker for a record minted from ``candidate``; {} for an ordinary one.

    An ``--unresolved`` approval starts the clock now. A candidate captured
    ``--unresolved`` carries its own ``open_since`` and ceiling over, the
    same rule as the TTL carry-over: approval must not silently move a date
    the reviewer saw on the card. A durable class drops the ceiling either
    way, and a candidate ceiling is re-derived only when it is absent (a
    candidate re-classed out of durable).
    """
    candidate_staleness = _candidate_staleness(candidate)
    if unresolved:
        return _open_staleness_fields(approved_at, retention_class=retention_class, open_max_days=open_max_days)
    if _record_resolution(candidate_staleness) != "open":
        return {}
    open_since = str(candidate_staleness.get("open_since", "") or candidate.get("created_at", "") or approved_at)
    fields = _open_staleness_fields(open_since, retention_class=retention_class, open_max_days=open_max_days)
    carried = str(candidate_staleness.get("open_expires_at", "") or "")
    if retention_class != "durable" and carried:
        fields["open_expires_at"] = carried
    return fields


def _ttl_projection(retention: dict[str, object]) -> dict[str, object]:
    return {
        "ttl_days": retention.get("ttl_days"),
        "expires_at": str(retention.get("expires_at", "")),
    }


def _staleness_projection(revalidation: dict[str, object]) -> dict[str, object]:
    deadline = str(revalidation.get("deadline", ""))
    return {"stale_after": deadline, "stale_after_days": None, "review_due_at": deadline}


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


def _project_memory_safety(
    summary: str,
    content: str,
    *,
    tags: list[str],
    source: str = "",
    source_ref: str = "",
) -> dict[str, object]:
    classification = classify_memory_admission("\n".join([summary, content, " ".join(tags), source, source_ref]))
    status = str(classification.get("status", "blocked"))
    return {
        # v2 stays: the shape gained `lane_refused_inputs` and `protected_inputs`
        # lost two entries, but nothing reads either key and no stored digest
        # covers this dict -- the batch artifacts that are re-digested never
        # carry it. A version bump would be a migration for no reader.
        "schema_version": "project_memory_safety/v2",
        "status": status,
        "safe_to_auto_approve": status == "safe",
        "review_reasons": [] if status == "safe" else [status],
        # What this classification actually screens, not what the lane asks a
        # person to refuse. Raw logs and transcripts belong in the second list:
        # the capture lane declines them and points at the session store, and
        # the domain-vocabulary gate matches their shape, but no pattern here
        # reads them, so naming them as screened here would be a claim the
        # verdict above cannot support.
        "protected_inputs": ["credentials", "prompt_injection_shaped_text", "temporary_task_progress"],
        "lane_refused_inputs": ["raw_logs", "full_transcripts"],
    }


# Relative-time prose in a stored summary is a fact with a hidden expiry:
# "계약 만료는 3주 뒤" is true for exactly one day and then lies, and nothing in
# the store can tell, because the phrase's anchor -- the moment of writing --
# is not part of the record's content. This is a content-quality lint on what
# the store accepts, not a language trigger table: matches only force review
# (never block, never auto-fix), so a false positive costs one review click
# and a false negative is the status quo. Patterns are deliberately tight --
# bare "후/전" ("리뷰 후 머지") never match; a number-plus-unit or an
# unambiguous deictic word must be present.
#
# The quantity slot takes spelled numbers and vague quantifiers as well as
# digits, because "two weeks ago" and "il y a quelques jours" are how people
# actually write these phrases; the anchor ("ago", "in", "il y a", "dans")
# stays mandatory, so "two weeks of leave" and "in two places" never match.
_EN_QUANTITY = (
    r"(?:\d{1,4}|an?|one|two|three|four|five|six|seven|eight|nine|ten"
    r"|(?:a\s+)?few|several|(?:a\s+)?couple(?:\s+of)?)"
)
_EN_TIME_UNIT = r"(?:days?|weeks?|months?|years?|hours?|minutes?)"
# A weekday bound to "last"/"next" is relative; "the last Friday" and
# "last Friday of the month" are a recurring rule and are held back.
_EN_WEEKDAY = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
_FR_QUANTITY = r"(?:\d{1,4}|une?|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|quelques|plusieurs)"
_FR_TIME_UNIT = r"(?:jours?|semaines?|mois|ann[ée]es?|ans?|heures?|minutes?)"
_FR_WEEKDAY = r"(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)"
_RELATIVE_TIME_PATTERN = re.compile(
    r"(?<!\d)\d{1,4}\s*(?:일|주|개월|달|년|시간|분)\s*(?:뒤|후|이내|안에|내로)"
    # Deictic words may carry an ordinary particle (내일부터, 오늘은) -- the
    # idiomatic majority -- but a following non-particle hangul syllable
    # (오늘의집, 내일정) means a compound, not a time reference.
    r"|(?<![가-힣])(?:그저께|어제|오늘|내일|모레|다음\s*주|다음\s*달|이번\s*주)(?:은|는|이|가|에|에는|부터|까지|도|만)?(?![가-힣])"
    # "in" takes a number or a vague quantifier but not a bare "a"/"one":
    # "built in a day" and "done in one week" are durations, and the
    # deictic reading ("ship in a week") is the rarer of the two.
    r"|\b(?:yesterday|today|tomorrow|next\s+(?:week|month|year)|in\s+(?!(?:an?|one)\s+(?!few\b|couple\b))" + _EN_QUANTITY + r"\s+" + _EN_TIME_UNIT
    # Past-relative English has the same hidden anchor: a number plus a unit
    # before "ago", "last" bound to a time noun, or the fixed "the other day".
    # Bare "ago", "last" and "other" ("the last step") never match.
    + r"|" + _EN_QUANTITY + r"\s+" + _EN_TIME_UNIT + r"\s+ago|last\s+(?:week|month|year)|the\s+other\s+day"
    r"|(?<!\bthe\s)(?:last|next)\s+" + _EN_WEEKDAY + r"(?!\s+(?:of|in)\b)"
    # "recently" carries the same hidden anchor; "most/least recently" is a
    # sort order ("least recently used"), not a time reference.
    r"|(?<!\bmost\s)(?<!\bleast\s)recently)\b"
    r"|(?<!\d)\d{1,4}\s*(?:日|週間|ヶ月|か月|年)\s*(?:後|以内)"
    r"|(?<!\d)\d{1,4}\s*(?:天|周|個月|个月|年)\s*(?:后|後|以内|以內|内|內)"
    r"|明日|昨日|来週|来月|明天|昨天|下周(?!期)|下個月|下个月"
    # French: a number plus a time unit after "dans"/"d'ici", a deictic word,
    # or "prochain(e)" bound to a time noun. Bare "semaine", "mois" and
    # "prochaine" ("la prochaine version") never match, and neither does
    # "hier": it is German for "here", and German prose must not lose
    # auto-approval to a French cue.
    r"|\b(?:(?:dans|d['’]ici)\s+" + _FR_QUANTITY + r"\s+" + _FR_TIME_UNIT
    + r"|(?:la\s+)?semaine\s+prochaine|(?:le\s+)?mois\s+prochain|(?:l['’])?ann[ée]e\s+prochaine"
    r"|demain|aujourd['’]hui|avant-hier"
    # Past-relative French: "il y a" only with a number plus a unit ("il y a
    # des cas" is ordinary), and "dernier/dernière" only bound to a time noun
    # ("le dernier commit" is ordinary).
    r"|il\s+y\s+a\s+" + _FR_QUANTITY + r"\s+" + _FR_TIME_UNIT
    # A weekday bound to "dernier"/"prochain" after it; "le dernier vendredi
    # du mois" puts the adjective first and is a recurring rule.
    + r"|" + _FR_WEEKDAY + r"\s+(?:dernier|prochain)"
    # Likewise "récemment", except after "plus"/"moins" (a sort order).
    r"|(?<!\bplus\s)(?<!\bmoins\s)r[ée]cemment"
    r"|(?:la\s+)?semaine\s+derni[èe]re|(?:le\s+)?mois\s+dernier|(?:l['’])?ann[ée]e\s+derni[èe]re|l['’]an\s+dernier"
    r"|d['’]ici\s+(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|demain|la\s+fin\s+(?:de\s+la\s+semaine|du\s+mois)))\b",
    re.IGNORECASE,
)


def _relative_time_phrase(value: str) -> str:
    """The first relative-time phrase in stored prose, or ""."""
    match = _RELATIVE_TIME_PATTERN.search(value)
    return match.group(0) if match else ""


def _validated_day_count(days: int | None, *, field: str) -> int | None:
    """A day count that can express a deadline, or None for "no deadline".

    The `>= 1` guard used to live only in the argparse layer, so the CLI
    rejected `--ttl-days 0` and `--ttl-days -5` while the workflow function
    behind it accepted both from the plugin bundle, the wrapper, or any future
    caller. `-5` minted a record that was already expired at creation, and `0`
    made the candidate and its own approved record disagree about the same
    input: the candidate read `expires_at: ""`, which means never expires, and
    the record read `expires_at == created_at`, which means expired the instant
    it was written.

    Zero is rejected rather than reinterpreted. It is not a shorter TTL and it
    is not the absence of one; it is an input nobody meant.
    """
    if days is None:
        return None
    if isinstance(days, bool) or not isinstance(days, int):
        raise ValueError(f"{field} must be a whole number of days")
    if days < 1 or days > MAX_RETENTION_DAYS:
        raise ValueError(f"{field} must be between 1 and {MAX_RETENTION_DAYS} days; got {days}")
    return days


def _ttl_metadata(
    ttl_days: int | None,
    *,
    record_type: str,
    created_at: str,
    episode_ttl_days: int | None = None,
) -> dict[str, object]:
    days = _validated_day_count(ttl_days, field="ttl_days")
    if days is None and record_type == "episode":
        days = episode_ttl_days if episode_ttl_days is not None else _EPISODE_DEFAULT_TTL_DAYS
    # `is None` rather than falsiness: "no deadline" and "zero days" are
    # different statements, and only the first one may produce an empty
    # `expires_at`. The falsy test is what let a rejected-at-the-CLI zero
    # become a candidate that claimed to never expire.
    return {
        "ttl_days": days,
        "expires_at": _days_after(created_at, days) if days is not None else "",
    }


def _staleness_metadata(
    stale_after_days: int | None,
    *,
    record_type: str,
    created_at: str,
    retention_class: str = "standard",
    default_days: int | None = None,
) -> dict[str, object]:
    """The review-due deadline, or none for a record declared durable.

    The 90-day default used to key off `record_type` alone, so a `durable`
    record -- the class that exists to say this does not expire -- still read
    `stale/review_due` after 90 days and carried a freshness warning into every
    recall from then on. `build_retention` has always been explicit that the
    class does not work that way ("durable: no default expiry; revalidation
    deadline is optional"); the two layers simply never spoke.

    A 90-day re-read is right for a claim that rots -- an API timeout, an
    on-call rotation, a deploy procedure. It is noise on a founding date, a
    chosen license, a settled architecture, or a post-mortem lesson, and noise
    on those trains operators to ignore the warning on the records where it was
    the point.

    An explicitly supplied deadline is still honoured for a durable record: the
    class says the deadline is optional, not forbidden.
    """
    days = _validated_day_count(stale_after_days, field="stale_after_days")
    if days is None and retention_class != "durable" and record_type in {"fact", "decision", "lesson", "procedure"}:
        days = default_days if default_days is not None else _REVIEW_DEFAULT_DAYS
    default_days = days
    deadline = _days_after(created_at, days) if days is not None else ""
    # `review_due_at` is the readable name for the date `stale_after` always
    # held. Both are written so older readers keep working; nothing derives a
    # second deadline from the new spelling.
    return {
        "stale_after_days": default_days,
        "stale_after": deadline,
        "review_due_at": deadline,
    }


def _absolute_deadline(value: str, *, field: str, now: datetime | None = None) -> str:
    """Normalize an absolute deadline: a future UTC instant, fail-closed.

    A bare date (`YYYY-MM-DD`) means the START of that UTC day -- the
    conservative reading: a record whose deadline is "the 18th" goes
    review-due or expires the moment the 18th begins, never quietly late on
    the 18th's last second. A full ISO timestamp is taken exactly (naive
    reads as UTC, matching every other deadline in this module). The past is
    refused rather than stored: a deadline that has already happened is a
    statement for `correct` or `retire`, not for capture.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    moment = now if now is not None else datetime.now(timezone.utc)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        try:
            parsed: datetime | None = datetime(int(raw[:4]), int(raw[5:7]), int(raw[8:10]), tzinfo=timezone.utc)
        except ValueError:
            parsed = None
    else:
        parsed = _parse_utc_naive_as_utc(raw)
    if parsed is None:
        raise ValueError(f"{field} must be YYYY-MM-DD or an ISO timestamp; got {value!r}")
    # Truncate BEFORE the future check: the stored value is the truncated
    # one, and a sub-second future instant would otherwise be accepted and
    # then stored already past.
    parsed = parsed.replace(microsecond=0)
    if parsed <= moment:
        raise ValueError(f"{field} must be in the future; got {value!r}")
    if parsed - moment > timedelta(days=MAX_RETENTION_DAYS):
        raise ValueError(f"{field} must be within {MAX_RETENTION_DAYS} days; got {value!r}")
    return parsed.isoformat().replace("+00:00", "Z")


def _days_after(created_at: str, days: int | None) -> str:
    if days is None:
        return ""
    base = _parse_utc(created_at) or datetime.now(timezone.utc)
    return (base + timedelta(days=int(days))).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_memory_mode(value: str | None) -> str:
    mode = str(value or PROJECT_MEMORY_DEFAULT_MODE).strip()
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
    if not _SAFE_REF.match(scope["ref"]) or contains_credential_like_material(scope["ref"]):
        raise ValueError("unsafe memory scope ref")
    return scope


def _redacted_scope(value: Any) -> dict[str, str]:
    scope = _normalize_scope(value)
    return {
        "kind": _redacted_metadata_label(scope.get("kind", "project")) or "project",
        "ref": _redacted_metadata_label(scope.get("ref", "default")) or "default",
    }


def _sanitize_project_memory_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    nested = _redact_nested_metadata(candidate)
    sanitized = nested if isinstance(nested, dict) else {}
    sanitized["summary"] = _redact_admitted_text(str(candidate.get("summary", "")))[:500]
    sanitized["tags"] = _normalize_tags(candidate.get("tags", []))
    sanitized["source"] = _redact_admitted_text(str(candidate.get("source", "")))
    sanitized["source_ref"] = _redact_admitted_text(str(candidate.get("source_ref", "")))[:160]
    sanitized["scope"] = _redacted_scope(candidate.get("scope", _scope("project", "default")))
    if "derived_from" in candidate:
        sanitized["derived_from"] = [
            _redacted_metadata_label(ref) for ref in _string_list(candidate.get("derived_from", []))
        ]
    if isinstance(candidate.get("perspective"), dict):
        sanitized["perspective"] = _redact_nested_metadata(candidate["perspective"])
    if isinstance(candidate.get("source_evidence"), dict):
        sanitized["source_evidence"] = _redact_nested_metadata(candidate["source_evidence"])
    return sanitized


def _redact(value: str) -> str:
    if _looks_sensitive(value):
        return "[redacted]"
    return value[:240]


def _looks_sensitive(value: str) -> bool:
    lowered = value.lower()
    return any(
        marker in lowered
        for marker in ("secret", "token", "password", "private-key", "api_key", "apikey")
    ) or contains_credential_like_material(value)
