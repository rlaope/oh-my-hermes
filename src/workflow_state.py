from __future__ import annotations

from json import JSONDecodeError
from pathlib import Path
from typing import Any

from .local_store import atomic_write_json, read_json_object, utc_now
from .paths import OmhPaths
from .skill_pack import CORE_SKILLS

SCHEMA_VERSION = 1
LIFECYCLE_OUTCOMES = ("finished", "blocked", "failed", "user_interlude", "question_pending")

ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "deep-interview": ("plan", "ralplan"),
    "plan": ("ultragoal", "team", "ralph", "ultraqa"),
    "ralplan": ("ultragoal", "team", "ralph", "ultraqa"),
}


class WorkflowStateError(ValueError):
    pass


def validate_workflow_name(workflow: str) -> None:
    if workflow not in CORE_SKILLS:
        raise WorkflowStateError(f"unknown workflow: {workflow}")


def workflow_state_path(paths: OmhPaths, workflow: str) -> Path:
    validate_workflow_name(workflow)
    return paths.workflow_state_dir / f"{workflow}-state.json"


def read_workflow_state(paths: OmhPaths, workflow: str) -> dict[str, Any] | None:
    path = workflow_state_path(paths, workflow)
    try:
        data = read_json_object(path)
    except JSONDecodeError:
        raise
    except ValueError as exc:
        raise WorkflowStateError(f"state for {workflow} must be a JSON object") from exc
    if not data:
        return None
    if data.get("workflow") not in {None, workflow}:
        raise WorkflowStateError(f"state file {path} belongs to {data.get('workflow')!r}")
    return data


def read_workflow_state_result(paths: OmhPaths, workflow: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return read_workflow_state(paths, workflow), None
    except (OSError, JSONDecodeError, WorkflowStateError, ValueError) as exc:
        return None, str(exc)


def list_workflow_states(paths: OmhPaths) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    states: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    if not paths.workflow_state_dir.exists():
        return states, errors
    for path in sorted(paths.workflow_state_dir.glob("*-state.json")):
        workflow = path.name[: -len("-state.json")]
        state, error = read_workflow_state_result(paths, workflow)
        if error:
            errors.append({"path": str(path), "error": error})
        elif state:
            states.append(state)
    return states, errors


def active_workflow_states(paths: OmhPaths) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    states, errors = list_workflow_states(paths)
    return [state for state in states if state.get("active")], errors


def _terminal_state(workflow: str, state: dict[str, Any] | None, outcome: str, note: str = "", transition_target: str | None = None) -> dict[str, Any]:
    if outcome not in LIFECYCLE_OUTCOMES:
        raise WorkflowStateError(f"unsupported lifecycle outcome: {outcome}")
    now = utc_now()
    base = state or {"workflow": workflow, "started_at": now}
    result = {
        **base,
        "schema_version": SCHEMA_VERSION,
        "workflow": workflow,
        "active": False,
        "lifecycle_outcome": outcome,
        "updated_at": now,
    }
    if note:
        result["note"] = note
    if transition_target:
        result["transition_target"] = transition_target
    return result


def finish_workflow_state(paths: OmhPaths, workflow: str, outcome: str = "finished", note: str = "") -> dict[str, Any]:
    state = read_workflow_state(paths, workflow)
    result = _terminal_state(workflow, state, outcome, note)
    atomic_write_json(workflow_state_path(paths, workflow), result, private=True)
    return result


def _transition_allowed(source: str, destination: str) -> bool:
    return destination in ALLOWED_TRANSITIONS.get(source, ())


def start_workflow_state(paths: OmhPaths, workflow: str, note: str = "") -> dict[str, Any]:
    validate_workflow_name(workflow)
    active, errors = active_workflow_states(paths)
    if errors:
        first = errors[0]
        raise WorkflowStateError(f"cannot start workflow while state is unreadable: {first['path']}: {first['error']}")
    now = utc_now()
    for current in active:
        source = str(current.get("workflow", ""))
        if source == workflow:
            updated = {**current, "schema_version": SCHEMA_VERSION, "active": True, "updated_at": now}
            if note:
                updated["note"] = note
            atomic_write_json(workflow_state_path(paths, workflow), updated, private=True)
            return updated
        if not _transition_allowed(source, workflow):
            raise WorkflowStateError(f"cannot start {workflow}; active workflow {source} must finish or be cleared first")
    for current in active:
        source = str(current["workflow"])
        completed = _terminal_state(source, current, "finished", f"auto-completed before starting {workflow}", workflow)
        atomic_write_json(workflow_state_path(paths, source), completed, private=True)
    state = {
        "schema_version": SCHEMA_VERSION,
        "workflow": workflow,
        "active": True,
        "lifecycle_outcome": None,
        "started_at": now,
        "updated_at": now,
    }
    if note:
        state["note"] = note
    atomic_write_json(workflow_state_path(paths, workflow), state, private=True)
    return state


def clear_workflow_state(paths: OmhPaths, workflow: str) -> bool:
    path = workflow_state_path(paths, workflow)
    if not path.exists():
        return False
    path.unlink()
    return True
