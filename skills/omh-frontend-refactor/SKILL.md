---
name: "omh-frontend-refactor"
description: "[omh] Oversized or tangled UI component: behavior-preserving refactor of UI code - preview the full change plan first, apply as a second explicit step, and work impact-ordered from state architecture down to naming polish. Use when the user says: frontend-refactor, front-refactor, frontend refactor, refactor this component, refactor the component, refactor my component, component refactor, react refactor."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, maintenance]
    category: maintenance
    phase: frontend-refactor
    role: handoff-guide
    quality_tier: behavior-lock-gated
    related_skills: [omh-ai-slop-cleaner, omh-frontend, omh-code-review, omh-refactor-plan, ulw-plan]
---

# Frontend Refactor

This is a Hermes-native `frontend-refactor` workflow skill.

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

## Workflow Lane

- Current lane: **Coding handoff** - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when existing UI code needs restructuring without behavior change - an oversized component, boolean-flag state, effect chains, prop drilling - and the user wants a previewed, pass-ordered refactor plan rather than a new build or a verdict-only review.

    Strong routing signals: `frontend-refactor`, `front-refactor`, `frontend refactor`, `refactor this component`, `refactor the component`, `refactor my component`, `component refactor`, `react refactor`, `refactor this hook`, `split this component`, `split the component`, `this component is too big`, `component is too large`, `state management review`, `state management`, `state colocation`, `too many useeffects`, `useeffect cleanup`, `clean up useeffect`, `prop drilling`, `컴포넌트 리팩터링`, `컴포넌트 리팩토링`, `컴포넌트 분리`, `컴포넌트가 너무 커`, `상태 관리 정리`, `상태 관리 리뷰`, `프론트 리팩터링`, `프론트엔드 리팩터링`, `useEffect 정리`, `рефакторинг компонента`, `раздели компонент`, `компонент слишком большой`, `рефакторинг фронта`, `разбей компонент`

## Catalog Metadata

Category: `maintenance`
Phase: `frontend-refactor`
Hermes role: `handoff-guide`
Quality tier: `behavior-lock-gated`
Reasoning demand: `heavy`

Quality bar:

- Work the ladder impact-first: state architecture before hook patterns before decomposition before naming and style - a state fix usually deletes the code a style pass would have polished.
- Make impossible states unrepresentable before memoizing anything: flag clusters become one discriminated union or reducer, and a state machine only when transitions carry retries, resets, or races.
- Treat effects as synchronization with external systems: deriving, event responses, prop-change resets, parent notification, and effect chains each have a non-effect form named in `omh-frontend-refactor/references/state-discipline.md`.
- Run the micro pass in fixed order - dead code, naming, simplification, modernization - finishing one category before the next; the full contract is `omh-frontend-refactor/references/refactor-passes.md`.
- Gate macro changes on characterization tests written before the refactor; snapshot tests lock markup, not behavior, and do not count. A change that alters DOM nesting, element type, or class composition also needs a before/after capture at one viewport, because green tests do not prove the render is unchanged.
- The scroll test picks the decomposition entry point, and extraction follows independent change reasons completely - a half-extracted component is two coupled ones.

Handoff policy:

Hermes prepares the preview plan, pass order, and characterization-test gate; the apply step is coding work for the selected executor lane, and behavior preservation is claimed only from observed test runs before and after apply.

Executor readiness:

- When accepted work mutates code, check `executor_readiness/v1` for the selected Codex, Claude Code, Hermes, or oh-my runtime path before first dispatch.
- If readiness is `missing` or `blocked`, ask the user to choose another coding agent, configure PATH, continue in Hermes, or keep a prompt/runtime handoff; retry only after that state changes.
- A readiness probe is not dispatch, implementation, verification, review, CI, merge-readiness, or merge evidence.

Delegation transparency:

- When delegating, show the composed delegate prompt in a fenced code block in the status message; truncate a long prompt to a bounded preview ending with `... [truncated, N chars total]`.
- Name every delegated or parallel lane's model and, when the host exposes it, its reasoning effort inline as `(model effort)` in status and briefing lines — including runtime-native subagents; when no effort is exposed, show the model alone as `(model)` rather than writing a placeholder like `unknown` beside a known model, and never emit empty parentheses. Carry token and elapsed figures the same way in these narration lines: report observed figures and omit unobserved ones — when the user asks for a figure directly, say it was not observed instead of omitting it; a rendered status-board column keeps its own `unknown` cell.
- Capture a resumable session or thread id at dispatch and report it in the status message: for non-interactive Claude Code pass `--output-format json` and read `session_id` from the result (resume with `claude -p --resume <session-id>`); for Codex pass `--json` and read `thread_id` (resume with `codex exec resume <thread-id>`, repeating `--skip-git-repo-check` outside a git repo). Never leave a delegate run with no recorded way to resume or steer it.
- Before dispatch, grant the executor session every permission the task will need — file write/edit, command/test execution, and the working directory — on the dispatch command itself, not through settings-file guesses: for non-interactive Claude Code pass `--permission-mode acceptEdits` or an explicit `--allowedTools` list (`--dangerously-skip-permissions` only inside an isolated worktree or sandbox), and the equivalent sandbox/approval flags for other CLIs. `acceptEdits: true` is not a settings key and `~/.claude/settings.local.json` is not a file Claude Code reads — user scope is `~/.claude/settings.json` and project scope is the dispatch cwd's `.claude/settings.local.json` with rules under `permissions.allow`. Prove the grant with a bounded scratch-edit probe run before the real dispatch: a permission denial in a non-interactive run recurs identically on retry, so never redispatch until a changed grant is proven, and surface an ungrantable permission as a blocker before dispatch, not after minutes of silence.

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

Preferred harness for this skill: `coding-handling`.

```sh
omh runtime record --skill frontend-refactor --harness coding-handling --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
