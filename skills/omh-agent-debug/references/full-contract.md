# Agent Debug

Load this on-demand contract after the compact `agent-debug` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

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

## Full Input, Output, and Artifact Expectations

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
