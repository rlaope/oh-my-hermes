---
name: deep-interview
description: Hermes Deep Interview workflow: one-question-at-a-time clarification.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, clarification]
    category: clarification
    phase: discovery
    role: retained-cognition
    quality_tier: clarity-gated
---

# Deep Interview

This is a Hermes-native `deep-interview` workflow skill.

## Use When

Use before planning or execution when requirements are materially ambiguous.

    Strong routing signals: `deep-interview`, `$deep-interview`, `interview`, `don't assume`, `clarify`, `feature shaping`, `ambiguous product request`, `one question`, `온보딩`, `부드럽게`, `모호한 제품 요청`, `기획자`, `개발자 사이`

## Catalog Metadata

Category: `clarification`
Phase: `discovery`
Hermes role: `retained-cognition`
Quality tier: `clarity-gated`

Quality bar:

- Ask exactly one blocking question per turn unless the wrapper explicitly supports a structured batch.
- Tie each question to a missing decision that changes the plan, handoff, or stop condition.
- Emit a clarified brief with non-goals and acceptance criteria before planning or delegation.

Handoff policy:

Run directly in Hermes or the chat wrapper; produce a clarified brief before any coding handoff is prepared.

Required inputs:

- initial request
- known repo facts
- current ambiguity

Expected outputs:

- clarified brief
- non-goals
- decision boundaries

Artifact expectations:

- clarity summary or transcript when the wrapper supports it

Safety rules:

- Ask one question at a time.
- Gather discoverable repo facts before asking the user.
- Stop interviewing once ambiguity is low enough to plan.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `deep-interview`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill deep-interview --harness deep-interview --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Respect `omh_target_topology/v1` when a wrapper reports it: bind state to the current target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, and fall back to single-target behavior when `active_agent_count` is one.
- When target topology changes from one to many or many to one, give a concise setup-change comment or use the wrapper's apply action before treating the new topology as persistent.
- When wrapper metadata includes `memory_review_card/v1` or `handoff_context_pack/v1`, treat it as reviewed OMH-local or wrapper-supplied context only. Use conflict-free context summaries to shape plans and handoffs, but do not claim Hermes internal memory was read or changed.
- When a runtime-specific mechanism appears in imported instructions, translate it to a Hermes-native artifact:
  - goal tools -> `.omh/goals/` ledgers or explicit checklists,
  - question renderers -> one concise question in the current Hermes interface,
  - native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - shell bridge commands -> optional bridge mode only.

## Execution Rules

1. Load supporting context with `skills_list` / `skill_view` when needed.
2. State the workflow target, constraints, validation evidence, and stop condition.
3. Keep progress evidence-backed.
4. Verify with the smallest relevant test or inspection before claiming completion.
5. If Hermes cannot provide a required runtime capability, say so and use the fallback above.
