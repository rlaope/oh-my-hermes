"""Fixed-profile normalized import and audit, Python 3.9+ stdlib only."""
import errno
import hashlib
import json
import math
import os
import pathlib
import re
import stat
from fractions import Fraction
from importlib import resources

CONTRACT = json.loads(resources.files('omh.workflows.repro_audit').joinpath('data').joinpath('contract.json').read_text(encoding='utf-8'))
FIELDS = {field['path']: field for field in CONTRACT['fields']}
SEMANTIC = CONTRACT['required_fields']
CONTEXT = CONTRACT['context_fields']
PROFILE = CONTRACT['profile_id']
PROFILES = {PROFILE: 'acc', 'hellaswag-acc-norm-audit-v0.2': 'acc_norm'}
POLICY = CONTRACT['policy_id']


def template_case(case_id):
    """Return unknown input records, without writing or inventing facts."""
    _typed(case_id, 'nonempty_string', '/case/case_id')
    _scan(case_id, '/case/case_id')
    return {
        'case.json': {'schema_id': 'reprodiff.normalized-case/v0.1', 'case_id': case_id,
                      'profile_id': PROFILE, 'policy_id': POLICY},
        'reported.json': {'manifest_id': case_id + '-reported', 'version': 1, 'role': 'reported',
                          'values': {p: {'state': 'unknown', 'value': None, 'evidence_refs': [],
                                         'reason': 'not_reported'} for p in FIELDS},
                          'score': {'state': 'unknown', 'raw_value': None, 'raw_unit': None,
                                    'source_rounding': 'not_reported', 'evidence_refs': [], 'reason': 'not_reported'}},
        'actual.json': None,
        'evidence.json': {'schema_id': 'reprodiff.evidence/v0.1', 'evidence': []}}


class ValidationError(Exception):
    """Controlled rejection. Diagnostics never include raw offending data."""
    def __init__(self, errors, input_digest=None):
        self.errors = errors
        self.input_digest = input_digest
        super().__init__('normalized input rejected')


def _fail(code, pointer='/', input_digest=None):
    raise ValidationError([{'code': code, 'pointer': pointer}], input_digest)


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _parse(data, pointer):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                _fail('duplicate_key', pointer)
            out[key] = value
        return out
    def constant(_):
        _fail('nonfinite_json', pointer)
    def integer(token):
        if len(token.lstrip('-')) > 1234:
            _fail('input_limit_exceeded', pointer)
        return int(token)
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant, parse_int=integer)
    except (ValueError, UnicodeError, RecursionError):
        _fail('invalid_json', pointer)


def _keys(value, expected, pointer):
    if type(value) is not dict or set(value) != set(expected):
        code = 'invalid_schema'
        if type(value) is dict:
            if set(value) & {'tolerance', 'threshold', 'force', 'override'}:
                code = 'policy_override_forbidden'
            elif set(value) & {'overall', 'comparison', 'run', 'verdict'}:
                raise ValidationError([{'code': 'invalid_schema', 'pointer': pointer},
                                       {'code': 'untrusted_derived_states', 'pointer': pointer}])
            elif pointer == '/case' and 'schema_id' not in value:
                code = 'normalized_boundary_required'
        _fail(code, pointer)


