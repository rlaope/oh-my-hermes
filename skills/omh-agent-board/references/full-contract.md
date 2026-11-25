# Agent Board

Load this on-demand contract after the compact `agent-board` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.
- A multi-lane implementation of an accepted plan; use `ulw-work`, which prepares its durable lanes through this board.
- The user only wants to see what is running right now, without creating or changing a task; use `omh-running-work-board`.
- The turn is a Kanban worker that the review dispatcher started on a review-lane task to verify a review-requested handoff; that worker loads Hermes' bundled `sdlc-review` skill, not this one.

## Examples

Good example:

- Prompt: agent-board coordinate PM, CTO, QA, and release agents on this launch checklist.
- Expected behavior: Produce `prepare_agent_board_card` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: agent-board mark the other agent complete without an observed heartbeat or result.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- agent-board/v1 card or guidance
- agent_board_request/v1 record from the `omh_agent_board` plugin tool
- next action
- prepared-vs-observed boundary

Artifact expectations:

- agent-board/v1 metadata-only runtime or wrapper card when recorded
- agent_board_state/v1 bounded board snapshot under the OMH home: request digests, receipts, and task references only; never raw bodies, comments, attachments, or host identity
