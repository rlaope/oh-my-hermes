from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from typing import Any

from .coding_contracts import CODING_EXECUTOR_TARGETS, EXECUTOR_HANDOFF_SCHEMA_VERSION
from .harness_quality import with_wrapper_actions
from .ingress import CHAT_SOURCES, extract_message_text, extract_source_metadata
from .routing.recommend import recommend_skills
from .skills.catalog import (
    CODING_INTENT_PRIORITY,
    CODING_REVIEW_TERMS,
    coding_intent_for_skill,
    coding_skills_for_intent,
    coding_terms_for_intent,
    harness_quality_contract,
    primary_harness_for_skill,
)


SCHEMA_VERSION = "coding_delegation/v1"
DELEGATION_ACTIONS = ("delegate", "clarify", "fallback")
_RETAINED_HERMES_WORKFLOWS = {
    "deep-interview",
    "web-research",
    "best-practice-research",
    "autoresearch-goal",
    "ultraqa",
    "skill",
    "wiki",
    "cancel",
}


@dataclass(frozen=True)
class CodingDelegation:
    action: str
    intent: str
    recommended_workflow: str
    recommended_harness: str
    executor_profile: str
    acceptance_criteria: tuple[str, ...]
    verification: tuple[str, ...]
    review_required: bool
    review_workflow: str | None
    delegation_prompt_template: str

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["acceptance_criteria"] = list(self.acceptance_criteria)
        data["verification"] = list(self.verification)
        return data


def build_coding_delegation_payload(
    message: str,
    *,
    source: str = "generic",
    limit: int = 3,
    include_message: bool = False,
    source_metadata: dict[str, str] | None = None,
    executor_target: str = "generic",
) -> dict[str, object]:
    message = message.strip()
    if not message:
        raise ValueError("coding delegate requires a task description")
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported coding delegate source: {source}")
    if executor_target not in CODING_EXECUTOR_TARGETS:
        raise ValueError(f"unsupported coding delegate executor: {executor_target}")
    if limit < 1:
        raise ValueError("coding delegate --limit must be at least 1")

    full_recommendations = recommend_skills(message, limit=max(limit, 5))
    recommendations = _compact_recommendations(full_recommendations[:limit])
    top = full_recommendations[0]
    workflow = str(top["skill"])
    score = int(top["score"])
    intent = _intent_for(message, workflow, score)
    action = _action_for(intent, score, workflow)
    if action == "fallback":
        workflow = "oh-my-hermes"
    elif action == "clarify":
        workflow = "oh-my-hermes"
    harness = primary_harness_for_skill(workflow)
    review_required = _review_required(message, intent, workflow)
    delegation = CodingDelegation(
        action=action,
        intent=intent,
        recommended_workflow=workflow,
        recommended_harness=harness,
        executor_profile=_executor_profile(intent, action),
        acceptance_criteria=_acceptance_criteria(intent, action),
        verification=_verification(intent, action),
        review_required=review_required,
        review_workflow="code-review" if review_required else None,
        delegation_prompt_template=_delegation_prompt_template(action, intent, workflow, harness),
    )
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "delegation": delegation.to_dict(),
        "recommendations": recommendations,
    }
    if executor_target != "generic" and delegation.action == "delegate":
        payload["executor_handoff"] = _executor_handoff(executor_target, delegation)
    payload["harness_quality"] = _public_harness_quality(
        harness,
        action=delegation.action,
        has_executor_handoff="executor_handoff" in payload,
    )
    metadata = {key: value for key, value in (source_metadata or {}).items() if value}
    if metadata:
        payload["source_metadata"] = metadata
    if include_message:
        payload["message"] = message
        payload["delegation_prompt"] = str(delegation.delegation_prompt_template).replace("{message}", message)
        handoff = payload.get("executor_handoff")
        if isinstance(handoff, dict) and "prompt_template" in handoff:
            payload["executor_handoff_prompt"] = str(handoff["prompt_template"]).replace("{message}", message)
    return payload


def build_coding_delegation_event_payload(
    event: dict[str, Any] | str,
    *,
    source: str = "generic",
    limit: int = 3,
    include_message: bool = False,
) -> dict[str, object]:
    message = extract_message_text(event)
    return build_coding_delegation_payload(
        message,
        source=source,
        limit=limit,
        include_message=include_message,
        source_metadata=extract_source_metadata(event),
    )


