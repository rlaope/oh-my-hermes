---
name: feedback-triage
description: [omh] Hermes Feedback Triage workflow: cluster customer signals and choose the next workflow.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, triage]
    category: triage
    phase: feedback
    role: retained-cognition
    quality_tier: triage-gated
---

# Feedback Triage

This is a Hermes-native `feedback-triage` workflow skill.

## Why This Exists

`feedback-triage` exists to keep customer and community signals from jumping straight into roadmap or coding; it clusters evidence, ranks signals, and chooses the next workflow.

## Do Not Use When

- The request already contains an accepted product decision and asks for implementation.
- There are no feedback items, source boundary, or product area to classify.
- The user wants current market research rather than triage of supplied signals.

## Examples

Good example:

- Prompt: feedback-triage these payment failure reports and feature requests before we plan fixes.
- Expected behavior: Cluster bug signals and feature asks, rank severity or opportunity, and recommend research, planning, or coding as a next workflow.
- Why: The input is mixed feedback that needs classification before delivery decisions.

Bad example:

- Prompt: feedback-triage implement the accepted billing fix now.
- Expected behavior: Route to planning or coding handoff instead of re-triaging.
- Why: The decision is already accepted, so triage would add delay without improving evidence.

## Use When

Use when Hermes should classify feedback, bug reports, and feature asks before deciding whether research, planning, or coding handoff is needed.

    Strong routing signals: `feedback-triage`, `customer-feedback-triage`, `feedback triage`, `customer feedback`, `feedback cluster`, `bug or feature`, `feature request triage`, `payment failure feedback`, `feedback trends`, `payment failure`, `payment failure issue`, `payment failure reports`, `고객 피드백`, `피드백`, `피드백 분류`, `피드백을 모아서`, `결제 실패`, `결제 실패 이슈`, `결제 실패 피드백`, `결제 오류`, `고객 불만`, `버그 제보`, `버그 기능 요청`, `기능 요청`

## Catalog Metadata

Category: `triage`
Phase: `feedback`
Hermes role: `retained-cognition`
Quality tier: `triage-gated`

Quality bar:

- Name the source boundary before clustering feedback.
- Classify signals into bug, feature, research, or strategy follow-up without overclaiming evidence.
- Recommend the next workflow instead of jumping straight to coding.

Handoff policy:

Keep feedback triage in Hermes; recommend the next workflow and prepare a selected executor/runtime handoff only after explicit coding intent or accepted plan evidence.

Required inputs:

- feedback items or summary
- source boundary
- product area

Expected outputs:

- clusters
- severity or opportunity ranking
- next workflow recommendation

Artifact expectations:

- feedback triage record when a wrapper captures it

Safety rules:

- Do not turn feedback into a roadmap, implementation plan, or coding handoff by default.
- Separate bug signal, feature ask, severity, opportunity, and missing evidence.
- Route code changes only after explicit user intent or accepted planning evidence.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `customer-insight-triage`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill feedback-triage --harness customer-insight-triage --status started
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
