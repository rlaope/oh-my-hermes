from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from contextlib import chdir
from datetime import datetime, timezone
from importlib import import_module
from typing import TypedDict
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from project_identity_fixture import PROJECT_IDENTITY, memory_paths as resolve_paths
from omh.plugin_bundle.omh import memory_prefetch_receipt as receipts
from omh.plugin_bundle.omh import memory_records  # noqa: E402
from omh.plugin_bundle.omh.memory_provider import OmhMemoryProvider
from omh.routing.chat import route_chat_message
from omh.workflows import memory

SESSION = 'session-a'
LONG_SUMMARY = ('checklist step repeated ' * 19).strip()


class CaptureOptions(TypedDict, total=False):
    stale_after_days: int
    ttl_days: int
    observed: str


class MemoryRecallIncidentTests(unittest.TestCase):
    def __init__(self, methodName='runTest') -> None:
        super().__init__(methodName)
        self.root: Path | None = None

    def setUp(self) -> None:
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(chdir(self.root))

    @property
    def paths(self):
        assert self.root is not None
        return resolve_paths(self.root / 'qa-profile', self.root / 'hermes')

    def api(self):
        # The repository loader supplies the worktree package dynamically.
        return import_module('omh.workflows.memory_recall_incident')

    def approved(self, summary='Prefer structured response output', *, scope_kind='project', scope_ref=PROJECT_IDENTITY):
        candidate = memory.capture_project_memory_candidate(
            self.paths, summary, scope_kind=scope_kind, scope_ref=scope_ref)['candidate']
        assert isinstance(candidate, dict)
        record = memory.approve_project_memory_candidate(self.paths, candidate['candidate_id'])['record']
        assert isinstance(record, dict)
        return record

    def serve(self, session_id: str = SESSION, query: str = 'structured response output') -> dict[str, object]:
        """The actual provider lifecycle persists the receipt this profile's diagnosis reads.

        The query names the records under test: a live turn serves only what
        its query matches (no active-tier fallback), so an empty one would
        select nothing but pins.
        """
        assert self.root is not None
        live = OmhMemoryProvider(self.paths.omh_home, hermes_home=self.paths.hermes_home)
        live.initialize(session_id, platform="cli", hermes_home=str(self.paths.hermes_home), agent_context='primary', cwd=str(self.root))
        live.queue_prefetch(query)
        live.prefetch(query)
        receipt = live.latest_prefetch_receipt()
        live.shutdown()
        assert receipt is not None
        self.assertEqual(receipts.read_prefetch_receipt(self.paths.omh_home), receipt)
        return receipt

    def selected_not_rendered(self) -> tuple[dict[str, object], str]:
        """Eight long summaries: the selector keeps six, the render budget fewer."""
        for index in range(8):
            self.approved(f'release detail {index} {LONG_SUMMARY}')
        receipt = self.serve(query='release detail checklist step')
        rendering = receipt['rendering']
        assert isinstance(rendering, dict)
        omitted = rendering['selected_not_rendered']
        assert isinstance(omitted, list) and omitted
        return receipt, str(omitted[0]['record_id'])

    def test_recall_complaint_routing(self) -> None:
        # Given explicit complaints, including punctuation normalized by the router.
        for message in ('Why was my saved response preference not used?',
                        'Why was my saved preference not used?', 'You forgot my preference.',
                        'Memory was not used!', 'You did not use my preference.'):
            with self.subTest(message=message):
                # When
                route = route_chat_message(message)
                # Then
                self.assertEqual(route['selected_skill'], 'memory-sync')
                recommendations = route['recommendations']
                assert isinstance(recommendations, list)
                self.assertIn('operator_surface_fast_path:memory_recall_incident', recommendations[0]['matched'])
        for message in ('Apologize for forgetting.', 'Debug the agent loop.',
                        'Remember this project: I prefer json.',
                        'Translate "memory was not used" into French.'):
            with self.subTest(control=message):
                route = route_chat_message(message)
                self.assertNotEqual(route.get('selected_skill'), 'memory-sync')

    def test_all_recall_stages(self) -> None:
        # Given synthetic reason codes for every stage, not a live receipt schema.
        api = self.api()
        cases = {
            'not_found': ('not_found', 'not_found'),
            'pending_review': ('pending_or_rejected', 'review_candidate'),
            'rejected': ('pending_or_rejected', 'review_candidate'),
            'superseded': ('invalid_or_superseded', 'review_correction'),
            'payload_digest_mismatch': ('invalid_or_superseded', 'review_correction'),
            'scope_mismatch': ('scope_or_perspective_mismatch', 'review_scope_lens'),
            'perspective_mismatch': ('scope_or_perspective_mismatch', 'review_scope_lens'),
            'review_due': ('stale_expired_or_archived', 'review_freshness'),
            'expired_standard': ('stale_expired_or_archived', 'review_freshness'),
            'archived_tier': ('stale_expired_or_archived', 'review_freshness'),
            'no_query_overlap': ('relevance_attention_or_budget_exclusion', 'review_recall_selection'),
            'common_terms_only': ('relevance_attention_or_budget_exclusion', 'review_recall_selection'),
            'attention_cut': ('relevance_attention_or_budget_exclusion', 'review_recall_selection'),
            'over_budget': ('relevance_attention_or_budget_exclusion', 'review_recall_selection'),
            'selected_not_rendered': ('selected_not_rendered', 'inspect_provider_rendering'),
            'rendered_delivery_not_observed': ('rendered_delivery_not_observed', 'inspect_host_delivery'),
            'delivered_model_use_unknown': ('delivered_model_use_unknown', 'leave_model_use_unresolved'),
            'used': ('used', 'no_change'),
        }
        for reason, (stage, _) in cases.items():
            with self.subTest(reason=reason):
                # When
                result = api.diagnose_synthetic_recall_stage(reason)
                # Then
                self.assertEqual(result['stage'], stage)
                self.assertEqual(result['evidence_basis'], 'synthetic')
        # Given a real local store; canonical selector owns these reasons.
        record = self.approved()
        for request, expected in (
            (api.RecallIncidentRequest(record_id=record['record_id']), 'unresolved'),
            # A query that overlaps no record re-admits the active tier, so the
            # lone record is selected; the no_query_overlap stage is pinned last.
            (api.RecallIncidentRequest(record_id=record['record_id'], query='volcano'), 'unresolved'),
            (api.RecallIncidentRequest(record_id=record['record_id'], max_chars=1), 'relevance_attention_or_budget_exclusion'),
            (api.RecallIncidentRequest(record_id=record['record_id'], scope_ref='another-project'), 'scope_or_perspective_mismatch'),
        ):
            with self.subTest(request=request):
                result = api.build_memory_recall_incident(self.paths, request)
                self.assertEqual(result['stage'], expected)

        fixtures: tuple[tuple[str, CaptureOptions, str | None, str], ...] = (
            ('pending', {}, None, 'pending_review'),
            ('rejected', {}, None, 'rejected'),
            ('stale', {'stale_after_days': 1}, None, 'stale_review_required'),
            ('expired', {'ttl_days': 1}, None, 'expired_standard'),
            ('archived', {}, 'archive', 'archived_tier'),
            ('perspective', {'observed': 'codex'}, None, 'perspective_mismatch'),
            ('retired', {'ttl_days': 1}, None, 'retired'),
        )
        anchors: dict[str, str] = {}
        for name, capture_options, tier, reason in fixtures:
            with self.subTest(local_fixture=name), patch.object(memory, 'utc_now', return_value='2000-12-31T00:00:00Z'):
                # Given public candidate/approval/attention operations, no mocked selector.
                candidate = memory.capture_project_memory_candidate(self.paths, name + ' preference', **capture_options)['candidate']
                assert isinstance(candidate, dict)
                anchor = candidate['candidate_id']
                if name == 'rejected':
                    memory.reject_project_memory_candidate(self.paths, anchor)
                elif name != 'pending':
                    local_record = memory.approve_project_memory_candidate(self.paths, anchor)['record']
                    assert isinstance(local_record, dict)
                    anchor = local_record['record_id']
                    if tier:
                        memory.apply_memory_attention_change(self.paths, anchor, tier=tier)
                    if name == 'retired':
                        memory.apply_memory_retirement(self.paths, now=datetime(2001, 1, 1, tzinfo=timezone.utc))
                anchors[name] = anchor
                request = api.RecallIncidentRequest(record_id=anchor, observed='claude',
                    now=datetime(2001, 1, 1, tzinfo=timezone.utc))
                # When
                result = api.build_memory_recall_incident(self.paths, request)
                # Then
                self.assertEqual(result['reason_code'], reason)
                self.assertNotEqual(result['stage'], 'unresolved')
        # Given the live turn over the same store (retirement already archived the expired
        # records): the provider's reader hands the stale record to the canonical selector,
        # which classifies it at its own clock and counts it in the receipt beside the
        # archived and foreign-perspective exclusions.
        receipt = self.serve()
        selection = receipt['selection']
        assert isinstance(selection, dict)
        self.assertEqual(selection['selected_record_ids'], [record['record_id']])
        self.assertEqual(selection['exclusion_reason_counts'],
                         {'archived_tier': 1, 'perspective_mismatch': 1, 'stale_review_required': 1})
        for name, reason in (('stale', 'stale_review_required'), ('archived', 'archived_tier')):
            with self.subTest(receipt_backed=name):
                # When: the same store, session and lens the receipt was bound to.
                result = api.build_memory_recall_incident(self.paths, api.RecallIncidentRequest(
                    record_id=anchors[name], session_id=SESSION))
                # Then: the local selector names the cause; the bound receipt's aggregate
                # count corroborates it but is never relabelled as per-record evidence.
                self.assertEqual(result['reason_code'], reason)
                self.assertEqual(result['stage'], 'stale_expired_or_archived')
                self.assertEqual(result['last_proven_stage'], 'stored')
                self.assertEqual(result['evidence_basis'], 'local_inspection')
                self.assertEqual(result['evidence_surfaces']['live_prefetch_receipt'],
                                 {'status': 'observed', 'basis': 'canonical_1452_receipt_bound'})
                self.assertEqual(result['configuration_identity']['receipt_id'], receipt['receipt_id'])
                self.assertIn(reason, selection['exclusion_reason_counts'])
        # Given the actual provider's persisted receipt for this profile and session.
        rendered = self.approved('rendered preference for the live turn')
        receipt = self.serve(query='rendered preference for the live turn')
        selection = receipt['selection']
        assert isinstance(selection, dict)
        self.assertIn(rendered['record_id'], selection['selected_record_ids'])
        # When
        result = api.build_memory_recall_incident(self.paths, api.RecallIncidentRequest(
            record_id=rendered['record_id'], session_id=SESSION))
        # Then: rendering and return are proven; host delivery and model use stay unknown.
        self.assertEqual(result['reason_code'], 'rendered_delivery_not_observed')
        self.assertEqual(result['stage'], 'rendered_delivery_not_observed')
        self.assertEqual(result['last_proven_stage'], 'rendered')
        self.assertEqual(result['evidence_basis'], 'live_prefetch_receipt')
        self.assertIsNone(result['delivery_observed'])
        self.assertIsNone(result['model_use_observed'])
        _, omitted = self.selected_not_rendered()
        result = api.build_memory_recall_incident(self.paths, api.RecallIncidentRequest(
            record_id=omitted, session_id=SESSION))
        self.assertEqual(result['reason_code'], 'selected_not_rendered')
        self.assertEqual(result['stage'], 'selected_not_rendered')
        self.assertEqual(result['last_proven_stage'], 'selected')
        self.assertEqual(result['evidence_basis'], 'live_prefetch_receipt')
        # Delivered and used have no record-bound surface; only the synthetic oracle names them.
        for reason in ('delivered_model_use_unknown', 'used'):
            self.assertEqual(api.diagnose_synthetic_recall_stage(reason)['evidence_basis'], 'synthetic')
        # Once any record overlaps the query, the rest are named no_query_overlap.
        self.approved('volcano monitoring runbook')
        result = api.build_memory_recall_incident(self.paths, api.RecallIncidentRequest(
            record_id=record['record_id'], query='volcano'))
        self.assertEqual(result['reason_code'], 'no_query_overlap')
        self.assertEqual(result['stage'], 'relevance_attention_or_budget_exclusion')

    def test_indexed_receipt_and_budget_cut_have_distinct_incident_reasons(self) -> None:
        api = self.api()
        record = self.approved()
        record_id = record['record_id']
        query = 'astronomy telescope'
        snapshot = memory_records.read_record_store_snapshot([self.paths.omh_home])
        request = api.RecallIncidentRequest(record_id=record_id, session_id=SESSION, query=query)
        # The same selected record is indexed with room, but omitted when even
        # its index cannot fit. An older receipt may lack indexed_records.
        for budget, legacy, reason, stage in (
            (memory_records.DEFAULT_RECORD_RENDER_BUDGET_CHARS, False,
             'no_query_overlap', 'relevance_attention_or_budget_exclusion'),
            (1, False, 'selected_not_rendered', 'selected_not_rendered'),
            (1, True, 'selected_not_rendered', 'selected_not_rendered'),
        ):
            with self.subTest(budget=budget, legacy=legacy):
                prepared = memory_records.prepare_prefetch_records(
                    snapshot, query, session_id=SESSION,
                    allowed_scopes=memory_records.prefetch_scope_allowlist(
                        project_identity=PROJECT_IDENTITY, session_id=SESSION),
                    budget_chars=budget, index_fallback=True,
                )
                receipt = receipts.build_prefetch_receipt(
                    prepared, session_id=SESSION, home_digests=snapshot.home_digests)
                self.assertEqual(receipt['selection']['selected_record_ids'], [record_id])
                self.assertEqual(receipt['selection']['query_fallback'], {
                    'mode': 'active_tier', 'reason': 'no_query_overlap', 'readmitted_count': 1})
                rendering = receipt['rendering']
                self.assertEqual(rendering['rendered_records'], [])
                self.assertEqual(rendering['indexed_records'],
                                 [record_id] if reason == 'no_query_overlap' else [])
                self.assertEqual(rendering['selected_not_rendered'],
                                 [] if reason == 'no_query_overlap' else [
                                     {'record_id': record_id, 'reason': 'render_budget_exhausted'}])
                if legacy:
                    del rendering['indexed_records']
                # Marking the genuine builder result returned also signs the
                # old-key shape; the incident still validates the entire receipt.
                receipt = receipts.mark_prefetch_receipt_returned(receipt)
                self.assertEqual(receipts.validate_prefetch_receipt(receipt), [])
                path = receipts.prefetch_receipt_path(self.paths.omh_home)
                path.write_text(json.dumps(receipt), encoding='utf-8')
                self.assertEqual(receipts.read_prefetch_receipt(self.paths.omh_home), receipt)

                result = api.build_memory_recall_incident(self.paths, request)

                self.assertEqual(result['reason_code'], reason)
                self.assertEqual(result['stage'], stage)
                self.assertEqual(result['last_proven_stage'], 'selected')
                self.assertEqual(result['evidence_basis'], 'live_prefetch_receipt')
                self.assertEqual(result['evidence_surfaces']['live_prefetch_receipt'],
                                 {'status': 'observed', 'basis': 'canonical_1452_receipt_bound'})
                self.assertEqual(result['configuration_identity']['receipt_id'], receipt['receipt_id'])
                self.assertIsNone(result['delivery_observed'])
                self.assertIsNone(result['model_use_observed'])

    def test_receipt_absence_is_not_nondelivery(self) -> None:
        # Given selected memory but no record-bound live evidence.
        api = self.api()
        record = self.approved()
        for count in (None, 0, 7):
            with self.subTest(count=count):
                request = api.RecallIncidentRequest(record_id=record['record_id'], provider_served_count=count)
                # When
                result = api.build_memory_recall_incident(self.paths, request)
                # Then
                self.assertEqual(result['stage'], 'unresolved')
                self.assertEqual(result['last_proven_stage'], 'selected')
                self.assertEqual(result['evidence_surfaces']['canonical_recall_pack']['status'], 'observed')
                self.assertEqual(result['evidence_surfaces']['live_prefetch_receipt']['status'], 'unavailable')
                self.assertEqual(result['evidence_surfaces']['host_delivery']['status'], 'unavailable')
                self.assertEqual(result['evidence_surfaces']['provider_recall_status']['status'],
                                 'unavailable' if count is None else 'not_authoritative')
                self.assertIsNone(result['delivery_observed'])

    def test_incident_privacy_and_scope(self) -> None:
        # Given private content and a foreign home with an unrelated record.
        api = self.api()
        record = self.approved('private-memory-sentinel')
        assert self.root is not None
        foreign = resolve_paths(self.root / 'foreign', self.root / 'foreign-hermes')
        candidate = memory.capture_project_memory_candidate(foreign, 'foreign-summary-sentinel')['candidate']
        assert isinstance(candidate, dict)
        foreign_record = memory.approve_project_memory_candidate(foreign, candidate['candidate_id'])['record']
        assert isinstance(foreign_record, dict)
        request = api.RecallIncidentRequest(record_id=record['record_id'], query='raw-query-sentinel',
                                           session_id='raw-session-sentinel')
        # When
        result = api.write_memory_recall_incident(self.paths, request)
        # Then
        persisted = list(self.paths.memory_incidents_dir.glob('*.json'))
        self.assertEqual(len(persisted), 1)
        text = persisted[0].read_text()
        self.assertEqual(json.loads(text), result)
        for sentinel in ('private-memory-sentinel', 'raw-query-sentinel', 'raw-session-sentinel',
                         'foreign-summary-sentinel', foreign_record['record_id']):
            self.assertNotIn(sentinel, text)
        for anchor in ('../../foreign/record', 'password=private-credential-sentinel'):
            with self.assertRaises(ValueError):
                api.RecallIncidentRequest(record_id=anchor)
        self.assertEqual(api.build_memory_recall_incident(self.paths, api.RecallIncidentRequest(
            record_id=foreign_record['record_id']))['stage'], 'not_found')

    def test_prepared_stage_specific_remediation(self) -> None:
        # Given distinct causes and a reviewed local record.
        api = self.api()
        expected = {'not_found': 'capture_for_review', 'pending_review': 'review_candidate',
                    'superseded': 'review_correction', 'scope_mismatch': 'review_scope_lens',
                    'review_due': 'review_freshness', 'over_budget': 'review_recall_selection',
                    'selected_not_rendered': 'inspect_provider_rendering',
                    'rendered_delivery_not_observed': 'inspect_host_delivery',
                    'delivered_model_use_unknown': 'leave_model_use_unresolved', 'used': 'no_change'}
        record = self.approved()
        before = {str(p): p.read_bytes() for p in self.paths.memory_dir.rglob('*') if p.is_file()}
        # When
        results = [api.diagnose_synthetic_recall_stage(reason) for reason in expected]
        local = api.build_memory_recall_incident(self.paths, api.RecallIncidentRequest(record_id=record['record_id']))
        # Then
        for result, action in zip(results, expected.values(), strict=True):
            self.assertEqual(result['remediation']['action'], action)
            self.assertEqual(result['remediation']['state'], 'prepared_not_applied')
            self.assertEqual(result['remediation']['requires'], ['memory_curation_review/v1 approval', 'native_write_approval'])
            self.assertFalse(result['authorizes_mutation'])
        self.assertFalse(local['authorizes_mutation'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.paths.memory_dir.rglob('*') if p.is_file()})

    def test_provider_fault_domain_boundary(self) -> None:
        # Given explicit synthetic provider/host failures vs aggregate local status.
        api = self.api()
        for reason, domain in (('selected_not_rendered', 'provider'),
                               ('rendered_delivery_not_observed', 'unresolved'),
                               ('delivered_model_use_unknown', 'unresolved')):
            # When
            result = api.diagnose_synthetic_recall_stage(reason)
            # Then
            self.assertEqual(result['fault_domain'], domain)
            self.assertFalse(result['omh_correction_proposed'])
        record = self.approved()
        result = api.build_memory_recall_incident(self.paths, api.RecallIncidentRequest(
            record_id=record['record_id'], provider_served_count=0))
        self.assertEqual(result['fault_domain'], 'unresolved')
        self.assertFalse(result['omh_correction_proposed'])
        # Given the actual provider omitted a selected record from its rendering.
        _, omitted = self.selected_not_rendered()
        # When
        result = api.build_memory_recall_incident(self.paths, api.RecallIncidentRequest(
            record_id=omitted, session_id=SESSION))
        # Then: provider evidence, no OMH correction, no mutation authority.
        self.assertEqual(result['stage'], 'selected_not_rendered')
        self.assertEqual(result['fault_domain'], 'provider')
        self.assertEqual(result['evidence_basis'], 'live_prefetch_receipt')
        self.assertFalse(result['omh_correction_proposed'])
        self.assertFalse(result['authorizes_mutation'])
        self.assertEqual(result['remediation']['action'], 'inspect_provider_rendering')
        # An aggregate count beside the receipt still proves nothing about delivery.
        result = api.build_memory_recall_incident(self.paths, api.RecallIncidentRequest(
            record_id=record['record_id'], session_id=SESSION, provider_served_count=9))
        self.assertEqual(result['evidence_surfaces']['provider_recall_status']['status'], 'not_authoritative')
        self.assertIsNone(result['delivery_observed'])

    def test_canonical_receipt_identity(self) -> None:
        # Given the actual provider receipt on disk and an unrelated second record.
        api = self.api()
        record = self.approved()
        other = self.approved('unrelated user-global preference', scope_kind='user-global', scope_ref='default')
        receipt = self.serve(query='structured response output, unrelated preference')
        path = receipts.prefetch_receipt_path(self.paths.omh_home)
        request = api.RecallIncidentRequest(record_id=record['record_id'], session_id=SESSION)
        # When
        bound = api.build_memory_recall_incident(self.paths, request)
        # Then: bound by session, store, configuration and record digest.
        self.assertEqual(bound['evidence_surfaces']['live_prefetch_receipt'],
                         {'status': 'observed', 'basis': 'canonical_1452_receipt_bound'})
        self.assertEqual(bound['stage'], 'rendered_delivery_not_observed')
        self.assertEqual(bound['configuration_identity']['receipt_id'], receipt['receipt_id'])
        self.assertEqual(bound['configuration_identity']['receipt_configuration_id'], receipt['configuration_id'])
        self.assertNotIn(other['record_id'], json.dumps(bound))
        self.assertIsNone(bound['delivery_observed'])
        self.assertIsNone(bound['model_use_observed'])
        # The explicit user-global lens is covered by the same live allowlist.
        global_bound = api.build_memory_recall_incident(self.paths, api.RecallIncidentRequest(
            record_id=other['record_id'], session_id=SESSION, scope_kind='user-global', scope_ref='default'))
        self.assertEqual(global_bound['stage'], 'rendered_delivery_not_observed')
        self.assertNotIn(record['record_id'], json.dumps(global_bound))

        def mutated(changes: Mapping[str, object], *, signed: bool = True) -> str:
            value = json.loads(json.dumps(receipt))
            for key, change in changes.items():
                target, _, field = key.rpartition('.')
                (value[target] if target else value)[field] = change
            if signed:
                # A foreign identity is only reachable behind a valid body digest;
                # an unsigned edit is a tampered file and is rejected before any identity check.
                body = {key: item for key, item in value.items() if key not in ('receipt_id', 'state', 'served_at')}
                value['receipt_id'] = receipts._digest(body)
            path.write_text(json.dumps(value))
            return path.read_text()

        rendering = receipt['rendering']
        assert isinstance(rendering, dict)
        rendered = [dict(item) for item in rendering['rendered_records']]
        self.assertEqual({item['record_id'] for item in rendered}, {record['record_id'], other['record_id']})
        retagged = [{**item, 'content_digest': 'f' * 64} if item['record_id'] == record['record_id'] else item
                    for item in rendered]
        rejected = (
            ('incompatible_receipt:receipt_id', {'prepared_at': '2000-01-01T00:00:00Z'}, request),
            ('incompatible_receipt:schema_version', {'schema_version': 'foreign_receipt/v9'}, request),
            ('receipt_not_returned_to_host', {'state': 'prepared'}, request),
            ('receipt_configuration_mismatch', {'configuration_id': '1' * 64}, request),
            ('receipt_configuration_mismatch', {}, api.RecallIncidentRequest(record_id=record['record_id'], session_id=SESSION, limit=1)),
            ('receipt_session_mismatch', {}, api.RecallIncidentRequest(record_id=record['record_id'], session_id='session-b')),
            ('receipt_session_unbound', {}, api.RecallIncidentRequest(record_id=record['record_id'])),
            ('receipt_store_mismatch', {'store': {'home_digests': ['0' * 64]}}, request),
            ('receipt_scope_mismatch', {}, api.RecallIncidentRequest(record_id=record['record_id'], session_id=SESSION, scope_ref='other')),
            ('receipt_record_digest_mismatch', {'rendering.rendered_records': retagged}, request),
        )
        for basis, changes, variant in rejected:
            with self.subTest(basis=basis):
                text = mutated(changes, signed=basis != 'incompatible_receipt:receipt_id')
                result = api.build_memory_recall_incident(self.paths, variant)
                self.assertEqual(result['evidence_surfaces']['live_prefetch_receipt']['status'], 'not_authoritative')
                self.assertEqual(result['evidence_surfaces']['live_prefetch_receipt']['basis'], basis)
                self.assertNotIn(result['stage'], ('rendered_delivery_not_observed', 'selected_not_rendered', 'used'))
                self.assertIsNone(result['delivery_observed'])
                self.assertEqual(path.read_text(), text)
        # Unavailable or unreadable proof stays unknown, never non-delivery.
        for basis, content in (('receipt_unreadable', '{'), ('no_receipt_persisted', None)):
            with self.subTest(basis=basis):
                if content is None:
                    path.unlink()
                else:
                    path.write_text(content)
                result = api.build_memory_recall_incident(self.paths, request)
                self.assertEqual(result['evidence_surfaces']['live_prefetch_receipt'], {'status': 'unavailable', 'basis': basis})
                self.assertEqual(result['reason_code'], 'selected_live_evidence_unavailable')
                self.assertEqual(result['stage'], 'unresolved')
                self.assertNotIn('receipt_id', result['configuration_identity'])

    def test_delivery_classifier_uses_observations_not_stage_labels(self) -> None:
        # Given synthetic observations over a real rendered record's identities.
        api = self.api()
        record = self.approved()
        original = self.serve()
        claim_digest = hashlib.sha256(str(record['summary']).encode()).hexdigest()
        for delivered, used, expected in (
            (None, None, ('rendered_delivery_not_observed', 'rendered')),
            (None, True, ('rendered_delivery_not_observed', 'rendered')),
            (True, None, ('delivered_model_use_unknown', 'delivered')),
            (True, True, ('used', 'used')),
        ):
            with self.subTest(delivered=delivered, used=used):
                synthetic = {**original, 'delivery_observed': delivered, 'model_use_observed': used}
                # When: exercise the same classifier the validated receipt path calls.
                result = api._receipt_stage(synthetic, record['record_id'], claim_digest)
                # Then: evidence gaps cannot be bridged by downstream assertions.
                self.assertEqual(result, expected)
                if delivered is not None or used is not None:
                    self.assertTrue(receipts.validate_prefetch_receipt(synthetic))

    def test_incident_contains_receipt_decoder_recursion_error(self) -> None:
        # Given a parser recursion failure (parser depth limits vary by Python).
        api = self.api()
        record = self.approved()
        self.serve()
        # When
        with patch.object(api.json, 'loads', side_effect=RecursionError):
            surface, receipt = api._read_live_receipt(
                self.paths, api.RecallIncidentRequest(record_id=record['record_id'], session_id=SESSION))
        # Then
        self.assertIsNone(receipt)
        self.assertEqual(surface, {'status': 'unavailable', 'basis': 'receipt_unreadable'})

    def test_incident_bounds_receipt_bytes_before_decoding(self) -> None:
        # Given valid metadata whose on-disk whitespace exceeds the input limit.
        api = self.api()
        record = self.approved()
        original = self.serve()
        path = receipts.prefetch_receipt_path(self.paths.omh_home)
        path.write_text(' ' * receipts.MAX_PREFETCH_RECEIPT_BYTES + json.dumps(original))
        # When
        result = api.build_memory_recall_incident(
            self.paths, api.RecallIncidentRequest(record_id=record['record_id'], session_id=SESSION))
        # Then
        self.assertEqual(result['stage'], 'unresolved')
        self.assertEqual(result['evidence_surfaces']['live_prefetch_receipt'],
                         {'status': 'unavailable', 'basis': 'receipt_unreadable'})

    def test_candidate_digest_and_perspective_when_locally_available(self) -> None:
        # Given a pending claim and a perspective-scoped approved claim.
        api = self.api()
        summary = 'pending preference'
        candidate = memory.capture_project_memory_candidate(self.paths, summary)['candidate']
        assert isinstance(candidate, dict)
        request = api.RecallIncidentRequest(claim_digest=hashlib.sha256(summary.encode()).hexdigest())
        # When
        pending = api.build_memory_recall_incident(self.paths, request)
        # Then
        self.assertEqual(pending['reason_code'], 'pending_review')
        self.assertEqual(pending['anchor']['candidate_id'], candidate['candidate_id'])

    def test_corrupt_store_when_expected_claim_cannot_be_checked(self) -> None:
        # Given an unreadable store entry, absence is not provable.
        api = self.api()
        directory = self.paths.memory_dir / 'records'
        directory.mkdir(parents=True)
        (directory / 'mem_0000000000000000.json').write_text('{')
        # When
        result = api.build_memory_recall_incident(self.paths, api.RecallIncidentRequest(
            claim_digest='a' * 64))
        # Then
        self.assertEqual(result['stage'], 'unresolved')
        self.assertEqual(result['evidence_surfaces']['omh_approved_records']['status'], 'unavailable')
