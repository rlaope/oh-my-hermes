# lifecycle-growth Specialist Procedure

Expert clarification questions:
- `lifecycle objective and stage`
  - English: Which lifecycle stage (onboarding, activation, retention, re-engagement, referral, monetization) and which value-bearing user behavior should improve, from what baseline?
  - Korean: 어떤 라이프사이클 단계(온보딩, 활성화, 리텐션, 재참여, 추천, 수익화)에서 어떤 가치 있는 사용자 행동을 어느 기준선에서 개선해야 하나요?
- `target segment`
  - English: Which users are eligible, by what stable identity key, and who must be excluded, including already-treated, suppressed, or overlapping-campaign users?
  - Korean: 어떤 사용자가 대상이며 어떤 안정적인 식별 키를 쓰고, 이미 처리된 사용자, 억제 대상, 겹치는 캠페인 대상 등 누구를 제외해야 하나요?
- `event schema and baseline`
  - English: Which canonical events define entry, exposure, action, and outcome, what do they mean, how fresh is the data, and what baseline and denominator are supplied?
  - Korean: 진입, 노출, 행동, 성과를 정의하는 표준 이벤트는 무엇이고 각각의 의미, 데이터 최신성, 제공된 기준선과 분모는 무엇인가요?
- `channels or product surfaces`
  - English: Which in-app surfaces, channels, or product treatments are available, and which of them can report actual display or receipt rather than only a send attempt?
  - Korean: 사용 가능한 인앱 화면, 채널, 제품 처리는 무엇이며 그중 발송 시도가 아니라 실제 표시나 수신을 보고할 수 있는 것은 무엇인가요?
- `consent and policy constraints`
  - English: Which consent basis, suppression lists, user preferences, legal or tenant constraints, quiet hours, locale rules, and frequency budgets apply?
  - Korean: 어떤 동의 근거, 억제 목록, 사용자 선호, 법적 또는 테넌트 제약, 방해 금지 시간, 로케일 규칙, 발송 빈도 예산이 적용되나요?
- `experiment budget`
  - English: How much traffic, runtime, holdout share, and risk can the experiment spend, and which guardrail breach must pause or roll it back?
  - Korean: 실험에 쓸 수 있는 트래픽, 실행 기간, 홀드아웃 비율, 위험 한도는 얼마이며 어떤 가드레일 위반 시 중단하거나 롤백해야 하나요?
- `decision owner`
  - English: Who owns the decision, who approves launch, and who may call ship, rollback, review, or insufficient_data on the readout?
  - Korean: 의사결정 책임자와 출시 승인자는 누구이며 리드아웃에서 ship, rollback, review, insufficient_data를 결정할 수 있는 사람은 누구인가요?

## Procedure

Declared checks:
- `lifecycle_target_behavior_check`
  - Required result fields: `lifecycle_stage`, `target_behavior`, `baseline_value`, `baseline_window`, `evidence_refs`, `hypotheses`, `non_goals`, `owner`, `disposition`
  - Criterion: PASS only when one value-bearing activation or retention behavior, its supplied baseline and window, observed evidence refs, and a decision owner are named before any treatment is proposed; otherwise HOLD naming each missing field.
- `lifecycle_audience_eligibility_check`
  - Required result fields: `identity_key`, `canonical_events`, `event_semantics_status`, `entry_conditions`, `exit_conditions`, `exclusions`, `denominator_status`, `idempotency_key`, `reentry_policy`, `collision_policy`, `disposition`
  - Criterion: HOLD when the identity key, event semantics, or denominator is unknown; every eligible audience must carry entry and exit conditions, exclusions, an idempotency key, a re-entry policy, and a collision policy for overlapping campaigns.
- `lifecycle_safety_eligibility_check`
  - Required result fields: `consent_basis`, `suppression_precedence`, `legal_tenant_constraints`, `user_preferences`, `channel_eligibility`, `quiet_hours`, `locale`, `global_frequency_budget`, `campaign_frequency_budget`, `throttle_grouping`, `workflow_content_state`, `promotion_decision`, `disposition`
  - Criterion: Consent and suppression must come from supplied records, never from product usage or a missing opt-out; HOLD when consent, suppression precedence, channel eligibility, or either frequency budget is unknown. The throttle grouping record keeps the configured key or expression apart from its resolved value and names the recipient or tenant scope, the fallback for a missing or empty value, and any window-reset consequence; production or published workflow content is read-only, and every edit routes through a development or draft copy plus an explicit promotion decision.
