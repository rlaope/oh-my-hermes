from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import lru_cache
import re

from ..skills.catalog import SkillDefinition, builtin_definitions, routable_definitions
from .domain_signals import (
    DomainOperatorOverride,
    DomainRouteSignal,
    excluded_specialist_domain_skills,
    specialist_domain_operator_override,
    specialist_domain_route_signal,
)
from .intent import scrub_diagnostic_status_text
from .localization import normalized_phrase, prepare_routing_text, routing_tokens
from .visual_qa_cues import contains_cue_phrase
from .missed_route import is_missed_route_feedback
from .omh_help import is_omh_docs_question
from .trigger_language_packs import (
    ORIGIN_USER,
    TriggerLanguagePack,
    load_user_trigger_language_packs,
    merged_holdback_tokens,
    merged_trigger_phrases,
    shipped_trigger_language_packs,
)
from .policy import (
    PUBLIC_PLUGIN_CONNECTOR_ALIAS_PHRASES,
    PUBLIC_PLUGIN_CONNECTOR_READINESS_CONTEXT_PHRASES,
    RoutingGuardRule,
    SKILL_SCOUT_CANDIDATE_ALIAS_PHRASES,
    SKILL_SCOUT_CANDIDATE_BLOCKER_PHRASES,
    SKILL_SCOUT_CANDIDATE_INTENT_PHRASES,
    _explicit_skill_candidate_is_negated,
    active_routing_guard_rules,
    explicit_skill_invocation,
    is_explicit_one_off_request,
    jit_learn_guard_applies,
    media_input_operator_guard_applies,
    ops_observability_external_blocked,
    ops_observability_generic_metrics_blocked,
)


_STOPWORDS = {
    "the",
    "and",
    "are",
    "as",
    "for",
    "in",
    "is",
    "of",
    "or",
    "to",
    "with",
    "that",
    "this",
    "when",
    "use",
    "task",
    "request",
    "workflow",
    "skill",
    "agent",
    "hermes",
    "해줘",
    "해주세요",
    "줘",
    "부탁",
    "정리해줘",
}
_FALLBACK_SKILLS = ("oh-my-hermes", "plan", "deep-interview")
_FALLBACK_WHY = "No strong catalog metadata match; start with general routing/planning guidance."
_GUARDRAIL_CANDIDATE_INJECTION_IDS = frozenset(
    {
        "adversarial_qa_before_generic_help",
        "coding_progress_status_before_clarify",
        "deep_interview_before_generic_plan",
        "direct_coding_task_before_fallback",
        "doctor_health_before_skill_catalog",
        "executor_runtime_readiness_before_generic_advice",
        "feedback_before_coding",
        "gateway_intent_before_feedback_triage",
        # A greenfield request scores 0 on `deep-interview` by construction - the
        # user types "build a todo list", never "interview me" - so without
        # injection the guard's boost has no candidate to land on.
        "greenfield_build_before_generic_picker",
        "hermes_coding_team_before_generic_clarification",
        # A well-formed "I need to learn X before <deadline>" request scores on
        # incident/review words instead of the learning target, so the guard
        # needs a candidate to boost.
        "jit_learn_before_generic_research_or_review",
        "github_event_ops_before_generic_planning",
        "github_issue_intake_before_event_ops_or_feedback",
        "live_info_operator_before_generic_current_facts",
        "research_brief_before_wiki",
        "loop_goal_before_generic_clarification",
        "materials_package_before_report_or_clarify",
        "memory_curation_before_generic_clarification",
        "media_input_operator_before_generic_content_or_direct",
        "named_coding_agent_delivery_before_advisor_or_feedback",
        "ops_observability_before_generic_loop",
        "release_claim_review_before_file_lookup",
        "safe_feature_change_before_generic_plan",
        "img_summary_before_materials_or_delivery",
        "paper_learning_before_materials_or_research_ops",
        "source_finder_before_generic_web_research",
        "toolbelt_readiness_before_generic_or_visual_fallback",
        "voice_operator_before_generic_clarification",
        "browser_operator_before_generic_clarification",
        "missed_workflow_research_recovery",
        "missed_workflow_operating_record_recovery",
        "product_shaping_before_ops_review",
        "workflow_learning_before_skill_management",
        "omh_quality_improvement_loop_before_feedback_triage",
    }
)
_COMMAND_TRIGGER_PHRASES = frozenset(("/", "./", "/o", "./o", "/om", "./om", "/omh", "./omh", "/skills", "./skills"))
_COMMAND_TRIGGER_PATTERNS = {
    phrase: re.compile(rf"(?<![\w./-]){re.escape(phrase)}(?![\w./-])")
    for phrase in _COMMAND_TRIGGER_PHRASES
}
_TOOLBELT_READINESS_GUARD_ID = "toolbelt_readiness_before_generic_or_visual_fallback"

_ECOSYSTEM_IDENTITY_CONNECTOR_TRIGGER_NOISE = frozenset(
    {
        "agentchat",
        "agy",
        "antigravity",
        "clawsocial",
        "crustocean",
        "genai",
        "keychain",
        "mailbox",
        "matrix",
        "miniverse",
        "oauth",
        "oci",
        "oracle",
        "pairing",
        "websocket",
        "windy",
        "windymail",
    }
)
_GENERIC_TRIGGER_TOKENS = frozenset(
    normalized_phrase(token)
    for token in (
        "같이",
        "것",
        "지금",
        "하고",
        "작업",
        "자연스럽게",
        "좀",
        "이거",
        "그거",
        "요즘",
        "한번",
        "내",
        "문제",
        "자료",
        "확인해줘",
        "정보",
        "계속",
        "상태",
        "write",
        "status",
        "running",
        "natural",
        "naturally",
        "make",
        "check",
    )
)
_RISKY_REFACTOR_GUARD_ID = "risky_refactor_before_cleanup"
_RISKY_REFACTOR_FOLLOWUP_ONLY_SKILLS = frozenset({"ai-slop-cleaner"})
_RISKY_REFACTOR_FOLLOWUP_SCORE_CAP = 7
_RISKY_REFACTOR_FOLLOWUP_MATCHED = "guard:risky_refactor_followup_after_plan"
_RISKY_REFACTOR_FOLLOWUP_WHY = (
    "Follow-up only: use cleanup after a reviewed plan locks scope, risks, and verification."
)
_RISKY_REFACTOR_FOLLOWUP_GUIDANCE_PREFIX = (
    "Treat this as a follow-up only after an accepted reviewed plan; do not present cleanup "
    "as the first action for risk-marked refactoring language. "
)
# Complete phrases that mean the adversarial round explicitly. Without the
# direct match these lose to `plan`, which scores 18 on any sentence containing
# the word: "adversarial planning for the redis migration" gave `plan` +5 name,
# +2 phase, +3 trigger token and +6 metadata against this workflow's +6 phrase.
# The boost is sized above that band and below the guard rules', so an explicit
# adversarial request wins while a bare planning request is untouched.
_ADVERSARIAL_CONSENSUS_EXPLICIT_PHRASES = tuple(
    normalized_phrase(phrase)
    for phrase in (
        "adversarial-consensus",
        "adversarial consensus",
        "adversarial planning",
        "adversarial plan review",
        "red team this plan",
        "red-team this plan",
        "red team the proposal",
        "red-team the proposal",
        "multi-perspective review",
        "multiple perspectives",
        "independent perspectives",
        "attack this proposal",
        "poke holes in this",
        "hyperplan",
        "적대적 검토",
        "다관점 검토",
        "여러 관점에서 검토",
        "레드팀 검토",
        "이 계획 반박",
        "허점 찾아",
    )
)
# Complete phrases that mean building an LLM feature, not discussing one. The
# workflow's own tokens are held back by `_WHOLE_PHRASE_ONLY_TRIGGER_TOKENS`
# below, so without this direct match a full trigger phrase scores only the +6
# phrase credit and loses to whatever else the sentence mentions. The boost is
# sized above the ordinary name/phase/metadata band and below the guard rules',
# so an explicit code-edit request on an LLM component still reaches the coding
# lane rather than this design pass.
#
# Only intent-bearing phrases are listed. The catalog also triggers on the bare
# subject nouns `rag pipeline` and `golden set` (and their Korean forms), and
# they are deliberately NOT boosted here: with the boost they carried
# "refactor the rag pipeline module", "rename the rag pipeline package", and
# "delete the golden set fixture" -- ordinary code edits that name an LLM
# component and belong to the coding lane. Left at the +6 phrase credit those
# sentences route on their verb, while "build a rag pipeline" still lands here.
_LLM_APP_DEV_EXPLICIT_PHRASES = tuple(
    normalized_phrase(phrase)
    for phrase in (
        "llm-app-dev",
        "llm app development",
        "llm application development",
        "build an llm app",
        "build an llm feature",
        "llm feature development",
        "build a rag pipeline",
        "retrieval augmented generation",
        "structured output schema",
        "json schema output",
        "prompt versioning",
        "llm eval suite",
        "llm 앱 개발",
        "llm 애플리케이션 개발",
        "llm 기능 개발",
        "rag 파이프라인 구축",
        "구조화된 출력 스키마",
        "프롬프트 버전 관리",
        "llm 평가셋",
    )
)
_FAILURE_SIGNAL_AUDIT_EXPLICIT_PHRASES = tuple(
    normalized_phrase(phrase)
    for phrase in (
        "failure-signal-audit",
        "failure signal audit",
        "silent failure hunter",
        "silent failure audit",
        "hidden failure audit",
        "false green audit",
        "실패 신호 감사",
        "실패 신호",
    )
)
_ACCESSIBILITY_AUDIT_EXPLICIT_PHRASES = tuple(
    normalized_phrase(phrase)
    for phrase in (
        "accessibility-audit",
        "accessibility audit",
        "a11y audit",
        "a11y architect",
        "wcag audit",
        "wcag 2.2",
        "wcag 2.2 aa",
        "screen reader",
        "keyboard navigation",
        "focus order",
        "focus trap",
        "target size",
        "touch target",
        "접근성 감사",
        "접근성 검토",
        "접근성 검사",
        "스크린리더",
        "키보드 내비게이션",
        "포커스 순서",
        "터치 타깃",
    )
)
_BUILD_FAILURE_TRIAGE_EXPLICIT_PHRASES = tuple(
    normalized_phrase(phrase)
    for phrase in (
        "build-failure-triage",
        "build failure triage",
        "build failure",
        "build fix",
        "build failed",
        "build failing",
        "compile error",
        "compilation error",
        "typecheck failed",
        "typecheck failure",
        "type check failed",
        "tsc failed",
        "lint failed",
        "lint failure",
        "test failed",
        "test failure",
        "tests failed",
        "ci failed",
        "ci failure",
        "github actions failed",
        "pr checks failed",
        "pr check failure",
        "dco failed",
        "dco failure",
        "pytest failed",
        "pytest failure",
        "npm build failed",
        "cargo build failed",
        "빌드 실패",
        "빌드 고쳐",
        "컴파일 에러",
        "타입체크 실패",
        "테스트 실패",
        "CI 실패",
        "체크 실패",
        "DCO 실패",
    )
)
_BUILD_FAILURE_TRIAGE_OVERRIDE_PHRASES = tuple(
    normalized_phrase(phrase)
    for phrase in (
        "build-failure-triage",
        "build failure triage",
        "triage",
        "minimal fix",
        "minimal-fix",
        "minimal safe fix",
        "root cause",
        "root-cause",
        "diagnose",
        "classify",
        "failure log",
        "log into",
        "원인",
        "분류",
        "최소 수정",
    )
)
_FIXED_OR_PASS_PHRASES = tuple(
    normalized_phrase(phrase)
    for phrase in (
        "fixed",
        "resolved",
        "passed",
        "passing",
        "green",
        "now passes",
        "now passing",
        "고쳤",
        "수정 완료",
        "해결",
        "통과했",
        "통과됨",
        "통과 완료",
    )
)
_VERIFY_OR_MERGE_READY_PHRASES = tuple(
    normalized_phrase(phrase)
    for phrase in (
        "verify",
        "verification",
        "verification gate",
        "verify before merge",
        "merge readiness",
        "merge-ready",
        "ready to merge",
        "before merge",
        "evidence matrix",
        "fresh rerun",
        "rerun evidence",
        "검증",
        "머지 가능",
        "머지 전",
    )
)
_BUILD_OR_CHECK_CONTEXT_PHRASES = tuple(
    normalized_phrase(phrase)
    for phrase in (
        "build",
        "compile",
        "typecheck",
        "type check",
        "tsc",
        "lint",
        "test",
        "tests",
        "pytest",
        "ci",
        "github actions",
        "pr check",
        "pr checks",
        "check",
        "checks",
        "dco",
        "failure",
        "failed",
        "failing",
        "빌드",
        "컴파일",
        "타입체크",
        "테스트",
        "체크",
        "실패",
    )
)
_HARNESS_SESSION_INVENTORY_INTENT_PHRASES = (
    "harness-session-inventory",
    "harness session inventory",
    "session inventory",
    "session adapter",
    "session adapters",
    "mcp inventory",
    "mcp config inventory",
    "mcp drift",
    "harness drift",
    "connector drift",
    "worktree inventory",
    "worktree lifecycle",
    "operator inventory",
    "control pane inventory",
    "codex session inventory",
    "claude code session inventory",
    # omo-runtime hosts; bare "pi" belongs to Raspberry-Pi routing, so pi only
    # appears inside longer phrases here.
    "senpi session inventory",
    "opencode session inventory",
    "omo runtime session inventory",
    "pi session inventory",
    "find previous coding session",
    "recover coding session",
    "previous codex coding session",
    "previous senpi coding session",
    "previous pi coding session",
    "coding session recall",
    "세션 인벤토리",
    "지난 코딩 세션",
    "코딩 세션 복구",
    "세션 기억 복구",
    "하네스 드리프트",
    "mcp 인벤토리",
    "mcp 설정 드리프트",
    "워크트리 인벤토리",
    "커넥터 드리프트",
)
_HARNESS_SESSION_INVENTORY_INTENT_TOKENS = frozenset(
    {"inventory", "drift", "adapter", "adapters", "lifecycle", "인벤토리", "드리프트"}
)
_HARNESS_SESSION_INVENTORY_CONTEXT_TOKENS = frozenset(
    {
        "mcp",
        "harness",
        "harnesses",
        "session",
        "sessions",
        "connector",
        "connectors",
        "worktree",
        "worktrees",
        "config",
        "configs",
        "codex",
        "claude",
        "hermes",
        # omo-runtime hosts. Bare "pi" cannot appear here: routing tokens are
        # three characters or longer, so it is unreachable as a token.
        "senpi",
        "opencode",
        "omo",
        "wrapper",
        "하네스",
        "세션",
        "커넥터",
        "워크트리",
    }
)


@dataclass(frozen=True)
class RecommendationPolicy:
    next_action: str
    evidence_boundary: str
    wrapper_guidance: str


@dataclass(frozen=True)
class _PreparedDefinition:
    definition: SkillDefinition
    policy: RecommendationPolicy
    trigger_phrases: tuple[str, ...]
    command_trigger_phrases: tuple[str, ...]
    plain_trigger_phrases: tuple[str, ...]
    trigger_tokens: frozenset[str]
    name_phrase: str
    description_phrase: str
    use_when_phrase: str
    category_phrase: str
    phase_phrase: str
    metadata_tokens: frozenset[str]