def coding_delegation_record_payload(
    payload: dict[str, object],
    message: str,
    *,
    source_metadata: dict[str, str] | None = None,
) -> dict[str, object]:
    delegation = payload.get("delegation")
    if not isinstance(delegation, dict):
        raise ValueError("coding delegation payload is missing delegation")
    metadata = dict(source_metadata or {})
    payload_metadata = payload.get("source_metadata")
    if isinstance(payload_metadata, dict):
        metadata.update({str(key): str(value) for key, value in payload_metadata.items() if str(value)})
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "coding_delegation",
        "source": payload.get("source", "generic"),
        "action": delegation.get("action", "fallback"),
        "intent": delegation.get("intent", "unknown"),
        "recommended_workflow": delegation.get("recommended_workflow", "oh-my-hermes"),
        "recommended_harness": delegation.get("recommended_harness", "coding-handling"),
        "executor_profile": delegation.get("executor_profile", "router"),
        "review_required": bool(delegation.get("review_required", False)),
        "review_workflow": delegation.get("review_workflow"),
        "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
        "message_length": len(message),
        "source_metadata": metadata,
        "recommendation_evidence": payload.get("recommendations", []),
        "harness_quality": payload.get("harness_quality", {}),
        "executor_handoff": payload.get("executor_handoff"),
        "acceptance_criteria": delegation.get("acceptance_criteria", []),
        "verification": delegation.get("verification", []),
        "status": "prepared_not_observed",
    }


def _intent_for(message: str, workflow: str, score: int) -> str:
    if score == 0:
        return "unknown"
    lowered = message.lower()
    for intent in CODING_INTENT_PRIORITY:
        if workflow in coding_skills_for_intent(intent) or _has_any(lowered, coding_terms_for_intent(intent)):
            return intent
    return coding_intent_for_skill(workflow)


def _action_for(intent: str, score: int, workflow: str) -> str:
    if intent == "unknown":
        return "fallback"
    if workflow in _RETAINED_HERMES_WORKFLOWS:
        return "clarify"
    if score < 4:
        return "clarify"
    return "delegate"


def _review_required(message: str, intent: str, workflow: str) -> bool:
    lowered = message.lower()
    if workflow == "code-review" or intent == "review":
        return True
    return _has_any(lowered, CODING_REVIEW_TERMS)


def _executor_profile(intent: str, action: str) -> str:
    if action == "fallback":
        return "router"
    if action == "clarify":
        return "planner"
    return {
        "planning": "planner",
        "review": "reviewer",
        "diagnostics": "qa-verifier",
        "docs": "docs-writer",
    }.get(intent, "coding-agent")


def _acceptance_criteria(intent: str, action: str) -> tuple[str, ...]:
    if action == "fallback":
        return (
            "Clarify the desired coding outcome before dispatching to an executor.",
            "Do not claim code was implemented or reviewed.",
        )
    if action == "clarify":
        return (
            "Ask the smallest blocking clarification before executor dispatch.",
            "Preserve the original task constraints in the eventual handoff.",
        )
    criteria = {
        "planning": (
            "Produce an execution-ready plan with goals, non-goals, risks, and acceptance criteria.",
            "Identify the verification commands or evidence required before implementation starts.",
        ),
        "review": (
            "Review the referenced code or plan with findings first and concrete evidence.",
            "State clearly when no actionable issue is found.",
        ),
        "diagnostics": (
            "Reproduce or inspect the reported failure before proposing a fix.",
            "Record the smallest evidence that proves the diagnosis.",
        ),
        "docs": (
            "Update documentation to match implemented behavior and known limitations.",
            "Keep examples reproducible and conservative.",
        ),
    }.get(
        intent,
        (
            "Implement only the requested coding change within the discovered scope.",
            "Preserve existing behavior outside the requested change.",
        ),
    )
    return criteria


def _verification(intent: str, action: str) -> tuple[str, ...]:
    if action == "fallback":
        return ("No executor verification until the task is clarified.",)
    if action == "clarify":
        return ("Verify the clarified handoff includes scope, constraints, and stop condition.",)
    checks = {
        "planning": ("Review the plan for testable acceptance criteria.", "Run implementation checks only after execution starts."),
        "review": ("Cite file, diff, command, or test evidence for every finding.",),
        "diagnostics": ("Run the smallest diagnostic or health check that can prove the claim.",),
        "docs": ("Run docs generation/check commands when docs are generated.",),
    }.get(
        intent,
        ("Run targeted tests for the changed behavior.", "Run static or compile checks when available."),
    )
    return checks


