---
name: report-package
description: [omh] Hermes Report Package workflow: weekly/monthly reports, executive briefs, PPT-ready outlines, and upload packages.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, reporting]
    category: reporting
    phase: package-outline
    role: operator
    quality_tier: report-gated
---

# Report Package

This is a Hermes-native `report-package` workflow skill.

## Why This Exists

`report-package` exists to make reporting a first-class operations surface: Hermes can produce clean report and slide outlines while keeping approvals, delivery, and binary deck export as separate evidence.

## Do Not Use When

- The user needs SLO, incident, or error-budget review; use `reliability-review`.
- The user asks for a live `.pptx` deck file rather than a PPT-ready outline.
- The request is meeting minutes, scrum history, or action-item tracking.

## Examples

Good example:

- Prompt: report-package 월간 리더십 보고서 PPT outline 만들어줘.
- Expected behavior: Prepare a report package with sections, assumptions, missing inputs, and Markdown/JSON outline scope.
- Why: The request is packaging known information for reporting, not reliability validation or code work.

Bad example:

- Prompt: report-package prove our SLO passed and close the incident.
- Expected behavior: Route to `reliability-review` and require metric or incident evidence.
- Why: Report packaging cannot satisfy reliability closure evidence.

## Completion Checklist

- The reporting window, inputs, audience, narrative, and evidence gaps are named.
- Draft report, generated package, approval, and delivery are separate states.
- The next action says whether to gather evidence, generate, revise, approve, or deliver.

## Recovery Notes

- If input evidence is incomplete, mark the section as pending rather than fabricating a report claim.
- If delivery or attachment is unavailable, keep the report package prepared_not_observed.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, show status, and hand off with observed evidence boundaries.
- Current lane: **Materials and visual summaries** (`design-quality-gate`, `frontend`, `visual-qa`, `materials-package`, `img-summary`, `report-package`, `deliverable-package`) - web, visual QA, files, image cards, and packages.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: For every OMH skill: match intent to a lane; name adjacent workflows; generic tool can render or execute is not a dismissal.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/visual-qa; paper->paper-learning; file->materials-package; search->web-research; audit->workspace-audit/production-audit/security-safety-review; verify->verification-gate; code->codebase-onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is backend, setup, verification, and wrapper infrastructure.
- Boundary: Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when Hermes should turn supplied inputs into a report, executive brief, PPT-ready outline, or upload package without claiming presentation delivery.

    Strong routing signals: `report-package`, `report package`, `weekly report`, `monthly report`, `executive report`, `exec brief`, `leadership deck`, `status package`, `ppt outline`, `presentation outline`, `slide outline`, `upload package`, `보고서 패키지`, `주간 보고서`, `월간 보고서`, `경영진 보고`, `리더십 보고`, `PPT`, `피피티`, `슬라이드`, `발표자료`, `업로드 패키지`

## Catalog Metadata

Category: `reporting`
Phase: `package-outline`
Hermes role: `operator`
Quality tier: `report-gated`

Quality bar:

- Name audience, reporting period, sections, supplied facts, assumptions, and missing data.
- Keep report packaging independent from reliability review unless explicitly requested.
- Export only Markdown/JSON outlines unless a separate presentation tool produces a binary deck.

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

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `report-package`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill report-package --harness report-package --status started
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