_DEFAULT_POLICY = RecommendationPolicy(
    next_action="show_workflow_guidance",
    evidence_boundary="Routing guidance is not execution evidence.",
    wrapper_guidance="Route conservatively and show the missing decision before claiming work started.",
)
_SKILL_POLICIES = {
    "meta-router": RecommendationPolicy(
        next_action="present_meta_route",
        evidence_boundary="A meta-routing decision names the workflow(s) to run; it is not execution, review, CI, or merge evidence.",
        wrapper_guidance="Reason over the /omh remainder, consult the live catalog with omh recommend --json, exclude meta-router itself, and present the chosen workflow or chain with its evidence boundary.",
    ),
    # `llm-app-dev` sits in the `delivery` category for its reasoning demand and
    # role, but the category policy is idea-to-deploy's app delivery loop --
    # idea, decision, plan, deploy, monitor. That is the wrong card: this
    # workflow never reaches deploy, and its output is a build handoff with rail
    # decisions, not a release stage rail.
    "llm-app-dev": RecommendationPolicy(
        next_action="prepare_llm_app_build",
        evidence_boundary=(
            "An LLM app build handoff is not a provider call, an observed eval run, a token or cost measurement, "
            "implementation, review, CI, or merge evidence; telemetry no run reported stays null and is never estimated."
        ),
        wrapper_guidance=(
            "Show the rail decisions, the output schema and its repair path, the prompt artifact layout, and the eval "
            "deliverables; keep model responses, eval results, token counts, and cost unobserved until a run reports them."
        ),
    ),
    "cancel": RecommendationPolicy(
        next_action="cancel",
        evidence_boundary="Cancellation is observed only after the wrapper records the state change.",
        wrapper_guidance="Stop the active workflow state in the wrapper; do not create a plan, handoff, or execution claim.",
    ),
    "operating-rhythm": RecommendationPolicy(
        next_action="prepare_operating_record",
        evidence_boundary="An operating rhythm record is not evidence that a meeting, scrum, sprint, retro, decision, or action item happened.",
        wrapper_guidance="Prepare or update the local operations artifact; mark decisions and actions as prepared until supplied notes or acceptance are observed.",
    ),
    "report-package": RecommendationPolicy(
        next_action="prepare_report_package",
        evidence_boundary="A report package or PPT-ready outline is not source-review completion, stakeholder approval, presentation delivery, or binary PPTX export evidence.",
        wrapper_guidance="Prepare a Markdown/JSON report outline from supplied inputs; keep missing numbers and approvals explicit.",
    ),
    "materials-package": RecommendationPolicy(
        next_action="prepare_material_package",
        evidence_boundary=(
            "A material package is not binary export, render QA, formula recalculation, stakeholder approval, "
            "delivery, or external upload evidence."
        ),
        wrapper_guidance=(
            "Prepare a material_artifact/v1 plan with target formats, source inputs, assumptions, missing inputs, "
            "QA ladder, and an executor-neutral generation handoff when a binary file is needed."
        ),
    ),
    "img-summary": RecommendationPolicy(
        next_action="prepare_visual_prompt_card",
        evidence_boundary=(
            "A prepared image-card brief is not generated image, visual QA, sharing, posting, attachment, or delivery evidence."
        ),
        wrapper_guidance=(
            "Prepare visual_prompt_card/v1 with short image-safe copy, generation prompt, negative prompt, "
            "language/aspect metadata, and visual_observation/v1 evidence requirements. Show generate action only "
            "when image_generation_capability/v1 is connected; otherwise route to image_generation_setup/v1 to choose "
            "a GPT image tool, existing Hermes connector, generic image tool, or prompt-only path."
        ),
    ),
    "apple-design": RecommendationPolicy(
        next_action="prepare_design_orchestration",
        evidence_boundary=(
            "An Apple design brief is prepared guidance, not Apple certification, implementation, accessibility PASS, visual QA, "
            "browser evidence, review, CI, deployment, or merge evidence."
        ),
        wrapper_guidance=(
            "Prepare apple_design_brief/v1 with mode, explicit visual target, platform convention, target/version/framework/input/surface/state, current tokens, "
            "applicable source records, observation-versus-hypothesis findings, remediation owners, and visual_status not_observed unless supplied evidence proves otherwise. For product visuals, prepare apple_visual_direction/v1 and name the available image-generator, renderer, or frontend execution boundary without claiming generation or rendering; when image generation is unavailable, use an authorized available renderer or selected coding owner before prompt-only preparation."
        ),
    ),
    "design-quality-gate": RecommendationPolicy(
        next_action="prepare_design_quality_gate",
        evidence_boundary=(
            "A design quality gate is not implementation, export, publication, visual QA, or proof that the rendered result "
            "beats the comparison baseline until observed render evidence exists."
        ),
        wrapper_guidance=(
            "Prepare design_quality_gate/v1 with references, comparative_quality_rubric/v1, surface_quality_matrix/v1, "
            "content and layout QA, downstream generation route, and observed-only visual QA requirements."
        ),
    ),
    "design-orchestration": RecommendationPolicy(
        next_action="prepare_design_orchestration",
        evidence_boundary=(
            "A prepared design orchestration contract is not executor selection, implementation, browser rendering, accessibility PASS, "
            "visual QA, review, CI, deployment, or merge evidence until matching observations exist."
        ),
        wrapper_guidance=(
            "Prepare design_orchestration/v1 with bounded intent, opaque context references, deliberate direction, existing-lane composition, "
            "executor_selection_required, and visual_verdict not_observed. Route narrowed work to design-quality-gate, frontend, accessibility-audit, or visual-qa."
        ),
    ),
    "frontend": RecommendationPolicy(
        next_action="prepare_frontend_handoff",
        evidence_boundary=(
            "A frontend brief is not implementation, browser verification, Lighthouse/Core Web Vitals, accessibility, "
            "deployment, or visual QA evidence until observed executor or wrapper evidence exists."
        ),
        wrapper_guidance=(
            "Prepare frontend_design_brief/v1 with design_system_contract/v1, route/state/viewport matrix, "
            "accessibility/performance expectations, implementation handoff, and visual_qa_required/v1."
        ),
    ),
    "backend": RecommendationPolicy(
        next_action="prepare_backend_handoff",
        evidence_boundary=(
            "A backend service contract is not implementation, a running service, an applied migration, an integration "
            "run, load evidence, or deployment until observed executor or wrapper evidence exists."
        ),
        wrapper_guidance=(
            "Prepare backend_service_contract/v1 with auth_boundary_map/v1, error_path_table/v1, "
            "response_shape_contract/v1, schema_migration_plan/v1 when storage is touched, and a "
            "backend_implementation_handoff/v1 naming the stack and its first reference."
        ),
    ),
    "rust": RecommendationPolicy(
        next_action="prepare_rust_handoff",
        evidence_boundary=(
            "A Rust change contract is not compilation, clippy cleanliness, a passing test, a Miri run, a sanitizer "
            "run, or a loom-style concurrency run until observed executor or wrapper evidence exists."
        ),
        wrapper_guidance=(
            "Prepare rust_change_contract/v1 opening with ub_escalation_verdict/v1, then ownership_shape/v1, "
            "error_and_api_contract/v1, rust_gate_list/v1, and ub_discipline_checklist/v1 as blocking items whenever "
            "the change touches unsafe, raw pointers, FFI, MaybeUninit, or a lock-free primitive."
        ),
    ),
    "native-debugging": RecommendationPolicy(
        next_action="prepare_native_debug_plan",
        evidence_boundary=(
            "A native debugging plan is not a reproduction, a breakpoint hit, a read value, a backtrace, a root cause, "
            "or a fix until observed executor or wrapper evidence exists."
        ),
        wrapper_guidance=(
            "Prepare native_fault_statement/v1, hypothesis_set/v1 with at least three hypotheses on distinct axes, "
            "distinguishing_observation_plan/v1, and debugger_session_plan/v1 naming the DAP adapter, breakpoints, "
            "watchpoints, threads, frames, and values the executor reads at each stop."
        ),
    ),
    "accessibility-audit": RecommendationPolicy(
        next_action="prepare_accessibility_audit",
        evidence_boundary=(
            "An accessibility audit is not remediation, implementation, WCAG PASS, screen-reader compatibility, "
            "keyboard proof, browser proof, visual QA, CI, release-readiness, merge-readiness, or merge evidence."
        ),
        wrapper_guidance=(
            "Prepare accessibility_audit_plan/v1 with WCAG 2.2 criteria, semantic_structure_review/v1, "
            "focus_and_keyboard_trace/v1, screen_reader_announcement_map/v1, target_size_and_pointer_review/v1, "
            "contrast_and_reflow_review/v1, and a remediation or visual-qa route when evidence is missing."
        ),
    ),
    "visual-qa": RecommendationPolicy(
        next_action="prepare_visual_qa",
        evidence_boundary=(
            "A visual QA plan is not PASS evidence; PASS requires fresh rendered captures after the last relevant edit "
            "plus recorded diff/review, browser interaction, console/network, click-path, and keyboard/accessibility findings "
            "for the covered surfaces when those checks are in scope."
        ),
        wrapper_guidance=(
            "Prepare visual_qa_plan/v1 with capture freshness rules, render_capture_manifest/v1 requirements, "
            "browser_interaction_trace/v1, console_network_health/v1, click_path_state_trace/v1, "
            "accessibility_keyboard_trace/v1, visual_diff_evidence/v1, dual_oracle_visual_review/v1, CJK/text checks, "
            "and a PASS/REVISE/BLOCK verdict."
        ),
    ),
    "workspace-audit": RecommendationPolicy(
        next_action="prepare_workspace_audit",
        evidence_boundary=(
            "A workspace audit is not setup repair, config mutation, secret validation, runtime load, skill mutation, "
            "executor dispatch, implementation, or verification evidence."
        ),
        wrapper_guidance=(
            "Prepare workspace_audit_plan/v1, observed surface_inventory/v1, capability_gap_matrix/v1, "
            "redacted config_security_findings/v1, and a downstream workflow recommendation."
        ),
    ),
    "production-audit": RecommendationPolicy(
        next_action="prepare_production_audit",
        evidence_boundary=(
            "A production audit is not deploy, live traffic, security scan, monitoring health, support readiness, "
            "incident closure, rollback execution, implementation, CI, or merge evidence."
        ),
        wrapper_guidance=(
            "Prepare readiness_matrix/v1, release_gate_verdict/v1, rollback_and_monitoring_plan/v1, "
            "risk_register/v1, and missing production evidence before GO/HOLD/BLOCK."
        ),
    ),
    "verification-gate": RecommendationPolicy(
        next_action="prepare_verification_gate",
        evidence_boundary=(
            "A verification gate plan is not command execution, test pass, review, CI, DCO, merge-readiness, "
            "or merge evidence; stale or missing checks block PASS."
        ),
        wrapper_guidance=(
            "Prepare verification_matrix/v1, record observed_check_results/v1 only from fresh outputs, "
            "and issue claim_verdict/v1 as PASS, HOLD, or BLOCK."
        ),
    ),
    "build-failure-triage": RecommendationPolicy(
        next_action="prepare_build_failure_triage",
        evidence_boundary=(
            "A build failure triage plan is not a code fix, dependency install, command rerun, test pass, "
            "CI pass, DCO pass, review, merge-readiness, or merge evidence."
        ),
        wrapper_guidance=(
            "Prepare build_failure_triage_plan/v1, failure_log_digest/v1, failure_cluster_matrix/v1, "
            "root_cause_hypothesis_set/v1, minimal_fix_handoff/v1 when allowed, rerun_plan/v1, "
            "and build_failure_triage_verdict/v1."
        ),
    ),
    "agent-evaluation": RecommendationPolicy(
        next_action="prepare_agent_evaluation",
        evidence_boundary=(
            "An agent evaluation design is not proof that an executor ran, edited code, used tools, incurred cost, "
            "passed tests, or completed review."
        ),
        wrapper_guidance=(
            "Prepare paired_run_decision/v1; retain not_observed until authenticated persisted receipt evidence exists."
        ),
    ),
    "rules-distill": RecommendationPolicy(
        next_action="prepare_rules_distillation",
        evidence_boundary=(
            "A rules distillation candidate is not approved guidance, skill mutation, prompt mutation, docs change, "
            "memory mutation, implementation, verification, review, CI, or merge evidence."
        ),
        wrapper_guidance=(
            "Prepare rules_distillation_plan/v1, principle_candidate_set/v1, duplication_conflict_report/v1, "
            "review_queue/v1, and approved_patch_handoff/v1 only after review approval."
        ),
    ),
    "codebase-onboarding": RecommendationPolicy(
        next_action="prepare_codebase_onboarding",
        evidence_boundary=(
            "A codebase onboarding pack is not setup, dependency install, architecture proof for unobserved surfaces, "
            "executor dispatch, implementation, review, verification, CI, or merge evidence."
        ),
        wrapper_guidance=(
            "Prepare codebase_onboarding_plan/v1, repo_map/v1, reading_path/v1, domain_glossary/v1, "
            "risk_and_unknowns_map/v1, and first_task_runway/v1 from observed repo evidence."
        ),
    ),
    "codebase-uml": RecommendationPolicy(
        next_action="prepare_codebase_uml",
        evidence_boundary=(
            "A generated PlantUML source or render plan is prepared_not_observed; it is not a rendered image, an "
            "attachment, complete architecture, review, CI, or merge evidence."
        ),
        wrapper_guidance=(
            "Scope the view (package, --focus, or module), generate the source with `omh codegraph uml --output`, "
            "render with the plan's exact command, attach the PNG, and read the omissions legend back."
        ),
    ),
    "frontend-refactor": RecommendationPolicy(
        next_action="present_plan",
        evidence_boundary=(
            "A preview change plan or pass selection is prepared_not_observed; it is not an applied refactor, "
            "preserved behavior, test evidence, review, CI, or merge evidence."
        ),
        wrapper_guidance=(
            "Preview first: emit the impact-ordered change plan with per-change safety reasons and the "
            "characterization-test gate; apply is a separate explicit step for the selected executor lane."
        ),
    ),
    "refactor-plan": RecommendationPolicy(
        next_action="prepare_refactor_plan",
        evidence_boundary=(
            "A phase plan, files table, or reconnaissance map is prepared_not_observed; it is not implementation, "
            "migration, verification, review, CI, or merge evidence, and approval of the plan proves no phase ran."
        ),
        wrapper_guidance=(
            "Map affected files, boundaries, coupling, and blast radius from observed evidence, order the five "
            "contracts-first phases with per-phase verification and rollback, ship the files table, and stop at "
            "the approval gate."
        ),
    ),
    "codegraph-refresh": RecommendationPolicy(
        next_action="prepare_codegraph_refresh",
        evidence_boundary=(
            "A codegraph refresh plan is not command execution, artifact write, architecture proof, executor dispatch, "
            "implementation, review, CI, or merge evidence."
        ),
        wrapper_guidance=(
            "Prepare codegraph_refresh_plan/v1 with repo root, refresh depth, build/summary/handoff command choices, "
            "staleness_and_scope_report/v1, `.omh/codegraph/codegraph.json` write requirements, and observed-only "
            "omh_codegraph_summary/v1 or omh_codegraph_context/v1 evidence."
        ),
    ),
    "skill-scout": RecommendationPolicy(
        next_action="prepare_skill_scout",
        evidence_boundary=(
            "A skill scout report is not skill installation, external source trust, marketplace mutation, file copy, "
            "network retrieval, credential use, implementation, review, CI, or proof that a candidate is safe to adopt."
        ),
        wrapper_guidance=(
            "Prepare skill_scout_query/v1, local_skill_candidate_inventory/v1 when observed, "
            "external_skill_candidate_risk_review/v1 when observed, skill_adoption_decision_matrix/v1, "
            "and skill_scout_recommendation/v1 without installing, copying, or trusting candidates."
        ),
    ),
    "skill-health": RecommendationPolicy(
        next_action="prepare_skill_health",
        evidence_boundary=(
            "A skill health dashboard is not install/setup health, live skill execution success, automatic skill mutation, "
            "model training, verification, review, CI, or proof that future routing is fixed."
        ),
        wrapper_guidance=(
            "Prepare the skill health card with catalog/generated/reference surface status, "
            "observed-only failure clusters, pending amendment review, and top safe actions while routing setup "
            "health to doctor and mutation work to reviewed implementation."
        ),
    ),
    "context-budget-review": RecommendationPolicy(
        next_action="prepare_context_budget_review",
        evidence_boundary=(
            "A context budget review is not exact token usage, provider billing, runtime compaction, executor progress, "
            "or completion evidence."
        ),
        wrapper_guidance=(
            "Prepare context_budget_plan/v1, must_keep_context_pack/v1, summarization_checkpoint_plan/v1, "
            "budget_risk_register/v1, and overflow_recovery_route/v1 while preserving the full objective."
        ),
    ),
    "security-safety-review": RecommendationPolicy(
        next_action="prepare_security_safety_review",
        evidence_boundary=(
            "A security safety review is not vulnerability absence, scanner execution, dependency update, credential validity, "
            "sandbox proof, permission change, or remediation evidence. An explicit plugin_risk_audit/v1 result is not plugin "
            "safety approval, import, registration, activation, execution, dependency installation, network access, or CI evidence."
        ),
        wrapper_guidance=(
            "Prepare security_safety_review_plan/v1, threat_surface_map/v1, permission_and_secret_risk_matrix/v1, "
            "prompt_injection_risk_review/v1, safe_action_policy/v1, and remediation_handoff/v1 when needed. Prepare "
            "plugin_risk_audit/v1 only for one explicitly supplied local plugin directory."
        ),
    ),
    "instinct-ledger": RecommendationPolicy(
        next_action="prepare_instinct_ledger",
        evidence_boundary=(
            "An instinct ledger is not hook installation, automatic observation, model training, hidden memory mutation, "
            "skill mutation, prompt mutation, global promotion, import/export, or proof that future behavior changed."
        ),
        wrapper_guidance=(
            "Prepare instinct_ledger_plan/v1, atomic instinct_candidate/v1 items, project_instinct_scope_map/v1, "
            "instinct_promotion_review/v1, and instinct_export_review/v1 when requested while keeping raw observations, "
            "writes, imports, exports, and global promotion observed-only."
        ),
    ),
    "workflow-learning": RecommendationPolicy(
        next_action="audit_learning_readiness",
        evidence_boundary=(
            "A workflow learning trace, eval, audit, candidate, regression case, or export is process-review evidence only; "
            "it is not model training, skill mutation, workflow execution, verification, CI, merge, or proof that future behavior is fixed."
        ),
        wrapper_guidance=(
            "Show the workflow learning card: record trace, run eval, add regression case, audit readiness, export a redacted review bundle, "
            "and keep human-reviewed improvement separate from automatic self-modification."
        ),
    ),
    "automation-blueprint": RecommendationPolicy(
        next_action="prepare_scheduled_ops_blueprint",
        evidence_boundary=(
            "A scheduled ops blueprint is not host cron creation, Hermes automation enablement, gateway delivery, "
            "source retrieval, no-agent execution, plugin load, connector invocation, review, CI, or merge evidence."
        ),
        wrapper_guidance=(
            "Prepare hermes_ops_blueprint/v1 with schedule, delivery, silence, skill/context chain, and status-card "
            "copy; ask for missing runtime/delivery decisions and record observed evidence only when Hermes or the host runtime provides it."
        ),
    ),
    "research-department": RecommendationPolicy(
        next_action="prepare_research_department_plan",
        evidence_boundary=(
            "A research department plan is not observed source retrieval, synthesis-tool execution, knowledge-store writes, "
            "host cron creation, gateway delivery, conflict resolution, or verified briefing evidence."
        ),
        wrapper_guidance=(
            "Prepare research_department_plan/v1 with Scout, Analyst, and Briefer lanes, source_inbox/v1 buckets, "
            "briefing_status/v1 counts, knowledge-store and synthesis-tool preferences, and observed-only evidence requirements."
        ),
    ),
    "paper-learning": RecommendationPolicy(
        next_action="prepare_paper_learning",
        evidence_boundary=(
            "A paper learning card is not full PDF extraction, figure OCR, external citation checking, math validation, "
            "code reproduction, peer review, or proof that paper claims are true."
        ),
        wrapper_guidance=(
            "Prepare paper_learning_card/v1 with level choice, source_state, coverage ledger, section-by-section outline, "
            "and not-observed extraction/validation boundaries before presenting the explanation as complete."
        ),
    ),
    "ultraperf": RecommendationPolicy(
        next_action="prepare_ultraperf_loop",
        evidence_boundary=(
            "An ultraperf loop is not profiling, benchmark execution, measurement proof, code change, "
            "regression-test completion, review, CI, or merge evidence."
        ),
        wrapper_guidance=(
            "Name the baseline, evaluator command, hot-path hypothesis, reversible fix owner, re-measure step, "
            "and budget tolerance before claiming any performance improvement."
        ),
    ),
    "performance-goal": RecommendationPolicy(
        next_action="prepare_quality_performance_and_usability_review",
        evidence_boundary=(
            "A performance goal card is not proof that a runtime, tool, MCP server, CI job, or platform action ran; "
            "it is not performance proof, benchmark execution, latency proof, throughput proof, profiling evidence, "
            "code change, regression-test completion, review, or merge evidence."
        ),
        wrapper_guidance=(
            "Scope the metric, baseline, suspected hot path, safe optimization boundary, and verification commands before "
            "claiming any runtime or AI-token efficiency improvement."
        ),
    ),
    "inference-serving": RecommendationPolicy(
        next_action="prepare_inference_serving",
        evidence_boundary=(
            "An engine verdict, runbook, or benchmark plan is prepared_not_observed; it is not a running server, "
            "rollout evidence, a measured capacity claim, review, CI, or merge evidence."
        ),
        wrapper_guidance=(
            "Decide engine and quantization from the tables, prepare the gated deployment runbook with its "
            "verification commands, and design the benchmark with metrics, load shape, SLO, and metadata; report "
            "every step prepared or observed."
        ),
    ),
    "tech-debt-audit": RecommendationPolicy(
        next_action="prepare_tech_debt_audit",
        evidence_boundary=(
            "A debt ledger is prepared analysis; it is not a completed cleanup, a measured quality improvement, "
            "observed command evidence, review, CI, or merge evidence."
        ),
        wrapper_guidance=(
            "Orient from repo evidence, audit the named dimensions with file:line citations, rank findings by "
            "severity and effort with quick wins and the looks-bad-but-fine list, and reconcile "
            "RESOLVED/NEW/CARRIED against the previous ledger on rerun."
        ),
    ),
    "award-bar-score": RecommendationPolicy(
        next_action="prepare_award_bar_score",
        evidence_boundary=(
            "An award-bar score is a self-assessment against a published rubric; it is not a jury score, a "
            "placement, an award, rendered visual evidence, accessibility conformance, or a measured performance run."
        ),
        wrapper_guidance=(
            "Score UI, UX, and innovation separately with the rendered evidence each score was read from, compute "
            "the weighted total against the published threshold, name the binding constraint, and record any "
            "innovation move that costs an accessibility or performance budget as a tradeoff the user chooses."
        ),
    ),
    "model-optimization": RecommendationPolicy(
        next_action="run_hermes_research",
        evidence_boundary=(
            "A recognition probe, research synthesis, or drafted calibration is prepared_not_observed; it is not a "
            "routing change, benchmark execution, measured superiority, provider readiness, or merge evidence."
        ),
        wrapper_guidance=(
            "Probe recognition for each new model id first, research official docs before community harness reports "
            "with every finding labeled, then draft trait-to-counter calibration and name routing/pricing placement "
            "surfaces and the measurement close."
        ),
    ),
    "source-finder": RecommendationPolicy(
        next_action="prepare_source_finder_plan",
        evidence_boundary=(
            "A source finder plan is not web search, download, repository clone, file extraction, file hash verification, "
            "license verification, source correctness verification, or downstream processing evidence."
        ),
        wrapper_guidance=(
            "Prepare source_finder_plan/v1 with source_candidate_set/v1, source_acquisition_status/v1, "
            "observation provenance, not-evidence boundaries, and a downstream workflow recommendation."
        ),
    ),
    "jit-learn": RecommendationPolicy(
        next_action="prepare_learning_brief",
        evidence_boundary=(
            "A prepared learning brief is not observed source retrieval, link or currency verification, source "
            "consumption, learning, progress, application, or resolution of the user's original blocker."
        ),
        wrapper_guidance=(
            "Ask one confirmation question before research, even when the request looks complete, and resolve "
            "urgency, current level, and application window one question per turn. Confirm the target as "
            "`Learn X now so I can do/decide Y in context Z by T.`, then prepare a source-gated Markdown brief with "
            "Books, Podcasts, Creators, and Courses ranked by fit, authority, currency, time-to-first-value, and "
            "direct transfer rather than popularity."
        ),
    ),
    "reliability-review": RecommendationPolicy(
        next_action="prepare_reliability_review",
        evidence_boundary="A reliability review is not SLO pass, healthy error-budget, incident closure, remediation completion, verification, review, CI, or merge evidence.",
        wrapper_guidance="Collect service, SLO, incident, metric, and reference boundaries; create remediation handoffs only after an accepted fix direction exists.",
    ),
    "web-research": RecommendationPolicy(
        next_action="run_hermes_research",
        evidence_boundary=(
            "A web lookup route is not observed retrieval, page reading, claim verification, or coding handoff "
            "evidence; web_research_brief/v1 is prepared context."
        ),
        wrapper_guidance=(
            "Keep this in Hermes as one cited retrieval round: ask for the freshness window and version or "
            "jurisdiction scope, cite the source behind each claim with its retrieval date, and name the retrieval "
            "gap rather than answering a current-facts question from recall."
        ),
    ),
    "research": RecommendationPolicy(
        next_action="run_hermes_research",
        evidence_boundary=(
            "A research route is not observed source retrieval, repository reading, claim or license verification, "
            "implementation, or coding handoff evidence; deep_research_dossier/v1 is prepared decision context."
        ),
        wrapper_guidance=(
            "Keep this in Hermes as a source-backed research lane: ask for source boundaries, freshness, version "
            "scope, and declared depth; gather cited evidence, study reference implementations with pinned refs "
            "when the decision needs them, gate contested claims, and report retrieval gaps before any handoff."
        ),
    ),
    "ultraqa": RecommendationPolicy(
        next_action="dispatch_to_workflow",
        evidence_boundary="A QA workflow route is not observed scenario execution, verification, fix evidence, CI, or release readiness evidence.",
        wrapper_guidance="Run the QA workflow as a Hermes-owned review lane; report scenarios, observed checks, gaps, and any follow-up handoff separately.",
    ),
}
_SKILL_POLICIES.update(
    {
        # Both of these are `category="operator"`, and without an entry here an
        # operator skill falls through to `run_local_operator_check` -- the
        # doctor lane. Routing was correct while the REPLY was doctor's: asking
        # to turn memory off answered "I can check whether OMH is installed and
        # connected correctly." The coverage gates passed because they check
        # that a skill is registered, not that its reply is about that skill.
        "capability-toggle": RecommendationPolicy(
            next_action="apply_capability_toggle",
            evidence_boundary=(
                "A capability policy change records which OMH family surfaces this install offers; it is not "
                "Hermes reconfiguration, uninstall, execution, review, CI, or merge evidence."
            ),
            wrapper_guidance=(
                "Name the capability family and the requested state, list the workflows it withholds and the core "
                "skills it always retains, and state the command that reverses it. Never guess the family."
            ),
        ),
        "running-work-board": RecommendationPolicy(
            next_action="show_running_work_board",
            evidence_boundary=(
                "A running-work board is observed activity metadata; presence is not liveness, and it is not "
                "result, verification, review, CI, merge-readiness, or merge evidence."
            ),
            wrapper_guidance=(
                "Show one row per unit with its runtime and model, and print the literal unknown wherever nothing "
                "was observed. Never estimate a token count or claim an unfinished unit is still alive."
            ),
        ),
        "github-event-ops": RecommendationPolicy(
            next_action="prepare_github_event_ops_card",
            evidence_boundary="A GitHub event ops card is not webhook delivery, API mutation, label application, review completion, CI rerun, or fix execution evidence.",
            wrapper_guidance="Classify PR, issue, review, and CI events into triage/review/label/fix-handoff actions; record GitHub mutations only when observed.",
        ),
        "github-issue-intake": RecommendationPolicy(
            next_action="prepare_github_issue_intake",
            evidence_boundary=(
                "A prepared github_issue_intake/v1 package is not issue creation, label application, or any GitHub "
                "mutation evidence; only authorized-connector read-back of repository, author, title, body, labels, "
                "and URL is observed evidence."
            ),
            wrapper_guidance=(
                "Classify the report, ask at most three decision-changing questions, search duplicates, present the "
                "direction check, and require explicit confirmation before handing the scoped create_issue package "
                "to an authorized connector; with no connector, return the complete package plus an explicit blocker."
            ),
        ),
        "agent-board": RecommendationPolicy(
            next_action="prepare_agent_board_card",
            evidence_boundary="An agent board card is not proof that another Hermes target accepted, worked, heartbeat-ed, or completed.",
            wrapper_guidance="Show task, handoff, heartbeat, blocker, and completion states per target/thread; require target-specific evidence before advancing.",
        ),
        "memory-new": RecommendationPolicy(
            next_action="prepare_memory_new",
            evidence_boundary=(
                "A memory candidate is not an approved record or Hermes-native mutation. Hermes-native and external "
                "provider/vector context is not_omh_reviewed, can nominate a candidate only, and a configured Hermes "
                "runtime may transmit rendered OMH prefetch content in its model request."
            ),
            wrapper_guidance=(
                "Ask source class, target store, scope, and retention class. Then remember one bounded durable candidate; "
                "refuse secrets, raw logs, transcripts, prompt injection, and temporary progress; or defer uncertain "
                "source/scope/target/retention and external provider/vector content to review."
            ),
        ),
        "memory-sync": RecommendationPolicy(
            next_action="prepare_memory_sync",
            evidence_boundary=(
                "Memory-sync prompt guidance is not Hermes internal memory, MEMORY.md, USER.md, or skill-file mutation "
                "evidence; no OMH surface invokes, applies, or observes a native MEMORY.md/USER.md write, and a "
                "user-approved diff applied through Hermes's native memory tool is Hermes's own act, never OMH evidence."
            ),
            wrapper_guidance=(
                "Use English-canonical claim review with concise Korean help labels and preserved Korean routes. Prepare a "
                "native write diff only; keep not_omh_reviewed Hermes-native/provider/vector context from inheriting OMH approval."
            ),
        ),
        "decision-recall": RecommendationPolicy(
            next_action="show_rejected_decision_recall",
            evidence_boundary="Rejected-decision context is reviewed OMH-local context, not approved memory, Hermes memory, source freshness, or execution evidence.",
            wrapper_guidance="Scope a query to reviewed rejected candidates, preserve tags and stale policy, and keep recall separate from approved-memory writes or execution claims.",
        ),
        "gateway-intent-card": RecommendationPolicy(
            next_action="prepare_gateway_intent_card",
            evidence_boundary="A gateway intent card is not platform login, message send, thread mutation, attachment upload, or delivery evidence.",
            wrapper_guidance="Normalize origin, thread, delivery, silent-update, attachment, and status-update policy before any gateway action is claimed.",
        ),
        "executor-runtime-readiness": RecommendationPolicy(
            next_action="prepare_executor_runtime_readiness",
            evidence_boundary="Runtime readiness is not executor dispatch, plugin load, tool invocation, execution, review, CI, or merge evidence.",
            wrapper_guidance="Compare Codex, Claude Code, Hermes coding, and oh-my runtimes by tools, missing capabilities, credentials, and handoff mode.",
        ),
        "deliverable-package": RecommendationPolicy(
            next_action="prepare_deliverable_package",
            evidence_boundary="A deliverable package card is not binary generation, render QA, formula recalculation, approval, upload, attachment, or delivery evidence.",
            wrapper_guidance="Track prepared, generated, QA, approved, attached, and delivered states separately for PPT/PDF/XLSX/DOCX/HWP/Markdown outputs.",
        ),
        "voice-operator": RecommendationPolicy(
            next_action="prepare_voice_operator_card",
            evidence_boundary="A voice operator card is not speech recognition proof, mobile notification delivery, platform action, or accepted execution evidence.",
            wrapper_guidance="Turn terse voice/mobile requests into concise clarify, plan, status, handoff, or confirmation cards; require confirmation for risky actions.",
        ),
        "browser-operator": RecommendationPolicy(
            next_action="prepare_browser_operator_card",
            evidence_boundary=(
                "A browser operator card is not browser launch, login, credential validation, page mutation, "
                "form submission, scraping, screenshot capture, or successful interaction evidence."
            ),
            wrapper_guidance=(
                "Prepare browser_task_card/v1 with target URL, allowed actions, auth/credential boundary, "
                "destructive confirmation gate, observation manifest slots, and a stop condition before any "
                "browser interaction is claimed."
            ),
        ),
        "workspace-file-operator": RecommendationPolicy(
            next_action="prepare_workspace_file_operator_card",
            evidence_boundary=(
                "A workspace file operator card is not file read, write, copy, move, rename, delete, archive, "
                "permission change, upload, download, or destructive filesystem evidence."
            ),
            wrapper_guidance=(
                "Prepare workspace_file_task_card/v1 with path root, allowed operations, excluded paths, "
                "destructive confirmation gate, observation manifest slots, and a stop condition before any "
                "filesystem action is claimed."
            ),
        ),
        "command-operator": RecommendationPolicy(
            next_action="prepare_command_operator_card",
            evidence_boundary=(
                "A command operator card is not terminal launch, shell execution, package-manager action, test run, "
                "stdout/stderr capture, exit-code success, filesystem mutation, network access, or destructive command evidence."
            ),
            wrapper_guidance=(
                "Prepare command_task_card/v1 with command text, working directory, environment assumptions, "
                "timeout, safety gate, result manifest slots, and a stop condition before command execution is claimed."
            ),
        ),
        "connector-operator": RecommendationPolicy(
            next_action="prepare_connector_operator_card",
            evidence_boundary=(
                "A connector operator card is not connector availability, credential validation, API call, message send, "
                "ticket mutation, external write, webhook delivery, or provider success evidence."
            ),
            wrapper_guidance=(
                "Prepare connector_task_card/v1 with provider, target object or recipient, allowed action, "
                "payload summary, auth boundary, confirmation gate, result manifest slots, and a stop condition "
                "before external app execution is claimed."
            ),
        ),
        "live-info-operator": RecommendationPolicy(
            next_action="prepare_live_info_operator_card",
            evidence_boundary=(
                "A live information card is not provider availability, API access, live data retrieval, weather, "
                "market price, sports score, exchange-rate, time-zone, map, or place-result evidence."
            ),
            wrapper_guidance=(
                "Prepare live_info_task_card/v1 with domain, location or symbol, time window, provider preference, "
                "freshness boundary, units, source-quality rule, result manifest slots, and a stop condition before "
                "live data is claimed."
            ),
        ),
        "external-connector-readiness": RecommendationPolicy(
            next_action="prepare_external_connector_readiness",
            evidence_boundary=(
                "An external connector readiness card is not connector installation, credential validation, provider access, "
                "API invocation, multimodal capture, live-data retrieval, external mutation, cost authorization, "
                "or successful trial evidence."
            ),
            wrapper_guidance=(
                "Prepare external_connector_readiness_card/v1 with connector_capability_matrix/v1, "
                "auth_cost_boundary/v1, freshness and multimodal routing policies, fallback routes, "
                "connector_trial_manifest/v1 slots, and a stop condition before adoption or provider results are claimed."
            ),
        ),
        "prompt-import-readiness": RecommendationPolicy(
            next_action="prepare_prompt_import_readiness",
            evidence_boundary=(
                "A prompt import readiness card is not prompt file access, prompt parsing success, slash command "
                "registration, prompt mutation, command activation, imported prompt trust, or successful dry-run evidence."
            ),
            wrapper_guidance=(
                "Prepare prompt_import_readiness_card/v1 with prompt_source_inventory/v1, prompt_format_matrix/v1, "
                "argument_interpolation_policy/v1, slash_command_collision_report/v1, prompt_trust_review/v1, "
                "prompt_import_manifest/v1 slots, and a stop condition before importing or exposing prompt commands."
            ),
        ),
        "physical-device-readiness": RecommendationPolicy(
            next_action="prepare_physical_device_readiness",
            evidence_boundary=(
                "A physical device readiness card is not device discovery, network pairing, credential validation, "
                "slicer output, G-code safety, camera inspection, sensor reading, relay actuation, robot movement, "
                "heat command, print start, emergency stop test, or successful hardware trial evidence."
            ),
            wrapper_guidance=(
                "Prepare physical_device_readiness_card/v1 with device_safety_envelope/v1, "
                "hazard_and_actuator_inventory/v1, sensor_camera_gate_policy/v1, operator_approval_policy/v1, "
                "dry-run and emergency-stop policies, device_trial_manifest/v1 slots, and a stop condition before "
                "hardware readiness or device action claims are made."
            ),
        ),
        "content-operator": RecommendationPolicy(
            next_action="prepare_content_operator_card",
            evidence_boundary=(
                "A content operator card is not source retrieval, fact verification, hallucination-free copy, "
                "stakeholder approval, publishing, email/message sending, file export, delivery, or accepted-final-copy evidence."
            ),
            wrapper_guidance=(
                "Prepare content_task_card/v1 with source scope, audience, channel, language, tone, style guide, "
                "fact-risk, review gate, output manifest slots, and a stop condition before content quality or "
                "delivery claims are made."
            ),
        ),
        "media-input-operator": RecommendationPolicy(
            next_action="prepare_media_input_card",
            evidence_boundary=(
                "A media input card is not media access, file upload, download, transcript extraction, "
                "OCR output, screenshot text extraction, receipt fields, speech-to-text output, timestamp accuracy, "
                "copyright clearance, source retrieval, or media-summary correctness evidence."
            ),
            wrapper_guidance=(
                "Prepare media_input_task_card/v1 with media source, permission boundary, transcript or extraction "
                "availability, language, speaker, OCR/receipt fields, and timestamp requirements, summary method, "
                "result manifest slots, and a stop condition before media access, transcription, OCR, timestamp, "
                "or summary claims are made."
            ),
        ),
        "data-analysis": RecommendationPolicy(
            next_action="prepare_data_analysis_card",
            evidence_boundary=(
                "A data analysis card is not file extraction, query execution, chart generation, statistical proof, "
                "data correctness, numeric evidence, association, or causality."
            ),
            wrapper_guidance=(
                "Prepare data_analysis_task_card/v1 with dataset or corpus scope, schema or extraction method, "
                "relationship-claim boundary, method plan, result-evidence slots, and a stop condition before "
                "numeric, association, or causal findings are claimed."
            ),
        ),
        "toolbelt-readiness": RecommendationPolicy(
            next_action="prepare_toolbelt_readiness",
            evidence_boundary="A toolbelt readiness card is not MCP server installation, credential validation, API access, connector invocation, or successful workflow execution evidence.",
            wrapper_guidance="List required MCP/CLI/API/credential/connectors, observed availability, missing pieces, and setup or handoff next action.",
        ),
        "harness-session-inventory": RecommendationPolicy(
            next_action="prepare_harness_session_inventory",
            evidence_boundary=(
                "A harness session inventory is not host load, MCP tool-call, connector availability, executor dispatch, "
                "worktree cleanup, merge-conflict resolution, or session progress evidence."
            ),
            wrapper_guidance=(
                "Build a redacted inventory across Codex, Claude Code, Hermes, OpenCode, Cursor, wrapper sessions, "
                "MCP host configs, connector entries, and worktrees; report prepared, observed, stale, missing, "
                "and drifted slots separately before any runtime or cleanup claim."
            ),
        ),
        "ops-observability-card": RecommendationPolicy(
            next_action="prepare_ops_observability_card",
            evidence_boundary=(
                "An ops observability card is not billing truth, provider quota truth, live metric-provider access, "
                "complete tracing, performance proof, SLO pass, incident closure, remediation completion, or workflow completion evidence."
            ),
            wrapper_guidance=(
                "Report token/cost/latency/run-history telemetry and supplied external_metric_provider/v1 payloads "
                "as a command-board with clear local-estimate, provider-truth, connector, SLO, incident, and remediation boundaries."
            ),
        ),
        "run-efficiency": RecommendationPolicy(
            next_action="show_run_efficiency_report",
            evidence_boundary="A run efficiency report is supplied OMH-local metadata, not provider billing, cron, host, or performance proof beyond supplied local metadata.",
            wrapper_guidance="Render run_efficiency_report/v1 from supplied context-budget, surface-count, and timing metadata; keep provider, billing, cron, and host gaps explicit as not observed.",
        ),
        "provider-profile-posture": RecommendationPolicy(
            next_action="prepare_provider_profile_posture",
            evidence_boundary="Provider/profile posture is OMH-local preparation metadata; it is not credential validation, provider connectivity, model routing, payment/wallet, or host execution evidence.",
            wrapper_guidance="Prepare provider_profile_posture/v1 using capability and secret-presence metadata only; do not read secrets, call providers, validate credentials, route models, or create wallet/payment actions.",
        ),
        "agent-ops-review": RecommendationPolicy(
            next_action="prepare_agent_ops_review",
            evidence_boundary=(
                "An agent ops review card is not source retrieval, executor dispatch, coding progress, "
                "implementation, review, verification, CI, merge-readiness, merge, platform delivery, "
                "provider billing, or live runtime telemetry evidence."
            ),
            wrapper_guidance=(
                "Render a manager-facing quality and throughput card: workflow quality lanes, blockers, "
                "next actions, and throughput levers. Keep shell commands hidden from normal chat users and "
                "record only observed runtime/source/review evidence."
            ),
        ),
        "agent-debug": RecommendationPolicy(
            next_action="prepare_agent_debug",
            evidence_boundary=(
                "An agent debug report is not executor reset, hidden state mutation, tool repair, "
                "implementation, review, verification, CI, merge-readiness, merge, or proof that future loops are fixed."
            ),
            wrapper_guidance=(
                "Prepare agent_debug_report/v1: capture the failure pattern, recent tool or command loop, "
                "goal drift, context pressure, environment assumptions, root-cause hypothesis, smallest safe "
                "recovery action, and whether evidence improved or the run remains blocked."
            ),
        ),
        "failure-signal-audit": RecommendationPolicy(
            next_action="prepare_failure_signal_audit",
            evidence_boundary=(
                "A failure signal audit is not remediation, code modification, runtime repair, console/network pass, "
                "incident closure, verification, review, CI, merge-readiness, merge, or proof that hidden failures no longer exist."
            ),
            wrapper_guidance=(
                "Prepare failure_signal_audit_plan/v1 with scope, observed-only silent_failure_finding/v1 evidence, "
                "fallback_risk_matrix/v1, propagation_gap_map/v1, false_green_status_review/v1, and a remediation "
                "or visual-qa route when hidden failure signals require follow-up."
            ),
        ),
    }
)
_SKILL_POLICIES.update(
    {
        "finance-analysis": RecommendationPolicy(
            next_action="prepare_finance_analysis",
            evidence_boundary="A finance analysis is not authoritative accounting, ERP, bank, ledger, tax, payment, filing, approval, or financial decision evidence.",
            wrapper_guidance="Prepare period and source boundaries, variance assumptions, cash or close risks, decision questions, and a route to strategy-brief, data-analysis, or human finance review.",
        ),
        "people-ops": RecommendationPolicy(
            next_action="prepare_people_ops_brief",
            evidence_boundary="A people-operations brief is not candidate contact, evaluation, hiring, rejection, ATS, HRIS, policy ruling, or employment-status evidence.",
            wrapper_guidance="Prepare fair role criteria, a structured scorecard, evidence-based debrief template, process owners, and inclusion, privacy, policy, and evidence gaps.",
        ),
        "legal-compliance-review": RecommendationPolicy(
            next_action="prepare_legal_compliance_review",
            evidence_boundary="A legal and compliance review is not legal advice, counsel sign-off, compliance certification, contract execution, filing, regulator communication, approval, or policy mutation evidence.",
            wrapper_guidance="Prepare jurisdiction, authority, document-version and evidence boundaries, an issue matrix, ranked escalation questions, and a counsel or human-review route.",
        ),
        "support-operations": RecommendationPolicy(
            next_action="prepare_support_operations",
            evidence_boundary="A support-operations brief is not a sent reply, ticket mutation, refund, account action, escalation completion, or customer-outcome evidence.",
            wrapper_guidance="Prepare a customer-safe reply draft, severity and impact matrix, owned escalation path, and missing repro, account, entitlement, or approval evidence.",
        ),
        "curriculum-design": RecommendationPolicy(
            next_action="prepare_curriculum_design",
            evidence_boundary="A curriculum design is not LMS creation, learner enrollment, grading, certification, material publication, or learning-outcome evidence.",
            wrapper_guidance="Prepare learner and prerequisite assumptions, scope and sequence, assessment evidence, accessibility and adaptation questions, and a materials or human-review route.",
        ),
        "localization-review": RecommendationPolicy(
            next_action="prepare_localization_review",
            evidence_boundary="A localization review is not locale-file mutation, translation upload, publication, rendered-build validation, market approval, or regulatory conclusion evidence.",
            wrapper_guidance="Prepare locale and source-version context, glossary choices, a string issue matrix, review owners, acceptance criteria, and rendered-QA or legal-review gaps.",
        ),
        "sales-development": RecommendationPolicy(
            next_action="prepare_sales_development",
            evidence_boundary="A sales development brief is not observed company research, prospect contact, CRM mutation, opportunity creation, meeting booking, revenue, or progress evidence.",
            wrapper_guidance="Prepare account and buyer hypotheses, evidence gaps, qualification questions, value and objection framing, outreach-draft outline, and an owned non-executing next-step plan.",
        ),
        "product-brief": RecommendationPolicy(
            next_action="prepare_product_brief",
            evidence_boundary="A product brief is not stakeholder acceptance, Jira, Linear, or roadmap-system mutation, implementation, test evidence, delivery, or market-commitment evidence.",
            wrapper_guidance="Prepare the problem, user, evidence, metric, goal, non-goal, PRD, prioritization options, dependencies, acceptance shape, decision owner, and gated downstream route.",
        ),
    }
)


