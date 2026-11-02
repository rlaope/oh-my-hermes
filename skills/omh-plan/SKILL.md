---
name: "omh-plan"
description: "[omh] Software feature or bugfix not yet planned: structured planning before execution. Use when the user says: plan, implementation plan, make a plan, write a plan, write the plan, task breakdown, safe feature, safely add a feature."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: plan
    role: planner
    quality_tier: acceptance-gated
---

# Plan

This is a Hermes-native `plan` workflow skill.

## Why This Exists

`plan` exists so a feature or a fix gets its goals, non-goals, risks, acceptance criteria, and verification shape written down and accepted by the user before any code moves, with every step small enough to check and no implementation hidden inside the plan text.

## Do Not Use When

- The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
- The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.

## Examples

Good example:

- Prompt: plan: handle a planning request that needs explicit evidence boundaries and a clear stop condition.
- Expected behavior: Run `plan` only after naming the target, evidence boundary, and stop condition.
- Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.

Bad example:

- Prompt: plan: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `plan`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Completion Checklist

- The plan names goals, non-goals, assumptions, acceptance criteria, and verification shape.
- Draft recommendations, accepted decisions, and executor handoffs are separate states.
- Rejected options or unresolved tradeoffs are recorded before handoff.
- When the plan describes code changes, it has a `Review Focus` section with at most 5 uncovered inputs and their owning task ids, or one stating the check found none.
- When the plan describes code changes, every task has an id, its dependencies, the files it may write, and a done check, and the last task is the closing gate.
- When the plan describes code changes, each code task is a vertical slice whose done check exercises its behavior end to end, or a prefactor ordered before the slices.
- When the plan describes code changes, it names the goal beyond the request, the raw material, and an outside judge for each verification step, or records the missing judge as an evidence gap.

## Recovery Notes

- If acceptance criteria or verification are missing, route back to clarification before handoff.
- If assumptions materially affect the plan, keep them visible and avoid treating the plan as accepted.

## Workflow Lane

- Current lane: **Intent -> plan** (`oh-my-hermes`, `meta-router`, `deep-interview`, `context`, `plan`, `ralplan`, `adversarial-consensus`, `codebase-onboarding`, `+9 more`) - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use for structured planning when implementation is not ready to start safely, including feature work that needs a safe plan before handoff.

    Strong routing signals: `plan`, `$plan`, `implementation plan`, `make a plan`, `write a plan`, `write the plan`, `task breakdown`, `safe feature`, `safely add a feature`, `add a feature`, `feature request`, `new feature`, `product triage`, `bug triage`, `issue triage`, `reproduction plan`, `workflow hub`, `coding handoff`, `project template`, `github pr workflow`, `実装計画`, `タスク分解`, `安全に機能追加`, `機能追加の計画`, `답할 차례`, `준비할 차례`, `재현 계획`, `요구사항 정리`, `작업 허브`, `작업 허브가 필요`, `상태와 다음 행동`, `프로젝트별 운영`, `сделай план`, `составь план`, `напиши план`, `спланируй`, `план реализации`, `实现计划`, `任务拆解`, `安全地新增功能`, `新增功能计划`, `susun rencana implementasi`, `pecah fitur ini jadi langkah pengerjaan`, `bantu rencanakan penambahan fitur`, `tolong bikin rencana perbaikan bug`, `susun tahapan implementasi sebelum mulai coding`, `lập kế hoạch thực hiện`, `chia tính năng này thành các bước thực hiện`, `giúp lên kế hoạch thêm tính năng`, `hãy lập kế hoạch sửa lỗi`, `xác định các giai đoạn thực hiện trước khi code`

## Catalog Metadata

Category: `planning`
Phase: `plan`
Hermes role: `planner`
Quality tier: `acceptance-gated`
Reasoning demand: `standard`

Quality bar:

