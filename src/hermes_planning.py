from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
import secrets
from pathlib import Path
from typing import Any

from .ingress import CHAT_SOURCES, extract_message_text, extract_source_metadata
from .local_store import atomic_write_json, atomic_write_text, utc_now
from .memory import validate_handoff_context_pack
from .observation_journal import append_observation_event
from .paths import OmhPaths
from .routing.recommend import recommend_skills
from .skills.catalog import harness_quality_contract


SCHEMA_VERSION = "hermes_plan/v1"
WRAPPER_CONTRACT_VERSION = "hermes_plan_wrapper/v1"
PLAN_STATUSES = ("draft", "accepted", "revised", "cancelled", "superseded", "blocked")
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
    "release gate",
    "claim",
    "evidence",
    "위험",
    "리뷰",
    "검토",
    "릴리즈",
    "검증",
    "실제 코드",
)
_CLARIFY_TERMS = ("maybe", "something", "stuff", "whatever", "help", "thing", "싶어", "부드럽게", "모호")


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
    try:
        artifact["journal_event"] = append_observation_event(
            paths,
            {
                "target_type": "plan",
                "target_id": str(path),
                "event": "plan_artifact_created",
                "status": "observed",
                "source": "hermes_plan",
                "plan_artifact": str(path),
                "plan_status": str(artifact["status"]),
                "summary": "Hermes file-backed plan artifact was created.",
            },
        )
    except (OSError, ValueError) as exc:
        artifact["journal_error"] = str(exc)
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


def read_hermes_plan_artifact(path: str | Path) -> dict[str, object]:
    plan_path = Path(path).expanduser().resolve()
    text = plan_path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(text)
    status = str(frontmatter.get("status", "draft"))
    task_statement = _section_text(body, "Task Statement") or _heading_title(body)
    return {
        "path": str(plan_path),
        "name": plan_path.name,
        "schema_version": str(frontmatter.get("schema_version", "")),
        "status": status,
        "source": str(frontmatter.get("source", "")),
        "task_statement": task_statement,
        "task_statement_sha256": hashlib.sha256(task_statement.encode("utf-8")).hexdigest() if task_statement else "",
        "task_statement_length": len(task_statement),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "body": body,
        "text": text,
        "frontmatter": frontmatter,
    }


def update_hermes_plan_status(
    paths: OmhPaths,
    path: str | Path,
    *,
    status: str,
    summary: str = "",
) -> dict[str, object]:
    if status not in PLAN_STATUSES:
        raise ValueError(f"unsupported plan status: {status}")
    plan_path = Path(path).expanduser().resolve()
    current = read_hermes_plan_artifact(plan_path)
    if current.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"expected {SCHEMA_VERSION} artifact")
    original = plan_path.read_text(encoding="utf-8")
    updated = _replace_frontmatter_status(original, status=status, summary=summary)
    atomic_write_text(plan_path, updated, private=True)
    artifact = read_hermes_plan_artifact(plan_path)
    event_name = {
        "accepted": "plan_accepted",
        "revised": "plan_revised",
        "cancelled": "plan_cancelled",
    }.get(status, "plan_artifact_created")
    result: dict[str, object] = {"artifact": _plan_artifact_summary(artifact)}
    try:
        result["journal_event"] = append_observation_event(
            paths,
            {
                "target_type": "plan",
                "target_id": str(plan_path),
                "event": event_name,
                "status": "observed",
                "source": "hermes_plan",
                "plan_artifact": str(plan_path),
                "plan_status": status,
                "summary": summary or f"Hermes plan marked {status}.",
            },
        )
    except (OSError, ValueError) as exc:
        result["journal_error"] = str(exc)
    return result


def build_plan_handoff_message(artifact: dict[str, object]) -> str:
    return "\n".join(
        [
            "Implement the accepted Hermes plan artifact below.",
            "",
            f"Plan artifact: {artifact.get('path', '')}",
            f"Plan status: {artifact.get('status', '')}",
            f"Plan sha256: {artifact.get('sha256', '')}",
            "",
            "Use this file-backed plan as the executor context. The Discord or chat summary is not the executor plan.",
            "Preserve prepared-vs-observed boundaries: prepared handoff is not execution, review, CI, merge-readiness, or merge evidence.",
            "",
            "----- BEGIN ACCEPTED HERMES PLAN -----",
            str(artifact.get("text", "")).strip(),
            "----- END ACCEPTED HERMES PLAN -----",
        ]
    )