_CATEGORY_POLICIES = {
    "planning": RecommendationPolicy(
        next_action="present_plan",
        evidence_boundary="A recommendation or draft plan is not execution evidence.",
        wrapper_guidance="Show an Accept plan / Revise plan choice; keep Prepare handoff disabled until the plan is accepted.",
    ),
    "clarification": RecommendationPolicy(
        next_action="ask_clarification",
        evidence_boundary="A clarification question is not routing, planning, or execution evidence.",
        wrapper_guidance="Ask one blocking question in the same thread before selecting a workflow.",
    ),
    "research": RecommendationPolicy(
        next_action="run_hermes_research",
        evidence_boundary="Research guidance is not observed source retrieval, implementation, or verification evidence.",
        wrapper_guidance=(
            "Keep this in Hermes as source-backed research, name source boundaries and freshness, summarize "
            "observed evidence with citations, and report retrieval gaps before any later handoff."
        ),
    ),
    "strategy": RecommendationPolicy(
        next_action="prepare_strategy_brief",
        evidence_boundary="A strategy brief is not an accepted decision or implementation evidence.",
        wrapper_guidance=(
            "Prepare options, tradeoffs, and decision notes in Hermes; keep implementation handoff disabled "
            "until a decision creates explicit code work."
        ),
    ),
    "meeting": RecommendationPolicy(
        next_action="prepare_meeting_brief",
        evidence_boundary="A meeting brief is not evidence that a meeting happened or decisions were accepted.",
        wrapper_guidance=(
            "Prepare agenda, prompts, and a record template in Hermes; do not treat preparation as observed "
            "meeting outcomes."
        ),
    ),
    "triage": RecommendationPolicy(
        next_action="triage_feedback",
        evidence_boundary="Feedback triage is not a roadmap, implementation plan, or coding handoff by default.",
        wrapper_guidance=(
            "Cluster feedback and recommend the next workflow; do not create a coding handoff unless code work "
            "is explicit."
        ),
    ),
    "operations": RecommendationPolicy(
        next_action="prepare_ops_review",
        evidence_boundary="An ops review is not implementation, release, CI, review, or merge evidence.",
        wrapper_guidance="Summarize observed status, risks, blockers, and follow-ups; keep unknowns explicit.",
    ),
    "materials": RecommendationPolicy(
        next_action="prepare_material_package",
        evidence_boundary=(
            "Material packaging guidance is not binary file generation, render QA, formula recalculation, "
            "approval, delivery, or upload evidence."
        ),
        wrapper_guidance=(
            "Route the request into a material plan first; keep Hermes chat as the normal surface and use CLI "
            "artifacts only as backend/verifier state."
        ),
    ),
    "hermes-setup": RecommendationPolicy(
        next_action="run_setup_guide",
        evidence_boundary=(
            "A setup guide is not evidence that prerequisites exist, configuration was applied, or "
            "verification passed; only the re-read checklist after approved edits is observed setup state."
        ),
        wrapper_guidance=(
            "Walk the five-step setup contract in Hermes chat: confirm prerequisites (mark unmet items "
            "not applicable), diagnose current configuration read-only, guide the manual steps, apply "
            "config edits only after an approved diff, then re-verify and report the checklist."
        ),
    ),
    "delivery": RecommendationPolicy(
        next_action="present_app_delivery_loop",
        evidence_boundary="An app delivery loop is not implementation, deploy, monitoring, rollback, or completion evidence.",
        wrapper_guidance=(
            "Show the idea, decision, plan, handoff, verification, deploy, and monitoring stages; keep executor "
            "and deploy actions disabled until the matching acceptance or observation exists."
        ),
    ),
    "leadership": RecommendationPolicy(
        next_action="run_cto_loop",
        evidence_boundary="A CTO loop brief is not an accepted decision, implementation, deploy, or monitoring evidence.",
        wrapper_guidance=(
            "Keep roadmap, architecture, risk, delivery, and release-readiness decisions in Hermes; convert accepted "
            "implementation follow-ups into explicit executor-neutral handoffs and record status only from observed evidence."
        ),
    ),
    "monitoring": RecommendationPolicy(
        next_action="prepare_deploy_monitor_plan",
        evidence_boundary="A deploy and monitor plan is not deploy, health-check, rollback, or incident evidence.",
        wrapper_guidance=(
            "Show deploy checklist, health signals, rollback gates, and post-deploy status; record only observed "
            "deploy or monitoring evidence."
        ),
    ),
    "goal-loop": RecommendationPolicy(
        next_action="assess_loopability",
        evidence_boundary=(
            "A goal loop is orchestration state only; it is not implementation, review, CI, merge, external "
            "publication, market response, or goal completion evidence."
        ),
        wrapper_guidance=(
            "Assess whether the request is a task, project, north-star ambition, external wait, or unclear goal before "
            "starting a loop. Only cycle research -> plan -> handoff -> feedback inside the selected authority envelope."
        ),
    ),
    "process": RecommendationPolicy(
        next_action="start_delivery_cycle",
        evidence_boundary=(
            "An Ultraprocess route is process orchestration only; it is not implementation, review, docs sync, "
            "CI, PR creation, merge-readiness, or merge evidence."
        ),
        wrapper_guidance=(
            "Show the plan -> implementation handoff -> code review -> docs sync -> PR stages, ask for or apply "
            "an executor owner before code work, and keep every stage prepared_not_observed until matching evidence exists."
        ),
    ),
    "review": RecommendationPolicy(
        next_action="prepare_review_or_followup_handoff",
        evidence_boundary="A review recommendation is not a completed review or fix evidence.",
        wrapper_guidance="Surface findings separately from any code changes; fixes need their own executor evidence.",
    ),
    "operator": RecommendationPolicy(
        next_action="run_local_operator_check",
        evidence_boundary="Local operator guidance is not a completed health check until command output is observed.",
        wrapper_guidance="Run or display the local check result directly; record only observed command evidence.",
    ),
    "router": RecommendationPolicy(
        next_action="clarify_or_route",
        evidence_boundary="Routing guidance is not execution evidence.",
        wrapper_guidance="Route conservatively and show the missing decision before claiming work started.",
    ),
}
_HERMES_ROLE_POLICIES = {
    "guide": RecommendationPolicy(
        next_action="clarify_or_route",
        evidence_boundary="Routing guidance is not plan acceptance, dispatch, execution, review, CI, or merge evidence.",
        wrapper_guidance="Route conservatively, show why the workflow was selected, and ask one focused question when confidence is low.",
    ),
    "researcher": RecommendationPolicy(
        next_action="run_hermes_research",
        evidence_boundary="Research guidance is not observed source retrieval, implementation, or verification evidence.",
        wrapper_guidance="Keep evidence, inference, freshness, and unknowns separate before moving to planning or handoff.",
    ),
    "planner": RecommendationPolicy(
        next_action="present_plan",
        evidence_boundary="A recommendation or draft plan is not execution evidence.",
        wrapper_guidance="Show an Accept plan / Revise plan choice; keep handoff disabled until the plan is accepted.",
    ),
    "operator": RecommendationPolicy(
        next_action="prepare_operating_workflow",
        evidence_boundary="Operational workflow guidance is not meeting, delivery, file export, deploy, monitoring, or platform evidence.",
        wrapper_guidance="Prepare the business or product workflow card and keep missing observations visible.",
    ),
    "memory-keeper": RecommendationPolicy(
        next_action="prepare_memory_review",
        evidence_boundary="Memory guidance is not proof that Hermes internal memory, wiki, USER.md, MEMORY.md, or skill files changed.",
        wrapper_guidance="Present context candidates and require observed approval before applying memory or knowledge changes.",
    ),
    "handoff-guide": RecommendationPolicy(
        next_action="prepare_coding_runtime_handoff",
        evidence_boundary=(
            "A prepared coding runtime handoff is not runtime start, worker dispatch, worktree creation, execution, "
            "review, CI, merge-readiness, or merge evidence."
        ),
        wrapper_guidance=(
            "Ask for or apply the selected runtime profile, expose runtime/team/worktree/status actions, "
            "and mark prepared work as prepared_not_observed until observed runtime evidence exists."
        ),
    ),
    "tracker": RecommendationPolicy(
        next_action="refresh_status",
        evidence_boundary="Status guidance is not proof that a runtime, tool, MCP server, CI job, or platform action ran.",
        wrapper_guidance="Report only observed status, show missing evidence, and keep estimates separate from provider or runtime truth.",
    ),
    "reviewer": RecommendationPolicy(
        next_action="prepare_review_or_followup_handoff",
        evidence_boundary="A review recommendation is not a completed review or fix evidence.",
        wrapper_guidance="Surface findings separately from any code changes; fixes need their own executor evidence.",
    ),
    "codex-handoff-guidance": RecommendationPolicy(
        next_action="prepare_coding_handoff",
        evidence_boundary=(
            "A prepared coding handoff is not execution, review, CI, merge-readiness, or merge evidence."
        ),
        wrapper_guidance=(
            "Ask for or apply the selected executor/runtime profile, expose executor-neutral handoff/status actions, "
            "and mark prepared work as prepared_not_observed."
        ),
    ),
    "runtime-handoff-guidance": RecommendationPolicy(
        next_action="prepare_coding_runtime_handoff",
        evidence_boundary=(
            "A prepared coding runtime handoff is not runtime start, worker dispatch, worktree creation, execution, "
            "review, CI, merge-readiness, or merge evidence."
        ),
        wrapper_guidance=(
            "Ask for or apply the selected runtime profile, expose runtime/team/worktree/status actions, "
            "and mark prepared work as prepared_not_observed until observed runtime evidence exists."
        ),
    ),
}


