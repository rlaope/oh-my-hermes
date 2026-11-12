---
name: "omh-jit-learn"
description: "[omh] Blocked on a project by a knowledge gap: just-in-time learning workflow: select and confirm an immediate learning target, research credible sources…"
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: learning-target
    role: researcher
    quality_tier: source-gated
---

# Jit Learn

This is an OMH `jit-learn` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`jit-learn` exists to choose what is worth learning for the user's present problem and convert credible sources into an immediate application path, instead of returning a generic self-help shelf or a popularity list.

## Do Not Use When

- The user asks OMH to learn from workflow outcomes, missed routes, or evaluation traces.
- The learning goal is already chosen and the user wants a multi-week syllabus, instructional sequence, or assessment plan; use `omh-curriculum-design`.
- The user supplied a paper, PDF, arXiv entry, or excerpt and wants it explained; use `omh-paper-learning`.
- The requested output is a typed source candidate inventory or acquisition status rather than a fitted learning brief; use `omh-source-finder`.
- The research question and target are already scoped and the user wants current facts, citations, or source synthesis rather than choosing what to learn; use `ulw-research`.

## Examples

Good example:

- Prompt: What should I learn next to solve my current onboarding blocker? Recommend books, podcasts, creators, and courses I can apply this week.
- Expected behavior: Ask one confirmation question, confirm the immediate target, then prepare a source-backed learning brief ranked by fit and time-to-first-value.
- Why: The user needs target selection and immediate transfer, not a generic curriculum or popularity-ranked resource list.

Bad example:

- Prompt: Design a six-week Python syllabus with weekly assessments.
- Expected behavior: Route to `omh-curriculum-design` because the target is already chosen and the requested output is a sequenced curriculum.
- Why: Just-in-time target selection should not displace an explicit `omh-curriculum-design` request.

## Completion Checklist

- At least one confirmation question was answered, no turn contained more than one question, and the shared interview ceiling was respected.
- Urgency/trigger, current level, application window, and the target statement are explicit before research.
- Every admitted recommendation is source-gated and popularity signals did not influence admission or rank.
- Books, Podcasts, Creators, and Courses are present with complete fields or an honest empty-section reason.
- Competing targets, filtered-out defaults, unresolved gaps, and one starting action are visible.
- The final status says the brief is prepared and does not claim consumption, learning, application, progress, or blocker resolution.

## Recovery Notes

- If a required readiness dimension remains unclear, ask the one answer that most changes the target while the shared round budget remains.
- If the shared interview ceiling is reached, proceed with explicit assumptions and gaps rather than asking another question.
- If sources or links cannot be checked, leave the affected section empty with the retrieval reason instead of adding a generic recommendation.
- If the target becomes a syllabus, supplied-paper explanation, source inventory, already-scoped research question, or OMH self-improvement request, preserve the sibling boundary and route accordingly.



## When to Use

Use when selecting the highest-leverage immediate learning target for an active blocker before preparing a source-backed Markdown brief for direct application.

    Strong routing signals: `jit-learn`, `learn next`, `learn now`, `blocker-specific learning target`, `highest-leverage learning target`, `immediate learning payoff`, `immediately applicable learning brief`, `source-backed learning brief`, `학습 주제`, `도움 되는 학습 주제`, `당장 적용할 학습 목표`, `책 팟캐스트 크리에이터 강의 학습 브리프`, `объясни с нуля`, `разжуй тему`, `выучи и расскажи`

## Catalog Metadata

Category: `research`
Phase: `learning-target`
Quality tier: `source-gated`
Reasoning demand: `standard`

Quality bar:

- Resolve urgency/trigger, current level, and application window with one question per turn, while stopping early once all three are clear after the mandatory first answer.
- Confirm one target in the form `Learn X now so I can do/decide Y in context Z by T.` before source research.
- Prefer primary, institutional, and credible practitioner sources; rank by specific fit, authority, currency, time-to-first-value, and direct transfer rather than popularity.
- Keep Books, Podcasts, Creators, and Courses visible even when no candidate passes, and explain every empty section instead of padding it.
- For each admitted resource, state title, format, creator/publisher, link, source class, time to first value, specific fit, first application, and applicable link/access/currency caveats.
- Close with competing targets considered, filtered-out defaults, unresolved gaps, and exactly one recommended starting action.

Required inputs:

- reviewed context
- urgency
- current level
- application window
- time/format constraints

Expected outputs:

- confirmed target statement: Learn X now so I can do/decide Y in context Z by T.
- source-backed Markdown learning brief
- Books section, including an explicit no-qualifying-candidate reason when empty
- Podcasts section, including an explicit no-qualifying-candidate reason when empty
- Creators section, including an explicit no-qualifying-candidate reason when empty
- Courses section, including an explicit no-qualifying-candidate reason when empty
- for every recommendation: title, format, creator/publisher, link, source class, time to first value, specific fit now, first application, and caveats
- competing learning targets, filtered-out defaults, unresolved gaps, and one recommended next action

Artifact expectations:

- prepared Markdown learning brief with observed source links and explicit retrieval gaps when a wrapper captures it

Safety rules:

- Always ask at least one confirmation question before research, exactly one question per turn, even when the initial request appears complete.
- Use the shared `ulw-interview` ceiling of 6 rounds and its early-stop discipline; do not create a second interview budget.
- Use only the current conversation and reviewed or explicitly approved OMH context; never claim hidden Hermes memory or create a persistent learner profile.
- Admit recommendations only from primary, institutional, or credible practitioner evidence whose authority, currency, availability, and link can be checked; report retrieval gaps instead of inventing support.
- Never use bestseller status, ratings, follower counts, charts, generic popularity, or unsupported reputation as admission or ranking evidence.
- Do not purchase, download, enroll, subscribe, contact a creator, bypass a paywall, write to an external system, or imply any external action occurred.
- A prepared brief is not evidence that the user consumed a resource, learned, made progress, applied the advice, or resolved the original blocker.

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
