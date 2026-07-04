from __future__ import annotations

from typing import Any, Mapping

from ..executors import (
    HERMES_CODING_TEAM_STATUS_LADDER,
    HERMES_CODING_TEAM_WRAPPER_ACTIONS,
    hermes_coding_team_path_contract,
)


HERMES_CODING_HARNESS_SCHEMA_VERSION = "hermes_coding_harness/v1"

WORKFLOW_STAGES: tuple[tuple[str, str, str, str], ...] = (
    ("intake", "planner", "Pick Hermes as the coding owner and explain why.", ""),
    ("scope", "planner", "Define goal, non-goals, constraints, risk, and affected areas.", ""),
    ("plan", "planner", "Prepare acceptance criteria, verification commands, and rollback notes.", ""),
    ("workspace", "builder", "Choose same workspace, recommended worktree, or required worktree.", "worktree_creation"),
    ("build", "builder", "Run the selected Hermes coding skill lane.", "worker_result"),
    ("verify", "verifier", "Record unit, integration, smoke, docs, or render checks.", "verification"),
    ("review", "reviewer", "Record code-review, architecture, security, or risk review evidence.", "review"),
    ("docs_sync", "docs-specialist", "Sync README, docs, site, generated skills, and public claims when behavior changed.", ""),
    ("pr_prep", "release-operator", "Prepare branch summary, commits, PR body, review checklist, and evidence gaps.", "merge_readiness"),
    ("handover", "release-operator", "Report next action: fix, verify, open PR, review, merge-ready, or stop.", "merge"),
)

LANE_DEFINITIONS: tuple[tuple[str, str, str, str], ...] = (
    ("builder_lane", "builder", "Implementation scope, file/worktree ownership, and changed-file reporting.", "worker_result"),
    ("verifier_lane", "verifier", "Commands/checks to run and observed verification refs to record.", "verification"),
    ("reviewer_lane", "reviewer", "Findings-first code, architecture, security, or risk review.", "review"),
    ("docs_lane", "docs-specialist", "Public claim, README/docs/site, and generated skill sync.", ""),
    ("pr_lane", "release-operator", "PR body, DCO/trailers, CI, merge-readiness, and merge status.", "merge_readiness"),
)

CLAIM_BOUNDARY = (
    "hermes_coding_harness/v1 is a read-only projection over prepared handoffs and observed "
    "runtime_observation/v1 evidence. It does not launch Hermes, edit code, create worktrees, run tests, "
    "review PRs, pass CI, create PRs, mark merge-ready, or merge."
)


