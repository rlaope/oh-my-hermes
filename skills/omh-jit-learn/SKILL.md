---
name: "omh-jit-learn"
description: "[omh] Just-in-time learning workflow: select and confirm an immediate learning target, research credible sources, and prepare an application-first brief without popularity ranking. Use when the user says: jit-learn, learn next, learn now, blocker-specific learning target, highest-leverage learning target, immediate learning payoff, immediately applicable learning brief, source-backed learning brief."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: learning-target
    role: researcher
    quality_tier: source-gated
---

# Jit Learn

This is a Hermes-native `jit-learn` workflow skill.

## Why This Exists

`jit-learn` exists to choose what is worth learning for the user's present problem and convert credible sources into an immediate application path, instead of returning a generic self-help shelf or a popularity list.

## Do Not Use When

- The user asks OMH to learn from workflow outcomes, missed routes, or evaluation traces; use `workflow-learning`.
- The learning goal is already chosen and the user wants a multi-week syllabus, instructional sequence, or assessment plan; use `curriculum-design`.
- The user supplied a paper, PDF, arXiv entry, or excerpt and wants it explained; use `paper-learning`.
- The requested output is a typed source candidate inventory or acquisition status rather than a fitted learning brief; use `source-finder`.
- The research question and target are already scoped and the user wants current facts, citations, or source synthesis rather than choosing what to learn; use `research`.

## Examples

Good example:

- Prompt: What should I learn next to solve my current onboarding blocker? Recommend books, podcasts, creators, and courses I can apply this week.
- Expected behavior: Ask one confirmation question, confirm the immediate target, then prepare a source-backed four-section learning brief ranked by fit and time-to-first-value.
- Why: The user needs target selection and immediate transfer, not a generic curriculum or popularity-ranked resource list.

Bad example:

- Prompt: Design a six-week Python syllabus with weekly assessments.
- Expected behavior: Route to `curriculum-design` because the target is already chosen and the requested output is a sequenced curriculum.
- Why: Just-in-time target selection should not displace an explicit curriculum-design request.

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

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `best-practice-research`, `autoresearch-goal`, `model-optimization`, `inference-serving`, `+17 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when selecting the highest-leverage immediate learning target for an active blocker before preparing a source-backed Markdown brief for direct application.

    Strong routing signals: `jit-learn`, `learn next`, `learn now`, `blocker-specific learning target`, `highest-leverage learning target`, `immediate learning payoff`, `immediately applicable learning brief`, `source-backed learning brief`, `학습 주제`, `도움 되는 학습 주제`, `당장 적용할 학습 목표`, `책 팟캐스트 크리에이터 강의 학습 브리프`

## Catalog Metadata

Category: `research`
Phase: `learning-target`
Hermes role: `researcher`
Quality tier: `source-gated`
Reasoning demand: `standard`

Quality bar:

- Resolve urgency/trigger, current level, and application window with one question per turn, while stopping early once all three are clear after the mandatory first answer.
- Confirm one target in the form `Learn X now so I can do/decide Y in context Z by T.` before source research.
- Prefer primary, institutional, and credible practitioner sources; rank by specific fit, authority, currency, time-to-first-value, and direct transfer rather than popularity.
- Keep Books, Podcasts, Creators, and Courses visible even when no candidate passes, and explain every empty section instead of padding it.
- For each admitted resource, state title, format, creator/publisher, link, source class, time to first value, specific fit, first application, and applicable link/access/currency caveats.
- Close with competing targets considered, filtered-out defaults, unresolved gaps, and exactly one recommended starting action.

Handoff policy:

Keep reviewed-context interpretation, the bounded one-question-at-a-time interview, target selection, source research, and Markdown brief preparation in Hermes. Do not create a learner profile, take an external action, or claim that a recommendation was consumed, learned, applied, or resolved the blocker.

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
- Use the shared deep-interview ceiling of 6 rounds and its early-stop discipline; do not create a second interview budget.
- Use only the current conversation and reviewed or explicitly approved OMH context; never claim hidden Hermes memory or create a persistent learner profile.
- Admit recommendations only from primary, institutional, or credible practitioner evidence whose authority, currency, availability, and link can be checked; report retrieval gaps instead of inventing support.
- Never use bestseller status, ratings, follower counts, charts, generic popularity, or unsupported reputation as admission or ranking evidence.
- Do not purchase, download, enroll, subscribe, contact a creator, bypass a paywall, write to an external system, or imply any external action occurred.
- A prepared brief is not evidence that the user consumed a resource, learned, made progress, applied the advice, or resolved the original blocker.

## Just-in-Time Learning Protocol

1. Review only the current conversation and reviewed or explicitly approved OMH context. Never claim access to hidden Hermes memory and never create a learner profile.
2. Always ask at least one confirmation question before research, including when the request appears complete. Ask exactly one question per turn. Resolve three readiness dimensions: **urgency/trigger** (why now), **current level** (what the user already knows or can do), and **application window** (where and by when this will be used), plus only practical constraints that change the recommendation. Record this evidence step as `confirmation_asked`.
3. Reuse the deep-interview early-stop discipline and its shared ceiling of 6 rounds. After the mandatory first answer, stop asking as soon as the three readiness dimensions are clear. If the ceiling is reached, state assumptions and gaps instead of asking again.
4. Confirm one target before research in exactly this semantic form: `Learn X now so I can do/decide Y in context Z by T.` Here T means the application deadline. When the initial request already supplies all readiness dimensions, use the mandatory first question to confirm this target so research can begin after one answer.
5. Scope research around that target. Prefer primary, institutional, and credible practitioner sources; check authority, currency, availability, and links. Admit and rank by specific fit, authority, currency, time-to-first-value, and direct transfer. Never admit or rank from bestseller status, ratings, followers, charts, generic popularity, or unsupported reputation.
6. Prepare the Markdown brief, then stop. Do not buy, download, enroll, subscribe, contact creators, bypass access controls, write externally, or imply those actions happened.

## Learning Brief Contract

Start with the confirmed target statement and a short source-boundary note. Then render all four headings, even when empty:

- `## Books`
- `## Podcasts`
- `## Creators`
- `## Courses`

Under every heading, list only candidates that passed the source gate. If none passed, say why - for example, insufficient authority, stale or unavailable evidence, poor immediate fit, or an unresolved retrieval gap - rather than padding the section.

For every recommendation include:

- **Title**
- **Format**
- **Creator/Publisher**
- **Link**
- **Source class** - primary, institutional, or credible practitioner
- **Time to first value**
- **Why it fits** - why it fits this user, target, level, and application window
- **First immediate application** - the first concrete use in the user's present context
- **Link/currency caveat** - link, availability, access, or currency limits when applicable

Close with `## Competing Targets Considered`, `## Filtered Out`, `## Gaps`, and `## Next Action`. Name the competing learning targets, generic defaults or resources rejected and why, unresolved evidence/context gaps, and exactly one recommended starting action.

The terminal state is `learning_brief_prepared`: the brief is prepared, not observed learning. Preparation does not prove source consumption, learning, progress, application, effectiveness, or resolution of the original blocker.

## Runtime Evidence

Preferred harness for this skill: `jit-learn`.

```sh
omh runtime record --skill jit-learn --harness jit-learn --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
