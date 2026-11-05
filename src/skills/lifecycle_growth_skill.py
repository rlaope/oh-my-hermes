"""Canonical `lifecycle-growth` skill data (issue #1374).

One `SkillDefinition` instance, `DEFINITION`, holding pure catalog data for the
lifecycle-growth workflow: routing triggers, required inputs with their
clarification questions, the six versioned artifact names, and the ordered
progressive-disclosure procedure the existing renderer turns into
`references/procedure.md`.

`catalog_definitions.py` imports this module as the single installed definition
source. Its artifacts guide human review and handoff; runtime operations are exposed through the
canonical `omh runtime workflow-artifact lifecycle-growth <operation>` interface.
The launch-review operations `audience`, `promote`, and `graduate` (issue #1399)
return separate versioned records and do not change the six artifacts below.

Concept-level prior art (pinned, MIT outside enterprise directories; no code
copied, no integration adopted): PostHog `ae880d30` for actual-display exposure,
launch/pause/stop controls, ordered audience reachability, read-only promotion
preflight, separate post-rollout gate cleanup, and deleted-reference/no-data
evaluation classes (issue #1399 review; `docs/SKILL-SOURCES.md` records the
five community commits), GrowthBook `095f6164` for sticky assignment,
guardrails, minimum runtime, the ship/rollback/review/insufficient-data
vocabulary, and the analysis-run state distinction that keeps queued, running,
failed, canceled, and never-started work apart from a missing result (issue
#1429), Dittofeed `52b2bee9` for entry/exit, re-entry, and idempotency,
Novu `c7bc772f` for preference precedence, digest/throttle windows, throttle
grouping identity, per-step matched/skipped tracing, and production read-only
workflow content (issue #1400).
"""

from __future__ import annotations

from .catalog_types import (
    ExpertQuestion,
    ProcedureCheck,
    ProcedureBail,
    ProcedureStep,
    SkillDefinition,
    SkillExample,
)

LIFECYCLE_GROWTH_SKILL_NAME = "lifecycle-growth"

LIFECYCLE_GROWTH_ARTIFACTS = (
    "lifecycle_growth_brief/v1",
    "audience_trigger_policy/v1",
    "lifecycle_safety_policy/v1",
    "growth_experiment_plan/v1",
    "growth_measurement_readout/v1",
    "growth_handoff_disposition/v1",
)

# Closed readout vocabulary. The readout check names these literally so the
# rendered procedure and any later contract module read the same four words.
LIFECYCLE_GROWTH_READOUT_DISPOSITIONS = ("ship", "rollback", "review", "insufficient_data")

# English only. Korean phrases live in `src/routing/trigger_packs/ko.json`.
LIFECYCLE_GROWTH_TRIGGERS = (
    "lifecycle-growth",
    "lifecycle growth",
    "lifecycle marketing",
    "lifecycle messaging",
    "in-app journey",
    "in-app message campaign",
    "onboarding journey",
    "onboarding nudge",
    "activation campaign",
    "activation experiment",
    "retention campaign",
    "retention experiment",
    "re-engagement campaign",
    "win-back campaign",
    "referral experiment",
    "monetization experiment",
    "growth experiment",
    "holdout experiment",
    "product-led growth loop",
)

_INPUT_OBJECTIVE = "lifecycle objective and stage"
_INPUT_SEGMENT = "target segment"
_INPUT_EVENTS = "event schema and baseline"
_INPUT_SURFACES = "channels or product surfaces"
_INPUT_CONSENT = "consent and policy constraints"
_INPUT_BUDGET = "experiment budget"
_INPUT_OWNER = "decision owner"

_ALL_INPUTS = (
    _INPUT_OBJECTIVE,
    _INPUT_SEGMENT,
    _INPUT_EVENTS,
    _INPUT_SURFACES,
    _INPUT_CONSENT,
    _INPUT_BUDGET,
    _INPUT_OWNER,
)

_BRIEF, _AUDIENCE, _SAFETY, _EXPERIMENT, _READOUT, _HANDOFF = LIFECYCLE_GROWTH_ARTIFACTS

