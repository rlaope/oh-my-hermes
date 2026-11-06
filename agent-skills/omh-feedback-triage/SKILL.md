---
name: "omh-feedback-triage"
description: "[omh] Unsorted customer feedback and bug reports: cluster customer signals and choose the next workflow. Use when the user says: feedback-triage, customer-feedback-triage, feedback triage, customer feedback, feedback cluster, bug or feature, feature request triage, payment failure feedback."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, triage]
    category: triage
    phase: feedback
    role: operator
    quality_tier: triage-gated
---

# Feedback Triage

This is an OMH `omh-feedback-triage` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`omh-feedback-triage` exists to keep customer and community signals from jumping straight into roadmap or coding; it clusters evidence, ranks signals, and chooses the next workflow.

## Do Not Use When

- The request already contains an accepted product decision and asks for implementation.
- There are no feedback items, source boundary, or product area to classify.
- The user wants current market research rather than triage of supplied signals.
- The triage result asks for a retention or activation intervention rather than another cluster; use `omh-lifecycle-growth`.
- The supplied material is opportunity records and the request is portfolio health or forecast review; use `omh-sales-pipeline-review`.

## Examples

Good example:

- Prompt: Cluster these customer payment failure reports and feature requests before we plan fixes.
- Expected behavior: Cluster bug signals and feature asks, rank severity or opportunity, and recommend research, planning, or coding as a next workflow.
- Why: The input is mixed feedback that needs classification before delivery decisions.

Bad example:

- Prompt: feedback-triage implement the accepted billing fix now.
- Expected behavior: Route to planning or coding handoff instead of re-triaging.
- Why: The decision is already accepted, so triage would add delay without improving evidence.

## Completion Checklist

- The source boundary, signal clusters, severity, and follow-up lane are named.
- Bug, feature, research, strategy, and coding handoff outcomes stay separate.
- The next workflow is recommended before any implementation claim.

## Recovery Notes

- If no feedback items are supplied, no cluster stands; mark triage not_observed and hand back the request for feedback items or a summary, source boundary, and product area.
- If bug and feature signals cannot be separated from the supplied reports, retain source-bounded clusters, mark their classification and ranking tentative, and hand back the missing evidence with research or strategy follow-up options.
- If a triaged cluster has no explicit coding intent or accepted-plan evidence, retain the clusters and ranking, mark the coding handoff unresolved, and hand back the next workflow recommendation with product_evidence_loop/v1 still prepared-only.



## When to Use

Use when Hermes should classify feedback, bug reports, and feature asks before deciding whether research, planning, or coding handoff is needed.

    Strong routing signals: `feedback-triage`, `customer-feedback-triage`, `feedback triage`, `customer feedback`, `feedback cluster`, `bug or feature`, `feature request triage`, `payment failure feedback`, `feedback trends`, `payment failure`, `payment failure issue`, `payment failure reports`, `고객 피드백`, `피드백`, `피드백 분류`, `피드백을 모아서`, `결제 실패`, `결제 실패 이슈`, `결제 실패 피드백`, `결제 오류`, `고객 불만`, `버그 제보`, `버그 기능 요청`, `기능 요청`

## Catalog Metadata

Category: `triage`
Phase: `feedback`
Quality tier: `triage-gated`
Reasoning demand: `standard`

Quality bar:

- Name the source boundary before clustering feedback.
- Classify signals into bug, feature, research, or strategy follow-up without overclaiming evidence.
- Recommend the next workflow instead of jumping straight to coding.

Required inputs:

- feedback items or summary
- source boundary
- product area

Expected outputs:

- clusters
- severity or opportunity ranking
- next workflow recommendation
- product_evidence_loop/v1

Artifact expectations:

- feedback triage record when a wrapper captures it

Safety rules:

- Do not turn feedback into a roadmap, implementation plan, or coding handoff by default.
- Separate bug signal, feature ask, severity, opportunity, and missing evidence.
- Route code changes only after explicit user intent or accepted planning evidence.
- product_evidence_loop/v1 is prepared-only opaque references, not observed evidence or execution.

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