def build_plan_handoff_context_pack(artifact: dict[str, object], *, executor_target: str = "codex") -> dict[str, object]:
    plan_artifact_path = str(artifact.get("path", ""))
    pack = {
        "schema_version": "handoff_context_pack/v1",
        "executor_target": executor_target,
        "session_id": "",
        "scope": {"kind": "project", "ref": "default"},
        "metadata": {
            "plan_artifact_path": plan_artifact_path,
            "plan_artifact_ref": plan_artifact_path,
            "plan_artifact_status": str(artifact.get("status", "")),
            "plan_artifact_schema_version": str(artifact.get("schema_version", "")),
            "plan_artifact_sha256": str(artifact.get("sha256", "")),
        },
        "source_refs": [
            {
                "source": "hermes_plan",
                "truth_level": "approved_context",
                "precedence": 95,
                "item_count": 1,
            }
        ],
        "included_context": [
            {
                "item_id": "accepted-hermes-plan",
                "key": "plan_artifact",
                "summary": (
                    f"Accepted Hermes plan artifact status={artifact.get('status', '')}; "
                    f"sha256={artifact.get('sha256', '')}."
                ),
                "artifact_ref": plan_artifact_path,
                "source": "hermes_plan",
                "truth_level": "approved_context",
                "scope": {"kind": "project", "ref": "default"},
            }
        ],
        "excluded_context": [],
        "blocked_by_conflicts": [],
        "redaction_policy": "metadata_only",
        "claim_boundary": "Plan context pack points to a file-backed Hermes plan; it is not execution evidence.",
    }
    errors = validate_handoff_context_pack(pack, require_conflict_free=True, label="plan context pack")
    if errors:
        raise ValueError("; ".join(errors))
    return pack


def write_plan_handoff_context_pack(
    paths: OmhPaths,
    artifact: dict[str, object],
    *,
    executor_target: str = "codex",
) -> dict[str, object]:
    pack = build_plan_handoff_context_pack(artifact, executor_target=executor_target)
    path = paths.runtime_plan_context_dir / f"{Path(str(artifact.get('path', 'plan'))).stem}-context-pack.json"
    atomic_write_json(path, pack, private=True)
    return {"path": str(path), "context_pack": pack}


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


def _split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        return {}, text
    frontmatter: dict[str, object] = {}
    current_parent = ""
    for raw in lines[1:end_index]:
        if not raw.strip():
            continue
        if raw.startswith((" ", "\t")) and current_parent:
            key, _, value = raw.strip().partition(":")
            parent = frontmatter.setdefault(current_parent, {})
            if isinstance(parent, dict) and key:
                parent[key] = _unquote_scalar(value.strip())
            continue
        key, _, value = raw.partition(":")
        if not key:
            continue
        current_parent = key.strip()
        frontmatter[current_parent] = _unquote_scalar(value.strip()) if value.strip() else {}
    return frontmatter, "\n".join(lines[end_index + 1 :]).lstrip("\n")