def _typed(value, kind, pointer):
    ok = False
    if kind in ('string', 'nonempty_string'):
        ok = type(value) is str and (kind == 'string' or len(value) > 0)
    elif kind in ('integer', 'positive_integer', 'nonnegative_integer'):
        ok = type(value) is int and (kind == 'integer' or value >= (1 if kind == 'positive_integer' else 0))
    elif kind == 'boolean':
        ok = type(value) is bool
    elif kind in ('sha256', 'git_sha40'):
        ok = type(value) is str and re.fullmatch('[0-9a-f]{%d}' % (64 if kind == 'sha256' else 40), value) is not None
    elif kind.startswith('enum:'):
        ok = type(value) is str and value in CONTRACT['enums'][kind[5:]]
    elif kind in ('json_object', 'seed_map', 'string_map'):
        ok = type(value) is dict
        if ok and kind != 'json_object':
            for key, item in value.items():
                _typed(key, 'nonempty_string', pointer)
                _typed(item, 'integer' if kind == 'seed_map' else 'nonempty_string', pointer)
    elif kind == 'revision':
        _keys(value, ('kind', 'value'), pointer)
        _typed(value['kind'], 'enum:revision_kind', pointer)
        _typed(value['value'], 'nonempty_string', pointer)
        k, v = value['kind'], value['value']
        if k == 'git_commit':
            _typed(v, 'git_sha40', pointer)
        elif k == 'content_addressed' and not re.fullmatch('sha256:[0-9a-f]{64}', v):
            _fail('invalid_revision', pointer)
        return
    elif kind in CONTRACT['types']:
        shape = CONTRACT['types'][kind]
        _keys(value, shape, pointer)
        for key, subtype in shape.items():
            _typed(value[key], subtype, pointer + '/' + key)
        return
    if not ok:
        _fail('invalid_schema', pointer)


def _refs(value, pointer):
    if type(value) is not list or any(type(x) is not str or not x for x in value) or len(value) != len(set(value)):
        _fail('invalid_evidence_reference', pointer)


def _envelope(env, field, pointer):
    _keys(env, ('state', 'value', 'evidence_refs', 'reason'), pointer)
    _typed(env['state'], 'enum:knowledge', pointer + '/state')
    _refs(env['evidence_refs'], pointer + '/evidence_refs')
    if env['reason'] is not None:
        _typed(env['reason'], 'nonempty_string', pointer + '/reason')
    if env['state'] == 'known':
        _typed(env['value'], field['type'], pointer + '/value')
    else:
        if env['value'] is not None or env['reason'] is None:
            _fail('invalid_schema', pointer)
        if env['state'] == 'not_applicable':
            gate = CONTRACT['comparison_policy']['not_applicable'].get(field['path'])
            if not gate or env['reason'] != gate['reason']:
                _fail('invalid_not_applicable', pointer)


def _ratio(value, unit):
    sign = -1 if value.startswith('-') else 1
    digits = value.lstrip('-').split('.')
    denominator = 10 ** (len(digits[1]) if len(digits) == 2 else 0)
    return Fraction(sign * int(''.join(digits)), denominator * (100 if unit == 'percent' else 1))


def _score(score, pointer):
    _keys(score, ('state', 'raw_value', 'raw_unit', 'source_rounding', 'evidence_refs', 'reason'), pointer)
    if score['state'] not in ('known', 'unknown'):
        _fail('invalid_schema', pointer)
    _typed(score['source_rounding'], 'enum:source_rounding', pointer)
    _refs(score['evidence_refs'], pointer)
    if score['reason'] is not None:
        _typed(score['reason'], 'nonempty_string', pointer)
    if score['state'] == 'unknown':
        if score['raw_value'] is not None or score['raw_unit'] is not None or score['reason'] is None:
            _fail('invalid_schema', pointer)
    else:
        v = score['raw_value']
        if type(v) is not str or len(v) > 4096 or not re.fullmatch(r'-?(0|[1-9][0-9]*)(\.[0-9]+)?', v):
            _fail('invalid_decimal', pointer)
        _typed(score['raw_unit'], 'enum:raw_unit', pointer)
        if not 0 <= _ratio(v, score['raw_unit']) <= 1:
            _fail('numeric_domain_error', pointer)


