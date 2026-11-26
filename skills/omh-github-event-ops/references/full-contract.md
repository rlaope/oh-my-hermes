# Github Event Ops

Load this on-demand contract after the compact `github-event-ops` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- One issue to file from a bug report or an idea, with no incoming event to route; use `omh-github-issue-intake`.
- A failing build log to diagnose, with no event routing left to decide; use `omh-build-failure-triage`.
- The event is a security advisory, a CVE in a dependency, or a leaked credential; use `omh-security-event-response`, which orders containment and closes only on an observed rotation or fix.
- The PR is a dependabot or renovate version bump with no advisory. A major or breaking bump goes to `omh-refactor-plan`, which decides whether it is safe to merge from the breaking changes against this repository's call sites; a patch or minor bump with its required checks green takes the review path, with `omh-verification-gate` deciding.
- The user wants a GitHub operation carried out with the gh CLI - open or label an issue, open or merge a PR, leave review comments, manage a repository - rather than an incoming event routed to a handoff card; load Hermes' bundled `github` skill instead of this one.

## Examples

Good example:

- Prompt: github-event-ops PR opened with failing CI; triage whether this needs review or fix handoff.
- Expected behavior: Produce `prepare_github_event_ops_card` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: github-event-ops prove the issue was labelled and CI was rerun.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the event type and action, repository, and PR or issue number
- for a pull-request or check event, the head sha the payload names
- the route or channel it arrived on, and what the user wants decided (review, triage, or fix hand-off)

Expected outputs:

- github-event-ops/v1 card or guidance
- next action
- prepared-vs-observed boundary

Artifact expectations:

- github-event-ops/v1 metadata-only runtime or wrapper card when recorded
- On Hermes, the intake records the webhook route the user subscribed (`hermes webhook subscribe <route> --events <types> --skills omh-github-event-ops`) and the event type it delivered
- On Hermes, a PR watch records its cron job id, the repository and PR number, and the deadline; a guarded route records its filter script (`--script pr_event_guard_<route>.py`)
