# Browser Operator

Load this on-demand contract after the compact `browser-operator` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- An ordinary read of a public page with no sign-in, form, or purchase; use the native browser tools directly unless OMH's browser adapter bridge is enabled, which blocks them.
- The question is whether a page looks right at each viewport; use `omh-visual-qa`.
- A web lookup or a cited answer rather than an interaction with a page; use `omh-web-research`.
- A page step that moves money -- a checkout, a payment, a booking deposit, a top-up; use `omh-spend-gate`, which shows the pre-spend card and takes the person's typed yes even when Hermes prompts on its own.
- The user needs native desktop GUI control outside a browser session (native macOS/Windows/Linux windows or background desktop driving); load Hermes' bundled `computer-use` skill instead of this one.

## Examples

Good example:

- Prompt: browser-operator open the staging checkout URL, click login, fill the form, and capture blockers.
- Expected behavior: Produce `prepare_browser_operator_card` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: browser-operator export the customer list from the production admin with the saved login and no confirmation.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- browser_task_card/v1
- browser_interaction_scope/v1
- browser_auth_boundary/v1
- browser_observation_manifest/v1 when observed
- browser_confirmation_gate/v1 when destructive
- browser_adapter_capabilities/v1 when acquired
- browser_session_lease/v1 when acquired
- browser_page_state/v1 when observed
- next action
- prepared-vs-observed boundary

Artifact expectations:

- browser_task_card/v1 metadata only
- browser_interaction_scope/v1: URL, allowed/prohibited actions, stop condition
- browser_auth_boundary/v1: supplied/missing/prohibited credentials
- browser_observation_manifest/v1: observed screenshots/DOM notes/console/network/click traces only
- Leases: docs/BROWSER-ADAPTER.md; owner/adapter/version/task scope, cached capabilities, digest-only state, exact revision handles.
- browser_skill_promotion/v1: `omh web-qa promotion diff`, `approve` its exact digest, then `promote` one receipt; SKILL.md alone commits visibility
