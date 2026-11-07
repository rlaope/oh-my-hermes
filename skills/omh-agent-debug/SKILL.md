---
name: "omh-agent-debug"
description: "[omh] Agent is stuck, looping, or drifting: capture a stuck, looping, drifting, or repeatedly failing agent run, diagnose the likely failure pattern, and prepare the smallest safe recovery action. Use when the user says: agent-debug, agent debug, agent debugging, agent introspection, agent self-debug, self-debug, self debugging, looping agent."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: agent-debug
    role: operator
    quality_tier: workflow-surface-gated
    related_skills: [omh-app-debugging, omh-doctor]
---

# Agent Debug

This is a Hermes-native `agent-debug` workflow skill.

## Why This Exists

`agent-debug` exists because an agent that loops, drifts, or burns tokens is explained by its session record (tool errors, identical retries, compaction boundaries, silent turn ends), not by the latest symptom or by memory of what happened.

## Do Not Use When

- The misbehaving thing is application code the agent only called, not the agent's own run; use `omh-app-debugging`.
- The request is install or gateway health rather than one agent run; use `omh-doctor`.
- A diagnosis would need the user's session read, a rerun, or an export and they have not agreed; ask first.

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

- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `live-incident-response`, `automation-blueprint`, `github-event-ops`, `github-issue-intake`, `buzz`, `+40 more`) - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when an agent run is stuck, looping on tools, burning tokens without progress, drifting from the objective, losing context, or failing on recoverable environment/tool assumptions.

    Strong routing signals: `agent-debug`, `agent debug`, `agent debugging`, `agent introspection`, `agent self-debug`, `self-debug`, `self debugging`, `looping agent`, `agent loop failure`, `agent run stuck`, `agent failure capture`, `tool retry loop`, `repeated tool calls`, `context drift`, `prompt drift`, `token burn`, `에이전트 디버그`, `에이전트 실패`, `에이전트 반복 실패`, `반복 실패`, `도구 반복`, `컨텍스트 드리프트`, `토큰 낭비`, `агент зациклился`, `агент завис`, `агент повторяет одно и то же`, `агент снова упал`

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
- Reproduce the failure before preparing any recovery action; a fix without a reproduced failure first is a guess. An agent run is stochastic and a rerun costs money, so reproduced means the recorded failing step recurs when the same tool result is replayed, or the failure rate over N reruns (state N) is above the baseline; replay needs the user's go-ahead. When it is declined or too costly, report causes as supported by the record with causation unproven, keep the two competing hypotheses, and propose only the smallest reversible action.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

Required inputs:

- session id or record path, and the turn range if known
- what the user expected the run to do, and what they saw instead
- the one thing to measure (the `--observable` kind: looping, repeated_work, goal_drift, context_loss, tool_stall, unexpected_cost)

Expected outputs:

- agent_debug_report/v1
- agent_failure_capture/v1
- agent_failure_pattern_hypothesis/v1
- contained_recovery_action/v1

Artifact expectations:

- agent_debug_report/v1 from `omh quality-evidence agent-debug --hermes-session <id|latest> --observable <kind> --json` (or `--session-record <jsonl>`, `--turns N:M`): tool errors, identical retries after an error, background processes started without notify_on_complete, compaction boundaries, and silent turn ends (an empty assistant row right after a tool result that ended the turn), each cited by session and message id or record line; treat a kind listed unavailable as unchecked, and when a silent turn end leads, read the host's agent.log `Turn ended: reason=` line for its timestamp before changing anything
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
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
