from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import re
import secrets
from pathlib import Path
from typing import Any

from .chat_router import CHAT_SOURCES, extract_message_text
from .coding_delegation import extract_source_metadata
from .local_store import atomic_write_text
from .paths import OmhPaths
from .recommend import recommend_skills


SCHEMA_VERSION = "hermes_plan/v1"
WRAPPER_CONTRACT_VERSION = "hermes_plan_wrapper/v1"
_REVIEW_TERMS = (
    "architecture",
    "architect",
    "risky",
    "risk",
    "review",
    "consensus",
    "ralplan",
    "migration",
    "refactor",
    "integration",
    "contract",
)
_CLARIFY_TERMS = ("maybe", "something", "stuff", "whatever", "help", "thing")


@dataclass(frozen=True)
class HermesPlan:
    status: str
    task_statement: str
    recommended_workflow: str
    recommended_harness: str
    planning_mode: str
    clarified_assumptions: tuple[str, ...]
    goals: tuple[str, ...]
    non_goals: tuple[str, ...]
    decision_drivers: tuple[str, ...]
    options: tuple[dict[str, object], ...]
    chosen_direction: str
    rejection_rationale: tuple[str, ...]
    risks: tuple[str, ...]
    mitigations: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    verification_plan: tuple[str, ...]
    execution_handoff: str
    review_gate: dict[str, str]
    quality_gate: dict[str, object]
    deep_interview: dict[str, object]
    stop_condition: str

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        for key in (
            "clarified_assumptions",
            "goals",
            "non_goals",
            "decision_drivers",
            "options",
            "rejection_rationale",
            "risks",
            "mitigations",
            "acceptance_criteria",
            "verification_plan",
        ):
            data[key] = list(data[key])
        return data


def build_hermes_plan_payload(
    message: str,
    *,
    source: str = "generic",
    limit: int = 3,
    source_metadata: dict[str, str] | None = None,
) -> dict[str, object]:
    task = message.strip()
    if not task:
        raise ValueError("hermes plan requires a task description")
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported hermes plan source: {source}")
    if limit < 1:
        raise ValueError("hermes plan --limit must be at least 1")

    recommendations = _compact_recommendations(recommend_skills(task, limit=max(limit, 5))[:limit])
    top = recommendations[0] if recommendations else {"skill": "oh-my-hermes", "score": 0, "confidence": "low"}
    plan = _plan_for(task, top)
    metadata = {key: value for key, value in (source_metadata or {}).items() if value}
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "plan": plan.to_dict(),
        "wrapper_contract": _wrapper_contract(plan, source=source, source_metadata=metadata),
        "recommendations": recommendations,
    }
    if metadata:
        payload["source_metadata"] = metadata
    return payload


def build_hermes_plan_event_payload(
    event: dict[str, Any] | str,
    *,
    source: str = "generic",
    limit: int = 3,
) -> dict[str, object]:
    return build_hermes_plan_payload(
        extract_message_text(event),
        source=source,
        limit=limit,
        source_metadata=extract_source_metadata(event),
    )


def write_hermes_plan(paths: OmhPaths, payload: dict[str, object]) -> dict[str, object]:
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("hermes plan payload is missing plan")
    slug = _slugify(str(plan.get("task_statement", "plan")))
    path = _unique_artifact_path(paths.hermes_home / "plans", slug, ".md")
    content = render_plan_markdown(payload, path.name)
    atomic_write_text(path, content, private=True)
    artifact: dict[str, object] = {
        "path": str(path),
        "kind": "hermes_plan",
        "schema_version": SCHEMA_VERSION,
        "status": plan.get("status", "draft"),
    }
    if plan.get("status") == "blocked":
        context_path = _unique_artifact_path(paths.hermes_home / "context", f"{slug}-context", ".md")
        atomic_write_text(context_path, render_context_markdown(payload, context_path.name), private=True)
        artifact["context_path"] = str(context_path)
    return artifact


