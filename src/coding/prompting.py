from __future__ import annotations

from typing import Iterable, Mapping, cast

from ..coding_contracts import (
    EXECUTOR_PROMPTING_CONTRACT_SCHEMA_VERSION,
    EXECUTOR_PROMPTING_REQUIRED_SECTIONS,
    EXECUTOR_PROMPTING_STRATEGIES,
    EXECUTOR_STEERING_DELTA_CONTRACT_SCHEMA_VERSION,
    STRUCTURAL_SEARCH_DISCIPLINE_CONTRACT_SCHEMA_VERSION,
    STRUCTURAL_SEARCH_DISCIPLINE_GUIDANCE,
)
from .throughput_prompting import build_throughput_overlay


_RISK_AWARE_CUES = (
    "risky",
    "refactor",
    "migration",
    "security",
    "auth",
    "payment",
    "breaking change",
    "data loss",
    "production",
)
_STEERING_DELTA_FIELDS = (
    "changed_constraint",
    "new_evidence",
    "required_action",
    "verification_target_changed",
)
# A named required artifact, not an advisory phrase: "consult docs first" is
# skippable, while a report block a reviewer can grep for is checkable. The
# always-present rule (entries or the explicit none line) keeps the check
# deterministic without OMH guessing at dispatch time whether a task is
# SDK-touching.
DOCS_CONSULTED_ARTIFACT_POLICY = (
    "Docs consulted artifact: when the task touches an SDK, framework, or external library API, "
    "read the official documentation before coding against it and record each source as an exact URL "
    "(prefer the framework's llms.txt index when one exists) plus the version consulted. "
    "The final report must contain a `Docs consulted:` block listing those URL+version entries; "
    "for SDK-touching work a report without this block is incomplete. When no SDK or framework is "
    "touched, the block must state `Docs consulted: none (no SDK/framework surface touched)`."
)
# The compaction-proven structured summary shape: six named sections plus two
# cumulative file lists. One recommended shape for every summary surface —
# prepared-handoff briefs, session summaries, continuation re-briefs — so a
# fresh or resumed session rebuilds working state without re-discovering the
# repository, and so a summary's completeness is checkable by section name
# instead of read as freeform prose.
STRUCTURAL_SEARCH_DISCIPLINE_CLAIM_BOUNDARY = (
    "This is prepared search-discipline guidance only; it is not dispatch, execution, verification, "
    "review, CI, or merge evidence."
)
SESSION_SUMMARY_SHAPE_POLICY = (
    "Session summary shape: when producing a session summary, prepared-handoff brief, or "
    "continuation re-brief, structure it as Goal / Constraints and Preferences / Progress "
    "(Done, In Progress, Blocked) / Key Decisions / Next Steps / Critical Context, plus "
    "explicit read-files and modified-files lists. Carry both file lists forward cumulatively "
    "across successive summaries. A summary in this shape remains a report; it is never "
    "execution, verification, review, CI, or merge evidence."
)
# The layout half of the same problem. SESSION_SUMMARY_SHAPE_POLICY says which
# sections a summary carries; it says nothing about what survives when the
# history does not fit the budget. Foveation answers that with arithmetic
# rather than taste: both temporal edges verbatim, the middle degraded,
# oldest-middle dropped first, the drop stated, and every summary re-planned
# from the original source so lossy layers never stack.
HISTORY_FOVEATION_POLICY = (
    "History foveation: when the history does not fit the budget of a summary, prepared-handoff "
    "brief, or continuation re-brief, keep both temporal edges verbatim -- the oldest turns that "
    "set the goal, constraints, and decisions, and the newest turns that hold current working "
    "state -- and compress the middle instead. When the compressed middle still exceeds the "
    "budget, drop the oldest part of the middle first and state what was dropped, naming the "
    "dropped span and how much of it was dropped. Re-plan every summary from the original "
    "source, never from an earlier summary, so successive re-briefs do not stack lossy layers. "
    "An unstated drop is missing evidence, not a shorter summary."
)
# Rides the Expected result section only when acceptance criteria exist.
ACCEPTANCE_SCOPING_LINE = (
    "Finished means every acceptance criterion above holds; be exhaustive on those, not beyond them."
)


