---
name: "omh-agent-evaluation"
description: "[omh] Choosing between coding agents on evidence: compare executor or agent choices on reproducible tasks using quality, cost, time, tool, and evidence metrics. Use when the user says: agent-evaluation, agent evaluation, agent eval, agent benchmark, executor evaluation, executor benchmark, compare agents, compare codex claude."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: agent-evaluation
    role: operator
    quality_tier: agent-eval-gated
    related_skills: [omh-executor-runtime-readiness, omh-workflow-learning, ulw-perf]
---

# Agent Evaluation

This is a Hermes-native `agent-evaluation` workflow skill.

## Why This Exists

`agent-evaluation` gives OMH a way to improve executor choice empirically, not by vibes, while preserving executor-neutral product language across Codex, Claude Code, Hermes, and generic runtimes.

## Do Not Use When

- The user needs current runtime readiness only; use `omh-executor-runtime-readiness`.
- The user already selected an executor and wants implementation; use the coding handoff or delivery workflow.
- The user asks for workflow learning from a single failed route; use `omh-workflow-learning`.
- The ask is to find and fix runtime, memory, cost, or rendering hotspots rather than score executor or model output quality; use `ulw-perf`.

## Examples

Good example:

- Prompt: agent-evaluation Codex와 Claude Code를 같은 버그 수정 태스크로 비교해서 어떤 런타임을 기본으로 둘지 판단해줘.
- Expected behavior: Prepare paired_run_decision/v1 requirements and a scenario-specific recommendation.
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

- Receipts: `omh coding paired-run dispatch --decision <paired_run_decision/v1 file> --dry-run` prints the plan; the built-in receipt-capable adapter runs only `hermes` arms and refuses Codex, Claude Code, and generic arms before any child starts. For those arms the comparison can be designed and the runs supplied as observed artifacts, but the result stays ungrounded until a caller adapter returns the authenticated receipt: give a per-scenario recommendation labelled ungrounded, never a ranking.
- If observed_at lacks receipt-authenticated provenance, retain the task set, rubric, and input digests, mark the comparison not_observed, and hand back paired_run_decision/v1 with the provenance gap rather than a pass or fail.
- If candidate inputs or success criteria differ outside the variable under test, retain the observed runs, mark executor selection tentative, and hand back the mismatched digests or criteria and a matched rerun budget.
- If a judge has no measured agreement against human labels, retain the prewritten rubric and observed executable checks, mark judgment unresolved and unqualified, and hand back the missing agreement measurements instead of a correctness claim.

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes should design or summarize a fair comparison of Codex, Claude Code, Hermes coding, or generic executors for a bounded task set.

    Strong routing signals: `agent-evaluation`, `agent evaluation`, `agent eval`, `agent benchmark`, `executor evaluation`, `executor benchmark`, `compare agents`, `compare codex claude`, `agent tournament`, `which agent is better`, `에이전트 평가`, `에이전트 비교`, `실행자 평가`, `코덱스 클로드 비교`, `сравни кодинг агентов`, `какой кодинг агент лучше`, `сравнение кодинг агентов`

## Catalog Metadata

Category: `operations`
Phase: `agent-evaluation`
Hermes role: `operator`
Quality tier: `agent-eval-gated`
Reasoning demand: `light`

Quality bar:

- Define tasks, rubric, isolation, budgets, and stop rules before comparing agents.
- Use the same inputs and success criteria across candidates unless the difference is the variable under test.
- Require receipt-authenticated observed_at provenance before public parse or validation can return pass or fail.
- Report quality, correctness, time, cost, tool coverage, verification, and review gaps separately.
- Score the trajectory as its own dimension beside the outcome and never fold the two into one total: it asks whether the run searched before it asserted, took approval before an irreversible side effect, used an available tool instead of guessing, and verified before claiming done. A run that reached the right answer with one of those skipped or out of order scores lower on trajectory than one that did not, and the report carries both dimensions.
- When the question is an agent judging and improving its own output rather than comparing executors, load `omh-agent-evaluation/references/self-evaluation-loops.md` and pick the loop shape from it - reflection, evaluator-optimizer, or test-driven refinement - remembering that an executable check outranks a judge whenever one exists.
- Declare all three stop rules before the loop runs - a maximum iteration count, a score threshold chosen in advance, and a no-improvement break - and report the iteration count, the final score, and which of the three ended the run. A loop whose only stop is that the output looks good now is a defect.
- Write criteria before generation and score a rubric dimension by dimension beside its total: criteria derived from an output describe it instead of testing it, and a single number hides which dimension failed.
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

- paired_run_decision/v1
- not-evidence boundary

Artifact expectations:

- paired_run_decision/v1 with per-task input digests, explicit criteria, baseline and variant exposure, attempted-run and per-dispatch time budgets, signed observed_at receipt provenance, and a scoped Pareto outcome

Safety rules:

- Do not claim an executor is better from anecdotes, brand names, or unobserved runs.
- Do not send secrets, credentials, private data, or production tasks into evaluation without explicit authority.
- Keep benchmark design, observed run evidence, scoring, and executor selection separate.
- A judge score is never correctness: it licenses no claim that the output is right, tested, reviewed, or shippable, and a model scoring its own output is the weakest evidence class - labelled as such, never reported as verification.
- A judge with no agreement measured against human labels is unqualified: report it as unqualified, never as a result, and take the qualification procedure and its agreement thresholds from `omh-agent-evaluation/references/self-evaluation-loops.md`.
- A signed local Hermes-child receipt proves that OMH recorded a process-sealed confirmed local dispatch event; it does not prove executor internals or protect evidence from the owning OS user.

## Runtime Evidence

Preferred harness for this skill: `agent-evaluation`.

```sh
omh runtime record --skill agent-evaluation --harness agent-evaluation --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. Finished work ends with no question and no offer; when a decision only the user can make remains, end with one specific question about that decision, not a list of questions, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
