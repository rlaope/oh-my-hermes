"""Explicitly SYNTHETIC data; not paper data or actual model evaluation.

Writes real local source records and JSON/text payload bytes. Evidence levels model
operator-confirmed fixture mappings solely to test the normative trust boundary.
"""
import copy
import hashlib
import json
import pathlib
import tempfile
from omh.workflows.repro_audit.core import template_case

ROOT = pathlib.Path(__file__).resolve().parents[1]



def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


class SyntheticCase:
    """Concrete on-disk case, explicitly labeled synthetic in every source."""
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix='core-synthetic-', dir=str(ROOT / 'tests'))
        self.path = pathlib.Path(self.temp.name)
        (self.path / 'artifacts').mkdir()
        t = template_case('SYNTHETIC-NOT-PAPER-DATA')
        self.records = {k[:-5]: v for k, v in t.items()}
        actual = copy.deepcopy(self.records['reported'])
        actual.update(manifest_id='synthetic-actual', role='actual', imported_run={
            'claimed_state': 'not_run', 'evidence_refs': [], 'processed_sample_count': None})
        self.records['actual'] = actual
        self.payloads = {}
        identity = {'source_id': 'synthetic/model', 'revision': {'kind': 'git_commit', 'value': '1'*40}}
        values = {
            'model.identity': identity, 'tokenizer.identity': identity,
            'data.identity': dict(identity, config='synthetic'), 'data.split': 'test',
            'data.selection': {'mode': 'full_split', 'rule': 'all in synthetic source order'},
            'data.sample_count': 100,
            'evaluator.identity': dict(identity, source_id='EleutherAI/lm-evaluation-harness'),
            'task.name': 'hellaswag', 'chat.mode': 'chat', 'fewshot.count': 5,
            'random.seeds': {'fewshot': 42},
            'metric.definition': {'name': 'acc', 'aggregation': 'mean_sample_accuracy', 'unit': 'fraction'},
            'numerics.spec': {'weight_dtype': 'fp32', 'compute_dtype': 'fp32', 'quantization': 'none'},
            'environment.hardware': 'synthetic CPU', 'environment.platform': 'synthetic OS',
            'environment.libraries': {'synthetic-evaluator': '1'},
            'environment.execution': {'batch_size': 1, 'parallelism': 1}}
        payloads = {
            'data.ordered_samples_digest': ('sample_index', [{'id': 's'+str(i), 'record_sha256': digest(str(i).encode())} for i in range(100)]),
            'fewshot.examples_digest': ('sample_index', [{'id': 'f'+str(i), 'record_sha256': digest(str(i).encode())} for i in range(5)]),
            'task.config_digest': ('task_config', {'task_name': 'hellaswag', 'task_revision': {'kind': 'git_commit', 'value': '1'*40}, 'config': {'synthetic': True}}),
            'prompt.spec_digest': ('prompt_spec', {'template': 'Synthetic {{ input }}', 'system_instruction': '', 'preprocess': 'identity', 'tokenization': 'synthetic-declared'}),
            'chat.template_digest': ('utf8_text', 'SYNTHETIC chat template\n'),
            'scoring.spec_digest': ('scoring_spec', {'output_type': 'loglikelihood', 'choice_scoring': 'sum_loglikelihood', 'length_normalization': 'none', 'tie_break': 'first', 'aggregation': 'mean_sample_accuracy'})}
        for role in ('reported', 'actual'):
            for p, value in values.items():
                self.set(role, p, copy.deepcopy(value))
            for p, (kind, payload) in payloads.items():
                self.payload(role, p, kind, copy.deepcopy(payload))
            self.na(role, 'generation.config', 'LL_NO_GENERATION')

    def close(self):
        self.temp.cleanup()

    def env(self, role, path):
        return self.records[role]['values'][path]

    def evidence(self, role, path):
        eid = role + ':' + path
        for e in self.records['evidence']['evidence']:
            if e['id'] == eid:
                return e
        e = {'id': eid, 'level': 'human_confirmed_reported' if role == 'reported' else 'imported_observed',
             'kind': 'document' if role == 'reported' else 'log',
             'source_path': 'artifacts/synthetic-' + role + '.json', 'source_sha256': '0'*64,
             'locator': '/values/' + path, 'document_id': 'SYNTHETIC NOT PAPER DATA',
             'document_version': 'synthetic-v1', 'excerpt': 'SYNTHETIC fixture statement only',
             'reviewer': 'synthetic-test-operator', 'confirmed': True, 'field_paths': [path], 'payload': None}
        self.records['evidence']['evidence'].append(e)
        return e

    def set(self, role, path, value):
        e = self.evidence(role, path)
        self.records[role]['values'][path] = {'state': 'known', 'value': value, 'evidence_refs': [e['id']], 'reason': None}

    def unknown(self, role, path, reason='not_reported'):
        self.records[role]['values'][path] = {'state': 'unknown', 'value': None, 'evidence_refs': [], 'reason': reason}

    def na(self, role, path, reason):
        self.set(role, path, None)
        self.env(role, path).update(state='not_applicable', reason=reason)

    def payload(self, role, path, kind=None, value=None):
        key = (role, path)
        if kind is None:
            kind, value = self.payloads[key]
        self.payloads[key] = (kind, value)
        data = value.encode('utf-8') if kind == 'utf8_text' else canonical(value)
        rel = 'artifacts/' + role + '-' + path + ('.txt' if kind == 'utf8_text' else '.json')
        (self.path / rel).write_bytes(data)
        self.set(role, path, digest(data))
        self.evidence(role, path)['payload'] = {'artifact_path': rel, 'sha256': digest(data), 'type': kind}

    def score(self, role, value='0.75', unit='fraction', rounding='exact'):
        e = self.evidence(role, 'score')
        self.records[role]['score'] = {'state': 'known', 'raw_value': value, 'raw_unit': unit,
                                     'source_rounding': rounding, 'evidence_refs': [e['id']], 'reason': None}

    def run(self, state='completed', count=100):
        e = self.evidence('actual', 'imported_run')
        self.records['actual']['imported_run'] = {'claimed_state': state, 'processed_sample_count': count, 'evidence_refs': [e['id']]}

    def completed(self, left='0.75', right='0.75'):
        self.score('reported', left)
        self.score('actual', right)
        self.run()

    def flush(self):
        for role in ('reported', 'actual'):
            data = canonical({'notice': 'SYNTHETIC NOT PAPER DATA OR MODEL RUN', 'claims': self.records[role]})
            rel = 'artifacts/synthetic-' + role + '.json'
            (self.path / rel).write_bytes(data)
            for e in self.records['evidence']['evidence']:
                if e['source_path'] == rel:
                    e['source_sha256'] = digest(data)
        for name, value in self.records.items():
            (self.path / (name + '.json')).write_bytes(canonical(value))
        return self.path