@dataclass(frozen=True)
class Recommendation:
    skill: str
    description: str
    category: str
    phase: str
    hermes_role: str
    handoff_policy: str
    reasoning_demand: str
    score: int
    confidence: str
    matched: tuple[str, ...]
    why: str
    next_action: str
    evidence_boundary: str
    wrapper_guidance: str
    suggested_prompt: str

    def to_dict(self) -> dict[str, object]:
        return {
            "skill": self.skill,
            "description": self.description,
            "category": self.category,
            "phase": self.phase,
            "hermes_role": self.hermes_role,
            "handoff_policy": self.handoff_policy,
            "reasoning_demand": self.reasoning_demand,
            "score": self.score,
            "confidence": self.confidence,
            "matched": list(self.matched),
            "why": _humanize_recommendation_reason(self.why),
            "next_action": self.next_action,
            "evidence_boundary": self.evidence_boundary,
            "wrapper_guidance": self.wrapper_guidance,
            "suggested_prompt": self.suggested_prompt,
        }


def recommend_skills(query: str, *, limit: int = 5, apply_guardrails: bool = True) -> list[dict[str, object]]:
    if limit < 1:
        raise ValueError("recommend --limit must be at least 1")

    return [recommendation.to_dict() for recommendation in _recommend_skills_cached(query, apply_guardrails)[:limit]]