def build_hermes_coding_harness(
    *,
    runtime_handoff: Mapping[str, Any] | None = None,
    runtime_observation: Mapping[str, Any] | None = None,
    session: Mapping[str, Any] | None = None,
    executor_status: Mapping[str, Any] | None = None,
    start_mode: str = "",
) -> dict[str, Any]:
    """Project Hermes-owned coding state without writing evidence.

    The harness intentionally consumes existing handoff/session/runtime status and
    produces one wrapper-friendly view. It never mutates ledgers or upgrades
    prepared state into observed evidence.
    """

    handoff = _mapping(runtime_handoff)
    observation = _mapping(runtime_observation)
    session_obj = _mapping(session)
    executor = str(
        handoff.get("selected_executor_profile")
        or session_obj.get("selected_executor_profile")
        or _mapping(executor_status).get("selected_executor_profile")
        or ""
    )
    if executor != "hermes":
        return {}

    observed_events = _string_set(observation.get("observed_events"))
    blocked_events = _string_set(observation.get("blocked_events"))
    failed_events = _string_set(observation.get("failed_events"))
    unsatisfied_events = _unsatisfied_events(observation, observed_events=observed_events)
    latest_by_event = _mapping(observation.get("latest"))
    resolved_start_mode = _resolve_start_mode(start_mode, handoff=handoff, observed_events=observed_events, latest_by_event=latest_by_event)
    workflow_graph = [
        _stage_payload(
            stage_id,
            owner_role,
            purpose,
            event_type,
            observed_events=observed_events,
            blocked_events=blocked_events,
            failed_events=failed_events,
            prepared=bool(handoff),
        )
        for stage_id, owner_role, purpose, event_type in WORKFLOW_STAGES
    ]
    lanes = [
        _lane_payload(
            lane_id,
            owner_role,
            purpose,
            event_type,
            start_mode=resolved_start_mode,
            observed_events=observed_events,
            blocked_events=blocked_events,
            failed_events=failed_events,
            latest_by_event=latest_by_event,
        )
        for lane_id, owner_role, purpose, event_type in LANE_DEFINITIONS
    ]
    verification_matrix = _verification_matrix(handoff, observed_events=observed_events, blocked_events=blocked_events, failed_events=failed_events)
    pr_preparation = _pr_preparation(
        observed_events=observed_events,
        blocked_events=blocked_events,
        failed_events=failed_events,
        latest_by_event=latest_by_event,
    )
    docs_sync = _docs_sync(handoff, observed_events=observed_events, latest_by_event=latest_by_event)
    status = _harness_status(
        observed_events=observed_events,
        blocked_events=blocked_events,
        failed_events=failed_events,
        unsatisfied_events=unsatisfied_events,
        projection_missing_evidence=_projection_missing_evidence(
            verification_matrix=verification_matrix,
            docs_sync=docs_sync,
            pr_preparation=pr_preparation,
        ),
    )

    return {
        "schema_version": HERMES_CODING_HARNESS_SCHEMA_VERSION,
        "status": status,
        "session_id": str(session_obj.get("session_id", "")),
        "run_id": str(session_obj.get("current_run_id", "")),
        "selected_owner": "hermes",
        "start_mode": resolved_start_mode,
        "source_of_truth": [
            "wrapper_session",
            "coding_runtime_handoff/v1",
            "hermes_coding_team_path/v1",
            "status_card/v1",
            "harness_progress/v1",
            "worktree_session_isolation/v1",
            "runtime_observation/v1",
            "conformance_report/v1",
        ],
        "workflow_graph": workflow_graph,
        "lanes": lanes,
        "gates": _gate_payloads(observed_events=observed_events, blocked_events=blocked_events, failed_events=failed_events),
        "verification_matrix": verification_matrix,
        "docs_sync": docs_sync,
        "pr_preparation": pr_preparation,
        "wrapper_actions": _wrapper_actions(),
        "runtime_observation_requirements": _runtime_requirements(),
        "safe_status_lines": _safe_status_lines(
            status=status,
            start_mode=resolved_start_mode,
            workflow_graph=workflow_graph,
            verification_matrix=verification_matrix,
            docs_sync=docs_sync,
            pr_preparation=pr_preparation,
        ),
        "claim_boundary": CLAIM_BOUNDARY,
    }


