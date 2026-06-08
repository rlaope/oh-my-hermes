---
name: cto-loop
description: Hermes CTO Loop workflow: roadmap, PM, technical tradeoffs, risk, delivery, release, and follow-up operating cadence.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, leadership]
    category: leadership
    phase: operating-loop
    role: retained-cognition
    quality_tier: decision-gated
---

# Cto Loop

This is a Hermes-native `cto-loop` workflow skill.

## Use When

Use when Hermes should run a leadership-style operating loop that turns signals into roadmap decisions, technical tradeoffs, delivery risk, release readiness, and explicit follow-up handoffs.

    Strong routing signals: `cto-loop`, `cto loop`, `cto`, `cto pm`, `pm dev qa security ops`, `roadmap technical tradeoffs`, `technical tradeoff`, `delivery risk`, `release readiness`, `technical leadership loop`, `leadership operating loop`, `engineering leadership`, `CTO 구조`, `PM 구조`, `로드맵`, `아키텍처 트레이드오프`, `기술 리더십`, `출시 준비`

## Catalog Metadata

Category: `leadership`
Phase: `operating-loop`
Hermes role: `retained-cognition`
Quality tier: `decision-gated`

Quality bar:

- Separate product priority, architecture tradeoff, delivery risk, release risk, and follow-up owner.
- Tie recommendations to observed signals or mark assumptions.
- Record accepted decisions separately from draft recommendations.
- Prepare executor handoffs only for accepted implementation follow-ups.

Handoff policy:

Keep CTO/PM-style synthesis, tradeoffs, risk ranking, decision notes, and status in Hermes; convert accepted implementation follow-ups into executor-neutral handoffs.

Required inputs:

- operating signals
- roadmap or release scope
- known risks
- decision owner

Expected outputs:

- priority frame
- architecture tradeoffs
- delivery risks
- decision note
- follow-up handoff candidates

Artifact expectations:

- leadership loop record or status summary when a wrapper captures decisions and follow-ups

Safety rules:

- Do not treat a CTO loop recommendation as an accepted roadmap decision.
- Do not imply CTO, PM, QA, Security, or Ops runtime agents exist without observed wrapper evidence.
- Separate strategy decisions from implementation handoffs and release evidence.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `app-delivery-loop`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill cto-loop --harness app-delivery-loop --status started
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
