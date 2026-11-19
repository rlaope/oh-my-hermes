## Catalog Metadata

Category: `connector`
Phase: `connector-readiness`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.
- Trial two or more memory providers on one corpus and one query set, never on each provider's own sample — load `references/memory-provider-trial.md` for the corpus, query, and reversibility rules.

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

Safety rules:

- An external connector readiness card is not connector installation, credential validation, provider access, API invocation, multimodal capture, live-data retrieval, external mutation, cost authorization, or successful trial evidence unless observed connector-trial evidence records it.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.
- A hook registration or lifecycle callback is an observation point only; it never grants write or synchronization authority.
- Documentation and open package code declare a contract; neither establishes a hosted service's storage, retention, cost, or deletion postcondition.
- A memory provider stays optional: an unknown or unavailable provider never becomes a required default.
- On Hermes, the memory provider is one slot: Hermes runs its built-in memory and no more than one external provider, the one `memory.provider` names, so adopting another provider (honcho or mem0, for example) where that key reads `omh` displaces OMH's provider. OMH's per-turn recall and dreaming reminders then stop, and the `omh_memory` tool stays registered but refuses to recall or write records (`session_lens_unavailable`), because the session lens it reads comes from the provider. State that displacement in the posture before adoption, and keep the switch a proposed `memory.provider` diff the user applies.
- A realtime voice verdict comes only from a supplied realtime_voice_trial_receipt/v1. OMH opens no microphone, call, room, socket, or provider session, installs no connector, downloads no voice model, and authorizes no tool from a receipt.
- A synthetic voice fixture never proves the intended room, microphone, network, or telephony path, and a fallback path succeeding is never success for the requested voice stack, provider, or model.
- Generic connector, voice-input, and media-input records are not realtime voice readiness; a turn that lost its onset, split, merged, dispatched twice, truncated, or replayed after audible output blocks the verdict rather than reporting latency.
- A memory-provider trial reports retrieval quality, latency, and cost per candidate only from host-supplied observation; a dimension nobody measured is not_observed, never a default or a zero, and a corpus is never copied into the record.
- A rollback is proven by exercising it during the trial and recording what came back; a documented rollback path is prepared, not reversible.

