---
name: "omh-terminal"
description: "[omh] Shell command or test-suite execution: policy overlay for terminal commands - add cwd, environment, safety, and result-evidence gates after preferring native shell tools for ordinary CLI, package-manager, and test runs. Use when the user says: command-operator, command operator, terminal command, terminal task, shell command, shell task, cli command, command execution."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, command]
    category: command
    phase: command-task
    role: guide
    quality_tier: workflow-surface-gated
---

# Command Operator

This is an OMH `command-operator` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`command-operator` exists because a host's own approval gate flags only some commands and can approve one with nobody asked: it fixes the working directory, environment, timeout, and stop condition, confirms every irreversible or externally visible command in chat whether or not the host flags it, records the host's own approval answer beside that confirmation, and reports results only from what the run returned.

## Do Not Use When

- An ordinary read-only or test command with a known working directory and nothing to gate; run it with the native terminal tool.
- The user pasted a failed command's output and asks for the cause; use `omh-build-failure-triage`, or `omh-agent-debug` when the agent itself is stuck.
- The user wants a command blocked for the agent from now on; use `omh-security-safety-review`, which prepares a proposed deny-glob list for the user to apply.

## Examples

Good example:

- Prompt: command-operator run npm test in the project terminal and summarize the output.
- Expected behavior: Produce `prepare_command_operator_card` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: command-operator run rm -rf without cwd, confirmation, or observation gates.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- Command text, working directory, environment assumptions, timeout, safety level, and stop condition are explicit.
- Destructive, credential, network, filesystem mutation, install, deploy, and production commands are confirmed in chat before the run, or marked missing and not run; a native approval note is recorded beside that confirmation, never in place of it.
- With nobody to answer the confirmation (a scheduled job, a one-shot run, a webhook run), an irreversible or externally visible action is not run: it is handed to a person's turn and its confirmation is recorded as missing.
- Exit codes, stdout/stderr, test results, package-manager effects, and filesystem mutations are reported only from observed command evidence.

## Recovery Notes

- If command text or working directory is missing, ask for the smallest missing scope needed before preparing the command task.
- If the command is irreversible or externally visible, require an explicit confirmation gate in chat before the run, whether or not the host flags it: deleting or overwriting user data, discarding history or force-pushing, deleting a remote branch, dropping, deleting from, truncating, or flushing a database, a credentialed or networked mutation, device actuation, an install, a deploy, a production change, or an external send.
- On Hermes, record the terminal result's `approval` note beside that confirmation as additional evidence, never in place of it: a note that the command "was approved by the user" is the person's answer to Hermes' own prompt for that command, while "auto-approved by smart approval" or no note at all is not a person's consent, and a `pending_approval` status means the command has not run and will not run on its own (Hermes stores it without running it, and `/approve` resumes only a run that is still waiting on an approval), so it is never re-run or reworded and goes to a person's turn.
- On Hermes, a cron job, a one-shot `-q` run, or a webhook run denies a flagged command by default (`approvals.cron_mode`, `approvals.single_query_mode`, `approvals.unattended_mode`): record the block as the gate's outcome and hand the command to a person's turn, never rephrase it to get past the gate. Nobody can answer the chat confirmation in those runs either, so an irreversible or externally visible command that Hermes does not flag is not run: it is handed to a person's turn and its confirmation is recorded as missing.
- If the user supplied failed command output and asks for root cause, route to build-failure-triage or agent-debug instead of preparing a fresh command.



## When to Use

Use when Hermes should prepare or supervise terminal/CLI command execution without claiming the command ran or succeeded.

    Strong routing signals: `command-operator`, `command operator`, `terminal command`, `terminal task`, `shell command`, `shell task`, `cli command`, `command execution`, `run command`, `run this command`, `execute command`, `execute this command`, `run npm test`, `run tests`, `npm test`, `pnpm test`, `bun test`, `uv run`, `python -m unittest`, `pytest`, `make test`, `cargo test`, `go test`, `summarize command output`, `터미널 명령`, `터미널에서`, `셸 명령`, `쉘 명령`, `명령 실행`, `명령어 실행`, `실행 준비`, `npm test 실행`, `테스트 실행`, `결과 요약`

## Catalog Metadata

Category: `command`
Phase: `command-task`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.
- Choose the wait strategy before starting long-running work and bind it to a completion signal the host exposes, never to a status loop: a command that fits one tool call runs once in the foreground with a duration-sized timeout; a longer terminal command runs in the background with completion notification armed and no process-status polling; a delegated lane relies on its delivered result while the parent continues independent work or ends the turn; a CI, PR, deploy, file, port, log-line, or external-session condition uses the host's monitor when observed, else exactly ONE bounded watcher or adaptive backoff outside model turns. Record the handle and observation mode at dispatch; every armed wait needs a hard deadline, a cancellation path, and a fallback naming the missing capability. Each wait closes in one terminal state with bounded evidence; an unbounded idle or busy-wait is a defect and a lost notification times out. One decision-changing midpoint peek and any user-requested status check stay allowed; neither is the wait mechanism. Ladder and terminal states: shared rail.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- command_task_card/v1
- command_scope/v1
- command_safety_gate/v1
- command_result_manifest/v1 when observed
- next action
- prepared-vs-observed boundary

Artifact expectations:

- command_task_card/v1 metadata-only wrapper card when prepared
- command_scope/v1 with command text, working directory, environment assumptions, timeout, and stop condition
- command_safety_gate/v1 separating read-only, write/mutation, network, credential, and destructive-risk commands, holding the chat confirmation for each irreversible or externally visible command and, on Hermes, the terminal result's `approval` note or its `blocked` or `pending_approval` status as additional observed evidence
- command_result_manifest/v1 only when exit code, stdout/stderr, logs, or terminal transcript are observed

Safety rules:

- A command operator card is not terminal launch, shell execution, package-manager action, test run, stdout/stderr capture, exit-code success, filesystem mutation, network access, or destructive command evidence unless observed command-result evidence records it.
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