def validate_hermes_coding_harness(harness: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(harness, dict):
        return ["hermes_coding_harness must be an object"]
    allowed_keys = {
        "schema_version",
        "status",
        "session_id",
        "run_id",
        "selected_owner",
        "start_mode",
        "source_of_truth",
        "workflow_graph",
        "lanes",
        "gates",
        "verification_matrix",
        "docs_sync",
        "pr_preparation",
        "wrapper_actions",
        "runtime_observation_requirements",
        "safe_status_lines",
        "claim_boundary",
    }
    extra_keys = sorted(set(harness) - allowed_keys)
    if extra_keys:
        errors.append(f"hermes_coding_harness has unsupported keys: {extra_keys}")
    if harness.get("schema_version") != HERMES_CODING_HARNESS_SCHEMA_VERSION:
        errors.append("hermes_coding_harness schema_version is invalid")
    if harness.get("selected_owner") != "hermes":
        errors.append("hermes_coding_harness selected_owner must be hermes")
    if harness.get("status") not in {"prepared_not_observed", "in_progress", "blocked", "completed", "failed"}:
        errors.append("hermes_coding_harness status is invalid")
    if harness.get("start_mode") not in {"solo", "durable_goal", "team", "swarm"}:
        errors.append("hermes_coding_harness start_mode is invalid")
    stages = harness.get("workflow_graph")
    if not isinstance(stages, list):
        errors.append("hermes_coding_harness workflow_graph must be a list")
    else:
        stage_ids = [stage.get("id") for stage in stages if isinstance(stage, dict)]
        expected_stage_ids = [stage[0] for stage in WORKFLOW_STAGES]
        if stage_ids != expected_stage_ids:
            errors.append("hermes_coding_harness workflow_graph must include the canonical ordered stages")
        errors.extend(_validate_stage_payloads(stages))
    lanes = harness.get("lanes")
    if not isinstance(lanes, list):
        errors.append("hermes_coding_harness lanes must be a list")
    else:
        lane_ids = [lane.get("id") for lane in lanes if isinstance(lane, dict)]
        expected_lane_ids = [lane[0] for lane in LANE_DEFINITIONS]
        if lane_ids != expected_lane_ids:
            errors.append("hermes_coding_harness lanes must include builder/verifier/reviewer/docs/pr lanes")
        errors.extend(_validate_lane_payloads(lanes))
    for key in ("gates", "wrapper_actions", "runtime_observation_requirements", "safe_status_lines"):
        if not isinstance(harness.get(key), list):
            errors.append(f"hermes_coding_harness {key} must be a list")
    for key in ("verification_matrix", "docs_sync", "pr_preparation"):
        if not isinstance(harness.get(key), dict):
            errors.append(f"hermes_coding_harness {key} must be an object")
    errors.extend(_validate_verification_matrix(harness.get("verification_matrix")))
    errors.extend(_validate_docs_sync(harness.get("docs_sync")))
    errors.extend(_validate_pr_preparation(harness.get("pr_preparation")))
    if "read-only projection" not in str(harness.get("claim_boundary", "")):
        errors.append("hermes_coding_harness claim_boundary must state read-only projection")
    return errors


def compact_hermes_coding_harness(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    compact: dict[str, Any] = {
        "schema_version": str(value.get("schema_version", "")),
        "status": str(value.get("status", "")),
        "selected_owner": str(value.get("selected_owner", "")),
        "start_mode": str(value.get("start_mode", "")),
        "source_of_truth": [str(item) for item in value.get("source_of_truth", []) if str(item)]
        if isinstance(value.get("source_of_truth"), list)
        else [],
        "safe_status_lines": [str(item) for item in value.get("safe_status_lines", []) if str(item)]
        if isinstance(value.get("safe_status_lines"), list)
        else [],
        "claim_boundary": str(value.get("claim_boundary", "")),
    }
    for key in ("workflow_graph", "lanes", "gates", "wrapper_actions", "runtime_observation_requirements"):
        if isinstance(value.get(key), list):
            compact[key] = value[key]
    for key in ("verification_matrix", "docs_sync", "pr_preparation"):
        if isinstance(value.get(key), dict):
            compact[key] = value[key]
    return compact


def _validate_verification_matrix(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return errors
    allowed = {
        "schema_version",
        "status",
        "required_checks",
        "optional_checks",
        "missing_evidence",
        "failure_action",
        "evidence_required",
        "claim_boundary",
    }
    errors.extend(_unsupported_key_errors(value, allowed, "hermes_coding_harness verification_matrix"))
    if value.get("schema_version") != "hermes_verification_matrix_projection/v1":
        errors.append("hermes_coding_harness verification_matrix schema_version is invalid")
    if value.get("status") not in {"pending", "observed", "blocked", "failed"}:
        errors.append("hermes_coding_harness verification_matrix status is invalid")
    for key in ("required_checks", "optional_checks", "missing_evidence"):
        if not isinstance(value.get(key), list):
            errors.append(f"hermes_coding_harness verification_matrix.{key} must be a list")
    if "observed verification evidence" not in str(value.get("claim_boundary", "")):
        errors.append("hermes_coding_harness verification_matrix claim_boundary must mention observed verification evidence")
    return errors


def _validate_stage_payloads(values: list[Any]) -> list[str]:
    errors: list[str] = []
    allowed = {
        "id",
        "owner_role",
        "purpose",
        "state",
        "required_inputs",
        "prepared_outputs",
        "observed_evidence_required",
        "allowed_next_actions",
        "not_evidence",
    }
    list_keys = {"required_inputs", "prepared_outputs", "observed_evidence_required", "allowed_next_actions", "not_evidence"}
    for index, stage in enumerate(values):
        label = f"hermes_coding_harness workflow_graph[{index}]"
        if not isinstance(stage, dict):
            errors.append(f"{label} must be an object")
            continue
        errors.extend(_unsupported_key_errors(stage, allowed, label))
        for key in allowed - list_keys:
            if not isinstance(stage.get(key), str):
                errors.append(f"{label}.{key} must be a string")
        if stage.get("state") not in {"prepared", "pending", "observed", "blocked", "failed"}:
            errors.append(f"{label}.state is invalid")
        for key in list_keys:
            if not isinstance(stage.get(key), list):
                errors.append(f"{label}.{key} must be a list")
    return errors


def _validate_lane_payloads(values: list[Any]) -> list[str]:
    errors: list[str] = []
    allowed = {
        "id",
        "owner_role",
        "purpose",
        "owner",
        "worker_ref",
        "worker_ref_required",
        "worktree_ref",
        "state",
        "observed_evidence_required",
        "evidence_gap",
        "claim_boundary",
    }
    string_keys = {"id", "owner_role", "purpose", "owner", "worker_ref", "worktree_ref", "state", "claim_boundary"}
    for index, lane in enumerate(values):
        label = f"hermes_coding_harness lanes[{index}]"
        if not isinstance(lane, dict):
            errors.append(f"{label} must be an object")
            continue
        errors.extend(_unsupported_key_errors(lane, allowed, label))
        for key in string_keys:
            if not isinstance(lane.get(key), str):
                errors.append(f"{label}.{key} must be a string")
        if lane.get("state") not in {"prepared", "pending", "observed", "blocked", "failed"}:
            errors.append(f"{label}.state is invalid")
        if not isinstance(lane.get("worker_ref_required"), bool):
            errors.append(f"{label}.worker_ref_required must be a boolean")
        if not isinstance(lane.get("evidence_gap"), bool):
            errors.append(f"{label}.evidence_gap must be a boolean")
        if not isinstance(lane.get("observed_evidence_required"), list):
            errors.append(f"{label}.observed_evidence_required must be a list")
        if "runtime_observation/v1" not in str(lane.get("claim_boundary", "")):
            errors.append(f"{label}.claim_boundary must mention runtime_observation/v1")
    return errors


def _validate_docs_sync(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return errors
    allowed = {"schema_version", "status", "triggered_when", "missing_evidence", "claim_boundary"}
    errors.extend(_unsupported_key_errors(value, allowed, "hermes_coding_harness docs_sync"))
    if value.get("schema_version") != "hermes_docs_sync_projection/v1":
        errors.append("hermes_coding_harness docs_sync schema_version is invalid")
    if value.get("status") not in {"prepared_not_observed", "not_required_until_public_behavior_changes", "observed"}:
        errors.append("hermes_coding_harness docs_sync status is invalid")
    for key in ("triggered_when", "missing_evidence"):
        if not isinstance(value.get(key), list):
            errors.append(f"hermes_coding_harness docs_sync.{key} must be a list")
    if "does not prove" not in str(value.get("claim_boundary", "")):
        errors.append("hermes_coding_harness docs_sync claim_boundary must avoid observed-file claims")
    return errors


def _validate_pr_preparation(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return errors
    allowed = {"schema_version", "status", "prepared_items", "missing_evidence", "not_observed", "claim_boundary"}
    errors.extend(_unsupported_key_errors(value, allowed, "hermes_coding_harness pr_preparation"))
    if value.get("schema_version") != "hermes_pr_preparation_projection/v1":
        errors.append("hermes_coding_harness pr_preparation schema_version is invalid")
    if value.get("status") not in {"pending", "observed", "blocked", "failed"}:
        errors.append("hermes_coding_harness pr_preparation status is invalid")
    for key in ("prepared_items", "missing_evidence", "not_observed"):
        if not isinstance(value.get(key), list):
            errors.append(f"hermes_coding_harness pr_preparation.{key} must be a list")
    missing_evidence = value.get("missing_evidence") if isinstance(value.get("missing_evidence"), list) else []
    not_observed = value.get("not_observed") if isinstance(value.get("not_observed"), list) else []
    if "GitHub PR creation" in not_observed and "github_pr_created" not in missing_evidence:
        errors.append("hermes_coding_harness pr_preparation missing_evidence must keep github_pr_created while PR creation is not observed")
    if "not GitHub PR creation" not in str(value.get("claim_boundary", "")):
        errors.append("hermes_coding_harness pr_preparation claim_boundary must avoid PR creation claims")
    return errors


def _unsupported_key_errors(value: Mapping[str, Any], allowed: set[str], label: str) -> list[str]:
    extra = sorted(set(value) - allowed)
    return [f"{label} has unsupported keys: {extra}"] if extra else []


def _stage_payload(
    stage_id: str,
    owner_role: str,
    purpose: str,
    event_type: str,
    *,
    observed_events: set[str],
    blocked_events: set[str],
    failed_events: set[str],
    prepared: bool,
) -> dict[str, Any]:
    return {
        "id": stage_id,
        "owner_role": owner_role,
        "purpose": purpose,
        "state": _state_for_event(event_type, observed_events=observed_events, blocked_events=blocked_events, failed_events=failed_events, prepared=prepared),
        "required_inputs": _stage_inputs(stage_id),
        "prepared_outputs": _stage_outputs(stage_id),
        "observed_evidence_required": [event_type] if event_type else [],
        "allowed_next_actions": _stage_actions(stage_id),
        "not_evidence": _not_evidence(stage_id),
    }


def _lane_payload(
    lane_id: str,
    owner_role: str,
    purpose: str,
    event_type: str,
    *,
    start_mode: str,
    observed_events: set[str],
    blocked_events: set[str],
    failed_events: set[str],
    latest_by_event: Mapping[str, Any],
) -> dict[str, Any]:
    latest = _mapping(latest_by_event.get(event_type))
    worker_ref = str(latest.get("worker_ref", ""))
    requires_worker_ref = start_mode in {"team", "swarm"} and event_type in {"worker_dispatch", "worker_result"}
    return {
        "id": lane_id,
        "owner_role": owner_role,
        "purpose": purpose,
        "owner": "Hermes Agent",
        "worker_ref": worker_ref,
        "worker_ref_required": requires_worker_ref,
        "worktree_ref": str(latest.get("worktree_ref", "")),
        "state": _state_for_event(event_type, observed_events=observed_events, blocked_events=blocked_events, failed_events=failed_events, prepared=True),
        "observed_evidence_required": [event_type] if event_type else [],
        "evidence_gap": bool(requires_worker_ref and event_type in observed_events and not worker_ref),
        "claim_boundary": "Lane status is projected from runtime_observation/v1; missing worker refs remain evidence gaps.",
    }


def _gate_payloads(*, observed_events: set[str], blocked_events: set[str], failed_events: set[str]) -> list[dict[str, str]]:
    return [
        {
            "id": event,
            "state": _state_for_event(event, observed_events=observed_events, blocked_events=blocked_events, failed_events=failed_events, prepared=True),
            "observed_evidence_required": event,
        }
        for event in HERMES_CODING_TEAM_STATUS_LADDER
    ]


def _verification_matrix(
    handoff: Mapping[str, Any],
    *,
    observed_events: set[str],
    blocked_events: set[str],
    failed_events: set[str],
) -> dict[str, Any]:
    expected = [str(item) for item in handoff.get("verification", []) if str(item)]
    verification_state = _state_for_event(
        "verification",
        observed_events=observed_events,
        blocked_events=blocked_events,
        failed_events=failed_events,
        prepared=True,
    )
    return {
        "schema_version": "hermes_verification_matrix_projection/v1",
        "status": verification_state,
        "required_checks": expected,
        "optional_checks": ["docs generation check when public behavior changed", "render/smoke check when UI or generated artifacts changed"],
        "missing_evidence": [] if "verification" in observed_events else ["runtime_observation:verification"],
        "failure_action": "return_to_build_or_plan",
        "evidence_required": "Record runtime_observation/v1 event_type=verification after checks really run.",
        "claim_boundary": "Verification matrix is prepared guidance until observed verification evidence exists.",
    }


def _docs_sync(handoff: Mapping[str, Any], *, observed_events: set[str], latest_by_event: Mapping[str, Any]) -> dict[str, Any]:
    public_change_hint = any(
        "doc" in str(item).casefold() or "readme" in str(item).casefold() or "site" in str(item).casefold()
        for item in [*list(handoff.get("acceptance_criteria", []) or []), *list(handoff.get("verification", []) or [])]
    )
    docs_evidence_observed = _evidence_ref_observed(
        latest_by_event,
        observed_events=observed_events,
        prefixes=("docs_sync:", "docs_sync_evidence:"),
    )
    return {
        "schema_version": "hermes_docs_sync_projection/v1",
        "status": "observed" if public_change_hint and docs_evidence_observed else "prepared_not_observed" if public_change_hint else "not_required_until_public_behavior_changes",
        "triggered_when": [
            "README, docs, site, generated skills, workflow examples, CLI copy, or public claims change",
            "verification/docs generation says generated content is stale",
        ],
        "missing_evidence": ["docs_sync_evidence_ref"] if public_change_hint and not docs_evidence_observed else [],
        "claim_boundary": "Docs sync projection does not prove files were edited or generated docs were refreshed.",
    }


def _pr_preparation(
    *,
    observed_events: set[str],
    blocked_events: set[str],
    failed_events: set[str],
    latest_by_event: Mapping[str, Any],
) -> dict[str, Any]:
    state = _state_for_event(
        "merge_readiness",
        observed_events=observed_events,
        blocked_events=blocked_events,
        failed_events=failed_events,
        prepared=True,
    )
    github_pr_created = _evidence_ref_observed(
        latest_by_event,
        observed_events=observed_events,
        prefixes=("github_pr_created:", "github_pr:", "pull_request:"),
    )
    return {
        "schema_version": "hermes_pr_preparation_projection/v1",
        "status": state,
        "prepared_items": [
            "branch summary",
            "commit plan with DCO/trailers",
            "PR body with why/how/what, tests, risks, and evidence gaps",
            "review checklist",
        ],
        "missing_evidence": [
            *(["runtime_observation:merge_readiness"] if "merge_readiness" not in observed_events else []),
            *(["github_pr_created"] if not github_pr_created else []),
        ],
        "not_observed": [
            *(["GitHub PR creation"] if not github_pr_created else []),
            *(["review passed"] if "review" not in observed_events else []),
            *(["CI passed"] if "ci" not in observed_events else []),
            *(["merge readiness"] if "merge_readiness" not in observed_events else []),
            *(["merge"] if "merge" not in observed_events else []),
        ],
        "claim_boundary": "PR preparation is not GitHub PR creation, review, CI, merge-readiness, or merge evidence.",
    }


def _runtime_requirements() -> list[dict[str, str]]:
    return [
        {
            "event_type": event,
            "record_schema": "runtime_observation/v1",
            "record_with": "omh runtime observe --session <wrapper-session-id> --runtime-profile hermes --event "
            f"{event} --status <observed|blocked|failed|not_observed> --summary <observed metadata>",
        }
        for event in HERMES_CODING_TEAM_STATUS_LADDER
    ]


def _wrapper_actions() -> list[str]:
    return [
        "show_runtime_handoff",
        *[action for action in HERMES_CODING_TEAM_WRAPPER_ACTIONS if action != "show_status"],
        "record_verification_evidence",
        "record_review_evidence",
        "record_ci_evidence",
        "record_merge_readiness",
        "show_status",
    ]


def _safe_status_lines(
    *,
    status: str,
    start_mode: str,
    workflow_graph: list[dict[str, Any]],
    verification_matrix: Mapping[str, Any],
    docs_sync: Mapping[str, Any],
    pr_preparation: Mapping[str, Any],
) -> list[str]:
    current = next((stage for stage in workflow_graph if stage.get("state") in {"pending", "blocked", "failed"}), workflow_graph[-1])
    lines = [
        f"Hermes coding harness is {status} in {start_mode} mode.",
        f"Current stage: {current.get('id')} ({current.get('owner_role')}).",
    ]
    if verification_matrix.get("missing_evidence"):
        lines.append("Verification evidence is still missing.")
    if docs_sync.get("missing_evidence"):
        lines.append("Docs sync evidence is still missing.")
    missing_pr_evidence = set(pr_preparation.get("missing_evidence", [])) if isinstance(pr_preparation.get("missing_evidence"), list) else set()
    if "runtime_observation:merge_readiness" in missing_pr_evidence:
        lines.append("PR merge-readiness remains prepared, not observed.")
    if "github_pr_created" in missing_pr_evidence:
        lines.append("GitHub PR creation is still not observed.")
    return lines


def _harness_status(
    *,
    observed_events: set[str],
    blocked_events: set[str],
    failed_events: set[str],
    unsatisfied_events: set[str],
    projection_missing_evidence: set[str],
) -> str:
    if failed_events:
        return "failed"
    if blocked_events:
        return "blocked"
    if "merge" in observed_events and not unsatisfied_events and not projection_missing_evidence:
        return "completed"
    if observed_events:
        return "in_progress"
    return "prepared_not_observed"


def _projection_missing_evidence(
    *,
    verification_matrix: Mapping[str, Any],
    docs_sync: Mapping[str, Any],
    pr_preparation: Mapping[str, Any],
) -> set[str]:
    missing: set[str] = set()
    for section in (verification_matrix, docs_sync, pr_preparation):
        values = section.get("missing_evidence") if isinstance(section, Mapping) else []
        if isinstance(values, list):
            missing.update(str(item) for item in values if str(item))
    return missing


def _evidence_ref_observed(
    latest_by_event: Mapping[str, Any],
    *,
    observed_events: set[str],
    prefixes: tuple[str, ...],
) -> bool:
    for event_type, value in latest_by_event.items():
        if str(event_type) not in observed_events:
            continue
        record = _mapping(value)
        if record.get("status") not in {None, "", "observed"}:
            continue
        refs = record.get("evidence_refs", [])
        if not isinstance(refs, list):
            continue
        for ref in refs:
            normalized = str(ref)
            if any(normalized.startswith(prefix) for prefix in prefixes):
                return True
    return False


def _unsatisfied_events(observation: Mapping[str, Any], *, observed_events: set[str]) -> set[str]:
    provided = _string_set(observation.get("unsatisfied_events"))
    if provided:
        return provided
    explicit_not_observed = _string_set(observation.get("not_observed_events"))
    explicit_missing = _string_set(observation.get("missing_events"))
    if explicit_not_observed or explicit_missing:
        return explicit_not_observed | explicit_missing
    if not observed_events:
        return set(HERMES_CODING_TEAM_STATUS_LADDER)
    return {event for event in HERMES_CODING_TEAM_STATUS_LADDER if event not in observed_events}


def _resolve_start_mode(
    start_mode: str,
    *,
    handoff: Mapping[str, Any],
    observed_events: set[str],
    latest_by_event: Mapping[str, Any],
) -> str:
    if start_mode in {"solo", "durable_goal", "team", "swarm"}:
        return start_mode
    if {"worker_dispatch", "worker_result"} & observed_events:
        worker_ref = str(_mapping(latest_by_event.get("worker_dispatch")).get("worker_ref", ""))
        if worker_ref and "swarm" in worker_ref.casefold():
            return "swarm"
        return "team"
    return "solo"


def _state_for_event(
    event_type: str,
    *,
    observed_events: set[str],
    blocked_events: set[str],
    failed_events: set[str],
    prepared: bool,
) -> str:
    if not event_type:
        return "prepared" if prepared else "pending"
    if event_type in failed_events:
        return "failed"
    if event_type in blocked_events:
        return "blocked"
    if event_type in observed_events:
        return "observed"
    return "pending"


def _stage_inputs(stage_id: str) -> list[str]:
    return {
        "intake": ["user request", "selected coding owner"],
        "scope": ["accepted intake", "repo/task constraints"],
        "plan": ["scope", "risk level", "acceptance criteria"],
        "workspace": ["plan", "isolation plan"],
        "build": ["plan", "workspace decision", "Hermes coding skill"],
        "verify": ["implementation result evidence", "verification command list"],
        "review": ["implementation and verification evidence"],
        "docs_sync": ["public behavior or claim changes"],
        "pr_prep": ["implementation, verification, review, docs evidence"],
        "handover": ["latest observed status"],
    }.get(stage_id, [])


def _stage_outputs(stage_id: str) -> list[str]:
    return {
        "intake": ["Hermes coding path selected"],
        "scope": ["bounded task scope"],
        "plan": ["reviewed implementation plan"],
        "workspace": ["workspace isolation guidance"],
        "build": ["implementation result report"],
        "verify": ["verification evidence refs"],
        "review": ["review evidence refs"],
        "docs_sync": ["docs sync status"],
        "pr_prep": ["PR package and evidence gaps"],
        "handover": ["user-facing status and next action"],
    }.get(stage_id, [])


def _stage_actions(stage_id: str) -> list[str]:
    return {
        "intake": ["show_coding_team_path", "show_status"],
        "scope": ["show_coding_team_path", "show_status"],
        "plan": ["show_runtime_handoff", "show_status"],
        "workspace": ["prepare_worktree", "record_runtime_observation", "show_status"],
        "build": ["start_hermes_coding", "start_team", "start_swarm", "record_runtime_observation", "show_status"],
        "verify": ["record_verification_evidence", "record_runtime_observation", "show_status"],
        "review": ["record_review_evidence", "record_runtime_observation", "show_status"],
        "docs_sync": ["show_status"],
        "pr_prep": ["record_ci_evidence", "record_merge_readiness", "show_status"],
        "handover": ["show_status"],
    }.get(stage_id, ["show_status"])


def _not_evidence(stage_id: str) -> list[str]:
    common = ["unobserved execution", "unobserved verification", "unobserved review", "unobserved CI", "unobserved merge"]
    if stage_id == "pr_prep":
        return ["GitHub PR creation", "review passed", "CI passed", "merge readiness", "merge"]
    if stage_id == "workspace":
        return ["worktree creation", *common]
    return common


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if str(item)}