- Make goals, non-goals, risks, acceptance criteria, and verification shape explicit.
- Where the repository declares non-negotiable principles, load `references/project-constitution.md` and record the check: a plan conflicting with a MUST is resolved by changing the plan, never by reinterpreting the principle.
- Keep draft plans unapproved until the user accepts; a wrapper must carry their answer.
- Only prepare coding handoff guidance after the plan is accepted.
- When the plan describes code changes, add a `Review Focus` section listing at most 5 inputs or failure modes the requirements imply that no planned test covers, likeliest first, each with its expected behavior and the id of the owning task that will add the test; an input the requirements do not mention must still leave the result intact, and when the check turns up nothing the section says it found none.
- When the plan describes code changes, keep each step to a single action whose outcome can be checked - a named test and what it asserts, an exact signature and its file, or a command and the output that counts as passing; a step that leaves the choice open (`TBD`, `make it robust`) is a gap.
- When the plan describes code changes, give each task a stable id (`T1`, `T2`, ...), the ids it depends on, the files it may write, and its done check (a checkable step as above; for a code task, a command with the result that counts as passing - the test's run command, a gate, or a grep for the signature - while a task that is not code may keep an observable check); when two tasks write the same file, one lists the other directly among its dependencies, since an order through a third task does not count. These carry a `dag-ulw` node's id, depends_on and write_scope, and the done check feeds its VERIFY and STOP WHEN; converting still adds each node's label, category and full prompt, and a baseline node before a full-suite check.
- When the plan describes code changes, cut the code tasks as vertical slices: each delivers one behavior through every layer it needs, and its done check drives that behavior through the surface a user or caller reaches, so an integration failure shows in the task that caused it rather than first in the closing gate. Do not split by layer to keep write scopes apart: two slices that write the same file are ordered, the later listing the earlier directly among its dependencies. A layer-only task is either a prefactor that makes the later slices easy and comes before them, or a wide mechanical change across many callers, which gets `refactor-plan`'s expand, migrate, and contract phases instead of a split by layer.
- When the plan describes code changes, its last task is the closing gate, named as the verification task (in `dag-ulw`, a node with `role: verify`): it depends on every other task, runs the real verification commands with the result that counts as passing, is run by someone other than the agent that built the work, and ends with a review. The plan states that a review that is not clean adds a fix task with its own id and done check and then reruns the gate instead of ending the plan - at most two fix rounds, or fewer when the engine running the plan stops sooner, after which the open findings are reported.
- When the plan describes code changes, run a proportion check before acceptance: if the plan text outgrows the code it leads to, or is mostly function bodies, implementation has leaked into it; reduce bodies to test names, assertions, and signatures.
- When the plan describes code changes, name the goal beyond the request before splitting tasks: one sentence on what should happen once the requested result exists, and whether the plan aims at that outcome or at the request as asked; when the two are the same, say so in one line. A plan aimed at the outcome adds, as its own tasks, the access the executor needs to work at that level unattended - failure logs, a reproduction environment, the raw data, the mapping from a released version to its commit.
- When the plan describes code changes, name the raw material the work starts from instead of a digest of it - the failing log, trace, or data rather than the issue summary - and the methods and tools a leading practitioner of the field would use on it. Every verification step names an outside judge - a test, CI, a measurement, a human reviewer, or an external tool - never the planning model's or the executor's own reading of the result; a step with no outside judge is recorded as an evidence gap.
- When the plan describes code changes, restate the deliverable once as the verbs it must accomplish rather than the noun it produces; when that brings in another field, write what a practitioner of that field does as a task (fuzz the parser, audit each completion claim against its evidence), never an instruction to write or speak like one.
- Take plan acceptance only from the answer the user gave — the response status and value the question tool returns, or the user's own reply — never from the wording of the question you asked: when the acceptance question times out, is dismissed, or returns with no answer, the plan stays unaccepted, so record no acceptance, prepare no handoff, and start nothing; a missing answer is not a refusal either, so ask again later or report the plan as awaiting acceptance.
- Plan acceptance approves the plan content, not execution: after acceptance, recommend the follow-on path that fits the work's shape — `dag-ulw` for an accepted plan whose tasks form a graph (several tasks with disjoint write scopes or an order between them, handing work on through files, plus a separate verification task), `ultrawork` durable checkpoints for progress that must survive sessions as a checkpointed ledger, `ultrawork` coordinated lanes for an accepted plan split into disjoint parallel lanes, `ultrawork` single-owner persistence for one already-scoped task with a single owner, `ultrawork` for one bounded delivery cycle, or a direct selected executor/runtime handoff for a single prepared coding change — state the fit reason in one line, and start it only after the user's explicit go-ahead.
- Hermes' built-in `/plan` writes one plan file under `.hermes/plans/` in a turn of its own that opens `[/plan — plan mode]` and executes nothing; in that turn, follow its instructions. When the user later asks to review, accept, or hand off that file, it is this skill's draft, not a reason to write a second plan: load `references/hermes-plan-mode.md`.

Handoff policy:

Keep planning in Hermes; if the accepted plan requires code edits, prepare a selected executor/runtime handoff after acceptance, and start a follow-on workflow engine only after the user explicitly confirms the recommended path.

Required inputs:

- requirements
- constraints
- known facts
- non-goals

Expected outputs:

- plan
- acceptance criteria
- verification strategy

Artifact expectations:

- plan artifact when durable execution will follow

Safety rules:

- Do not imply hidden Hermes runtime behavior.
- Use the smallest verification that can prove the claim.

## Runtime Evidence

Preferred harness for this skill: `planning`.

```sh
omh runtime record --skill plan --harness planning --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- When wrapper metadata includes `memory_review_card/v1` or `handoff_context_pack/v1`, treat it as reviewed OMH-local or wrapper-supplied context only. Use conflict-free context summaries to shape plans and handoffs, but do not claim Hermes internal memory was read or changed.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
