"""Read-only, expected-record diagnosis over canonical OMH recall selection.

A prepared pack and an aggregate provider count cannot prove rendering,
delivery, or model use. The provider's canonical prefetch receipt (#1452)
proves local rendering and return for one session, store and configuration;
host delivery and model use stay unknown even with it.
"""
from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..plugin_bundle.omh.hermes_memory import HERMES_MEMORY_FILES, read_hermes_memory_file
from ..plugin_bundle.omh.memory_prefetch_receipt import (
    MAX_PREFETCH_RECEIPT_BYTES, prefetch_receipt_path, validate_prefetch_receipt,
)
from ..plugin_bundle.omh.memory_recall_selector import select_memory_recall
from ..plugin_bundle.omh.memory_records import prefetch_required_scope_kinds
from ..plugin_bundle.omh.project_identity import LEGACY_BASENAME_STATE, legacy_project_scope, project_identity_root, resolve_project_identity
from ..system.local_store import atomic_write_json, read_json_object_result
from ..system.paths import OmhPaths
from . import memory
from ._memory_lifecycle_scan import json_files, read_json
from .memory_recall_incident_model import (
    EvidenceSurface, Incident, RecallIncidentRequest, diagnosis, digest,
    diagnose_synthetic_recall_stage, recall_delivery_stage,
)

__all__ = ['RecallIncidentRequest', 'build_memory_recall_incident',
           'write_memory_recall_incident', 'diagnose_synthetic_recall_stage']


def _read_live_receipt(paths: OmhPaths, request: RecallIncidentRequest, *, invocation_cwd: str | Path | None = None) -> tuple[EvidenceSurface, dict[str, Any] | None]:
    """Bind the provider's persisted receipt to this store, session, configuration and scope.

    Absent or unreadable proof is unknown. A receipt that exists but names a
    foreign schema, session, store, configuration or lens is rejected as
    evidence; its identities are still returned so the incident can cite them.
    """
    path = prefetch_receipt_path(paths.omh_home)
    try:
        if path.is_symlink():
            return {'status': 'unavailable', 'basis': 'receipt_unreadable'}, None
        if not path.is_file():
            return {'status': 'unavailable', 'basis': 'no_receipt_persisted'}, None
        with path.open('rb') as stream:
            raw = stream.read(MAX_PREFETCH_RECEIPT_BYTES + 1)
        if len(raw) > MAX_PREFETCH_RECEIPT_BYTES:
            return {'status': 'unavailable', 'basis': 'receipt_unreadable'}, None
        value = json.loads(raw.decode('utf-8'))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return {'status': 'unavailable', 'basis': 'receipt_unreadable'}, None
    errors = validate_prefetch_receipt(value)
    if errors or not isinstance(value, dict):
        return {'status': 'not_authoritative', 'basis': f'incompatible_receipt:{errors[0]}'}, None
    receipt: dict[str, Any] = value

    def rejected(basis: str) -> tuple[EvidenceSurface, dict[str, Any]]:
        return {'status': 'not_authoritative', 'basis': basis}, receipt

    if receipt['state'] != 'returned_to_host':
        return rejected('receipt_not_returned_to_host')
    if not request.session_id:
        return rejected('receipt_session_unbound')
    if receipt['session_id'] != request.session_id:
        return rejected('receipt_session_mismatch')
    store = receipt.get('store')
    home_digests = store.get('home_digests') if isinstance(store, dict) else None
    if not isinstance(home_digests, list) or digest(str(paths.omh_home.resolve())) not in home_digests:
        return rejected('receipt_store_mismatch')
    resolution = resolve_project_identity(invocation_cwd)
    if receipt.get('resolver_version') != resolution.resolver_version or receipt.get('project_identity') != resolution.identity:
        return rejected('receipt_project_identity_mismatch')
    lens = receipt['lens']
    perspective = lens['perspective']
    allowlist = [{**scope} for scope in lens['scope_allowlist'] if isinstance(scope, dict)]
    try:
        # The canonical selector recomputes the configuration identity for the
        # receipt's own lens under this profile's policy and the requested
        # budget; no record is evaluated and no hash logic is duplicated.
        # The receipt's own requirement: a project scope only when its
        # project identity resolved (`prefetch_scope_allowlist`).
        selection = select_memory_recall(
            [], allowed_scopes=allowlist, inspection=False,
            required_scope_kinds=prefetch_required_scope_kinds(str(receipt.get('project_identity', '') or '')),
            policy=memory.read_project_memory_policy(paths),
            observer=str(perspective.get('observer', '') or '') or None,
            observed=str(perspective.get('observed', '') or '') or None,
            query_intent=str(lens.get('query_intent', '') or '') or None,
            limit=request.limit, max_chars=request.max_chars, now=request.now,
        )
        principal = receipt.get('principal_decision')
        binding = {
            key: principal.get(key)
            for key in ('binding_state', 'principal_ref', 'actor_kind', 'shared_surface', 'context_digest')
        } if isinstance(principal, dict) else selection.configuration['principal_decision']
        configuration = {
            **selection.configuration,
            'principal_decision': binding,
            'audience_policy_digest': receipt.get('audience_policy_digest', selection.audience_policy_digest),
        }
        expected = digest(json.dumps(configuration, sort_keys=True, separators=(",", ":")))
    except (ValueError, TypeError):
        return rejected('incompatible_receipt:lens')
    if expected != receipt['configuration_id']:
        return rejected('receipt_configuration_mismatch')
    if {'kind': request.scope_kind, 'ref': request.scope_ref} not in allowlist:
        return rejected('receipt_scope_mismatch')
    return {'status': 'observed', 'basis': 'canonical_1452_receipt_bound'}, receipt


