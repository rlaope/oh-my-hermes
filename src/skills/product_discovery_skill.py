"""Canonical catalog data for the `product-discovery-validation` workflow (issue #1375).

This module holds one ``SkillDefinition`` and nothing else. It is the canonical
installed source imported by ``catalog_definitions.py``: no routing logic,
artifact builders, or validators live here. Use the canonical
`omh runtime workflow-artifact product-discovery-validation <operation>` interface
for metadata-only builds, gates, and handoffs.

Concept-level sources, adapted with attribution and without copying code:

- GitLab Product Development Flow, handbook revision ``4165803c`` (MIT):
  a validation track separated from build, with a problem gate before solution
  work.
- Mycelium ``8e958f82`` (MIT): evidence source classes, external-human gates,
  falsification propagation, precommitted assumption tests, and the
  audience-before-build invariant that an unknown audience may be investigated
  but must not cross the build boundary.
- Claude Code Discover ``a414fc7a`` (MIT): explicit hypothesis states, the
  smallest disconfirming test, hard budgets, and honest inconclusive results.
- Product Pipeline Public ``a0997741`` (MIT): persistent hypotheses, evidence
  typing, decision history, and contradiction flags.
- PM Skills ``18468a95`` (MIT): assumption categories, past-behavior
  interviews, demand tests, and beachhead/ICP framing.

None of those projects' hooks, schemas, runtimes, or vendor integrations are
adopted here.
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

SKILL_NAME = "product-discovery-validation"

# Required inputs. Every member has one ExpertQuestion and is referenced by at
# least one procedure step; the procedure validator enforces both.
_INPUT_PROBLEM = "problem hypothesis"
_INPUT_SEGMENT = "target segment"
_INPUT_EVIDENCE = "known evidence and current alternatives"
_INPUT_OWNER = "decision owner"
_INPUT_BUDGET = "learning budget and deadline"
_INPUT_CRITERIA = "success, failure, and stop criteria"

# Versioned artifact names, exactly as issue #1375 lists them.
_ARTIFACT_FRAME = "discovery_decision_frame/v1"
_ARTIFACT_LEDGER = "discovery_evidence_ledger/v1"
_ARTIFACT_PLAN = "customer_discovery_plan/v1"
_ARTIFACT_PORTFOLIO = "assumption_test_portfolio/v1"
_ARTIFACT_RECEIPT = "discovery_decision_receipt/v1"
_ARTIFACT_GTM = "initial_gtm_hypothesis/v1"

_ALL_INPUTS = (
    _INPUT_PROBLEM,
    _INPUT_SEGMENT,
    _INPUT_EVIDENCE,
    _INPUT_OWNER,
    _INPUT_BUDGET,
    _INPUT_CRITERIA,
)

DEFINITION = SkillDefinition(
    SKILL_NAME,
    "Unvalidated early product idea: test whether a customer problem, segment, and business hypothesis deserve product investment, ending in kill, pivot, persevere, or inconclusive before any PRD.",
    (
        "product-discovery-validation",
        "product discovery validation",
        "product discovery",
        "customer discovery",
        "customer discovery plan",
        "zero to one validation",
        "validate the problem before building",
        "problem solution interview",
        "customer interview guide",
        "riskiest assumption test",
        "assumption test portfolio",
        "kill pivot persevere",
        "kill or pivot decision",
        "willingness to pay test",
        "business hypothesis validation",
        "is this idea worth building",
    ),
    "Use when a founder or product owner brings an early idea and needs the problem, segment, value proposition, and business hypothesis framed, evidence-typed, and tested to an explicit discovery decision before a PRD, prototype, or delivery plan exists.",
    category="planning",
    phase="product-discovery-validation",
    hermes_role="retained-cognition",
    delegation_boundary="retained-catalog-intent",
    handoff_policy=(
        "Keep decision framing, evidence classification, assumption ranking, test precommitment, and the discovery decision in Hermes. "
        "A prepared plan, ledger, portfolio, or receipt is not participant recruitment, an interview, a survey, a payment, a prototype, a PRD, code, or a launch. "
        "Prepare a `product-brief` handoff only from a `persevere` receipt the decision owner accepted; route a single empirical prototype question to `decision-prototype`; reach `idea-to-deploy` only after the resulting product brief and plan are accepted."
    ),
    required_inputs=_ALL_INPUTS,
    expert_questions=(
        ExpertQuestion(
            _INPUT_PROBLEM,
            "Which customer problem or opportunity do you believe exists, for whom, and what would you expect to observe if it were false?",
            "어떤 고객 문제 또는 기회가 존재한다고 보시며, 누구에게 해당하고, 그 가설이 틀렸다면 무엇이 관찰될 것으로 예상하시나요?",
        ),
        ExpertQuestion(
            _INPUT_SEGMENT,
            "Which target segment, buyer versus user roles, and recruitable participant criteria define who must show the problem, or is that audience still unknown?",
            "어떤 목표 세그먼트, 구매자와 사용자 구분, 모집 가능한 참여자 기준이 이 문제를 보여야 하는 대상을 정의하나요, 아니면 그 대상이 아직 미정인가요?",
        ),
        ExpertQuestion(
            _INPUT_EVIDENCE,
            "Which evidence already exists, from which source class and date, and which current alternatives or workarounds do those people use today?",
            "이미 확보된 근거는 무엇이고 출처 유형과 날짜는 어떠하며, 그 사람들이 지금 사용하는 대안이나 우회 방법은 무엇인가요?",
        ),
        ExpertQuestion(
            _INPUT_OWNER,
            "Who owns the kill, pivot, persevere, or inconclusive decision, and who must accept a handoff to a product brief?",
            "킬, 피벗, 지속, 미결 결정의 책임자는 누구이며, 제품 브리프로의 인계는 누가 승인해야 하나요?",
        ),
        ExpertQuestion(
            _INPUT_BUDGET,
            "What learning budget in time, money, and participant count applies, and by which date must the decision be made?",
            "시간, 비용, 참여자 수 기준의 학습 예산은 얼마이며, 어느 날짜까지 결정을 내려야 하나요?",
        ),
        ExpertQuestion(
            _INPUT_CRITERIA,
            "Which observed conditions would count as success, failure, or a stop before evidence is gathered?",
            "근거를 수집하기 전에 어떤 관찰 조건을 성공, 실패, 중단으로 간주할지 정해 두셨나요?",
        ),
    ),
    expected_outputs=(
        _ARTIFACT_FRAME,
        _ARTIFACT_LEDGER,
        _ARTIFACT_PLAN,
        _ARTIFACT_PORTFOLIO,
        _ARTIFACT_RECEIPT,
        _ARTIFACT_GTM,
    ),
    procedure_checks=(
        ProcedureCheck(
            "discovery_decision_frame_check",
            (
                "problem_hypothesis",
                "segment",
                "target_segment_definition",
                "current_alternatives",
                "decision",
                "constraints",
                "owner",
                "learning_budget",
                "kill_criteria",
                "disposition",
            ),
            "PASS only when every frame field is supplied by the user or marked unknown; HOLD when the decision, owner, learning budget, or kill criteria are missing, and never infer them. Record `target_segment_definition` as recruitable, behaviorally observed, unknown, synthetic-only, or non-recruitable; an unknown, synthetic-only, or non-recruitable audience keeps discovery framing and evidence planning open while it blocks solution work, and never invent a persona to close it.",
        ),
        ProcedureCheck(
            "discovery_evidence_class_check",
            (
                "source_class",
                "safe_reference",
                "observation_date",
                "segment",
                "observation",
                "direction",
                "confidence_limits",
                "unresolved_inconsistency",
                "pointer_status",
            ),
            "Label every item as external-human, behavioral-data, internal-stakeholder, secondary-research, synthetic, or inferred; record direction as supporting or contradicting; assign no confidence from source class alone; keep a source pointer a pointer, not a fresh observation.",
        ),
        ProcedureCheck(
            "discovery_customer_reentry_check",
            (
                "participant_criteria",
                "interview_guide_focus",
                "consent_privacy_constraints",
                "bias_controls",
                "human_task_handoff",
                "evidence_reentry_contract",
                "transcript_exclusion",
            ),
            "The guide must ask about past behavior, current workarounds, switching costs, and observed commitments, not praise or future intent; refuse simulated personas or model-generated answers as participants; raw recordings, transcripts, and contact data stay outside durable artifacts.",
        ),
        ProcedureCheck(
            "discovery_problem_gate_check",
            (
                "problem_gate_state",
                "supporting_refs",
                "contradicting_refs",
                "gate_reason",
                "audience_gate",
                "missing_audience_evidence",
                "solution_work_permitted",
            ),
            "Set `problem_gate_state` to validated, refuted, or inconclusive from external-human or behavioral-data entries only; the supporting entries must come from the same target segment the frame names. `solution_work_permitted` is true only when the gate is validated and `audience_gate` is defined, so refuted, inconclusive, or an unknown, synthetic-only, or non-recruitable audience never advances to a solution, PRD, prototype-as-validation, or coding handoff; name the missing audience evidence as the next task instead.",
        ),
        ProcedureCheck(
            "discovery_assumption_precommit_check",
            (
                "assumption_category",
                "decision_impact",
                "evidence_gap",
                "rank",
                "smallest_disconfirming_test",
                "success_condition",
                "failure_condition",
                "inconclusive_condition",
                "segment_sample",
                "deadline",
                "cost",
                "owner",
                "evidence_reentry",
            ),
            "Rank each value, usability, feasibility, viability, go-to-market, or ethics assumption by decision impact multiplied by evidence gap; every test must carry precommitted success, failure, and inconclusive conditions plus segment, deadline, cost, owner, and evidence re-entry before any observation is accepted.",
        ),
        ProcedureCheck(
            "discovery_decision_receipt_check",
            (
                "decision",
                "precommitted_criteria",
                "observed_evidence",
                "confidence_limits",
                "rejected_paths",
                "residual_risks",
                "next_route",
                "promotion_guard",
            ),
            "Decision must be kill, pivot, persevere, or inconclusive; missing external evidence, a refuted problem, unresolved contradiction, an expired test, an inconclusive result, or an audience that is unknown, synthetic-only, or non-recruitable must not produce persevere or a `product-brief`, `decision-prototype`, or coding route; rejected and falsified hypotheses are preserved, and no raw transcript is replayed.",
        ),
        ProcedureCheck(
            "discovery_gtm_hypothesis_check",
            (
                "beachhead_segment",
                "buyer_user_distinction",
                "current_alternative",
                "value_proposition",
                "pricing_wtp_hypothesis",
                "initial_channel",
                "first_cohort",
                "learning_metrics",
                "evidence_basis",
            ),
            "Every field is a labeled hypothesis with its evidence basis; pricing, willingness-to-pay, and market-size figures require an observed source or behavioral evidence with explicit assumptions, and an unsupported field stays unknown instead of a generic ratio.",
        ),
    ),
    procedure_steps=(
        ProcedureStep(
            "discovery_frame_decision",
            "analysis",
            (_INPUT_PROBLEM, _INPUT_SEGMENT, _INPUT_OWNER, _INPUT_BUDGET, _INPUT_CRITERIA),
            (_ARTIFACT_FRAME,),
            ("discovery_decision_frame_check",),
            "Write the decision the discovery must inform, the problem hypothesis, segment, known current alternatives, constraints, owner, learning budget, and kill criteria before touching any evidence.",
        ),
        ProcedureStep(
            "discovery_classify_evidence",
            "analysis",
            (_INPUT_EVIDENCE, _INPUT_SEGMENT),
            (_ARTIFACT_LEDGER,),
            ("discovery_evidence_class_check",),
            "Enter each supplied item with its source class, safe reference, date, segment, observation, direction, and confidence limits; flag contradictions as unresolved inconsistency rather than resolving them by preference.",
        ),
        ProcedureStep(
            "discovery_plan_customer_reentry",
            "production",
            (_INPUT_SEGMENT, _INPUT_EVIDENCE, _INPUT_BUDGET),
            (_ARTIFACT_PLAN,),
            ("discovery_customer_reentry_check",),
            "Prepare participant criteria, a past-behavior interview guide, consent and privacy constraints, bias controls, the human task that recruits and interviews, and the contract for how bounded summaries re-enter the ledger; OMH contacts nobody.",
            on_fail=ProcedureBail(
                still_stands=('discovery_decision_frame/v1', 'discovery_evidence_ledger/v1'),
                downgrade_to='tentative',
                handback='Return the tentative customer_discovery_plan/v1 with missing participant criteria, past-behavior prompts, consent, bias controls, or evidence re-entry fields flagged for correction.',
            ),
        ),
        ProcedureStep(
            "discovery_gate_problem",
            "validation",
            (_INPUT_PROBLEM, _INPUT_EVIDENCE, _INPUT_CRITERIA),
            (_ARTIFACT_FRAME,),
            ("discovery_evidence_class_check", "discovery_problem_gate_check"),
            "Compare ledger entries against the precommitted criteria and record the problem gate as validated, refuted, or inconclusive, admitting only entries observed in the framed target segment; when it is not validated, or when the audience is unknown, synthetic-only, or non-recruitable, stop solution and MVP work and name the customer or audience evidence still missing.",
            on_fail=ProcedureBail(
                still_stands=('discovery_decision_frame/v1', 'discovery_evidence_ledger/v1', 'customer_discovery_plan/v1'),
                downgrade_to='unresolved',
                handback='Return the discovery_decision_frame/v1 as unresolved with missing target-segment human or behavioral evidence and the customer_discovery_plan/v1; keep solution work blocked.',
            ),
        ),
        ProcedureStep(
            "discovery_rank_assumptions",
            "production",
            (_INPUT_PROBLEM, _INPUT_SEGMENT, _INPUT_EVIDENCE, _INPUT_OWNER, _INPUT_BUDGET, _INPUT_CRITERIA),
            (_ARTIFACT_PORTFOLIO,),
            ("discovery_assumption_precommit_check",),
            "List the assumptions by category, score decision impact and evidence gap, and select for each top-ranked assumption the cheapest disconfirming test that could change the decision, with its precommitted conditions and bounded budget; a prototype is one optional instrument routed to `decision-prototype`, never validation by itself.",
            on_fail=ProcedureBail(
                still_stands=('discovery_decision_frame/v1', 'discovery_evidence_ledger/v1', 'customer_discovery_plan/v1'),
                downgrade_to='tentative',
                handback='Return the tentative assumption_test_portfolio/v1 with unranked assumptions or missing success, failure, inconclusive, segment, budget, owner, and evidence re-entry conditions flagged.',
            ),
        ),
        ProcedureStep(
            "discovery_draft_gtm_hypothesis",
            "production",
            (_INPUT_PROBLEM, _INPUT_SEGMENT, _INPUT_EVIDENCE),
            (_ARTIFACT_GTM,),
            ("discovery_gtm_hypothesis_check",),
            "Draft the beachhead segment, buyer versus user, current alternative, value proposition, pricing or willingness-to-pay hypothesis, one initial channel, first cohort, and learning metrics, each tied to its evidence basis or marked unknown.",
            on_fail=ProcedureBail(
                still_stands=('discovery_decision_frame/v1', 'discovery_evidence_ledger/v1', 'customer_discovery_plan/v1', 'assumption_test_portfolio/v1'),
                downgrade_to='tentative',
                handback='Return the tentative initial_gtm_hypothesis/v1 with unsupported pricing, willingness-to-pay, or market-size fields left unknown and each missing evidence basis named.',
            ),
        ),
        ProcedureStep(
            "discovery_validate_decision_receipt",
            "validation",
            _ALL_INPUTS,
            (_ARTIFACT_RECEIPT,),
            (
                "discovery_decision_frame_check",
                "discovery_evidence_class_check",
                "discovery_customer_reentry_check",
                "discovery_problem_gate_check",
                "discovery_assumption_precommit_check",
                "discovery_decision_receipt_check",
                "discovery_gtm_hypothesis_check",
            ),
            "Record the decision against the precommitted criteria and observed evidence, with confidence limits, rejected paths, residual risks, and the next route; a `persevere` receipt hands `product-brief` the validated problem, segment, MVP learning boundary, residual risks, and GTM hypotheses without transcript replay.",
            on_fail=ProcedureBail(
                still_stands=('discovery_decision_frame/v1', 'discovery_evidence_ledger/v1', 'customer_discovery_plan/v1', 'assumption_test_portfolio/v1', 'initial_gtm_hypothesis/v1'),
                downgrade_to='unresolved',
                handback='Return an unresolved discovery_decision_receipt/v1 naming unmet precommitted criteria, contradictions, rejected paths, and missing audience evidence; block persevere and product handoff.',
            ),
        ),
    ),
    artifact_expectations=(
        "prepared discovery decision frame, evidence ledger, customer discovery plan, assumption test portfolio, decision receipt, and GTM hypothesis when a wrapper captures them",
    ),
    safety_rules=(
        "Do not recruit or contact participants, record interviews, run surveys, scrape communities, buy ads, launch fake doors, accept payments, build a prototype, write a PRD, write code, or deploy anything from this workflow.",
        "Synthetic personas, model-generated interview answers, secondary summaries, prototypes without representative-user observation, and unsupported market-size figures cannot satisfy a customer-validation gate.",
        "Interview praise, stated purchase intent, a waitlist signup, a finished prototype, or one passed experiment is not product-market fit; state what each signal can and cannot establish.",
        "Founder-market fit and strategic preference may inform the decision but never substitute for target-customer evidence.",
        "An unknown, synthetic-only, or non-recruitable target segment blocks a solution, PRD, prototype-as-validation, or coding handoff; discovery framing, the customer discovery plan, and evidence work continue while it does.",
    ),
    quality_tier="decision-gated",
    quality_bar=(
        "Separate the decision frame, typed evidence, customer re-entry plan, ranked assumptions, and the receipt so each can be reviewed alone.",
        "Keep every kill, pivot, persevere, or inconclusive claim tied to precommitted criteria and observed evidence.",
    ),
    why_this_exists="`product-discovery-validation` gives an early idea a bounded, evidence-typed path to a kill, pivot, persevere, or inconclusive decision so `product-brief` consumes validated inputs instead of judging raw discovery itself.",
    do_not_use_when=(
        "The user needs market, competitor, pricing, or customer research on named sources without a discovery decision to make; use `research-brief`.",
        "The user is clarifying their own request, requirements, or preferences rather than testing a customer problem with external people; use `deep-interview`.",
        "The user needs a company or product strategy decision across existing options with evidence already in hand; use `strategy-brief`.",
        "The problem, segment, and evidence are already validated and accepted and the user wants a PRD or prioritization; use `product-brief`.",
        "An accepted product brief and plan exist and the user wants implementation, QA, and release gates; use `idea-to-deploy`.",
        "The user has one falsifiable technical or empirical question a disposable prototype can answer; use `decision-prototype`.",
    ),
    good_example=SkillExample(
        prompt="I think freelance designers struggle to chase late invoices. Before we write a PRD, help me test whether this is worth building.",
        expected="Frame the decision and kill criteria, classify the existing evidence, plan past-behavior customer interviews, rank the riskiest assumptions with precommitted tests, and stop at an explicit kill, pivot, persevere, or inconclusive receipt.",
        why="The request is a pre-PRD discovery decision about a customer problem and segment, not research on named sources, requester clarification, or a PRD.",
    ),
    bad_example=SkillExample(
        prompt="Write the PRD for our invoice-chasing feature; the interviews already confirmed the problem.",
        expected="Route to `product-brief` and ask for the accepted discovery receipt or evidence rather than rerunning discovery.",
        why="Validated, accepted evidence with a PRD request belongs to the PRD owner, not to discovery.",
    ),
    final_checklist=(
        "The problem gate state is recorded as validated, refuted, or inconclusive with the external-human or behavioral-data refs that decided it, all observed in the framed target segment.",
        "The target segment is explicit enough to recruit or tied to observed behavioral data before any solution, PRD, prototype, or coding output leaves this workflow.",
        "Every assumption test in the portfolio carries its precommitted success, failure, inconclusive, segment, deadline, cost, owner, and evidence re-entry fields.",
        "The receipt names kill, pivot, persevere, or inconclusive, preserves rejected paths, and routes to `product-brief` only from an accepted persevere.",
        "Every artifact is reported as prepared; interviews, tests, and prototypes stay not_observed until re-entered evidence exists.",
    ),
    recovery_notes=(
        "If external-human or behavioral-data evidence is absent, hold the problem gate at inconclusive and hand the customer discovery plan to a human owner instead of filling the gap with personas.",
        "If a test passes its deadline or budget without meeting a precommitted condition, record inconclusive with the residual risk and let the decision owner choose a new budget or a kill.",
        "If the target segment is unknown, synthetic-only, or non-recruitable, keep the discovery frame and customer discovery plan and report defining a recruitable or behaviorally observed audience as the next evidence task.",
        "If a pivot changes the problem or segment, open a new decision frame and carry the falsified hypotheses forward as rejected paths.",
    ),
    progressive_disclosure=True,
    situations=(
        "is this startup idea worth building",
        "customer interviews to validate a problem",
        "will people pay for this",
        "should we pivot",
        "test demand before writing a PRD",
    ),
)
