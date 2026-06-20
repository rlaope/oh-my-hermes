from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from ..executors import CODING_EXECUTOR_TARGETS, CODING_RUNTIME_HANDOFF_TARGETS, executor_label
from ..isolation import build_isolation_plan
from ..paths import OmhPaths, expand_path
from ..worktree_creator import latest_observed_worktree_record
from .executor_sessions import build_executor_launch_contract

WORKTREE_BINDING_SCHEMA_VERSION = "worktree_executor_binding/v1"


def build_worktree_executor_binding(
    paths: OmhPaths,
    *,
    worktree_path: str | Path,
    executor: str,
    session_id: str = "",
    run_id: str = "",
    runtime_profile: str = "",
    prompt_ref: str = "",
) -> dict[str, Any]:
    if executor == "choose" or executor not in CODING_EXECUTOR_TARGETS:
        raise ValueError(f"unsupported executor for worktree binding: {executor}")
    resolved_path = expand_path(worktree_path)
    observed_record = latest_observed_worktree_record(paths, resolved_path)
    path_exists = resolved_path.exists()
    status = _binding_status(path_exists=path_exists, observed_record=observed_record)
    isolation_status = _binding_isolation_status(
        executor=executor,
        status=status,
        worktree_path=resolved_path,
        observed_record=observed_record,
    )
    launch = build_executor_launch_contract(
        executor,
        session_id=session_id or "worktree-binding",
        isolation_status=isolation_status,
    )
    launch["resolved_workspace_path"] = str(resolved_path)
    launch["resolved_command_templates"] = _resolve_workspace_templates(launch, resolved_path)
    launch["preferred_command_template_id"] = _preferred_workspace_template_id(
        launch["resolved_command_templates"]
    )
    preferred_command_template_id = str(launch["preferred_command_template_id"])
    return {
        "schema_version": WORKTREE_BINDING_SCHEMA_VERSION,
        "status": status,
        "executor": {
            "profile": executor,
            "label": executor_label(executor),
            "terminal_launch_available": bool(launch.get("terminal_launch_available")),
        },
        "worktree": {
            "path": str(resolved_path),
            "exists": path_exists,
            "observed_in_omh_ledger": bool(observed_record),
            "evidence_refs": list(observed_record.get("evidence_refs", [])) if observed_record else [],
            "record": observed_record or None,
        },
        "session_binding": {
            "session_id": session_id,
            "run_id": run_id,
            "runtime_profile": runtime_profile
            or (executor if executor in CODING_RUNTIME_HANDOFF_TARGETS else ""),
            "prompt_ref": prompt_ref,
        },
        "launch": launch,
        "wrapper_actions": _binding_actions(
            executor=executor,
            status=status,
            worktree_path=resolved_path,
            session_id=session_id,
            run_id=run_id,
            runtime_profile=runtime_profile,
            prompt_ref=prompt_ref,
            preferred_command_template_id=preferred_command_template_id,
        ),
        "next_action": _binding_next_action(status, executor=executor, session_id=session_id, run_id=run_id),
        "claim_boundary": (
            "A worktree binding recipe is wrapper guidance only. It can show how to open or attach a "
            "coding-agent session in an isolated workspace, but OMH does not launch the executor or claim "
            "coding progress until matching observed session or runtime evidence is recorded."
        ),
        "not_evidence_until_observed": [
            "executor_dispatch",
            "executor_result",
            "verification",
            "review",
            "ci",
            "merge_readiness",
            "merge",
        ],
    }


def _binding_isolation_status(
    *,
    executor: str,
    status: str,
    worktree_path: Path,
    observed_record: dict[str, Any],
) -> dict[str, object]:
    plan = build_isolation_plan(
        "isolated coding-agent session",
        intent="implementation",
        workflow="ultrawork",
        work_owner_mode=(
            "runtime_handoff" if executor in CODING_RUNTIME_HANDOFF_TARGETS else "external_executor"
        ),
        selected_executor_profile=executor,
    )
    plan = {**plan, "worktree_path": str(worktree_path)}
    return {
        "schema_version": "worktree_session_isolation_status/v1",
        "status": "observed"
        if observed_record
        else ("filesystem_only" if status != "blocked_missing_worktree" else "missing"),
        "strategy": str(plan.get("strategy", "worktree_recommended")),
        "risk_level": str(plan.get("risk_level", "high")),
        "next_action": (
            "open_executor_session" if status != "blocked_missing_worktree" else "prepare_worktree"
        ),
        "observed": bool(observed_record),
        "worktree_path": str(worktree_path),
        "plan": plan,
        "claim_boundary": (
            "This binding uses an isolated workspace path for a future coding-agent session. "
            "It is not executor dispatch, implementation, verification, review, CI, merge-readiness, or merge evidence."
        ),
    }


def _binding_status(*, path_exists: bool, observed_record: dict[str, Any]) -> str:
    if observed_record:
        return "ready_observed_worktree"
    if path_exists:
        return "ready_filesystem_only"
    return "blocked_missing_worktree"


