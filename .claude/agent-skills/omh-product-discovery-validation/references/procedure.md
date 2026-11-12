# product-discovery-validation Specialist Procedure

Expert clarification questions:
- `problem hypothesis`
  - English: Which customer problem or opportunity do you believe exists, for whom, and what would you expect to observe if it were false?
  - Korean: 어떤 고객 문제 또는 기회가 존재한다고 보시며, 누구에게 해당하고, 그 가설이 틀렸다면 무엇이 관찰될 것으로 예상하시나요?
- `target segment`
  - English: Which target segment, buyer versus user roles, and recruitable participant criteria define who must show the problem, or is that audience still unknown?
  - Korean: 어떤 목표 세그먼트, 구매자와 사용자 구분, 모집 가능한 참여자 기준이 이 문제를 보여야 하는 대상을 정의하나요, 아니면 그 대상이 아직 미정인가요?
- `known evidence and current alternatives`
  - English: Which evidence already exists, from which source class and date, and which current alternatives or workarounds do those people use today?
  - Korean: 이미 확보된 근거는 무엇이고 출처 유형과 날짜는 어떠하며, 그 사람들이 지금 사용하는 대안이나 우회 방법은 무엇인가요?
- `decision owner`
  - English: Who owns the kill, pivot, persevere, or inconclusive decision, and who must accept a handoff to a product brief?
  - Korean: 킬, 피벗, 지속, 미결 결정의 책임자는 누구이며, 제품 브리프로의 인계는 누가 승인해야 하나요?
- `learning budget and deadline`
  - English: What learning budget in time, money, and participant count applies, and by which date must the decision be made?
  - Korean: 시간, 비용, 참여자 수 기준의 학습 예산은 얼마이며, 어느 날짜까지 결정을 내려야 하나요?
- `success, failure, and stop criteria`
  - English: Which observed conditions would count as success, failure, or a stop before evidence is gathered?
  - Korean: 근거를 수집하기 전에 어떤 관찰 조건을 성공, 실패, 중단으로 간주할지 정해 두셨나요?

## Procedure

Declared checks:
- `discovery_decision_frame_check`
  - Required result fields: `problem_hypothesis`, `segment`, `target_segment_definition`, `current_alternatives`, `decision`, `constraints`, `owner`, `learning_budget`, `kill_criteria`, `disposition`
  - Criterion: PASS only when every frame field is supplied by the user or marked unknown; HOLD when the decision, owner, learning budget, or kill criteria are missing, and never infer them. Record `target_segment_definition` as recruitable, behaviorally observed, unknown, synthetic-only, or non-recruitable; an unknown, synthetic-only, or non-recruitable audience keeps discovery framing and evidence planning open while it blocks solution work, and never invent a persona to close it.
- `discovery_evidence_class_check`
  - Required result fields: `source_class`, `safe_reference`, `observation_date`, `segment`, `observation`, `direction`, `confidence_limits`, `unresolved_inconsistency`, `pointer_status`
  - Criterion: Label every item as external-human, behavioral-data, internal-stakeholder, secondary-research, synthetic, or inferred; record direction as supporting or contradicting; assign no confidence from source class alone; keep a source pointer a pointer, not a fresh observation.
- `discovery_customer_reentry_check`
  - Required result fields: `participant_criteria`, `interview_guide_focus`, `consent_privacy_constraints`, `bias_controls`, `human_task_handoff`, `evidence_reentry_contract`, `transcript_exclusion`
  - Criterion: The guide must ask about past behavior, current workarounds, switching costs, and observed commitments, not praise or future intent; refuse simulated personas or model-generated answers as participants; raw recordings, transcripts, and contact data stay outside durable artifacts.
- `discovery_problem_gate_check`
  - Required result fields: `problem_gate_state`, `supporting_refs`, `contradicting_refs`, `gate_reason`, `audience_gate`, `missing_audience_evidence`, `solution_work_permitted`
  - Criterion: Set `problem_gate_state` to validated, refuted, or inconclusive from external-human or behavioral-data entries only; the supporting entries must come from the same target segment the frame names. `solution_work_permitted` is true only when the gate is validated and `audience_gate` is defined, so refuted, inconclusive, or an unknown, synthetic-only, or non-recruitable audience never advances to a solution, PRD, prototype-as-validation, or coding handoff; name the missing audience evidence as the next task instead.
- `discovery_assumption_precommit_check`
  - Required result fields: `assumption_category`, `decision_impact`, `evidence_gap`, `rank`, `smallest_disconfirming_test`, `success_condition`, `failure_condition`, `inconclusive_condition`, `segment_sample`, `deadline`, `cost`, `owner`, `evidence_reentry`
  - Criterion: Rank each value, usability, feasibility, viability, go-to-market, or ethics assumption by decision impact multiplied by evidence gap; every test must carry precommitted success, failure, and inconclusive conditions plus segment, deadline, cost, owner, and evidence re-entry before any observation is accepted.
- `discovery_decision_receipt_check`
  - Required result fields: `decision`, `precommitted_criteria`, `observed_evidence`, `confidence_limits`, `rejected_paths`, `residual_risks`, `next_route`, `promotion_guard`
  - Criterion: Decision must be kill, pivot, persevere, or inconclusive; missing external evidence, a refuted problem, unresolved contradiction, an expired test, an inconclusive result, or an audience that is unknown, synthetic-only, or non-recruitable must not produce persevere or a `omh-product-brief`, `omh-decision-prototype`, or coding route; rejected and falsified hypotheses are preserved, and no raw transcript is replayed.
