---
name: "omh-agent-debug"
description: "[omh] Agent is stuck, looping, or drifting: capture a stuck, looping, drifting, or repeatedly failing agent run, diagnose the likely failure pattern, and prepare the smallest safe recovery action. Use when the user says: agent-debug, agent debug, agent debugging, agent introspection, agent self-debug, self-debug, self debugging, looping agent."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: agent-debug
    role: operator
    quality_tier: workflow-surface-gated
---

# Agent Debug

This is an OMH `agent-debug` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

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

- If the request is install/setup health, it is outside this skill.
- If the request is a manager status or throughput review, route to agent-ops-review.
- If the request is a durable self-improvement record after diagnosis, it is outside this skill.



## When to Use

Use when an agent run is stuck, looping on tools, burning tokens without progress, drifting from the objective, losing context, or failing on recoverable environment/tool assumptions.

    Strong routing signals: `agent-debug`, `agent debug`, `agent debugging`, `agent introspection`, `agent self-debug`, `self-debug`, `self debugging`, `looping agent`, `agent loop failure`, `agent run stuck`, `agent failure capture`, `tool retry loop`, `repeated tool calls`, `context drift`, `prompt drift`, `token burn`, `에이전트 디버그`, `에이전트 실패`, `에이전트 반복 실패`, `반복 실패`, `도구 반복`, `컨텍스트 드리프트`, `토큰 낭비`, `агент зациклился`, `агент завис`, `агент повторяет одно и то же`, `агент снова упал`

## Catalog Metadata

Category: `operations`
Phase: `agent-debug`
Quality tier: `workflow-surface-gated`
Reasoning demand: `light`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.
- Hold at least two competing failure hypotheses at once, each with observed evidence for and against; a diagnosis that never named a rival hypothesis is a guess.
- Order probes cheapest-discriminating-first: run the cheapest check that splits the surviving hypotheses before any expensive capture, rerun, or restart.
- When a run that used to work now fails, bisect from last-known-good to first-bad change (prompt, config, tool, model, or environment) instead of debugging the newest symptom.
- Name a cause only after revert-verify: remove the suspect change and observe the failure disappear, or state that causation is unproven.
- Reproduce the failure before preparing any recovery action; a fix without a reproduced failure first is a guess.

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

- agent_debug_report/v1 from `omh quality-evidence agent-debug --hermes-session <id|latest> --observable <kind> --json` (or `--session-record <jsonl>`, `--turns N:M`): tool errors, identical retries after an error, background processes started without notify_on_complete, compaction boundaries, and silent turn ends (an empty assistant row right after a tool result that ended the turn), each cited by session and message id or record line; treat a kind listed unavailable as unchecked, and when a silent turn end leads, read the host's agent.log `Turn ended: reason=` line for its timestamp before changing anything
- agent_failure_capture/v1 and agent_failure_pattern_hypothesis/v1 in that payload: observed finding ids, unavailable evidence, and at least two competing hypotheses with evidence for and against
- contained_recovery_action/v1 proposing the smallest reversible step, never executed; sharing is the separate `agent-debug-export`, written only with --confirm-export

Safety rules:

- An agent debug report is not executor reset, hidden state mutation, tool repair, implementation, verification, CI, merge-readiness, merge, or proof that future loops are fixed. Record only observed failure evidence, diagnosis hypotheses, contained recovery actions, and remaining blockers.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

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