def _receipt_stage(receipt: dict[str, Any], record_id: str, claim_digest: str) -> tuple[str, str] | None:
    """(reason, last proven stage) for one record, or None when the receipt cites another revision."""
    rendered = {str(item['record_id']): str(item['content_digest']) for item in receipt['rendering']['rendered_records']}
    selected = [str(value) for value in receipt['selection']['selected_record_ids']]
    if record_id in rendered:
        if rendered[record_id] != claim_digest:
            return None
        return recall_delivery_stage(
            rendered=True, delivery_observed=receipt['delivery_observed'],
            model_use_observed=receipt['model_use_observed'],
        )
    if record_id in selected:
        return recall_delivery_stage(
            rendered=False, indexed=record_id in receipt['rendering'].get('indexed_records', []),
            delivery_observed=None, model_use_observed=None,
        )
    if record_id in receipt['selection'].get('served_this_session', []):
        # An earlier turn of this conversation carried it; that turn's receipt
        # is gone, so delivery stays unproven, but the case has a name.
        return 'served_this_session', 'selected'
    return 'live_selection_excluded', 'selected'


def build_memory_recall_incident(paths: OmhPaths, request: RecallIncidentRequest, *, invocation_cwd: str | Path | None = None) -> Incident:
    """Inspect an anchor under the active checkout, independently of store location."""
    if request.scope_kind == 'project' and not request.scope_ref:
        request = replace(request, scope_ref=resolve_project_identity(invocation_cwd).identity)
    pack = memory.build_project_memory_recall_pack(
        paths, request.query, session_id=request.session_id,
        scope_kind=request.scope_kind, scope_ref=request.scope_ref,
        observer=request.observer, observed=request.observed,
        limit=request.limit, max_chars=request.max_chars, now=request.now,
    )
    records, unreadable = memory.scan_project_memory_records(paths)
    surfaces: dict[str, EvidenceSurface] = {
        name: {'status': 'unavailable', 'basis': basis}
        for name, basis in (
            ('host_delivery', 'no_record_bound_observation'),
            ('model_use', 'no_record_bound_observation'),
            ('provider_availability', 'runtime_not_inspected'),
            ('provider_recall_status', 'not_supplied'),
        )
    }
    surfaces['live_prefetch_receipt'], receipt = _read_live_receipt(paths, request, invocation_cwd=invocation_cwd)
    surfaces['canonical_recall_pack'] = {'status': 'observed', 'basis': 'prepared_local_selection'}
    surfaces['omh_approved_records'] = {
        'status': 'unavailable' if unreadable else 'observed',
        'basis': 'partial_unreadable_store' if unreadable else 'local_store',
    }
    if request.provider_served_count is not None:
        surfaces['provider_recall_status'] = {'status': 'not_authoritative', 'basis': 'caller_supplied_aggregate_count'}
    native = tuple(read_hermes_memory_file(
        paths.hermes_home / 'memories' / label, label=label, cap=cap,
        now=request.now.timestamp() if request.now else None,
    ) for label, _, cap in HERMES_MEMORY_FILES)
    native_error = any(item.error for item in native)
    surfaces['native_inventory'] = {
        'status': 'unavailable' if native_error else 'not_authoritative',
        'basis': 'read_error' if native_error else 'native_inventory_not_omh_reviewed',
    }
    native_match = bool(request.claim_digest) and any(
        digest(entry) == request.claim_digest for item in native for entry in item.entries)
    candidates: list[dict[str, object]] = []
    candidate_error = False
    for path in sorted((paths.memory_dir / 'candidates').glob('*.json')):
        if path.is_symlink():
            candidate_error = True
            continue
        memory._assert_under_memory_root(paths, path)
        value, error = read_json_object_result(path)
        candidate_error = candidate_error or error is not None
        if value is not None:
            candidates.append(value)
    surfaces['omh_candidates'] = {
        'status': 'unavailable' if candidate_error else 'observed',
        'basis': 'partial_unreadable_store' if candidate_error else 'local_store',
    }
    # Scope helpers are the selector's own filters. Digest lookup never exposes
    # a claim from another project; explicit IDs may explain a lens mismatch.
    def anchored(value: dict[str, object]) -> bool:
        if request.record_id:
            return request.record_id in (value.get('record_id'), value.get('candidate_id'))
        return memory._record_scope_matches(value, scope_kind=request.scope_kind, scope_ref=request.scope_ref) and (
            digest(str(value.get('summary', ''))) == request.claim_digest)

    matches = [value for value in records if anchored(value)]
    pending = [value for value in candidates if anchored(value)]
    history: list[dict[str, object]] = []
    history_error = False
    for relative, error in json_files(paths.memory_dir, 'history'):
        if error:
            history_error = True
            continue
        value, error = read_json(paths.memory_dir, relative)
        if error or value is None:
            history_error = True
            continue
        if value.get('schema_version') != memory.PROJECT_MEMORY_RECORD_SCHEMA_VERSION:
            history_error = True
            continue
        if anchored(value) and value.get('superseded_by'):
            history.append(value)
    surfaces['omh_history'] = {
        'status': 'unavailable' if history_error else 'observed',
        'basis': 'partial_unreadable_store' if history_error else 'local_store',
    }
    # Current records take precedence over their older revisions. History can
    # explain a removed claim without admitting it back into recall selection.
    if not matches:
        matches = history
    anchor = {'requested_digest': digest(request.record_id) if request.record_id else request.claim_digest}
    reason = 'not_found'
    last = 'none'
    basis = 'local_inspection'
    if unreadable or candidate_error or native_error or history_error:
        reason = 'store_unavailable'
    if native_match:
        reason = 'native_only_not_omh_reviewed'
    if pending:
        candidate = pending[0]
        reason = str(candidate.get('status', 'selection_unresolved'))
        candidate_id = str(candidate.get('candidate_id', ''))
        # Only canonical generated IDs can cross the persistence boundary.
        if re.fullmatch(r'cand_[0-9a-f]{16}', candidate_id):
            anchor['candidate_id'] = candidate_id
        last = 'candidate'
    if len(matches) > 1:
        reason = 'ambiguous_anchor'
    elif matches:
        record = matches[0]
        record_id = str(record.get('record_id', ''))
        if re.fullmatch(r'mem_[0-9a-f]{16}', record_id):
            anchor['record_id'] = record_id
        anchor['claim_digest'] = digest(str(record.get('summary', '')))
        last = 'stored'
        if not memory._record_scope_matches(record, scope_kind=request.scope_kind, scope_ref=request.scope_ref):
            reason = 'scope_mismatch'
        elif not memory._record_perspective_matches(
            record, observer=(request.observer.strip().lower() if request.observer else None),
            observed=(request.observed.strip().lower() if request.observed else None),
        ):
            reason = 'perspective_mismatch'
        elif record.get('superseded_by'):
            reason = 'superseded'
        else:
            reason = 'selection_unresolved'
            # Legacy pack API returns object-valued JSON; narrow at that boundary.
            excluded = pack['excluded_records']
            included = pack['included_records']
            if not isinstance(excluded, list) or not isinstance(included, list):
                raise ValueError('invalid canonical recall pack record lists')
            for item in excluded:
                if isinstance(item, dict) and item.get('record_id') == record_id:
                    reason = str(item['reason'])
            if any(isinstance(item, dict) and item.get('record_id') == record_id for item in included):
                reason, last = 'selected_live_evidence_unavailable', 'selected'
                if receipt is not None and surfaces['live_prefetch_receipt']['status'] == 'observed':
                    staged = _receipt_stage(receipt, record_id, anchor['claim_digest'])
                    if staged is None:
                        surfaces['live_prefetch_receipt'] = {'status': 'not_authoritative', 'basis': 'receipt_record_digest_mismatch'}
                    else:
                        (reason, last), basis = staged, 'live_prefetch_receipt'
    if not pack['enabled']:
        reason = 'project_memory_disabled'
    root = project_identity_root(invocation_cwd)
    resolution = resolve_project_identity(invocation_cwd)
    if root is not None and resolution.state == 'resolved' and request.scope_kind == 'project' and request.scope_ref == legacy_project_scope(root)['ref']:
        reason = LEGACY_BASENAME_STATE
        basis = 'project_identity_resolution'
    config = {
        'home_digest': digest(str(paths.omh_home.resolve())),
        'session_digest': digest(request.session_id),
        'policy_digest': digest(json.dumps(pack['policy'], sort_keys=True)),
        'selection_digest': digest(json.dumps({
            'scope': pack['scope'], 'perspective': pack['perspective'],
            'query_digest': digest(request.query), 'limit': request.limit, 'max_chars': request.max_chars,
        }, sort_keys=True)),
    }
    if receipt is not None:
        # Validated sha256 identities only: they cite the receipt without copying it.
        config['receipt_id'] = str(receipt['receipt_id'])
        config['receipt_configuration_id'] = str(receipt['configuration_id'])
    result: Incident = {
        **diagnosis(reason, basis),
        'schema_version': 'memory_recall_incident/v1',
        'incident_id': 'incident_' + digest(json.dumps([anchor, config, reason], sort_keys=True))[:24],
        'anchor': anchor, 'configuration_identity': config, 'evidence_surfaces': surfaces,
        'last_proven_stage': last, 'delivery_observed': None, 'model_use_observed': None,
        'external_review_status': 'not_omh_reviewed', 'redaction_policy': 'metadata_only',
        'claim_boundary': 'Local diagnosis and prepared remediation only; not live rendering, delivery, model use, '
                          'dispatch, execution, review, CI, merge, or native-write evidence.',
    }
    return result


def write_memory_recall_incident(paths: OmhPaths, request: RecallIncidentRequest, *, invocation_cwd: str | Path | None = None) -> Incident:
    """Explicitly persist only the bounded diagnosis, never caller-supplied artifacts."""
    result = build_memory_recall_incident(paths, request, invocation_cwd=invocation_cwd)
    destination = paths.memory_incidents_dir / f"{result['incident_id']}.json"
    memory._assert_under_memory_root(paths, destination)
    atomic_write_json(destination, dict(result), private=True)
    return result
