"""Canonical `sales-pipeline-review` skill data for issue #1376.

This module exports the canonical installed definition imported by
`catalog_definitions.py`. Its artifact names guide a human review and handoff;
the canonical operator surface is `omh runtime workflow-artifact
sales-pipeline-review <operation>`; no CRM mutation, storage, sync, alert,
outreach, or delivery is performed.

Triggers are English only. The three narrow Korean phrases live in
`src/routing/trigger_packs/ko.json`, not in this canonical definition.

Concept-level prior art (no code copied, no vendor integration adopted): the
GitLab Handbook sales stage/exit-criteria, coverage, aging, forecast-accuracy and
renewal-review material (MIT, `4165803c`), Odoo `crm_lead` field semantics
(LGPL-3.0, `1a13ceea`), the ERPNext `opportunity` doctype (GPL-3.0, `72fa7d0b`),
and Twenty's opportunity entity (AGPL-3.0 with exceptions, `c8fc7665`) were read
as data-model observations only.
"""

from __future__ import annotations

from .catalog_types import SPECIALIST_DOMAIN_HANDOFF_BOUNDARY, ExpertQuestion, ProcedureCheck, ProcedureBail, ProcedureStep, SkillDefinition, SkillExample


SALES_PIPELINE_SCOPE = "sales_pipeline_scope/v1"
SALES_PIPELINE_HEALTH = "sales_pipeline_health/v1"
SALES_FORECAST_ASSESSMENT = "sales_forecast_assessment/v1"
SALES_OUTCOME_LEARNING_ANNEX = "sales_outcome_learning_annex/v1"
SALES_RENEWAL_RISK_ANNEX = "sales_renewal_risk_annex/v1"
SALES_PIPELINE_HANDOFF = "sales_pipeline_handoff/v1"

_INPUT_SNAPSHOT = "pipeline snapshot"
_INPUT_AS_OF = "as-of time and review horizon"
_INPUT_DEFINITIONS = "currency, amount, stage, and forecast definitions"
_INPUT_PRIOR = "prior forecast, actuals, and quota or target"
_INPUT_OWNER = "decision owner"


