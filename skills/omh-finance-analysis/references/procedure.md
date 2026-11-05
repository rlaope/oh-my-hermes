# finance-analysis Specialist Procedure

Expert clarification questions:
- `period`
  - English: What period, cutoff, reporting entity/perimeter, currency/units, accounting basis, comparator version, and close status apply?
  - Korean: 어떤 기간, 마감 기준일, 보고 법인과 범위, 통화와 단위, 회계 기준, 비교 버전, 마감 상태를 적용해야 하나요?
- `supplied finance source`
  - English: Which actual and comparator sources, provenance, versions, completeness checks, account mappings, and tie-out status are supplied?
  - Korean: 어떤 실적 및 비교 자료와 출처, 버전, 완전성 점검, 계정 매핑, 대사 상태가 제공되었나요?
- `decision question`
  - English: Which decision, owner, threshold or materiality boundary, and deadline should the analysis support?
  - Korean: 이 분석이 지원할 의사결정, 책임자, 임계값 또는 중요성 기준, 기한은 무엇인가요?
- `calculation assumptions`
  - English: Which formulas, approved policy sources, materiality, FX or allocation treatments, and challenged assumptions apply?
  - Korean: 어떤 공식, 승인된 정책 근거, 중요성, 환율 또는 배부 처리, 검토할 가정을 적용해야 하나요?

## Procedure

Declared checks:
- `finance_scope_comparability_check`
  - Required result fields: `entity_perimeter`, `period_cutoff`, `currency_units`, `accounting_basis`, `comparator_version`, `close_status`, `source_provenance`
  - Criterion: PASS only when scope and comparator attributes are supplied and comparable; otherwise HOLD with each missing or conflicting attribute.
- `finance_source_reconciliation_check`
  - Required result fields: `totals_status`, `account_mapping_status`, `basis_units_status`, `cutoff_status`, `duplicate_missing_status`, `tie_out_status`, `unreconciled_gaps`
  - Criterion: Record totals, mappings, basis and units, cutoff, duplicate or missing records, and tie-out evidence; never label an untied extract reconciled.
- `finance_policy_assumption_check`
  - Required result fields: `formula_provenance`, `policy_provenance`, `materiality_status`, `fx_allocation_treatment`, `assumption_approval_status`
  - Criterion: Use supplied formulas, policy, thresholds, FX, and allocations; mark every unsupplied choice an unapproved assumption and infer no accounting policy or assurance.
- `finance_conditional_interpretation_check`
  - Required result fields: `analysis_applicability`, `revenue_bridge_status`, `receivables_dso_status`, `working_capital_status`, `unavailable_evidence`
  - Criterion: Run only relevant supported analyses; distinguish bookings, billings, recognized and deferred revenue and cutoff, or calculate DSO, aging, AR, AP, inventory and working-capital movement only from stated comparable formulas and balances.
- `finance_validation_escalation_check`
  - Required result fields: `recalculation_status`, `reconciliation_status`, `source_conflicts`, `control_exceptions`, `high_impact_assumptions`, `disposition`, `escalation_owner`
  - Criterion: HOLD authoritative conclusions and escalate unresolved policy, cutoff, source conflict, control exception, failed recalculation, or high-impact assumption to a qualified finance or accounting owner.

### `finance_scope_sources` (analysis)

Capture the reporting and comparator perimeter, units, basis, versions, close state, provenance, and explicit evidence gaps before interpreting amounts.

- Input refs: `period`, `supplied finance source`
- Output refs: `finance_scope_source_record/v1`
- Check IDs: `finance_scope_comparability_check`

### `finance_reconcile_sources` (validation)

Tie totals and account mappings, normalize only approved basis and units, test cutoff and duplicate or missing records, and preserve unreconciled gaps.

- Input refs: `period`, `supplied finance source`
- Output refs: `finance_reconciliation_analysis_schedule/v1`
- Check IDs: `finance_source_reconciliation_check`
- If this step fails: unresolved; still stands: `finance_scope_source_record/v1`; hand back: Return the draft finance_reconciliation_analysis_schedule/v1 with untied totals, mappings, basis or unit conflicts, cutoff defects and duplicate or missing records listed; do not label the extract reconciled.

### `finance_analyze_variances` (analysis)

Recalculate comparable variances with supplied formulas and thresholds, separating facts, approved policy, proposed assumptions, and material decision effects.

- Input refs: `supplied finance source`, `calculation assumptions`, `decision question`
- Output refs: `finance_reconciliation_analysis_schedule/v1`
- Check IDs: `finance_policy_assumption_check`

### `finance_interpret_conditionally` (analysis)

Apply revenue, receivables, liquidity, or working-capital interpretation only when relevant evidence exists, and mark unavailable analyses rather than forcing them.

- Input refs: `supplied finance source`, `calculation assumptions`, `decision question`
- Output refs: `finance_risk_register/v1`
- Check IDs: `finance_conditional_interpretation_check`

### `finance_validate_brief` (validation)

Report recalculation and reconciliation status, evidence-linked risks, assumptions, decision options and owners, and a PASS or HOLD disposition with mandatory escalation gaps.

- Input refs: `period`, `supplied finance source`, `decision question`, `calculation assumptions`
- Output refs: `finance_decision_brief/v1`
- Check IDs: `finance_scope_comparability_check`, `finance_source_reconciliation_check`, `finance_policy_assumption_check`, `finance_conditional_interpretation_check`, `finance_validation_escalation_check`
- If this step fails: unresolved; still stands: `finance_scope_source_record/v1`, `finance_risk_register/v1`; hand back: Return finance_decision_brief/v1 as HOLD with failed recalculations, reconciliation gaps, policy or cutoff conflicts, control exceptions and high-impact assumptions assigned to a qualified finance or accounting owner.