def _manifest(manifest, role):
    pointer = '/' + role
    _keys(manifest, ('manifest_id', 'version', 'role', 'values', 'score') + (('imported_run',) if role == 'actual' else ()), pointer)
    _typed(manifest['manifest_id'], 'nonempty_string', pointer)
    _typed(manifest['version'], 'positive_integer', pointer)
    if manifest['role'] != role:
        _fail('invalid_schema', pointer)
    _keys(manifest['values'], FIELDS, pointer + '/values')
    for path, field in FIELDS.items():
        _envelope(manifest['values'][path], field, pointer + '/values/' + path)
    _score(manifest['score'], pointer + '/score')
    if role == 'actual':
        run = manifest['imported_run']
        _keys(run, ('claimed_state', 'evidence_refs', 'processed_sample_count'), pointer + '/imported_run')
        _typed(run['claimed_state'], 'enum:run', pointer + '/imported_run')
        _refs(run['evidence_refs'], pointer + '/imported_run')
        if run['processed_sample_count'] is not None:
            _typed(run['processed_sample_count'], 'nonnegative_integer', pointer + '/imported_run')


# Explicit defensive limits, not source-token normalization. Each unique file is
# snapshotted once (8 MiB/file, 64 MiB total), 32 JSON levels, 200k JSON nodes,
# 1 MiB/string, 4096 decimal characters and 4096 bits per non-score integer.
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
_SECRET_KEY = re.compile(r'api[_\-]?key|secret|password|passwd|credential|access[_\-]?token|authorization|private[_\-]?key', re.I)
_SECRET_TEXT = re.compile(r'REPRODIFF_SYNTHETIC_SECRET_DO_NOT_EXPORT|-----BEGIN (?:[A-Z0-9 ]*PRIVATE KEY)-----|/(?:Users|home)/[^\s"<>]+|[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/]', re.I)


def _scan(value, pointer='/', depth=0, budget=None):
    if budget is None:
        budget = [200000]
    budget[0] -= 1
    if depth > 32 or budget[0] < 0:
        _fail('input_limit_exceeded', pointer)
    if type(value) is str:
        if len(value) > 1024 * 1024:
            _fail('input_limit_exceeded', pointer)
        if _SECRET_TEXT.search(value):
            _fail('sensitive_input', pointer)
        try:
            value.encode('utf-8')
        except UnicodeError:
            _fail('invalid_unicode', pointer)
    elif type(value) is dict:
        for key, item in value.items():
            if _SECRET_KEY.search(key):
                _fail('sensitive_input', pointer)
            _scan(key, pointer, depth + 1, budget)
            _scan(item, pointer, depth + 1, budget)
    elif type(value) is list:
        for item in value:
            _scan(item, pointer, depth + 1, budget)
    elif type(value) is float and not math.isfinite(value):
        _fail('nonfinite_json', pointer)
    elif type(value) is int and value.bit_length() > 4096:
        _fail('input_limit_exceeded', pointer)


def _artifact_path(value, pointer):
    if type(value) is not str or not value.startswith('artifacts/') or any(c in value for c in ('\\', '%', '\x00')):
        _fail('unsafe_path', pointer)
    parts = value.split('/')
    if any(p in ('', '.', '..') for p in parts):
        _fail('unsafe_path', pointer)
    return parts


class _Snapshot:
    """Descriptor-relative, no-follow traversal closes symlink TOCTOU windows."""
    def __init__(self, root):
        self.root = pathlib.Path(os.path.abspath(os.fspath(root)))
        self.cache = {}
        self.total = 0

    def read(self, relative, pointer):
        if relative in self.cache:
            return self.cache[relative]
        fd = None
        try:
            fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
            components = self.root.parts[1:] + tuple(relative.split('/'))
            for i, part in enumerate(components):
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                if i < len(components) - 1:
                    flags |= os.O_DIRECTORY
                child = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                _fail('unsafe_path', pointer)
            with os.fdopen(fd, 'rb') as handle:
                fd = None
                data = handle.read(MAX_FILE_BYTES + 1)
            self.total += len(data)
            if len(data) > MAX_FILE_BYTES or self.total > MAX_TOTAL_BYTES:
                _fail('input_limit_exceeded', pointer)
            text = data.decode('utf-8', errors='replace')
            if _SECRET_TEXT.search(text) or re.search(r'["\'](?:api[_-]?key|secret|password|credential|access[_-]?token|authorization|private[_-]?key)["\']\s*:', text, re.I):
                _fail('sensitive_input', pointer)
            self.cache[relative] = data
            return data
        except FileNotFoundError:
            _fail('missing_required_artifact', pointer)
        except OSError as error:
            if error.errno in (errno.ELOOP, errno.ENOTDIR):
                _fail('unsafe_path', pointer)
            raise
        finally:
            if fd is not None:
                os.close(fd)


