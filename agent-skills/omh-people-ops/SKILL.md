---
name: "omh-people-ops"
description: "[omh] Company hiring or HR process to structure: turn hiring and people context into a fair, structured recruiting or people-operations brief. Use when the user says: recruiting plan, hiring scorecard, interview scorecard, candidate debrief, 채용 계획, 면접 평가표, 후보자 비교."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: people-operations
    role: operator
    quality_tier: evidence-gated
---

# People Ops

This is an OMH `people-ops` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`people-ops` keeps recruiting and people-process guidance fair, structured, and evidence bounded before any human decision or external HR action.

## Do Not Use When

- The request asks for a jurisdiction-specific employment-law conclusion, policy compliance ruling, or contract interpretation; use `omh-legal-compliance-review`.
- The user only needs a one-off job-ad, rejection, or interview-email rewrite; use `omh-content-operator`.
- The user asks to create ATS records, send invitations, book interviews, change employment status, or modify HRIS settings; use `omh-apps` with explicit authorization and observed results.
- The user is the candidate: tailoring a resume, preparing for their own interview or tracking applications; use `omh-ai-job-search`.
- The prompt asks the workflow to make an unsupported candidate decision from protected characteristics or missing interview evidence; retain the process and evidence gap instead.

## Examples

Good example:

- Prompt: Create an interview scorecard and debrief plan for our first senior support hire.
- Expected behavior: Prepare role criteria, a structured scorecard, a debrief template, and decision-owner plan.
- Why: The request needs a fair hiring-process brief, not a claim that a candidate was evaluated or hired.

Bad example:

- Prompt: Send calendar invitations to every candidate for next Tuesday.
- Expected behavior: Route to `omh-apps`, not `people-ops`.
- Why: Sending invitations is an explicit external calendar action.

## Completion Checklist

- Outcomes, must-haves and trainable skills are separate; every criterion has anchors and states the outcome it predicts; interviewers score before the debrief; no candidate recommendation without interview evidence; no ATS, calendar or HRIS action is claimed.
- A scored screen gets a job-relatedness and adverse-impact check (e.g. the four-fifths rule); jurisdiction questions go to `omh-legal-compliance-review`.

## Recovery Notes

- If interview evidence cannot support a candidate debrief, retain the role outcomes, must-have versus trainable criteria, and scorecard, mark the recommendation unresolved, and hand back the missing evidence to the decision owner.
- If policy constraints need a jurisdiction-specific ruling, retain the role brief and interview scorecard, mark the policy conclusion unresolved, and hand back the flagged questions to `omh-legal-compliance-review`.



## When to Use

Use when a team needs a role brief, hiring plan, interview rubric, candidate-debrief structure, onboarding outline, or people-process decision support.

    Strong routing signals: `recruiting plan`, `hiring scorecard`, `interview scorecard`, `candidate debrief`, `채용 계획`, `면접 평가표`, `후보자 비교`

## Catalog Metadata

Category: `operations`
Phase: `people-operations`
Quality tier: `evidence-gated`
Reasoning demand: `light`

Quality bar:

- Distinguish role outcomes from proxy criteria and missing evidence.
- Keep inclusion, privacy, policy, and decision-owner gaps visible.

Required inputs:

- role or people-process outcome
- available evidence
- decision owner
- policy constraints

Expert clarification questions:
- `role or people-process outcome`
  - English: What role or people-process outcome should this work achieve?
  - Korean: 이 작업에서 어떤 역할 또는 인사 프로세스 결과를 달성해야 하나요?

Expected outputs:

- role/outcome and must-have versus trainable-criteria brief
- structured interview scorecard and evidence-based debrief template
- hiring-process, interviewer, and decision-owner plan
- inclusion, privacy, policy, and missing-evidence flags with a next route

Artifact expectations:

- prepared people-operations brief when a wrapper captures it

Safety rules:

- Keep protected characteristics and missing interview evidence out of unsupported candidate recommendations.
- Do not claim HRIS, ATS, outreach, interview, or employment-status actions occurred.
- Draft no questions on protected traits or their proxies (age, family status, health).

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
