# Repro Audit

Load this on-demand contract after the compact `repro-audit` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- A bug report whose reproduction steps need checking is software debugging, not an evaluation audit; use `omh-app-debugging`.
- A results file for any benchmark other than HellaSwag (the importer reads only the HellaSwag task); say it is unsupported and do not map it onto HellaSwag.
- A supplied article needs section-by-section explanation rather than comparison of retained records.
- A pull request needs code correctness review rather than research evidence mapping.
- The request requires running an evaluator, downloading weights or verifying scientific reproduction.

## Examples

Good example:

- Prompt: Compare this HellaSwag log to the paper's reported conditions
- Expected behavior: Ask for the metric, import selected claims, retain pending review and explain audit blockers.
- Why: The person has existing results, not a request for model execution.

Bad example:

- Prompt: Explain how HellaSwag score is computed
- Expected behavior: Answer the question directly.
- Why: Naming the benchmark is not a request to compare a supplied record with a paper.

## Full Input, Output, and Artifact Expectations

Required inputs:

- local Harness results JSON or normalized case
- explicit acc or acc_norm selection
- paper conditions and human-reviewed source mappings, or explicit unknowns
- new output directory with existing parent

Expected outputs:

- validation.json
- report.json and offline escaped report.html after accepted audit
- original-input hash and JSON pointers in import-review.json
- blocking unknowns and pending review

Artifact expectations:

- Keep selected evidence only; never copy arbitrary model_args, credentials or raw logs.
- Preserve import-review.json beside the case: original hash, derived hash, lexical number token and original JSON pointers have different meanings.
