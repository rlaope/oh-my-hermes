---
name: idea-to-deploy
description: [omh] Hermes Idea-to-Deploy workflow: shape an app idea into decisions, delivery handoff, verification, release, and monitoring status.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, delivery]
    category: delivery
    phase: app-delivery-loop
    role: retained-cognition
    quality_tier: delivery-gated
---

# Idea To Deploy

This is a Hermes-native `idea-to-deploy` workflow skill.

## Why This Exists

`idea-to-deploy` exists to keep `delivery` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
- The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.

## Examples

Good example:

- Prompt: idea-to-deploy: handle a delivery request that needs explicit evidence boundaries and a clear stop condition.
- Expected behavior: Run `idea-to-deploy` only after naming the target, evidence boundary, and stop condition.
- Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.

Bad example:

- Prompt: idea-to-deploy: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `idea-to-deploy`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Use When

Use when Hermes should carry a product or app idea through shaping, decision gates, plan acceptance, executor handoff, verification, release readiness, deploy, and monitoring boundaries.

    Strong routing signals: `idea-to-deploy`, `idea to deploy`, `from idea to deploy`, `plan to deploy`, `idea to launch`, `ship this idea`, `ship this feature`, `launch this feature`, `product delivery loop`, `app delivery loop`, `complete product loop`, `end-to-end app operation`, `완제품 루프`, `아이디어부터 배포`, `기획부터 배포`, `출시까지`, `앱 운영 루프`

## Catalog Metadata

Category: `delivery`
Phase: `app-delivery-loop`
Hermes role: `retained-cognition`
Quality tier: `delivery-gated`

Quality bar:

- Name the idea, user value, decision owner, non-goals, and success metric before planning delivery.
- Expose idea, decision, plan, handoff, verification, release, deploy, and monitor stages as separate status steps.
- Prepare coding handoffs only after plan acceptance and selected executor choice.
- Mark deploy, monitoring, and rollback as unobserved until the wrapper or operator records evidence.

Handoff policy:

Keep idea shaping, decision gates, planning, release narration, and status in Hermes; prepare selected executor handoffs only for accepted code work and record deploy/monitoring only from observed operator or wrapper evidence.

Required inputs:

- product idea
- target user or customer signal
- success metric
- repo or app context

Expected outputs:

- stage rail
- decision gates
- executor handoff criteria
- verification and deploy/monitor status boundaries

Artifact expectations:

- app delivery loop status record when the wrapper captures stage acceptance or observations

Safety rules:

- Do not claim implementation, deploy, health checks, rollback, or monitoring happened from a prepared loop.
- Keep coding, release, and monitoring observations as separate evidence gates.
- Ask for missing success metric, release scope, or executor choice before preparing a handoff.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `app-delivery-loop`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill idea-to-deploy --harness app-delivery-loop --status started
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