def build_executor_prompting_contract(
    profile: str,
    *,
    intent: str,
    message: str,
    has_plan_artifact: bool,
    plan_artifact_status: str = "",
    isolation_plan: Mapping[str, object] | None = None,
    recommended_workflow: str = "",
    main_agent_model: str = "",
) -> dict[str, object]:
    """Describe a deterministic executor prompt without storing the task itself."""
    strategy = select_executor_prompting_strategy(
        intent=intent,
        message=message,
        has_plan_artifact=has_plan_artifact,
        isolation_plan=isolation_plan,
    )
    contract: dict[str, object] = {
        "schema_version": EXECUTOR_PROMPTING_CONTRACT_SCHEMA_VERSION,
        "profile": profile,
        "status": "prepared_not_observed",
        "intent": intent,
        "strategy": strategy,
        "task_source": _task_source(has_plan_artifact, plan_artifact_status),
        "required_sections": list(EXECUTOR_PROMPTING_REQUIRED_SECTIONS),
        "repository_first_policy": (
            "Inspect the repository, project instructions, and current diff before editing; reconcile the request with observed code facts."
        ),
        "docs_consulted_policy": DOCS_CONSULTED_ARTIFACT_POLICY,
        "uncertainty_policy": (
            "When a missing fact changes scope, safety, or verification, ask one focused question or state the smallest reversible assumption before editing."
        ),
        "verification_policy": (
            "Name focused verification before edits, run the smallest relevant checks after edits, and report commands with outcomes instead of inferred success."
        ),
        "reporting_policy": (
            "Report progress, changed files, tests, blockers, evidence refs, local_capabilities_used, local_capability_evidence_refs, and local_capability_fallback_reason; distinguish prepared guidance from observed executor results."
        ),
        "session_summary_policy": SESSION_SUMMARY_SHAPE_POLICY,
        "history_foveation_policy": HISTORY_FOVEATION_POLICY,
        "structural_search_discipline": {
            "schema_version": STRUCTURAL_SEARCH_DISCIPLINE_CONTRACT_SCHEMA_VERSION,
            "status": "prepared_not_observed",
            "guidance": STRUCTURAL_SEARCH_DISCIPLINE_GUIDANCE,
            "claim_boundary": STRUCTURAL_SEARCH_DISCIPLINE_CLAIM_BOUNDARY,
        },
        "steering_delta_contract": {
            "schema_version": EXECUTOR_STEERING_DELTA_CONTRACT_SCHEMA_VERSION,
            "status": "prepared_not_observed",
            "required_fields": list(_STEERING_DELTA_FIELDS),
            "action_rule": (
                "Send only changed constraints, new evidence, required action, and changed verification "
                "target to an active executor turn. When a full re-brief is needed instead of a delta — a "
                "fresh session, a replaced executor, or a compacted context — send a session summary in "
                "the recommended structured summary shape rather than an oversized delta."
            ),
            "claim_boundary": "A prepared steering delta is not dispatch, execution, verification, review, CI, or merge evidence.",
        },
        "steering_delta_template": steering_delta_template(),
        "claim_boundary": (
            "This is prepared executor-prompt guidance only; it is not dispatch, execution, verification, review, CI, or merge evidence."
        ),
    }
    throughput_overlay = build_throughput_overlay(
        profile,
        main_agent_model=main_agent_model,
        recommended_workflow=recommended_workflow,
    )
    if throughput_overlay:
        contract["throughput_overlay"] = throughput_overlay
    return contract


def select_executor_prompting_strategy(
    *,
    intent: str,
    message: str,
    has_plan_artifact: bool,
    isolation_plan: Mapping[str, object] | None = None,
) -> str:
    if has_plan_artifact:
        return "plan_backed_change"
    if intent in {"review", "diagnostics"}:
        return "review_or_repair"
    lowered = message.casefold()
    isolation = isolation_plan or {}
    risk_level = str(isolation.get("risk_level", "")).casefold()
    if risk_level == "high" or any(cue in lowered for cue in _RISK_AWARE_CUES):
        return "risk_aware_change"
    return "direct_change"


