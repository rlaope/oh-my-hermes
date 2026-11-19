---
name: "omh-external-connector-readiness"
description: "[omh] Evaluating a plugin, connector or API for adoption."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, connector]
    category: connector
    phase: connector-readiness
    role: guide
    quality_tier: workflow-surface-gated
---

# External Connector Readiness

This is an OMH `external-connector-readiness` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`external-connector-readiness` exists because adopting a plugin, connector, API, or memory provider changes what the agent can reach, spend, and remember, and a host's install-time scan or a vendor's docs answer only part of that: it scores capability, auth, cost, freshness, safety, and fallback for each candidate, and reports a trial only from what was observed.

## Do Not Use When

- Choosing which coding owner runs a task.
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
- If a memory-provider lifecycle field is unknown, ask the operator to declare it or supply an observed trial receipt; keep the result as not_omh_reviewed context rather than importing it into OMH review.
- If a realtime voice connector has no supplied realtime_voice_trial_receipt/v1, route the setup and the trial run to the host, connector, or operator that owns the microphone, call, or room, then consume only the returned receipt.



## When to Use

Use before adopting, enabling, or routing an external plugin/connector/API when Hermes must compare capability, auth, cost, modality, freshness, safety, fallback, and observable trial evidence. Use it for an optional memory provider too, where enabling, switching, pausing, or removing it also needs identity scope, automatic hooks, retention, deletion, export, and switching answered before adoption.

    Strong routing signals: `external-connector-readiness`, `external connector readiness`, `connector readiness matrix`, `plugin readiness matrix`, `provider readiness`, `api readiness`, `connector adoption`, `external plugin adoption`, `weather plugin readiness`, `weather connector readiness`, `wxtrain readiness`, `onequery read-only sql`, `read-only sql connector`, `sql connector readiness`, `nextcloud connector`, `microsoft workspace connector`, `microsoft graph connector`, `chainlink connector`, `solana connector`, `xmr gateway`, `private crypto transaction`, `private cryptocurrency connector`, `crypto transaction plugin`, `blockchain gateway`, `composio connector`, `composio universal cli`, `universal cli connector`, `universal cli skill adoption`, `skill connector adoption`, `connector auth risk`, `connector cost auth risk`, `agentchat connector`, `peer-to-peer agent messaging connector`, `websocket identity connector`, `websocket connector trial`, `clawsocial connector`, `social discovery connector`, `windy pairing`, `windymail mailbox connector`, `matrix chat identity`, `antigravity cli connector`, `agy cli bridge`, `agy bridge connector`, `macos keychain oauth connector`, `oracle oci connector`, `oracle genai connector`, `miniverse bridge`, `crustocean platform connector`, `cost-aware connector`, `multimodal connector`, `multimodal routing`, `screenshot connector`, `audio connector`, `video generation connector`, `video connector readiness`, `text to video provider`, `home assistant connector`, `home assistant integration`, `home assistant device control`, `home assistant smart home`, `smart home connector`, `device control connector`, `plugin auto-routing`, `connector auto-routing`, `external tool trial`, `memory provider readiness`, `memory provider posture`, `memory provider lifecycle`, `memory provider adoption`, `memory provider retention`, `memory provider portability`, `memory provider sync failure`, `compare memory providers`, `memory provider comparison`, `memory provider`, `memory provider trial`, `memory provider benchmark`, `memory provider migration`, `memory provider rollback`, `switch memory provider`, `switching memory providers`, `disable memory provider`, `delete provider memory`, `export memory provider data`, `realtime voice connector`, `real-time voice connector`, `realtime voice readiness`, `realtime voice trial`, `realtime voice stack`, `voice connector readiness`, `voice connector trial`, `voice gateway readiness`, `voice gateway trial`, `voice agent connector readiness`, `voice trial receipt`, `voice turn integrity`, `voice turn receipt`, `barge-in behavior`, `barge-in handling`, `voice tool safety`, `spoken tool safety`, `커넥터 준비도`, `외부 커넥터 준비`, `외부 플러그인 채택`, `플러그인 준비도`, `커넥터 도입`, `플러그인 도입`, `비용 인증 리스크`, `인증 리스크`, `도입 비용`, `비용 기준 커넥터`, `자동 라우팅`, `멀티모달 커넥터`, `멀티모달 라우팅`, `홈 어시스턴트 커넥터`, `홈 어시스턴트 연동`, `홈 어시스턴트 기기 제어`, `홈 어시스턴트 스마트홈`, `홈어시스턴트 커넥터`, `홈어시스턴트 연동`, `홈어시스턴트 기기 제어`, `홈어시스턴트 스마트홈`, `스마트홈 커넥터`, `영상 생성 커넥터`

## Catalog Metadata

Read `references/details.md` before you act: it holds this skill's quality bar and catalog metadata, kept out of this file so the whole of it fits in one read on every host.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
