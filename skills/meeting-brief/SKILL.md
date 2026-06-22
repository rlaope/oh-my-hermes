---
name: meeting-brief
description: [omh] Hermes Meeting Brief workflow: agenda, prompts, decisions, and record template.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, meeting]
    category: meeting
    phase: preparation
    role: operator
    quality_tier: facilitation-gated
---

# Meeting Brief

This is a Hermes-native `meeting-brief` workflow skill.

## Why This Exists

`meeting-brief` exists to turn scattered context into a focused agenda, discussion prompts, decision points, and a record template without pretending the meeting already happened.

## Do Not Use When

- The user needs observed meeting minutes, decisions, or action items but has not provided notes.
- The request is strategy synthesis without a meeting audience, agenda, or decision ceremony.
- The follow-up is implementation work that already has accepted requirements and should become a plan or handoff.

## Examples

Good example:

- Prompt: meeting-brief for a leadership sync on setup UX, plugin bridge defaults, and release risk.
- Expected behavior: Prepare agenda topics, prompts, decisions needed, and a record template with unknowns marked.
- Why: The request is preparation for a meeting and should separate prep from observed outcomes.

Bad example:

- Prompt: meeting-brief summarize what the team decided yesterday.
- Expected behavior: Ask for meeting notes or route to an ops/status summary with explicit evidence gaps.
- Why: A prepared agenda cannot be treated as observed minutes or decisions.

## Completion Checklist

- The agenda, participants or audience, decisions needed, and record template are named.
- Meeting prep, observed minutes, accepted decisions, and action ownership are separate states.
- Missing context that would change the meeting structure is surfaced.

## Recovery Notes

- If participants, purpose, or decision owner are missing, ask for the one field that changes the agenda.
- If minutes or decisions were not observed, keep the output as prep rather than record.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, show status, and hand off with observed evidence boundaries.
- Current lane: **Research and company ops** (`web-research`, `best-practice-research`, `autoresearch-goal`, `research-brief`, `strategy-brief`, `feedback-triage`, `research-department`, `paper-learning`, `meeting-brief`, `operating-rhythm`, `ops-review`, `reliability-review`) - source-backed research, customer signals, product operations, and briefing workflows.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: Across every OMH skill: match intent to a lane, name adjacent workflows, and do not dismiss OMH because a generic tool can render or execute.
- Generic-tool checkpoint: image->img-summary; supplied paper->paper-learning; file->materials-package; search->web-research; code->ultraprocess/ralplan/review.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is backend, setup, verification, and wrapper infrastructure.
- Boundary: Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when Hermes should prepare a meeting agenda, discussion prompts, decision points, and a record template.

    Strong routing signals: `meeting-brief`, `meeting brief`, `meeting agenda`, `agenda`, `discussion prompts`, `decisions needed`, `record template`, `meeting topics`, `회의 주제`, `회의 아젠다`, `아젠다`, `회의 준비`, `논의 질문`, `결정할 것`, `기록 템플릿`

## Catalog Metadata

Category: `meeting`
Phase: `preparation`
Hermes role: `operator`
Quality tier: `facilitation-gated`

Quality bar:

- Turn context into agenda topics, prompts, decisions needed, and a record template.
- Keep prep distinct from actual meeting minutes or accepted decisions.
- Identify missing context that would change the meeting structure.

Handoff policy:

Run meeting preparation in Hermes; only create follow-up coding handoff from observed decisions or accepted plans.

Required inputs:

- meeting goal
- audience
- known context
- decision topics

Expected outputs:

- agenda
- discussion prompts
- decisions needed
- action-item template

Artifact expectations:

- meeting brief or record template when the wrapper captures it

Safety rules:

- Do not claim the meeting happened from a prepared agenda.
- Separate proposed action items from observed decisions.
- Use a later status or decision record for actual meeting outcomes.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `meeting-facilitation`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill meeting-brief --harness meeting-facilitation --status started
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
