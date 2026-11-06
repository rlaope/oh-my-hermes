---
name: "omh-materials-package"
description: "[omh] PPT, PDF, Excel, or HWP output to produce: decks, PDFs, spreadsheets, documents, HWP, Markdown, and binary export handoffs. Use when the user says: materials-package, material package, materials package, document package, deck file, binary export, file export, render qa."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, materials]
    category: materials
    phase: material-plan
    role: operator
    quality_tier: material-gated
    related_skills: [omh-report-package, omh-operating-rhythm, pdf, docx, powerpoint, xlsx, microsoft-office]
---

# Materials Package

This is a Hermes-native `materials-package` workflow skill.

## Why This Exists

`materials-package` exists so Hermes can handle document, deck, spreadsheet, PDF, Word, Keynote, HWP, and Markdown work as a first-class material-processing workflow without becoming a hidden file generator.

## Do Not Use When

- The user only needs a weekly/monthly report outline; use `omh-report-package`.
- The user asks for recurring meeting minutes or scrum history; use `omh-operating-rhythm`.
- The request is code documentation, README, or project wiki maintenance; use the docs/wiki workflow.
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

## Completion Checklist

- The material source, target format, audience, structure, and QA expectation are named.
- Binary export, rendering, formula recalculation, attachment, and delivery stay observed-only.
- The next action identifies whether the package is planned, generated, QA-ready, or blocked.

## Recovery Notes

- If source metrics needed by an outline section are missing, retain the verified source facts and outline, mark that section unresolved, and hand back material_artifact/v1 with its missing inputs and output owner.
- If xlsx_recalc.py reports recalculated false, retain the observed sheet_schema, mark formula_recalculation not_observed, and hand back its missing tools and the --out <copy> recalculation and cached-value read-back steps.
- If DOCX package validation passes without a rendered converted PDF, retain observed section_structure and required_clause_check, mark appearance and page_count not_observed, and hand back the converted-PDF preview checks.

## Workflow Lane

- Current lane: **Materials and visual summaries** (`show-reel`, `sprite-forge`, `design-orchestration`, `apple-design`, `design-quality-gate`, `award-bar-score`, `frontend`, `accessibility-audit`, `+8 more`) - web, accessibility, visual QA, files, and packages.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes should turn source inputs into a material plan for decks, PDFs, Word/documents, spreadsheets, HWP, Markdown, office-file summaries, comparisons, table extraction plans, or binary export handoff without claiming file generation.

    Strong routing signals: `materials-package`, `material package`, `materials package`, `document package`, `deck file`, `binary export`, `file export`, `render qa`, `layout qa`, `ppt and pdf`, `pdf and ppt`, `ppt/pdf`, `pdf/ppt`, `spreadsheet to pdf`, `excel to pdf`, `monthly report pdf`, `attached spreadsheet`, `word document`, `word doc`, `document action items`, `compare pdfs`, `pdf differences`, `extract tables from pdf`, `pdf to csv`, `spreadsheet analysis brief`, `clean analysis brief`, `pdf`, `pptx`, `keynote`, `keynote deck`, `docx`, `xlsx`, `csv report`, `spreadsheet`, `excel`, `hwp`, `korean hwp`, `proposal document`, `PDF`, `HWP`, `첨부한 엑셀`, `첨부한 워드`, `워드 문서`, `PDF 두 개 비교`, `PDF 표를 CSV`, `PDF 표 추출`, `분석 브리프`, `엑셀을 월간 보고서`, `자료 패키지`, `자료 처리`, `자료 생성`, `문서 패키지`, `문서 생성`, `제안서 문서`, `엑셀`, `스프레드시트`, `피디에프`, `한글 문서`, `키노트`, `파일 export`, `파일 생성`, `렌더 QA`, `PDF랑 PPT`, `PPT랑 PDF`, `PDF와 PPT`, `PPT와 PDF`, `PDF랑 PPT로`

## Catalog Metadata

Category: `materials`
Phase: `material-plan`
Hermes role: `operator`
Quality tier: `material-gated`
Reasoning demand: `standard`

Quality bar:

- Name audience, source inputs, requested extraction/comparison task, target formats, outline sections, assumptions, missing inputs, and output owner.
- Attach format-specific QA expectations before preparing a binary-generation handoff.
- Record binary export, render QA, formula checks, approvals, and delivery only from observed evidence.
- On Hermes, a rung taken from a bundled document skill is observed only from that skill's result for that exact file, judged by its field, not its exit code: `"rendered": false` or `"recalculated": false` exits 0 yet leaves that rung not observed, blocked on the missing tools it names; other observed evidence for a rung still counts.
- On Hermes, the bundled document skills give these rungs when available (`powerpoint`, `xlsx`, `docx`; `microsoft-office` from v0.22.6; same scripts): PowerPoint gives `slide_count` (`pptx_read.py --outline`) and `render_screenshot` (`pptx_render.py` into a fresh directory, its image count matching `slide_count`, since it lists every image already in that directory); `pdf` gives `page_count` (`pdf_read.py --meta`) and `render_preview` (`pdf_page_image.py`); Excel gives `sheet_schema` (`xlsx_read.py --sheets`) and `formula_recalculation` (`xlsx_recalc.py --out <copy>`, since without `--out` it replaces the input and rungs or approvals already recorded were for other bytes, then the cached results read back with `xlsx_read.py --formulas`, where an error value or a formula with no cached value is a finding); Word gives `section_structure` and `required_clause_check` (`docx_read.py --structure` and `--text`) but no `page_count` or appearance until a converted PDF is rendered, and `docx_validate.py` checks package health, never rendering. Images that exist are not a render pass until each one has been inspected, and a producer's `"ok": true` is never the QA verdict.
- No bundled reader covers HWP or Keynote: ask which tool the session has (Hancom Office or a converter for HWP, Keynote export for Keynote). With none, the plan ends at the outline, every QA rung for that file is not_observed, and a PDF export reviewed with the `pdf` rungs is the checkable substitute; say the layout of the HWP or Keynote file itself was not checked.

Handoff policy:

Keep source organization, outline planning, target-format selection, QA ladder, and missing-input review in Hermes; prepare an executor-neutral document-generation handoff only when a binary file is needed.

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

Safety rules:

- Do not claim PPTX, PDF, Keynote, DOCX, XLSX, HWP, or upload output without observed file evidence.
- Do not claim render QA, formula recalculation, approval, or delivery from a prepared material plan.
- Keep source facts, assumptions, missing inputs, and generated output evidence separate.

## Runtime Evidence

Preferred harness for this skill: `materials-package`.

```sh
omh runtime record --skill materials-package --harness materials-package --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