- `lifecycle_experiment_validity_check`
  - Required result fields: `treatment_control`, `assignment_unit`, `assignment_stickiness`, `exposure_unit`, `exposure_definition`, `primary_metric`, `guardrail_metrics`, `holdout_rationale`, `minimum_runtime`, `data_health_checks`, `pause_rollback_conditions`, `approval_state`
  - Criterion: Require sticky assignment, exposure defined as actual treatment display or receipt rather than send or eligibility, exactly one primary metric, at least one guardrail, a holdout rationale, a minimum runtime, data-health checks, and pause/rollback conditions; approval_state stays unapproved until a named human approves.
- `lifecycle_readout_evidence_check`
  - Required result fields: `eligible_count`, `assigned_count`, `attempted_count`, `delivered_count`, `displayed_count`, `acted_count`, `outcome_count`, `exposure_evidence`, `contact_pressure_state`, `repeated_contact_count`, `channels`, `denominator_status`, `freshness_status`, `sample_ratio_status`, `cross_exposure_status`, `instrumentation_status`, `overlap_status`, `step_outcomes`, `step_trace_status`, `analysis_run_state`, `analysis_observed_at`, `analysis_delay_status`, `evidence_refs`, `causal_claim_status`, `disposition`
  - Criterion: Require a separate `lifecycle_growth_exposure_evidence/v1` companion with the bound audience/safety policies, eligibility/exclusion checks, assignment identity/count, reconciled populations, observed repeated-contact pressure and experiment-overlap checks, and per-channel reach/failure accounting. Missing evidence means HOLD, not zero or ship; configuration alone cannot supply it. Fill eligible, assigned, attempted, reached, and converted populations only from supplied observations, keeping delivery and action separate. Partial delivery requires review and channel failures retain their reasons; an independently justified rollback outranks missing launch evidence. Pause interpretation on sample-ratio mismatch, cross-exposure, stale data, broken instrumentation, or overlapping interventions; disposition must be exactly one of `ship`, `rollback`, `review`, or `insufficient_data`. Record every conditional step as `matched` or `skipped` with its own reason and status, never its evaluated values; a missing or failed best-effort step trace is not delivery evidence and must not turn a send into a failure. Name the analysis run as exactly one of `not_started`, `queued`, `running`, `completed`, `failed`, `canceled`, or `unknown` with the time that state was observed; elapsed time never rewrites the state.
- `lifecycle_handoff_boundary_check`
  - Required result fields: `action_class`, `target_owner`, `approver`, `evidence_refs`, `timing`, `stop_conditions`, `analysis_cancellation`, `approval_state`, `readiness`, `disposition`
  - Criterion: Each proposed action must name its class (`connector`, `content`, `analytics`, `product`, `implementation`), owner, approver, evidence refs, timing, and stop conditions; readiness is HOLD while any prior check holds or approval is missing, and no delivery, display, action, outcome, or causal claim may appear without observed evidence. A cancellation or status-reconciliation handoff names the exact run and its scope, and keeps three states apart: the prepared request, which stays `prepared_not_observed`; an observed provider acknowledgement; and an observed terminal cancellation, which alone may back a `canceled` run state.

### `lifecycle_define_target_behavior` (analysis)

Name the lifecycle stage, the value-bearing behavior to move, its supplied baseline and window, the observed evidence behind the problem, competing hypotheses, non-goals, and the owner before proposing any message or product treatment.

- Input refs: `lifecycle objective and stage`, `event schema and baseline`, `decision owner`
- Output refs: `lifecycle_growth_brief/v1`
- Check IDs: `lifecycle_target_behavior_check`

### `lifecycle_scope_audience_triggers` (analysis)

Define the stable identity key, canonical entry and exit events with their semantics, exclusions, denominator, idempotency key, re-entry policy, and collision policy; record any unknown as a HOLD rather than assuming it.

- Input refs: `target segment`, `event schema and baseline`
- Output refs: `audience_trigger_policy/v1`
- Check IDs: `lifecycle_audience_eligibility_check`

### `lifecycle_check_safety_eligibility` (validation)

