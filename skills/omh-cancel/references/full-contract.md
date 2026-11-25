# Cancel

Load this on-demand contract after the compact `cancel` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

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

## Full Input, Output, and Artifact Expectations

Required inputs:

- active workflow state
- cancellation intent

Expected outputs:

- cleared state
- safe stop summary

Artifact expectations:

- state clear record when state exists