def _payload_shape(value, kind, pointer):
    if kind == 'sample_index':
        if type(value) is not list:
            _fail('invalid_payload_schema', pointer)
        ids = set()
        for item in value:
            _keys(item, ('id', 'record_sha256'), pointer)
            _typed(item['id'], 'nonempty_string', pointer)
            _typed(item['record_sha256'], 'sha256', pointer)
            if item['id'] in ids:
                _fail('duplicate_sample_id', pointer)
            ids.add(item['id'])
    elif kind == 'task_config':
        _keys(value, ('task_name', 'task_revision', 'config'), pointer)
        _typed(value['task_name'], 'nonempty_string', pointer)
        _typed(value['task_revision'], 'revision', pointer)
        _typed(value['config'], 'json_object', pointer)
    elif kind == 'prompt_spec':
        _keys(value, ('template', 'system_instruction', 'preprocess', 'tokenization'), pointer)
        for k in value:
            _typed(value[k], 'string' if k in ('template', 'system_instruction') else 'nonempty_string', pointer)
    elif kind == 'scoring_spec':
        _keys(value, ('output_type', 'choice_scoring', 'length_normalization', 'tie_break', 'aggregation'), pointer)
        for k in value:
            _typed(value[k], 'nonempty_string', pointer)
        if value['output_type'] != 'loglikelihood' or value['aggregation'] != 'mean_sample_accuracy':
            _fail('invalid_payload_schema', pointer)