_CHECK_TARGET = "lifecycle_target_behavior_check"
_CHECK_AUDIENCE = "lifecycle_audience_eligibility_check"
_CHECK_SAFETY = "lifecycle_safety_eligibility_check"
_CHECK_EXPERIMENT = "lifecycle_experiment_validity_check"
_CHECK_READOUT = "lifecycle_readout_evidence_check"
_CHECK_HANDOFF = "lifecycle_handoff_boundary_check"


DEFINITION = SkillDefinition(
    LIFECYCLE_GROWTH_SKILL_NAME,
    "Churn or weak activation among users: turn an observed onboarding, activation, retention, re-engagement, referral, or monetization problem into one consent-safe in-app journey or growth experiment plan with a bounded readout and an explicit decision.",
    LIFECYCLE_GROWTH_TRIGGERS,
    "Use when a product or growth owner wants to improve a lifecycle stage and needs the target behavior, eligible audience, safety policy, experiment design, launch/rollback gates, measurement readout, and ship/rollback/review/insufficient_data decision assembled as one evidence-bounded plan.",
    category="strategy",
    phase="lifecycle-growth",
    hermes_role="retained-cognition",
    delegation_boundary="retained-catalog-intent",
    handoff_policy=(
        "Keep lifecycle framing, audience and safety policy, experiment design, and readout interpretation in Hermes. "
        "A prepared journey or experiment plan is not a send, a flag change, a delivered message, a displayed treatment, "
        "a user action, a business outcome, or a causal result. Hand external sends and flag mutations to "
        "`connector-operator`, copy to `content-operator`, supplied-data calculation to `data-analysis`, recurring "
        "scheduling to `automation-blueprint`, and validated product changes to `product-brief`, each only after the "
        "human approval gate and only reported from observed evidence."
    ),
    required_inputs=_ALL_INPUTS,
    expert_questions=(
        ExpertQuestion(
            _INPUT_OBJECTIVE,
            "Which lifecycle stage (onboarding, activation, retention, re-engagement, referral, monetization) and which value-bearing user behavior should improve, from what baseline?",
            "어떤 라이프사이클 단계(온보딩, 활성화, 리텐션, 재참여, 추천, 수익화)에서 어떤 가치 있는 사용자 행동을 어느 기준선에서 개선해야 하나요?",
        ),
        ExpertQuestion(
            _INPUT_SEGMENT,
            "Which users are eligible, by what stable identity key, and who must be excluded, including already-treated, suppressed, or overlapping-campaign users?",
            "어떤 사용자가 대상이며 어떤 안정적인 식별 키를 쓰고, 이미 처리된 사용자, 억제 대상, 겹치는 캠페인 대상 등 누구를 제외해야 하나요?",
        ),
        ExpertQuestion(
            _INPUT_EVENTS,
            "Which canonical events define entry, exposure, action, and outcome, what do they mean, how fresh is the data, and what baseline and denominator are supplied?",
            "진입, 노출, 행동, 성과를 정의하는 표준 이벤트는 무엇이고 각각의 의미, 데이터 최신성, 제공된 기준선과 분모는 무엇인가요?",
        ),
        ExpertQuestion(
            _INPUT_SURFACES,
            "Which in-app surfaces, channels, or product treatments are available, and which of them can report actual display or receipt rather than only a send attempt?",
            "사용 가능한 인앱 화면, 채널, 제품 처리는 무엇이며 그중 발송 시도가 아니라 실제 표시나 수신을 보고할 수 있는 것은 무엇인가요?",
        ),
        ExpertQuestion(
            _INPUT_CONSENT,
            "Which consent basis, suppression lists, user preferences, legal or tenant constraints, quiet hours, locale rules, and frequency budgets apply?",
            "어떤 동의 근거, 억제 목록, 사용자 선호, 법적 또는 테넌트 제약, 방해 금지 시간, 로케일 규칙, 발송 빈도 예산이 적용되나요?",
        ),
        ExpertQuestion(
            _INPUT_BUDGET,
            "How much traffic, runtime, holdout share, and risk can the experiment spend, and which guardrail breach must pause or roll it back?",
            "실험에 쓸 수 있는 트래픽, 실행 기간, 홀드아웃 비율, 위험 한도는 얼마이며 어떤 가드레일 위반 시 중단하거나 롤백해야 하나요?",
        ),
        ExpertQuestion(
            _INPUT_OWNER,
            "Who owns the decision, who approves launch, and who may call ship, rollback, review, or insufficient_data on the readout?",
            "의사결정 책임자와 출시 승인자는 누구이며 리드아웃에서 ship, rollback, review, insufficient_data를 결정할 수 있는 사람은 누구인가요?",
        ),
    ),
    expected_outputs=LIFECYCLE_GROWTH_ARTIFACTS,
    procedure_checks=(
        ProcedureCheck(
            _CHECK_TARGET,
            ("lifecycle_stage", "target_behavior", "baseline_value", "baseline_window", "evidence_refs", "hypotheses", "non_goals", "owner", "disposition"),
            "PASS only when one value-bearing activation or retention behavior, its supplied baseline and window, observed evidence refs, and a decision owner are named before any treatment is proposed; otherwise HOLD naming each missing field.",
        ),
        ProcedureCheck(
            _CHECK_AUDIENCE,
            ("identity_key", "canonical_events", "event_semantics_status", "entry_conditions", "exit_conditions", "exclusions", "denominator_status", "idempotency_key", "reentry_policy", "collision_policy", "disposition"),
            "HOLD when the identity key, event semantics, or denominator is unknown; every eligible audience must carry entry and exit conditions, exclusions, an idempotency key, a re-entry policy, and a collision policy for overlapping campaigns.",
        ),
        ProcedureCheck(
            _CHECK_SAFETY,
            ("consent_basis", "suppression_precedence", "legal_tenant_constraints", "user_preferences", "channel_eligibility", "quiet_hours", "locale", "global_frequency_budget", "campaign_frequency_budget", "throttle_grouping", "workflow_content_state", "promotion_decision", "disposition"),
            "Consent and suppression must come from supplied records, never from product usage or a missing opt-out; HOLD when consent, suppression precedence, channel eligibility, or either frequency budget is unknown. The throttle grouping record keeps the configured key or expression apart from its resolved value and names the recipient or tenant scope, the fallback for a missing or empty value, and any window-reset consequence; production or published workflow content is read-only, and every edit routes through a development or draft copy plus an explicit promotion decision.",
        ),
        ProcedureCheck(
            _CHECK_EXPERIMENT,
            ("treatment_control", "assignment_unit", "assignment_stickiness", "exposure_unit", "exposure_definition", "primary_metric", "guardrail_metrics", "holdout_rationale", "minimum_runtime", "data_health_checks", "pause_rollback_conditions", "approval_state"),
            "Require sticky assignment, exposure defined as actual treatment display or receipt rather than send or eligibility, exactly one primary metric, at least one guardrail, a holdout rationale, a minimum runtime, data-health checks, and pause/rollback conditions; approval_state stays unapproved until a named human approves.",
        ),
        ProcedureCheck(
            _CHECK_READOUT,
            ("eligible_count", "assigned_count", "attempted_count", "delivered_count", "displayed_count", "acted_count", "outcome_count", "exposure_evidence", "contact_pressure_state", "repeated_contact_count", "channels", "denominator_status", "freshness_status", "sample_ratio_status", "cross_exposure_status", "instrumentation_status", "overlap_status", "step_outcomes", "step_trace_status", "analysis_run_state", "analysis_observed_at", "analysis_delay_status", "evidence_refs", "causal_claim_status", "disposition"),
            "Require a separate `lifecycle_growth_exposure_evidence/v1` companion with the bound audience/safety policies, eligibility/exclusion checks, assignment identity/count, reconciled populations, observed repeated-contact pressure and experiment-overlap checks, and per-channel reach/failure accounting. Missing evidence means HOLD, not zero or ship; configuration alone cannot supply it. Fill eligible, assigned, attempted, reached, and converted populations only from supplied observations, keeping delivery and action separate. Partial delivery requires review and channel failures retain their reasons; an independently justified rollback outranks missing launch evidence. Pause interpretation on sample-ratio mismatch, cross-exposure, stale data, broken instrumentation, or overlapping interventions; disposition must be exactly one of `ship`, `rollback`, `review`, or `insufficient_data`. Record every conditional step as `matched` or `skipped` with its own reason and status, never its evaluated values; a missing or failed best-effort step trace is not delivery evidence and must not turn a send into a failure. Name the analysis run as exactly one of `not_started`, `queued`, `running`, `completed`, `failed`, `canceled`, or `unknown` with the time that state was observed; elapsed time never rewrites the state.",
        ),
        ProcedureCheck(
            _CHECK_HANDOFF,
            ("action_class", "target_owner", "approver", "evidence_refs", "timing", "stop_conditions", "analysis_cancellation", "approval_state", "readiness", "disposition"),
            "Each proposed action must name its class (`connector`, `content`, `analytics`, `product`, `implementation`), owner, approver, evidence refs, timing, and stop conditions; readiness is HOLD while any prior check holds or approval is missing, and no delivery, display, action, outcome, or causal claim may appear without observed evidence. A cancellation or status-reconciliation handoff names the exact run and its scope, and keeps three states apart: the prepared request, which stays `prepared_not_observed`; an observed provider acknowledgement; and an observed terminal cancellation, which alone may back a `canceled` run state.",
        ),
    ),
    procedure_steps=(
        ProcedureStep(
            "lifecycle_define_target_behavior", "analysis", (_INPUT_OBJECTIVE, _INPUT_EVENTS, _INPUT_OWNER),
            (_BRIEF,), (_CHECK_TARGET,),
            "Name the lifecycle stage, the value-bearing behavior to move, its supplied baseline and window, the observed evidence behind the problem, competing hypotheses, non-goals, and the owner before proposing any message or product treatment.",
        ),
        ProcedureStep(
            "lifecycle_scope_audience_triggers", "analysis", (_INPUT_SEGMENT, _INPUT_EVENTS),
            (_AUDIENCE,), (_CHECK_AUDIENCE,),
            "Define the stable identity key, canonical entry and exit events with their semantics, exclusions, denominator, idempotency key, re-entry policy, and collision policy; record any unknown as a HOLD rather than assuming it.",
        ),
        ProcedureStep(
            "lifecycle_check_safety_eligibility", "validation", (_INPUT_SEGMENT, _INPUT_SURFACES, _INPUT_CONSENT),
            (_SAFETY,), (_CHECK_SAFETY,),
            "Order suppression precedence above legal and tenant constraints, user preferences, channel eligibility, quiet hours, and locale, then set global and per-campaign frequency budgets; record the throttle grouping key, resolved value, scope, and fallback so distinct recipients or tenants never share one window; treat production workflow content as read-only and route edits to a draft with an explicit promotion decision; fail closed when any eligibility input is missing.",
            on_fail=ProcedureBail(
                still_stands=('lifecycle_growth_brief/v1', 'audience_trigger_policy/v1'),
                downgrade_to='unresolved',
                handback='Return the unresolved lifecycle_safety_policy/v1 with missing consent, suppression, channel eligibility, frequency budgets, or throttle scope named; keep launch on HOLD.',
            ),
        ),
        ProcedureStep(
            "lifecycle_design_experiment", "production", (_INPUT_OBJECTIVE, _INPUT_EVENTS, _INPUT_SURFACES, _INPUT_BUDGET, _INPUT_OWNER),
            (_EXPERIMENT,), (_CHECK_TARGET, _CHECK_EXPERIMENT),
            "Specify treatment and control, sticky assignment and exposure units, the actual-exposure definition, one primary metric, guardrails, holdout rationale, minimum runtime, data-health checks, pause and rollback conditions, and an approval state that a named human must set before any launch handoff.",
            on_fail=ProcedureBail(
                still_stands=('lifecycle_growth_brief/v1', 'audience_trigger_policy/v1', 'lifecycle_safety_policy/v1'),
                downgrade_to='tentative',
                handback='Return the tentative growth_experiment_plan/v1 with missing assignment, actual-exposure definition, metric, guardrail, runtime, or rollback checks flagged; keep approval unapproved.',
            ),
        ),
        ProcedureStep(
            "lifecycle_prepare_measurement_readout", "validation", (_INPUT_EVENTS, _INPUT_BUDGET, _INPUT_OWNER),
            (_READOUT,), (_CHECK_READOUT,),
            "Lay out eligible, assigned, attempted, delivered, displayed, acted, and outcome stages with denominator and freshness checks. Supply the separate exposure-evidence companion to evaluate or prepare; unknown audience, assignment, contact pressure, overlap, or channel accounting holds expansion. First-launch preparation needs observed audience/reachability/contact checks, not invented treatment counts. Keep causal-claim status separate, list each conditional step as matched or skipped with a redacted reason, and record the analysis run's state and observation time alongside any delay. Record `ship`, `rollback`, `review`, or `insufficient_data` without forcing a decision on thin data.",
            on_fail=ProcedureBail(
                still_stands=('lifecycle_growth_brief/v1', 'audience_trigger_policy/v1', 'lifecycle_safety_policy/v1', 'growth_experiment_plan/v1'),
                downgrade_to='unresolved',
                handback='Return the unresolved growth_measurement_readout/v1 with missing exposure evidence, denominator, freshness, overlap, channel, or analysis-run checks named; keep counts unknown, not zero.',
            ),
        ),
        ProcedureStep(
            "lifecycle_validate_handoff", "validation", _ALL_INPUTS,
            (_HANDOFF,),
            (_CHECK_TARGET, _CHECK_AUDIENCE, _CHECK_SAFETY, _CHECK_EXPERIMENT, _CHECK_READOUT, _CHECK_HANDOFF),
            "Propose connector, content, analytics, product, or implementation actions with owner, approver, evidence refs, timing, and stop conditions; prepare any cancellation or status-reconciliation request against the exact named run and leave it `prepared_not_observed` until a provider result is observed; return HOLD readiness while any check holds, approval is missing, or the latest analysis run is still in flight, route validated product changes to `product-brief`, and never report a send, display, action, outcome, cancellation, or causal effect that was not observed.",
            on_fail=ProcedureBail(
                still_stands=('lifecycle_growth_brief/v1', 'audience_trigger_policy/v1', 'lifecycle_safety_policy/v1', 'growth_experiment_plan/v1', 'growth_measurement_readout/v1'),
                downgrade_to='unresolved',
                handback='Return the unresolved growth_handoff_disposition/v1 with blocked actions, missing owners or approvals, and the exact analysis run needing status reconciliation; leave requests prepared_not_observed.',
            ),
        ),
    ),
    artifact_expectations=(
        "prepared lifecycle-growth plan and readout, as metadata-only records with safe references, when a wrapper captures them",
    ),
    safety_rules=(
        "Fail closed: unknown consent, suppression, frequency eligibility, event semantics, identity, denominator, or decision owner returns HOLD and blocks a launch-ready handoff.",
        "Consent and suppression come only from supplied records; product usage or the absence of an opt-out never implies either.",
        "Do not claim a message was sent, a flag was changed, a treatment was displayed, a user acted, an outcome moved, or an experiment succeeded without observed provider, runtime, or data evidence.",
        "Delivery and click counts are not product or revenue impact; a causal claim needs a valid observed experiment or another named identification method.",
        "Retain bounded metadata and safe references only; never store user identity, event payloads, message bodies, consent records, or transcripts in durable artifacts.",
        "Treat small samples, novelty effects, seasonality, concurrent interventions, and inconsistent event semantics as blockers or stated uncertainty, not as results.",
        "A throttle window is identified by its configured key or expression plus the resolved value, scoped to a recipient or tenant; a resolved value is never re-read as a second key, a missing static value stays ungrouped, and an empty dynamic value falls back to the default window.",
        "Per-step matched and skipped outcomes carry a reason and status but never evaluated values or secrets; a step trace is best-effort diagnostics, not delivery evidence, and its absence must not block or fail a send.",
        "Production or published workflow content is view-only in prepared guidance; mutations go to a development or draft copy, then an explicit promotion decision, and only an observed provider result proves the promotion happened.",
        "A missing analysis result is not proof that no analysis is running; name the run state and the time it was observed, and never report a queued or running analysis as failed, canceled, absent, or complete.",
        "Elapsed time is a delay warning measured against a supplied service expectation, never evidence about a run; no fixed staleness cutoff may overwrite an observed in-flight state, and analysis-job runtime, experiment minimum runtime, and source-data freshness stay three separate questions.",
        "While the latest observed run is queued or running, do not start or recommend another analysis; reconcile the existing work first, and select the newest in-flight run rather than the newest run of any kind.",
        "A cancellation or status-reconciliation handoff is prepared, never performed: it names the exact run and scope, stays `prepared_not_observed`, and only an observed provider result may record acceptance or a terminal cancellation.",
    ),
    quality_tier="decision-gated",
    quality_bar=(
        "Define the value-bearing behavior and its baseline before any campaign or treatment is proposed.",
        "Separate assignment from actual exposure, and eligible, attempted, delivered, displayed, acted, and outcome stages from one another.",
        "Keep copy, supplied-data calculation, recurring scheduling, external sends, and PRD work with their owning workflows.",
        "Require a named human approval before any launch handoff and observed evidence before any delivery or outcome claim.",
    ),
    why_this_exists="`lifecycle-growth` exists so audience eligibility, consent and frequency safety, sticky exposure, causal measurement, and the stop decision travel together in one plan instead of being assembled ad hoc from analysis, copy, scheduling, and connector work.",
    do_not_use_when=(
        "The user only wants a one-off message, email, banner, or push copy rewrite with no audience, experiment, or decision; use `content-operator`.",
        "The user wants generic exploration or calculation over a supplied cohort, retention, conversion, or segment table with no journey or experiment to design; use `data-analysis`.",
        "The user wants a recurring schedule, cron, or digest cadence for an already-decided operation rather than a lifecycle intervention; use `automation-blueprint`.",
        "The user asks to send a message, change a feature flag, create a segment, or start an experiment in a provider now; use `connector-operator` with explicit authorization and observed results.",
        "The user needs a PRD, prioritization frame, or roadmap for a product change rather than a journey or experiment; use `product-brief`.",
    ),
    final_checklist=(
        "The target behavior, baseline, eligible audience, safety policy, experiment design, readout, and decision owner are named or marked HOLD.",
        "Prepared plan, human approval, observed delivery or display, observed user action, observed outcome, and causal claim are reported as separate states.",
        "The readout disposition is exactly `ship`, `rollback`, `review`, or `insufficient_data`, and every proposed handoff names its owning workflow, approver, and stop conditions.",
    ),
    recovery_notes=(
        "If consent, suppression, identity, event semantics, denominator, or the decision owner is unknown, return HOLD with the missing fields and ask for the one input that unblocks the smallest next step.",
        "If provider or data evidence for delivery, display, action, or outcome is unavailable, keep every readout stage not_observed and set the disposition to `insufficient_data` or `review` rather than `ship`.",
        "If a readout is missing, ask for the analysis run state and its observation time before concluding anything: a queued or long-running analysis holds for reconciliation, while failed, canceled, and never-started runs each need a different next step.",
    ),
    good_example=SkillExample(
        prompt="Our day-7 retention dropped for new workspace admins; design an in-app onboarding journey and a holdout experiment so we know whether it works.",
        expected="Prepare the brief, audience trigger policy, safety policy, experiment plan with sticky assignment and actual exposure, a readout scaffold, and an approval-gated handoff disposition.",
        why="The request spans lifecycle stage, audience, treatment, and causal measurement, which is the whole lifecycle-growth loop rather than one sibling's slice.",
    ),
    bad_example=SkillExample(
        prompt="Send the re-engagement push to every inactive user tonight.",
        expected="Route to `connector-operator` with explicit authorization, or return HOLD if consent, suppression, and frequency eligibility are unknown.",
        why="An immediate external send is a connector action, and lifecycle-growth never sends or claims delivery.",
    ),
    progressive_disclosure=True,
    situations=(
        "users sign up but never come back",
        "improve onboarding activation",
        "win back churned users",
        "in-app message experiment",
        "increase trial to paid conversion",
        "retention a/b test",
    ),
)
