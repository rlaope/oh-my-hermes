---
name: "omh-deploy-and-monitor"
description: "[omh] Release rollout needing health signals: release checklist, deploy decision, health signals, rollback gate, and post-deploy status."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, monitoring]
    category: monitoring
    phase: release-ops
    role: operator
    quality_tier: release-gated
---

# Deploy And Monitor

This is an OMH `deploy-and-monitor` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`deploy-and-monitor` exists because a deploy is judged healthy by whoever last looked at a dashboard: it fixes the baseline before the change and names the thresholds that mean roll back.

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

- Prompt: deploy-and-monitor: ship it and tell me when it is healthy.
- Expected behavior: Refuse a health claim; name the missing baseline, signals, window, and rollback owner.
- Why: Healthy with no baseline is whatever the dashboard shows after the fact.

## Completion Checklist

- Each health signal has a pre-deploy baseline, a threshold, a window, and an action.
- The rollback owner and trigger are named, with a bake time and schema compatibility.
- Post-deploy status cites observed values or reads not_observed.

## Recovery Notes

- If a monitor has only its first baseline tick or a silent tick, retain the checklist and watchlist, mark release health not_observed, and hand back the recorded cron runs and open incidents needed to assess health.
- If the rollback owner is missing, retain the release scope and health signals, mark the deploy decision gate unresolved, and hand back the rollback criteria with the owner question before advancing.
- If a canary lacks host_deployment_observation/v1 or a pre-deploy production baseline, retain the checklist, mark the comparison unresolved and BLOCK, and hand back the missing observation or baseline without authorizing rollback.



## When to Use

Use when Hermes should prepare or narrate a release operation with deploy checklist, health signals, rollback criteria, and post-deploy status without pretending to run infrastructure.

    Strong routing signals: `deploy-and-monitor`, `deploy and monitor`, `deploy monitor`, `deployment monitoring`, `release monitor`, `post deploy`, `post-deploy`, `rollback`, `rollback gate`, `health check`, `incident watch`, `release health`, `deploy this service`, `배포 모니터링`, `서비스 배포`, `프로덕션 배포`, `인프라에 배포`, `배포 감시`, `롤백`, `헬스 체크`, `장애 감시`, `릴리즈 모니터링`, `задеплой`, `выкатить релиз`, `мониторинг после деплоя`, `откат релиза`, `следи за деплоем`

## Catalog Metadata

Category: `monitoring`
Phase: `release-ops`
Quality tier: `release-gated`
Reasoning demand: `light`

Quality bar:

- Name release scope, target environment, health signals, rollback criteria, and evidence owner.
- Show pre-deploy, deploy decision, monitor, rollback, and post-deploy as distinct stages.
- Mark health and rollback status unknown until observed evidence arrives.
- A watchlist that must keep running after this turn is prepared for a scheduler the user runs, with the user's own source (a health URL or a script whose output carries no timestamps, never one OMH writes), and is activated by the user, never by OMH.
- On Hermes, the first monitor tick runs against a baseline with nothing to diff, so it is not a detected change; a silent tick says only that nothing was delivered (a no_change run, or an agent run that answered `[SILENT]`) and never that the release is healthy; a source that failed is an error, not a change; and what the job finds enters the post-deploy status only from its recorded runs (`hermes cron runs <job_id>`) and its open `hermes cron incidents`.
- Name an error, a latency, and a saturation signal per service and record each pre-deploy value over the same window; healthy is a comparison to that baseline.
- Set a bake time, and list migrations and flags in the decision gate with whether the old version still runs on the new schema.

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