def _verify_evidence(bundle, snapshot):
    index, payloads, payload_hashes = {}, {}, {}
    for i, evidence in enumerate(bundle['evidence']['evidence']):
        p = '/evidence/evidence/' + str(i)
        _keys(evidence, CONTRACT['types']['evidence'], p)
        for k in ('id', 'locator', 'document_id', 'document_version', 'reviewer'):
            _typed(evidence[k], 'nonempty_string', p + '/' + k)
        for k, t in (('level', 'enum:provenance'), ('kind', 'enum:evidence_kind'), ('source_sha256', 'sha256'), ('excerpt', 'string'), ('confirmed', 'boolean')):
            _typed(evidence[k], t, p + '/' + k)
        _refs(evidence['field_paths'], p + '/field_paths')
        if any(k not in FIELDS and k not in ('score', 'imported_run') for k in evidence['field_paths']):
            _fail('invalid_field_binding', p)
        if evidence['id'] in index:
            _fail('duplicate_evidence_id', p)
        _artifact_path(evidence['source_path'], p + '/source_path')
        source = snapshot.read(evidence['source_path'], p + '/source_path')
        if _sha(source) != evidence['source_sha256']:
            _fail('artifact_integrity_failed', p + '/source_sha256')
        payload = evidence['payload']
        if payload is not None:
            _keys(payload, ('artifact_path', 'sha256', 'type'), p + '/payload')
            _artifact_path(payload['artifact_path'], p + '/payload/artifact_path')
            _typed(payload['sha256'], 'sha256', p + '/payload/sha256')
            if type(payload['type']) is not str or payload['type'] not in CONTRACT['payload_types']:
                _fail('invalid_payload_schema', p + '/payload/type')
            raw = snapshot.read(payload['artifact_path'], p + '/payload')
            if payload['type'] == 'utf8_text':
                try:
                    value = raw.decode('utf-8')
                except UnicodeError:
                    _fail('invalid_payload_schema', p + '/payload')
                _scan(value, p + '/payload')
                digest = _sha(raw)
            else:
                value = _parse(raw, p + '/payload')
                _scan(value, p + '/payload')
                _payload_shape(value, payload['type'], p + '/payload')
                digest = _sha(canonical_json(value))
            if digest != payload['sha256']:
                _fail('payload_integrity_failed', p + '/payload/sha256')
            payloads[evidence['id']] = value
            payload_hashes[evidence['id']] = digest
        index[evidence['id']] = evidence
    for role in ('reported', 'actual'):
        manifest = bundle[role]
        if manifest is None:
            continue
        claims = dict(manifest['values'], score=manifest['score'])
        if role == 'actual':
            claims['imported_run'] = manifest['imported_run']
        for path, claim in claims.items():
            p = '/' + role + '/' + path
            for ref in claim['evidence_refs']:
                if ref not in index:
                    _fail('invalid_evidence_reference', p)
                e = index[ref]
                expected_type = FIELDS.get(path, {}).get('payload_type')
                if expected_type and claim['state'] == 'known' and e['payload'] is not None:
                    if e['payload']['type'] != expected_type:
                        _fail('payload_type_mismatch', p)
                    if payload_hashes[ref] != claim['value']:
                        _fail('field_digest_mismatch', p)
                    if expected_type == 'sample_index':
                        count_path = 'data.sample_count' if path.startswith('data.') else 'fewshot.count'
                        count = manifest['values'][count_path]
                        n = len(payloads[ref])
                        if (path.startswith('data.') and n == 0) or (count['state'] == 'known' and n != count['value']):
                            _fail('sample_count_mismatch', p)
    return {'evidence': index, 'payloads': payloads,
            'source_digests': {path: _sha(raw) for path, raw in snapshot.cache.items()}}


def load_case(case_dir):
    """Read the four normalized files; reject malformed typed claims safely."""
    snapshot = _Snapshot(case_dir)
    bundle = {}
    for name in ('case', 'reported', 'actual', 'evidence'):
        data = snapshot.read(name + '.json', '/' + name)
        bundle[name] = _parse(data, '/' + name)
        _scan(bundle[name], '/' + name)
    input_digest = _sha(canonical_json(bundle))
    try:
        case = bundle['case']
        _keys(case, ('schema_id', 'case_id', 'profile_id', 'policy_id'), '/case')
        _typed(case['case_id'], 'nonempty_string', '/case/case_id')
        if case['policy_id'] != POLICY:
            _fail('policy_override_forbidden', '/case/policy_id')
        if case['schema_id'] != 'reprodiff.normalized-case/v0.1' or type(case['profile_id']) is not str or case['profile_id'] not in PROFILES:
            _fail('unsupported_version', '/case')
        _manifest(bundle['reported'], 'reported')
        if bundle['actual'] is not None:
            _manifest(bundle['actual'], 'actual')
            if bundle['actual']['manifest_id'] == bundle['reported']['manifest_id']:
                _fail('duplicate_manifest_id', '/actual/manifest_id')
        _keys(bundle['evidence'], ('schema_id', 'evidence'), '/evidence')
        if bundle['evidence']['schema_id'] != 'reprodiff.evidence/v0.1' or type(bundle['evidence']['evidence']) is not list:
            _fail('invalid_schema', '/evidence')
        resolved = _verify_evidence(bundle, snapshot)
        resolved['effective'] = _effective_fields(bundle, resolved)
        _profile_anchors(resolved['effective'], PROFILES[case['profile_id']])
        resolved['imported_run'] = _imported_run(bundle, resolved)
    except ValidationError as error:
        error.input_digest = input_digest
        raise
    resolved['input_digest'] = input_digest
    bundle['_resolved'] = resolved
    return bundle


