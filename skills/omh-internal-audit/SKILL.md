---
name: "omh-internal-audit"
description: "[omh] Testing an internal control -- SOX, ICFR or ITGC: define the population and the sample, name the evidence that proves each item, re-perform the control, and grade any deficiency from stated likelihood, magnitude and compensating-control criteria, never by assertion. Use when the user says: internal-audit, internal audit, internal control, internal controls, internal control audit, control testing, test of controls, tests of controls."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, review]
    category: review
    phase: internal-audit
    role: reviewer
    quality_tier: criteria-derived-severity
    related_skills: [omh-finance-analysis, omh-legal-compliance-review, omh-production-audit, omh-tech-debt-audit]
---

# Internal Audit

Required: the control: its objective, owner, frequency, and the risk or assertion it addresses, the population it operates over: the period, the source system, and how completeness was checked, the firm's or team's sampling guidance, or the confidence and tolerable deviation rate to use, the materiality threshold and the compensating controls that exist, the evidence each sample item actually produced, as observed documents, logs, or approvals. Output: control_under_test/v1, sample_design/v1, evidence_request/v1, reperformance_record/v1, deficiency_severity_grade/v1.

## Why This Exists

`internal-audit` exists because control-testing methodology had no owner: `omh-finance-analysis` reports figures and names control exceptions, `omh-tech-debt-audit` audits code, and `omh-production-audit` audits a release, while population, sampling, re-performance, and deficiency severity had nothing that derived a grade from criteria.

## First Steps

- Ask what the control is meant to prevent or detect, and over which population and period it operates.
- Ask for the sampling guidance and the materiality threshold before sizing any sample or grading anything.

Contract: `references/full-contract.md` (examples, sibling boundaries, full artifact details).

## Workflow Lane

- Current lane: **Research and company ops** - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when an internal control is being tested or a control failure graded: SOX or ICFR testing, IT general controls, a control owner's evidence, a sample of transactions, re-performing a reconciliation or an approval, or deciding whether a deficiency is a significant deficiency or a material weakness. The output is the control and its population, the sample design, the evidence per item, the re-performance record, and a severity grade derived from stated criteria; OMH reads no ledger and tests nothing itself.

    Strong routing signals: `internal-audit`, `internal audit`, `internal control`, `internal controls`, `internal control audit`, `control testing`, `test of controls`, `tests of controls`, `sox`, `sox 404`, `sox testing`, `sox control`, `icfr`, `itgc`, `itgcs`, `material weakness`, `significant deficiency`, `control deficiency`, `deficiency severity`, `re-performance`, `reperformance`, `reperform`, `reperform the control`, `audit sampling`, `attribute sampling`, `control population`, `audit evidence`, `audit workpaper`, `segregation of duties`

## Catalog Metadata

Category: `review`
Phase: `internal-audit`
Hermes role: `reviewer`
Quality tier: `criteria-derived-severity`
Reasoning demand: `standard`

Quality bar:

- Define the population and check its completeness before designing the sample.
- Load `references/control-audit-method.md` for the sample-size table, the evidence hierarchy, and the severity decision table instead of recalling them.
- Re-perform the control independently; do not re-read the owner's conclusion.
- Show every criterion beside the severity grade so a reviewer can re-derive it.
- Keep planned, sampled, evidenced, re-performed, and graded as separate states for every item.

Handoff policy:

Keep the control definition, sample design, evidence requests, re-performance record, and severity grade in Hermes. Populations, sample items, evidence, and re-performance results are recorded only from auditor, control owner, or operator observed output; OMH never queries a ledger or system of record and never signs off a control.

Safety rules:

- Derive every severity grade from stated criteria -- likelihood, magnitude against a stated materiality, and compensating controls; with a criterion missing, withhold the grade rather than assert one.
- Check the population's completeness before sampling from it; a sample from an incomplete population says nothing about the items left out.
- Record evidence obtained, not evidence described; a control owner's explanation is inquiry, not proof the control operated.
- Never drop a deviation found in the sample because it was explained; record it, and judge the sample by its upper deviation limit against the tolerable rate, not by the sample rate.
- OMH reads no ledger, tests no control, and signs off nothing; every population, sample, and result comes from observed output or is marked unverified.

## Completion Checklist

- The control, its population, and the completeness check are stated.
- The sample size is derived from stated frequency, confidence, and tolerable rate, and the selection can be redrawn.
- Each sample item names the evidence obtained, not described.
- Each item's re-performance result cites its evidence.
- The severity grade shows every criterion, or is withheld with the missing one named, and OMH signed off nothing.

## Recovery Notes

- If the population cannot be shown complete, stop and name the completeness test before any sampling.
- If materiality or the compensating controls are not stated, report the deviations and withhold the grade.

## Runtime Evidence

Preferred harness for this skill: `critic`.

```sh
omh runtime record --skill internal-audit --harness critic --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
