"""Read-only bounded Harness results adapter; source claims never operator approval."""
import copy
import json
from decimal import Decimal, InvalidOperation
from .core import template_case, canonical_json, _sha, _fail, _scan


class _Number(str):
    """Original JSON number token (not a user-supplied JSON string)."""


class _Integer(_Number):
    """Original integer token, distinct from decimal/exponent tokens."""


def _parse_native(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail('duplicate_key', '/results')
            result[key] = value
        return result
    def constant(_):
        _fail('nonfinite_json', '/results')
    def integer(token):
        if len(token.lstrip('-')) > 1234:
            _fail('input_limit_exceeded', '/results')
        return _Integer(token)
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                           parse_float=_Number, parse_int=integer, parse_constant=constant)
        budget = [200000]
        def bounded(item, depth=0):
            budget[0] -= 1
            if depth > 32 or budget[0] < 0:
                _fail('input_limit_exceeded', '/results')
            if isinstance(item, str) and len(item) > 1024 * 1024:
                _fail('input_limit_exceeded', '/results')
            if type(item) is dict:
                for key, child in item.items():
                    bounded(key, depth + 1)
                    bounded(child, depth + 1)
            elif type(item) is list:
                for child in item:
                    bounded(child, depth + 1)
        bounded(value)
        return value
    except (ValueError, UnicodeError, RecursionError):
        _fail('invalid_json', '/results')


def import_harness(raw, metric):
    """Prepare only whitelisted derived bytes; no input path or native config export."""
    if metric not in ('acc', 'acc_norm'):
        _fail('unsupported_metric', '/results')
    native = _parse_native(raw)
    if type(native) is not dict or type(native.get('results')) is not dict:
        _fail('missing_task_results', '/results')
    task = native['results'].get('hellaswag')
    if type(task) is not dict:
        _fail('missing_task_results', '/results/hellaswag')
    keys = [key for key in (metric, metric + ',none') if key in task]
    if len(keys) != 1 or any(k.startswith(metric + ',') and k != metric + ',none' for k in task):
        _fail('missing_or_ambiguous_metric', '/results/hellaswag')
    key = keys[0]
    score = task[key]
    if type(score) not in (_Integer, _Number):
        _fail('invalid_numeric', '/results/hellaswag')
    # The normalized decimal grammar is checked by core; never round a float.
    token = str(score)
    try:
        decimal = Decimal(token)
        if not decimal.is_finite() or not 0 <= decimal <= 1 or len(token) > 4096 or abs(decimal.as_tuple().exponent) > 4096:
            _fail('invalid_numeric', '/results/hellaswag')
        score = format(decimal, 'f')
    except InvalidOperation:
        _fail('invalid_numeric', '/results/hellaswag')
    from .core import _score
    score_claim = {'state': 'known', 'raw_value': score, 'raw_unit': 'fraction',
                   'source_rounding': 'not_reported', 'evidence_refs': ['native-source'], 'reason': None}
    _score(score_claim, '/results/hellaswag')
    pointers = ['/results/hellaswag', '/results/hellaswag/' + key]
    extract = {'task': 'hellaswag', 'metric': metric, 'raw_value': score, 'raw_unit': 'fraction'}
    candidates = []
    config = native.get('config')
    configs = native.get('configs')
    task_config = configs.get('hellaswag') if type(configs) is dict else None
    for obj, pointer in ((config, '/config/num_fewshot'), (task_config, '/configs/hellaswag/num_fewshot')):
        if type(obj) is dict and 'num_fewshot' in obj:
            fewshot = obj['num_fewshot']
            if type(fewshot) is not _Integer or not 0 <= int(fewshot) <= 2147483647:
                _fail('invalid_fewshot', '/results')
            candidates.append(int(fewshot))
            pointers.append(pointer)
    if candidates:
        if len(set(candidates)) != 1:
            _fail('conflicting_fewshot', '/results')
        extract['num_fewshot'] = candidates[0]
    templates = template_case('harness-import')
    if metric == 'acc_norm':
        templates['case.json']['profile_id'] = 'hellaswag-acc-norm-audit-v0.2'
    actual = copy.deepcopy(templates['reported.json'])
    actual.update(manifest_id='harness-import-actual', role='actual', score=score_claim,
                  imported_run={'claimed_state': 'not_run', 'evidence_refs': [], 'processed_sample_count': None})
    claims = {'task.name': 'hellaswag', 'metric.definition': {
        'name': metric, 'aggregation': 'mean_sample_accuracy', 'unit': 'fraction'}}
    if 'num_fewshot' in extract:
        claims['fewshot.count'] = extract['num_fewshot']
    for path, value in claims.items():
        actual['values'][path] = {'state': 'known', 'value': value,
                                  'evidence_refs': ['native-source'], 'reason': 'pending_operator_review'}
    templates['actual.json'] = actual
    extract_raw = canonical_json(extract)
    extract_path = 'artifacts/harness-extract.json'
    digest = _sha(extract_raw)
    templates['evidence.json']['evidence'] = [{
        'id': 'native-source', 'level': 'manual_declaration', 'kind': 'log',
        'source_path': extract_path, 'source_sha256': digest,
        'locator': '/', 'document_id': 'derived Harness source extract', 'document_version': 'v0.2',
        'excerpt': 'Whitelisted source claims only; original pointers and byte digest in import-review.json.',
        'reviewer': 'pending-operator-review', 'confirmed': False,
        'field_paths': list(claims) + ['score'], 'payload': None}]
    review = {'schema_id': 'reprodiff.import-review/v0.2', 'operator_review': 'pending',
              'original_input_sha256': _sha(raw), 'original_json_pointers': pointers,
              'source_number_token': token,
              'derived_extract_path': extract_path, 'derived_extract_sha256': digest,
              'metric': metric, 'current_tool_execution': 'none',
              'notes': ['Original SHA-256 covers original input bytes, not retained or exported.',
                        'Derived extract digest covers only whitelisted claims; not original log bytes.',
                        'Review original source and mappings before changing provenance or confirmation.',
                        'Metric name does not establish token or byte normalization; conditions remain unknown.']}
    _scan(templates)
    files = {name: canonical_json(value) for name, value in templates.items()}
    files[extract_path] = extract_raw
    files['import-review.json'] = canonical_json(review)
    return files