def _usable_refs(refs, role, path, resolved):
    expected = 'human_confirmed_reported' if role == 'reported' else 'imported_observed'
    usable, reasons = [], []
    for ref in refs:
        e = resolved['evidence'][ref]
        if e['level'] != expected:
            reasons.append('unusable_provenance')
        elif not e['confirmed']:
            reasons.append('evidence_not_confirmed')
        elif path not in e['field_paths']:
            reasons.append('evidence_field_binding_missing')
        else:
            usable.append(ref)
    return usable, reasons or ['missing_evidence']


def _unresolved(value):
    if type(value) is dict:
        return value.get('kind') == 'unresolved' or any(_unresolved(v) for v in value.values())
    if type(value) is list:
        return any(_unresolved(v) for v in value)
    return False


def _effective_fields(bundle, resolved):
    sides = {}
    for role in ('reported', 'actual'):
        values = {}
        sides[role] = values
        for path in FIELDS:
            state, value, reasons, refs = 'unknown', None, [], []
            if bundle[role] is None:
                reasons = ['actual_absent']
            else:
                env = bundle[role]['values'][path]
                refs, why = _usable_refs(env['evidence_refs'], role, path, resolved)
                if env['state'] == 'unknown':
                    reasons = [env['reason']]
                elif not refs:
                    reasons = why + ([env['reason']] if env['reason'] else [])
                elif env['state'] == 'not_applicable':
                    state = 'not_applicable'
                elif _unresolved(env['value']):
                    reasons = ['unresolved_revision']
                else:
                    state, value = 'known', env['value']
                    expected_type = FIELDS[path].get('payload_type')
                    if expected_type:
                        refs = [ref for ref in refs if resolved['evidence'][ref]['payload'] is not None]
                        if not refs:
                            state, value, reasons = 'unknown', None, ['missing_payload']
                        elif any(_unresolved(resolved['payloads'][ref]) for ref in refs):
                            state, value, reasons = 'unknown', None, ['unresolved_revision']
            values[path] = {'state': state, 'value': value, 'reason': reasons, 'refs': refs,
                            'declared_state': bundle[role]['values'][path]['state'] if bundle[role] else 'unknown',
                            'claim_refs': list(bundle[role]['values'][path]['evidence_refs']) if bundle[role] else []}
        # A payload's presence is not evidence that it was applicable/used.
        for path, dependency in (('chat.template_digest', 'chat.mode'), ('fewshot.examples_digest', 'fewshot.count')):
            item, dep = values[path], values[dependency]
            if item['state'] == 'known':
                applicable = (dep['state'] == 'known' and
                              (dep['value'] == 'chat' if dependency == 'chat.mode' else dep['value'] > 0))
                if not applicable:
                    item.update(state='unknown', value=None, reason=item['reason'] + ['unverified_applicability'])
        # Resolve allowlisted N/A only after all underlying known claims resolve.
        for path in CONTRACT['comparison_policy']['not_applicable']:
            item = values[path]
            env = bundle[role]['values'][path] if bundle[role] is not None else None
            if env is None or env['state'] != 'not_applicable':
                continue
            valid = item['state'] == 'not_applicable'
            if path == 'chat.template_digest':
                valid = valid and values['chat.mode']['state'] == 'known' and values['chat.mode']['value'] == 'raw'
            elif path == 'fewshot.examples_digest':
                valid = valid and values['fewshot.count']['state'] == 'known' and values['fewshot.count']['value'] == 0
            else:
                scoring = values['scoring.spec_digest']
                valid = (valid and values['task.name']['state'] == 'known' and values['task.name']['value'] == 'hellaswag'
                         and scoring['state'] == 'known' and any(resolved['payloads'][ref]['output_type'] == 'loglikelihood' for ref in scoring['refs']))
            if not valid:
                item.update(state='unknown', value=None,
                            reason=item['reason'] + ['unverified_applicability' if path == 'generation.config' else 'ungrounded_not_applicable'])
    return sides