def attach_plan_artifact_to_wrapper_contract(payload: dict[str, object], artifact: dict[str, object]) -> None:
    contract = payload.get("wrapper_contract")
    if not isinstance(contract, dict):
        return
    plan_artifact: dict[str, object] = {
        "recorded": True,
        "kind": artifact.get("kind", "hermes_plan"),
        "schema_version": artifact.get("schema_version", SCHEMA_VERSION),
        "status": artifact.get("status", "draft"),
        "path": artifact.get("path", ""),
    }
    if artifact.get("context_path"):
        plan_artifact["context_path"] = artifact["context_path"]
    contract["plan_artifact"] = plan_artifact


def render_plan_markdown(payload: dict[str, object], artifact_name: str = "plan.md") -> str:
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("hermes plan payload is missing plan")
    review_gate = plan.get("review_gate", {})
    if not isinstance(review_gate, dict):
        review_gate = {}
    metadata = payload.get("source_metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    lines = [
        "---",
        f"schema_version: {SCHEMA_VERSION}",
        f"status: {plan.get('status', 'draft')}",
        f"source: {payload.get('source', 'generic')}",
        "review_gate:",
        f"  architect: {review_gate.get('architect', 'not_observed')}",
        f"  critic: {review_gate.get('critic', 'not_observed')}",
    ]
    if metadata:
        lines.append("source_metadata:")
        for key in ("source_event_id", "channel_ref", "user_ref", "timestamp"):
            value = metadata.get(key)
            if value:
                lines.append(f"  {key}: {_yaml_string(value)}")
    lines.extend(
        [
            "---",
            "",
            f"# Hermes Plan: {plan.get('task_statement', 'Untitled task')}",
            "",
            f"Artifact: `{artifact_name}`",
            "",
            "## Task Statement",
            "",
            str(plan.get("task_statement", "")).strip(),
            "",
            "## Clarified Assumptions",
            "",
            *_markdown_list(plan.get("clarified_assumptions", [])),
            "",
            "## Goals",
            "",
            *_markdown_list(plan.get("goals", [])),
            "",
            "## Non-Goals",
            "",
            *_markdown_list(plan.get("non_goals", [])),
            "",
            "## Decision Drivers",
            "",
            *_markdown_list(plan.get("decision_drivers", [])),
            "",
            "## Quality Gate",
            "",
            *_quality_gate_lines(plan.get("quality_gate", {})),
            "",
            "## Deep Interview",
            "",
            *_deep_interview_lines(plan.get("deep_interview", {})),
            "",
            "## Viable Options",
            "",
            *_option_lines(plan.get("options", [])),
            "",
            "## Chosen Direction",
            "",
            str(plan.get("chosen_direction", "")).strip(),
            "",
            "## Rejection Rationale",
            "",
            *_markdown_list(plan.get("rejection_rationale", [])),
            "",
            "## Risks",
            "",
            *_markdown_list(plan.get("risks", [])),
            "",
            "## Mitigations",
            "",
            *_markdown_list(plan.get("mitigations", [])),
            "",
            "## Acceptance Criteria",
            "",
            *_markdown_list(plan.get("acceptance_criteria", [])),
            "",
            "## Verification Plan",
            "",
            *_markdown_list(plan.get("verification_plan", [])),
            "",
            "## Execution Handoff",
            "",
            str(plan.get("execution_handoff", "")).strip(),
            "",
            "## Review Status",
            "",
            f"- Architect: `{review_gate.get('architect', 'not_observed')}`",
            f"- Critic: `{review_gate.get('critic', 'not_observed')}`",
            "",
            "## Stop Condition",
            "",
            str(plan.get("stop_condition", "")).strip(),
            "",
        ]
    )
    return "\n".join(lines)


def render_context_markdown(payload: dict[str, object], artifact_name: str = "context.md") -> str:
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("hermes plan payload is missing plan")
    return "\n".join(
        [
            "---",
            f"schema_version: {SCHEMA_VERSION}",
            "status: blocked",
            f"source: {payload.get('source', 'generic')}",
            "---",
            "",
            f"# Hermes Context: {plan.get('task_statement', 'Untitled task')}",
            "",
            f"Artifact: `{artifact_name}`",
            "",
            "## Known Facts",
            "",
            *_markdown_list(plan.get("clarified_assumptions", [])),
            "",
            "## Missing Decisions",
            "",
            *_markdown_list(_nested_list(plan.get("deep_interview", {}), "missing_decisions")),
            "",
            "## Recommended Question",
            "",
            str(_nested_value(plan.get("deep_interview", {}), "question", "What outcome should Hermes plan for?")).strip(),
            "",
            "## Answer Shape",
            "",
            *_markdown_list(_nested_list(plan.get("deep_interview", {}), "answer_shape")),
            "",
            "## Clarification Log",
            "",
            "- Ask one concise blocking question before producing an execution plan.",
            "",
            "## Stop Condition",
            "",
            str(plan.get("stop_condition", "")).strip(),
            "",
        ]
    )