- `discovery_gtm_hypothesis_check`
  - Required result fields: `beachhead_segment`, `buyer_user_distinction`, `current_alternative`, `value_proposition`, `pricing_wtp_hypothesis`, `initial_channel`, `first_cohort`, `learning_metrics`, `evidence_basis`
  - Criterion: Every field is a labeled hypothesis with its evidence basis; pricing, willingness-to-pay, and market-size figures require an observed source or behavioral evidence with explicit assumptions, and an unsupported field stays unknown instead of a generic ratio.

### `discovery_frame_decision` (analysis)

Write the decision the discovery must inform, the problem hypothesis, segment, known current alternatives, constraints, owner, learning budget, and kill criteria before touching any evidence.

- Input refs: `problem hypothesis`, `target segment`, `decision owner`, `learning budget and deadline`, `success, failure, and stop criteria`
- Output refs: `discovery_decision_frame/v1`
- Check IDs: `discovery_decision_frame_check`

### `discovery_classify_evidence` (analysis)

Enter each supplied item with its source class, safe reference, date, segment, observation, direction, and confidence limits; flag contradictions as unresolved inconsistency rather than resolving them by preference.

- Input refs: `known evidence and current alternatives`, `target segment`
- Output refs: `discovery_evidence_ledger/v1`
- Check IDs: `discovery_evidence_class_check`

### `discovery_plan_customer_reentry` (production)

Prepare participant criteria, a past-behavior interview guide, consent and privacy constraints, bias controls, the human task that recruits and interviews, and the contract for how bounded summaries re-enter the ledger; OMH contacts nobody.

- Input refs: `target segment`, `known evidence and current alternatives`, `learning budget and deadline`
- Output refs: `customer_discovery_plan/v1`
- Check IDs: `discovery_customer_reentry_check`
- If this step fails: tentative; still stands: `discovery_decision_frame/v1`, `discovery_evidence_ledger/v1`; hand back: Return the tentative customer_discovery_plan/v1 with missing participant criteria, past-behavior prompts, consent, bias controls, or evidence re-entry fields flagged for correction.

### `discovery_gate_problem` (validation)

Compare ledger entries against the precommitted criteria and record the problem gate as validated, refuted, or inconclusive, admitting only entries observed in the framed target segment; when it is not validated, or when the audience is unknown, synthetic-only, or non-recruitable, stop solution and MVP work and name the customer or audience evidence still missing.

- Input refs: `problem hypothesis`, `known evidence and current alternatives`, `success, failure, and stop criteria`
- Output refs: `discovery_decision_frame/v1`
- Check IDs: `discovery_evidence_class_check`, `discovery_problem_gate_check`
- If this step fails: unresolved; still stands: `discovery_decision_frame/v1`, `discovery_evidence_ledger/v1`, `customer_discovery_plan/v1`; hand back: Return the discovery_decision_frame/v1 as unresolved with missing target-segment human or behavioral evidence and the customer_discovery_plan/v1; keep solution work blocked.

### `discovery_rank_assumptions` (production)

List the assumptions by category, score decision impact and evidence gap, and select for each top-ranked assumption the cheapest disconfirming test that could change the decision, with its precommitted conditions and bounded budget; a prototype is one optional instrument routed to `omh-decision-prototype`, never validation by itself.

- Input refs: `problem hypothesis`, `target segment`, `known evidence and current alternatives`, `decision owner`, `learning budget and deadline`, `success, failure, and stop criteria`
- Output refs: `assumption_test_portfolio/v1`
- Check IDs: `discovery_assumption_precommit_check`
- If this step fails: tentative; still stands: `discovery_decision_frame/v1`, `discovery_evidence_ledger/v1`, `customer_discovery_plan/v1`; hand back: Return the tentative assumption_test_portfolio/v1 with unranked assumptions or missing success, failure, inconclusive, segment, budget, owner, and evidence re-entry conditions flagged.

### `discovery_draft_gtm_hypothesis` (production)

Draft the beachhead segment, buyer versus user, current alternative, value proposition, pricing or willingness-to-pay hypothesis, one initial channel, first cohort, and learning metrics, each tied to its evidence basis or marked unknown.

- Input refs: `problem hypothesis`, `target segment`, `known evidence and current alternatives`
- Output refs: `initial_gtm_hypothesis/v1`
- Check IDs: `discovery_gtm_hypothesis_check`
- If this step fails: tentative; still stands: `discovery_decision_frame/v1`, `discovery_evidence_ledger/v1`, `customer_discovery_plan/v1`, `assumption_test_portfolio/v1`; hand back: Return the tentative initial_gtm_hypothesis/v1 with unsupported pricing, willingness-to-pay, or market-size fields left unknown and each missing evidence basis named.

### `discovery_validate_decision_receipt` (validation)

Record the decision against the precommitted criteria and observed evidence, with confidence limits, rejected paths, residual risks, and the next route; a `persevere` receipt hands `omh-product-brief` the validated problem, segment, MVP learning boundary, residual risks, and GTM hypotheses without transcript replay.

- Input refs: `problem hypothesis`, `target segment`, `known evidence and current alternatives`, `decision owner`, `learning budget and deadline`, `success, failure, and stop criteria`
- Output refs: `discovery_decision_receipt/v1`
- Check IDs: `discovery_decision_frame_check`, `discovery_evidence_class_check`, `discovery_customer_reentry_check`, `discovery_problem_gate_check`, `discovery_assumption_precommit_check`, `discovery_decision_receipt_check`, `discovery_gtm_hypothesis_check`
- If this step fails: unresolved; still stands: `discovery_decision_frame/v1`, `discovery_evidence_ledger/v1`, `customer_discovery_plan/v1`, `assumption_test_portfolio/v1`, `initial_gtm_hypothesis/v1`; hand back: Return an unresolved discovery_decision_receipt/v1 naming unmet precommitted criteria, contradictions, rejected paths, and missing audience evidence; block persevere and product handoff.