def _profile_anchors(sides, metric='acc'):
    values = sides['reported']
    anchors = {'task.name': 'hellaswag',
               'metric.definition': {'name': metric, 'aggregation': 'mean_sample_accuracy', 'unit': 'fraction'}}
    for path, expected in anchors.items():
        item = values[path]
        if item['state'] == 'known' and item['value'] != expected:
            _fail('unsupported_profile', '/reported/values/' + path)
    item = values['evaluator.identity']
    if item['state'] == 'known' and item['value']['source_id'] != 'EleutherAI/lm-evaluation-harness':
        _fail('unsupported_profile', '/reported/values/evaluator.identity')
    for role in sides:
        if sides[role]['generation.config']['state'] == 'known':
            _fail('unsupported_profile', '/' + role + '/values/generation.config')


def _field_result(left, right, resolved):
    reasons = sorted(set(left['reason'] + right['reason']))
    if 'unknown' in (left['state'], right['state']):
        status = 'unknown'
    elif left['state'] == right['state'] == 'not_applicable':
        status = 'not_applicable'
    elif left['state'] != right['state']:
        status = 'different'
    else:
        # Typed canonical JSON distinguishes booleans, integers and JSON floats.
        status = 'equal' if canonical_json(left['value']) == canonical_json(right['value']) else 'different'
    return {'status': status, 'left_state': left['declared_state'], 'right_state': right['declared_state'],
            'adopted_left': left['value'], 'adopted_right': right['value'],
            'evidence_refs': {'left': [dict(resolved['evidence'][ref]) for ref in left['claim_refs']],
                              'right': [dict(resolved['evidence'][ref]) for ref in right['claim_refs']]},
            'reason': reasons}


def _imported_run(bundle, resolved):
    actual = bundle['actual']
    result = {'claimed_state': actual['imported_run']['claimed_state'] if actual else None,
              'effective_state': 'not_run', 'provenance': [], 'reason': 'actual_absent' if actual is None else 'no_usable_imported_record'}
    if actual is None:
        return result
    run = actual['imported_run']
    if run['claimed_state'] == 'not_run':
        return result
    refs, _ = _usable_refs(run['evidence_refs'], 'actual', 'imported_run', resolved)
    if not refs:
        result['reason'] = 'unverified_imported_run'
        return result
    result['provenance'] = [dict(resolved['evidence'][ref]) for ref in refs]
    if run['claimed_state'] == 'completed':
        count = resolved['effective']['actual']['data.sample_count']
        if count['state'] != 'known' or run['processed_sample_count'] is None:
            result['reason'] = 'incomplete_completion_evidence'
            return result
        if count['value'] != run['processed_sample_count']:
            _fail('inconsistent_completion', '/actual/imported_run/processed_sample_count')
    result.update(effective_state=run['claimed_state'], reason='supported_imported_terminal_record')
    return result


def _rational(value):
    return {'numerator': str(value.numerator), 'denominator': str(value.denominator)}


