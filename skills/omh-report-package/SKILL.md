---
name: "omh-report-package"
description: "[omh] Periodic report for executives: weekly/monthly reports, executive briefs, PPT-ready outlines, and upload packages. Use when the user says: report-package, report package, weekly report, monthly report, executive report, exec brief, leadership deck, status package."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, reporting]
    category: reporting
    phase: package-outline
    role: operator
    quality_tier: report-gated
    related_skills: [omh-reliability-review]
---

# Report Package

This is a Hermes-native `report-package` workflow skill.

## Why This Exists

`report-package` exists to make reporting a first-class operations surface: Hermes can produce clean report and slide outlines while keeping approvals, delivery, and binary deck export as separate evidence.

## Do Not Use When

- The user needs SLO, incident, or error-budget review; use `omh-reliability-review`.
- The user asks for a live `.pptx` deck file rather than a PPT-ready outline.
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

## Completion Checklist

- The reporting window, inputs, audience, narrative, and evidence gaps are named.
- Draft report, generated package, approval, and delivery are separate states.
- The next action says whether to gather evidence, generate, revise, approve, or deliver.

## Recovery Notes

- If no presentation tool can produce a binary deck, retain the PPT-ready Markdown or JSON outline, mark binary export not_observed, and hand back the outline, assumptions, and missing-input list for separate deck generation.
- If the tool returns "rendered": false (it still exits 0) or its image count differs from slide_count, keep the deck's outline read-back, leave render QA not observed, and hand back the missing-tool or image-count gap for that file.
- If the requested achievements export fails, retain the rest of the report package, mark the badge section not_observed, and hand back the missing output from omh achievements export --format md instead of inventing badges.

## Workflow Lane

- Current lane: **Materials and visual summaries** (`show-reel`, `sprite-forge`, `design-orchestration`, `apple-design`, `design-quality-gate`, `award-bar-score`, `frontend`, `accessibility-audit`, `+8 more`) - web, accessibility, visual QA, files, and packages.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes should turn supplied inputs into a report, executive brief, PPT-ready outline, or upload package without claiming presentation delivery.

    Strong routing signals: `report-package`, `report package`, `weekly report`, `monthly report`, `executive report`, `exec brief`, `leadership deck`, `status package`, `ppt outline`, `presentation outline`, `slide outline`, `upload package`, `PPT`, `보고서 패키지`, `주간 보고서`, `월간 보고서`, `경영진 보고`, `리더십 보고`, `피피티`, `슬라이드`, `발표자료`, `업로드 패키지`, `недельный отчёт`, `еженедельный отчёт`, `месячный отчёт`, `ежемесячный отчёт`, `отчёт для начальства`, `сделай отчёт за неделю`, `отчёт руководству`

## Catalog Metadata

Category: `reporting`
Phase: `package-outline`
Hermes role: `operator`
Quality tier: `report-gated`
Reasoning demand: `standard`

Quality bar:

- Name audience, reporting period, sections, supplied facts, assumptions, and missing data.
- Keep report packaging independent from reliability review unless explicitly requested.
- Export only Markdown/JSON outlines unless a separate presentation tool produces a binary deck.
- On Hermes, that tool can be the bundled `powerpoint` skill, and a deck it builds counts as generated from its read-back (`pptx_read.py --outline`).
- On Hermes, a rung taken from a bundled document skill is observed only from that skill's result for that exact file, judged by its field, not its exit code: `"rendered": false` or `"recalculated": false` exits 0 yet leaves that rung not observed, blocked on the missing tools it names; other observed evidence for a rung still counts.
- On Hermes, `powerpoint` gives `slide_count` (`pptx_read.py --outline`) and `render_screenshot` (`pptx_render.py` into a fresh directory, its image count matching `slide_count`, since it lists every image already in that directory). Images that exist are not a render pass until each one has been inspected.

Handoff policy:

Keep report narrative, sectioning, and Markdown/JSON outline packaging in Hermes; do not require reliability evidence unless the user asks for a reliability review.

Required inputs:

- audience
- reporting period or scope
- supplied facts
- missing data or assumptions

Expected outputs:

- report package
- PPT-ready Markdown or JSON outline
- assumptions and missing-input list
- optional achievements badge section sourced from `omh achievements export --format md` when requested

Artifact expectations:

- operation_artifact/v1 report-package artifact when a wrapper or CLI records it

Safety rules:

- Do not claim source review completion from a prepared report package.
- Do not claim stakeholder approval or presentation delivery without observed evidence.
- Do not couple report packages to SLO, incident, or error-budget evidence by default.

## Runtime Evidence

Preferred harness for this skill: `report-package`.

```sh
omh runtime record --skill report-package --harness report-package --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
