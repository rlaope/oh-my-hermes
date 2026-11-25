# Materials Package

Load this on-demand contract after the compact `materials-package` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user only needs a weekly/monthly report outline; use `omh-report-package`.
- The user asks for recurring meeting minutes or scrum history; use `omh-operating-rhythm`.
- The request is code documentation, README, or project wiki maintenance; use `omh-wiki`.
- The user wants an operation done on one existing file - fill a PDF form, merge or split PDFs, or edit the text of a Word document, the slides of a deck, or the cells of a workbook - rather than a material plan with an export and QA ladder; load Hermes' bundled `pdf`, `docx`, `powerpoint`, or `xlsx` skill (`microsoft-office` from v0.22.6) for that file instead of this one.

## Examples

Good example:

- Prompt: materials-package 엑셀 매출 리포트를 PDF로 공유할 수 있게 준비해줘.
- Expected behavior: Create a material plan with xlsx/pdf target formats, source inputs, missing metrics, QA checks, and a generation handoff boundary.
- Why: The request is about material processing and binary export evidence, not just a text report outline.

Bad example:

- Prompt: materials-package prove the PDF was sent to leadership.
- Expected behavior: Ask for observed delivery evidence or record the delivery as not_observed instead of claiming it happened.
- Why: A prepared material artifact cannot prove export, approval, or delivery.

## Full Input, Output, and Artifact Expectations

Required inputs:

- audience or recipient
- source inputs
- target format(s)
- deadline or delivery context
- missing data or assumptions

Expected outputs:

- material_artifact/v1 plan
- format-specific QA ladder
- executor-neutral generation handoff when needed
- observed export boundary

Artifact expectations:

- material_artifact/v1 under .omh/materials when a wrapper or CLI records it
