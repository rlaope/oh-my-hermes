---
name: agent-evaluation
description: [omh] Hermes Agent Evaluation workflow: compare executor or agent choices on reproducible tasks using quality, cost, time, tool, and evidence metrics.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: agent-evaluation
    role: operator
    quality_tier: agent-eval-gated
---

# Agent Evaluation

This is a Hermes-native `agent-evaluation` workflow skill.

## Why This Exists

`agent-evaluation` gives OMH a way to improve executor choice empirically, not by vibes, while preserving executor-neutral product language across Codex, Claude Code, Hermes, and generic runtimes.

## Do Not Use When

- The user needs current runtime readiness only; use `executor-runtime-readiness`.
- The user already selected an executor and wants implementation; use the coding handoff or delivery workflow.
- The user asks for workflow learning from a single failed route; use `workflow-learning`.

## Examples

Good example:

- Prompt: agent-evaluation Codex와 Claude Code를 같은 버그 수정 태스크로 비교해서 어떤 런타임을 기본으로 둘지 판단해줘.
- Expected behavior: Prepare task_benchmark_set/v1, run_result_matrix/v1 requirements, scorecard/v1, and scenario-specific recommendation.
- Why: The request compares executor choices and needs fair evaluation boundaries.

Bad example:

- Prompt: agent-evaluation 실행 증거 없이 Codex가 항상 최고라고 결론내줘.
- Expected behavior: Reject universal ranking and require observed runs or mark the recommendation as ungrounded.
- Why: Agent evaluation must be reproducible and evidence-backed.

## Completion Checklist

- Confirm the workflow target, evidence boundary, and stop condition are named.
- Report which outputs are prepared, observed, blocked, or missing.
- Name the smallest next verification or handoff instead of claiming completion from narration.

## Recovery Notes

- If required context is missing, ask one blocking question or route back to the narrower workflow.
- If runtime or wrapper evidence is unavailable, keep the status as not_observed and expose the next observable action.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, show status, and hand off with observed evidence boundaries.
- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `automation-blueprint`, `github-event-ops`, `agent-board`, `gateway-intent-card`, `voice-operator`, `+14 more`) - schedules, status, health, and release/ops review.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: For every OMH skill: match intent to a lane; name adjacent workflows; generic tool can render or execute is not a dismissal.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/visual-qa; paper->paper-learning; file->materials-package; search->web-research; audit->workspace-audit/production-audit/security-safety-review; verify->verification-gate; code->codegraph-refresh/codebase-onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is backend, setup, verification, and wrapper infrastructure.
- Boundary: Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when Hermes should design or summarize a fair comparison of Codex, Claude Code, Hermes coding, or generic executors for a bounded task set.

    Strong routing signals: `agent-evaluation`, `agent evaluation`, `agent eval`, `agent benchmark`, `executor evaluation`, `executor benchmark`, `compare agents`, `compare codex claude`, `agent tournament`, `which agent is better`, `에이전트 평가`, `에이전트 비교`, `실행자 평가`, `코덱스 클로드 비교`

## Catalog Metadata

Category: `operations`
Phase: `agent-evaluation`
Hermes role: `operator`
Quality tier: `agent-eval-gated`

Quality bar:

- Define tasks, rubric, isolation, budgets, and stop rules before comparing agents.
- Use the same inputs and success criteria across candidates unless the difference is the variable under test.
- Report quality, correctness, time, cost, tool coverage, verification, and review gaps separately.
- Recommend executor choice per scenario and confidence, not as a universal ranking.

Handoff policy:

Keep evaluation design and scoring in Hermes. Actual executor runs, costs, timings, tool calls, code edits, and review results must come from observed runtime or supplied artifacts.

Required inputs:

- candidate executors or agents
- task set and fixtures
- success criteria and scoring rubric
- allowed tools, budget, timebox, and isolation policy
- observed run artifacts when comparing completed attempts

Expected outputs:

- agent_eval_plan/v1
- task_benchmark_set/v1
- run_result_matrix/v1 when observed
- scorecard/v1
- selection_recommendation/v1
- not-evidence boundary

Artifact expectations:

- task_benchmark_set/v1 with reproducible tasks, fixtures, budgets, allowed tools, and acceptance criteria
- run_result_matrix/v1 with quality, correctness, time, cost, context, tool, verification, and review evidence when observed
- selection_recommendation/v1 with confidence, caveats, and winner-by-scenario rather than global mythology

Safety rules:

- Do not claim an executor is better from anecdotes, brand names, or unobserved runs.
- Do not send secrets, credentials, private data, or production tasks into evaluation without explicit authority.
- Keep benchmark design, observed run evidence, scoring, and executor selection separate.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `agent-evaluation`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill agent-evaluation --harness agent-evaluation --status started
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
