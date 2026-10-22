"""Static English audit report. Imported values enter escaped text nodes only."""
import html


_STYLE = """
:root{color-scheme:light;--ink:#17283b;--muted:#526579;--line:#d6dfe7;--paper:#fff;--wash:#f1f5f8;--accent:#18546a}
*{box-sizing:border-box}body{margin:0;background:var(--wash);color:var(--ink);font:15px/1.65 system-ui,-apple-system,sans-serif}
main{max-width:1120px;margin:auto;padding:40px 24px 64px}header{border-top:5px solid var(--accent);padding:26px 0 20px}
h1{font-size:clamp(26px,4vw,38px);line-height:1.2;letter-spacing:-.04em;margin:8px 0 16px}h2{font-size:22px;margin:36px 0 12px}h3{font-size:16px;margin:0}h4{font-size:14px;margin:0 0 8px;color:var(--muted)}
p{margin:8px 0}.eyebrow{font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--accent)}
.notice{border-left:4px solid #bb7832;background:#fff8ec;padding:14px 18px;margin:18px 0}.muted,small{color:var(--muted)}
.summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.summary>div,.panel,article{border:1px solid var(--line);border-radius:10px;background:var(--paper);padding:18px}
.summary strong{display:block;font-size:16px;margin-top:8px;overflow-wrap:anywhere}.summary span{color:var(--muted);font-size:13px}
article{margin:14px 0}article header{border:0;padding:0 0 12px;display:flex;gap:12px;justify-content:space-between;align-items:baseline;flex-wrap:wrap}
.badge{display:inline-block;border:1px solid #a7bac9;border-radius:5px;padding:2px 8px;font:12px/1.6 ui-monospace,monospace;background:#edf3f7}
.sides{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.side{min-width:0}.side+.side{border-left:1px solid var(--line);padding-left:20px}
dl{margin:8px 0}dt{font-size:12px;font-weight:650;color:var(--muted);margin-top:8px;overflow-wrap:anywhere}dd{margin:2px 0 8px;padding-left:12px;border-left:2px solid #e8edf1;min-width:0}
code{font:12px/1.65 ui-monospace,SFMono-Regular,monospace;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word}ul{margin:6px 0;padding-left:22px}li{overflow-wrap:anywhere}
details{margin-top:12px;border-top:1px solid var(--line);padding-top:10px}summary{cursor:pointer;font-weight:600;color:var(--accent)}.reasons{border-top:1px solid var(--line);padding-top:10px;margin-top:12px}
footer{margin-top:32px;padding-top:18px;border-top:1px solid var(--line);font-size:13px;color:var(--muted)}
@media(max-width:680px){main{padding:20px 14px 40px}.summary,.sides{grid-template-columns:1fr}.side+.side{border-left:0;border-top:1px solid var(--line);padding:14px 0 0}.panel,article{padding:14px}}
@media print{body{background:white}main{max-width:none;padding:0}article{break-inside:avoid}summary{color:var(--ink)}details{display:block}}
"""


def _text(value):
    return html.escape(str(value), quote=True)


def _data(value):
    """Structured metadata, not JSON inside HTML attributes or script elements."""
    if isinstance(value, dict):
        return '<dl>' + ''.join('<dt>' + _text(k) + '</dt><dd>' + _data(v) + '</dd>'
                                for k, v in value.items()) + '</dl>'
    if isinstance(value, list):
        return '<ul>' + ''.join('<li>' + _data(v) + '</li>' for v in value) + '</ul>' if value else '<code>[]</code>'
    literal = 'null' if value is None else ('true' if value is True else ('false' if value is False else value))
    return '<code>' + _text(literal) + '</code>'


def _field(path, result, inputs):
    sides = []
    for role, side, title in (('reported', 'left', 'Reported conditions'), ('actual', 'right', 'Imported conditions')):
        manifest = inputs[role]
        claim = manifest['values'][path] if manifest else None
        sides.append('<div class="side"><h4>' + title + '</h4><p>Declared claim</p>' + _data(claim)
                     + '<p>Adopted comparison value</p>' + _data(result['adopted_' + side])
                     + '<details><summary>Evidence metadata including unused references</summary>'
                     + _data(result['evidence_refs'][side]) + '</details></div>')
    return ('<article><header><h3><code>' + _text(path) + '</code></h3><span class="badge">'
            + _text(result['status']) + '</span></header><div class="sides">' + ''.join(sides)
            + '</div><div class="reasons"><strong>Reason</strong>' + _data(result['reason'])
            + '<p class="muted">Declared state: reported ' + _data(result['left_state']) + ' / actual '
            + _data(result['right_state']) + '</p></div></article>')