def _plan_for(task: str, top: dict[str, object]) -> HermesPlan:
    lowered = task.lower()
    score = _int_value(top.get("score", 0))
    weak = len(task.split()) <= 2 and (score == 0 or any(term in lowered for term in _CLARIFY_TERMS))
    review_shaped = any(term in lowered for term in _REVIEW_TERMS)
    coding_shaped = _is_coding_shaped(task)

    if weak:
        return HermesPlan(
            status="blocked",
            task_statement=task,
            recommended_workflow="deep-interview",
            recommended_harness="deep-interview",
            planning_mode="clarification-first",
            clarified_assumptions=("The request needs one blocking clarification before a durable plan is safe.",),
            goals=("Capture the missing decision in `.hermes/context/`.", "Ask one concise question instead of guessing."),
            non_goals=("Do not execute implementation work.", "Do not claim review or planning approval."),
            decision_drivers=("Avoid turning ambiguous chat into false certainty.", "Keep the user-facing artifact under `.hermes/`."),
            options=_options("clarification"),
            chosen_direction="Create a blocked planning scaffold and a Hermes context artifact before execution.",
            rejection_rationale=("Skipping clarification would make the plan depend on unstated assumptions.",),
            risks=("The user may expect immediate execution.",),
            mitigations=("State the exact missing decision and stop after one concise question.",),
            acceptance_criteria=("A context artifact names the missing decision.", "No execution handoff is marked ready."),
            verification_plan=("Inspect the generated `.hermes/context/` artifact.",),
            execution_handoff="Ask the smallest blocking clarification, then rerun `omh hermes plan` with the clarified task.",
            review_gate={"architect": "not_observed", "critic": "not_observed"},
            quality_gate=_quality_gate(
                status="blocked",
                top=top,
                coding_shaped=False,
                review_shaped=False,
            ),
            deep_interview=_deep_interview_contract(
                task,
                required=True,
                missing_decisions=_missing_decisions(task),
            ),
            stop_condition="A clarified task statement is available for planning.",
        )

    workflow = "ralplan" if review_shaped else "plan"
    harness = "planning"
    handoff = "Use `omh coding delegate --record` after this plan is accepted." if coding_shaped else "Use the selected Hermes workflow only after the plan is accepted."
    return HermesPlan(
        status="draft",
        task_statement=task,
        recommended_workflow=workflow,
        recommended_harness=harness,
        planning_mode="review-gated" if review_shaped else "structured",
        clarified_assumptions=("The task statement is sufficient for a first deterministic planning scaffold.",),
        goals=_goals(coding_shaped, review_shaped),
        non_goals=(
            "Do not execute code or mutate Hermes core from the planning command.",
            "Do not claim architect or critic approval without wrapper evidence.",
            "Do not store raw platform event payloads in the plan artifact.",
        ),
        decision_drivers=(
            "Keep product-facing plans under `.hermes/plans/`.",
            "Make acceptance criteria and verification visible before execution.",
            "Separate planned work from observed implementation evidence.",
        ),
        options=_options("reviewed" if review_shaped else "structured"),
        chosen_direction=_chosen_direction(coding_shaped, review_shaped),
        rejection_rationale=(
            "Direct execution is rejected until the plan names success criteria and verification.",
            "Claimed multi-role consensus is rejected unless wrapper metadata proves those reviews ran.",
        ),
        risks=(
            "A deterministic scaffold may be less specific than a human-written plan.",
            "Wrappers may display the draft as approved if status is ignored.",
        ),
        mitigations=(
            "Persist `status: draft` and `not_observed` review gates by default.",
            "Keep the execution handoff explicit and separate from the plan command.",
        ),
        acceptance_criteria=(
            "The plan includes goals, non-goals, options, risks, acceptance criteria, verification, and handoff guidance.",
            "The artifact is written under `.hermes/plans/` when `--record` is used.",
            "The review gate remains `not_observed` unless wrapper evidence proves otherwise.",
        ),
        verification_plan=(
            "Run the targeted CLI test for `omh hermes plan`.",
            "Run generated-doc checks when Hermes guidance changes.",
            "Run the repo unit test suite before merge.",
        ),
        execution_handoff=handoff,
        review_gate={"architect": "not_observed", "critic": "not_observed"},
        quality_gate=_quality_gate(
            status="draft",
            top=top,
            coding_shaped=coding_shaped,
            review_shaped=review_shaped,
        ),
        deep_interview=_deep_interview_contract(
            task,
            required=False,
            missing_decisions=(),
        ),
        stop_condition="The plan is accepted or a reviewer requests concrete changes.",
    )


