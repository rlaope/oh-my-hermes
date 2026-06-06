# Harness Quality Contract

`harness_quality/v1` is the small machine-readable contract that tells a chat
wrapper what quality gate a workflow lane is using.

It exists so Discord, Slack, or hosted Hermes wrappers can render better UX
without teaching end users command names or parsing generated skill prose.

## What Users Get

For a chat user, this changes the experience from vague status copy to explicit
state:

- "I need one answer before planning" for clarification lanes.
- "A draft plan is ready to accept or revise" for planning lanes.
- "A coding handoff is prepared, but execution is not observed yet" for coding
  lanes.
- "Review or CI is still missing" before merge-ready status is shown.

The wrapper can choose buttons from `wrapper_actions`, show progress from
`evidence_ladder`, and avoid false claims with `overclaim_guards`.
Local operators can inspect the same contract with `omh harness list`,
`omh harness inspect <name>`, and `omh harness validate`.

## Contract Shape

Every generated workflow catalog entry and relevant runtime payload can expose a
contract shaped like this:

```json
{
  "schema_version": "harness_quality/v1",
  "harness": "coding-handling",
  "quality_tier": "handoff-gated",
  "quality_bar": [
    "Clarify scope before edits when target behavior, files, or verification are missing."
  ],
  "evidence_ladder": [
    "coding_delegation_prepared",
    "executor_dispatch_observed",
    "executor_result_observed",
    "verification_recorded"
  ],
  "wrapper_actions": ["accept_plan", "send_to_codex", "show_status"],
  "overclaim_guards": [
    "A prepared coding_delegation.json is not implementation evidence."
  ]
}
```

## Where It Appears

- `omh docs workflows --json` exposes the full local workflow and harness
  catalog, including `workflow_catalog/v1.harnesses[].harness_quality`.
- `omh coding delegate` includes `harness_quality` beside the prepared
  delegation. Dispatch actions are removed unless the payload also includes a
  prepared executor handoff.
- `omh coding delegate --executor codex` includes the dispatch-capable contract
  in both the public payload and `executor_handoff` when the request is specific
  enough to delegate.
- `omh hermes plan` includes `wrapper_contract.harness_quality` so wrappers can
  render accept/revise/cancel and handoff readiness from the plan contract.
- Runtime records preserve the contract in `coding_delegation.json` when present.
- `omh runtime delegation-status --run <run-id>` includes
  `harness_progress/v1`, which marks ladder steps complete only when the
  corresponding runtime or wrapper evidence is observed.

## Wrapper Rules

- Use `wrapper_actions` as platform-neutral action ids; map them to buttons,
  menu items, or thread actions in the adapter.
- Use `evidence_ladder` to show progress, but mark a step complete only when a
  runtime record or wrapper observation proves it.
- Use `quality_bar` as the lane's success checklist.
- Use `overclaim_guards` before changing status text. If a guard conflicts with
  a later artifact, show the blocker instead of the optimistic state.
- Treat `harness_progress/v1.next_step` as a wrapper hint, not as proof that the
  next action has already happened.

## Golden Examples

See `examples/wrapper-golden/harness-quality.json` for deterministic examples
covering coding handoff, planning, research, and clarification lanes.
