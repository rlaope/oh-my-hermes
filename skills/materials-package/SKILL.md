---
name: materials-package
description: [omh] Hermes Materials Package workflow: decks, PDFs, spreadsheets, documents, HWP, Markdown, and binary export handoffs.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, materials]
    category: materials
    phase: material-plan
    role: operator
    quality_tier: material-gated
---

# Materials Package

This is a Hermes-native `materials-package` workflow skill.

## Why This Exists

`materials-package` exists so Hermes can handle document, deck, spreadsheet, PDF, Keynote, HWP, and Markdown work as a first-class material-processing workflow without becoming a hidden file generator.

## Do Not Use When

- The user only needs a weekly/monthly report outline; use `report-package`.
- The user asks for recurring meeting minutes or scrum history; use `operating-rhythm`.
- The request is code documentation, README, or project wiki maintenance; use the docs/wiki workflow.

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

- If a renderer or file tool is missing, keep the package prepared and expose the generation handoff.
- If render QA is unavailable, mark the artifact unverified and request the smallest visual/file check.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: choose skills, shape work, prepare artifacts, show status, and hand off with evidence boundaries.
- Current lane: **Materials and visual summaries** (`design-quality-gate`, `frontend`, `accessibility-audit`, `visual-qa`, `content-operator`, `materials-package`, `img-summary`, `report-package`, `+1 more`) - web, accessibility, visual QA, files, and packages.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: every OMH skill: match lane; generic tool can render or execute.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/accessibility-audit/visual-qa; paper->paper-learning; content->content-operator; file->materials-package; search->web-research; live info->live-info-operator; audit->workspace-audit/production-audit/security-safety-review; failures->build-failure-triage; verify->verification-gate; code->codegraph-refresh/codebase-onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is infra.
- Boundary: Prepared OMH routing, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when Hermes should turn source inputs into a material plan for decks, PDFs, spreadsheets, documents, HWP, Markdown, or binary export handoff without claiming file generation.

    Strong routing signals: `materials-package`, `material package`, `materials package`, `document package`, `deck file`, `binary export`, `file export`, `render qa`, `layout qa`, `ppt and pdf`, `pdf and ppt`, `ppt/pdf`, `pdf/ppt`, `spreadsheet to pdf`, `excel to pdf`, `monthly report pdf`, `attached spreadsheet`, `pdf`, `pptx`, `keynote`, `keynote deck`, `docx`, `xlsx`, `csv report`, `spreadsheet`, `excel`, `hwp`, `korean hwp`, `proposal document`, `자료 패키지`, `자료 처리`, `자료 생성`, `문서 패키지`, `문서 생성`, `제안서 문서`, `엑셀`, `스프레드시트`, `피디에프`, `PDF`, `한글 문서`, `HWP`, `키노트`, `파일 export`, `파일 생성`, `렌더 QA`, `첨부한 엑셀`, `엑셀을 월간 보고서`, `PDF랑 PPT`, `PPT랑 PDF`, `PDF와 PPT`, `PPT와 PDF`, `PDF랑 PPT로`

## Catalog Metadata

Category: `materials`
Phase: `material-plan`
Hermes role: `operator`
Quality tier: `material-gated`

Quality bar:

- Name audience, source inputs, target formats, outline sections, assumptions, missing inputs, and output owner.
- Attach format-specific QA expectations before preparing a binary-generation handoff.
- Record binary export, render QA, formula checks, approvals, and delivery only from observed evidence.

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

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `materials-package`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill materials-package --harness materials-package --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Respect `omh_target_topology/v1` when a wrapper reports it: bind state to the current target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, and fall back to single-target behavior when `active_agent_count` is one.
- When target topology changes from one to many or many to one, give a concise setup-change comment or use the wrapper's apply action before treating the new topology as persistent.
- Treat wrapper-supplied memory/context summaries as advisory local context, not proof that opaque Hermes memory was read or changed.
- When a runtime-specific mechanism appears in imported instructions, translate it to a Hermes-native artifact:
  - goal tools -> `.omh/goals/` ledgers, `goal_completion_gate/v1`, `goal_status_card/v1`, `goal_continuation/v1`, or explicit checklists with named next actions,
  - question renderers -> one concise question in the current Hermes interface,
  - native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - shell bridge commands -> optional bridge mode only.

## Execution Rules

1. Load supporting context with `skills_list` / `skill_view` when needed.
2. State the workflow target, constraints, validation evidence, and stop condition.
3. Keep progress evidence-backed.
4. Verify with the smallest relevant test or inspection before claiming completion.
5. If Hermes cannot provide a required runtime capability, say so and use the fallback above.
