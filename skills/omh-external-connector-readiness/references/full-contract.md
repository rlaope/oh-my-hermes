# External Connector Readiness

Load this on-demand contract after the compact `external-connector-readiness` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- Choosing which coding owner runs a task; use `omh-executor-runtime-readiness`.
- Finding which tool, credential, or install is missing for work already chosen; use `omh-toolbelt-readiness`.
- A read-only live lookup or an external write through a connector already adopted; use `omh-live-info` or `omh-apps`.

## Examples

Good example:

- Prompt: external-connector-readiness compare weather plugin and wxtrain candidates with cost, freshness, multimodal evidence, and fallback routes before adoption.
- Expected behavior: Produce `prepare_external_connector_readiness` with required context, wrapper actions, and not-evidence boundaries.
- Why: Two named weather connectors need a cost, freshness, and fallback comparison before either is enabled; no provider has been called.

Bad example:

- Prompt: external-connector-readiness silently enable a paid connector and claim weather, SQL, and screenshot results without observed provider evidence.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- external_connector_readiness_card/v1
- connector_capability_matrix/v1
- auth_cost_boundary/v1
- live_data_freshness_policy/v1 when live data is required
- multimodal_routing_policy/v1 when screenshots, audio, video, or files are involved
- fallback_route_policy/v1
- connector_trial_manifest/v1 when observed
- memory_provider_posture/v1 when the candidate is an optional memory provider
- memory_provider_trial_comparison/v1 when two or more memory providers are trialled on one corpus
- realtime_voice_trial_receipt/v1 when a supplied realtime voice trial is observed
- realtime_voice_readiness/v1 verdict per voice dimension when a receipt is supplied
- next action
- prepared-vs-observed boundary

Artifact expectations:

- external_connector_readiness_card/v1 metadata-only wrapper card when prepared
- connector_capability_matrix/v1 with candidate, domain, read/write shape, modality, owner workflow, and fallback route
- auth_cost_boundary/v1 separating missing connector, missing credentials, paid/provider cost risk, quota, and user authority
- live_data_freshness_policy/v1 for requested recency, provider timestamp, stale-result handling, and source-quality thresholds
- multimodal_routing_policy/v1 for screenshot, audio, video, file, OCR, or visual QA evidence routes when needed
- connector_trial_manifest/v1 only when a provider response, capture id, query transcript, message id, or tool-call observation is recorded
- memory_provider_posture/v1 for an optional memory provider, covering identity scope, automatic hooks, storage boundary, synchronization, failure, retention, deletion, export/import, backup/restore, and portability, each marked ready, missing, risky, not_observed, or unknown
- memory_provider_trial_comparison/v1 built on the connector_trial_manifest/v1 pattern: one corpus and one query set per candidate, retrieval quality, latency, and cost each reported per provider or marked not_observed, plus the migration route and the rollback that was exercised rather than asserted
- realtime_voice_trial_receipt/v1 only when an authorized host, connector, or operator supplies the observed trial: connector build identity, requested versus observed stack, per-turn milestones on one declared timing reference, turn-integrity states, fallback path, interruption behavior, and spoken tool decisions
- realtime_voice_readiness/v1 with a pass, hold, or block state and reasons for turn integrity, latency, fallback, interruption, and tool safety, plus the separated connector-configured, synthetic-trial, actual-environment-trial, voice-turn, tool-action, and session-completed states