DEFINITION = SkillDefinition(
    "sales-pipeline-review",
    "CRM pipeline or sales forecast to review: turn a supplied CRM export or pipeline snapshot into an evidence-bound pipeline health, forecast, and follow-up review.",
    (
        "sales-pipeline-review",
        "sales pipeline review",
        "pipeline review",
        "pipeline health",
        "pipeline coverage",
        "deal review",
        "deal health",
        "sales forecast review",
        "forecast call",
        "forecast calibration",
        "seller forecast",
        "stale deals",
        "slipped deals",
        "renewal risk review",
        "win loss review",
    ),
    "Use when a sales leader or business owner supplies a bounded CRM export or pipeline snapshot and needs recurring portfolio review: evidence scope and freshness, stage and forecast definitions, movement and aging, stale or slipped deals, exit-criteria gaps, next-step quality, concentration, forecast scenarios and prior-forecast calibration, optional won/lost or renewal-risk learning, and an owned follow-up handoff.",
    category="operations",
    phase="sales-pipeline-review",
    hermes_role="retained-cognition",
    delegation_boundary="retained-catalog-intent",
    handoff_policy=(
        SPECIALIST_DOMAIN_HANDOFF_BOUNDARY
        + " Hermes reviews supplied records; it does not replace a CRM, store or sync CRM data, mutate opportunities, create dashboards or alerts, send outreach, book revenue, or claim seller or buyer commitments that were not observed."
    ),
    required_inputs=(_INPUT_SNAPSHOT, _INPUT_AS_OF, _INPUT_DEFINITIONS, _INPUT_PRIOR, _INPUT_OWNER),
    expert_questions=(
        ExpertQuestion(
            _INPUT_SNAPSHOT,
            "Which CRM export or pipeline snapshot is supplied, with its opaque source reference, included motions, owners, cohort, record count, and known data-quality gaps such as duplicates or missing owners?",
            "어떤 CRM 내보내기 파일 또는 파이프라인 스냅샷이 제공되며, 출처 참조, 포함된 영업 방식, 담당자, 코호트, 레코드 수, 중복이나 담당자 누락 같은 알려진 데이터 품질 결함은 무엇인가요?",
        ),
        ExpertQuestion(
            _INPUT_AS_OF,
            "What as-of timestamp does the snapshot carry, what review horizon and cadence apply, and how stale may the data be before the review must HOLD?",
            "스냅샷의 기준 시각은 언제이고, 검토 기간과 주기는 무엇이며, 데이터가 얼마나 오래되면 검토를 보류해야 하나요?",
        ),
        ExpertQuestion(
            _INPUT_DEFINITIONS,
            "Which currency and conversion basis, amount meaning, close-date meaning, stage definitions with exit criteria, and forecast-category or probability definitions does your organization use for these records?",
            "이 레코드에 적용되는 통화와 환산 기준, 금액의 의미, 마감일의 의미, 종료 기준을 포함한 단계 정의, 예측 카테고리 또는 확률 정의는 무엇인가요?",
        ),
        ExpertQuestion(
            _INPUT_PRIOR,
            "Which prior forecast snapshots and observed won, lost, slipped, or renewal outcomes are supplied for calibration or learning, or is calibration not requested this cycle, and which quota or target applies to this horizon?",
            "보정이나 학습을 위해 어떤 이전 예측 스냅샷과 관찰된 수주, 실주, 지연, 갱신 결과와 이 기간의 할당량이나 목표가 제공되나요, 아니면 이번 주기에는 보정을 요청하지 않나요?",
        ),
        ExpertQuestion(
            _INPUT_OWNER,
            "Who owns the review decision, who may approve proposed CRM corrections, and which follow-up owners and due-date conventions apply?",
            "검토 결정의 책임자는 누구이고, 제안된 CRM 수정을 승인할 수 있는 사람은 누구이며, 후속 조치 담당자와 기한 규칙은 무엇인가요?",
        ),
    ),
    expected_outputs=(
        SALES_PIPELINE_SCOPE,
        SALES_PIPELINE_HEALTH,
        SALES_FORECAST_ASSESSMENT,
        SALES_OUTCOME_LEARNING_ANNEX,
        SALES_RENEWAL_RISK_ANNEX,
        SALES_PIPELINE_HANDOFF,
    ),
    procedure_checks=(
        ProcedureCheck(
            "sales_pipeline_scope_check",
            (
                "source_reference",
                "as_of_time",
                "review_horizon_cohort",
                "included_motions_owners",
                "currency_conversion_basis",
                "amount_semantics",
                "stage_definitions",
                "forecast_category_definitions",
                "freshness_status",
                "duplicate_status",
                "missing_owner_status",
                "data_quality_gaps",
                "disposition",
            ),
            "HOLD before any calculation or ranking when the as-of time is missing or stale for the horizon, stage or forecast-category semantics are undefined, currencies are mixed without an observed conversion basis, amount meaning is unknown, or duplicate records and missing owners are unresolved; every field is supplied or observed, never assumed.",
        ),
        ProcedureCheck(
            "sales_pipeline_health_check",
            (
                "stage_movement",
                "aging_stalls",
                "slipped_close_dates",
                "exit_criteria_evidence",
                "next_step_quality",
                "concentration",
                "duplicates",
                "missing_ownership",
                "deal_exceptions",
                "record_evidence_refs",
            ),
            "Derive movement, aging, stalls, slips, exit-criteria gaps, next-step quality, and concentration from supplied records only, citing the record reference behind every exception; never infer buyer activity or stage progress from silence, and never rank deals a HOLD scope excluded; stage_movement and slipped_close_dates need a prior snapshot or stage and close-date history fields, so with one snapshot and neither mark both `unavailable` and still report records whose close date is before the as-of time.",
        ),
        ProcedureCheck(
            "sales_forecast_state_check",
            (
                "supplied_seller_category",
                "supplied_probability",
                "scenario_range",
                "observed_buyer_commitment",
                "evidence_limits",
                "prior_forecast_actual_comparison",
                "calibration_status",
                "confidence",
                "target_source",
                "coverage_ratio",
            ),
            "Keep stage, supplied seller category or probability, model-derived scenario range, and observed buyer commitment as separate states: stage alone never creates a probability or commitment, a probability-weighted total is a scenario and not a promise, and calibration_status is `unavailable` unless matching prior snapshots and observed outcomes were supplied; coverage_ratio is pipeline over the supplied target and is `unavailable` when no target was supplied, never a benchmark multiple.",
        ),
        ProcedureCheck(
            "sales_outcome_learning_check",
            (
                "cohort_bounds",
                "observed_won_reasons",
                "observed_lost_reasons",
                "unqualified_reasons",
                "contradictions",
                "missing_evidence",
                "research_followups",
                "annex_status",
            ),
            "Emit the learning annex only when supplied won, lost, or unqualified evidence covers a bounded cohort; keep reasons observed rather than causal, record contradictions and missing evidence, and set annex_status to `unsupported` when the cohort is empty.",
        ),
        ProcedureCheck(
            "sales_renewal_risk_check",
            (
                "renewal_horizon",
                "health_signal",
                "utilization_signal",
                "support_signal",
                "budget_signal",
                "staffing_signal",
                "open_risks",
                "expansion_hypotheses",
                "owner",
                "annex_status",
            ),
            "Emit the renewal annex only when supplied renewal evidence exists; each signal is observed, missing, or unknown, expansion items stay hypotheses, and an unowned risk is recorded as a gap rather than assigned.",
        ),
        ProcedureCheck(
            "sales_pipeline_handoff_check",
            (
                "selected_account_followups",
                "owner",
                "due_date",
                "exit_criterion",
                "evidence_ref",
                "crm_object_field_value_proposals",
                "approval_state",
                "sibling_routes",
                "mutation_status",
                "disposition",
            ),
            "Every follow-up carries owner, due date, exit criterion, and evidence reference; every CRM correction carries object, field, value, evidence, owner, and approval state and stays proposed; mutation_status stays `not_observed` unless an observed connector result exists, and account discovery, qualitative customer material, generic calculation, and authoritative finance reporting are routed to their owning workflows.",
        ),
    ),
    procedure_steps=(
        ProcedureStep(
            "sales_pipeline_validate_scope",
            "validation",
            (_INPUT_SNAPSHOT, _INPUT_AS_OF, _INPUT_DEFINITIONS, _INPUT_OWNER),
            (SALES_PIPELINE_SCOPE,),
            ("sales_pipeline_scope_check",),
            "Record the opaque source reference, as-of time, horizon and cohort, included motions and owners, currency and conversion basis, amount semantics, stage and forecast-category definitions, freshness, duplicates, missing owners, and data-quality gaps; return `HOLD` with the exact blocking gap before calculating or ranking anything.",
            on_fail=ProcedureBail(
                still_stands=(),
                downgrade_to='unresolved',
                handback='Return sales_pipeline_scope/v1 as unresolved with the exact missing or stale timestamp, undefined semantics, currency basis, duplicate, or ownership gap; perform no calculation or ranking.',
            ),
        ),
        ProcedureStep(
            "sales_pipeline_assess_health",
            "analysis",
            (_INPUT_SNAPSHOT, _INPUT_AS_OF, _INPUT_DEFINITIONS),
            (SALES_PIPELINE_HEALTH,),
            ("sales_pipeline_health_check",),
            "From the validated records identify stage movement, aging and stalls against the supplied definitions, slipped close dates, exit-criteria evidence per stage, next-step quality, concentration by account, owner, or segment, duplicates, missing ownership, and deal exceptions, each tied to its record reference.",
        ),
        ProcedureStep(
            "sales_pipeline_assess_forecast",
            "analysis",
            (_INPUT_SNAPSHOT, _INPUT_DEFINITIONS, _INPUT_PRIOR),
            (SALES_FORECAST_ASSESSMENT,),
            ("sales_forecast_state_check",),
            "Report supplied seller categories and probabilities as supplied, build scenario ranges with their evidence limits, list observed buyer commitments separately, compare prior forecasts with observed outcomes only when matching snapshots and actuals exist, and state confidence; otherwise mark calibration `unavailable`.",
        ),
        ProcedureStep(
            "sales_pipeline_prepare_annexes",
            "production",
            (_INPUT_SNAPSHOT, _INPUT_AS_OF, _INPUT_PRIOR),
            (SALES_OUTCOME_LEARNING_ANNEX, SALES_RENEWAL_RISK_ANNEX),
            ("sales_outcome_learning_check", "sales_renewal_risk_check"),
            "When supplied evidence supports it, prepare the won/lost/unqualified learning annex by bounded cohort with contradictions and research follow-ups, and the renewal-risk annex with horizon, health, utilization, support, budget, and staffing signals, open risks, expansion hypotheses, and owner; otherwise emit each annex as `unsupported` with the missing evidence named.",
            on_fail=ProcedureBail(
                still_stands=('sales_pipeline_scope/v1', 'sales_pipeline_health/v1', 'sales_forecast_assessment/v1'),
                downgrade_to='tentative',
                handback='Return tentative sales_outcome_learning_annex/v1 and sales_renewal_risk_annex/v1 drafts with their cohort, source, contradiction, and owner gaps; mark unsupported annexes unsupported.',
            ),
        ),
        ProcedureStep(
            "sales_pipeline_validate_handoff",
            "validation",
            (_INPUT_SNAPSHOT, _INPUT_AS_OF, _INPUT_DEFINITIONS, _INPUT_PRIOR, _INPUT_OWNER),
            (SALES_PIPELINE_HANDOFF,),
            (
                "sales_pipeline_scope_check",
                "sales_pipeline_health_check",
                "sales_forecast_state_check",
                "sales_pipeline_handoff_check",
            ),
            "Select account follow-ups with owner, due date, exit criterion, and evidence reference, list proposed CRM object/field/value corrections with evidence, owner, and approval state, name the sibling route for discovery, feedback, calculation, or finance work, and return the review disposition with mutation, storage, sync, alert, and communication left to the connector boundary.",
            on_fail=ProcedureBail(
                still_stands=('sales_pipeline_scope/v1', 'sales_pipeline_health/v1', 'sales_forecast_assessment/v1', 'sales_outcome_learning_annex/v1', 'sales_renewal_risk_annex/v1'),
                downgrade_to='unresolved',
                handback='Return the unresolved sales_pipeline_handoff/v1 with missing follow-up owners, due dates, exit criteria, evidence, or CRM approvals named; keep CRM changes proposed and mutation not_observed.',
            ),
        ),
    ),
    artifact_expectations=(
        "prepared sales pipeline review brief when a wrapper captures it",
        "durable artifacts hold bounded aggregates, opaque source references, and only the account identifiers an approved handoff needs; raw export rows and message content are not persisted by default",
    ),
    safety_rules=(
        "Treat a missing or stale as-of time, undefined stage or forecast semantics, mixed currencies without an observed conversion basis, unknown amount meaning, duplicate opportunities, or missing owners as `HOLD`, never as an input to a calculation.",
        "Do not claim CRM storage, sync, mutation, dashboards, alerts, outreach, booked revenue, or seller or buyer commitments; a proposed correction is not a change and a scenario is not a promise.",
        "Consume the organization's supplied stage, category, probability, amount, and close-date definitions; never impose a vendor schema or a default probability table.",
        "Persist bounded aggregates and opaque source references only; raw CRM exports and message content stay out of durable artifacts unless the user explicitly approves a scoped exception.",
    ),
    quality_tier="decision-gated",
    quality_bar=(
        "Separate stage, seller forecast, model-derived scenario, and observed buyer commitment in every forecast statement.",
        "Cite the supplied record reference behind every exception, slip, stall, concentration, and proposed correction.",
        "Emit calibration only from matched prior snapshots and observed outcomes; otherwise state that it is unavailable.",
    ),
    reasoning_demand="standard",
    aliases=("pipeline-review", "forecast-review", "deal-review"),
    why_this_exists="`sales-pipeline-review` prepares evidence-bounded portfolio pipeline, forecast, and follow-up reviews from supplied CRM snapshots without replacing a CRM, mutating records, or claiming revenue.",
    do_not_use_when=(
        "The request is single-account discovery, qualification, buyer hypotheses, outreach drafting, or one opportunity's next step; use `sales-development`.",
        "The user wants a weekly status, release-risk, or operating review with no sales stages, forecast categories, or deal records; use `ops-review`.",
        "The user needs authoritative revenue, bookings, budget-variance, or close reporting rather than a pipeline scenario; use `finance-analysis`.",
        "The user wants generic exploration or calculation on a supplied table with no stage, forecast, or deal-health semantics; use `data-analysis`.",
        "The supplied material is qualitative customer feedback, call notes, or survey text rather than opportunity records; use `feedback-triage`.",
        "The user asks to update Salesforce or HubSpot, store or sync CRM data, send alerts or outreach, or change an opportunity; use `connector-operator` with explicit object, field, and authority.",
    ),
    good_example=SkillExample(
        prompt="Here is this week's pipeline export as of Monday 09:00; review deal health, slipped close dates, and whether the commit forecast holds up against last quarter's calls.",
        expected="Validate as-of time, currency, amount and stage semantics first, then prepare health, forecast-state, and calibration findings with owned follow-ups and proposed CRM corrections.",
        why="The request is portfolio-level pipeline and forecast review over a supplied snapshot with a stated as-of time.",
    ),
    bad_example=SkillExample(
        prompt="Write discovery questions for the Northwind opportunity and draft the follow-up email.",
        expected="Route to `sales-development`, not `sales-pipeline-review`.",
        why="A single account's discovery, qualification, and outreach draft has no portfolio, aging, or forecast-calibration objective.",
    ),
    final_checklist=(
        "The scope disposition is recorded before any figure: `HOLD` names the blocking gap, otherwise freshness, currency basis, amount and stage semantics, duplicates, and owners are confirmed from supplied data.",
        "Health, forecast, and annex outputs cite supplied record references, keep stage, seller forecast, scenario, and observed commitment separate, and mark calibration or an annex `unavailable` or `unsupported` instead of filling it.",
        "The handoff lists owner, due date, exit criterion, and evidence per follow-up, keeps every CRM correction proposed with an approval state, and reports mutation, storage, sync, alerts, and outreach as `not_observed` unless a connector result was observed.",
    ),
    recovery_notes=(
        "If the snapshot fails scope validation, return `HOLD` naming the exact missing definition, conversion basis, owner, or duplicate set and ask for it; do not rank or total partial data.",
        "If only one snapshot with no history fields is supplied, keep stage movement and slipped close dates `unavailable`; if prior forecasts or outcomes are absent, keep calibration `unavailable`; if an annex has no supporting evidence, emit it as `unsupported` with the gap named rather than omitting it.",
        "If a connector is unavailable, keep every CRM correction proposed and every alert or message unsent, and name the connector boundary as the next observable step.",
    ),
    progressive_disclosure=True,
    situations=(
        "which deals are stuck",
        "is our forecast realistic",
        "enough pipeline for the quarter",
        "review this salesforce export",
        "deals slipping to next quarter",
    ),
)
