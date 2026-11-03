"""Canonical reviewed-memory selection, importable by the installed plugin.

Only stdlib and sibling plugin modules are dependencies. The caller supplies
store snapshots; source freshness performs bounded local read-only hashing.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .memory_governance import (
    PRINCIPAL_PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
    canonical_memory_scope,
    contains_credential_like_material,
    evaluate_memory_replay,
)
from .memory_principals import audience_policy_digest, parse_principal_context, principal_recall_decision
from .project_identity import RESOLVER_VERSION
from .memory_recall_support import (
    LEGACY_MEMORY_SCOPE_SCHEMA_VERSION,
    LEGACY_PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
    MEMORY_SCOPE_SCHEMA_VERSION,
    PROJECT_MEMORY_RECALL_PACK_SCHEMA_VERSION,
    PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
    _ADMISSION_VERACITY_DEFAULT_PCT,
    _ADMISSION_VERACITY_WEIGHT_PCT,
    _AGE_TIER_BOUNDS_DAYS,
    _AGE_TIER_WEIGHTS,
    _EXPIRES_SOON_DAYS,
    _INSPECTABLE_STALE_REASONS,
    _MEMORY_ATTENTION_RANK,
    _MEMORY_CADENCE_DEFAULTS,
    _MEMORY_PINS_LIMIT,
    _RECALL_BM25_B,
    _RECALL_BM25_K1,
    _RECALL_BM25_RECORD_TYPE_WEIGHT,
    _RECALL_BM25_TAG_WEIGHT,
    _RECALL_COMMON_TERM_MIN_CANDIDATES,
    _RECALL_COMMON_TERM_SHARE_PCT,
    _RECALL_RRF_K,
    _RECALL_RRF_WEIGHTS,
    _RECALL_SCORE_SCALE,
    _TEMPORAL_RELEVANCE_BANDS,
    _REVIEW_DUE_SOON_DAYS,
    _attach_recall_ranking,
    _attention_disclosure,
    _cadence_value,
    _empty_recall_pack,
    _freshness_warnings,
    _memory_query_split,
    _memory_relevance,
    _normalize_evaluator_timestamps,
    _ranking_field,
    _ranking_flag,
    _recall_evidence_fields,
    _recall_exclusion,
    _recall_item,
    _record_attention_tier,
    _record_perspective_matches,
    _record_staleness,
    _redacted_metadata_label,
    _replay_evaluation,
    _resolve_query_intent,
    _scope,
    newest_record,
    normalized_summary_key,
    recall_pack_policy,
    record_subject,
)


@dataclass(frozen=True)
class MemoryRecallSelection:
    """Prepared selection, never proof of rendering, host delivery or model use."""

    pack: dict[str, Any]
    scope_allowlist: tuple[dict[str, str], ...]
    scope_status: str
    exclusion_reason_counts: dict[str, int]
    configuration: dict[str, object]
    configuration_id: str
    principal_decision: dict[str, object] = field(default_factory=dict)
    audience_policy_digest: str = ""


def resolve_scope_allowlist(
    allowed_scopes: list[dict[str, str]] | tuple[dict[str, str], ...] | None,
    *,
    required_scope_kinds: tuple[str, ...] = ("project",),
    inspection: bool = False,
) -> tuple[tuple[dict[str, str], ...], str]:
    """Validate explicit labels without deriving authority from stored records.

    Missing, empty or invalid required scope fails closed. Inspection without
    any allowlist is the only wildcard, for the existing operator facade.
    """
    if inspection and allowed_scopes is None:
        return (), "inspection"
    scopes = []
    for raw in allowed_scopes or ():
        if contains_credential_like_material(str(raw)):
            raise ValueError("credential-like recall selector is not allowed")
        try:
            canonical = canonical_memory_scope({**raw})
        except (ValueError, TypeError):
            return (), "unresolved"
        scope = {"kind": str(canonical["kind"]), "ref": str(canonical["ref"])}
        if not scope["ref"].strip():
            return (), "unresolved"
        if scope not in scopes:
            scopes.append(scope)
    if not inspection and sum(scope["kind"] == "project" for scope in scopes) > 1:
        return (), "unresolved"
    if not scopes or any(kind not in {scope["kind"] for scope in scopes} for kind in required_scope_kinds):
        return (), "unresolved"
    return tuple(sorted(scopes, key=lambda scope: (scope["kind"], scope["ref"]))), "resolved"


def _selection_result(
    pack: dict[str, Any], scopes: tuple[dict[str, str], ...], scope_status: str,
    hidden_exclusions: Counter[str], *, limit: int, max_chars: int | None,
    inspection: bool, include_stale: bool, include_archived: bool,
    principal_decision: dict[str, object], audience_digest: str,
    query_fallback: bool = True,
) -> MemoryRecallSelection:
    counts = hidden_exclusions.copy()
    counts.update(str(item["reason"]) for item in pack["excluded_records"])
    configuration = {
        **effective_recall_configuration(),
        "scope_allowlist": list(scopes),
        "project_identity": next((scope["ref"] for scope in scopes if scope["kind"] == "project"), ""),
        "scope_status": scope_status,
        "perspective": pack["perspective"],
        "query_intent": pack["query_intent"],
        "inspection": inspection,
        "include_stale": include_stale,
        "include_archived": include_archived,
        "limit": max(limit, 0),
        "max_chars": max_chars,
        "recall_enabled": bool(pack["enabled"]),
        "due_soon_days": _cadence_value(pack["policy"], "due_soon_days"),
        "principal_decision": {
            key: principal_decision.get(key)
            for key in ("binding_state", "principal_ref", "actor_kind", "shared_surface", "context_digest")
        },
        "audience_policy_digest": audience_digest,
        # Replaces the fallback's rule name only when it is off, so every
        # configuration built with the fallback keeps its earlier identity.
        **({"query_fallback": "off"} if not query_fallback else {}),
    }
    configuration_id = hashlib.sha256(json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return MemoryRecallSelection(
        pack,
        scopes,
        scope_status,
        dict(sorted(counts.items())),
        configuration,
        configuration_id,
        principal_decision,
        audience_digest,
    )


def effective_recall_configuration() -> dict[str, object]:
    """Every constant the recall ladder ranks, decays, and cuts with.

    A retrieval regression report is only comparable against another report
    built under the same retrieval configuration, so the configuration has to
    be readable rather than inferred from the sorted output. Reading the live
    constants here -- not a copy of their values -- is the point: retuning a
    weight changes this projection, which changes the report's configuration
    digest, which is what makes two reports refuse to be compared.
    """
    return {
        "selector_schema_version": "omh_memory_recall_selector/v1",
        "resolver_version": RESOLVER_VERSION,
        "scope_policy": "explicit_allowlist/v1",
        "recall_pack_schema_version": PROJECT_MEMORY_RECALL_PACK_SCHEMA_VERSION,
        "rrf_k": _RECALL_RRF_K,
        "rrf_weights": dict(sorted(_RECALL_RRF_WEIGHTS.items())),
        "relevance": {
            "model": "bm25f_without_idf_whole_multiple_length/v2",
            "k1": _RECALL_BM25_K1,
            "b": _RECALL_BM25_B,
            "tag_weight": _RECALL_BM25_TAG_WEIGHT,
            "record_type_weight": _RECALL_BM25_RECORD_TYPE_WEIGHT,
            "score_scale": _RECALL_SCORE_SCALE,
            "stemmer": "light_english_suffix/v1",
            "record_type_needs_content_hit": True,
            "stemmed_only_overlap": "counts_when_the_pack_has_an_unstemmed_match/v1",
            "temporal_relevance_bands": _TEMPORAL_RELEVANCE_BANDS,
            "primary_key": "coverage_2_per_content_term_plus_1_per_tag/v2",
            "query_closed_lists": "function_words_fillers_ko_runs_prefixes_ja_zh_cuts/v3",
            "listed_terms": "order_within_one_coverage_only/v1",
            "listed_word_kept_when": "no_content_term_past_two_latin_chars_or_all_caps_or_capitalized_mid_sentence/v2",
            "store_common_terms": {
                "rule": "never_match_alone_unless_tagged_all_common_kept/v1",
                "population": "live_distinct_candidates/v1",
                "min_candidates": _RECALL_COMMON_TERM_MIN_CANDIDATES,
                "share_pct_exceeded": _RECALL_COMMON_TERM_SHARE_PCT,
            },
        },
        "temporal_recency_weight": 2.0,
        "age_tier_bounds_days": list(_AGE_TIER_BOUNDS_DAYS),
        "age_tier_weights": list(_AGE_TIER_WEIGHTS),
        "attention_rank": dict(sorted(_MEMORY_ATTENTION_RANK.items())),
        "admission_veracity_weight_pct": dict(sorted(_ADMISSION_VERACITY_WEIGHT_PCT.items())),
        "admission_veracity_default_pct": _ADMISSION_VERACITY_DEFAULT_PCT,
        "pins_limit": _MEMORY_PINS_LIMIT,
        "inspectable_stale_reasons": sorted(_INSPECTABLE_STALE_REASONS),
        "expires_soon_days": _EXPIRES_SOON_DAYS,
        "review_due_soon_days": _REVIEW_DUE_SOON_DAYS,
        "cadence_defaults": dict(sorted(_MEMORY_CADENCE_DEFAULTS.items())),
        # Behaviour switches with no tunable constant: naming them here is
        # what makes a report built before either existed refuse comparison.
        "query_fallback": "active_tier_unless_unstemmed_common_terms_only/v2",
        "duplicate_collapse": "normalized_exact_match/v1",
        "subject_collapse": "newest_non_retired_per_scope_subject/v2",
        "subject_score_transfer": "kept_record_shares_a_query_term/v1",
    }


def recall_revision(record: Mapping[str, Any]) -> str:
    """What a record says as served: its stored revision and the text a pack renders.

    The live provider skips a record it already put into the conversation
    (`session_served`) until this changes. The stored `revision` moves when the
    operator lifecycle rewrites a record; the summary, type and open/settled
    state are what the rendered element carries, so an edit that leaves the
    revision alone still counts. A confirm moves neither and is not re-served.
    """
    revision = record.get("revision")
    revision = revision if isinstance(revision, int) and not isinstance(revision, bool) else 0
    rendered = json.dumps(
        [str(record.get("summary", "") or ""), str(record.get("record_type", "") or ""), str(record.get("resolution", "") or "")],
        ensure_ascii=False,
    )
    return f"{revision}:{hashlib.sha256(rendered.encode('utf-8')).hexdigest()[:16]}"


def _subject_group(record: dict[str, Any]) -> tuple[str, str, str] | None:
    """(scope kind, scope ref, subject) for a record that declares a subject."""
    subject = record_subject(record)
    if not subject:
        return None
    scope = record.get("scope") if isinstance(record.get("scope"), dict) else {}
    return (str(scope.get("kind", "")), str(scope.get("ref", "")), subject)


def _current_subject_holders(pool: list[dict[str, Any]]) -> dict[tuple[str, str, str], str]:
    """The record id that holds each (scope kind, scope ref, subject) now.

    A subject is the slug the model declared at capture (`deploy-branch`), so
    two records in one scope carrying it are two values of one thing, and only
    the newest (`newest_record`) is current. The pool is every record the lens
    admits that is still in the store -- whatever its attention tier or
    eligibility -- so a superseded value cannot come back when the newest one
    expires, goes stale or is archived; the subject still says it was replaced.
    Only two structured fields are read, never the summaries, and a record
    with no subject never joins a group.
    """
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for record in pool:
        group = _subject_group(record)
        if group is not None:
            groups.setdefault(group, []).append(record)
    return {group: str(newest_record(members).get("record_id", "")) for group, members in groups.items()}


def _collapse_duplicate_summaries(
    included: list[dict[str, object]], *, pins: set[str]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """One pack slot per normalized summary; the others are named, not dropped.

    Two approved records saying the same thing would spend two slots of the
    budget on one fact. Capture already flags the second as `duplicate_of`,
    but review may approve both, so the pack keeps one: a pinned record first
    (a pin is the operator's explicit anchor), then the newest `approved_at`,
    then the smaller record id. The match is exact after normalization --
    never similarity -- so two facts that merely look alike both stay.
    """
    groups: dict[str, list[dict[str, object]]] = {}
    for item in included:
        key = normalized_summary_key(str(item.get("summary", "")))
        if key:
            groups.setdefault(key, []).append(item)
    keep_by_id: dict[str, str] = {}
    for group in groups.values():
        if len(group) < 2:
            continue
        # max() returns the first maximal element, so sorting by record id
        # first makes the smaller id win an equal (pinned, approved_at) pair.
        kept = max(
            sorted(group, key=lambda item: str(item.get("record_id", ""))),
            key=lambda item: (str(item.get("record_id", "")) in pins, str(item.get("approved_at", ""))),
        )
        for item in group:
            if item is not kept:
                keep_by_id[str(item.get("record_id", ""))] = str(kept.get("record_id", ""))
    remaining: list[dict[str, object]] = []
    duplicates: list[dict[str, object]] = []
    for item in included:
        record_id = str(item.get("record_id", ""))
        if record_id not in keep_by_id:
            remaining.append(item)
            continue
        duplicates.append(
            {
                "record_id": record_id,
                "reason": "duplicate_record",
                "duplicate_of": keep_by_id[record_id],
                "staleness": item.get("staleness", {"state": "not_checked"}),
                **_recall_evidence_fields(item.get("replay_evaluation")),
            }
        )
    return remaining, duplicates


def _evaluate_memory_artifact(
    artifact: dict[str, Any],
    *,
    operation_states: dict[str, str] | None = None,
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
        and artifact.get("schema_version") in {
            PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
            PRINCIPAL_PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
            MEMORY_SCOPE_SCHEMA_VERSION,
        }
        and (not isinstance(review_id, str) or not review_id or not review_resolver or review_id not in review_resolver)
    ):
        # The core boundary supplies a resolver, so an approval without its
        # immutable review record cannot become eligible through an omitted id.
        result = {**result, "eligible": False, "reason_code": "review_not_found"}
    operation_id = artifact.get("operation_id")
    if result.get("eligible") is True and isinstance(operation_id, str) and operation_id:
        if not operation_states or operation_states.get(operation_id) != "completed":
            result = {**result, "eligible": False, "reason_code": "operation_incomplete"}
    return _replay_evaluation(artifact, result)


def select_memory_recall(
    records: list[dict[str, Any]],
    query: str = "",
    *,
    allowed_scopes: list[dict[str, str]] | tuple[dict[str, str], ...] | None = None,
    required_scope_kinds: tuple[str, ...] = ("project",),
    inspection: bool = False,
    review_resolver: dict[str, dict[str, object]] | None = None,
    operation_states: dict[str, str] | None = None,
    policy: dict[str, object] | None = None,
    usage: Mapping[str, Mapping[str, object]] | None = None,
    pins: set[str] | None = None,
    executor_target: str = "generic",
    session_id: str = "",
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
    principal_context: dict[str, object] | None = None,
    shared_surface: bool = False,
    query_fallback: bool = True,
    session_served: Mapping[str, str] | None = None,
) -> MemoryRecallSelection:
    """One read-only eligibility/ranking/budget contract for every recall surface.

    Delivery requires resolved explicit scopes. Inspection is an explicit,
    read-only compatibility affordance and must never be served as live recall.
    Foreign IDs/content are omitted; only aggregate exclusion counts survive.

    ``query_fallback`` False is the live per-turn and tool recall contract: a
    query with no indexable terms (or none at all) serves pinned records only,
    and a query that matches nothing serves no active-tier fallback. Handoffs,
    the CLI and inspection keep the default. ``session_served`` maps the
    records a conversation already holds to their `recall_revision`; a record
    still at that revision is excluded as `served_this_session` before the
    budget cut, so it never spends a slot.
    """
    policy = dict(policy) if policy is not None else {"recall_enabled": True, **_MEMORY_CADENCE_DEFAULTS}
    now = now if now is not None else datetime.now(timezone.utc)
    scopes, scope_status = resolve_scope_allowlist(allowed_scopes, required_scope_kinds=required_scope_kinds, inspection=inspection)
    hidden_exclusions: Counter[str] = Counter()
    if not inspection and include_stale:
        raise ValueError("include_stale is inspection-only")
    primary_scope = next((scope for scope in scopes if scope["kind"] == "project"), scopes[0] if scopes else {})
    scope_kind = primary_scope.get("kind")
    scope_ref = primary_scope.get("ref")
    structural_selectors = (scope_kind, scope_ref, observer, observed)
    if any(
        value is not None and contains_credential_like_material(str(value))
        for value in structural_selectors
    ):
        raise ValueError("credential-like recall selector is not allowed")
    executor_target = _redacted_metadata_label(executor_target)
    session_id = _redacted_metadata_label(session_id)
    scope_kind = _redacted_metadata_label(scope_kind) if scope_kind is not None else None
    scope_ref = _redacted_metadata_label(scope_ref) if scope_ref is not None else None
    # Lens labels normalize exactly like capture labels: capture lowercases
    # and strips, so a raw "--observed Codex" here would silently match
    # nothing and read as "never captured".
    observer = _redacted_metadata_label(str(observer or "").strip().lower()) or None
    observed = _redacted_metadata_label(str(observed or "").strip().lower()) or None
    if not inspection and observed is None:
        observed = str(executor_target or "").strip().lower() or "choose"
    query_intent = _resolve_query_intent(query, query_intent)
    parsed_principal = parse_principal_context(principal_context, expected_session=session_id)
    principal_ref = str(parsed_principal.get("principal", "")) if parsed_principal is not None else ""
    actor_kind = str(parsed_principal.get("actor_kind", "unknown")) if parsed_principal is not None else "unknown"
    principal_counts: Counter[str] = Counter()
    allowed_identity_count = 0
    audience_digests: set[str] = set()
    context_projection = {
        key: parsed_principal.get(key)
        for key in ("principal", "profile_ref", "surface_ref", "session_ref", "turn_ref", "actor_kind", "binding_state")
    } if parsed_principal is not None else {}
    principal_metadata = {
        "binding_state": str(parsed_principal.get("binding_state", "unbound")) if parsed_principal is not None else "unbound",
        "principal_ref": principal_ref or None,
        "actor_kind": actor_kind,
        "shared_surface": bool(shared_surface),
        "context_digest": hashlib.sha256(json.dumps(context_projection, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
    }
    task_ref = {
        "sha256": hashlib.sha256(query.encode("utf-8")).hexdigest() if query else "",
        "length": len(query),
        "query_supplied": bool(query),
    }
    if scope_status == "unresolved" or not bool(policy.get("recall_enabled", True)):
        pack = _empty_recall_pack(
            policy,
            executor_target=executor_target,
            session_id=session_id,
            task_ref=task_ref,
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            reason="scope_unresolved" if scope_status == "unresolved" else "project_memory_disabled",
        )
        pack["perspective"] = {"observer": observer or "", "observed": observed or ""}
        pack["query_intent"] = query_intent
        return _selection_result(
            pack,
            scopes,
            scope_status,
            hidden_exclusions,
            limit=limit,
            max_chars=max_chars,
            inspection=inspection,
            include_stale=include_stale,
            include_archived=include_archived,
            principal_decision={**principal_metadata, "allowed_count": 0, "denied_count": 0, "reason_counts": {}},
            audience_digest=hashlib.sha256(b"").hexdigest(),
            query_fallback=query_fallback,
        )
    pins = set(pins or ())
    usage = usage or {}
    included: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    no_overlap_active: list[tuple[dict[str, object], dict[str, Any], dict[str, object], dict[str, object], int]] = []
    archived_excluded = 0
    # Relevance is scored against the whole eligible candidate set (length is
    # normalized against its average summary), so the first pass
    # decides lens, tier and eligibility and holds each record's outcome as a
    # step; the second pass resolves the steps in store order, which keeps the
    # order of `excluded_records` exactly what one pass produced.
    steps: list[tuple[str, Any]] = []
    candidates: list[tuple[dict[str, Any], dict[str, object], dict[str, object], str, bool]] = []
    # Every lens-admitted record that declares a subject, whatever its tier or
    # eligibility: the subject collapse decides "current" over all of them.
    subject_pool: list[dict[str, Any]] = []
    # A channel named in the allowlist admits its own identity-unbound records
    # on a shared surface; no other scope does (`principal_recall_decision`).
    channel_scopes = tuple(scope for scope in scopes if scope["kind"] == "channel")
    for record in records:
        identity_decision = principal_recall_decision(record, parsed_principal, shared_surface=shared_surface, channel_scopes=channel_scopes)
        reason_code = str(identity_decision["reason_code"])
        principal_counts[reason_code] += 1
        if not bool(identity_decision["allowed"]):
            hidden_exclusions[reason_code] += 1
            continue
        allowed_identity_count += 1
        audience_digests.add(audience_policy_digest(record))
        if (scopes or not inspection) and record.get("scope") not in scopes:
            hidden_exclusions["scope_mismatch"] += 1
            continue
        # Perspective mismatch skips silently, exactly like scope mismatch:
        # the record belongs to another actor's lens, not to this pack.
        if not _record_perspective_matches(record, observer=observer, observed=observed):
            hidden_exclusions["perspective_mismatch"] += 1
            continue
        if record_subject(record):
            subject_pool.append(record)
        attention_tier = _record_attention_tier(record, override=attention_override)
        if attention_tier == "archive" and not include_archived:
            # Archive is an attention tier, not a deletion. The record stays
            # in `records/`, stays readable, and returns to any pack built
            # with include_archived -- but it leaves the default working
            # context NAMED, never silently, so the operator can always see
            # what the archive is holding back.
            steps.append(
                (
                    "excluded",
                    {
                        "record_id": _redacted_metadata_label(record.get("record_id", "")),
                        "reason": "archived_tier",
                        "staleness": {"state": "not_checked"},
                    },
                )
            )
            archived_excluded += 1
            continue
        evaluation = _evaluate_memory_artifact(
            record,
            operation_states=operation_states,
            now=now,
            requested_scope=record.get("scope") if not inspection or scopes else None,
            review_resolver=review_resolver,
            stale_override=stale_override,
            run_id=run_id,
        )
        staleness = _record_staleness(record, now=now, due_soon_days=_cadence_value(policy, "due_soon_days"))
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
        # The open ceiling is NOT folded here: the shared evaluator decides
        # `unresolved_expired` beside `expired_*` (so recall, `memory status`,
        # and the bridge agree), and the staleness verdict mirrors it the way
        # it mirrors the retention classifier. It is terminal exactly like a
        # retention expiry -- not inspectable through --include-stale, never
        # resurrected by a confirm -- so the operator sees that a question
        # died unanswered rather than that a fact aged out.
        if not bool(evaluation["eligible"]):
            # --include-stale is an inspection affordance: it surfaces
            # records whose ONLY problem is unconfirmed freshness -- a passed
            # revalidation deadline or a moved source -- carrying their
            # ineligible replay evidence so the pack cannot be attached to a
            # handoff. Expired and otherwise-ineligible records stay excluded
            # regardless.
            if include_stale and str(evaluation.get("reason_code", "")) in _INSPECTABLE_STALE_REASONS:
                steps.append(("candidate", len(candidates)))
                candidates.append((record, evaluation, staleness, attention_tier, True))
                continue
            steps.append(("excluded", _recall_exclusion(record, evaluation, staleness=staleness)))
            continue
        steps.append(("candidate", len(candidates)))
        candidates.append((record, evaluation, staleness, attention_tier, False))
    holders = _current_subject_holders(subject_pool)
    replaced_by: dict[int, str] = {}
    group_members: dict[tuple[str, str, str], list[int]] = {}
    for index, candidate in enumerate(candidates):
        group = _subject_group(candidate[0])
        if group is None:
            continue
        group_members.setdefault(group, []).append(index)
        holder = holders.get(group, "")
        if holder and holder != str(candidate[0].get("record_id", "")):
            replaced_by[index] = holder
    # Which query terms are store-common is counted only over the records this
    # pack could serve: a subject's old values and inspection-only records are
    # scored, but they never make a word common.
    live = [not candidate[4] and index not in replaced_by for index, candidate in enumerate(candidates)]
    relevance = _memory_relevance([candidate[0] for candidate in candidates], query, live)
    scores, unstemmed, coverage = list(relevance.scores), relevance.unstemmed, list(relevance.coverage)
    common_only = list(relevance.common_only)
    common_terms_only_excluded = False
    # The current value of a subject takes the best (coverage, score) in its
    # group, but only when it shares a query term itself: a query that names
    # the old wording still finds the new value of the same thing, while a
    # record that matches nothing is never pulled in on another record's words
    # (two facts given one slug by mistake must not serve the unrelated one).
    # A store-common word counts as shared: a current value that met the query
    # only on one (`common_only`) takes an older value's match on another
    # word, and is then a match, not `common_terms_only`.
    for members in group_members.values():
        best = max((coverage[index], scores[index]) for index in members)
        for index in members:
            if index not in replaced_by and (scores[index] > 0 or common_only[index]) and best[1] > 0:
                coverage[index], scores[index] = best
                common_only[index] = False
    # A stemmed-only match counts as overlap only when some live candidate also
    # shares an unstemmed query token. Otherwise the query met the store only
    # through a suffix rule (stats -> stat -> "State is kept in Redux"), and it
    # falls back to the active tier exactly as a query matching nothing does;
    # the stemmed matches keep their scores, so they lead that pack. A record
    # that met the query only on store-common words (`common_only`, score 0)
    # keeps its unstemmed flag, so one that writes such a word as the query
    # does counts here.
    unstemmed_somewhere = any(unstemmed[index] for index in range(len(candidates)) if live[index])

    def overlaps(index: int) -> bool:
        return scores[index] > 0 and (unstemmed[index] or unstemmed_somewhere)

    # No query, or one with no indexable terms, scores every record 1 above:
    # with the fallback that serves the whole active and reference set, which
    # on a live turn ("ok", "야", a cleaned-away notice) is unrelated memory.
    unqueried = not _memory_query_split(query)[0]

    for kind, value in steps:
        if kind == "excluded":
            excluded.append(value)
            continue
        record, evaluation, staleness, attention_tier, inspection_only = candidates[value]
        score = scores[value]
        if value in replaced_by:
            exclusion = _recall_exclusion(record, evaluation, staleness=staleness, reason="superseded_by_subject")
            exclusion["superseded_by"] = _redacted_metadata_label(replaced_by[value])
            exclusion["subject"] = record_subject(record)
            excluded.append(exclusion)
            continue
        if inspection_only:
            if not query or overlaps(value) or str(record.get("record_id", "")) in pins:
                included.append(
                    _recall_item(record, score=score, staleness=staleness, evaluation=evaluation, attention_tier=attention_tier)
                )
                continue
            excluded.append(_recall_exclusion(record, evaluation, staleness=staleness))
            continue
        # A pinned anchor is always in context: it skips only the
        # no_query_overlap cut, never an eligibility check above.
        if not query_fallback and unqueried and str(record.get("record_id", "")) not in pins:
            excluded.append(_recall_exclusion(record, evaluation, staleness=staleness, reason="no_query_overlap"))
            continue
        if query and not overlaps(value) and str(record.get("record_id", "")) not in pins:
            if common_only[value]:
                # It met the query only on words most candidates hold
                # (`_store_common_terms`): named apart, and never readmitted.
                excluded.append(_recall_exclusion(record, evaluation, staleness=staleness, reason="common_terms_only"))
                common_terms_only_excluded = True
                continue
            exclusion = _recall_exclusion(record, evaluation, staleness=staleness, reason="no_query_overlap")
            excluded.append(exclusion)
            if attention_tier == "active":
                no_overlap_active.append((exclusion, record, evaluation, staleness, max(score, 1)))
            continue
        included.append(_recall_item(record, score=score, staleness=staleness, evaluation=evaluation, attention_tier=attention_tier))
    # A chat message that shares no token with any record used to hand the
    # model an empty pack while approved active memories sat in the store,
    # every such turn. When the query matched nothing at all -- no pin, no
    # overlap -- the active tier is served as an unqueried pack would serve
    # it, and the pack says so. Reference stays keyword-gated and archive
    # stays explicit, and any overlap at all (a partial match) means the
    # query did its job, so nothing is re-admitted then. Overlap only on
    # store-common words (`common_terms_only`) is not a match, and it does not
    # fall back either: the query did meet the store, and the fallback would
    # serve the records that do not even share the common word. That holds
    # only when some live record shares an unstemmed query token; without one
    # the common-word hits are stemmed-only too, the query met the store only
    # through a suffix rule, and it falls back as above (the common-only
    # records still stay out). With nothing included, `common_overlap` equals
    # `unstemmed_somewhere`: a live record that shares an unstemmed query token
    # and was not included can only be common-only; the first conjunct names
    # that reason. A query with no indexable tokens never reaches here: it
    # already scores every record 1. A record that met the query only through
    # stemming is readmitted with its score, so it leads the fallback pack;
    # every other one scores 1.
    fallback_served: dict[str, object] | None = None
    common_overlap = common_terms_only_excluded and unstemmed_somewhere
    if query_fallback and query and not included and no_overlap_active and not common_overlap:
        readmitted = {id(entry) for entry, *_ in no_overlap_active}
        excluded = [entry for entry in excluded if id(entry) not in readmitted]
        included = [
            _recall_item(record, score=score, staleness=staleness, evaluation=evaluation, attention_tier="active")
            for _, record, evaluation, staleness, score in no_overlap_active
        ]
        fallback_served = {"mode": "active_tier", "reason": "no_query_overlap", "readmitted_count": len(included)}
    included, duplicates = _collapse_duplicate_summaries(included, pins=pins)
    excluded.extend(duplicates)
    if session_served:
        # After the fallback and the duplicate collapse decided what this
        # query answers, so a record the conversation already holds is not
        # replaced by an unrelated one, and before the budget cut.
        by_id = {str(candidate[0].get("record_id", "")): candidate for candidate in candidates}
        fresh: list[dict[str, object]] = []
        for item in included:
            record_id = str(item.get("record_id", ""))
            candidate = by_id.get(record_id)
            if candidate is not None and session_served.get(record_id) == recall_revision(candidate[0]):
                excluded.append(_recall_exclusion(candidate[0], candidate[1], staleness=candidate[2], reason="served_this_session"))
                continue
            fresh.append(item)
        included = fresh
    _attach_recall_ranking(
        included,
        usage,
        pins=pins,
        now=now,
        recency_weight=2.0 if query_intent == "temporal" else _RECALL_RRF_WEIGHTS["recency"],
        temporal=query_intent == "temporal",
        coverage={str(candidate[0].get("record_id", "")): coverage[index] for index, candidate in enumerate(candidates)},
    )
    # Pinned anchors lead, then attention tier, then relevance; the decayed
    # fused score orders records only within an equal relevance rank. A weaker
    # keyword match can therefore never displace a stronger unpinned one of
    # the same tier -- including across the budget cut below -- while recency,
    # delivery usage, and age tier decide ties and unqueried packs. Attention
    # sits above relevance on purpose: that is what "build recall packs from
    # active records first" means, and it is the one place the tier acts.
    # Pins take priority within the budget but never own it outright: at most
    # limit-1 pinned slots lead the pack (minimum one), and further pins
    # compete as normal records, so a fully-used pin budget cannot blank
    # query-driven recall.
    ranked_key = lambda item: (  # noqa: E731 - shared by both sort passes below
        int(_ranking_field(item, "attention_rank")),
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
    pack = {
        "schema_version": PROJECT_MEMORY_RECALL_PACK_SCHEMA_VERSION,
        "enabled": True,
        "executor_target": executor_target,
        "session_id": session_id,
        "task_ref": task_ref,
        "policy": recall_pack_policy(policy),
        "scope": _scope(scope_kind or "project", scope_ref or "default"),
        "perspective": {"observer": observer or "", "observed": observed or ""},
        "query_intent": query_intent,
        # Present only when the active-tier fallback served this pack, so a
        # pack the query answered stays byte-identical to before it existed.
        **({"query_fallback": fallback_served} if fallback_served else {}),
        "included_records": included,
        "excluded_records": excluded,
        "freshness_warnings": _freshness_warnings(included, excluded),
        "attention": _attention_disclosure(included, archived_excluded, include_archived=include_archived),
        "record_count": len(included),
        # One count per pack, never a banner per record: the cost of carrying
        # open questions is visible without drowning the records themselves.
        "unresolved_delivered": sum(1 for item in included if str(item.get("resolution", "")) == "open"),
        "truncated": budget_exhausted,
        "redaction_policy": "metadata_only",
        "claim_boundary": (
            "Memory recall packs contain reviewed OMH project summaries only; "
            "they are prepared context, not execution, review, CI, merge, or Hermes internal-memory evidence."
        ),
    }

    audience_digest = hashlib.sha256("".join(sorted(audience_digests)).encode("utf-8")).hexdigest()
    return _selection_result(
        pack,
        scopes,
        scope_status,
        hidden_exclusions,
        limit=limit,
        max_chars=max_chars,
        inspection=inspection,
        include_stale=include_stale,
        include_archived=include_archived,
        principal_decision={
            **principal_metadata,
            "allowed_count": allowed_identity_count,
            "denied_count": sum(principal_counts.values()) - allowed_identity_count,
            "reason_counts": dict(sorted(principal_counts.items())),
        },
        audience_digest=audience_digest,
        query_fallback=query_fallback,
    )