def has_strong_named_catalog_owner(query: str) -> bool:
    """Return whether one catalog name and a second semantic signal match."""

    routing_text = prepare_routing_text(_strip_path_like_fragments(scrub_diagnostic_status_text(query)))
    normalized_query = normalized_phrase(routing_text.scoring_text)
    query_tokens = _tokens(normalized_query)
    if (
        any(guard.id == _TOOLBELT_READINESS_GUARD_ID for guard in active_routing_guard_rules(normalized_query, query_tokens))
        and query_tokens
        & {
            "api",
            "credential",
            "credentials",
            "key",
            "missing",
            "mcp",
            "unavailable",
            "자격증명",
            "키",
            "없어",
            "없어서",
        }
    ):
        return False
    for prepared in _prepared_routable_definitions():
        if not _phrase_match(normalized_query, prepared.name_phrase):
            continue
        if _explicit_skill_candidate_is_negated(query, prepared.definition.name):
            continue
        name_tokens = _tokens(prepared.name_phrase)
        if query_tokens & (prepared.trigger_tokens - name_tokens - _GENERIC_TRIGGER_TOKENS):
            return True
    return False


def recommendation_for_definition(
    definition: SkillDefinition,
    query: str,
    *,
    matched: tuple[str, ...],
    score: int,
    why: str | None = None,
) -> dict[str, object]:
    policy = _policy_for(definition)
    matched_tuple = tuple(sorted(matched))
    return Recommendation(
        skill=definition.name,
        description=definition.description,
        category=definition.category,
        phase=definition.phase,
        hermes_role=definition.hermes_role,
        handoff_policy=definition.handoff_policy,
        reasoning_demand=definition.reasoning_demand,
        score=score,
        confidence=_confidence(score),
        matched=matched_tuple,
        why=why or _why(matched_tuple),
        next_action=policy.next_action,
        evidence_boundary=policy.evidence_boundary,
        wrapper_guidance=policy.wrapper_guidance,
        suggested_prompt=_suggested_prompt(definition.name, query),
    ).to_dict()


@lru_cache(maxsize=2048)
def _recommend_skills_cached(query: str, apply_guardrails: bool) -> tuple[Recommendation, ...]:
    routing_query = scrub_diagnostic_status_text(query)
    routing_text = prepare_routing_text(_strip_path_like_fragments(routing_query))
    normalized_query = normalized_phrase(routing_text.scoring_text)
    query_tokens = _tokens(normalized_query)
    prepared_definitions = _prepared_routable_definitions()
    definitions = [prepared.definition for prepared in prepared_definitions]
    explicit_skill = explicit_skill_invocation(routing_query, {definition.name for definition in definitions})
    if explicit_skill and is_missed_route_feedback(normalized_query):
        explicit_skill = None
    if explicit_skill == "skill" and _skill_scout_candidate_alias_intent_match(normalized_query):
        explicit_skill = None
    return _scored_field(
        query,
        routing_query=routing_query,
        routing_text=routing_text,
        normalized_query=normalized_query,
        query_tokens=query_tokens,
        prepared_definitions=prepared_definitions,
        definitions=definitions,
        explicit_skill=explicit_skill,
        apply_guardrails=apply_guardrails,
    )


def scored_field_winner_without_explicit_invocation(query: str) -> str:
    """Return the top skill when the typed skill name earns no invocation bonus.

    `explicit_skill_invocation()` uses this to decide whether a bare, sigil-free
    first word that happens to be a catalog name (`research ...`) was an
    invocation or just the sentence's verb. Scoring with `explicit_skill=None`
    is what makes the answer meaningful: the invocation bonus is +12 AND it
    suppresses the routing guards that would otherwise hand the message to its
    real owner, so the unbiased field is the only view that shows the competing
    lane. This never calls back into `explicit_skill_invocation()`, so there is
    no recursion.
    """
    routing_query = scrub_diagnostic_status_text(query)
    routing_text = prepare_routing_text(_strip_path_like_fragments(routing_query))
    normalized_query = normalized_phrase(routing_text.scoring_text)
    prepared_definitions = _prepared_routable_definitions()
    field = _scored_field(
        query,
        routing_query=routing_query,
        routing_text=routing_text,
        normalized_query=normalized_query,
        query_tokens=_tokens(normalized_query),
        prepared_definitions=prepared_definitions,
        definitions=[prepared.definition for prepared in prepared_definitions],
        explicit_skill=None,
        apply_guardrails=True,
    )
    return field[0].skill if field else ""


def _scored_field(
    query: str,
    *,
    routing_query: str,
    routing_text: object,
    normalized_query: str,
    query_tokens: set[str],
    prepared_definitions: tuple[_PreparedDefinition, ...],
    definitions: list[SkillDefinition],
    explicit_skill: str | None,
    apply_guardrails: bool,
) -> tuple[Recommendation, ...]:
    ecosystem_identity_connector_match = _ecosystem_identity_connector_explicit_match(normalized_query)
    domain_signal = specialist_domain_route_signal(routing_text.scoring_text)
    domain_operator_override = specialist_domain_operator_override(
        routing_text.scoring_text,
        domain_signal,
    )
    excluded_domain_skills = excluded_specialist_domain_skills(normalized_query)
    scored = []
    for prepared in prepared_definitions:
        recommendation = _score_definition(
            prepared,
            normalized_query,
            query_tokens,
            routing_query,
            routing_text.locale_matches,
            explicit_skill=explicit_skill,
            domain_signal=None if domain_operator_override is not None else domain_signal,
            domain_operator_override=domain_operator_override,
        )
        if recommendation is not None:
            scored.append(recommendation)
    scored = [recommendation for recommendation in scored if recommendation.skill not in excluded_domain_skills]
    if explicit_skill != "automation-blueprint" and is_explicit_one_off_request(normalized_query, query_tokens):
        scored = [recommendation for recommendation in scored if recommendation.skill != "automation-blueprint"]
    matches = scored
    if apply_guardrails:
        guards = active_routing_guard_rules(normalized_query, query_tokens, explicit_skill=explicit_skill)
        public_plugin_connector_match = _public_plugin_connector_readiness_match(normalized_query)
        if (
            ecosystem_identity_connector_match
            or public_plugin_connector_match
            or _has_strong_named_catalog_owner(matches)
        ):
            guards = tuple(guard for guard in guards if guard.id != _TOOLBELT_READINESS_GUARD_ID)
        if public_plugin_connector_match or _skill_scout_candidate_alias_intent_match(normalized_query):
            guards = tuple(guard for guard in guards if guard.id != "ops_observability_before_generic_loop")
        matches = _ensure_guardrail_candidates(matches, definitions, guards, query)
        matches = _apply_guardrail_reranking(
            matches,
            guards=guards,
        )
        matches = _apply_guardrail_followup_boundaries(matches, guards)
        visual_guard_active = any(guard.id == "img_summary_before_materials_or_delivery" for guard in guards)
        if explicit_skill != "img-summary" and not visual_guard_active:
            matches = [recommendation for recommendation in matches if recommendation.skill != "img-summary"]
            if not matches:
                matches = _fallback_recommendations(definitions, query)
                return tuple(matches)
    if not matches:
        matches = _fallback_recommendations(definitions, query)
        return tuple(matches)
    matches.sort(key=lambda recommendation: (-recommendation.score, recommendation.skill))
    matches = _prioritize_guarded_workflow_learning(matches)
    matches = _prioritize_explicit_skill(matches, explicit_skill)
    return tuple(matches)


