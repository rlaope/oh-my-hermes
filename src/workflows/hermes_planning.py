from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import re
import secrets
from pathlib import Path
from typing import Any

from ..executors import CODING_EXECUTOR_TARGETS, executor_handoff_metadata_for_target
from ..ingress import CHAT_SOURCES, extract_message_text, extract_source_metadata
from ..local_store import atomic_write_json, atomic_write_text, utc_now
from ..memory import validate_handoff_context_pack
from ..observation_journal import append_observation_event
from ..paths import OmhPaths, ensure_project_store_ignored, project_artifact_dir, project_identity
from ..routing.recommend import recommend_skills
from ..skills.catalog import (
    DEEP_INTERVIEW_CLARITY_DIMENSIONS,
    DEEP_INTERVIEW_MAX_ROUNDS,
    DEEP_INTERVIEW_SOFT_CHECK_ROUND,
    harness_quality_contract,
    routable_definitions,
)
from .decision_receipt_handoffs import DecisionArtifact, build_decision_receipt_handoff
from .workflow_composition import (
    CODING_OWNER_CHOICE_PENDING,
    WORKFLOW_COMPOSITION_CODING_OWNERS,
    build_workflow_composition,
)


SCHEMA_VERSION = "hermes_plan/v1"
INPUT_SCHEMA_VERSION = "hermes_plan_input/v1"
REVIEWED_BODY_MAX_BYTES = 262144
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
        return {
            "status": self.status,
            "task_statement": self.task_statement,
            "recommended_workflow": self.recommended_workflow,
            "recommended_harness": self.recommended_harness,
            "planning_mode": self.planning_mode,
            "clarified_assumptions": list(self.clarified_assumptions),
            "goals": list(self.goals),
            "non_goals": list(self.non_goals),
            "decision_drivers": list(self.decision_drivers),
            "options": [_clone_jsonish(option) for option in self.options],
            "chosen_direction": self.chosen_direction,
            "rejection_rationale": list(self.rejection_rationale),
            "risks": list(self.risks),
            "mitigations": list(self.mitigations),
            "acceptance_criteria": list(self.acceptance_criteria),
            "verification_plan": list(self.verification_plan),
            "execution_handoff": self.execution_handoff,
            "review_gate": dict(self.review_gate),
            "quality_gate": _clone_jsonish(self.quality_gate),
            "deep_interview": _clone_jsonish(self.deep_interview),
            "stop_condition": self.stop_condition,
        }


def build_hermes_plan_payload(
    message: str,
    *,
    source: str = "generic",
    limit: int = 3,
    source_metadata: dict[str, str] | None = None,
    executor_target: str = "generic",
    decision_artifact: DecisionArtifact | None = None,
) -> dict[str, object]:
    task = message.strip()
    if not task:
        raise ValueError("hermes plan requires a task description")
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported hermes plan source: {source}")
    if executor_target not in CODING_EXECUTOR_TARGETS:
        raise ValueError(f"unsupported hermes plan executor: {executor_target}")
    if limit < 1:
        raise ValueError("hermes plan --limit must be at least 1")

    metadata_items = tuple(sorted((key, value) for key, value in (source_metadata or {}).items() if value))
    payload = _clone_jsonish(
        _build_hermes_plan_payload_cached(
            task,
            source,
            limit,
            executor_target,
            metadata_items,
        )
    )
    if decision_artifact is not None:
        payload["decision_receipt_handoff"] = build_decision_receipt_handoff(
            decision_artifact, target_workflow="ralplan"
        )
    return payload


