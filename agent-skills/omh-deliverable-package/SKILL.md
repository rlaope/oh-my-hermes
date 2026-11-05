---
name: "omh-deliverable-package"
description: "[omh] Attachment and deliverable status tracking: track PPT, PDF, XLSX, DOCX, HWP, Markdown, and attachments through prepared, generated, QA, approved, attached, archived, and published states. Use when the user says: deliverable-package, deliverable mode, file attachment, attach file, attachment status, file delivery, file deliverable status, generated file."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, deliverables]
    category: deliverables
    phase: package-status
    role: operator
    quality_tier: workflow-surface-gated
---

# Deliverable Package

This is an OMH `deliverable-package` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`deliverable-package` exists because a requested file moves through prepared, generated, QA-checked, approved, and attached states that no single tool reports together: it tracks each file through them and reports a state only from that state's own evidence, never from an earlier one's.

## Do Not Use When

- Planning a deck, PDF, workbook, or document from source inputs before any file exists (its outline, target formats, and QA ladder); use `omh-materials-package`.
- A text-only report, executive brief, or slide outline with no file to produce; use `omh-report-package`.

## Examples

Good example:

- Prompt: deliverable-package turn this research into PPT and PDF with attachment status.
- Expected behavior: Produce `prepare_deliverable_package` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: deliverable-package claim the PDF was attached without observed file evidence.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- The deliverable type, audience, source inputs, QA ladder, and delivery boundary are named.
- Prepared generation, generated file, render QA, approval, attachment, and delivery are separate states.
- The next action says whether to generate, revise, QA, approve, attach, or deliver.

## Recovery Notes

- If rendered images do not match slide_count or remain uninspected, retain the observed slide_count, mark render_screenshot unresolved, and hand back the exact file and outstanding image checks.
- If the person's approval names no final file, retain each generated version's read-back, mark approval unresolved, and hand back the stable id and version choices without selecting by modification time.
- If a publication URL resolves to a different content hash, retain the approved file and any archive evidence already read back, mark publication unresolved, and hand back the URL and expected sha256 for destination read-back.



## When to Use

Use when Hermes should prepare, request generation, QA, and report attachment status for user-visible file deliverables.

    Strong routing signals: `deliverable-package`, `deliverable mode`, `file attachment`, `attach file`, `attachment status`, `file delivery`, `file deliverable status`, `generated file`, `첨부`, `첨부 상태`, `전달 상태`

## Catalog Metadata

Category: `deliverables`
Phase: `package-status`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.
- On Hermes, a rung taken from a bundled document skill is observed only from that skill's result for that exact file, judged by its field, not its exit code: `"rendered": false` or `"recalculated": false` exits 0 yet leaves that rung not observed, blocked on the missing tools it names; other observed evidence for a rung still counts.
- On Hermes, the bundled skills give these rungs when available: `powerpoint` gives `slide_count` (`pptx_read.py --outline`) and `render_screenshot` (`pptx_render.py` into a fresh directory, its image count matching `slide_count`, since it lists every image already in that directory); `pdf` gives `page_count` (`pdf_read.py --meta`) and `render_preview` (`pdf_page_image.py`); `xlsx` gives `sheet_schema` (`xlsx_read.py --sheets`) and `formula_recalculation` (`xlsx_recalc.py --out <copy>`, since without `--out` it replaces the input and rungs or approvals already recorded were for other bytes, then the cached results read back with `xlsx_read.py --formulas`, where an error value or a formula with no cached value is a finding); `docx` gives `section_structure` and `required_clause_check` (`docx_read.py --structure` and `--text`) but no `page_count` or appearance until a converted PDF is rendered, and `docx_validate.py` checks package health, never rendering. Images that exist are not a render pass until each one has been inspected, and a producer's `"ok": true` is never the QA verdict.
- A file is `generated` only from the producer's read-back of the written file, `approved` only from the person's answer, and `attached` only from the destination's own read-back, never from a reply that names the file.
- `archived` only after the archive entry records the content sha256, the version, a poster frame or thumbnail for media, and a catalog row read back from the archive.
- `published` only from the destination's own read-back - a URL resolving to the same content hash - never from an upload command's exit code.
- Never pick the final file by modification time: the person's approval names it.
- One work keeps one stable id, and each revision is a new version under it - never a new id and never an overwrite.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- deliverable-package/v1 card or guidance
- next action
- prepared-vs-observed boundary

Artifact expectations:

- deliverable-package/v1 metadata-only runtime or wrapper card when recorded

Safety rules:

- A deliverable package card is not binary generation, render QA, formula recalculation, approval, upload, attachment, or delivery evidence.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
