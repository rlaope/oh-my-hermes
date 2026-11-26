# Agent Evaluation

Load this on-demand contract after the compact `agent-evaluation` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user needs current runtime readiness only; use `omh-executor-runtime-readiness`.
- The user already selected an executor and wants implementation; use the coding handoff or delivery workflow.
- The user asks for workflow learning from a single failed route; use `omh-workflow-learning`.
- The ask is to find and fix runtime, memory, cost, or rendering hotspots rather than score executor or model output quality; use `ulw-perf`.

## Examples

Good example:

- Prompt: agent-evaluation Codex와 Claude Code를 같은 버그 수정 태스크로 비교해서 어떤 런타임을 기본으로 둘지 판단해줘.
- Expected behavior: Prepare paired_run_decision/v2 requirements and a scenario-specific recommendation.
- Why: The request compares executor choices and needs fair evaluation boundaries.

Bad example:

- Prompt: agent-evaluation 실행 증거 없이 Codex가 항상 최고라고 결론내줘.
- Expected behavior: Reject universal ranking and require observed runs or mark the recommendation as ungrounded.
- Why: Agent evaluation must be reproducible and evidence-backed.

## Full Input, Output, and Artifact Expectations

Required inputs:

- candidate executors or agents
- task set and fixtures
- success criteria and scoring rubric
- allowed tools, budget, timebox, and isolation policy
- observed run artifacts when comparing completed attempts

Expected outputs:

- paired_run_decision/v2
- not-evidence boundary

Artifact expectations:

- paired_run_decision/v2 with per-task input digests, explicit criteria, baseline and variant exposure, attempted-run and per-dispatch time budgets, signed observed_at and elapsed-seconds receipt provenance, a scoped Pareto outcome, and a speed-at-equal-quality verdict that claims speed only when quality held