def _goals(coding_shaped: bool, review_shaped: bool) -> tuple[str, ...]:
    goals = [
        "Create a durable Hermes-facing planning artifact.",
        "Make the next execution step explicit and testable.",
    ]
    if coding_shaped:
        goals.append("Prepare a later coding delegation handoff instead of treating Hermes as the implementer.")
    if review_shaped:
        goals.append("Require review-gate evidence before calling the plan approved.")
    return tuple(goals)


def _chosen_direction(coding_shaped: bool, review_shaped: bool) -> str:
    if coding_shaped and review_shaped:
        return "Create a reviewed planning scaffold first, then delegate coding only after acceptance and verification expectations are clear."
    if coding_shaped:
        return "Create a structured planning scaffold first, then hand implementation to the coding delegation flow."
    if review_shaped:
        return "Create a review-gated planning scaffold and keep review approval unobserved until evidence exists."
    return "Create a structured Hermes plan before any execution handoff."


def _options(kind: str) -> tuple[dict[str, object], ...]:
    if kind == "clarification":
        return (
            {
                "name": "Clarify first",
                "pros": ["Avoids guessing", "Creates a clear stop condition"],
                "cons": ["Delays execution until one answer is available"],
            },
            {
                "name": "Draft immediately",
                "pros": ["Fast initial artifact"],
                "cons": ["Likely to encode hidden assumptions"],
            },
        )
    if kind == "reviewed":
        return (
            {
                "name": "Review-gated Hermes plan",
                "pros": ["Fits risky or architectural work", "Keeps approval claims honest"],
                "cons": ["Requires wrapper evidence for real multi-role review"],
            },
            {
                "name": "Plain plan",
                "pros": ["Smaller artifact"],
                "cons": ["Weaker risk and verification discipline"],
            },
        )
    return (
        {
            "name": "Structured Hermes plan",
            "pros": ["Fast deterministic scaffold", "Good handoff surface for wrappers"],
            "cons": ["Needs later human or wrapper review for approval"],
        },
        {
            "name": "Immediate execution",
            "pros": ["Shortest path to action"],
            "cons": ["Skips acceptance and verification planning"],
        },
    )


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
                "score": _int_value(item.get("score", 0)),
                "confidence": str(item.get("confidence", "low")),
                "matched": [str(value) for value in matched] if isinstance(matched, list) else [],
            }
        )
    return compact


