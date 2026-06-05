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
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "plan": plan.to_dict(),
        "recommendations": recommendations,
    }
    metadata = {key: value for key, value in (source_metadata or {}).items() if value}
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
            "- The desired outcome, constraints, or success criteria are not specific enough for a safe plan.",
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
    coding_shaped = any(term in lowered for term in ("code", "coding", "implement", "fix", "debug", "test", "feature", "refactor"))

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


def _markdown_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return ["- None recorded."]
    return [f"- {str(value)}" for value in values if str(value)] or ["- None recorded."]


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
