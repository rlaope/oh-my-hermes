---
name: "omh-agent-debug"
description: "[omh] Agent is stuck, looping, or drifting: capture a stuck, looping, drifting, or repeatedly failing agent run, diagnose the likely failure pattern, and prepare the smallest safe recovery action. Use when the user says: agent-debug, agent debug, agent debugging, agent introspection, agent self-debug, self-debug, self debugging, looping agent."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: agent-debug
    role: operator
    quality_tier: workflow-surface-gated
---

# Agent Debug

This is a Hermes-native `agent-debug` workflow skill.

## Why This Exists

`agent-debug` exists so Hermes users can ask for this workflow in chat and get a structured, checkable answer instead of an improvised one.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.

## Examples

Good example:

- Prompt: agent-debug capture why this agent is looping on the same tool and prepare the smallest safe recovery action.
- Expected behavior: Produce `prepare_agent_debug` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: agent-debug silently reset the executor, patch the environment, and claim the future loop is fixed.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- Failure state, intended goal, recent tool sequence, and context pressure are captured.
- Diagnosis distinguishes repeated command/tool loops, context drift, environment mismatch, service errors, and wrong-hypothesis tests.
- Recovery action is contained, reversible, and does not claim implementation, verification, CI, merge, or future-loop fixes.

## Recovery Notes

- If the request is install/setup health, route to doctor.
- If the request is a manager status or throughput review, route to agent-ops-review.
- If the request is a durable self-improvement record after diagnosis, route to workflow-learning.

## Workflow Lane

- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `live-incident-response`, `automation-blueprint`, `github-event-ops`, `github-issue-intake`, `buzz`, `+39 more`) - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when an agent run is stuck, looping on tools, burning tokens without progress, drifting from the objective, losing context, or failing on recoverable environment/tool assumptions.

    Strong routing signals: `agent-debug`, `agent debug`, `agent debugging`, `agent introspection`, `agent self-debug`, `self-debug`, `self debugging`, `looping agent`, `agent loop failure`, `agent run stuck`, `agent failure capture`, `tool retry loop`, `repeated tool calls`, `context drift`, `prompt drift`, `token burn`, `에이전트 디버그`, `에이전트 실패`, `에이전트 반복 실패`, `반복 실패`, `도구 반복`, `컨텍스트 드리프트`, `토큰 낭비`

## Catalog Metadata

Category: `operations`
Phase: `agent-debug`
Hermes role: `operator`
Quality tier: `workflow-surface-gated`
Reasoning demand: `light`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.
- Hold at least two competing failure hypotheses at once, each with observed evidence for and against; a diagnosis that never named a rival hypothesis is a guess.
- Before reading a Hermes session store, a session record, or a delegated child's transcript, load `references/session-forensics.md`: intake first, read-only and length-bounded reads, who actually wrote each row, and only numbers computed from the session.
- Order probes cheapest-discriminating-first: run the cheapest check that splits the surviving hypotheses before any expensive capture, rerun, or restart.
- When a run that used to work now fails, bisect from last-known-good to first-bad change (prompt, config, tool, model, or environment) instead of debugging the newest symptom.
- Name a cause only after revert-verify: remove the suspect change and observe the failure disappear, or state that causation is unproven.
- Reproduce the failure before preparing any recovery action; a fix without a reproduced failure first is a guess.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- agent_debug_report/v1
- agent_failure_capture/v1
- agent_failure_pattern_hypothesis/v1
- contained_recovery_action/v1

Artifact expectations:

- agent_debug_report/v1 from `omh quality-evidence agent-debug --hermes-session <id|latest> --observable <kind> --json` (or `--session-record <jsonl>`, `--turns N:M`): tool errors, identical retries after an error, background processes started without notify_on_complete, and compaction boundaries, each cited by session and message id or record line; treat a kind listed unavailable as unchecked
- agent_failure_capture/v1 and agent_failure_pattern_hypothesis/v1 in that payload: observed finding ids, unavailable evidence, and at least two competing hypotheses with evidence for and against
- contained_recovery_action/v1 proposing the smallest reversible step, never executed; sharing is the separate `agent-debug-export`, written only with --confirm-export

Safety rules:

- An agent debug report is not executor reset, hidden state mutation, tool repair, implementation, verification, CI, merge-readiness, merge, or proof that future loops are fixed. Record only observed failure evidence, diagnosis hypotheses, contained recovery actions, and remaining blockers.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Runtime Evidence

Preferred harness for this skill: `agent-debug`.

```sh
omh runtime record --skill agent-debug --harness agent-debug --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a stop condition or a decision the user owns ends the turn, offer the next action as a question rather than declaring what will not be done.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