def _wrapper_contract(plan: HermesPlan, *, source: str, source_metadata: dict[str, str]) -> dict[str, object]:
    coding_available = plan.status == "draft" and _is_coding_shaped(plan.task_statement)
    metadata_args = _source_metadata_argv(source_metadata)
    contract: dict[str, object] = {
        "schema_version": WRAPPER_CONTRACT_VERSION,
        "source": source,
        "current_step": "ask_clarification" if plan.status == "blocked" else "present_plan",
        "next_action": _wrapper_next_action(plan, coding_available),
        "message_field": "plan.task_statement",
        "plan_artifact": {
            "recorded": False,
            "kind": "hermes_plan",
            "schema_version": SCHEMA_VERSION,
        },
        "decision_gate": {
            "required": plan.status == "draft",
            "condition": "plan.status is draft and the wrapper or a human accepts the plan",
            "do_not_delegate_when": [
                "plan.status is blocked",
                "the wrapper cannot preserve the original task message",
                "the wrapper would claim review or execution without evidence",
            ],
        },
        "quality_gate": plan.quality_gate,
        "deep_interview": plan.deep_interview,
        "coding_delegate": {
            "available": coding_available,
            "requires_plan_acceptance": coding_available,
            "stdout_schema_version": "coding_delegation/v1",
            "recording_contract": "prepared_not_observed",
            "input_policy": "Pass the original task message directly; do not parse the Markdown plan body.",
        },
    }
    coding_delegate = contract["coding_delegate"]
    if isinstance(coding_delegate, dict):
        if coding_available:
            coding_delegate.update(
                {
                    "argv_template": [
                        "omh",
                        "coding",
                        "delegate",
                        "--source",
                        source,
                        "--record",
                        *metadata_args,
                        "{message}",
                    ],
                    "prompt_template_field": "delegation.delegation_prompt_template",
                    "include_message_flag": "--include-message",
                    "recorded_run_field": "runtime.run.run_id",
                }
            )
        else:
            coding_delegate["unavailable_reason"] = (
                "plan is blocked" if plan.status == "blocked" else "task is not implementation-shaped"
            )
    return contract


def _wrapper_next_action(plan: HermesPlan, coding_available: bool) -> str:
    if plan.status == "blocked":
        return "ask_clarification"
    if coding_available:
        return "prepare_coding_delegation_after_plan_acceptance"
    return "forward_plan_to_selected_workflow"


def _source_metadata_argv(metadata: dict[str, str]) -> list[str]:
    flags = {
        "source_event_id": "--source-event-id",
        "channel_ref": "--channel-ref",
        "user_ref": "--user-ref",
    }
    args: list[str] = []
    for key in ("source_event_id", "channel_ref", "user_ref"):
        value = metadata.get(key)
        if value:
            args.extend([flags[key], value])
    return args


def _quality_gate(
    *,
    status: str,
    top: dict[str, object],
    coding_shaped: bool,
    review_shaped: bool,
) -> dict[str, object]:
    readiness = "needs_clarification" if status == "blocked" else "ready_for_acceptance"
    confidence = str(top.get("confidence", "low"))
    pass_conditions = [
        "task statement is specific enough to preserve user intent",
        "acceptance criteria and verification plan are visible before any handoff",
        "review gates stay not_observed until wrapper evidence exists",
    ]
    if coding_shaped:
        pass_conditions.append("coding handoff is prepared only after plan acceptance")
    if status == "blocked":
        pass_conditions = [
            "one blocking question is answered",
            "missing decisions are captured in `.hermes/context/`",
            "the clarified request can be replanned without guessing",
        ]
    return {
        "schema_version": "hermes_plan_quality/v1",
        "readiness": readiness,
        "confidence": confidence,
        "review_required": review_shaped,
        "coding_handoff_ready": status == "draft" and coding_shaped,
        "status_claim": "draft_plan_not_approval" if status == "draft" else "blocked_not_plan",
        "pass_conditions": pass_conditions,
        "must_observe_before_claiming": [
            "plan acceptance",
            "executor dispatch",
            "executor result",
            "verification",
            "review when required",
            "CI and merge readiness when reported",
        ],
    }


def _deep_interview_contract(
    task: str,
    *,
    required: bool,
    missing_decisions: tuple[str, ...],
) -> dict[str, object]:
    if required:
        return {
            "schema_version": "deep_interview_contract/v1",
            "required": True,
            "question_style": "one_question",
            "question": _clarification_question(task),
            "reason": "The request is too underspecified for a safe Hermes plan or coding handoff.",
            "missing_decisions": list(missing_decisions),
            "answer_shape": [
                "target outcome",
                "important constraints or non-goals",
                "success signal the wrapper can later report",
            ],
            "after_answer_next_action": "rerun_hermes_plan",
        }
    return {
        "schema_version": "deep_interview_contract/v1",
        "required": False,
        "question_style": "none",
        "question": "",
        "reason": "The task is specific enough for a draft plan; users can still request revisions before acceptance.",
        "missing_decisions": [],
        "answer_shape": [],
        "after_answer_next_action": "accept_or_revise_plan",
    }


