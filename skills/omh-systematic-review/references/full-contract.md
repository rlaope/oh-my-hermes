# Systematic Review

Load this on-demand contract after the compact `systematic-review` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- Finding candidate papers, datasets or repositories on a topic belongs to `omh-source-finder`.
- Explaining one supplied paper section by section belongs to `omh-paper-learning`.
- Checking a HellaSwag log against the paper's reported conditions belongs to `omh-repro-audit`.
- Full-text screening, search-string building, risk-of-bias and data extraction are not covered; this skill screens title and abstract only.
- Drafting the manuscript itself is paper writing: load Hermes' optional research-paper-writing skill when it is installed.

## Examples

Good example:

- Prompt: Screen these 400 abstracts for my systematic review of statin trials with two reviewers.
- Expected behavior: Freeze the agreed criteria, prepare blind batches, dispatch reviewers A and B, merge, and report conflicts, pending records and agreement with the independence label.
- Why: The person has records and a review protocol, and needs dual screening.

Bad example:

- Prompt: Do a systematic code review of this PR.
- Expected behavior: Route to code review; nothing here screens literature.
- Why: Systematic describes the review style, not a literature screening protocol.

## Full Input, Output, and Artifact Expectations

Required inputs:

- inclusion and exclusion criteria the person approved
- ordered exclusion codes (E1, E2, ...)
- records JSONL with id, title and abstract
- new screening directory and an integer seed

Expected outputs:

- DIR/protocol.json (screening_protocol/v1, write-once)
- DIR/tasks/A and DIR/tasks/B blind batches plus DIR/manifest.json (screening_manifest/v1)
- screening_merge/v1 with counts, conflict and pending ids, agreement_stats/v1 and reviewer_independence

Artifact expectations:

- Keep protocol.json, manifest.json, every task file and every answer file under DIR; the merge payload carries ids and codes only, never titles, abstracts or answer text.