def render_executor_prompt_sections(
    contract: Mapping[str, object],
    *,
    recommended_workflow: str,
    recommended_harness: str,
    acceptance_criteria: Iterable[str],
    verification: Iterable[str],
    review_required: bool,
    task_placeholder: str = "{message}",
    handoff_contract: Mapping[str, object] | None = None,
) -> str:
    """Render the shared execution prompt body from metadata-only contract fields.

    A declared `handoff_contract/v1` reaches the executor here: its forbidden
    actions join the Don't section, each postcondition joins the Test section
    as the command whose exit status is the verdict, and the output shape joins
    the expected result. Without a contract the rendered text is unchanged.
    """
    strategy = str(contract.get("strategy", "direct_change"))
    task_source = str(contract.get("task_source", "original_message_at_dispatch_time"))
    intent = str(contract.get("intent", "unknown"))
    structural_search_discipline = contract.get("structural_search_discipline")
    structural_search_guidance = (
        str(structural_search_discipline.get("guidance", ""))
        if isinstance(structural_search_discipline, Mapping)
        else ""
    ) or STRUCTURAL_SEARCH_DISCIPLINE_GUIDANCE
    do_items = [
        str(contract.get("repository_first_policy", "Inspect the repository before editing.")),
        str(contract.get("docs_consulted_policy", DOCS_CONSULTED_ARTIFACT_POLICY)),
        structural_search_guidance,
        _strategy_instruction(strategy),
        "Implement only the requested scope after repository facts confirm it.",
    ]
    throughput_overlay = contract.get("throughput_overlay")
    if isinstance(throughput_overlay, Mapping) and throughput_overlay.get("status") == "enabled":
        overlay = cast(Mapping[str, object], throughput_overlay)
        rules = overlay.get("rules")
        if isinstance(rules, list):
            typed_rules = cast(list[object], rules)
            do_items.extend(rule for rule in typed_rules if isinstance(rule, str) and rule.strip())
    if review_required:
        do_items.append("Treat review findings as a separate gate and report unresolved risks explicitly.")
    known_context = [
        f"Recommended workflow: `{recommended_workflow}`.",
        f"Recommended harness: `{recommended_harness}`.",
        f"Intent: `{intent}`.",
        _task_source_context(task_source),
    ]
    expected_result = [str(item) for item in acceptance_criteria if str(item).strip()]
    if expected_result:
        # Scoping, not persistence (OpenAI "Prompting GPT-6.2 in Codex" guide,
        # official): say what counts as finished and where to be exhaustive.
        expected_result.append(ACCEPTANCE_SCOPING_LINE)
    else:
        expected_result.append("A scoped change or review result aligned to the request.")
    expected_result.append(
        "A concise report with changed files, verification outcomes, blockers, and evidence refs."
    )
    expected_result.append(
        "A `Docs consulted:` block with exact URL+version entries for any SDK/framework touched, "
        "or its explicit none line; SDK-touching work without it is incomplete."
    )
    if review_required:
        expected_result.append("Review status and any remaining review risk are explicit.")
    test_steps = [str(contract.get("verification_policy", ""))]
    test_steps.extend(str(item) for item in verification if str(item).strip())
    dont_items = [
        "Do not modify unrelated files or overwrite user changes.",
        "Do not claim tests, review, CI, or merge passed without observed evidence.",
        "Do not replace an active task with a broad refactor unless the request or plan requires it.",
    ]
    if handoff_contract is not None:
        _extend_with_handoff_contract(handoff_contract, dont_items, expected_result, test_steps)
    return "\n\n".join(
        (
            _section("Goal", (_strategy_goal(strategy),)),
            _section("Do", do_items),
            _section("Don't", dont_items),
            _section("Known context", known_context),
            _section("Unknowns and decision rule", (str(contract.get("uncertainty_policy", "")),)),
            _section("Expected result", expected_result),
            _section("Test", test_steps),
            _section(
                "Progress and blockers",
                (
                    str(contract.get("reporting_policy", "")),
                    str(contract.get("session_summary_policy", SESSION_SUMMARY_SHAPE_POLICY)),
                    str(contract.get("history_foveation_policy", HISTORY_FOVEATION_POLICY)),
                ),
            ),
            _section("Evidence boundary", (str(contract.get("claim_boundary", "")),)),
            f"Task:\n{task_placeholder}",
        )
    )


