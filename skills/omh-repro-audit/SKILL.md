---
name: "omh-repro-audit"
description: "[omh] Evaluation logs versus reported paper conditions: audit supplied HellaSwag results with exact scores and review-gated evidence; never run a model. Use when the user says: repro-audit, hellaswag log, hellaswag results, hellaswag score."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: result-audit
    role: researcher
    quality_tier: evidence-gated
    related_skills: [omh-app-debugging]
---

# Repro Audit

This is a Hermes-native `repro-audit` workflow skill.

## Why This Exists

A displayed score is not evidence that evaluation conditions match. This audit covers lm-eval HellaSwag results only. This workflow compares retained source claims without executing an evaluator or inventing missing conditions.

## First Steps

- Ask which metric the person means if acc versus acc_norm is not explicit; never substitute one for the other.
- Use only supplied local files. If no evaluation record is available, ask for one; do not run or fetch a model.
- For agent infrastructure, call `omh paper import-harness --results FILE --metric acc_norm --out NEW_CASE` for native Harness JSON; `--metric acc` is a separate profile.
- When authoring a normalized case instead, call `omh paper audit-init --out NEW_CASE [--metric acc_norm]`; omitted metric preserves the acc default. All conditions start unknown.
- Review the selected source claims and paper conditions with the person. No command records confirmation yet: never edit evidence.json or reported.json to stand in for one, so imported claims stay pending and the audit reports them as blockers.
- Call `omh paper audit --case CASE --out NEW_REPORT`; read validation.json and report.json, then explain blockers and the offline report. Exit 0 means an audit artifact was written, not that conditions match.

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

## Completion Checklist

- The selected metric and source pointers are explicit.
- No model or tokenizer was executed; unknown and pending confirmation stay blocked.
- Report paths exist only after observed command success; an accepted artifact is not a reproduction verdict.

## Recovery Notes

- If validation rejects an input, show sanitized reason codes, not source contents, and request a corrected file.
- A raw lm-eval results file that holds a home-directory path (model_args pretrained=/home/...) is refused as an attached artifact (sensitive_input); import it with import-harness, which keeps only the derived extract.
- If the output exists, choose a new directory instead of deleting or replacing it.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `model-optimization`, `inference-serving`, `model-finetuning`, `research-brief`, `+28 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when supplied evaluation logs must be compared with paper conditions, not when a new evaluation must run.

    Strong routing signals: `repro-audit`, `hellaswag log`, `hellaswag results`, `hellaswag score`

## Catalog Metadata

Category: `research`
Phase: `result-audit`
Hermes role: `researcher`
Quality tier: `evidence-gated`
Reasoning demand: `standard`

Quality bar:

- Check original bytes remain unchanged and the original and derived evidence hashes bind the intended inputs.
- Keep missing reported conditions, unusable provenance and run completion blockers visible even when the raw score is known.

Handoff policy:

Keep source mapping and local evidence comparison in Hermes. Never launch a model, tokenizer, evaluator, subprocess or network request from the audit feature.

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

Safety rules:

- Never infer immutable revisions, sample completion, normalization algorithm, human approval or N/A from missing fields.
- acc and acc_norm must stay separate; exact decimal imports never pass through float. Percent conversion divides exactly by 100; tolerance is zero.
- Unknown is not equal. Imported pending-review evidence cannot establish comparable conditions or a completed run. Scientific verdict stays not_assessed.
- Only macOS/Linux safe descriptor-relative filesystem operations are supported; other platforms fail closed before reading or writing. Do not bypass the guard.
- Require new-only output directories; reject symlinks, traversal, malformed inputs and overlapping case/report paths. Never overwrite the source or an existing output.

## Runtime Evidence

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
