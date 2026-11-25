# Model Setup

Load this on-demand contract after the compact `model-setup` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user is asking which model Hermes currently is, not asking to inspect, change, connect, or route one.
- The request needs a repository code change rather than local model setup or recommendation review.
- The user wants anti-ban, cooldown-bypass, hidden retry, benchmark-superiority, or provider-entitlement claims.

## Examples

Good example:

- Prompt: Set up models from what I already have; only Qwen and Gemini are active, and show me the Hermes versus external-owner changes before applying anything.
- Expected behavior: Inspect safe metadata, ask the user to confirm active candidates, keep unavailable preferred heads visible, resolve compatible fallbacks, and separately preview Hermes-native config and Maestro external-handoff guidance.
- Why: The request needs flexible missing-model resolution while preserving owner and approval boundaries.

Bad example:

- Prompt: Use an old session entry to prove my Grok account is active and silently replace the main alias.
- Expected behavior: Treat the entry as observed_before only, require active confirmation, show any alias collision, and refuse an unapproved write.
- Why: Historical metadata is not provider readiness and cannot authorize a configuration change.

## Full Input, Output, and Artifact Expectations

Required inputs:

- metadata-only discovery report and its source/candidate states
- user confirmation of which discovered models and providers are currently active
- target Hermes model alias (`main` or a user-named alias), semantic category, X-platform domain, or external coding owner
- optional user-edited recommendation overrides

Expected outputs:

- source-labeled candidate inventory separating historical observation from confirmed-active models
- editable editorial recommendation chains resolved only against confirmed-active compatible candidates
- Hermes-native alias/provider preview or a separate Maestro ordered external-handoff recommendation
- verification checklist or an incomplete non-blocking setup advisory with exact next actions

Artifact expectations:

- model_discovery/v1 metadata-only report when local discovery runs
- model_recommendation_resolution/v3 recommendation result when a chain is resolved
- omh_model_activation/v1 setup receipt when the setup surface captures it
