# Curriculum Design

Load this on-demand contract after the compact `curriculum-design` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user wants an explanation of a supplied academic paper rather than a teachable sequence; use `omh-paper-learning`.
- The user needs a deck, workbook, PDF, or other exported learning artifact; route packaging to `omh-materials-package` after the curriculum is accepted.
- The user asks to create or publish an LMS course, enroll students, grade work, or change course settings; use `omh-apps` with explicit authorization and observed evidence.
- The user needs only a short rewrite or one isolated worksheet prompt, not curriculum structure; use `omh-content-operator`.

## Examples

Good example:

- Prompt: Design a six-week onboarding curriculum with learning objectives and practical assessments for new support agents.
- Expected behavior: Prepare learner constraints, scope and sequence, learning objectives, assessments, and adaptation questions.
- Why: The request needs a teachable sequence and assessment plan rather than an LMS course or exported material.

Bad example:

- Prompt: Explain the attached machine-learning paper for a beginner.
- Expected behavior: Route to `omh-paper-learning`, not `curriculum-design`.
- Why: A supplied paper explanation is not a curriculum-design request.

## Full Input, Output, and Artifact Expectations

Required inputs:

- learners
- learning goal
- prerequisites
- constraints

Expected outputs:

- curriculum_learner_outcome_brief/v1
- curriculum_alignment_map/v1
- curriculum_sequence_design/v1
- curriculum_validation_disposition/v1

Artifact expectations:

- prepared curriculum design brief when a wrapper captures it

Detailed procedure steps: `references/procedure.md`.
