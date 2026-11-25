# Live Info Operator

Load this on-demand contract after the compact `live-info-operator` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

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

## Full Input, Output, and Artifact Expectations

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
