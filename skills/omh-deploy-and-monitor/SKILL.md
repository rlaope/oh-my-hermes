---
name: "omh-deploy-and-monitor"
description: "[omh] Release rollout needing health signals: release checklist, deploy decision, health signals, rollback gate, and post-deploy status. Use when the user says: deploy-and-monitor, deploy and monitor, deploy monitor, deployment monitoring, release monitor, post deploy, post-deploy, rollback."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, monitoring]
    category: monitoring
    phase: release-ops
    role: operator
    quality_tier: release-gated
    related_skills: [omh-live-incident-response, omh-release-cut, omh-iac-change]
---

# Deploy And Monitor

This is a Hermes-native `deploy-and-monitor` workflow skill.

## Why This Exists

`deploy-and-monitor` exists to keep `monitoring` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- An incident has already been declared and the work is commanding it -- severity, commander, running timeline, recovery verification -- rather than watching a release; use `omh-live-incident-response`.
- The ask is deciding a release before it ships -- what goes in, its version and tag, the canary stages, or which command rolls it back; use `omh-release-cut`, which writes the rollback trigger down before it is needed.
- The change is to declared infrastructure itself -- a Terraform plan, a Kubernetes manifest, a Helm chart -- and needs its drift, blast radius, and cost delta read before it is applied; use `omh-iac-change`.

## Examples

Good example:

- Prompt: deploy-and-monitor: prepare the release monitor, rollback signals, health checks, and post-deploy status card.
- Expected behavior: Create release monitoring guidance with deployment, metric, rollback, and observation boundaries.
- Why: The request is about deploy readiness and monitoring rather than code review alone.

Bad example:

- Prompt: deploy-and-monitor: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `deploy-and-monitor`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Completion Checklist

- Confirm the workflow target, evidence boundary, and stop condition are named.
- Report which outputs are prepared, observed, blocked, or missing.
- Name the smallest next verification or handoff instead of claiming completion from narration.

## Recovery Notes

- If a monitor has only its first baseline tick or a silent tick, retain the checklist and watchlist, mark release health not_observed, and hand back the recorded cron runs and open incidents needed to assess health.
- If the rollback owner is missing, retain the release scope and health signals, mark the deploy decision gate unresolved, and hand back the rollback criteria with the owner question before advancing.
- If a canary lacks host_deployment_observation/v1 or a pre-deploy production baseline, retain the checklist, mark the comparison unresolved and BLOCK, and hand back the missing observation or baseline without authorizing rollback.

## Workflow Lane

- Current lane: **Coding handoff** (`idea-to-deploy`, `llm-app-dev`, `cto-loop`, `deploy-and-monitor`, `code-review`, `build-failure-triage`, `verification-gate`, `security-safety-review`, `+28 more`) - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes should prepare or narrate a release operation with deploy checklist, health signals, rollback criteria, and post-deploy status without pretending to run infrastructure.

    Strong routing signals: `deploy-and-monitor`, `deploy and monitor`, `deploy monitor`, `deployment monitoring`, `release monitor`, `post deploy`, `post-deploy`, `rollback`, `rollback gate`, `health check`, `incident watch`, `release health`, `deploy this service`, `배포 모니터링`, `서비스 배포`, `프로덕션 배포`, `인프라에 배포`, `배포 감시`, `롤백`, `헬스 체크`, `장애 감시`, `릴리즈 모니터링`, `задеплой`, `выкатить релиз`, `мониторинг после деплоя`, `откат релиза`, `следи за деплоем`

## Catalog Metadata

Category: `monitoring`
Phase: `release-ops`
Hermes role: `operator`
Quality tier: `release-gated`
Reasoning demand: `light`

Quality bar:

- Name release scope, target environment, health signals, rollback criteria, and evidence owner.
- Show pre-deploy, deploy decision, monitor, rollback, and post-deploy as distinct stages.
- Mark health and rollback status unknown until observed evidence arrives.
- On Hermes, a watchlist that must keep running after this turn is prepared as a native blueprint through `omh-automation-blueprint` (a cron job whose `monitor` source, a health URL or a script whose output carries no timestamps, is the user's source, never one OMH writes), activated by the user or Hermes and never by OMH.
- On Hermes, the first monitor tick runs against a baseline with nothing to diff, so it is not a detected change; a silent tick says only that nothing was delivered (a no_change run, or an agent run that answered `[SILENT]`) and never that the release is healthy; a source that failed is an error, not a change; and what the job finds enters the post-deploy status only from its recorded runs (`hermes cron runs <job_id>`) and its open `hermes cron incidents`.

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
- web_qa_comparison/v1 for a canary only with a trusted host_deployment_observation/v1 and a production baseline captured before it

Artifact contracts:

This label denotes the machine-enforcement level, not a skill quality score and not an observed evidence state.

- contract_id: `deploy-and-monitor`; enforcement_level: `guidance_only`; consumer_id: `none`

Safety rules:

- Do not claim deployment, health checks, rollback, or incident response happened from a prepared checklist.
- Keep release readiness, deploy decision, monitor signals, and rollback as separate evidence steps.
- Route code fixes discovered during monitoring as later executor handoffs.
- A canary web-QA comparison never authorizes rollback; a missing deployment observation is BLOCK and a field regression beyond tolerance is REVISE.

## Runtime Evidence

Preferred harness for this skill: `app-delivery-loop`.

```sh
omh runtime record --skill deploy-and-monitor --harness app-delivery-loop --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- When wrapper metadata includes `memory_review_card/v1` or `handoff_context_pack/v1`, treat it as reviewed OMH-local or wrapper-supplied context only. Use conflict-free context summaries to shape plans and handoffs, but do not claim Hermes internal memory was read or changed.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
