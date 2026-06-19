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
- "Feedback is clustered, but no roadmap or coding handoff exists yet" for
  customer triage lanes.
- "A meeting agenda is prepared, but the meeting outcome is not observed yet"
  for meeting lanes.
- "An ops review names risks and blockers, but it is not CI or release
  evidence" for operating review lanes.
- "Operating rhythm history is recorded, but unprovided meeting outcomes remain
  unobserved" for cadence lanes.
- "A report package outline is ready, but approval and binary PPTX export are
  not observed yet" for report lanes.
- "A material package plan is ready, but binary export, render QA, formula
  recalculation, approval, delivery, and upload are not observed yet" for
  material lanes.
- "A reliability review is drafted, but SLO, incident, and error-budget claims
  require metric or source evidence" for reliability lanes.
- "A coding handoff is prepared, but execution is not observed yet" for coding
  lanes.
- "Review or CI is still missing" before merge-ready status is shown.
- "This workflow attempt is now a learning trace" when Hermes records the route,
  next action, missing evidence, eval result, and future regression case without
  storing the raw prompt or silently patching a skill.

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
    "Clarify scope before edits when target behavior, files, or verification are missing.",
    "Attach acceptance criteria, verification expectations, and review expectations to the prepared handoff.",
    "Report coding progress from lifecycle evidence, not from the existence of a prepared prompt."
  ],
  "evidence_ladder": [
    "coding_delegation_prepared",
    "executor_dispatch_observed",
    "executor_result_observed",
    "verification_recorded",
    "review_ci_merge_recorded_when_required"
  ],
  "wrapper_actions": ["accept_plan", "show_prompt_handoff", "copy_prompt_handoff", "choose_executor", "send_to_executor", "send_to_codex", "show_status", "record_result"],
  "overclaim_guards": [
    "A prepared coding_delegation.json is not implementation evidence.",
    "Executor completion is not review, CI, merge-readiness, or merge evidence."
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
  enough to delegate. The primary action is `send_to_executor`; `send_to_codex`
  remains a compatibility alias only for Codex-selected flows.
- `omh coding delegate --executor claude-code`, `--executor omx-runtime`, or
  `--executor generic` returns a prompt-only handoff. It can expose
  `show_prompt_handoff`, `copy_prompt_handoff`, and `choose_executor`, but it
  must not create a lifecycle run or observed execution evidence.
- `omh hermes plan` includes `wrapper_contract.harness_quality` so wrappers can
  render accept/revise/cancel and handoff readiness from the plan contract.
- Runtime records preserve the contract in `coding_delegation.json` when present.
- `omh runtime delegation-status --run <run-id>` includes
  `harness_progress/v1`, which marks ladder steps complete only when the
  corresponding runtime or wrapper evidence is observed.
- `omh learning record`, `omh learning eval`, and `omh learning regression
  replay` expose the `workflow-learning` harness for process-supervision data:
  why a workflow was chosen, what was prepared, what was observed, which
  deterministic checks passed, and what improvement candidate still needs human
  approval.
- `omh learning index check` and `omh learning index rebuild` keep the local
  workflow-learning index repairable if metadata records exist but the pointer
  index drifts. Rebuilding the index is not workflow execution, skill mutation,
  or proof that a future workflow improved.
- `omh learning audit` reads the local learning corpus and returns
  `workflow_learning_audit/v1`: trace/eval/regression/export counts, coverage,
  stale-index blockers, regression replay status, and the next repair or review
  action. The same payload includes `learning_audit_card/v1` so Hermes wrappers
  can render a compact review card with record, eval, regression, audit, export,
  replay, index-check, and index-rebuild actions. The audit is readiness
  evidence for the learning corpus only; it does not patch skills, execute
  workflows, or prove future behavior improved.
- `omh learning candidate <trace-id>` returns an
  `improvement_candidate/v1` plus `improvement_candidate_review_card/v1`. The
  review card is the Hermes-facing surface for approve/revise/reject decisions,
  regression-case follow-up, and status narration. It is not a source patch,
  automatic skill mutation, or proof that future behavior changed.
- `omh learning export` creates a redacted `workflow_learning_export/v1` review
  bundle from selected traces plus related evals, candidates, and regression
  cases. The bundle omits raw prompts and fixture text; it is review material,
  not model training, automatic skill patching, execution, review, CI, merge, or
  proof that future routing improved. Export bundles are derived artifacts and
  are not part of the canonical learning index repair loop.

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

The business workflow pack adds non-coding harnesses such as
`business-research`, `strategy-synthesis`, `meeting-facilitation`,
`customer-insight-triage`, `ops-review`, `operating-rhythm`, `report-package`,
`materials-package`, and `reliability-review`. These give wrappers the same
evidence discipline for company work: research briefs are not fetched data,
strategy briefs are not accepted decisions, meeting briefs are not meeting
minutes, feedback triage is not a roadmap, ops review is not release or CI
evidence, report packages are not binary decks or approvals, material packages
are not binary exports, render/formula QA, uploads, approvals, or delivery, and
reliability reviews are not proof that SLOs passed without metric or source
evidence.