@lru_cache(maxsize=2048)
def _build_hermes_plan_payload_cached(
    task: str,
    source: str,
    limit: int,
    executor_target: str,
    metadata_items: tuple[tuple[str, str], ...],
) -> dict[str, object]:
    recommendations = _compact_recommendations(recommend_skills(task, limit=max(limit, 5))[:limit])
    top = recommendations[0] if recommendations else {"skill": "oh-my-hermes", "score": 0, "confidence": "low"}
    plan = _plan_for(task, top)
    metadata = dict(metadata_items)
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "plan": plan.to_dict(),
        "wrapper_contract": _wrapper_contract(
            plan,
            source=source,
            source_metadata=metadata,
            executor_target=executor_target,
        ),
        "recommendations": recommendations,
    }
    composition = _workflow_composition_for(task, executor_target)
    if composition is not None:
        payload["workflow_composition"] = composition
    if metadata:
        payload["source_metadata"] = metadata
    return payload


def _workflow_composition_for(task: str, executor_target: str) -> dict[str, object] | None:
    """The ordered workflow a compound request asked for, or nothing (issue #816).

    A plan is built around one recommended skill. When the request asked for
    several outcomes at once, that single skill answers the loudest fragment and
    the rest disappear, so the composition is attached alongside it. Only a
    `composed` result is attached: a single-outcome request already has its
    answer in `plan`, and attaching a one-step composition to it would dress a
    single capability up as a workflow.

    An `executor_target` a composition cannot delegate to -- `hermes`, the chat
    orchestrator -- falls back to an unmade choice rather than being accepted.
    """
    coding_owner = (
        executor_target if executor_target in WORKFLOW_COMPOSITION_CODING_OWNERS else CODING_OWNER_CHOICE_PENDING
    )
    composition = build_workflow_composition(task, coding_owner=coding_owner)
    return composition if composition.get("state") == "composed" else None


def _clone_jsonish(value: Any) -> Any:
    value_type = type(value)
    if value_type is dict:
        return {key: _clone_jsonish(item) for key, item in value.items()}
    if value_type is list:
        return [_clone_jsonish(item) for item in value]
    if value_type is tuple:
        return tuple(_clone_jsonish(item) for item in value)
    return value


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


_LINE_BREAKS = "\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"
_HANDOFF_DELIMITER = re.compile(
    rf"(^|[{_LINE_BREAKS}])([^\S{_LINE_BREAKS}]*)(-{{5}} (?:BEGIN|END) ACCEPTED HERMES PLAN -{{5}})"
)


def _neutralise_handoff_delimiters(text: str) -> str:
    """No line of caller text may read as the handoff's own BEGIN/END delimiter."""
    return _HANDOFF_DELIMITER.sub(r"\1\2> \3", text)


def read_plan_file(path: str) -> str:
    """The text of a `--plan-file`, size-checked before it is read, or ValueError."""
    plan_path = Path(path).expanduser()
    if not plan_path.is_file():
        raise ValueError(f"--plan-file is not a readable file: {path}")
    if plan_path.stat().st_size > REVIEWED_BODY_MAX_BYTES:
        raise ValueError(f"--plan-file is larger than {REVIEWED_BODY_MAX_BYTES} bytes")
    return validate_reviewed_body(plan_path.read_text(encoding="utf-8"))


_BODY_BEGIN = "<!-- omh-reviewed-body-begin:{nonce} -->"
_BODY_END = "<!-- omh-reviewed-body-end:{nonce} -->"
_DIGEST_LINE = re.compile(r"^(?:body_nonce|body_sha256): .*\n", re.MULTILINE)


def _reviewed_body_lines(body: str, nonce: str) -> list[str]:
    return [
        "## Reviewed Plan",
        "",
        _BODY_BEGIN.format(nonce=nonce),
        validate_reviewed_body(body),
        _BODY_END.format(nonce=nonce),
        "",
    ]


