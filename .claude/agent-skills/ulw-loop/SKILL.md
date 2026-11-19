---
name: "ulw-loop"
description: "[omh] Ambitious project goal needing many build cycles."
license: MIT
compatibility: "Requires the omh CLI on PATH (pip install oh-my-hermes)."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, goal-loop]
    category: goal-loop
    phase: continuous-goal-loop
    role: planner
    quality_tier: loop-gated
---

# Loop

This is an OMH `loop` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`loop` exists for goals whose correct implementation cannot be known upfront but can be discovered through bounded cycles of definition, action, verification, and revision without confusing planned cycles with observed progress.

## Do Not Use When

- The user asks for one bounded delivery cycle; use `ulw-work`'s delivery-boundary capability instead.
- Scope and milestones are already known and only durable checkpoint/resume tracking is needed; use `ulw-work`'s durable-checkpoint capability.
- The user gives only a north-star outcome such as revenue, stars, or adoption and declines the bounded first loop goal you proposed; stop at the proposed arena, problem and verification and wait.
- The goal is too vague to name an observable problem, next artifact, verification signal, or stop condition.
- The goal depends mainly on external waiting, adoption, revenue, or community response without observable local next actions.
- The permission profile does not allow repeated research, handoff, queue, or feedback cycles.

## Examples

Good example:

- Prompt: ./loop make OMH a credible Hermes workflow pack with install, docs, QA, and feedback cycles.
- Expected behavior: Start a permission-scoped loop, maintain loop_cycle/v2 selected-driver state, choose the next concrete task, and keep external outcomes as waiting states.
- Why: The request is long-horizon and needs repeated discovery, verification, feedback, and resume decisions.

Bad example:

- Prompt: ./loop merge this already reviewed one-line README fix.
- Expected behavior: Use a direct delivery or PR workflow instead of starting a persistent loop.
- Why: The task is bounded and should stop after merge evidence rather than create ongoing cycles.

## Completion Checklist

- The request is classified as task, project, north-star ambition, external-wait, or unclear before a loop starts.
- The current loop_status_card/v1 names the queue item, tick status, verification_plan, and next action.
- failure_mode_summary checks verification_gap, comprehension_debt, and cognitive_surrender before progress advances.
- Completion is backed by linked goal/runtime evidence; queued loop ticks alone are not observed work.
- Native goal activation remains unavailable unless independently observed in its owning runtime; host results never substitute for native activation or contiguous-turn evidence.

## Recovery Notes

- Drive the loop lifecycle through a native loop tool when this host offers one, submitting the revision the last read reported; the OMH native loop tool is unavailable in this projection, so keep the durable ledger with the host commands instead.
- If a queued tick is pending, show it as prepared queue state and use loop status/run-once before claiming progress.
- If feedback is unclear, ask one gate question or route back to `ulw-research` or `omh-plan` rather than advancing the loop.
- If the goal turns into external waiting, record the waiting state and next observable signal instead of continuing locally.
- Checkpoint on context/budget exhaustion. Migrate loop_cycle/v1 with migrate-driver --apply before external binding.
- Resume the current host's durable checklist from observed evidence. If native goal control is requested on an unsupported host, report unavailable instead of inventing activation.
- If the loop runs out of next actions, re-read the scoped files, recombine the near-miss attempts, then escalate to a more radical change before declaring the loop blocked.



## When to Use

Use when the user starts a high-level goal or invokes loop. Direct loop invocation means start/continue through interviewer, planner, researcher, builder, reviewer, and loop-controller lanes until a real gate stops it.

    Strong routing signals: `loop`, `./loop`, `$loop`, `goal loop`, `long horizon goal`, `never stop`, `research plan goal feedback`, `token exhaustion resume`, `permission profile`, `star 10k`, `10k star`, `loop engineering`, `keep running until done`, `루프`, `목표 루프`, `장기 목표`, `끝까지`, `토큰 고갈`, `피드백 루프`, `끝날 때까지 계속`, `계속 돌려줘`

## Catalog Metadata

Read `references/details.md` before you act: it holds this skill's quality bar and catalog metadata, kept out of this file so the whole of it fits in one read on every host.

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
