# Internal Audit

Load this on-demand contract after the compact `internal-audit` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The ask is the month's figures, a budget variance, or the close itself; use `omh-finance-analysis`.
- The ask is reading a contract or a regulation for legal risk; use `omh-legal-compliance-review`.
- The ask is whether a service is ready to launch; use `omh-production-audit`.
- The ask is ranking a codebase's debt; use `omh-tech-debt-audit`.
- The ask is an internal audit engagement plan, a risk-based audit universe or a findings report with condition, criteria, cause and effect rather than testing one control; say it is outside this skill (no sibling covers it) and offer the control-test steps for any control the engagement selects.

## Examples

Good example:

- Prompt: we need to test the quarterly access review control for sox and grade what we find
- Expected behavior: Define the population of quarterly reviews for the period and check its completeness, size the sample from the quarterly frequency, request the signed review and the removal tickets per item, re-perform the comparison of access lists, and grade any deviation from stated likelihood, magnitude and compensating controls.
- Why: A grade that is not derived from criteria cannot be defended to an external auditor.

Bad example:

- Prompt: the owner says the control worked, just mark it effective
- Expected behavior: Refuse to conclude on inquiry alone: sample the population, obtain the evidence, and re-perform before any conclusion.
- Why: An owner's statement is the weakest evidence a control test can hold.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the control: its objective, owner, frequency, and the risk or assertion it addresses
- the population it operates over: the period, the source system, and how completeness was checked
- the firm's or team's sampling guidance, or the confidence and tolerable deviation rate to use
- the materiality threshold and the compensating controls that exist
- the evidence each sample item actually produced, as observed documents, logs, or approvals

Expected outputs:

- control_under_test/v1
- sample_design/v1
- evidence_request/v1
- reperformance_record/v1
- deficiency_severity_grade/v1

Artifact expectations:

- control_under_test/v1 names the control's objective, owner, frequency, and risk, the design result (would it prevent or detect the risk), and the population with its period, source, and completeness check
- sample_design/v1 states the sampling method and derives the sample size from the control's frequency and the stated confidence and tolerable deviation rate, with a selection record that lets someone draw the same items again
- evidence_request/v1 names, per sample item, the document, log, or approval that proves the control operated and who provides it, and separates evidence obtained from evidence described
- reperformance_record/v1 records, per sample item, the independent re-performance of the control and its result -- operated, deviation, or not testable -- with the evidence reference
- deficiency_severity_grade/v1 derives control deficiency, significant deficiency, or material weakness from stated likelihood, magnitude against stated materiality, and compensating controls, shows each criterion's value and source, and withholds the grade when a criterion is missing
