---
name: "omh-idea-to-deploy"
description: "[omh] App idea headed for launch: shape an app idea into decisions, delivery handoff, verification, release, and monitoring status. Use when the user says: idea-to-deploy, idea to deploy, from idea to deploy, plan to deploy, idea to launch, ship this idea, ship this feature, launch this feature."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, delivery]
    category: delivery
    phase: app-delivery-loop
    role: operator
    quality_tier: delivery-gated
---

# Idea To Deploy

This is an OMH `idea-to-deploy` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

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

- The idea, user, success metric, and non-goals are written down.
- Each stage has an owner and the skill that runs it; plan acceptance and executor choice precede any coding handoff.
- Where it runs, how secrets are provided, and the first environment are decided before deploy; deploy evidence is observed.

## Recovery Notes

- If the success metric or release scope is missing, retain the supplied idea and user value, mark delivery planning unresolved, and hand back the stage rail with the missing decision before an executor handoff.
- If plan acceptance or executor choice is absent, retain the prepared decision gates and stage rail, mark the coding handoff unresolved, and hand back the acceptance or runtime-choice question.
- If deploy evidence is missing after verification, retain the observed verification results, mark deploy and monitoring not_observed, and hand back the stage rail with the deploy evidence gate still open.



## When to Use

Use when Hermes should carry a product or app idea through shaping, decision gates, plan acceptance, executor handoff, verification, release readiness, deploy, and monitoring boundaries, including a fresh or empty repository that needs the greenfield bootstrap pass (git, license, README, agent context file, CI skeleton) before delivery work starts.

    Strong routing signals: `idea-to-deploy`, `idea to deploy`, `from idea to deploy`, `plan to deploy`, `idea to launch`, `ship this idea`, `ship this feature`, `launch this feature`, `product delivery loop`, `app delivery loop`, `complete product loop`, `end-to-end app operation`, `ship this idea to production`, `bootstrap the project`, `bootstrap this project`, `bootstrap a new project`, `scaffold a new project`, `set up a new repo`, `완제품 루프`, `아이디어부터 배포`, `기획부터 배포`, `출시까지`, `앱 운영 루프`, `서비스로 만들어서 배포`, `아이디어를 서비스로`, `배포까지 가보자`

## Catalog Metadata

Category: `delivery`
Phase: `app-delivery-loop`
Quality tier: `delivery-gated`
Reasoning demand: `heavy`

Quality bar:

- Name the idea, user value, decision owner, non-goals, and success metric before planning delivery.
- Expose idea, decision, plan, handoff, verification, release, deploy, and monitor stages as separate status steps.
- Prepare coding handoffs only after plan acceptance and selected executor/runtime choice.
- Mark deploy, monitoring, and rollback as unobserved until the wrapper or operator records evidence.
- For a fresh, empty, or newly `git init`-ed target that is expected to outlive the session, run the greenfield bootstrap pass before or alongside delivery planning - load `references/project-bootstrap.md` for the six-step order (git and .gitignore, LICENSE, README, agent context file, CI skeleton, docs/ seed) and its per-file verify line; explicitly skip it for throwaway or scratch work instead of silently running it.
- Name the skill per stage: `backend`, `omh-relational-db`, `omh-frontend`, `omh-application-threat-model`, `omh-iac-change`, `omh-production-audit`, `omh-release-cut`, `omh-deploy-and-monitor`. Settle where it runs, how secrets are provided, and the first environment before deploy.

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