def _binding_next_action(status: str, *, executor: str, session_id: str, run_id: str) -> str:
    if status == "blocked_missing_worktree":
        return "prepare_worktree_before_opening_executor"
    if executor in CODING_RUNTIME_HANDOFF_TARGETS and (session_id or run_id):
        return "open_runtime_session_then_record_runtime_observation"
    if session_id:
        return "open_executor_session_then_record_observed_session"
    return "open_executor_in_worktree_then_attach_session_ref"


def _resolve_workspace_templates(launch: dict[str, Any], worktree_path: Path) -> list[dict[str, Any]]:
    workspace = str(worktree_path)
    workspace_shell = shlex.quote(workspace)
    resolved: list[dict[str, Any]] = []
    for template in launch.get("command_templates", []):
        if not isinstance(template, dict):
            continue
        rendered = dict(template)
        argv_template = template.get("argv_template")
        if isinstance(argv_template, list):
            rendered["argv_template"] = [
                _replace_workspace_placeholders(str(item), workspace, workspace_shell)
                for item in argv_template
            ]
        shell_template = template.get("shell_command_template")
        if isinstance(shell_template, str):
            rendered["shell_command_template"] = _replace_workspace_placeholders(
                shell_template, workspace, workspace_shell
            )
        resolved.append(rendered)
    return resolved


def _preferred_workspace_template_id(templates: list[dict[str, Any]]) -> str:
    for template in templates:
        if (
            "{workspace_path}" in str(template)
            or " --cd " in str(template)
            or "--add-dir" in str(template)
        ):
            return str(template.get("id", ""))
    return str(templates[0].get("id", "")) if templates else ""


def _replace_workspace_placeholders(value: str, workspace: str, workspace_shell: str) -> str:
    return value.replace("{workspace_path}", workspace).replace("{workspace_path_shell_quoted}", workspace_shell)


def _binding_actions(
    *,
    executor: str,
    status: str,
    worktree_path: Path,
    session_id: str,
    run_id: str,
    runtime_profile: str,
    prompt_ref: str,
    preferred_command_template_id: str,
) -> list[dict[str, Any]]:
    disabled_reason = (
        "Worktree path is missing; run omh worktree prepare first."
        if status == "blocked_missing_worktree"
        else ""
    )
    worktree_ref = str(worktree_path)
    worktree_evidence_ref = f"worktree:{worktree_ref}"
    worktree_evidence_arg = shlex.quote(worktree_evidence_ref)
    actions: list[dict[str, Any]] = [
        {
            "id": "open_executor_session",
            "label": f"Open in {executor_label(executor)}",
            "enabled": not disabled_reason,
            "style": "primary",
            "disabled_reason": disabled_reason,
            "worktree_path": worktree_ref,
            "prompt_ref": prompt_ref,
            "backend_action_owner": "wrapper",
            "launch_command_template_id": preferred_command_template_id,
            "claim_boundary": (
                "Opening the executor is observed only after Hermes or the wrapper actually starts "
                "or attaches the session."
            ),
        },
        {
            "id": "attach_executor_session",
            "label": "Attach existing session",
            "enabled": not disabled_reason,
            "style": "secondary",
            "disabled_reason": disabled_reason,
            "backend_action_owner": "wrapper",
            "input_schema": {
                "type": "object",
                "required": ["external_session_ref"],
                "properties": {
                    "external_session_ref": {"type": "string", "title": "Coding session reference"},
                    "evidence_ref": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    ]
    if session_id and executor not in CODING_RUNTIME_HANDOFF_TARGETS:
        actions.append(
            {
                "id": "record_executor_opened",
                "label": "Record opened",
                "enabled": not disabled_reason,
                "style": "secondary",
                "backend_command": (
                    f"omh chat session open-executor {shlex.quote(session_id)} --observed "
                    f"--evidence-ref {worktree_evidence_arg}"
                ),
                "claim_boundary": (
                    "This records that a wrapper observed session open/dispatch; it is not executor "
                    "result evidence."
                ),
            }
        )
    runtime = runtime_profile or (executor if executor in CODING_RUNTIME_HANDOFF_TARGETS else "")
    if runtime and (session_id or run_id):
        target = f"--session {shlex.quote(session_id)}" if session_id else f"--run {shlex.quote(run_id)}"
        actions.append(
            {
                "id": "record_worktree_runtime_observation",
                "label": "Record worktree observation",
                "enabled": not disabled_reason,
                "style": "secondary",
                "backend_command": (
                    f"omh runtime observe {target} --runtime-profile {shlex.quote(runtime)} "
                    f"--event worktree_creation --status observed --worktree-ref {shlex.quote(worktree_ref)} "
                    f"--evidence-ref {worktree_evidence_arg}"
                ),
                "claim_boundary": (
                    "This records workspace-isolation evidence only; runtime start and worker/result "
                    "events remain separate."
                ),
            }
        )
    return actions
