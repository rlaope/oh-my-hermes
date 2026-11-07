---
name: "omh-live-info"
description: "[omh] Live rate, score, or local time a work task needs: policy overlay for live lookups - add provider, freshness, units, and source-quality gates after preferring native live-data tools for ordinary weather, finance, sports, maps, and time-zone requests. Use when the user says: live-info-operator, live info operator, live information, real time information, real-time information, weather today, current weather, weather forecast."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, live-info]
    category: live-info
    phase: live-info-task
    role: guide
    quality_tier: workflow-surface-gated
    related_skills: [omh-web-research, omh-finance-analysis, omh-apps]
---

# Live Info Operator

This is a Hermes-native `live-info-operator` workflow skill.

## Why This Exists

`live-info-operator` exists because a live number answered from recall, or from a quote with no timestamp, is wrong in a way the reader cannot see: it runs the lookup with an available tool and then checks what came back for provider, time, units and staleness before it is stated.

## Do Not Use When

- The question is a broad current-facts or citation question rather than one live value; use `omh-web-research`.
- A supplied ledger, budget or close needs analysis rather than a live rate; use `omh-finance-analysis`.
- The request would create, update, send or mutate state in an external app; use `omh-apps`.

## Examples

Good example:

- Prompt: live-info-operator check today's Seoul weather with freshness, units, and provider boundaries before answering.
- Expected behavior: Run the lookup with an available tool, then state the resolved place, the provider's observation time, units and local time zone; produce `prepare_live_info_operator_card` only when no tool can reach a provider.
- Why: The value is retrieved and checked, not recalled, and the card is the fallback rather than the answer.

Bad example:

- Prompt: live-info-operator invent the latest stock price without provider evidence or timestamp.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- The lookup was run with an available tool - a maps or time-zone tool, a quotes tool, otherwise web search or extract of one named provider page - and the card is prepared alone only when no tool can reach a provider.
- Domain, location or symbol, time window, provider preference, freshness, units, and stop condition are explicit.
- Weather names the resolved place (and the match when ambiguous), the provider's observation or forecast time, units and local time zone; a forecast is not an observation.
- A price or rate names the symbol or pair, venue, currency, quote timestamp, and whether the feed is delayed (free equity feeds often are, by about 15 minutes) or the market is closed.
- A score says live, final or scheduled, with the kickoff time zone; a time-zone answer uses an IANA zone name and the date the offset applies to (daylight saving).
- If the provider timestamp is older than the window the person needs (name it), say so instead of answering.
- Provider setup, API access, source quality, stale data, and missing location/symbol decisions are gated or marked missing.
- Weather, price, score, exchange-rate, time-zone, map, place, and traffic facts are reported only from observed provider evidence.

## Recovery Notes

- If the provider, plugin, API key, or connector is missing, route to `omh-toolbelt-readiness` before preparing result claims.
- If the request asks for citations, best practices, docs, or broad current-source synthesis, route to `ulw-research` instead.
- If the request would create, update, invite, send, or mutate external provider state, route to `omh-apps` instead.

## Workflow Lane

- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `live-incident-response`, `automation-blueprint`, `github-event-ops`, `github-issue-intake`, `buzz`, `+40 more`) - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when someone needs a live lookup now, with the provider, freshness, and units stated, and no result claimed beyond the tool's output.

    Strong routing signals: `live-info-operator`, `live info operator`, `live information`, `real time information`, `real-time information`, `weather today`, `current weather`, `weather forecast`, `stock price`, `crypto price`, `btc price`, `exchange rate`, `sports score`, `game score`, `time zone`, `timezone`, `time in`, `map directions`, `directions to`, `near me`, `nearby restaurants`, `traffic now`, `오늘 날씨`, `현재 날씨`, `날씨 예보`, `주가`, `코인 가격`, `환율`, `스포츠 점수`, `경기 결과`, `시간대`, `현재 시간`, `지도`, `길찾기`, `주변 식당`

## Catalog Metadata

Category: `live-info`
Phase: `live-info-task`
Hermes role: `guide`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- live_info_task_card/v1
- live_info_scope/v1
- freshness_boundary/v1
- live_info_result_manifest/v1 when observed
- next action
- prepared-vs-observed boundary

Artifact expectations:

- live_info_task_card/v1 metadata-only wrapper card when prepared
- live_info_scope/v1 with domain, location or symbol, time window, provider preference, units, and stop condition
- freshness_boundary/v1 separating requested recency, provider timestamp, source quality, and stale-result handling
- live_info_result_manifest/v1 only when provider response, timestamp, quote/source id, or rendered result is observed

Safety rules:

- A live information card is not provider availability, API access, live data retrieval, weather, market price, sports score, exchange-rate, time-zone, map, or place-result evidence unless observed live-info result evidence records it.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Runtime Evidence

Preferred harness for this skill: `live-info-operator`.

```sh
omh runtime record --skill live-info-operator --harness live-info-operator --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
