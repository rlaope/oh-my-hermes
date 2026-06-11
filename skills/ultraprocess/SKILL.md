---
name: ultraprocess
description: Ultra Process - Research - Ralplan - Ultragoal - Code Review - Sync Circle: one PR-ready delivery cycle.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, process]
    category: process
    phase: single-cycle-plan-to-pr
    role: retained-cognition
    quality_tier: process-gated
---

# Ultraprocess

This is a Hermes-native `ultraprocess` workflow skill.

## Use When

Use when the user asks Hermes to take a concrete task through one full delivery cycle: research/codebase context, reviewed plan, selected implementation handoff, code review, docs sync when needed, and PR preparation.

    Strong routing signals: `ultraprocess`, `$ultraprocess`, `./ultraprocess`, `/ultraprocess`, `single-cycle delivery`, `one-cycle delivery`, `end-to-end process`, `delivery process`, `research plan implement review docs pr`, `plan implement review docs pr`, `ralplan ultragoal code-review`, `codebase research web research planning implementation review docs sync pr`, `docs sync`, `pr-ready`, `prepare a pr`, `sync docs and prepare a pr`, `code-review sync docs and prepare a pr`, `make a pr`, `open a pr`, `끝까지 해줘`, `PR까지`, `계획 구현 리뷰 문서 PR`, `기획 구현 리뷰 문서 PR`, `코드베이스 조사 웹리서치 계획 구현 리뷰 문서 최신화 PR`, `문서 최신화 PR`

## Catalog Metadata

Category: `process`
Phase: `single-cycle-plan-to-pr`
Hermes role: `retained-cognition`
Quality tier: `process-gated`

Quality bar:

- Complete exactly one plan-to-PR delivery cycle, then stop with status, evidence gaps, or a next recommended workflow.
- Start with codebase/source research and a ralplan-style decision record before implementation handoff.
- Use ultragoal or the selected executor path for implementation, with acceptance criteria and verification commands attached.
- Run code-review as a gate after implementation evidence exists; review preparation alone is not review evidence.
- Add docs-specialist sync when public behavior, commands, setup, examples, or claims changed.
- End with a PR-ready or PR-observed report that separates prepared, executed, reviewed, verified, CI, and PR evidence.

Handoff policy:

Keep the one-cycle process orchestration, source/codebase research, planning, review framing, docs-sync checks, PR narration, and evidence boundaries in Hermes; convert implementation into a selected executor handoff such as Codex, Claude Code, another coding agent, or explicit Hermes-retained work only when the user accepts that owner.

Required inputs:

- task statement
- repo or workspace context
- executor preference or choose-at-handoff policy
- verification expectations

Expected outputs:

- ralplan-ready context and plan
- ultragoal or selected executor handoff
- code-review gate
- docs sync checklist
- single-cycle PR-ready summary with observed evidence and gaps

Artifact expectations:

- process checklist or runtime record when a wrapper can observe the stages
- prepared handoff artifact only after implementation owner selection
- docs-specialist claim check when public behavior changes

Safety rules:

- Do not skip planning when the request is broad, risky, or user-visible.
- Do not continue into a repeated feedback loop; recommend `loop` when the user wants ongoing cycles.
- Do not claim implementation, review, CI, merge readiness, or PR creation without observed executor or GitHub evidence.
- Keep web research source-backed and permission-aware; do not run hidden network or LLM calls from OMH core.
- Run docs sync only when behavior, setup, commands, or public claims changed.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `goal-execution`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill ultraprocess --harness goal-execution --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Respect `omh_target_topology/v1` when a wrapper reports it: bind state to the current target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, and fall back to single-target behavior when `active_agent_count` is one.
- When target topology changes from one to many or many to one, give a concise setup-change comment or use the wrapper's apply action before treating the new topology as persistent.
- When wrapper metadata includes `memory_review_card/v1` or `handoff_context_pack/v1`, treat it as reviewed OMH-local or wrapper-supplied context only. Use conflict-free context summaries to shape plans and handoffs, but do not claim Hermes internal memory was read or changed.
- When a runtime-specific mechanism appears in imported instructions, translate it to a Hermes-native artifact:
  - goal tools -> `.omh/goals/` ledgers, `goal_completion_gate/v1`, `goal_status_card/v1`, `goal_continuation/v1`, or explicit checklists with named next actions,
  - question renderers -> one concise question in the current Hermes interface,
  - native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - shell bridge commands -> optional bridge mode only.

## Execution Rules

1. Load supporting context with `skills_list` / `skill_view` when needed.
2. State the workflow target, constraints, validation evidence, and stop condition.
3. Keep progress evidence-backed.
4. Verify with the smallest relevant test or inspection before claiming completion.
5. If Hermes cannot provide a required runtime capability, say so and use the fallback above.
