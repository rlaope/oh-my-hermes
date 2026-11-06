# sales-pipeline-review Specialist Procedure

Expert clarification questions:
- `pipeline snapshot`
  - English: Which CRM export or pipeline snapshot is supplied, with its opaque source reference, included motions, owners, cohort, record count, and known data-quality gaps such as duplicates or missing owners?
  - Korean: 어떤 CRM 내보내기 파일 또는 파이프라인 스냅샷이 제공되며, 출처 참조, 포함된 영업 방식, 담당자, 코호트, 레코드 수, 중복이나 담당자 누락 같은 알려진 데이터 품질 결함은 무엇인가요?
- `as-of time and review horizon`
  - English: What as-of timestamp does the snapshot carry, what review horizon and cadence apply, and how stale may the data be before the review must HOLD?
  - Korean: 스냅샷의 기준 시각은 언제이고, 검토 기간과 주기는 무엇이며, 데이터가 얼마나 오래되면 검토를 보류해야 하나요?
- `currency, amount, stage, and forecast definitions`
  - English: Which currency and conversion basis, amount meaning, close-date meaning, stage definitions with exit criteria, and forecast-category or probability definitions does your organization use for these records?
  - Korean: 이 레코드에 적용되는 통화와 환산 기준, 금액의 의미, 마감일의 의미, 종료 기준을 포함한 단계 정의, 예측 카테고리 또는 확률 정의는 무엇인가요?
- `prior forecast, actuals, and quota or target`
  - English: Which prior forecast snapshots and observed won, lost, slipped, or renewal outcomes are supplied for calibration or learning, or is calibration not requested this cycle, and which quota or target applies to this horizon?
  - Korean: 보정이나 학습을 위해 어떤 이전 예측 스냅샷과 관찰된 수주, 실주, 지연, 갱신 결과와 이 기간의 할당량이나 목표가 제공되나요, 아니면 이번 주기에는 보정을 요청하지 않나요?
- `decision owner`
  - English: Who owns the review decision, who may approve proposed CRM corrections, and which follow-up owners and due-date conventions apply?
  - Korean: 검토 결정의 책임자는 누구이고, 제안된 CRM 수정을 승인할 수 있는 사람은 누구이며, 후속 조치 담당자와 기한 규칙은 무엇인가요?

## Procedure

Declared checks:
- `sales_pipeline_scope_check`
  - Required result fields: `source_reference`, `as_of_time`, `review_horizon_cohort`, `included_motions_owners`, `currency_conversion_basis`, `amount_semantics`, `stage_definitions`, `forecast_category_definitions`, `freshness_status`, `duplicate_status`, `missing_owner_status`, `data_quality_gaps`, `disposition`
  - Criterion: HOLD before any calculation or ranking when the as-of time is missing or stale for the horizon, stage or forecast-category semantics are undefined, currencies are mixed without an observed conversion basis, amount meaning is unknown, or duplicate records and missing owners are unresolved; every field is supplied or observed, never assumed.
- `sales_pipeline_health_check`
  - Required result fields: `stage_movement`, `aging_stalls`, `slipped_close_dates`, `exit_criteria_evidence`, `next_step_quality`, `concentration`, `duplicates`, `missing_ownership`, `deal_exceptions`, `record_evidence_refs`
  - Criterion: Derive movement, aging, stalls, slips, exit-criteria gaps, next-step quality, and concentration from supplied records only, citing the record reference behind every exception; never infer buyer activity or stage progress from silence, and never rank deals a HOLD scope excluded; stage_movement and slipped_close_dates need a prior snapshot or stage and close-date history fields, so with one snapshot and neither mark both `unavailable` and still report records whose close date is before the as-of time.
- `sales_forecast_state_check`
  - Required result fields: `supplied_seller_category`, `supplied_probability`, `scenario_range`, `observed_buyer_commitment`, `evidence_limits`, `prior_forecast_actual_comparison`, `calibration_status`, `confidence`, `target_source`, `coverage_ratio`
  - Criterion: Keep stage, supplied seller category or probability, model-derived scenario range, and observed buyer commitment as separate states: stage alone never creates a probability or commitment, a probability-weighted total is a scenario and not a promise, and calibration_status is `unavailable` unless matching prior snapshots and observed outcomes were supplied; coverage_ratio is pipeline over the supplied target and is `unavailable` when no target was supplied, never a benchmark multiple.
- `sales_outcome_learning_check`
  - Required result fields: `cohort_bounds`, `observed_won_reasons`, `observed_lost_reasons`, `unqualified_reasons`, `contradictions`, `missing_evidence`, `research_followups`, `annex_status`
  - Criterion: Emit the learning annex only when supplied won, lost, or unqualified evidence covers a bounded cohort; keep reasons observed rather than causal, record contradictions and missing evidence, and set annex_status to `unsupported` when the cohort is empty.
