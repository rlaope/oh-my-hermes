# Research result audit

Ask Hermes: “Compare this HellaSwag log to the paper's reported conditions.”
Supply the existing result file and paper evidence, and specify **acc** or
**acc_norm** when asked. In other languages, Hermes can select the installed
`omh-repro-audit` skill by its meaning; deterministic routing evidence here is
English only. Live host nomination and message delivery are not verified by
local routing tests.

Hermes can import selected claims, identify missing or incompatible conditions,
and produce an offline report. It does **not** run a model, tokenizer or native
evaluator, fetch weights, execute native configuration, or establish scientific
reproduction. An accepted audit is a valid artifact, not a passing experiment.

## What is compared

The fixed HellaSwag profiles keep `acc` and `acc_norm` separate. The legacy
`acc` profile remains the default only for template initialization. Importing
native results always requires an explicit metric. Both old exact `acc` /
`acc_norm` keys and current `acc,none` / `acc_norm,none` keys under
`results.hellaswag` are supported; ambiguous filters or duplicate selected keys
are rejected. Other tasks, missing metrics, duplicate JSON keys, nonfinite or
out-of-range scores, booleans and oversized/deep inputs are refused.

Source number tokens and decimal values are preserved without a float round
trip. Explicit percentages divide by exactly 100. Comparison uses exact integer
ratios and zero tolerance; rounding warnings never widen it. Equal displayed
scores cannot rescue unknown or mismatched evaluation conditions.

Reported conditions start unknown. Native imports retain only the selected
metric, task and an explicitly present few-shot count. Model identity/revision,
tokenizer, task revision, ordered samples, prompt/chat/scoring specifications,
normalization algorithm, seeds and environment are not inferred. No completion
state is inferred from a score. Missing information is not equal, and N/A needs
the profile's explicit applicability evidence.

## Review and evidence

Imports are source claims with **pending human review**, not approved observations.
`evidence.json` records manual declarations with `confirmed: false`. The
`import-review.json` receipt retains original-byte SHA-256, original JSON
pointers and lexical number token, plus a different hash for the whitelisted
`artifacts/harness-extract.json`. The original log is not copied or changed;
arbitrary configuration, `model_args`, credentials and executable text are not
exported. Hashes establish byte identity, not source truth or loaded model/data.

Hermes must ask the person to review source mappings before recording any human
confirmation in a normalized case. There is no automatic approval command.
Imported pending evidence remains ineffective for comparability. Absent a
supported completed-run record, effective run state is `not_run`; this means
no usable record, not proof that no past evaluation occurred. Scientific verdict
remains `not_assessed` even for otherwise comparable conditions.

## Agent / verifier backend reference

These commands are infrastructure used by Hermes or maintainers, not commands
normal users need to learn. Output parents must already exist and each output
must be a **new directory**:

```sh
omh paper audit-init --out new-case                   # all unknown, acc profile
omh paper audit-init --metric acc_norm --out norm-case
omh paper import-harness --results results.json --metric acc_norm --out imported-case
omh paper audit --case imported-case --out audit-report
```

The case holds `case.json`, `reported.json`, `actual.json`, `evidence.json` and
selected artifacts. Import also adds `import-review.json`. Contract schema IDs
retain the adopted `reprodiff.*` identifiers for normalized-case compatibility;
all implementation and distribution ownership is `omh.workflows.repro_audit`.
There is no separate executable or service.

Accepted audits produce `validation.json`, `report.json`,
`inputs.canonical.json`, `artifact-index.json` and `report.html`. The report is
English, static, HTML-escaped and usable offline, with no scripts, active links
or external resources. Validation rejections produce only sanitized
`validation.json` when a safe new output can be published. Unsafe paths do not
produce an output. Input filenames/content are not echoed by audit errors.

Exit 0 means artifact creation; inspect `comparison.overall`, blocking paths,
`metric.state` and `scientific_verdict`, not just the exit code. Exit 2 means
validation, unsupported capability or unsafe/existing path rejection; exit 3 is
an I/O failure. Outputs never overwrite an existing directory. Symlink traversal,
`..` components and report destinations inside the input case are refused.
Publication uses descriptor-pinned staging and native exclusive directory rename;
atomic visibility is not a power-loss durability guarantee.

**Platform boundary:** these filesystem commands support macOS and Linux only.
Windows and unsupported capability sets fail closed with a controlled message
before reading or writing. The rest of OMH remains OS-independent; this feature
does not claim a Windows filesystem port.

## Reference interpretation

The retained official StableLM log at commit
`93eea082c49c61e64da1a0e1092fe82cc74b46d3` contains distinct HellaSwag
`acc` and `acc_norm` scores. Its report footnote labels the published 73.90
HellaSwag figure as byte-length-normalized `acc_norm`; raw `acc` must not be
substituted. The importer does not infer that normalization algorithm from the
metric name. Importing either score without reviewed reported conditions stays
blocked, and a rounded published number is not an exact-match/reproduction claim.

The comparator, normalized contract, bounded importer, safe publication and
escaped renderer were adopted from retained local ReproDiff candidate code.
Their normalized schema identifiers are compatibility names, not a dependency
on an installed standalone package. Tests use clearly synthetic records; local
reference execution evidence is kept outside the repository.