@lru_cache(maxsize=1)
def _prepared_routable_definitions() -> tuple[_PreparedDefinition, ...]:
    return tuple(_prepare_definition(definition) for definition in routable_definitions())


# A description that ends "...for X use <sibling>" hands the sibling's own
# vocabulary to the skill doing the pointing, because metadata tokens are derived
# from the description text. For most skills the clause words are harmless; for
# `research` they reverse the boundary the clause exists to state. "upstream
# guidance for pinning Python dependencies" gave `research` +1 for `upstream` and
# +1 for `guidance`, and with the web-research-before-process guard's +14 that
# beat `best-practice-research`, the skill the sentence names. Same shape for
# `brief`/`decision` against `research-brief`. Excluded per skill, in the same
# spirit as the per-skill trigger-token exclusions in `_score_definition`; the
# general derivation is untouched.
_SIBLING_POINTER_METADATA_TOKENS = {
    "research": frozenset({"upstream", "guidance", "brief", "decision"}),
}

# These ordinary English words are meaningful only as complete status-board
# phrases. Crediting them separately made unrelated sentences containing
# `models` and `work` look like observed-work inventory requests.
_WHOLE_PHRASE_ONLY_TRIGGER_TOKENS = {
    "running-work-board": frozenset({"board", "models", "running", "units", "what", "which", "work"}),
    # `model-optimization` names the onboarding process with ordinary ML and
    # tuning words. Credited as bare tokens they made "which model is cheapest
    # right now", "optimize database indexes", and "calibrate the load
    # balancer weights" name this workflow as a candidate. The intent lives
    # only in the complete phrases ("onboard new model", "model calibration",
    # ...), which the +6 phrase match already covers.
    "model-optimization": frozenset(
        {"calibrate", "calibration", "model", "new", "onboard", "optimization", "optimize"}
    ),
    # `inference-serving` names its work with ordinary infra words --
    # "serve", "serving", "deploy", "endpoint", "benchmark", "quantization".
    # Credited as bare tokens they claimed API-serving and web-deploy chat.
    # Complete phrases and the engine names (`vllm`, `llama.cpp`) carry the
    # intent.
    "inference-serving": frozenset(
        {
            "benchmark",
            "deploy",
            "endpoint",
            "inference",
            "model",
            "quantization",
            "serve",
            "serving",
            "the",
            "this",
            "which",
        }
    ),
    # `tech-debt-audit` names its work with words other domains own outright
    # -- "debt" is personal finance and loan-domain vocabulary, "audit" is
    # code-review's trigger, "ledger" is bookkeeping. Credited as bare tokens
    # they claimed finance chat and every review request. Complete phrases
    # ("tech debt", "debt ledger", ...) carry the intent; no single token is
    # unambiguous alone.
    "tech-debt-audit": frozenset(
        {"audit", "code", "debt", "is", "ledger", "our", "report", "tech", "technical", "where"}
    ),
    # `award-bar-score` names its work with words every other lane owns --
    # "design" is the whole materials lane, "review" is code-review, "site",
    # "website" and "page" are frontend, and "award", "score" and "day" are
    # ordinary business vocabulary. Credited as bare tokens they claimed sales
    # awards, performance reviews, and every site request. Complete phrases
    # ("award winning website", "design award", ...) carry the intent; the only
    # unambiguous bare tokens are the award bodies' own names, kept in the route
    # hint's `tokens` tuple.
    "award-bar-score": frozenset(
        {
            "award",
            "awards",
            "bar",
            "css",
            "day",
            "design",
            "it",
            "make",
            "my",
            "of",
            "ready",
            "review",
            "score",
            "site",
            "the",
            "website",
            "winning",
        }
    ),
    # `refactor-plan` names its work with the two most ordinary words in the
    # catalog -- "refactor" and "plan" -- plus "phases", "restructure", and
    # "blast". Credited as bare tokens they claimed every planning and
    # cleanup message. Complete phrases carry the intent.
    "refactor-plan": frozenset(
        {"blast", "module", "phased", "phases", "plan", "planning", "radius", "refactor", "restructure", "rollback", "the", "this"}
    ),
    # `codebase-uml` names its picture with the vocabulary of every code
    # question -- "draw", "diagram", "architecture", "package", "module",
    # "picture". Credited as bare tokens they made "which package owns the
    # router" and "draw up a release plan" name the diagram as a candidate.
    # Only `uml` and `plantuml` are unambiguous alone; the rest dispatch as
    # complete phrases.
    "codebase-uml": frozenset(
        {
            "architecture",
            "class",
            "code",
            "codebase",
            "dependency",
            "diagram",
            "draw",
            "module",
            "package",
            "picture",
            "the",
            "this",
            "visualization",
            "visualize",
        }
    ),
    # `frontend-refactor` shares its vocabulary with every coding request --
    # "refactor", "component", "state", "hook", "split". Credited as bare
    # tokens they made "refactor this function" and "what is state management"
    # name the workflow as a candidate. The intent lives in the complete
    # phrases, which the +6 phrase match already covers.
    "frontend-refactor": frozenset(
        {
            "cleanup",
            "component",
            "hook",
            "management",
            "refactor",
            "split",
            "state",
            "the",
            "this",
        }
    ),
    # `memory-sync` gained natural interview phrases ("your memories",
    # "memories still true", "memory interview"); their loose tokens are
    # everyday words that made "how do computers store memories" name this
    # workflow ("memories") and would credit any "is it still true ..."
    # sentence ("still", "true") or pull deep-interview requests
    # ("interview"). The intent lives only in the complete phrases; "your"
    # stays creditable because it was already trigger vocabulary before
    # these phrases landed.
    "memory-sync": frozenset({"interview", "memories", "still", "true"}),
    # `adversarial-consensus` names its mechanic with ordinary planning words --
    # "red team this plan", "attack this proposal", "poke holes in this". Split
    # into tokens they are the vocabulary of every planning request: crediting
    # `plan` alone made the catalog question "what can OMH do for plan?" score
    # this workflow at high confidence and show its card instead of the picker.
    # The distinctive tokens (`adversarial`, `consensus`, `perspective`,
    # `red-team`, `hyperplan`) still score; these carry the intent only inside a
    # complete trigger phrase, which the +6 phrase match already covers. The
    # non-English words with the same problem live beside their own language's
    # phrases, in that language's trigger pack `whole_phrase_only_tokens` --
    # a hold-back belongs wherever the phrase it guards was authored.
    "adversarial-consensus": frozenset(
        {
            "attack",
            "holes",
            "independent",
            "multi",
            "multiple",
            "plan",
            "planning",
            "poke",
            "proposal",
            "red",
            "review",
            "team",
        }
    ),
    # `llm-app-dev` is named out of the most generic vocabulary in the catalog:
    # `llm`, `app`, `build`, `output`, `schema`, `prompt`, `eval`, `set`. Split
    # into tokens, "what does an llm agent eval look like?" and "the app build
    # failed" both credit this workflow, and `llm` alone appears in every
    # sentence about agents -- which is `agent-evaluation`'s and `agent-debug`'s
    # subject, not this one. `rag` is held back for the same reason even though
    # it looks distinctive: crediting it dispatched "rename the rag pipeline
    # package" and "refactor the rag pipeline module" -- ordinary renames on an
    # LLM component -- at a score of 9 against a field of 4s. Only `dev` and
    # `llm-app` stay creditable on their own; the rest carry the intent only
    # inside a complete trigger phrase, which the phrase match and the
    # `direct:llm_app_dev` boost cover.
    #
    # English only -- not because a non-English entry could not be held back
    # (pack entries are normalized through `routing_tokens` before use, same as
    # these), but because the Korean triggers do not need the hold-back at all:
    # measured on "앱 개발
    # 시작하자", "기능 개발 계획 세워줘", "버전 관리 어떻게 해?", "출력 형식
    # 바꿔줘", and "프롬프트 좀 고쳐줘", their token credit tops out at 6, which
    # stays in clarify and never dispatches.
    "llm-app-dev": frozenset(
        {
            "app",
            "application",
            "augmented",
            "build",
            "development",
            "eval",
            "feature",
            "generation",
            "golden",
            "json",
            "llm",
            "output",
            "pipeline",
            "prompt",
            "rag",
            "retrieval",
            "schema",
            "set",
            "structured",
            "suite",
            "versioning",
        }
    ),
}


def _normalized_trigger_token_holdback(entries: frozenset[str]) -> frozenset[str]:
    # `trigger_tokens` below is built from `_tokens(...)`, which folds every
    # token through `routing_tokens` -- NFKD normalization that decomposes
    # precomposed Hangul syllables into their component jamo. Subtracting the
    # *raw* `_WHOLE_PHRASE_ONLY_TRIGGER_TOKENS` entries would compare an
    # as-written composed Korean word against decomposed tokens it can never
    # equal, so the hold-back would silently remove nothing for Korean
    # entries (see `tests/test_trigger_holdback_reachability.py`). Running
    # each entry through the same `_tokens` pipeline before subtracting keeps
    # this a set difference over a shared representation, so authors can
    # write entries -- Korean or English -- in ordinary composed form.
    # `_tokens` itself is defined later in this module (it is only a thin
    # `routing_tokens(value, stopwords=_STOPWORDS)` wrapper), and this table
    # is built at import time, so call `routing_tokens` directly here rather
    # than forward-reference `_tokens`.
    normalized: set[str] = set()
    for entry in entries:
        normalized.update(routing_tokens(entry, stopwords=_STOPWORDS))
    return frozenset(normalized)


_NORMALIZED_WHOLE_PHRASE_ONLY_TRIGGER_TOKENS = {
    name: _normalized_trigger_token_holdback(entries) for name, entries in _WHOLE_PHRASE_ONLY_TRIGGER_TOKENS.items()
}


@lru_cache(maxsize=1)
def _trigger_pack_packs() -> tuple[TriggerLanguagePack, ...]:
    """Shipped packs plus the person's own, for the scoring layer only.

    Shipped packs already merged into the catalog, so their *phrases* arrive
    through `definition.triggers`; they are re-read here for their hold-back
    entries, which are a scoring concern rather than a catalog one. User packs
    contribute both, and only here: a local pack must widen what this router
    recognises without rewriting the product's generated artifacts.
    """
    known_skills = frozenset(definition.name for definition in builtin_definitions())
    shipped = shipped_trigger_language_packs(known_skills)
    user_packs, _ = load_user_trigger_language_packs(None, known_skills)
    return shipped + user_packs


@lru_cache(maxsize=1)
def _user_trigger_pack_phrases() -> dict[str, tuple[str, ...]]:
    return merged_trigger_phrases(
        tuple(pack for pack in _trigger_pack_packs() if pack.origin == ORIGIN_USER)
    )


@lru_cache(maxsize=1)
def _pack_trigger_token_holdback() -> dict[str, frozenset[str]]:
    return {
        skill: _normalized_trigger_token_holdback(frozenset(tokens))
        for skill, tokens in merged_holdback_tokens(_trigger_pack_packs()).items()
    }


def _trigger_token_holdback_for(name: str) -> frozenset[str]:
    return _NORMALIZED_WHOLE_PHRASE_ONLY_TRIGGER_TOKENS.get(
        name, frozenset()
    ) | _pack_trigger_token_holdback().get(name, frozenset())


def _prepare_definition(definition: SkillDefinition) -> _PreparedDefinition:
    triggers = definition.triggers + tuple(
        phrase
        for phrase in _user_trigger_pack_phrases().get(definition.name, ())
        if phrase not in definition.triggers
    )
    trigger_phrases = tuple(normalized_phrase(trigger) for trigger in triggers)
    metadata_tokens = frozenset(
        _tokens(" ".join((definition.name, definition.description, definition.use_when)))
    ) - _SIBLING_POINTER_METADATA_TOKENS.get(definition.name, frozenset())
    return _PreparedDefinition(
        definition=definition,
        policy=_policy_for(definition),
        trigger_phrases=trigger_phrases,
        command_trigger_phrases=tuple(trigger for trigger in trigger_phrases if trigger in _COMMAND_TRIGGER_PHRASES),
        plain_trigger_phrases=tuple(trigger for trigger in trigger_phrases if trigger and trigger not in _COMMAND_TRIGGER_PHRASES),
        trigger_tokens=frozenset(_tokens(" ".join(triggers))) - _trigger_token_holdback_for(definition.name),
        name_phrase=normalized_phrase(definition.name),
        description_phrase=normalized_phrase(definition.description),
        use_when_phrase=normalized_phrase(definition.use_when),
        category_phrase=normalized_phrase(definition.category),
        phase_phrase=normalized_phrase(definition.phase),
        metadata_tokens=metadata_tokens,
    )