def _replace_frontmatter_status(text: str, *, status: str, summary: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "\n".join(
            [
                "---",
                f"schema_version: {SCHEMA_VERSION}",
                f"status: {status}",
                f"{status}_at: {utc_now()}",
                *_status_note_lines(summary),
                "---",
                "",
                text,
            ]
        )
    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        return text
    status_written = False
    timestamp_key = f"{status}_at"
    timestamp_written = False
    note_written = False
    frontmatter: list[str] = []
    for line in lines[1:end_index]:
        stripped = line.strip()
        if stripped.startswith("status:"):
            frontmatter.append(f"status: {status}")
            status_written = True
        elif stripped.startswith(f"{timestamp_key}:"):
            frontmatter.append(f"{timestamp_key}: {utc_now()}")
            timestamp_written = True
        elif stripped.startswith("status_note:") and summary:
            frontmatter.append(f"status_note: {_yaml_string(summary)}")
            note_written = True
        else:
            frontmatter.append(line)
    if not status_written:
        frontmatter.insert(1 if frontmatter else 0, f"status: {status}")
    if not timestamp_written:
        frontmatter.append(f"{timestamp_key}: {utc_now()}")
    if summary and not note_written:
        frontmatter.extend(_status_note_lines(summary))
    return "\n".join(["---", *frontmatter, "---", *lines[end_index + 1 :]]) + "\n"


def _status_note_lines(summary: str) -> list[str]:
    return [f"status_note: {_yaml_string(summary)}"] if summary else []


def _section_text(body: str, heading: str) -> str:
    lines = body.splitlines()
    marker = f"## {heading}"
    start = None
    for index, line in enumerate(lines):
        if line.strip() == marker:
            start = index + 1
            break
    if start is None:
        return ""
    collected: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        collected.append(line)
    return "\n".join(collected).strip()


def _heading_title(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].replace("Hermes Plan:", "", 1).strip()
    return ""


def _plan_artifact_summary(artifact: dict[str, object]) -> dict[str, object]:
    return {
        "path": artifact.get("path", ""),
        "kind": "hermes_plan",
        "schema_version": artifact.get("schema_version", SCHEMA_VERSION),
        "status": artifact.get("status", "draft"),
        "sha256": artifact.get("sha256", ""),
        "task_statement_sha256": artifact.get("task_statement_sha256", ""),
        "task_statement_length": artifact.get("task_statement_length", 0),
    }


def _unquote_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


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
    handoff = (
        "Use `omh coding delegate --executor codex --record --from-plan <accepted-plan.md>` after this plan is accepted for a run-backed Codex handoff."
        if coding_shaped
        else "Use the selected Hermes workflow only after the plan is accepted."
    )
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
        goals.append("Require reviewer evidence before calling the plan approved.")
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
        "plan_artifact_field": "wrapper_contract.plan_artifact.path",
        "handoff_context_policy": (
            "After plan acceptance, read the accepted plan artifact or generated handoff context pack "
            "and pass that to the coding executor. Discord/channel text is only a summary."
        ),
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
                "the wrapper cannot provide an accepted plan artifact or generated context pack",
                "the wrapper would claim review or execution without evidence",
            ],
        },
        "quality_gate": plan.quality_gate,
        "harness_quality": harness_quality_contract(plan.recommended_harness),
        "deep_interview": plan.deep_interview,
        "coding_delegate": {
            "available": coding_available,
            "requires_plan_acceptance": coding_available,
            "stdout_schema_version": "coding_delegation/v1",
            "recording_contract": "prepared_not_observed",
            "input_policy": (
                "Use accepted plan artifact content or generated context pack; do not use Discord summary "
                "as the executor plan."
            ),
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
                        "--executor",
                        "codex",
                        "--source",
                        source,
                        "--record",
                        "--from-plan",
                        "{plan_artifact}",
                        *metadata_args,
                    ],
                    "plan_artifact_arg": "--from-plan",
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
            "executor/runtime dispatch",
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
    if any(term in lowered for term in ("실패", "버그", "장애", "재현")):
        missing.append("observable failure or reproduction signal")
    if any(term in lowered for term in ("계획", "전략", "아키텍처", "기획")):
        missing.append("decision authority and tradeoff preference")
    return tuple(missing)


def _clarification_question(task: str) -> str:
    if any(term in task.lower() for term in ("fix", "bug", "debug", "실패", "버그", "장애", "재현")):
        return "What exact failure should Hermes plan around, and what result would prove it is fixed?"
    return "What outcome should Hermes plan for, and what would make the result acceptable?"


def _is_coding_shaped(task: str) -> bool:
    lowered = task.lower()
    return bool(
        re.search(
            r"\b(code|coding|implement|implementation|fix|fixed|fixes|debug|debugging|test|tests|testing|refactor|refactoring|bug)\b",
            lowered,
        )
        or re.search(
            r"\b(add|change|modify)\s+(?:a\s+)?(?:new\s+)?(feature|code|test|tests|endpoint|api|command|cli|workflow|harness|module|function)\b",
            lowered,
        )
        or any(
            term in lowered
            for term in (
                "구현",
                "수정",
                "추가",
                "변경",
                "고쳐",
                "만들",
                "결제 실패",
                "버그",
                "장애",
                "재현",
                "리팩터링",
                "리팩토링",
                "기능 요청",
                "구현 handoff",
            )
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