def _executor_handoff(executor_target: str, delegation: CodingDelegation) -> dict[str, object]:
    if executor_target != "codex":
        raise ValueError(f"unsupported coding delegate executor: {executor_target}")
    codex_skill = _codex_skill_for_workflow(delegation.recommended_workflow)
    return {
        "schema_version": EXECUTOR_HANDOFF_SCHEMA_VERSION,
        "executor_target": "codex",
        "handoff_mode": "instruction_payload",
        "codex_skill": codex_skill,
        "codex_invocation": {
            "syntax": "$skill",
            "skill": codex_skill,
            "dispatch_text_template": f"{codex_skill} {{message}}",
            "message_placeholder": "{message}",
            "wrapper_note": "Replace {message} only at dispatch time; do not persist the raw task in OMH artifacts.",
        },
        "status": "prepared_not_observed",
        "recording_contract": "prepared_not_observed",
        "dispatch_contract": "wrapper_dispatches_to_codex; omh_does_not_execute_codex",
        "prompt_template": _codex_prompt_template(delegation, codex_skill=codex_skill),
        "execution_brief": {
            "task_source": "original_message_at_dispatch_time",
            "recommended_workflow": delegation.recommended_workflow,
            "recommended_harness": delegation.recommended_harness,
            "intent": delegation.intent,
            "codex_owns": [
                "repository inspection",
                "code edits when needed",
                "tests and verification",
                "commits or PR updates when authorized",
                "executor evidence report",
            ],
            "hermes_owns": [
                "chat intake",
                "plan and status narration",
                "prepared versus observed evidence boundaries",
            ],
        },
        "scope": [
            "Use the original task message as the implementation request.",
            f"Invoke the Codex-side workflow with `{codex_skill}` unless the executor has stronger local routing evidence.",
            "Respect the recommended OMHM workflow and harness metadata.",
            "Keep Hermes-facing status separate from Codex execution evidence.",
        ],
        "non_goals": [
            "Do not claim Hermes implemented the code.",
            "Do not claim review, CI, or merge status without wrapper evidence.",
            "Do not call network services from omh while preparing this handoff.",
        ],
        "acceptance_criteria": list(delegation.acceptance_criteria),
        "verification": list(delegation.verification),
        "review": {
            "required": delegation.review_required,
            "workflow": delegation.review_workflow,
            "evidence_required": "Record separate wrapper/runtime evidence before marking review observed.",
        },
        "report_contract": {
            "allowed_statuses": ["completed", "blocked", "failed"],
            "required_fields": [
                "status",
                "changed_files",
                "commits",
                "tests_run",
                "blockers",
                "evidence_refs",
            ],
            "review_fields": ["review_comments_addressed", "remaining_review_risks"],
        },
        "evidence_contract": {
            "prepared_is_not": ["dispatch", "implementation", "verification", "review", "ci", "merge"],
            "observed_required_for": [
                "executor_dispatch",
                "executor_result",
                "verification",
                "review",
                "ci",
                "merge_readiness",
                "merge",
            ],
        },
        "harness_quality": harness_quality_contract(delegation.recommended_harness),
    }


def _public_harness_quality(harness: str, *, action: str, has_executor_handoff: bool) -> dict[str, object]:
    contract = harness_quality_contract(harness)
    if action == "delegate" and has_executor_handoff:
        return contract
    return with_wrapper_actions(contract, ("show_status",))


def _codex_prompt_template(delegation: CodingDelegation, *, codex_skill: str) -> str:
    return (
        "You are Codex, acting as the coding executor for a Hermes-orchestrated request.\n\n"
        "Executor target: codex\n"
        "Use Codex skill: `{codex_skill}`\n"
        "Codex invocation template: `{codex_skill} {{message}}`\n"
        "Recommended OMHM workflow: `{workflow}`\n"
        "Recommended harness: `{harness}`\n"
        "Intent: `{intent}`\n"
        "Prepared status: `prepared_not_observed`\n\n"
        "Rules:\n"
        "- Implement only after inspecting the repository and confirming the scope.\n"
        "- Preserve unrelated behavior and user changes.\n"
        "- Run targeted verification and report exact evidence.\n"
        "- Do not say Hermes performed the implementation; Hermes prepared this handoff.\n\n"
        "Report back with: status, changed_files, commits, tests_run, blockers, and evidence_refs.\n\n"
        "Task:\n{message}"
    ).format(
        codex_skill=codex_skill,
        workflow=delegation.recommended_workflow,
        harness=delegation.recommended_harness,
        intent=delegation.intent,
        message="{message}",
    )


def _codex_skill_for_workflow(workflow: str) -> str:
    name = workflow.strip() or "oh-my-hermes"
    return name if name.startswith("$") else f"${name}"


def _delegation_prompt_template(action: str, intent: str, workflow: str, harness: str) -> str:
    if action == "fallback":
        return (
            "Use the `oh-my-hermes` router before coding delegation.\n\n"
            "Ask one concise clarification question for this task:\n{message}"
        )
    if action == "clarify":
        return (
            "Clarify this {intent} request before executor dispatch.\n\n"
            "Candidate workflow: `{workflow}` / `{harness}`.\n\n"
            "Task:\n{message}"
        ).format(intent=intent, workflow=workflow, harness=harness, message="{message}")
    return (
        "Delegate this {intent} request to a {workflow} executor lane.\n\n"
        "Recommended workflow: `{workflow}`\n"
        "Recommended harness: `{harness}`\n"
        "Do not claim execution is observed unless wrapper/runtime evidence proves it.\n\n"
        "Task:\n{message}"
    ).format(intent=intent, workflow=workflow, harness=harness, message="{message}")


def _compact_recommendations(recommendations: object) -> list[dict[str, object]]:
    if not isinstance(recommendations, list):
        return []
    compact: list[dict[str, object]] = []
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        matched = item.get("matched", [])
        compact.append(
            {
                "skill": str(item.get("skill", "")),
                "score": int(item.get("score", 0)),
                "confidence": str(item.get("confidence", "low")),
                "matched": [str(value) for value in matched] if isinstance(matched, list) else [],
            }
        )
    return compact


def _has_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)
