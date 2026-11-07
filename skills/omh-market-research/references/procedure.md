# market-research Specialist Procedure

Expert clarification questions:
- `decision and audience`
  - English: Which decision must this inform, for which audience and decision owner?
  - Korean: 이 조사가 뒷받침할 의사결정은 무엇이고, 대상 청중과 결정권자는 누구인가요?
- `buyer segment and geography`
  - English: Which buyer versus user segment, geography, alternatives, and exclusions define the market?
  - Korean: 시장을 정의하는 구매자와 사용자 구분, 지역, 대안, 제외 대상은 무엇인가요?
- `period currency units and source cutoff`
  - English: Which observation period, currency/base year, units/denominator, and source cutoff apply?
  - Korean: 어떤 관측 기간, 통화와 기준 연도, 단위와 분모, 자료 기준일을 적용하나요?
- `available evidence and source boundary`
  - English: Which evidence is supplied, which sources may be retrieved, and which access/privacy limits apply?
  - Korean: 어떤 근거가 제공되었고, 어떤 출처를 조회할 수 있으며, 접근과 개인정보 제한은 무엇인가요?
- `research budget and stop condition`
  - English: What time/source/cost budget and stop condition bound the work?
  - Korean: 시간, 출처, 비용 예산과 중단 조건은 무엇인가요?

## Procedure

Declared checks:
- `market_scope_check`
  - Required result fields: `decision`, `segment`, `geography`, `period`, `currency_base_year`, `units_denominator`, `source_cutoff`, `budget`, `stop_condition`
  - Criterion: PASS only when scope is supplied or explicitly unknown; HOLD numeric estimates when a missing denominator or period makes them uninterpretable.
- `market_source_check`
  - Required result fields: `source_id`, `source_date`, `retrieved_at`, `coverage`, `evidence_class`, `claim_ids`, `failed_retrieval`, `contrary_evidence`
  - Criterion: Require observed, vendor-asserted, or inferred per claim, not per document; preserve source dates and access failures, and do not count copied press coverage as independent evidence.
- `market_size_check`
  - Required result fields: `input_refs`, `assumptions`, `formula_units`, `tool_receipt`, `tam`, `sam`, `som`, `reconciliation`, `sensitivity`
  - Criterion: Use tools for calculations; enforce nested scope and consistent units. Unknown operands yield unknown results, not zeros; test bounded scenarios and reconcile top-down with bottom-up or explain why one is unavailable.
- `market_customer_check`
  - Required result fields: `evidence_ids`, `quote_ids`, `segment`, `sample_frame`, `jtbd`, `past_behavior`, `bias`, `contrary_evidence`, `privacy`
  - Criterion: Keep observed behavior separate from stated intent and analyst inference. Attribute quotations exactly or omit them; sample counts are not population prevalence or willingness-to-pay evidence.
- `market_comparability_check`
  - Required result fields: `competitor`, `source_ids`, `as_of`, `coverage`, `segment`, `packaging`, `normalized_price`, `limits`, `evidence_class`
  - Criterion: Require comparable buyer/use-case and billing units before ranking. A missing feature or price is not observed, never absent or free; vendor claims are not verified outcomes.
- `market_findings_check`
  - Required result fields: `finding_ids`, `source_refs`, `assumption_refs`, `contrary_evidence`, `confidence_limits`, `decision_implications`, `verification_needs`, `stop_reason`
  - Criterion: Every finding must link evidence or explicit assumptions, state uncertainty and a falsifier, and name a next verification owner without making the product investment decision.

### `frame_market` (analysis)

Record the bounded market contract and exclusions; choose only the relevant method references and precommit what evidence would change the decision.

- Input refs: `decision and audience`, `buyer segment and geography`, `period currency units and source cutoff`, `available evidence and source boundary`, `research budget and stop condition`
- Output refs: `market scope and source ledger`
- Check IDs: `market_scope_check`

### `register_market_evidence` (analysis)

Register sources at retrieval with IDs, dates, cutoff coverage, access failures and claim classes; seek contrary evidence within the budget, preserving gaps rather than filling them from recall.

- Input refs: `period currency units and source cutoff`, `available evidence and source boundary`, `research budget and stop condition`
- Output refs: `market scope and source ledger`
- Check IDs: `market_source_check`

### `size_addressable_market` (production)

When in scope, use references/market-sizing.md to construct sourced TAM/SAM/SOM boundaries, calculate top-down and bottom-up scenarios with tools, reconcile disagreement, and report sensitivity; otherwise mark this lane not requested.

- Input refs: `buyer segment and geography`, `period currency units and source cutoff`, `available evidence and source boundary`
- Output refs: `TAM SAM SOM model and sensitivity`
- Check IDs: `market_size_check`
- If this step fails: unresolved; still stands: `market scope and source ledger`; hand back: Return the market scope and source ledger with an unresolved TAM SAM SOM model and sensitivity, preserving unknown operands, unit gaps, calculation receipts, and unreconciled ranges.

### `analyze_customer_evidence` (analysis)

When in scope, use references/customer-evidence.md to code attributed jobs, pains, triggers, alternatives and behavior; retain sample frame, selection bias and contrary cases. An interview plan is not an interview.

- Input refs: `buyer segment and geography`, `available evidence and source boundary`
- Output refs: `customer evidence and JTBD matrix`
- Check IDs: `market_customer_check`

### `compare_competitors_and_pricing` (analysis)

When in scope, use references/competitive-pricing.md to build dated comparable profiles and normalize price/packaging with tool calculations; separate observation, assertion and inference and keep unavailable metrics unavailable.

- Input refs: `buyer segment and geography`, `period currency units and source cutoff`, `available evidence and source boundary`
- Output refs: `comparable competitor and pricing profiles`
- Check IDs: `market_comparability_check`

### `deliver_market_findings` (validation)

Use references/findings-template.md to deliver findings, calculations, assumptions, contrary evidence and unresolved retrieval gaps; record optional lanes as not requested, stop at the agreed budget, and hand decision implications to the decision owner.

- Input refs: `decision and audience`, `buyer segment and geography`, `period currency units and source cutoff`, `available evidence and source boundary`, `research budget and stop condition`
- Output refs: `decision-ready market findings`
- Check IDs: `market_source_check`, `market_findings_check`
- If this step fails: tentative; still stands: `market scope and source ledger`, `TAM SAM SOM model and sensitivity`, `customer evidence and JTBD matrix`, `comparable competitor and pricing profiles`; hand back: Return tentative decision-ready market findings with the source ledger, calculation receipts, assumptions, contrary evidence, and unresolved retrieval gaps; name each next verification owner.