def _score_definition(
    prepared: _PreparedDefinition,
    normalized_query: str,
    query_tokens: set[str],
    original_query: str,
    locale_matches: tuple[str, ...],
    *,
    explicit_skill: str | None,
    domain_signal: DomainRouteSignal | None,
    domain_operator_override: DomainOperatorOverride | None,
) -> Recommendation | None:
    definition = prepared.definition
    policy = prepared.policy
    if explicit_skill != definition.name and _explicit_skill_candidate_is_negated(original_query, definition.name):
        return None
    score = 0
    matched: set[str] = set()
    ecosystem_identity_connector_match = definition.name == "external-connector-readiness" and (
        _ecosystem_identity_connector_explicit_match(normalized_query)
    )

    # Some skills belong in the shortlist only when their own precondition
    # holds. That was seven copies of this same conditional, so adding an
    # eighth meant editing the function every skill is scored by. The rules
    # live in `_SKILL_OFFERS_ITSELF` at the foot of this module now: same
    # predicates, same evaluation order, one row per skill.
    offers_itself = _SKILL_OFFERS_ITSELF.get(definition.name)
    if (
        offers_itself is not None
        and (
            explicit_skill != definition.name
            or (definition.name == "context" and "budget" in query_tokens)
        )
        and not offers_itself(normalized_query, query_tokens)
    ):
        return None

    if definition.name == explicit_skill:
        score += 12
        matched.update(("explicit_invocation", f"name:{definition.name}"))

    for trigger_phrase in prepared.plain_trigger_phrases:
        if _trigger_phrase_match(normalized_query, trigger_phrase):
            score += 6
            matched.add(f"trigger:{trigger_phrase}")

    for trigger_phrase in prepared.command_trigger_phrases:
        if _command_trigger_match(normalized_query, trigger_phrase):
            score += 6
            matched.add(f"trigger:{trigger_phrase}")

    if _phrase_match(normalized_query, prepared.name_phrase):
        score += 5
        matched.add(f"name:{prepared.name_phrase}")

    if _phrase_match(normalized_query, prepared.description_phrase):
        score += 3
        matched.add("description:phrase")

    if _phrase_match(normalized_query, prepared.use_when_phrase):
        score += 3
        matched.add("use_when:phrase")

    for field_name, normalized_value in (("category", prepared.category_phrase), ("phase", prepared.phase_phrase)):
        if _phrase_match(normalized_query, normalized_value):
            score += 2
            matched.add(f"{field_name}:{normalized_value}")

    trigger_token_matches = query_tokens & prepared.trigger_tokens
    if definition.name == "ops-observability-card" and "dashboard" in trigger_token_matches and "slo" not in query_tokens:
        trigger_token_matches.remove("dashboard")
    if definition.name == "codegraph-refresh" and not _codegraph_refresh_token_context(normalized_query, query_tokens):
        trigger_token_matches -= {"index", "refresh", "stale", "갱신"}
    if definition.name == "external-connector-readiness" and not ecosystem_identity_connector_match:
        trigger_token_matches -= _ECOSYSTEM_IDENTITY_CONNECTOR_TRIGGER_NOISE
    if not matched and not (trigger_token_matches - _GENERIC_TRIGGER_TOKENS):
        trigger_token_matches -= _GENERIC_TRIGGER_TOKENS
    for token in trigger_token_matches:
        score += 3
        matched.add(f"trigger:{token}")

    for token in query_tokens & prepared.metadata_tokens:
        score += 1
        matched.add(f"metadata:{token}")

    if domain_signal is not None and definition.name == domain_signal.skill:
        score += 54
        matched.update(f"domain:{cue}" for cue in domain_signal.matched_cues)
    if domain_operator_override is not None and definition.name == domain_operator_override.skill:
        score += 72
        matched.update(f"domain_action:{cue}" for cue in domain_operator_override.matched_cues)

    if definition.name == "apple-design" and _apple_design_offers_itself(normalized_query, query_tokens):
        score += 30
        matched.add("direct:apple_design_specialist")
    if definition.name == "adversarial-consensus" and _adversarial_consensus_explicit_match(normalized_query):
        score += 30
        matched.add("direct:adversarial_consensus")
    if definition.name == "llm-app-dev" and _llm_app_dev_explicit_match(normalized_query):
        score += 30
        matched.add("direct:llm_app_dev")
    if definition.name == "product-docs" and _omh_docs_offers_itself(normalized_query, query_tokens):
        score += 30
        matched.add("direct:omh_docs_self_knowledge")
    if definition.name == "memory-sync" and _memory_interview_explicit_match(normalized_query):
        score += 30
        matched.add("direct:memory_interview")
    if definition.name == "failure-signal-audit" and _failure_signal_audit_explicit_match(normalized_query):
        score += 34
        matched.add("direct:failure_signal_audit")
    if ecosystem_identity_connector_match:
        score += 36
        matched.add("direct:ecosystem_identity_connector")
    if definition.name == "external-connector-readiness" and _public_plugin_connector_readiness_match(normalized_query):
        score += 36
        matched.add("direct:public_plugin_connector_readiness")
    if definition.name == "skill-scout" and _skill_scout_candidate_alias_intent_match(normalized_query):
        score += 36
        matched.add("direct:skill_scout_candidate_alias")
    if definition.name == "source-finder" and _explicit_phrase_match(normalized_query, "source-finder"):
        score += 36
        matched.add("direct:source_finder_alias")
    if definition.name == "accessibility-audit" and _accessibility_audit_explicit_match(normalized_query):
        score += 30
        matched.add("direct:accessibility_audit")
    if definition.name == "build-failure-triage" and _build_failure_triage_explicit_match(normalized_query):
        score += 32
        matched.add("direct:build_failure_triage")
    if definition.name == "verification-gate" and _build_failure_triage_fixed_or_pass_verification_context(
        normalized_query
    ):
        score += 28
        matched.add("direct:fixed_or_pass_verification")

    if score <= 0:
        return None

    if score > 0:
        matched.update(f"locale:{match}" for match in locale_matches)

    matched_tuple = tuple(sorted(matched))
    return Recommendation(
        skill=definition.name,
        description=definition.description,
        category=definition.category,
        phase=definition.phase,
        hermes_role=definition.hermes_role,
        handoff_policy=definition.handoff_policy,
        reasoning_demand=definition.reasoning_demand,
        score=score,
        confidence=_confidence(score),
        matched=matched_tuple,
        why=_why(matched_tuple),
        next_action=policy.next_action,
        evidence_boundary=policy.evidence_boundary,
        wrapper_guidance=policy.wrapper_guidance,
        suggested_prompt=_suggested_prompt(definition.name, original_query),
    )


def _codegraph_refresh_token_context(normalized_query: str, query_tokens: set[str]) -> bool:
    return bool({"codegraph", "codemap", "codemaps", "code", "코드그래프", "코드맵", "코드"} & query_tokens) or _phrase_match(
        normalized_query,
        "code map",
    )


def _external_connector_readiness_recommendation_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _public_plugin_connector_readiness_match(normalized_query):
        return True

    strong_anchor_tokens = {
        "adopt",
        "adoption",
        "api",
        "apis",
        "audio",
        "auth",
        "authentication",
        "authorization",
        "caldav",
        "carddav",
        "chainlink",
        "cli",
        "composio",
        "connector",
        "connectors",
        "credential",
        "credentials",
        "database",
        "fallback",
        "file",
        "files",
        "freshness",
        "graph",
        "live-data",
        "microsoft",
        "multimodal",
        "nextcloud",
        "onequery",
        "plugin",
        "plugins",
        "quota",
        "readiness",
        "ready",
        "screenshot",
        "screenshots",
        "solana",
        "sql",
        "trial",
        "trials",
        "universal",
        "video",
        "webdav",
        "workspace",
        "wxtrain",
        "도입",
        "멀티모달",
        "비디오",
        "스크린샷",
        "오디오",
        "인증",
        "리스크",
        "비용",
        "준비",
        "준비도",
        "캡처",
        "캡쳐",
        "커넥터",
        "쿼터",
        "파일",
        "플러그인",
    }
    if query_tokens & strong_anchor_tokens:
        return True
    return any(
        _phrase_match(normalized_query, phrase)
        for phrase in (
            "auto routing",
            "automatic routing",
            "자동 라우팅",
            "composio universal cli",
            "universal cli connector",
            "universal cli skill adoption",
            "skill connector adoption",
            "connector auth risk",
            "connector cost auth risk",
            "cost aware connector",
            "private crypto transaction",
            "private cryptocurrency connector",
            "crypto transaction plugin",
            "monero gateway",
            "xmr gateway",
            "blockchain gateway",
            "read only sql",
            "live data",
            "peer-to-peer agent messaging",
            "peer to peer agent messaging",
            "websocket identity",
            "agentchat connector",
            "agy cli bridge",
            "agy bridge connector",
            "windy pairing",
            "macos keychain oauth",
            "oracle oci",
            "oracle genai",
            "miniverse bridge",
            "crustocean platform",
            "smart home connector",
        )
    )


def _public_plugin_connector_readiness_match(normalized_query: str) -> bool:
    if _skill_scout_candidate_alias_intent_match(normalized_query):
        return False
    exact_readiness = any(
        _phrase_match(normalized_query, normalized_phrase(phrase))
        for phrase in (
            "memory provider readiness",
            "search provider connector readiness",
            "social automation connector readiness",
            "twitter automation connector readiness",
            "x/twitter automation connector readiness",
            "x twitter automation connector readiness",
        )
    )
    candidate = any(
        _phrase_match(normalized_query, normalized_phrase(phrase))
        for phrase in PUBLIC_PLUGIN_CONNECTOR_ALIAS_PHRASES
    )
    readiness_context = any(
        _phrase_match(normalized_query, normalized_phrase(phrase))
        for phrase in PUBLIC_PLUGIN_CONNECTOR_READINESS_CONTEXT_PHRASES
    )
    return exact_readiness or (candidate and readiness_context)


def _ecosystem_identity_connector_explicit_match(normalized_query: str) -> bool:
    return any(
        _phrase_match(normalized_query, phrase)
        for phrase in (
            "agentchat connector",
            "agentchat peer-to-peer",
            "peer-to-peer agent messaging",
            "peer to peer agent messaging",
            "websocket identity",
            "websocket connector",
            "clawsocial connector",
            "social discovery connector",
            "windy pairing",
            "windymail mailbox",
            "matrix chat identity",
            "antigravity cli connector",
            "agy cli bridge",
            "agy bridge connector",
            "macos keychain oauth",
            "oracle oci connector",
            "oracle genai connector",
            "miniverse bridge",
            "crustocean platform connector",
        )
    )


def _skill_scout_candidate_alias_intent_match(normalized_query: str) -> bool:
    return (
        any(
            _phrase_match(normalized_query, normalized_phrase(phrase))
            for phrase in SKILL_SCOUT_CANDIDATE_ALIAS_PHRASES
        )
        and any(
            _phrase_match(normalized_query, normalized_phrase(phrase))
            for phrase in SKILL_SCOUT_CANDIDATE_INTENT_PHRASES
        )
        and not any(
            _phrase_match(normalized_query, normalized_phrase(phrase))
            for phrase in SKILL_SCOUT_CANDIDATE_BLOCKER_PHRASES
        )
    )


def _physical_device_readiness_recommendation_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    strong_anchor_tokens = {
        "actuate",
        "actuator",
        "actuators",
        "camera",
        "device",
        "devices",
        "emergency",
        "g-code",
        "gcode",
        "gate",
        "gated",
        "greenhouse",
        "hardware",
        "heat",
        "heated",
        "iot",
        "klipper",
        "moonraker",
        "mushroom",
        "nozzle",
        "physical",
        "pi",
        "printer",
        "printers",
        "raspberry",
        "relay",
        "relays",
        "robot",
        "robotics",
        "robots",
        "safety",
        "sensor",
        "sensors",
        "snapmaker",
        "telemetry",
        "vla",
        "가열",
        "로봇",
        "릴레이",
        "물리",
        "센서",
        "안전",
        "장비",
        "카메라",
        "프린터",
    }
    if not query_tokens & strong_anchor_tokens:
        return False
    return any(
        _phrase_match(normalized_query, phrase)
        for phrase in (
            "physical device",
            "device safety",
            "hardware safety",
            "3d printer",
            "printer safety",
            "snapmaker printer safety",
            "snapmaker readiness",
            "moonraker klipper",
            "camera gate",
            "camera gated",
            "camera-gated",
            "heat command",
            "iot relay",
            "sensor relay",
            "robot control",
            "robotics safety",
            "vla robot",
            "mushroom cultivation",
            "raspberry pi relay",
            "physical-device-readiness",
            "물리 장비",
            "하드웨어 안전",
            "프린터 안전",
            "로봇 제어",
            "iot 릴레이",
            "센서 릴레이",
        )
    )


def _prompt_import_readiness_recommendation_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    strong_anchor_tokens = {
        "arguments",
        "claude",
        "cli",
        "codex",
        "collision",
        "collisions",
        "command",
        "commands",
        "frontmatter",
        "gemini",
        "import",
        "importing",
        "imports",
        "interpolation",
        "opencode",
        "prompt",
        "prompts",
        "slash",
        "toml",
        "yaml",
        "가져오기",
        "명령",
        "슬래시",
        "인자",
        "프롬프트",
    }
    if not query_tokens & strong_anchor_tokens:
        return False
    return any(
        _phrase_match(normalized_query, phrase)
        for phrase in (
            "slash prompt",
            "slash prompts",
            "prompt import",
            "prompt imports",
            "prompt folder",
            "prompt directory",
            "cli prompt",
            "cli agent prompt",
            "opencode prompt",
            "claude code prompt",
            "codex prompt",
            "gemini cli prompt",
            "$arguments",
            "{{args}}",
            "$1",
            "$2",
            "argument interpolation",
            "슬래시 프롬프트",
            "프롬프트 가져오기",
            "프롬프트 폴더",
            "프롬프트 디렉터리",
            "프롬프트 인자",
        )
    )


def _fallback_recommendations(definitions: list[SkillDefinition], query: str) -> list[Recommendation]:
    by_name = {definition.name: definition for definition in definitions}
    recommendations = []
    for name in _FALLBACK_SKILLS:
        definition = by_name.get(name)
        if definition is None:
            continue
        recommendations.append(
            Recommendation(
                skill=definition.name,
                description=definition.description,
                category=definition.category,
                phase=definition.phase,
                hermes_role=definition.hermes_role,
                handoff_policy=definition.handoff_policy,
                reasoning_demand=definition.reasoning_demand,
                score=0,
                confidence="low",
                matched=(),
                why=_FALLBACK_WHY,
                next_action=_next_action(definition),
                evidence_boundary=_evidence_boundary(definition),
                wrapper_guidance=_wrapper_guidance(definition),
                suggested_prompt=_suggested_prompt(definition.name, query),
            )
        )
    return recommendations


def _ensure_guardrail_candidates(
    recommendations: list[Recommendation],
    definitions: list[SkillDefinition],
    guards: tuple[RoutingGuardRule, ...],
    query: str,
) -> list[Recommendation]:
    injectable_guards = tuple(
        guard for guard in guards if guard.id in _GUARDRAIL_CANDIDATE_INJECTION_IDS
    )
    if not injectable_guards:
        return recommendations
    by_skill = {recommendation.skill: recommendation for recommendation in recommendations}
    by_definition = {definition.name: definition for definition in definitions}
    expanded = list(recommendations)
    for guard in injectable_guards:
        for skill_name in guard.preferred_skills:
            if skill_name in by_skill:
                continue
            definition = by_definition.get(skill_name)
            if definition is None:
                continue
            recommendation = Recommendation(
                skill=definition.name,
                description=definition.description,
                category=definition.category,
                phase=definition.phase,
                hermes_role=definition.hermes_role,
                handoff_policy=definition.handoff_policy,
                reasoning_demand=definition.reasoning_demand,
                score=0,
                confidence="low",
                matched=(),
                why=_FALLBACK_WHY,
                next_action=_next_action(definition),
                evidence_boundary=_evidence_boundary(definition),
                wrapper_guidance=_wrapper_guidance(definition),
                suggested_prompt=_suggested_prompt(definition.name, query),
            )
            by_skill[skill_name] = recommendation
            expanded.append(recommendation)
    return expanded


def _apply_guardrail_reranking(
    recommendations: list[Recommendation],
    *,
    guards: tuple[RoutingGuardRule, ...],
) -> list[Recommendation]:
    if not guards:
        return recommendations
    reranked = []
    for recommendation in recommendations:
        reranked.append(_apply_guard_rules_to_recommendation(recommendation, guards))
    return reranked


def _has_strong_named_catalog_owner(recommendations: list[Recommendation]) -> bool:
    """Keep generic readiness guards behind a strongly matched named workflow.

    This is catalog evidence, not a product-name keyword branch: every
    routable definition gets the same threshold and exact-name requirement.
    """

    for recommendation in recommendations:
        names = {label.removeprefix("name:") for label in recommendation.matched if label.startswith("name:")}
        triggers = {
            label.removeprefix("trigger:")
            for label in recommendation.matched
            if label.startswith("trigger:")
        }
        if recommendation.score >= 12 and names and triggers - names:
            return True
    return False


def _apply_guard_rules_to_recommendation(
    recommendation: Recommendation,
    guards: tuple[RoutingGuardRule, ...],
) -> Recommendation:
    updated = recommendation
    for guard in guards:
        if updated.skill in guard.preferred_skills:
            score = updated.score + guard.score_boost
            updated = replace(
                updated,
                score=score,
                confidence=_confidence(score),
                matched=tuple(sorted({*updated.matched, guard.matched_label})),
                why=guard.why,
            )
    return updated


