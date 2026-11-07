---
name: "omh-external-connector-readiness"
description: "[omh] Evaluating a plugin, connector, or API for adoption: external connector readiness - assess whether a named plugin, connector, API, data provider, or multimodal route is safe, affordable, fresh, and observable; use executor-runtime-readiness for coding-owner choice and toolbelt-readiness for missing capability inventory. Use when the user says: external-connector-readiness, external connector readiness, connector readiness matrix, plugin readiness matrix, provider readiness, api readiness, connector adoption, external plugin adoption."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, connector]
    category: connector
    phase: connector-readiness
    role: guide
    quality_tier: workflow-surface-gated
    related_skills: [omh-executor-runtime-readiness, omh-toolbelt-readiness, omh-live-info, omh-apps]
---

# External Connector Readiness

This is a Hermes-native `external-connector-readiness` workflow skill.

## Why This Exists

`external-connector-readiness` exists because adopting a plugin, connector, API, or memory provider changes what the agent can reach, spend, and remember, and a host's install-time scan or a vendor's docs answer only part of that: it scores capability, auth, cost, freshness, safety, and fallback for each candidate, and reports a trial only from what was observed.

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

## Completion Checklist

- Candidate connector, target domain, read/write scope, modality needs, provider owner, fallback workflow, and stop condition are explicit.
- Cost, quota, credential, permission, live-data freshness, multimodal capture, safety, and compliance boundaries are marked ready, missing, risky, or not_observed.
- Route live read-only lookups to `omh-live-info`, external writes to `omh-apps`, datasets/SQL to `omh-data-analysis`, and missing tools to `omh-toolbelt-readiness` before claiming results.
- Provider responses, screenshots, audio/video/file captures, query outputs, message ids, and external mutations are reported only from observed trial evidence.
- For a memory provider, disabling it, removing its local cache, deleting its remote memory, deleting the account, and switching away are reported as distinct operations with distinct postconditions.
- Unknown deletion, isolation, or write semantics block automatic writes and irreversible adoption instead of resolving to an OMH or Hermes default.
- For a realtime voice connector, keep turn integrity, latency, fallback, interruption, and spoken tool safety separate; report unsupported or unobserved dimensions as hold or block rather than as a pass.
- On Hermes, record its install-time scans as observed evidence beside the card, never in place of it: `hermes plugins install` scans a plugin before installing it (`safe`, `caution`, or `dangerous`, and a `dangerous` verdict is refused even with `--force`), and an MCP server started through `npx`, `uvx`, or `pipx` is checked against OSV malware advisories and refused on a match with an error that reads `MCP server '<name>': BLOCKED: ...`. A scan counts only when its output was seen: the plugin scan does not run with `plugins.scan_on_install` off, and the OSV check covers known malware only and lets the server start when its lookup fails, so a quiet install or launch is not a clean result.

## Recovery Notes

- If the candidate list is unknown, route to `omh-skill-scout` or `omh-source-finder` before readiness scoring.
- If credentials, cost authority, or connector installation is missing, keep readiness blocked and route setup to `omh-toolbelt-readiness`.
- If a specific provider action is already selected, route read-only live data to `omh-live-info` or write/mutation tasks to `omh-apps`.
- If a memory-provider lifecycle field is unknown, ask the operator to declare it or supply an observed trial receipt; hand the result to memory-sync as not_omh_reviewed context rather than importing it into OMH review.
- If a realtime voice connector has no supplied realtime_voice_trial_receipt/v1, route the setup and the trial run to the host, connector, or operator that owns the microphone, call, or room, then consume only the returned receipt.

## Workflow Lane

- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `live-incident-response`, `automation-blueprint`, `github-event-ops`, `github-issue-intake`, `buzz`, `+40 more`) - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use before adopting, enabling, or routing an external plugin/connector/API when Hermes must compare capability, auth, cost, modality, freshness, safety, fallback, and observable trial evidence. Use it for an optional memory provider too, where enabling, switching, pausing, or removing it also needs identity scope, automatic hooks, retention, deletion, export, and switching answered before adoption.

    Strong routing signals: `external-connector-readiness`, `external connector readiness`, `connector readiness matrix`, `plugin readiness matrix`, `provider readiness`, `api readiness`, `connector adoption`, `external plugin adoption`, `weather plugin readiness`, `weather connector readiness`, `wxtrain readiness`, `onequery read-only sql`, `read-only sql connector`, `sql connector readiness`, `nextcloud connector`, `microsoft workspace connector`, `microsoft graph connector`, `chainlink connector`, `solana connector`, `xmr gateway`, `private crypto transaction`, `private cryptocurrency connector`, `crypto transaction plugin`, `blockchain gateway`, `composio connector`, `composio universal cli`, `universal cli connector`, `universal cli skill adoption`, `skill connector adoption`, `connector auth risk`, `connector cost auth risk`, `agentchat connector`, `peer-to-peer agent messaging connector`, `websocket identity connector`, `websocket connector trial`, `clawsocial connector`, `social discovery connector`, `windy pairing`, `windymail mailbox connector`, `matrix chat identity`, `antigravity cli connector`, `agy cli bridge`, `agy bridge connector`, `macos keychain oauth connector`, `oracle oci connector`, `oracle genai connector`, `miniverse bridge`, `crustocean platform connector`, `cost-aware connector`, `multimodal connector`, `multimodal routing`, `screenshot connector`, `audio connector`, `video generation connector`, `video connector readiness`, `text to video provider`, `home assistant connector`, `home assistant integration`, `home assistant device control`, `home assistant smart home`, `smart home connector`, `device control connector`, `plugin auto-routing`, `connector auto-routing`, `external tool trial`, `memory provider readiness`, `memory provider posture`, `memory provider lifecycle`, `memory provider adoption`, `memory provider retention`, `memory provider portability`, `memory provider sync failure`, `compare memory providers`, `memory provider comparison`, `memory provider`, `memory provider trial`, `memory provider benchmark`, `memory provider migration`, `memory provider rollback`, `switch memory provider`, `switching memory providers`, `disable memory provider`, `delete provider memory`, `export memory provider data`, `realtime voice connector`, `real-time voice connector`, `realtime voice readiness`, `realtime voice trial`, `realtime voice stack`, `voice connector readiness`, `voice connector trial`, `voice gateway readiness`, `voice gateway trial`, `voice agent connector readiness`, `voice trial receipt`, `voice turn integrity`, `voice turn receipt`, `barge-in behavior`, `barge-in handling`, `voice tool safety`, `spoken tool safety`, `커넥터 준비도`, `외부 커넥터 준비`, `외부 플러그인 채택`, `플러그인 준비도`, `커넥터 도입`, `플러그인 도입`, `비용 인증 리스크`, `인증 리스크`, `도입 비용`, `비용 기준 커넥터`, `자동 라우팅`, `멀티모달 커넥터`, `멀티모달 라우팅`, `홈 어시스턴트 커넥터`, `홈 어시스턴트 연동`, `홈 어시스턴트 기기 제어`, `홈 어시스턴트 스마트홈`, `홈어시스턴트 커넥터`, `홈어시스턴트 연동`, `홈어시스턴트 기기 제어`, `홈어시스턴트 스마트홈`, `스마트홈 커넥터`, `영상 생성 커넥터`

## Catalog Metadata

Category: `connector`
Phase: `connector-readiness`
Hermes role: `guide`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.
- Trial two or more memory providers on one corpus and one query set, never on each provider's own sample — load `references/memory-provider-trial.md` for the corpus, query, and reversibility rules.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

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

## Runtime Evidence

Preferred harness for this skill: `external-connector-readiness`.

```sh
omh runtime record --skill external-connector-readiness --harness external-connector-readiness --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