def _missing_decisions(task: str) -> tuple[str, ...]:
    lowered = task.lower()
    missing = [
        "target outcome",
        "success criteria",
        "scope boundary",
    ]
    if any(term in lowered for term in ("fix", "bug", "debug")):
        missing.append("observable failure or reproduction signal")
    if any(term in lowered for term in ("plan", "strategy", "architecture")):
        missing.append("decision authority and tradeoff preference")
    return tuple(missing)


def _clarification_question(task: str) -> str:
    if any(term in task.lower() for term in ("fix", "bug", "debug")):
        return "What exact failure should Hermes plan around, and what result would prove it is fixed?"
    return "What outcome should Hermes plan for, and what would make the result acceptable?"


def _is_coding_shaped(task: str) -> bool:
    return bool(
        re.search(
            r"\b(code|coding|implement|implementation|fix|fixed|fixes|debug|debugging|test|tests|testing|refactor|refactoring|bug)\b",
            task.lower(),
        )
    )


def _markdown_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return ["- None recorded."]
    return [f"- {str(value)}" for value in values if str(value)] or ["- None recorded."]


def _quality_gate_lines(value: object) -> list[str]:
    if not isinstance(value, dict):
        return ["- None recorded."]
    lines = [
        f"- Readiness: `{value.get('readiness', 'unknown')}`",
        f"- Confidence: `{value.get('confidence', 'low')}`",
        f"- Coding handoff ready: `{str(value.get('coding_handoff_ready', False)).lower()}`",
        f"- Status claim: `{value.get('status_claim', 'unknown')}`",
        "- Pass conditions:",
    ]
    lines.extend(f"  - {item}" for item in value.get("pass_conditions", []) if str(item))
    lines.append("- Must observe before claiming:")
    lines.extend(f"  - {item}" for item in value.get("must_observe_before_claiming", []) if str(item))
    return lines


def _deep_interview_lines(value: object) -> list[str]:
    if not isinstance(value, dict):
        return ["- None recorded."]
    if not value.get("required", False):
        return [
            "- Required: `false`",
            f"- Reason: {value.get('reason', 'No blocking interview required.')}",
            f"- Next action: `{value.get('after_answer_next_action', 'accept_or_revise_plan')}`",
        ]
    lines = [
        "- Required: `true`",
        f"- Question style: `{value.get('question_style', 'one_question')}`",
        f"- Question: {value.get('question', '')}",
        f"- Reason: {value.get('reason', '')}",
        "- Missing decisions:",
    ]
    lines.extend(f"  - {item}" for item in value.get("missing_decisions", []) if str(item))
    lines.append("- Answer shape:")
    lines.extend(f"  - {item}" for item in value.get("answer_shape", []) if str(item))
    lines.append(f"- Next action: `{value.get('after_answer_next_action', 'rerun_hermes_plan')}`")
    return lines


def _nested_list(value: object, key: str) -> list[str]:
    if not isinstance(value, dict):
        return []
    nested = value.get(key, [])
    return [str(item) for item in nested] if isinstance(nested, list) else []


def _nested_value(value: object, key: str, default: str) -> str:
    if not isinstance(value, dict):
        return default
    nested = value.get(key, default)
    return str(nested) if str(nested) else default


def _option_lines(values: object) -> list[str]:
    if not isinstance(values, list):
        return ["- None recorded."]
    lines: list[str] = []
    for option in values:
        if not isinstance(option, dict):
            continue
        lines.append(f"### {option.get('name', 'Option')}")
        lines.append("")
        lines.append("Pros:")
        lines.extend(_markdown_list(option.get("pros", [])))
        lines.append("")
        lines.append("Cons:")
        lines.extend(_markdown_list(option.get("cons", [])))
        lines.append("")
    return lines or ["- None recorded."]


def _unique_artifact_path(directory: Path, slug: str, suffix: str) -> Path:
    for _ in range(100):
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S%fZ")
        path = directory / f"{stamp}-{slug}-{secrets.token_hex(3)}{suffix}"
        if not path.exists():
            return path
    raise RuntimeError("could not allocate unique Hermes planning artifact path")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "plan")[:64].strip("-") or "plan"


def _int_value(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _yaml_string(value: object) -> str:
    return json.dumps(str(value))