Order suppression precedence above legal and tenant constraints, user preferences, channel eligibility, quiet hours, and locale, then set global and per-campaign frequency budgets; record the throttle grouping key, resolved value, scope, and fallback so distinct recipients or tenants never share one window; treat production workflow content as read-only and route edits to a draft with an explicit promotion decision; fail closed when any eligibility input is missing.

- Input refs: `target segment`, `channels or product surfaces`, `consent and policy constraints`
- Output refs: `lifecycle_safety_policy/v1`
- Check IDs: `lifecycle_safety_eligibility_check`
- If this step fails: unresolved; still stands: `lifecycle_growth_brief/v1`, `audience_trigger_policy/v1`; hand back: Return the unresolved lifecycle_safety_policy/v1 with missing consent, suppression, channel eligibility, frequency budgets, or throttle scope named; keep launch on HOLD.

### `lifecycle_design_experiment` (production)

Specify treatment and control, sticky assignment and exposure units, the actual-exposure definition, one primary metric, guardrails, holdout rationale, minimum runtime, data-health checks, pause and rollback conditions, and an approval state that a named human must set before any launch handoff.

- Input refs: `lifecycle objective and stage`, `event schema and baseline`, `channels or product surfaces`, `experiment budget`, `decision owner`
- Output refs: `growth_experiment_plan/v1`
- Check IDs: `lifecycle_target_behavior_check`, `lifecycle_experiment_validity_check`
- If this step fails: tentative; still stands: `lifecycle_growth_brief/v1`, `audience_trigger_policy/v1`, `lifecycle_safety_policy/v1`; hand back: Return the tentative growth_experiment_plan/v1 with missing assignment, actual-exposure definition, metric, guardrail, runtime, or rollback checks flagged; keep approval unapproved.

### `lifecycle_prepare_measurement_readout` (validation)

Lay out eligible, assigned, attempted, delivered, displayed, acted, and outcome stages with denominator and freshness checks. Supply the separate exposure-evidence companion to evaluate or prepare; unknown audience, assignment, contact pressure, overlap, or channel accounting holds expansion. First-launch preparation needs observed audience/reachability/contact checks, not invented treatment counts. Keep causal-claim status separate, list each conditional step as matched or skipped with a redacted reason, and record the analysis run's state and observation time alongside any delay. Record `ship`, `rollback`, `review`, or `insufficient_data` without forcing a decision on thin data.

- Input refs: `event schema and baseline`, `experiment budget`, `decision owner`
- Output refs: `growth_measurement_readout/v1`
- Check IDs: `lifecycle_readout_evidence_check`
- If this step fails: unresolved; still stands: `lifecycle_growth_brief/v1`, `audience_trigger_policy/v1`, `lifecycle_safety_policy/v1`, `growth_experiment_plan/v1`; hand back: Return the unresolved growth_measurement_readout/v1 with missing exposure evidence, denominator, freshness, overlap, channel, or analysis-run checks named; keep counts unknown, not zero.

### `lifecycle_validate_handoff` (validation)

Propose connector, content, analytics, product, or implementation actions with owner, approver, evidence refs, timing, and stop conditions; prepare any cancellation or status-reconciliation request against the exact named run and leave it `prepared_not_observed` until a provider result is observed; return HOLD readiness while any check holds, approval is missing, or the latest analysis run is still in flight, route validated product changes to `product-brief`, and never report a send, display, action, outcome, cancellation, or causal effect that was not observed.

- Input refs: `lifecycle objective and stage`, `target segment`, `event schema and baseline`, `channels or product surfaces`, `consent and policy constraints`, `experiment budget`, `decision owner`
- Output refs: `growth_handoff_disposition/v1`
- Check IDs: `lifecycle_target_behavior_check`, `lifecycle_audience_eligibility_check`, `lifecycle_safety_eligibility_check`, `lifecycle_experiment_validity_check`, `lifecycle_readout_evidence_check`, `lifecycle_handoff_boundary_check`
- If this step fails: unresolved; still stands: `lifecycle_growth_brief/v1`, `audience_trigger_policy/v1`, `lifecycle_safety_policy/v1`, `growth_experiment_plan/v1`, `growth_measurement_readout/v1`; hand back: Return the unresolved growth_handoff_disposition/v1 with blocked actions, missing owners or approvals, and the exact analysis run needing status reconciliation; leave requests prepared_not_observed.
