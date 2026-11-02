"""Canonical `decision-prototype` skill data (issue #1371).

Pure catalog data. This module exports one `SkillDefinition` for the bounded
decision-prototype workflow: turn one high-impact uncertainty into a
disposable, isolated experiment whose observed result feeds planning without
becoming implementation.

`catalog_definitions.py` imports this module as the single installed definition
source. It describes bounded human or executor-guided work only; it does not
execute, validate, or persist an artifact.
"""

from __future__ import annotations

from .catalog_types import (
    ExpertQuestion,
    HermesSkillLine,
    ProcedureCheck,
    ProcedureStep,
    SkillDefinition,
    SkillExample,
)

DECISION_PROTOTYPE_ARTIFACT = "decision_prototype/v1"

_DECISION_QUESTION = "decision question"
_EXPERIMENT_BUDGET = "experiment budget"
_SCRATCH_BOUNDARY = "scratch boundary"
_MEASUREMENT_METHOD = "measurement method"

_PREPARED_HANDOFF = "prepared prototype handoff with exact commands and expected observations"
_OBSERVATION_LEDGER = "observation ledger separating observed outputs from interpretation and confidence"
_DECISION_RECEIPT = "decision receipt for planning with supported option, rejected option, residual risk, and evidence limits"

DEFINITION = SkillDefinition(
    "decision-prototype",
    "Uncertain technical choice for a spike: bounded decision prototype workflow: resolve one uncertain interaction, API, performance, or integration choice with a disposable, isolated experiment whose observed result feeds planning.",
    (
        "decision-prototype",
        "$decision-prototype",
        "decision prototype",
        "prototype this uncertain choice before planning",
        "prototype before planning",
        "prototype the uncertain choice",
        "run a small spike",
        "small spike",
        "spike solution",
        "decision spike",
        "feasibility spike",
        "test the risky assumption first",
        "test the risky assumption",
        "throwaway prototype",
        "disposable prototype",
        "timing probe",
        "api probe",
    ),
    "Use when discussion cannot settle one interaction, API, performance, or integration choice and a cheap reversible experiment can answer it before planning; refuse unbounded or multi-feature experiments and ask for or derive one falsifiable decision question.",
    category="planning",
    phase="decision-prototype",
    hermes_role="retained-cognition",
    delegation_boundary="retained-catalog-intent",
    handoff_policy=(
        "Keep the decision question, hypothesis, budget, scratch boundary, measurement method, and decision receipt in Hermes. "
        "When a selected executor or runtime (Codex, Claude Code, Hermes runtime/handoff, or a generic executor) will run the experiment, "
        "prepare an executor-neutral handoff with exact commands and expected observations; it stays `prepared_not_observed` until observed outputs exist. "
        "A prototype result is decision grounding only: promotion into production requires a separate accepted `ralplan` plan and its own implementation handoff."
    ),
    required_inputs=(_DECISION_QUESTION, _EXPERIMENT_BUDGET, _SCRATCH_BOUNDARY, _MEASUREMENT_METHOD),
    expert_questions=(
        ExpertQuestion(
            _DECISION_QUESTION,
            "Which single decision should this prototype settle, which alternatives are in play, and what observable result would falsify the preferred option?",
            "이 프로토타입으로 결정할 단일 의사결정은 무엇이고, 어떤 대안들이 있으며, 어떤 관찰 결과가 나오면 선호 옵션이 틀렸다고 볼 수 있나요?",
        ),
        ExpertQuestion(
            _EXPERIMENT_BUDGET,
            "What time, tool, file, and command budget bounds the experiment, and which stop condition ends it even without an answer?",
            "이 실험을 제한하는 시간, 도구, 파일, 명령 예산은 무엇이고, 답이 없더라도 실험을 끝내는 중단 조건은 무엇인가요?",
        ),
        ExpertQuestion(
            _SCRATCH_BOUNDARY,
            "Which scratch directory or temporary worktree receives every write, which executor or runtime is available, and does any write outside that boundary have explicit approval?",
            "모든 쓰기가 들어갈 스크래치 디렉터리 또는 임시 워크트리는 무엇이고, 어떤 실행기나 런타임을 사용할 수 있으며, 그 경계 밖 쓰기에 명시적 승인이 있나요?",
        ),
        ExpertQuestion(
            _MEASUREMENT_METHOD,
            "How will the result be measured, which target user or task applies when usability is involved, and which fixture or sample limits how far the result generalizes?",
            "결과를 어떻게 측정하고, 사용성이 걸린 경우 대상 사용자나 과제는 무엇이며, 어떤 픽스처나 샘플이 결과의 일반화 범위를 제한하나요?",
        ),
    ),
    expected_outputs=(
        DECISION_PROTOTYPE_ARTIFACT,
        _PREPARED_HANDOFF,
        _OBSERVATION_LEDGER,
        _DECISION_RECEIPT,
    ),
    procedure_checks=(
        ProcedureCheck(
            "prototype_scope_check",
            ("decision_id", "decision_question", "alternatives", "hypothesis_falsifiable", "target_user_task", "scope_disposition"),
            "PASS only when exactly one decision question carries a stable decision id, at least two alternatives, and a falsifiable hypothesis; otherwise HOLD, refuse the unbounded or multi-feature experiment, and ask for or derive one question.",
        ),
        ProcedureCheck(
            "prototype_budget_isolation_check",
            ("time_budget", "tool_budget", "file_budget", "command_budget", "executor_runtime", "capability_limits", "workspace_identity", "write_boundary_status"),
            "Record every budget with a unit, the selected executor or runtime and its observed capability limits, and the scratch directory or temporary worktree identity; HOLD when a write would leave that boundary without explicit user approval or when the observed workspace does not match the declared one.",
        ),
        ProcedureCheck(
            "prototype_smallest_artifact_check",
            ("artifact_kind", "measurement_method", "stop_conditions", "fixture_data_class", "expansion_refused"),
            "Choose the smallest artifact that can answer the question (wireframe, CLI spike, API probe, fixture, timing probe, test harness, or mocked interaction), use synthetic fixtures by default, and refuse expansion into general feature implementation.",
        ),
        ProcedureCheck(
            "prototype_execution_evidence_check",
            ("execution_status", "observed_outputs", "evidence_refs", "interpretation", "confidence", "unresolved_questions"),
            "When no executor is available, emit the prepared handoff and report results as unobserved; when execution occurred, record only observed outputs and bounded evidence references, keep interpretation and confidence separate, and mark timeout or inconclusive runs as such; tool success is never product validation.",
        ),
        ProcedureCheck(
            "prototype_cleanup_receipt_check",
            ("keep_discard_decision", "cleanup_status", "supported_option", "rejected_option", "residual_risk", "evidence_limits", "prototype_code_reference_permission", "promotion_status"),
            "Report `discarded` only after cleanup is observed and record cleanup failure distinctly; the receipt names the supported option, rejected option, residual risk, evidence limits, and whether prototype code may be referenced, and promotion stays blocked until a separate accepted plan and implementation handoff exist.",
        ),
    ),
    procedure_steps=(
        ProcedureStep(
            "prototype_frame_decision", "analysis", (_DECISION_QUESTION, _MEASUREMENT_METHOD),
            (DECISION_PROTOTYPE_ARTIFACT,), ("prototype_scope_check",),
            "Reduce the uncertainty to one decision question with a stable decision id, the alternatives, a falsifiable hypothesis, and the target user or task when usability is involved; refuse or split anything broader before spending budget.",
        ),
        ProcedureStep(
            "prototype_bound_experiment", "analysis", (_EXPERIMENT_BUDGET, _SCRATCH_BOUNDARY, _MEASUREMENT_METHOD),
            (DECISION_PROTOTYPE_ARTIFACT,), ("prototype_budget_isolation_check", "prototype_smallest_artifact_check"),
            "Fix the time, tool, file, and command budget, declare the scratch directory or temporary worktree, name the executor or runtime and its capability limits, and pick the smallest artifact plus measurement method and stop conditions.",
        ),
        ProcedureStep(
            "prototype_prepare_handoff", "production", (_EXPERIMENT_BUDGET, _SCRATCH_BOUNDARY, _MEASUREMENT_METHOD),
            (_PREPARED_HANDOFF,), ("prototype_budget_isolation_check", "prototype_smallest_artifact_check"),
            "Write the exact commands, expected observations, workspace identity, and stop conditions as an executor-neutral handoff; production files are read-only inputs and no result is filled in before it is observed.",
        ),
        ProcedureStep(
            "prototype_record_observations", "validation", (_EXPERIMENT_BUDGET, _MEASUREMENT_METHOD),
            (_OBSERVATION_LEDGER,), ("prototype_execution_evidence_check",),
            "Ingest only observed outputs and bounded evidence references, then derive interpretation, confidence, and unresolved questions in separate fields; an unavailable executor, timeout, or inconclusive run is recorded as that state, never as a result.",
        ),
        ProcedureStep(
            "prototype_close_receipt", "validation", (_DECISION_QUESTION, _EXPERIMENT_BUDGET, _SCRATCH_BOUNDARY, _MEASUREMENT_METHOD),
            (_DECISION_RECEIPT, DECISION_PROTOTYPE_ARTIFACT),
            ("prototype_scope_check", "prototype_budget_isolation_check", "prototype_smallest_artifact_check", "prototype_execution_evidence_check", "prototype_cleanup_receipt_check"),
            "Decide keep or discard, observe cleanup before reporting `discarded`, and close with a compact decision receipt that `ralplan` can consume without transcript replay and without any implementation handoff.",
        ),
    ),
    artifact_expectations=(
        "prepared decision_prototype/v1 record when a wrapper captures it: decision id and question, alternatives, hypothesis, target user or task, time/tool/file/command budget, executor or runtime and capability limits, scratch workspace identity, measurement method, stop conditions, observed results, interpretation, confidence, unresolved questions, keep or discard decision, and cleanup status",
        "prepared prototype handoff carrying exact commands and expected observations; it stays prepared_not_observed until a separate observation records outputs",
        "declared scratch workspace identity compatible with the existing worktree_session_isolation/v1 guidance when a temporary worktree is used",
        "metadata-only evidence references for executed runs; raw outputs, secrets, user data, and transcripts stay out of the record",
    ),
    safety_rules=(
        "Refuse an experiment that answers more than one decision question or has no falsifiable hypothesis; ask for or derive one question before spending budget.",
        "Read existing production files freely, but write only inside the declared scratch directory or temporary worktree unless the user explicitly approves a different boundary.",
        "Do not manufacture results: without an available executor the output is a prepared handoff and every result field reads unobserved.",
        "Executor or tool success is not product validation; keep measured observations, assumptions, and derived interpretation in separate fields.",
        "Use synthetic fixtures by default and keep secrets and user data out of the record; preserve only bounded metadata and safe evidence references.",
        "Destructive experiments, paid services, external publication, and irreversible side effects require the existing authority and approval gates before any command runs.",
        "No prototype code enters a production branch or implementation handoff without a separate accepted plan; the receipt only states whether prototype code may be referenced.",
        "Report `discarded` only after cleanup is observed; a failed or pending cleanup stays visible in the artifact.",
    ),
    quality_tier="decision-gated",
    quality_bar=(
        "Name the decision id, question, alternatives, hypothesis, budget, scratch boundary, measurement method, and stop conditions before any command is prepared.",
        "Select the smallest artifact that can answer the question and state why a larger one was not needed.",
        "Separate prepared handoff, observed outputs, interpretation, confidence, and cleanup state as distinct evidence states.",
        "Preserve the declared task, fixture, environment, and sample limits so the result is not generalized beyond them.",
        "End with a decision receipt that `ralplan` can consume: supported option, rejected option, residual risk, evidence limits, and prototype-code reference permission.",
        "When the question is about logic or state, or about an interaction or layout, or the receipt may let later work reference the prototype code, load `references/artifact-shapes.md`: a pure module a plan can lift with the full state shown after each action, structurally different variants mounted in the real host page, and kept code on a named throwaway ref.",
    ),
    why_this_exists=(
        "`decision-prototype` exists so one empirical uncertainty can be settled by a bounded, disposable experiment instead of endless interviewing or an experiment hidden inside production work; "
        "it records observed results apart from interpretation and feeds planning a receipt without claiming the prototype is implementation-ready."
    ),
    do_not_use_when=(
        "$context is the explicit-only route for a repository terminology or product decision frontier (`context`); preference or policy decisions that behavior cannot test stay with `deep-interview`.",
        "$context is the explicit-only route for unresolved repository terminology or project language (`context`); hand only an empirical decision here.",
        "The decision is already made and the request is an implementation plan with acceptance criteria; use `ralplan` and consume the decision receipt there.",
        "The user wants the feature built, reviewed, or shipped rather than one question answered; use `ultrawork` after an accepted plan.",
        "The request is UI creation, redesign, or polish of a real surface rather than a throwaway wireframe that answers one interaction question; use `frontend`.",
        "The request is a premium content, layout, or visual quality gate on deliverables; use `design-quality-gate`.",
        "The uncertainty is whether customers have the problem or would adopt the solution, which needs customer evidence rather than a technical or interaction spike; use `product-discovery-validation`.",
        "The request needs QA certification, production-readiness evidence, or a performance baseline for release; prototype results do not generalize beyond their declared fixture and environment.",
        HermesSkillLine(
            "The user wants an idea's feasibility probed across several questions with throwaway spikes, with no single decision for a plan to consume; load Hermes' bundled `spike` skill instead of this one.",
            ("spike",),
        ),
    ),
    good_example=SkillExample(
        prompt="Run a small spike to check whether the streaming API can hold 500 concurrent connections on one worker before we plan the migration.",
        expected="Frame one decision question with a stable id, bound the budget and scratch worktree, prepare a timing probe with exact commands and expected observations, record only observed results, and close with a decision receipt for planning.",
        why="One empirical uncertainty blocks planning and a cheap, reversible, isolated probe can answer it without building the migration.",
    ),
    bad_example=SkillExample(
        prompt="decision-prototype build the whole notifications feature as a prototype and merge it if it works.",
        expected="Refuse the multi-feature scope, ask for the one decision the prototype should settle, and route accepted implementation to `ralplan` then `ultrawork`.",
        why="A general feature build is not a bounded experiment, and a successful prototype is never promoted without a separate accepted plan.",
    ),
    final_checklist=(
        "Exactly one decision question with a stable decision id, alternatives, and a falsifiable hypothesis is recorded, or the request was refused with the missing question named.",
        "Time, tool, file, and command budgets carry units, and the scratch directory or temporary worktree identity matches the observed workspace.",
        "The artifact kind is the smallest that can answer the question, and any expansion into feature implementation was refused.",
        "Execution status is one of prepared_not_observed, observed, timeout, or inconclusive; observed outputs, evidence references, interpretation, and confidence sit in separate fields.",
        "Cleanup is observed before `discarded` is reported, and a cleanup failure is recorded distinctly.",
        "The decision receipt names the supported option, rejected option, residual risk, evidence limits, and prototype-code reference permission, and no implementation handoff was prepared from it.",
    ),
    recovery_notes=(
        "If the request spans several decisions or has no falsifiable hypothesis, HOLD and ask for or derive the single question instead of running anything.",
        "If no executor, temporary worktree, browser tool, or device is available, emit the prepared handoff with exact commands and expected observations and report every result as unobserved.",
        "If the observed workspace differs from the declared scratch boundary, stop before the first write and report the mismatch as a blocker.",
        "If the time or command budget runs out, record `timeout` with whatever was observed so far and leave interpretation as unresolved questions.",
        "If observations do not falsify or support the hypothesis, record `inconclusive` with the evidence limits rather than choosing an option.",
        "If cleanup fails, keep the artifact at its last observed cleanup state, name the residual scratch identity, and never report `discarded`.",
        "If the user asks to ship the prototype, summarize the receipt and route to `ralplan`; promotion needs an accepted plan and its own implementation handoff.",
    ),
    progressive_disclosure=True,
    situations=(
        "try both libraries quickly before deciding",
        "throwaway experiment to test performance",
        "will this api work for us",
        "quick proof of concept for one question",
        "spike before we plan",
    ),
)
