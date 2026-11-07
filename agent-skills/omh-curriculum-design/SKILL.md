---
name: "omh-curriculum-design"
description: "[omh] Team training or course that needs a syllabus: turn a learning goal into a teachable curriculum, assessment plan, and learner-ready sequence. Use when the user says: curriculum design, learning objectives, assessment plan, 커리큘럼 설계, 학습 목표, 평가 계획."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: curriculum-design
    role: planner
    quality_tier: planning-gated
---

# Curriculum Design

This is an OMH `curriculum-design` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`curriculum-design` makes outcomes, sequence, assessment, and constraints reviewable before materials or LMS work.

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

## Completion Checklist

- Every outcome states performance, conditions and criterion; each has assessment evidence and rubric criteria, and the alignment map lists orphan outcomes and orphan assessments.
- The sequence shows diagnosis, modeling, guided practice, feedback and independent transfer, with the hours per week totalled against the stated schedule.
- Each accessibility adaptation names the learner barrier and an equivalent demonstration path.
- Validation is PASS, REVISE or BLOCKED per criterion; learner review and pilot stay prepared until observed.

## Recovery Notes

- If an outcome lacks acceptable assessment evidence, retain curriculum_learner_outcome_brief/v1, mark curriculum_alignment_map/v1 tentative, and hand back the orphan outcomes or assessment mismatches for revision.
- If an access or technology barrier has no equivalent demonstration path, retain the aligned outcomes and assessments, mark curriculum_sequence_design/v1 unresolved, and hand back the barrier and required adaptation.
- If learner review or pilot evidence is absent, return the alignment and sequence as unvalidated drafts, mark validation unresolved, and hand back curriculum_validation_disposition/v1 with required reviews and revalidation checks.



## When to Use

Use when an educator or enablement owner needs outcomes, scope and sequence, lesson/module design, assessment criteria, and differentiation assumptions.

    Strong routing signals: `curriculum design`, `learning objectives`, `assessment plan`, `커리큘럼 설계`, `학습 목표`, `평가 계획`

## Catalog Metadata

Category: `planning`
Phase: `curriculum-design`
Quality tier: `planning-gated`
Reasoning demand: `standard`

Quality bar:

- Tie outcomes to scope, sequence, activities, assessments, and completion evidence.
- Keep instructional design distinct from exported materials or LMS actions.

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
