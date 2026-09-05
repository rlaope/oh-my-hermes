# Apple Design Review Playbook

## Source record

- Apple guidance, accessed 2026-09-05: https://developer.apple.com/design/human-interface-guidelines/
- Apple guidance, accessed 2026-09-05: https://developer.apple.com/design/human-interface-guidelines/color
- Apple guidance, accessed 2026-09-05: https://developer.apple.com/design/human-interface-guidelines/layout
- Apple guidance, accessed 2026-09-05: https://developer.apple.com/design/human-interface-guidelines/typography
- OMH recommendation, accessed 2026-09-05: evidence-shaped findings and owner handoffs below.

## Review from evidence

Read actual supplied screens, captures, and code before making a finding. State
exactly what each artifact proves. With no supplied screenshot or rendered
surface, set `visual_status` to `not_observed`; a description is not visual
evidence. Review hierarchy and task flow before cosmetic polish. Compare the
chosen platform convention against the target's controls, color, type, layout,
input, material, and accessibility constraints rather than a generic glass
style.

Each `apple_design_finding/v1` carries:

- severity;
- location and evidence;
- user impact;
- source URL, date, class, and applicability;
- actionable fix;
- downstream owner; and
- missing check.

Mark a fact from supplied evidence as `observation`; mark an inference as
`hypothesis`. Do not invent a compliance score. Design direction or a prepared
brief does not prove coding, accessibility, visual QA, or Apple certification.

## Compose remediation

- Use `design-orchestration` for broad direction and alternatives.
- Use `frontend` for Apple-inspired web or selected-owner implementation briefs.
- Use `design-quality-gate` for a broad craft and content bar.
- Use `accessibility-audit` for semantic, keyboard, VoiceOver, WCAG, and
  assistive-technology evidence.
- Use `visual-qa` for fresh captured states, viewports, motion, and visual
  PASS/REVISE/BLOCK.
- Use `award-bar-score` only for an external web-award rubric, never as Apple
  compliance.

The selected coding owner remains the implementation owner; do not substitute
one by default. Return the smallest applicable handoff and the missing checks
that keep it prepared rather than complete.

Illustrative example data is not runtime status or evidence. Only a matching observed artifact may change implementation, accessibility, visual-QA, or certification status.
