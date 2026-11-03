"""Closed, metadata-only recall diagnosis values over the canonical receipt contract."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import re
from typing import Final, Literal, TypedDict

from ..plugin_bundle.omh.memory_governance import SCOPE_KINDS
from ..system.metadata_safety import require_opaque_metadata_ref

Stage = Literal['not_found', 'pending_or_rejected', 'invalid_or_superseded',
                'scope_or_perspective_mismatch', 'stale_expired_or_archived',
                'relevance_attention_or_budget_exclusion', 'selected_not_rendered',
                'rendered_delivery_not_observed', 'delivered_model_use_unknown', 'used', 'unresolved']


class IncidentInputError(ValueError):
    """A bounded field name, never its private input, identifies the refusal."""
    def __init__(self, field: str):
        self.field = field
        super().__init__(f'invalid recall incident field: {field}')


@dataclass(frozen=True, slots=True)
class RecallIncidentRequest:
    """One expected anchor and the existing canonical recall lens/budget."""
    record_id: str = ''
    claim_digest: str = ''
    query: str = ''
    session_id: str = ''
    scope_kind: str = 'project'
    scope_ref: str = ''
    observer: str | None = None
    observed: str | None = None
    limit: int = 6
    max_chars: int | None = None
    provider_served_count: int | None = None
    now: datetime | None = None

    def __post_init__(self) -> None:
        if bool(self.record_id) == bool(self.claim_digest):
            raise IncidentInputError('anchor')
        if self.record_id and not re.fullmatch(r'(?:mem|cand)_[0-9a-f]{16}', self.record_id):
            raise IncidentInputError('record_id')
        if self.claim_digest and not re.fullmatch(r'[0-9a-f]{64}', self.claim_digest):
            raise IncidentInputError('claim_digest')
        if self.scope_kind not in SCOPE_KINDS:
            raise IncidentInputError('scope_kind')
        for field in ('scope_ref', 'observer', 'observed'):
            value = getattr(self, field)
            if value is not None and not (field == 'scope_ref' and value == '' and self.scope_kind == 'project'):
                require_opaque_metadata_ref(value, field=field)
        for field in ('limit', 'max_chars', 'provider_served_count'):
            value = getattr(self, field)
            if value is not None and (type(value) is not int or value < 0):
                raise IncidentInputError(field)
        if self.limit < 1 or (self.max_chars is not None and self.max_chars < 1):
            raise IncidentInputError('budget')
        if self.now is not None and self.now.tzinfo is None:
            raise IncidentInputError('now')


class EvidenceSurface(TypedDict):
    status: Literal['observed', 'unavailable', 'not_authoritative']
    basis: str


class Remediation(TypedDict):
    action: str
    state: str
    requires: list[str]


class Diagnosis(TypedDict):
    stage: Stage
    reason_code: str
    evidence_basis: str
    fault_domain: str
    omh_correction_proposed: bool
    remediation: Remediation
    authorizes_mutation: bool


class Incident(Diagnosis):
    schema_version: str
    incident_id: str
    anchor: dict[str, str]
    configuration_identity: dict[str, str]
    evidence_surfaces: dict[str, EvidenceSurface]
    last_proven_stage: str
    delivery_observed: None
    model_use_observed: None
    external_review_status: str
    redaction_policy: str
    claim_boundary: str


REASON_STAGES: Final[dict[str, Stage]] = {
    'not_found': 'not_found',
    'pending_review': 'pending_or_rejected', 'rejected': 'pending_or_rejected',
    'blocked_review_required': 'pending_or_rejected',
    'superseded': 'invalid_or_superseded', 'payload_digest_mismatch': 'invalid_or_superseded',
    'invalid_record': 'invalid_or_superseded', 'review_required_legacy': 'invalid_or_superseded',
    'review_not_found': 'invalid_or_superseded', 'review_identity_mismatch': 'invalid_or_superseded',
    'scope_mismatch': 'scope_or_perspective_mismatch', 'perspective_mismatch': 'scope_or_perspective_mismatch',
    'legacy_basename': 'scope_or_perspective_mismatch',
    'review_due': 'stale_expired_or_archived', 'stale_review_required': 'stale_expired_or_archived',
    'expired_standard': 'stale_expired_or_archived', 'expired_volatile': 'stale_expired_or_archived',
    'expired_durable': 'stale_expired_or_archived', 'archived_tier': 'stale_expired_or_archived',
    'retired': 'stale_expired_or_archived',
    'source_changed': 'stale_expired_or_archived', 'source_unverifiable': 'stale_expired_or_archived',
    'no_query_overlap': 'relevance_attention_or_budget_exclusion',
    'common_terms_only': 'relevance_attention_or_budget_exclusion',
    'attention_cut': 'relevance_attention_or_budget_exclusion', 'over_budget': 'relevance_attention_or_budget_exclusion',
    'duplicate_record': 'relevance_attention_or_budget_exclusion',
    'selected_not_rendered': 'selected_not_rendered',
    'rendered_delivery_not_observed': 'rendered_delivery_not_observed',
    'delivered_model_use_unknown': 'delivered_model_use_unknown', 'used': 'used',
    'selected_live_evidence_unavailable': 'unresolved', 'live_selection_excluded': 'unresolved',
    'store_unavailable': 'unresolved',
    'native_only_not_omh_reviewed': 'unresolved', 'selection_unresolved': 'unresolved',
    'ambiguous_anchor': 'unresolved', 'project_memory_disabled': 'unresolved',
}
ACTIONS: Final[dict[Stage, str]] = {
    'not_found': 'capture_for_review', 'pending_or_rejected': 'review_candidate',
    'invalid_or_superseded': 'review_correction', 'scope_or_perspective_mismatch': 'review_scope_lens',
    'stale_expired_or_archived': 'review_freshness',
    'relevance_attention_or_budget_exclusion': 'review_recall_selection',
    'selected_not_rendered': 'inspect_provider_rendering',
    'rendered_delivery_not_observed': 'inspect_host_delivery',
    'delivered_model_use_unknown': 'leave_model_use_unresolved',
    'used': 'no_change', 'unresolved': 'collect_record_bound_evidence',
}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def diagnosis(reason: str, basis: str) -> Diagnosis:
    """Unknown reason codes never become confident failures or mutation authority."""
    stage = REASON_STAGES.get(reason, 'unresolved')
    local = stage in ('not_found', 'pending_or_rejected', 'invalid_or_superseded',
                      'scope_or_perspective_mismatch', 'stale_expired_or_archived',
                      'relevance_attention_or_budget_exclusion')
    domain = {'selected_not_rendered': 'provider'}.get(stage, 'omh_control_plane' if local else 'unresolved')
    return {
        'stage': stage, 'reason_code': reason if reason in REASON_STAGES else 'selection_unresolved',
        'evidence_basis': basis, 'fault_domain': domain, 'omh_correction_proposed': local,
        'remediation': {'action': ACTIONS[stage], 'state': 'prepared_not_applied',
                        'requires': ['memory_curation_review/v1 approval', 'native_write_approval']},
        'authorizes_mutation': False,
    }


def diagnose_synthetic_recall_stage(reason: str) -> Diagnosis:
    """Exercise the stage model offline; this is NOT a receipt or incident writer input."""
    if reason not in REASON_STAGES:
        raise IncidentInputError('synthetic_reason')
    return diagnosis(reason, 'synthetic')


def recall_delivery_stage(
    *, rendered: bool, delivery_observed: bool | None, model_use_observed: bool | None,
    indexed: bool = False,
) -> tuple[str, str]:
    """Classify supplied observations without crossing a missing earlier stage.

    The live receipt validator currently admits only None for delivery/use.
    Synthetic cases can exercise later states without gaining live authority.
    """
    if not rendered:
        if indexed:
            return 'no_query_overlap', 'selected'
        return 'selected_not_rendered', 'selected'
    if delivery_observed is not True:
        return 'rendered_delivery_not_observed', 'rendered'
    if model_use_observed is not True:
        return 'delivered_model_use_unknown', 'delivered'
    return 'used', 'used'