def _extend_with_handoff_contract(
    handoff_contract: Mapping[str, object],
    dont_items: list[str],
    expected_result: list[str],
    test_steps: list[str],
) -> None:
    forbidden = handoff_contract.get("forbidden_actions")
    if isinstance(forbidden, list):
        dont_items.extend(f"Forbidden: {item}" for item in forbidden if isinstance(item, str))
    output_shape = handoff_contract.get("output_shape")
    if isinstance(output_shape, Mapping):
        fields = output_shape.get("required_fields")
        field_list = ", ".join(f"`{field}`" for field in fields) if isinstance(fields, list) else ""
        expected_result.append(
            f"A final report in {output_shape.get('format', 'json')} format carrying {field_list}."
        )
    postconditions = handoff_contract.get("postconditions")
    if isinstance(postconditions, list):
        for entry in postconditions:
            if isinstance(entry, Mapping):
                test_steps.append(
                    f"Postcondition `{entry.get('id')}`: run `{entry.get('command')}` and report its exit "
                    "status under that id; the exit status is the verdict, not your description of it."
                )


def steering_delta_template() -> str:
    return (
        "Active-turn steering delta\n\n"
        "Changed constraint:\n{changed_constraint}\n\n"
        "New evidence:\n{new_evidence}\n\n"
        "Required action:\n{required_action}\n\n"
        "Verification target changed:\n{verification_target_changed}\n\n"
        "Apply only this delta. Do not replay the full task or claim progress that has not been observed."
    )


def _strategy_goal(strategy: str) -> str:
    goals = {
        "direct_change": "Deliver the requested bounded change with repository-grounded scope and focused verification.",
        "plan_backed_change": "Implement the accepted plan while checking it against the current repository before each material change.",
        "risk_aware_change": "Reduce change risk first, then make the smallest safe implementation with explicit rollback and verification thinking.",
        "review_or_repair": "Inspect the reported behavior or change, establish evidence, and repair only what the evidence supports.",
    }
    return goals.get(strategy, goals["direct_change"])


def _strategy_instruction(strategy: str) -> str:
    instructions = {
        "direct_change": "Keep the implementation narrow and prefer existing project patterns.",
        "plan_backed_change": "Use accepted plan criteria as the decision source; surface any repository conflict before widening scope.",
        "risk_aware_change": "Identify the affected boundary, preserve rollback options, and verify the highest-risk behavior before reporting success.",
        "review_or_repair": "Reproduce or inspect the relevant evidence before proposing or applying a repair.",
    }
    return instructions.get(strategy, instructions["direct_change"])


def _task_source_context(task_source: str) -> str:
    if task_source == "accepted_plan_artifact":
        return "An accepted plan artifact exists; use its criteria without treating it as proof that implementation already ran."
    if task_source == "draft_plan_artifact":
        return "A draft plan artifact was explicitly allowed; verify unresolved decisions and do not treat it as accepted."
    return "Use the original request only at dispatch time; OMH stores metadata, not the raw task, in durable artifacts."


def _task_source(has_plan_artifact: bool, plan_artifact_status: str) -> str:
    if not has_plan_artifact:
        return "original_message_at_dispatch_time"
    if plan_artifact_status == "draft":
        return "draft_plan_artifact"
    return "accepted_plan_artifact"


def _section(title: str, items: Iterable[str]) -> str:
    lines = [f"- {item}" for item in items if str(item).strip()]
    return f"{title}\n" + "\n".join(lines or ["- No additional detail is prepared."])


__all__ = [
    "ACCEPTANCE_SCOPING_LINE",
    "DOCS_CONSULTED_ARTIFACT_POLICY",
    "HISTORY_FOVEATION_POLICY",
    "SESSION_SUMMARY_SHAPE_POLICY",
    "STRUCTURAL_SEARCH_DISCIPLINE_CLAIM_BOUNDARY",
    "build_executor_prompting_contract",
    "render_executor_prompt_sections",
    "select_executor_prompting_strategy",
    "steering_delta_template",
    "EXECUTOR_PROMPTING_STRATEGIES",
]
