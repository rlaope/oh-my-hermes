# Command Operator

Load this on-demand contract after the compact `command-operator` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- An ordinary read-only or test command with a known working directory and nothing to gate; run it with the native terminal tool.
- The user pasted a failed command's output and asks for the cause; use `omh-build-failure-triage`, or `omh-agent-debug` when the agent itself is stuck.
- The user wants a command blocked for the agent from now on; use `omh-security-safety-review`, which prepares a proposed deny-glob list for the user to apply.

## Examples

Good example:

- Prompt: command-operator run the staging deploy script from the repo root and confirm with me before it touches anything.
- Expected behavior: Produce `prepare_command_operator_card` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: command-operator run rm -rf without cwd, confirmation, or observation gates.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

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
