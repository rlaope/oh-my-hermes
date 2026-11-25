# Provider Profile Posture

Load this on-demand contract after the compact `provider-profile-posture` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- Choosing or adopting a connector; use `omh-external-connector-readiness`.
- Listing every tool and credential a workflow needs; use `omh-toolbelt-readiness`.
- Connecting a model provider or its login; use `omh-model-setup`.

## Examples

Good example:

- Prompt: Prepare provider profile posture for this connector using metadata-only secret presence.
- Expected behavior: Produce `prepare_provider_profile_posture` with required context, wrapper actions, and not-evidence boundaries.
- Why: The card records which key names are present, missing, or unknown, and never reads a value.

Bad example:

- Prompt: Read the secret, validate the credential, call the provider, or create a payment route.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- provider_profile_posture/v1
- metadata-only secret requirements
- allowed and prohibited actions

Artifact expectations:

- provider_profile_posture/v1 metadata-only preparation record