- `sales_renewal_risk_check`
  - Required result fields: `renewal_horizon`, `health_signal`, `utilization_signal`, `support_signal`, `budget_signal`, `staffing_signal`, `open_risks`, `expansion_hypotheses`, `owner`, `annex_status`
  - Criterion: Emit the renewal annex only when supplied renewal evidence exists; each signal is observed, missing, or unknown, expansion items stay hypotheses, and an unowned risk is recorded as a gap rather than assigned.
- `sales_pipeline_handoff_check`
  - Required result fields: `selected_account_followups`, `owner`, `due_date`, `exit_criterion`, `evidence_ref`, `crm_object_field_value_proposals`, `approval_state`, `sibling_routes`, `mutation_status`, `disposition`
  - Criterion: Every follow-up carries owner, due date, exit criterion, and evidence reference; every CRM correction carries object, field, value, evidence, owner, and approval state and stays proposed; mutation_status stays `not_observed` unless an observed connector result exists, and account discovery, qualitative customer material, generic calculation, and authoritative finance reporting are routed to their owning workflows.

### `sales_pipeline_validate_scope` (validation)

Record the opaque source reference, as-of time, horizon and cohort, included motions and owners, currency and conversion basis, amount semantics, stage and forecast-category definitions, freshness, duplicates, missing owners, and data-quality gaps; return `HOLD` with the exact blocking gap before calculating or ranking anything.

- Input refs: `pipeline snapshot`, `as-of time and review horizon`, `currency, amount, stage, and forecast definitions`, `decision owner`
- Output refs: `sales_pipeline_scope/v1`
- Check IDs: `sales_pipeline_scope_check`
- If this step fails: unresolved; still stands: nothing yet; hand back: Return sales_pipeline_scope/v1 as unresolved with the exact missing or stale timestamp, undefined semantics, currency basis, duplicate, or ownership gap; perform no calculation or ranking.

### `sales_pipeline_assess_health` (analysis)

From the validated records identify stage movement, aging and stalls against the supplied definitions, slipped close dates, exit-criteria evidence per stage, next-step quality, concentration by account, owner, or segment, duplicates, missing ownership, and deal exceptions, each tied to its record reference.

- Input refs: `pipeline snapshot`, `as-of time and review horizon`, `currency, amount, stage, and forecast definitions`
- Output refs: `sales_pipeline_health/v1`
- Check IDs: `sales_pipeline_health_check`

### `sales_pipeline_assess_forecast` (analysis)

Report supplied seller categories and probabilities as supplied, build scenario ranges with their evidence limits, list observed buyer commitments separately, compare prior forecasts with observed outcomes only when matching snapshots and actuals exist, and state confidence; otherwise mark calibration `unavailable`.

- Input refs: `pipeline snapshot`, `currency, amount, stage, and forecast definitions`, `prior forecast, actuals, and quota or target`
- Output refs: `sales_forecast_assessment/v1`
- Check IDs: `sales_forecast_state_check`

### `sales_pipeline_prepare_annexes` (production)

When supplied evidence supports it, prepare the won/lost/unqualified learning annex by bounded cohort with contradictions and research follow-ups, and the renewal-risk annex with horizon, health, utilization, support, budget, and staffing signals, open risks, expansion hypotheses, and owner; otherwise emit each annex as `unsupported` with the missing evidence named.

- Input refs: `pipeline snapshot`, `as-of time and review horizon`, `prior forecast, actuals, and quota or target`
- Output refs: `sales_outcome_learning_annex/v1`, `sales_renewal_risk_annex/v1`
- Check IDs: `sales_outcome_learning_check`, `sales_renewal_risk_check`
- If this step fails: tentative; still stands: `sales_pipeline_scope/v1`, `sales_pipeline_health/v1`, `sales_forecast_assessment/v1`; hand back: Return tentative sales_outcome_learning_annex/v1 and sales_renewal_risk_annex/v1 drafts with their cohort, source, contradiction, and owner gaps; mark unsupported annexes unsupported.

### `sales_pipeline_validate_handoff` (validation)

Select account follow-ups with owner, due date, exit criterion, and evidence reference, list proposed CRM object/field/value corrections with evidence, owner, and approval state, name the sibling route for discovery, feedback, calculation, or finance work, and return the review disposition with mutation, storage, sync, alert, and communication left to the connector boundary.

- Input refs: `pipeline snapshot`, `as-of time and review horizon`, `currency, amount, stage, and forecast definitions`, `prior forecast, actuals, and quota or target`, `decision owner`
- Output refs: `sales_pipeline_handoff/v1`
- Check IDs: `sales_pipeline_scope_check`, `sales_pipeline_health_check`, `sales_forecast_state_check`, `sales_pipeline_handoff_check`
- If this step fails: unresolved; still stands: `sales_pipeline_scope/v1`, `sales_pipeline_health/v1`, `sales_forecast_assessment/v1`, `sales_outcome_learning_annex/v1`, `sales_renewal_risk_annex/v1`; hand back: Return the unresolved sales_pipeline_handoff/v1 with missing follow-up owners, due dates, exit criteria, evidence, or CRM approvals named; keep CRM changes proposed and mutation not_observed.
