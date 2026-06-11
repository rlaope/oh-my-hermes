---
name: deploy-and-monitor
description: [omh] Hermes Deploy-and-Monitor workflow: release checklist, deploy decision, health signals, rollback gate, and post-deploy status.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, monitoring]
    category: monitoring
    phase: release-ops
    role: retained-cognition
    quality_tier: release-gated
---

# Deploy And Monitor

This is a Hermes-native `deploy-and-monitor` workflow skill.

## Why This Exists

`deploy-and-monitor` exists to keep `monitoring` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
- The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.

## Examples

Good example:

- Prompt: deploy-and-monitor: handle a monitoring request that needs explicit evidence boundaries and a clear stop condition.
- Expected behavior: Run `deploy-and-monitor` only after naming the target, evidence boundary, and stop condition.
- Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.

Bad example:

- Prompt: deploy-and-monitor: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `deploy-and-monitor`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Use When

Use when Hermes should prepare or narrate a release operation with deploy checklist, health signals, rollback criteria, and post-deploy status without pretending to run infrastructure.

    Strong routing signals: `deploy-and-monitor`, `deploy and monitor`, `deploy monitor`, `deployment monitoring`, `release monitor`, `post deploy`, `post-deploy`, `rollback`, `rollback gate`, `health check`, `incident watch`, `release health`, `배포 모니터링`, `배포 감시`, `롤백`, `헬스 체크`, `장애 감시`, `릴리즈 모니터링`

## Catalog Metadata

Category: `monitoring`
Phase: `release-ops`
Hermes role: `retained-cognition`
Quality tier: `release-gated`

Quality bar:

- Name release scope, target environment, health signals, rollback criteria, and evidence owner.
- Show pre-deploy, deploy decision, monitor, rollback, and post-deploy record as distinct stages.
- Mark health and rollback status unknown until observed evidence arrives.
- Convert fix follow-ups into separate accepted plans or executor handoffs.

Handoff policy:

Keep release checklist, health criteria, rollback gates, and status narration in Hermes; record deploy, monitor, incident, or rollback evidence only when the wrapper or operator observes it.

Required inputs:

- release scope
- environment
- health signals
- rollback owner

Expected outputs:

- pre-deploy checklist
- deploy decision gate
- monitoring watchlist
- rollback criteria
- post-deploy status boundary

Artifact expectations:

- release operation status record when the wrapper captures deploy or monitor observations

Safety rules:

- Do not claim deployment, health checks, rollback, or incident response happened from a prepared checklist.
- Keep release readiness, deploy decision, monitor signals, and rollback as separate evidence steps.
- Route code fixes discovered during monitoring as later executor handoffs.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `app-delivery-loop`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill deploy-and-monitor --harness app-delivery-loop --status started
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
