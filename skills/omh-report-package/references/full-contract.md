# Report Package

Load this on-demand contract after the compact `report-package` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user needs SLO, incident, or error-budget review; use `omh-reliability-review`.
- The user asks only for a designed `.pptx` file; use `omh-materials-package`.
- The request is meeting minutes, scrum history, or action-item tracking.

## Examples

Good example:

- Prompt: report-package 월간 리더십 보고서 PPT outline 만들어줘.
- Expected behavior: Prepare a report package with sections, assumptions, missing inputs, and Markdown/JSON outline scope.
- Why: The request is packaging known information for reporting, not reliability validation or code work.

Bad example:

- Prompt: report-package prove our SLO passed and close the incident.
- Expected behavior: Route to `omh-reliability-review` and require metric or incident evidence.
- Why: Report packaging cannot satisfy reliability closure evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- audience
- reporting period or scope
- supplied facts with targets or prior-period figures
- missing data or assumptions

Expected outputs:

- report package
- PPT-ready Markdown or JSON outline
- assumptions and missing-input list
- optional achievements badge section sourced from `omh achievements export --format md` when requested

Artifact expectations:

- operation_artifact/v1 report-package artifact when a wrapper or CLI records it