def split_reviewed_body(text: str) -> tuple[str, str] | None:
    """(text without the reviewed body, the body) for a plan file whose body is intact.

    The body sits between two markers carrying a random nonce that is stored in
    the front matter beside the body's sha256. The nonce is chosen when the file
    is written, after the task is fixed, so text the person wrote cannot carry the
    markers. Both markers must occur exactly once and the digest must match;
    otherwise this returns None and the caller treats the whole text as not
    reviewed. The two front-matter digest lines and the markers go with the body.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    nonce = digest = ""
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("body_nonce: "):
            nonce = line[len("body_nonce: ") :].strip()
        elif line.startswith("body_sha256: "):
            digest = line[len("body_sha256: ") :].strip()
    if not re.fullmatch(r"[0-9a-f]{32}", nonce) or not digest:
        return None
    begin, end = _BODY_BEGIN.format(nonce=nonce), _BODY_END.format(nonce=nonce)
    if text.count(begin) != 1 or text.count(end) != 1:
        return None
    start = text.index(begin)
    stop = text.index(end)
    if stop < start:
        return None
    body = text[start + len(begin) : stop].strip("\n")
    if hashlib.sha256(body.encode("utf-8")).hexdigest() != digest:
        return None
    rest = text[:start] + text[stop + len(end) :]
    return _DIGEST_LINE.sub("", rest, count=2), body


def scan_text_without_reviewed_body(text: str) -> str:
    """What the delegate gate scans for a plan: everything main scanned, minus an intact reviewed body."""
    marker = "----- BEGIN ACCEPTED HERMES PLAN -----\n"
    head = ""
    if marker in text:
        cut = text.index(marker) + len(marker)
        head, text = text[:cut], text[cut:]
    split = split_reviewed_body(text)
    if not split:
        return head + text
    scan = head + split[0]
    # Cutting the body removes one copy of quote characters that pair across the
    # whole message; a second copy with quotes blanked keeps a path inside an
    # unclosed quote visible, as it was when the body was still there.
    return scan + "\n" + re.sub(r"[\"']", " ", scan)


_SYSTEM_ROOTS = "etc|usr|var|root|home|Users|opt|bin|sbin|sys|proc|dev|boot|lib|srv|mnt|private|tmp|System|Library|Applications|Volumes"


def outside_targets_note(paths: list[str]) -> str:
    return (
        "The reviewed plan names a path that may be outside the repository ("
        + ", ".join(paths)
        + "). The coding handoff gate scans the task, not the reviewed plan, so nothing else will flag it: "
        "check it before the executor starts."
    )


def outside_repository_targets(body: str) -> list[str]:
    """Absolute, home or parent-relative paths a reviewed body names, for a visibility note only."""
    from ..coding.coding_delegation import _safety_preflight_target_paths

    found: list[str] = []
    for line in body.split("\n"):
        for path in _safety_preflight_target_paths(line):
            outside = (
                path.startswith(("~/", "../"))
                or path in ("~", "..")
                or re.match(r"^[A-Za-z]:[\\/]", path)
                or re.match(rf"^/(?:{_SYSTEM_ROOTS})(?:/|$)", path)
            )
            if outside and path not in found:
                found.append(path)
                if len(found) >= 5:
                    return found
    return found


def apply_reviewed_body_to_payload(payload: dict[str, object]) -> None:
    """Make a payload agree with a file whose plan is the caller's reviewed text.

    A short task statement makes the scaffold `blocked` and ask for a
    clarification; with a reviewed body there is nothing left to ask. Applied to
    the copy that is rendered and to the stdout payload, so the two say the same.
    """
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        return
    payload["plan"] = plan = dict(plan)
    if plan.get("status") == "blocked":
        plan["status"] = "draft"
        gate = plan.get("quality_gate")
        if isinstance(gate, dict):
            plan["quality_gate"] = {**gate, "readiness": "ready_for_acceptance", "status_claim": "draft_plan_not_approval"}
        contract = payload.get("wrapper_contract")
        if isinstance(contract, dict):
            contract["next_action"] = "forward_plan_to_selected_workflow"
            contract["current_step"] = "present_plan"
        payload["say"] = (
            "The task statement alone was too short to classify, but the reviewed plan is recorded; "
            "ignore the clarification fields in this output."
        )
    plan["execution_handoff"] = (
        "Use the selected Hermes workflow only after the plan is accepted and the user confirms the recommended follow-on path."
    )
    plan["stop_condition"] = "The plan is accepted or a reviewer requests concrete changes."


def mark_payload_as_planning_input(payload: dict[str, object]) -> None:
    """Make stdout of `--input-bundle` say what the file says: input, not a plan to accept."""
    plan = payload.get("plan")
    gate = {
        "schema_version": "hermes_plan_quality/v1",
        "readiness": "input_not_a_plan",
        "status_claim": "planning_input_not_a_plan",
        "coding_handoff_ready": False,
    }
    payload.pop("workflow_composition", None)
    if isinstance(plan, dict):
        plan["status"] = "input"
        plan["quality_gate"] = dict(gate)
        plan["execution_handoff"] = "Hand this bundle to a planner as input; it is not a plan and has no executor handoff."
    contract = payload.get("wrapper_contract")
    if isinstance(contract, dict):
        contract["next_action"] = "hand_bundle_to_planner"
        contract["current_step"] = "planning_input_recorded"
        contract["coding_delegate"] = {"available": False, "unavailable_reason": "planning input is not a plan"}
        contract.pop("decision_gate", None)
        contract["quality_gate"] = dict(gate)
    payload["say"] = (
        "Recorded the bundle as planning input (hermes_plan_input/v1). It is not a plan: hand it to a planner; "
        "plan-accept refuses it."
    )


def validate_reviewed_body(body: str) -> str:
    """The reviewed plan text a caller wants recorded, or ValueError."""
    text = body.replace("\r\n", "\n").strip()
    text = _neutralise_handoff_delimiters(text)
    if not text:
        raise ValueError("--plan-file is empty: nothing reviewed to record")
    if len(text.encode("utf-8")) > REVIEWED_BODY_MAX_BYTES:
        raise ValueError(f"--plan-file is larger than {REVIEWED_BODY_MAX_BYTES} bytes")
    return text


def write_hermes_plan(
    paths: OmhPaths,
    payload: dict[str, object],
    *,
    reviewed_body: str | None = None,
    input_bundle: bool = False,
) -> dict[str, object]:
    """Write the file-backed plan artifact into OMH's store for this repository.

    With `reviewed_body` the caller's reviewed plan replaces the canned
    scaffold sections, and the front matter says `plan_body: reviewed`. With
    `input_bundle` the body is recorded as planning input (`hermes_plan_input/v1`),
    which `plan-accept` refuses because it is not a plan.
    """
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("hermes plan payload is missing plan")
    if input_bundle and reviewed_body is None:
        raise ValueError("--input-bundle needs --plan-file")
    if reviewed_body is not None and not input_bundle:
        # The caller's plan replaces the generated one wholesale: the composed
        # workflow, the stock stop condition and a "blocked" verdict derived
        # from a short task statement all belong to the scaffold, and would sit
        # next to the reviewed lanes as if the executor should follow both.
        payload = {**payload, "workflow_composition": None}
        apply_reviewed_body_to_payload(payload)
        plan = payload["plan"]
    slug = _slugify(str(plan.get("task_statement", "plan")))
    plans_dir = project_artifact_dir(paths, "plans")
    ensure_project_store_ignored(plans_dir)
    if input_bundle:
        path = _unique_artifact_path(plans_dir, f"{slug}-bundle", ".md")
        content = render_plan_input_markdown(payload, str(reviewed_body), path.name)
    else:
        path = _unique_artifact_path(plans_dir, slug, ".md")
        content = render_plan_markdown(payload, path.name, reviewed_body=reviewed_body)
    atomic_write_text(path, content, private=True)
    artifact: dict[str, object] = {
        "path": str(path),
        "kind": "hermes_plan_input" if input_bundle else "hermes_plan",
        "schema_version": INPUT_SCHEMA_VERSION if input_bundle else SCHEMA_VERSION,
        "status": "input" if input_bundle else plan.get("status", "draft"),
        "plan_body": "input" if input_bundle else ("reviewed" if reviewed_body is not None else "scaffold"),
    }
    if plan.get("status") == "blocked" and not input_bundle:
        context_path = _unique_artifact_path(
            project_artifact_dir(paths, "plan-context"), f"{slug}-context", ".md"
        )
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
                "summary": {
                    "reviewed": "Hermes file-backed plan artifact was created with a reviewed plan body.",
                    "input": "Hermes planning input bundle was recorded; it is not a plan.",
                }.get(str(artifact["plan_body"]), "Hermes file-backed plan artifact was created from the scaffold, with no reviewed body."),
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
        "plan_body": artifact.get("plan_body", "unknown"),
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
        "plan_body": str(frontmatter.get("plan_body", "unknown")),
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
    body_state = str(artifact.get("plan_body", "unknown"))
    note = ""
    if status == "accepted" and body_state == "scaffold":
        note = (
            "This plan file holds only the generated scaffold, not a reviewed plan. "
            "Accepting it accepts the scaffold; record the reviewed plan with --plan-file first."
        )
        result["reviewed_body"] = False
    elif status == "accepted" and body_state == "unknown":
        note = "This plan file does not record whether it holds a reviewed plan or only the generated scaffold."
        result["reviewed_body"] = None
    if status == "accepted" and body_state == "reviewed":
        split = split_reviewed_body(original)
        outside = outside_repository_targets(split[1]) if split else []
        if outside:
            note = outside_targets_note(outside)
    if note:
        result["say"] = note
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
                "summary": " ".join(part for part in (summary or f"Hermes plan marked {status}.", note) if part),
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
            _neutralise_handoff_delimiters(str(artifact.get("text", "")).strip()),
            "----- END ACCEPTED HERMES PLAN -----",
        ]
    )


def build_plan_handoff_context_pack(artifact: dict[str, object], *, executor_target: str = "generic") -> dict[str, object]:
    plan_artifact_path = str(artifact.get("path", ""))
    # Copied into each consumer below so editing one scope cannot rewrite the others.
    scope = {"kind": "project", "ref": project_identity()}
    pack = {
        "schema_version": "handoff_context_pack/v1",
        "executor_target": executor_target,
        "session_id": "",
        "scope": dict(scope),
        "metadata": {
            "plan_artifact_path": plan_artifact_path,
            "plan_artifact_ref": plan_artifact_path,
            "plan_artifact_status": str(artifact.get("status", "")),
            "plan_artifact_schema_version": str(artifact.get("schema_version", "")),
            "plan_artifact_sha256": str(artifact.get("sha256", "")),
            "plan_artifact_plan_body": str(artifact.get("plan_body", "unknown")),
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
                    f"plan_body={artifact.get('plan_body', 'unknown')}"
                    f"{' (generated scaffold, no reviewed plan)' if artifact.get('plan_body') == 'scaffold' else ''}; "
                    f"sha256={artifact.get('sha256', '')}."
                ),
                "artifact_ref": plan_artifact_path,
                "source": "hermes_plan",
                "truth_level": "approved_context",
                "scope": dict(scope),
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
    executor_target: str = "generic",
) -> dict[str, object]:
    pack = build_plan_handoff_context_pack(artifact, executor_target=executor_target)
    path = paths.runtime_plan_context_dir / f"{Path(str(artifact.get('path', 'plan'))).stem}-context-pack.json"
    atomic_write_json(path, pack, private=True)
    return {"path": str(path), "context_pack": pack}


def render_plan_markdown(
    payload: dict[str, object],
    artifact_name: str = "plan.md",
    *,
    reviewed_body: str | None = None,
) -> str:
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("hermes plan payload is missing plan")
    review_gate = plan.get("review_gate", {})
    if not isinstance(review_gate, dict):
        review_gate = {}
    metadata = payload.get("source_metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    nonce = secrets.token_hex(16)
    lines = [
        "---",
        f"schema_version: {SCHEMA_VERSION}",
        f"status: {plan.get('status', 'draft')}",
        f"source: {payload.get('source', 'generic')}",
        f"plan_body: {'scaffold' if reviewed_body is None else 'reviewed'}",
        *(
            [
                f"body_nonce: {nonce}",
                f"body_sha256: {hashlib.sha256(validate_reviewed_body(reviewed_body).encode('utf-8')).hexdigest()}",
            ]
            if reviewed_body is not None
            else []
        ),
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
            *(
                _reviewed_body_lines(reviewed_body, nonce)
                if reviewed_body is not None
                else _scaffold_section_lines(plan)
            ),
            *_composed_workflow_lines(payload.get("workflow_composition")),
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


def _scaffold_section_lines(plan: dict[str, object]) -> list[str]:
    """The canned sections of a plan recorded without a reviewed body."""
    return [
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
    ]


def render_plan_input_markdown(payload: dict[str, object], body: str, artifact_name: str) -> str:
    """A planning input bundle: recorded beside the plans, never acceptable as one."""
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("hermes plan payload is missing plan")
    return "\n".join(
        [
            "---",
            f"schema_version: {INPUT_SCHEMA_VERSION}",
            "status: input",
            f"source: {payload.get('source', 'generic')}",
            "---",
            "",
            f"# Planning Input: {plan.get('task_statement', 'Untitled task')}",
            "",
            f"Artifact: `{artifact_name}`",
            "",
            "INPUT TO PLANNING, NOT A PLAN. A planner consumes this; it has no acceptance criteria, order or owner.",
            "",
            "## Task Statement",
            "",
            str(plan.get("task_statement", "")).strip(),
            "",
            "## Bundle",
            "",
            validate_reviewed_body(body),
            "",
        ]
    )


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
    lines = text.split("\n")
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
    tail = lines[end_index + 1 :]
    if tail and tail[-1] == "":
        tail.pop()
    return "\n".join(["---", *frontmatter, "---", *tail]) + "\n"


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
        "plan_body": artifact.get("plan_body", "unknown"),
    }


def _unquote_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _plan_for(task: str, top: dict[str, object]) -> HermesPlan:
    lowered = task.lower()
    score = _int_value(top.get("score", 0))
    top_skill = str(top.get("skill", ""))
    weak = len(task.split()) <= 2 and (score == 0 or any(term in lowered for term in _CLARIFY_TERMS))
    review_shaped = any(term in lowered for term in _REVIEW_TERMS)
    reviewed_plan_shaped = review_shaped or top_skill == "ralplan"
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

    workflow = "ralplan" if reviewed_plan_shaped else "plan"
    harness = "planning"
    handoff = (
        "After this plan is accepted and the user confirms the selected executor, use `omh coding delegate --executor <selected-executor> --record --from-plan <accepted-plan.md>` for a run-backed coding handoff."
        if coding_shaped
        else "Use the selected Hermes workflow only after the plan is accepted and the user confirms the recommended follow-on path."
    )
    return HermesPlan(
        status="draft",
        task_statement=task,
        recommended_workflow=workflow,
        recommended_harness=harness,
        planning_mode="review-gated" if reviewed_plan_shaped else "structured",
        clarified_assumptions=("The task statement is sufficient for a first deterministic planning scaffold.",),
        goals=_goals(coding_shaped, reviewed_plan_shaped),
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
        options=_options("reviewed" if reviewed_plan_shaped else "structured"),
        chosen_direction=_chosen_direction(coding_shaped, reviewed_plan_shaped),
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
            review_shaped=reviewed_plan_shaped,
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


def _resolved_reasoning_demand(item: dict[str, object]) -> str:
    value = item.get("reasoning_demand")
    if value in {"light", "standard", "heavy"}:
        return str(value)
    skill = str(item.get("skill") or "")
    return next(
        (definition.reasoning_demand for definition in routable_definitions() if definition.name == skill),
        "standard",
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
                "reasoning_demand": _resolved_reasoning_demand(item),
            }
        )
    return compact


def _wrapper_contract(
    plan: HermesPlan,
    *,
    source: str,
    source_metadata: dict[str, str],
    executor_target: str,
) -> dict[str, object]:
    coding_available = plan.status == "draft" and _is_coding_shaped(plan.task_statement)
    metadata_args = _source_metadata_argv(source_metadata)
    executor_handoff = executor_handoff_metadata_for_target(executor_target)
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
                        executor_target,
                        "--source",
                        source,
                        "--record",
                        "--from-plan",
                        "{plan_artifact}",
                        *metadata_args,
                    ],
                    "executor_target": executor_handoff.executor_target,
                    "executor_choice_required": executor_handoff.executor_choice_required,
                    "selected_executor_profile": executor_handoff.selected_executor_profile,
                    "work_owner_mode": executor_handoff.work_owner_mode,
                    "after_acceptance_next_action": executor_handoff.after_acceptance_next_action,
                    "prepared_handoff_field": executor_handoff.prepared_handoff_field,
                    "prepared_handoff_boundary": executor_handoff.prepared_handoff_boundary,
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
            # Static interview policy. These describe the bounded interview the skill
            # instructs; they are not live counters. `rerun_hermes_plan` is stateless, so a
            # `round` field would report 1 forever. The live count lives in the thread header.
            "max_rounds": DEEP_INTERVIEW_MAX_ROUNDS,
            "soft_check_round": DEEP_INTERVIEW_SOFT_CHECK_ROUND,
            "clarity_dimensions": list(DEEP_INTERVIEW_CLARITY_DIMENSIONS),
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


def is_coding_shaped_task(task: str) -> bool:
    return _is_coding_shaped(task)


def _markdown_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return ["- None recorded."]
    return [f"- {str(value)}" for value in values if str(value)] or ["- None recorded."]


def _composed_workflow_lines(composition: object) -> list[str]:
    """The ordered workflow section, present only when the request composed.

    The recorded artifact is what a coding owner is handed after acceptance, so
    a composition that lived only in stdout would be lost exactly where it
    matters. The section is omitted entirely for a single-outcome plan rather
    than rendered empty, which keeps every existing artifact byte-identical.
    """
    if not isinstance(composition, dict) or composition.get("state") != "composed":
        return []
    steps = composition.get("steps")
    if not isinstance(steps, list) or not steps:
        return []
    lines = ["## Composed Workflow", ""]
    for step in steps:
        if not isinstance(step, dict):
            continue
        status = " (capability not available)" if step.get("capability_status") == "missing" else ""
        lines.append(
            f"{step.get('order', '')}. `{step.get('capability', '')}` — owner: "
            f"{step.get('owner', '')} ({step.get('owner_kind', '')}){status}"
        )
        lines.append("")
        lines.append("Inputs:")
        lines.extend(_markdown_list(step.get("inputs", [])))
        lines.append("")
        lines.append(f"Output: {step.get('output', '')}")
        lines.append("")
        lines.append(f"Evidence boundary: {step.get('evidence_boundary', '')}")
        lines.append("")
    gaps = composition.get("missing_capabilities")
    if isinstance(gaps, list) and gaps:
        lines.append("Missing capabilities (reported, not installed):")
        lines.extend(
            f"- {gap.get('capability', '')} ({gap.get('needed_for_step', '')}): {gap.get('reason', '')}"
            for gap in gaps
            if isinstance(gap, dict)
        )
        lines.append("")
    lines.append(str(composition.get("ownership_rule", "")))
    lines.append("")
    lines.append(str(composition.get("claim_boundary", "")))
    lines.append("")
    return lines


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
