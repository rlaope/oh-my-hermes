---
name: "omh-frontend-refactor"
description: "[omh] Oversized or tangled UI component: behavior-preserving refactor of UI code - preview the full change plan first, apply as a second explicit step."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, maintenance]
    category: maintenance
    phase: frontend-refactor
    role: handoff-guide
    quality_tier: behavior-lock-gated
---

# Frontend Refactor

This is an OMH `frontend-refactor` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`frontend-refactor` exists so UI restructuring runs as a previewed, behavior-locked, impact-ordered process instead of ad-hoc rewrites: the plan comes before any edit, state fixes come before polish, and every change carries its safety reason.

## Do Not Use When

- The target is not UI code, or the smell is generic slop, duplication, or dead code outside a component tree; use `omh-ai-slop-cleaner`.
- The user wants new UI built or redesigned rather than restructured; use `omh-frontend`.
- The user wants findings and a verdict without changing the code; use `omh-code-review`.
- The restructuring crosses module boundaries or changes architecture beyond the component tree; use `omh-refactor-plan` for the phased execution shape, or `ulw-plan` first when the direction itself is still contested.

## Examples

Good example:

- Prompt: This dashboard component is 800 lines and has six useState booleans - refactor it without changing behavior.
- Expected behavior: Preview first: characterization-test gate, then a plan that folds the booleans into one state union, extracts along change reasons found by the scroll test, and lists per-change line refs with safety reasons; apply only as the explicit second step.
- Why: Oversized component plus flag-cluster state is exactly the impact-ordered, behavior-locked restructuring this workflow owns.

Bad example:

- Prompt: Refactor and also add the dark-mode feature while you are in there.
- Expected behavior: Split the request: the behavior-preserving refactor runs under this workflow, and the dark-mode feature goes to `omh-frontend` as separate planned work.
- Why: A refactor that changes behavior cannot claim behavior preservation; mixing the two hides the feature from review.

## Completion Checklist

- The preview plan was emitted before any file changed, and the apply step was an explicit second decision.
- Behavior evidence exists on both sides of apply, and unsafe-in-isolation changes are listed as notes, not half-applied.
- Pass order was impact-first and each finding names its category and safety reason.
- Out-of-scope smells were routed: generic slop to `omh-ai-slop-cleaner`, new UI goes to `omh-frontend`, verdict-only review to `omh-code-review`.

## Recovery Notes

- If no tests exist, write the characterization checks first or hand the user the smallest set to approve; do not start the macro pass on unlocked behavior.
- If a change turns out to alter behavior mid-apply, revert that change, record it as a finding, and keep the rest of the pass.
- If the component resists extraction because state is tangled, run the state ladder first and re-attempt decomposition after.
- If the framework is not React, run only the micro pass and the characterization-test gate, say the hook, effect, and context content does not apply, and use the state ladder's principles (derive, colocate, one owner) only where the framework has the same idea.



## When to Use

Use when existing UI code needs restructuring without behavior change - an oversized component, boolean-flag state, effect chains, prop drilling - and the user wants a previewed, pass-ordered refactor plan rather than a new build or a verdict-only review.

    Strong routing signals: `frontend-refactor`, `front-refactor`, `frontend refactor`, `refactor this component`, `refactor the component`, `refactor my component`, `component refactor`, `react refactor`, `refactor this hook`, `split this component`, `split the component`, `this component is too big`, `component is too large`, `state management review`, `state management`, `state colocation`, `too many useeffects`, `useeffect cleanup`, `clean up useeffect`, `prop drilling`, `컴포넌트 리팩터링`, `컴포넌트 리팩토링`, `컴포넌트 분리`, `컴포넌트가 너무 커`, `상태 관리 정리`, `상태 관리 리뷰`, `프론트 리팩터링`, `프론트엔드 리팩터링`, `useEffect 정리`, `рефакторинг компонента`, `раздели компонент`, `компонент слишком большой`, `рефакторинг фронта`, `разбей компонент`

## Catalog Metadata

Category: `maintenance`
Phase: `frontend-refactor`
Quality tier: `behavior-lock-gated`
Reasoning demand: `heavy`

Quality bar:

- Work the ladder impact-first: state architecture before hook patterns before decomposition before naming and style - a state fix usually deletes the code a style pass would have polished.
- Make impossible states unrepresentable before memoizing anything: flag clusters become one discriminated union or reducer, and a state machine only when transitions carry retries, resets, or races.
- Treat effects as synchronization with external systems: deriving, event responses, prop-change resets, parent notification, and effect chains each have a non-effect form named in `omh-frontend-refactor/references/state-discipline.md`.
- Run the micro pass in fixed order - dead code, naming, simplification, modernization - finishing one category before the next; the full contract is `omh-frontend-refactor/references/refactor-passes.md`.
- Gate macro changes on characterization tests written before the refactor; snapshot tests lock markup, not behavior, and do not count. A change that alters DOM nesting, element type, or class composition also needs a before/after capture at one viewport, because green tests do not prove the render is unchanged.
- The scroll test picks the decomposition entry point, and extraction follows independent change reasons completely - a half-extracted component is two coupled ones.

Required inputs:

- the target files or component, and the framework in use
- current behavior evidence: tests, or the characterization checks to write first
- the diff budget: micro pass only, one macro tier, or full ladder

Expected outputs:

- preview change plan with per-change line refs, before/after, safety reason, and category counts
- impact-ordered pass selection naming what is deferred and why
- characterization-test gate verdict before any macro change
- apply-step handoff with the unsafe-in-isolation changes listed under notes, never half-applied

Artifact expectations:

- metadata-only runtime record when a wrapper or shell is available

Safety rules:

- Preview is the default: analyze the whole target and emit the plan before touching any file.
- Outputs, side effects, and error handling stay identical; a dropped branch or weakened handler is a defect, not a simplification.
- Never rename exports, change signatures, merge or split files, or alter async execution models without flagging a breaking change; cross-file renames are notes, not silent edits. Changes to props, exports, or file layout are proposals in notes until the user's second decision. `[behavior-changing]` items (remounts, new dependencies, caching, URL state, timing, a logout reset) never apply under this skill: route them to `omh-frontend` or a feature request and list them in notes.
- Do not refactor test files, and do not claim behavior preservation without the before/after test evidence.

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
