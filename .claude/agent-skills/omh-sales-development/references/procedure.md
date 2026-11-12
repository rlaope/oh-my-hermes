# sales-development Specialist Procedure

Expert clarification questions:
- `account or segment`
  - English: Which fit criteria and disqualifiers, offer or use case, stage and owner, geography, and evidenced stakeholders and roles define the account or segment?
  - Korean: 어떤 적합 기준과 제외 기준, 제안 또는 사용 사례, 단계와 책임자, 지역, 근거가 있는 이해관계자와 역할이 계정 또는 세그먼트를 정의하나요?
- `available evidence`
  - English: Which source locators, dates, reliability and permission states, observed facts, contradictions, and approved personalization claims are available?
  - Korean: 어떤 출처 위치, 날짜, 신뢰도와 사용 권한 상태, 관찰된 사실, 상충 정보, 승인된 개인화 주장이 제공되나요?
- `buyer hypothesis`
  - English: Which stakeholder role, problem and current approach, impact, influence, buying stage, and evidence state should discovery test?
  - Korean: 어떤 이해관계자 역할, 문제와 현재 방식, 영향, 영향력, 구매 단계, 근거 상태를 발견 과정에서 검증해야 하나요?
- `sales objective`
  - English: Which motion, measurable outcome, offer and approved proof, channel and consent constraints, deadline, owner, approver, CRM shape, and next-step criterion apply?
  - Korean: 어떤 영업 방식, 측정 가능한 결과, 제안과 승인된 근거, 채널과 동의 제약, 기한, 책임자, 승인자, CRM 형식, 다음 단계 기준이 적용되나요?

## Procedure

Declared checks:
- `sales_account_evidence_check`
  - Required result fields: `fit_disqualifiers`, `offer_use_case`, `account_stage_owner`, `stakeholder_states`, `problem_current_approach_impact`, `source_locator_date_reliability_permission`, `contradictions`, `unknowns`, `claim_evidence_state`
  - Criterion: Every account, stakeholder, problem, impact and personalization claim must point to approved supplied or observed evidence or remain a hypothesis; never fill missing customer facts.
- `sales_qualification_state_check`
  - Required result fields: `stakeholder_authority_state`, `problem_current_state`, `measurable_impact`, `decision_criteria_process`, `alternatives`, `timing_urgency`, `risks_blockers`, `champion_economic_buyer_hypotheses`, `prioritized_questions`, `buyer_confirmation_evidence`, `disposition`
  - Criterion: Maintain framework-neutral observed, asserted, hypothesis, unknown and buyer-confirmed states, prioritized questions, and explicit ADVANCE, HOLD or DISQUALIFY evidence criteria; named methods are optional mappings only.
- `sales_sequence_eligibility_check`
  - Required result fields: `consent_basis`, `privacy_constraints`, `suppression_status`, `channel_eligibility`, `policy_constraints`, `audience_persona`, `timing_cadence`, `evidence_backed_personalization`, `approved_proof`, `purpose_value_cta`, `objection_hypothesis`, `validation_question`, `owner_approver`, `stop_opt_out_reply_conditions`, `draft_status`
  - Criterion: HOLD drafting when supplied consent, privacy, suppression, channel or policy eligibility is unknown; each eligible row must remain a draft with bounded cadence and stop, opt-out and reply conditions.
- `sales_handoff_check`
  - Required result fields: `proposed_confirmed_status`, `action`, `owner`, `approver`, `target_timing`, `success_exit_criterion`, `dependencies`, `evidence_refs`, `crm_object_field_value_proposals`, `unresolved_gaps`, `disposition`
  - Criterion: Emit measurable proposed handoff and CRM field/value changes without mutation; only observed buyer response may mark a next step, objection or commitment confirmed.

### `sales_scope_account_evidence` (analysis)

Record fit and disqualifiers, offer and stage, owner, evidenced stakeholders, problem and current approach signals, source provenance and permissions, contradictions, unknowns, and per-claim evidence state.

- Input refs: `account or segment`, `available evidence`, `buyer hypothesis`, `sales objective`
- Output refs: `sales_opportunity_evidence_record/v1`
- Check IDs: `sales_account_evidence_check`

### `sales_build_qualification_state` (analysis)

Build neutral qualification fields, distinguish seller hypotheses from observed buyer responses, prioritize discovery questions, and assign ADVANCE, HOLD or DISQUALIFY criteria without forcing a named method.

- Input refs: `account or segment`, `available evidence`, `buyer hypothesis`, `sales objective`
- Output refs: `sales_qualification_state/v1`
- Check IDs: `sales_qualification_state_check`

### `sales_check_sequence_eligibility` (validation)

Verify supplied consent basis, privacy and suppression restrictions, permitted channels, organizational policy, sender and approver, locale, timing and cadence before any message construction.

- Input refs: `account or segment`, `available evidence`, `sales objective`
- Output refs: `sales_draft_sequence/v1`
- Check IDs: `sales_sequence_eligibility_check`
- If this step fails: unresolved; still stands: `sales_opportunity_evidence_record/v1`, `sales_qualification_state/v1`; hand back: Return sales_draft_sequence/v1 as HOLD with missing consent, privacy, suppression, channel or policy evidence and the owner/approver question required before drafting.

### `sales_prepare_draft_sequence` (production)

Prepare eligible draft rows for audience, channel, cadence, supported personalization and proof, purpose, value, CTA, objection hypothesis and validation question, owner, approver and stop conditions; do not send.

- Input refs: `account or segment`, `available evidence`, `buyer hypothesis`, `sales objective`
- Output refs: `sales_draft_sequence/v1`
- Check IDs: `sales_account_evidence_check`, `sales_sequence_eligibility_check`
- If this step fails: tentative; still stands: `sales_opportunity_evidence_record/v1`, `sales_qualification_state/v1`; hand back: Return sales_draft_sequence/v1 with unsupported personalization or proof and missing cadence, owner, approver or stop conditions marked for correction, keeping every row an unsent draft.

### `sales_validate_handoff` (validation)

Return proposed versus confirmed actions, ownership, timing, exit criteria, dependencies, evidence refs, CRM object/field/value proposals, gaps and ADVANCE, HOLD or DISQUALIFY disposition, preserving confirmation only from observed response.

- Input refs: `account or segment`, `available evidence`, `buyer hypothesis`, `sales objective`
- Output refs: `sales_handoff_disposition/v1`
- Check IDs: `sales_account_evidence_check`, `sales_qualification_state_check`, `sales_sequence_eligibility_check`, `sales_handoff_check`
- If this step fails: unresolved; still stands: `sales_draft_sequence/v1`, `sales_opportunity_evidence_record/v1`, `sales_qualification_state/v1`; hand back: Return sales_handoff_disposition/v1 as HOLD with proposed actions, CRM field/value proposals, missing buyer confirmation and unresolved owner, timing, dependency or exit-criterion gaps.
