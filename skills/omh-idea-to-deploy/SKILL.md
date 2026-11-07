---
name: "omh-idea-to-deploy"
description: "[omh] App idea headed for launch: shape an app idea into decisions, delivery handoff, verification, release, and monitoring status. Use when the user says: idea-to-deploy, idea to deploy, from idea to deploy, plan to deploy, idea to launch, ship this idea, ship this feature, launch this feature."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, delivery]
    category: delivery
    phase: app-delivery-loop
    role: operator
    quality_tier: delivery-gated
    related_skills: [ulw-work]
---

# Idea To Deploy

This is a Hermes-native `idea-to-deploy` workflow skill.

## Why This Exists

`idea-to-deploy` exists because an idea becomes a running product through decisions nobody owns together: it keeps metric, plan, executor, and release evidence as separate gates.

## Do Not Use When

- The task is already a concrete repo change whose stopping point is one PR-ready cycle, not product or release operations; use `ulw-work`.
- The request is a settings-only change, one bounded edit that is explicitly low-risk and has a direct owner and verification path, or a direct answer/diagnosis; handle it directly instead of opening a product delivery loop.

## Examples

Good example:

- Prompt: idea-to-deploy: turn this onboarding idea into a scoped plan, implementation handoff, QA gate, and release path.
- Expected behavior: Prepare the idea-to-release lane while keeping implementation, QA, and deploy evidence observed-only.
- Why: The request spans product shaping through deploy readiness instead of a single task.

Bad example:

- Prompt: idea-to-deploy: build the whole app and deploy it, I will check later.
- Expected behavior: Refuse the single jump: ask for the success metric and scope, then produce the stage rail with an owner per stage.
- Why: An unscoped build has no acceptance test and no rollback.

## Completion Checklist

- The idea, user, success metric, and non-goals are written down; each stage has an owner and the skill that runs it.
- Plan acceptance and executor choice precede any handoff; where it runs and how secrets are provided are decided before deploy.

## Recovery Notes

- If the success metric or release scope is missing, retain the supplied idea and user value, mark delivery planning unresolved, and hand back the stage rail with the missing decision before an executor handoff.
- If plan acceptance or executor choice is absent, retain the prepared decision gates and stage rail, mark the coding handoff unresolved, and hand back the acceptance or runtime-choice question.
- If deploy evidence is missing after verification, retain the observed verification results, mark deploy and monitoring not_observed, and hand back the stage rail with the deploy evidence gate still open.

## Workflow Lane

- Current lane: **Coding handoff** - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes should carry a product or app idea through shaping, decision gates, plan acceptance, executor handoff, verification, release readiness, deploy, and monitoring boundaries, including a fresh or empty repository that needs the greenfield bootstrap pass (git, license, README, agent context file, CI skeleton) before delivery work starts.

    Strong routing signals: `idea-to-deploy`, `idea to deploy`, `from idea to deploy`, `plan to deploy`, `idea to launch`, `ship this idea`, `ship this feature`, `launch this feature`, `product delivery loop`, `app delivery loop`, `complete product loop`, `end-to-end app operation`, `ship this idea to production`, `bootstrap the project`, `bootstrap this project`, `bootstrap a new project`, `scaffold a new project`, `set up a new repo`, `완제품 루프`, `아이디어부터 배포`, `기획부터 배포`, `출시까지`, `앱 운영 루프`, `서비스로 만들어서 배포`, `아이디어를 서비스로`, `배포까지 가보자`

## Catalog Metadata

Category: `delivery`
Phase: `app-delivery-loop`
Hermes role: `operator`
Quality tier: `delivery-gated`
Reasoning demand: `heavy`

Quality bar:

- Name the idea, user value, decision owner, non-goals, and success metric before planning delivery.
- Expose idea, decision, plan, handoff, verification, release, deploy, and monitor stages as separate status steps.
- Prepare coding handoffs only after plan acceptance and selected executor/runtime choice.
- Mark deploy, monitoring, and rollback as unobserved until the wrapper or operator records evidence.
- For a fresh, empty, or newly `git init`-ed target that is expected to outlive the session, run the greenfield bootstrap pass before or alongside delivery planning - load `references/project-bootstrap.md` for the six-step order (git and .gitignore, LICENSE, README, agent context file, CI skeleton, docs/ seed) and its per-file verify line; explicitly skip it for throwaway or scratch work instead of silently running it.
- Name the skill per stage: `omh-backend`, `omh-relational-db`, `omh-frontend`, `omh-application-threat-model`, `omh-iac-change`, `omh-production-audit`, `omh-release-cut`, `omh-deploy-and-monitor`. Settle where it runs, how secrets are provided, and the first environment before deploy.

Handoff policy:

Keep idea shaping, decision gates, planning, release narration, and status in Hermes; prepare selected executor/runtime handoffs only for accepted code work and record deploy/monitoring only from observed operator or wrapper evidence.

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

## Runtime Evidence

Preferred harness for this skill: `app-delivery-loop`.

```sh
omh runtime record --skill idea-to-deploy --harness app-delivery-loop --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- When wrapper metadata includes `memory_review_card/v1` or `handoff_context_pack/v1`, treat it as reviewed OMH-local or wrapper-supplied context only. Use conflict-free context summaries to shape plans and handoffs, but do not claim Hermes internal memory was read or changed.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
