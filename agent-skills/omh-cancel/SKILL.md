---
name: "omh-cancel"
description: "[omh] Aborting an active workflow: ending active workflow state cleanly. Use when the user says: cancel, stop the workflow, abort the run, cancel the loop."
license: MIT
compatibility: "Requires the omh CLI on PATH (pip install oh-my-hermes)."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operator]
    category: operator
    phase: state-cleanup
    role: tracker
    quality_tier: evidence-gated
---

# Cancel

This is an OMH `cancel` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`cancel` exists so a request to stop ends the right thing: OMH clears the state this session owns, and work the host owns stops through the person's own host command, so nothing reads as stopped before a record or the host's own reply says it is.

## Do Not Use When

- The workflow finished and its outcome should be kept; record it with omh state finish instead of clearing it.
- The user wants to see what is still running rather than stop it; use `omh-running-work-board`.
- The user means cancelling something in their own product or accounts, such as an order, a subscription, or a meeting, rather than OMH or host work.

## Examples

Good example:

- Prompt: cancel the loop and stop everything that is running
- Expected behavior: Clear this session's OMH state with its own commands, name the host's stop commands (on Hermes, `/loop stop` and `/stop`) for the person to run, and report each OMH clear from its result and each host stop as requested.
- Why: The request spans OMH state and host-owned work, which stop through different owners.

Bad example:

- Prompt: cancel: kill the background processes yourself and say everything stopped
- Expected behavior: Leave the processes to the person's own stop command (on Hermes, `/stop`), and report them stopped only after the host's own reply.
- Why: OMH never ends a host process, and a requested stop is not an observed one.

## Completion Checklist

- Every stopped item is named with its owner: OMH state or host work.
- Each OMH clear cites its command result; each host stop stays requested until the host's reply is seen.
- Nothing outside this session's own state was cleared, and no host process was ended by OMH.

## Recovery Notes

- If a session-bound clear is refused for a missing --session-ref, report the refusal rather than clearing without it.
- If the host's reply to a stop never appears, keep the stop requested and ask the person what it said.



## When to Use

Use to cleanly end active adapted workflow state.

    Strong routing signals: `cancel`, `$cancel`, `stop the workflow`, `abort the run`, `cancel the loop`

## Catalog Metadata

Category: `operator`
Phase: `state-cleanup`
Quality tier: `evidence-gated`
Reasoning demand: `light`

Quality bar:

- Name each thing to stop and its owner: OMH state (workflow lifecycle, plan checklist, OMH goal) or host work (the running turn, background processes, delegations, a Hermes /loop or /goal).
- Clear OMH state with its own commands: `omh state clear --workflow <name>` (`--session-ref` when session-bound), on Hermes `omh_todo action=clear`, and `omh goal cancel --goal <id>`; an OMH loop stops through its linked goal, and one without a goal has no cancel record.
- Hand host work to the person's own stop command; on Hermes `/stop` (in a CLI or TUI session it ends every background process, and the classic CLI its background delegations too; on a messaging platform it interrupts the running turn rather than ending every background process), `/loop stop`, `/goal pause` or `/goal clear`, `/heartbeat clear`, `/pause` (all new work on a gateway).
- Report an OMH clear as done only from its command result, and a host stop as requested until the host's own reply to it is seen.

Required inputs:

- active workflow state
- cancellation intent

Expected outputs:

- cleared state
- safe stop summary

Artifact expectations:

- state clear record when state exists

Safety rules:

- Never end, kill, or signal a host process, background job, or delegation from this workflow, through the terminal or any other tool (on Hermes, `process_manage` included); that stop is the person's own host command.
- Clear only what this session owns; another session's plan, workflow state, or goal stays as it is.

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