def render_report(report, inputs):
    """Render a core-validated report and its canonical inputs, with no I/O."""
    comparison, run, metric = report['comparison'], report['imported_run'], report['metric']
    sections = []
    for group, title, explanation in (
            ('fields', 'Required semantic conditions', 'Differences or unknown values block comparison.'),
            ('context', 'Environment context', 'Missing or different context warns without changing comparability.')):
        sections.append('<section><h2>' + title + '</h2><p class="muted">' + explanation + '</p>'
                        + ''.join(_field(path, value, inputs) for path, value in comparison[group].items()) + '</section>')
    run_details = {'claimed_state': run['claimed_state'], 'effective_state': run['effective_state'],
                   'reason': run['reason'], 'imported_run_claim': inputs['actual']['imported_run'] if inputs['actual'] else None,
                   'provenance': run['provenance']}
    run_refs = inputs['actual']['imported_run']['evidence_refs'] if inputs['actual'] else []
    run_details['claimed_evidence_including_unused'] = [e for e in inputs['evidence']['evidence'] if e['id'] in run_refs]
    score_evidence = []
    for role in ('reported', 'actual'):
        manifest = inputs[role]
        refs = manifest['score']['evidence_refs'] if manifest else []
        score_evidence.append({role: [e for e in inputs['evidence']['evidence'] if e['id'] in refs]})
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; '
            'base-uri \'none\'; form-action \'none\'; object-src \'none\'">'
            '<title>OMH research result audit</title><style>' + _STYLE + '</style></head><body><main>'
            '<header><p class="eyebrow">OMH / Local evidence audit</p><h1>Conditions before scores</h1><p>'
            + _text(report['case_id']) + '</p><p class="muted">Compare reported conditions against existing evaluation evidence.</p></header>'
            '<div class="notice">No model is executed. Imported completed describes an imported record, '
            'not proof of reproduction, source truth or statistical equivalence.</div>'
            '<section class="summary" aria-label="Audit summary"><div><span>Condition comparison</span><strong>'
            + _text(comparison['overall']) + '</strong></div><div><span>Imported run</span><strong>'
            + _text(run['effective_state']) + '</strong></div><div><span>Displayed score</span><strong>'
            + _text(metric['state']) + '</strong></div></section><section><h2>Audit identity and blockers</h2><div class="panel">'
            + _data({k: report[k] for k in ('schema_id', 'validation', 'profile_id', 'policy_id', 'input_digest')})
            + _data({'overall': comparison['overall'], 'blocking_paths': comparison['blocking_paths'], 'warnings': comparison['warnings']})
            + '</div></section><section><h2>Imported run: claimed and effective state</h2><p>not_run can mean absence of a supported record; '
            'it does not prove no past run occurred and is not this command execution state.</p><div class="panel">'
            + _data(run_details) + '</div></section><section><h2>Displayed score and fixed policy</h2><div class="panel">'
            '<p>Explicit fractions are unchanged; percentages divide by exactly 100. Units are never inferred. '
            'Integer ratios are preserved; absolute tolerance is zero.</p>'
            '<p>source_rounding rounded / not_reported never widens tolerance. '
            'Only displayed decimal values are compared. '
            'When not_computed, raw/canonical scores are references, not equality verdicts.</p>'
            + _data(metric) + '<details><summary>Score evidence including unused references</summary>' + _data(score_evidence)
            + '</details></div></section>' + ''.join(sections)
            + '<section><h2>Scientific verdict and limitations</h2><div class="panel"><p>scientific_verdict: <strong>'
            + _text(report['scientific_verdict']) + '</strong></p><p>No independent source, execution or reproduction verdict is made. '
            'Human mappings and integrity hashes are not independent proof of source truth or loaded model/data.</p>'
            + _data(report['limitations']) + '</div></section><footer>Offline static report: no external resources, scripts or active links. '
            'Machine results are preserved in report.json. Raw logs are not copied.</footer>'
            '</main></body></html>')
