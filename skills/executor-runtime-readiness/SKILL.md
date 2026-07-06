---
name: executor-runtime-readiness
description: [omh] Hermes executor runtime readiness workflow: compare Codex, Claude Code, Hermes coding, and oh-my runtimes by available tools, missing tools, and handoff mode.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, executor-readiness]
    category: executor-readiness
    phase: runtime-selection
    role: handoff-guide
    quality_tier: workflow-surface-gated
---

# Executor Runtime Readiness

This is a Hermes-native `executor-runtime-readiness` workflow skill.

## Why This Exists

`executor-runtime-readiness` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.

## Examples

Good example:

- Prompt: executor-runtime-readiness can this task run in Codex, Claude Code, or Hermes coding?
- Expected behavior: Produce `prepare_executor_runtime_readiness` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: executor-runtime-readiness claim Codex already started the session.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- The selected coding or runtime owner is named before any implementation claim.
- Prepared handoff, dispatch, execution, verification, review, CI, and merge states are separated.
- The final status cites observed runtime evidence or keeps the work prepared_not_observed.
- When Hermes is the selected coding owner, use `hermes_coding_harness/v1` to keep builder, verifier, reviewer, docs, and PR lanes separate.
- Report the current harness stage, owner, next action, and missing evidence without claiming PR creation, review, CI, merge-readiness, or merge until matching runtime observations exist.

## Recovery Notes

- If the selected executor is unavailable, ask for Codex, Claude Code, Hermes, or another runtime before retrying.
- If dispatch or result evidence is missing, keep the handoff prepared_not_observed and expose the next observable action.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: choose skills, shape work, prepare artifacts, show status, and hand off with evidence boundaries.
- Current lane: **Coding handoff** (`idea-to-deploy`, `cto-loop`, `deploy-and-monitor`, `code-review`, `build-failure-triage`, `verification-gate`, `security-safety-review`, `ultrawork`, `+7 more`) - coding owners, handoffs, review, CI, and merge evidence.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: every OMH skill: match lane; generic tool can render or execute.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/accessibility-audit/visual-qa; paper->paper-learning; content->content-operator; file->materials-package; search->web-research; live info->live-info-operator; audit->workspace-audit/production-audit/security-safety-review; failures->build-failure-triage; verify->verification-gate; code->codegraph-refresh/codebase-onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is infra.
- Boundary: Prepared OMH routing, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when a user may choose Codex, Claude Code, Hermes coding, or another runtime and needs tool/credential gaps before handoff.

    Strong routing signals: `executor-runtime-readiness`, `executor readiness`, `runtime readiness`, `codex readiness`, `claude code readiness`, `hermes coding readiness`, `executor tools`, `missing tools`, `missing runtime tools`, `runtime tools`, `coding agent readiness`, `coding runtime`, `handoff mode`, `handoff readiness`, `codex or claude`, `codex vs claude`, `codex tools`, `claude code tools`, `hermes coding`, `agent runtime`, `subagent readiness`, `worktree readiness`, `codex로 넘길지 claude`, `claude code로 넘길지 codex`, `codex랑 claude`, `claude code 중`, `넘길지 codex`, `넘길지 claude`, `runtime migration`, `omx`, `omc`, `omo`, `코덱스`, `클로드 코드`, `헤르메스 코딩`, `코딩 에이전트`, `서브에이전트`, `작업트리`, `준비성`, `실행 런타임`, `어떤 런타임`, `런타임으로 넘겨`

## Catalog Metadata

Category: `executor-readiness`
Phase: `runtime-selection`
Hermes role: `handoff-guide`
Quality tier: `workflow-surface-gated`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

Executor readiness:

- When accepted work mutates code, check `executor_readiness/v1` for the selected Codex, Claude Code, Hermes, or oh-my runtime path before first dispatch.
- If readiness is `missing` or `blocked`, ask the user to choose another coding agent, configure PATH, continue in Hermes, or keep a prompt/runtime handoff; retry only after that state changes.
- A readiness probe is not dispatch, implementation, verification, review, CI, merge-readiness, or merge evidence.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- executor-runtime-readiness/v1 card or guidance
- next action
- prepared-vs-observed boundary

Artifact expectations:

- executor-runtime-readiness/v1 metadata-only runtime or wrapper card when recorded

Safety rules:

- Runtime readiness is not executor dispatch, plugin load, tool invocation, repository mutation, review, CI, or merge evidence.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `executor-runtime-readiness`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill executor-runtime-readiness --harness executor-runtime-readiness --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Respect `omh_target_topology/v1` when a wrapper reports it: bind state to the current target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, and fall back to single-target behavior when `active_agent_count` is one.
- When target topology changes from one to many or many to one, give a concise setup-change comment or use the wrapper's apply action before treating the new topology as persistent.
- Treat wrapper-supplied memory/context summaries as advisory local context, not proof that opaque Hermes memory was read or changed.
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