def _apply_guardrail_followup_boundaries(
    recommendations: list[Recommendation],
    guards: tuple[RoutingGuardRule, ...],
) -> list[Recommendation]:
    guard_ids = {guard.id for guard in guards}
    if _RISKY_REFACTOR_GUARD_ID not in guard_ids:
        return recommendations

    return [_risky_refactor_followup_boundary(recommendation) for recommendation in recommendations]


def _risky_refactor_followup_boundary(recommendation: Recommendation) -> Recommendation:
    if recommendation.skill not in _RISKY_REFACTOR_FOLLOWUP_ONLY_SKILLS:
        return recommendation

    score = min(recommendation.score, _RISKY_REFACTOR_FOLLOWUP_SCORE_CAP)
    return replace(
        recommendation,
        score=score,
        confidence=_confidence(score),
        matched=tuple(sorted({*recommendation.matched, _RISKY_REFACTOR_FOLLOWUP_MATCHED})),
        why=_RISKY_REFACTOR_FOLLOWUP_WHY,
        wrapper_guidance=_RISKY_REFACTOR_FOLLOWUP_GUIDANCE_PREFIX + recommendation.wrapper_guidance,
    )


def _prioritize_explicit_skill(
    recommendations: list[Recommendation],
    explicit_skill: str | None,
) -> list[Recommendation]:
    if not explicit_skill:
        return recommendations
    selected = next(
        (recommendation for recommendation in recommendations if recommendation.skill == explicit_skill),
        None,
    )
    if selected is None:
        return recommendations
    return [selected, *[recommendation for recommendation in recommendations if recommendation.skill != explicit_skill]]


def _prioritize_guarded_workflow_learning(recommendations: list[Recommendation]) -> list[Recommendation]:
    selected = next(
        (
            recommendation
            for recommendation in recommendations
            if recommendation.skill == "workflow-learning" and "guard:workflow_learning" in recommendation.matched
        ),
        None,
    )
    if selected is None:
        return recommendations
    return [selected, *[recommendation for recommendation in recommendations if recommendation.skill != "workflow-learning"]]


def _tokens(value: str) -> set[str]:
    return routing_tokens(value, stopwords=_STOPWORDS)


def _strip_path_like_fragments(value: str) -> str:
    neutralized: list[str] = []
    for raw_fragment in value.split():
        fragment = raw_fragment.strip("`'\"“”‘’.,;:!?()[]{}")
        if ("/" in fragment or "\\" in fragment) and normalized_phrase(fragment) not in _COMMAND_TRIGGER_PHRASES:
            neutralized.append(" ")
        else:
            neutralized.append(raw_fragment)
    return " ".join(neutralized)


def _command_trigger_match(query: str, value: str) -> bool:
    return bool(_COMMAND_TRIGGER_PATTERNS[value].search(query))


def _phrase_match(query: str, value: str) -> bool:
    return bool(query and value and (query in value or value in query))


def _trigger_phrase_match(query: str, value: str) -> bool:
    """A trigger fires when the message contains it, never the reverse.

    `_phrase_match` is bidirectional, which is right for description and
    use_when - a short query legitimately appears inside a long prose field.
    For triggers the reverse arm inverts the contract: it makes the message
    `test` match the triggers `npm test`, `cargo test`, `pytest`, and
    `python -m unittest` at +6 apiece, so one ambiguous word scored 73 and
    routed to `command-operator` at high confidence. A trigger is a phrase the
    user is expected to say; a fragment of one is not evidence they said it.
    """
    return bool(query and value and value in query)


def _explicit_phrase_match(query: str, value: str) -> bool:
    return bool(query and value and value in query)


def _adversarial_consensus_explicit_match(normalized_query: str) -> bool:
    return any(
        _explicit_phrase_match(normalized_query, phrase)
        for phrase in _ADVERSARIAL_CONSENSUS_EXPLICIT_PHRASES
    )


def _llm_app_dev_explicit_match(normalized_query: str) -> bool:
    return any(_explicit_phrase_match(normalized_query, phrase) for phrase in _LLM_APP_DEV_EXPLICIT_PHRASES)


def _memory_interview_explicit_match(normalized_query: str) -> bool:
    # "ask" is the ask skill's home vocabulary (name + bare trigger = 15 for
    # any sentence containing the word), so the memory-interview intent —
    # "<verb> your memories ... and ask me ..." — lost to `ask` on every
    # paraphrase except a literal fixture sentence. Possessive memory
    # vocabulary co-occurring with an asking verb is the interview asking the
    # user about their memories, not an advisor question.
    return _phrase_match(normalized_query, "your memories") and _phrase_match(normalized_query, "ask")


def _failure_signal_audit_explicit_match(normalized_query: str) -> bool:
    return any(_explicit_phrase_match(normalized_query, phrase) for phrase in _FAILURE_SIGNAL_AUDIT_EXPLICIT_PHRASES)



_APPLE_DESIGN_SPECIALIST_PHRASES = tuple(
    normalized_phrase(phrase)
    for phrase in (
        "apple design",
        "apple ui design",
        "apple hig",
        "human interface guidelines",
        "ios design guidelines",
        "macos app design",
        "apple-inspired web",
        "liquid glass review",
        "liquid glass design",
        "apple 3d hero",
        "apple-style 3d",
        "apple product render",
        "apple product visual",
        "apple studio lighting",
        "apple-style landing visual",
        "apple product page",
    )
)
_APPLE_DESIGN_PLATFORM_TOKENS = frozenset({"apple", "human", "ios", "macos", "liquid"})


def _apple_design_offers_itself(normalized_query: str, query_tokens: set[str]) -> bool:
    """Require an explicit Apple design or product-visual phrase, not a product-name or glass token alone."""
    return bool(query_tokens & _APPLE_DESIGN_PLATFORM_TOKENS) and contains_cue_phrase(
        normalized_query, _APPLE_DESIGN_SPECIALIST_PHRASES
    )


def _accessibility_audit_explicit_match(normalized_query: str) -> bool:
    return any(_explicit_phrase_match(normalized_query, phrase) for phrase in _ACCESSIBILITY_AUDIT_EXPLICIT_PHRASES)


def _build_failure_triage_explicit_match(normalized_query: str) -> bool:
    return any(_explicit_phrase_match(normalized_query, phrase) for phrase in _BUILD_FAILURE_TRIAGE_EXPLICIT_PHRASES)


def _build_failure_triage_fixed_or_pass_verification_context(normalized_query: str) -> bool:
    if any(_explicit_phrase_match(normalized_query, phrase) for phrase in _BUILD_FAILURE_TRIAGE_OVERRIDE_PHRASES):
        return False
    has_fixed_or_pass = any(_explicit_phrase_match(normalized_query, phrase) for phrase in _FIXED_OR_PASS_PHRASES)
    has_verify_or_merge = any(
        _explicit_phrase_match(normalized_query, phrase) for phrase in _VERIFY_OR_MERGE_READY_PHRASES
    )
    has_build_or_check_context = any(
        _explicit_phrase_match(normalized_query, phrase) for phrase in _BUILD_OR_CHECK_CONTEXT_PHRASES
    )
    return has_fixed_or_pass and (has_verify_or_merge or has_build_or_check_context)


def _harness_session_inventory_recommendation_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if any(
        _explicit_phrase_match(normalized_query, normalized_phrase(phrase))
        for phrase in _HARNESS_SESSION_INVENTORY_INTENT_PHRASES
    ):
        return True
    has_inventory_intent = bool(query_tokens & _HARNESS_SESSION_INVENTORY_INTENT_TOKENS)
    has_harness_context = bool(query_tokens & _HARNESS_SESSION_INVENTORY_CONTEXT_TOKENS)
    return has_inventory_intent and has_harness_context


def _confidence(score: int) -> str:
    if score >= 8:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def _why(matched: tuple[str, ...]) -> str:
    if not matched:
        return _FALLBACK_WHY
    sources = sorted({item.split(":", 1)[0] for item in matched})
    labels = [_match_source_label(source) for source in sources]
    return f"Matched {_human_join(labels)} for this task."


def _humanize_recommendation_reason(reason: str) -> str:
    text = reason.strip()
    guard_prefix = "Matched guard/trigger metadata; "
    if text.startswith(guard_prefix):
        return _capitalize_sentence(text[len(guard_prefix) :])
    if text == "Matched trigger metadata for this task.":
        return "Matched workflow trigger language for this task."
    if text == "Matched metadata metadata for this task.":
        return "Matched catalog keywords for this task."
    return text


def _capitalize_sentence(value: str) -> str:
    text = value.strip()
    if not text:
        return text
    return text[:1].upper() + text[1:]


def _match_source_label(source: str) -> str:
    return {
        "category": "workflow category",
        "description": "catalog description",
        "locale": "deterministic multilingual hint",
        "metadata": "catalog keywords",
        "name": "workflow name",
        "phase": "workflow phase",
        "trigger": "workflow trigger language",
        "use_when": "catalog use-when guidance",
    }.get(source, source.replace("_", " "))


def _human_join(items: list[str]) -> str:
    unique_items = list(dict.fromkeys(item for item in items if item))
    if not unique_items:
        return "catalog signals"
    if len(unique_items) == 1:
        return unique_items[0]
    if len(unique_items) == 2:
        return f"{unique_items[0]} and {unique_items[1]}"
    return f"{', '.join(unique_items[:-1])}, and {unique_items[-1]}"


def _suggested_prompt(skill: str, query: str) -> str:
    return f"Use {skill} for: {query}"


def _policy_for(definition: SkillDefinition) -> RecommendationPolicy:
    return (
        _SKILL_POLICIES.get(definition.name)
        or _CATEGORY_POLICIES.get(definition.category)
        or _HERMES_ROLE_POLICIES.get(definition.hermes_role)
        or _DEFAULT_POLICY
    )


def _next_action(definition: SkillDefinition) -> str:
    return _policy_for(definition).next_action


def _evidence_boundary(definition: SkillDefinition) -> str:
    return _policy_for(definition).evidence_boundary


def _wrapper_guidance(definition: SkillDefinition) -> str:
    return _policy_for(definition).wrapper_guidance


def _ops_observability_card_offers_itself(normalized_query: str, query_tokens: set[str]) -> bool:
    return not (
        ops_observability_external_blocked(normalized_query)
        or ops_observability_generic_metrics_blocked(normalized_query, query_tokens)
        or _public_plugin_connector_readiness_match(normalized_query)
        or _skill_scout_candidate_alias_intent_match(normalized_query)
    )


def _build_failure_triage_offers_itself(normalized_query: str, query_tokens: set[str]) -> bool:
    return not _build_failure_triage_fixed_or_pass_verification_context(normalized_query)


def _context_alignment_offers_itself(normalized_query: str, query_tokens: set[str]) -> bool:
    """Keep generic uses of "context" from offering the terminology workflow."""
    return (
        "budget" not in query_tokens
        and "project" in query_tokens
        and bool({"terminology", "terms"} & query_tokens)
        and bool({"align", "alignment", "review"} & query_tokens)
    )


def _codebase_uml_offers_itself(normalized_query: str, query_tokens: set[str]) -> bool:
    """Keep prose about architecture from offering the diagram workflow.

    The skill's description and metadata carry ordinary planning words
    ("architecture", "codebase", "picture"), so a bare "architecture" scored it
    level with `ralplan` on field matches alone. It offers itself only when the
    message is diagram-shaped: a diagram/UML token, a visualize verb aimed at
    code, or draw/picture aimed at the codebase. Explicit invocation overrides
    this, as `_score_definition` already exempts.
    """
    if {"uml", "plantuml", "diagram", "diagrams", "다이어그램"} & query_tokens:
        return True
    if any(token.startswith("시각화") for token in query_tokens):
        return True
    code_target = bool({"architecture", "code", "codebase", "repo", "repository"} & query_tokens)
    if code_target and {"visualize", "visualise", "visualization", "visualisation"} & query_tokens:
        return True
    return bool({"architecture", "codebase"} & query_tokens) and bool({"draw", "picture"} & query_tokens)
def _frontend_refactor_offers_itself(normalized_query: str, query_tokens: set[str]) -> bool:
    """Keep generic refactor talk from offering the UI refactor workflow.

    "Refactor", "state", and "split" are every coding request's words; the
    skill offers itself only when the message is UI-shaped - a component/hook
    vocabulary token, a UI framework name, or the skill's own name. Explicit
    invocation overrides this, as `_score_definition` already exempts.
    """
    ui_tokens = {
        "component",
        "components",
        "hook",
        "hooks",
        "useeffect",
        "useeffects",
        "usestate",
        "react",
        "vue",
        "svelte",
        "frontend",
        "front-end",
        "ui",
        "props",
        "prop",
        "jsx",
        "tsx",
        "컴포넌트",
        "프론트엔드",
    }
    return bool(ui_tokens & query_tokens)


def _refactor_plan_offers_itself(normalized_query: str, query_tokens: set[str]) -> bool:
    """Keep single-word refactor or plan talk from offering the phase planner.

    The skill offers itself only when the message carries both halves of its
    intent - restructuring vocabulary AND planning vocabulary - or the
    unambiguous "phased". Explicit invocation overrides this, as
    `_score_definition` already exempts.
    """
    restructure = {"refactor", "refactoring", "restructure", "restructuring", "리팩터링", "리팩토링"}
    planning = {"plan", "planning", "phases", "phase", "phased", "rollback", "계획", "단계"}
    if "phased" in query_tokens:
        return True
    return bool(restructure & query_tokens) and bool(planning & query_tokens)


def _jit_learn_offers_itself(normalized_query: str, query_tokens: set[str]) -> bool:
    """Keep a bare "learn" from carrying the just-in-time learning route.

    The catalog triggers tokenize `learn next` and `learn now` down to a bare
    `learn`, which is also `workflow-learning`'s, `paper-learning`'s, and
    `curriculum-design`'s word. `jit-learn` only offers itself when the message
    actually asks what to learn for a live problem: its own guard cues, or an
    explicit invocation, which `_score_definition` already exempts.
    """
    return jit_learn_guard_applies(normalized_query, query_tokens)


def _omh_docs_offers_itself(normalized_query: str, query_tokens: set[str]) -> bool:
    del query_tokens
    if _explicit_skill_candidate_is_negated(normalized_query, "omh-docs", "product-docs"):
        return False
    return is_omh_docs_question(normalized_query)


# Skills that withdraw from the shortlist unless their own precondition holds,
# checked in `_score_definition`. An explicit invocation always overrides this:
# naming a skill outright is the user overruling its self-assessment.
#
# This is a table because it was a table already - seven hand-written copies of
# one conditional inside the function that scores every skill, which is where
# `docs/ADDING-A-SKILL.md` did not think to send anyone. Two entries are phrased
# as blockers upstream and keep that phrasing in the wrappers above rather than
# being rewritten, so the predicates here are the same ones as before.
_SKILL_OFFERS_ITSELF: dict[str, Callable[[str, set[str]], bool]] = {
    "apple-design": _apple_design_offers_itself,
    "codebase-uml": _codebase_uml_offers_itself,
    "context": _context_alignment_offers_itself,
    "product-docs": _omh_docs_offers_itself,
    "refactor-plan": _refactor_plan_offers_itself,
    "frontend-refactor": _frontend_refactor_offers_itself,
    "jit-learn": _jit_learn_offers_itself,
    "ops-observability-card": _ops_observability_card_offers_itself,
    "harness-session-inventory": _harness_session_inventory_recommendation_applies,
    "build-failure-triage": _build_failure_triage_offers_itself,
    "media-input-operator": media_input_operator_guard_applies,
    "external-connector-readiness": _external_connector_readiness_recommendation_applies,
    "prompt-import-readiness": _prompt_import_readiness_recommendation_applies,
    "physical-device-readiness": _physical_device_readiness_recommendation_applies,
}
