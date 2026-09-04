---
name: "omh-curriculum-design"
description: "[omh] Turn a learning goal into a teachable curriculum, assessment plan, and learner-ready sequence. Use when the user says: curriculum design, learning objectives, assessment plan, 커리큘럼 설계, 학습 목표, 평가 계획."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: curriculum-design
    role: planner
    quality_tier: planning-gated
---

# Curriculum Design

This is a Hermes-native `curriculum-design` workflow skill.

## Why This Exists

`curriculum-design` makes outcomes, sequence, assessment, and constraints reviewable before materials or LMS work.

## Do Not Use When

- The user wants an explanation of a supplied academic paper rather than a teachable sequence; use `paper-learning`.
- The user needs a deck, workbook, PDF, or other exported learning artifact; route packaging to `materials-package` after the curriculum is accepted.
- The user asks to create or publish an LMS course, enroll students, grade work, or change course settings; use `connector-operator` with explicit authorization and observed evidence.
- The user needs only a short rewrite or one isolated worksheet prompt, not curriculum structure; use `content-operator`.

## Examples

Good example:

- Prompt: Design a six-week onboarding curriculum with learning objectives and practical assessments for new support agents.
- Expected behavior: Prepare learner constraints, scope and sequence, learning objectives, assessments, and adaptation questions.
- Why: The request needs a teachable sequence and assessment plan rather than an LMS course or exported material.

Bad example:

- Prompt: Explain the attached machine-learning paper for a beginner.
- Expected behavior: Route to `paper-learning`, not `curriculum-design`.
- Why: A supplied paper explanation is not a curriculum-design request.

## Completion Checklist

- The plan names goals, non-goals, assumptions, acceptance criteria, and verification shape.
- Draft recommendations, accepted decisions, and executor handoffs are separate states.
- Rejected options or unresolved tradeoffs are recorded before handoff.

## Recovery Notes

- If acceptance criteria or verification are missing, route back to clarification before handoff.
- If assumptions materially affect the plan, keep them visible and avoid treating the plan as accepted.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `best-practice-research`, `autoresearch-goal`, `model-optimization`, `inference-serving`, `+17 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when an educator or enablement owner needs outcomes, scope and sequence, lesson/module design, assessment criteria, and differentiation assumptions.

    Strong routing signals: `curriculum design`, `learning objectives`, `assessment plan`, `커리큘럼 설계`, `학습 목표`, `평가 계획`

## Catalog Metadata

Category: `planning`
Phase: `curriculum-design`
Hermes role: `planner`
Quality tier: `planning-gated`
Reasoning demand: `standard`

Quality bar:

- Tie outcomes to scope, sequence, activities, assessments, and completion evidence.
- Keep instructional design distinct from exported materials or LMS actions.

Handoff policy:

Keep domain framing, clarification, source/evidence synthesis, draft outputs, and next-work routing in Hermes. A prepared brief, review, reply, or plan is not an external action, approval, filing, send, publish, data mutation, implementation, review, CI, or merge claim. Prepare a connector, file, coding, or human-review handoff only when the user explicitly accepts that next step; report it only from observed evidence. Hermes designs an instructional plan; it does not create an LMS course, enroll learners, grade submissions, certify learning, publish materials, or claim learning outcomes occurred.

Required inputs:

- learners
- learning goal
- prerequisites
- constraints

Expert clarification questions:
- `learners`
  - English: Which learner roles or ages and setting, baseline evidence, experience, motivations, language or culture, access needs, and relevant variability should shape the design?
  - Korean: 어떤 학습자 역할 또는 연령과 환경, 기초 수준 근거, 경험, 동기, 언어와 문화, 접근 요구, 관련 다양성이 설계에 반영되어야 하나요?

Expected outputs:

- curriculum_learner_outcome_brief/v1
- curriculum_alignment_map/v1
- curriculum_sequence_design/v1
- curriculum_validation_disposition/v1

Artifact expectations:

- prepared curriculum design brief when a wrapper captures it

Safety rules:

- Make learner prerequisites, accessibility, adaptation, and source-rights gaps explicit.
- Do not claim LMS mutation, enrollment, grading, certification, publication, or learning outcomes.

Procedure: load `references/procedure.md`.

## Runtime Evidence

Preferred harness for this skill: `planning`.

```sh
omh runtime record --skill curriculum-design --harness planning --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