def _metric(bundle, resolved, overall):
    actual = bundle['actual']
    scores = {'reported': bundle['reported']['score'], 'actual': actual['score'] if actual else None}
    result = {'state': 'not_computed', 'reason': None, 'raw_reported': scores['reported'], 'raw_actual': scores['actual'],
              'canonical_reported': None, 'canonical_actual': None,
              'conversion_methods': {'reported': None, 'actual': None},
              'source_rounding': {role: score['source_rounding'] if score else None for role, score in scores.items()},
              'absolute_delta_rational_or_null': None, 'tolerance_fraction': '0'}
    usable = {}
    warnings = []
    for role, score in scores.items():
        if score is not None and score['state'] == 'known':
            refs, _ = _usable_refs(score['evidence_refs'], role, 'score', resolved)
            if refs:
                usable[role] = _ratio(score['raw_value'], score['raw_unit'])
                result['canonical_' + role] = _rational(usable[role])
                result['conversion_methods'][role] = 'percent_divide_exactly_100' if score['raw_unit'] == 'percent' else 'fraction_identity'
                if score['source_rounding'] != 'exact':
                    warnings.append('source_rounding_warning')
    run = resolved['imported_run']['effective_state']
    if overall != 'comparable':
        result['reason'] = 'comparison_' + overall
    elif run != 'completed':
        result['reason'] = 'imported_' + run + '_partial_score' if run in ('failed', 'cancelled') else resolved['imported_run']['reason']
    elif len(usable) != 2:
        result['reason'] = 'score_not_reported' if any(s is None or s['state'] == 'unknown' for s in scores.values()) else 'unusable_score_evidence'
    else:
        delta = abs(usable['reported'] - usable['actual'])
        result.update(state='within_tolerance' if delta == 0 else 'outside_tolerance',
                      reason='exact_display_equality' if delta == 0 else 'exact_display_difference',
                      absolute_delta_rational_or_null=_rational(delta))
    return result, sorted(set(warnings))


def compare_case(bundle):
    """Compare a load_case-verified snapshot, never execute or reread sources."""
    resolved = bundle['_resolved']
    sides = resolved['effective']
    fields = {p: _field_result(sides['reported'][p], sides['actual'][p], resolved) for p in SEMANTIC}
    context = {p: _field_result(sides['reported'][p], sides['actual'][p], resolved) for p in CONTEXT}
    statuses = [f['status'] for f in fields.values()]
    overall = 'blocked_mismatch' if 'different' in statuses else ('blocked_unknown' if 'unknown' in statuses else 'comparable')
    warnings = []
    if 'different' in statuses:
        warnings.append('semantic_mismatch')
    if any(f['left_state'] == f['right_state'] == 'unknown' for f in fields.values()):
        warnings.append('unknown_is_not_equal')
    if any('unresolved_revision' in item['reason'] for item in sides['reported'].values()):
        warnings.append('reported_revision_unresolved')
    if any(any(mark in e[k].lower() for mark in ('<', 'javascript:'))
           for e in resolved['evidence'].values() for k in ('excerpt', 'document_id', 'locator')):
        warnings.append('inert_text_only')
    if any(f['status'] == 'different' for f in context.values()):
        warnings.append('context_different')
    if any(f['status'] == 'unknown' for f in context.values()):
        warnings.append('context_incomplete')
    for item in fields.values():
        warnings.extend(r for r in item['reason'] if r not in warnings)
    imported_run = resolved['imported_run']
    metric, metric_warnings = _metric(bundle, resolved, overall)
    warnings.extend(w for w in metric_warnings if w not in warnings)
    return {'schema_id': 'reprodiff.audit/v0.1', 'case_id': bundle['case']['case_id'], 'profile_id': bundle['case']['profile_id'],
            'policy_id': POLICY, 'input_digest': resolved['input_digest'], 'validation': 'accepted',
            'comparison': {'fields': fields, 'context': context, 'overall': overall,
                           'blocking_paths': [p for p in SEMANTIC if fields[p]['status'] in ('unknown', 'different')],
                           'warnings': warnings},
            'imported_run': imported_run, 'metric': metric, 'scientific_verdict': 'not_assessed',
            'limitations': ['Declared normalized semantics only; no model/tokenizer execution or runtime attestation.',
                            'Human-confirmed reported and operator-confirmed imported mappings are local statements, not independent source truth.',
                            'Context fields warn only; comparable does not establish bitwise or environmental reproducibility.',
                            'Record hashes and source digests do not independently verify loaded model or original dataset bytes.',
                            'Exact displayed scores are not a scientific reproduction or statistical significance verdict.']}
