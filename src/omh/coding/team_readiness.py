from __future__ import annotations

from pathlib import Path
from typing import Any

from ..executors import (
    CODING_RUNTIME_HANDOFF_TARGETS,
    HERMES_CODING_TEAM_START_MODE_IDS,
    HERMES_CODING_TEAM_STATUS_LADDER,
    HERMES_CODING_TEAM_WRAPPER_ACTIONS,
    hermes_coding_team_path_contract,
    runtime_profile_contract,
    runtime_templates_for_profile,
)
from ..local_store import read_json_object_result
from ..paths import OmhPaths
from ..runtime.artifacts import (
    read_runtime_observations_result,
    runtime_observations_for_target,
    summarize_runtime_observation_status,
)
from ..runtime.records import RUNTIME_OBSERVATION_SCHEMA_VERSION
from ..skill_pack import builtin_skill_templates


TEAM_WORKER_READINESS_SCHEMA_VERSION = "omh_team_worker_readiness/v1"
TEAM_WORKER_SKILLS = ("team", "ultrawork", "ultragoal", "code-review")
TEAM_WORKER_EVENTS = ("runtime_start", "worktree_creation", "worker_dispatch", "worker_result")
DEFAULT_RUNTIME_TARGET_SCAN_LIMIT = 50


def build_team_worker_readiness(paths: OmhPaths, *, target_limit: int | None = DEFAULT_RUNTIME_TARGET_SCAN_LIMIT) -> dict[str, Any]:
    skill_surfaces = _skill_surfaces(paths)
    missing_required_skills = [
        skill["name"]
        for skill in skill_surfaces
        if skill["name"] in {"team", "ultrawork"} and not skill["available_in_package"]
    ]
    runtime_profiles = [runtime_profile_contract(profile) for profile in CODING_RUNTIME_HANDOFF_TARGETS]
    runtime_observation = _runtime_observation_readiness(paths, target_limit=target_limit)
    installed_skill_count = sum(1 for skill in skill_surfaces if skill["installed_for_hermes"])
    hermes_visible = all(
        skill["installed_for_hermes"] for skill in skill_surfaces if skill["name"] in {"team", "ultrawork"}
    )
    contract_status = "available" if not missing_required_skills else "missing"
    if contract_status == "available" and not hermes_visible:
        hermes_visibility_status = "not_installed"
    else:
        hermes_visibility_status = "available" if hermes_visible else "missing"
    presentation_status = "available" if contract_status == "available" and hermes_visible else "not_installed"

    return {
        "schema_version": TEAM_WORKER_READINESS_SCHEMA_VERSION,
        "status": contract_status,
        "contract_status": contract_status,
        "presentation_status": presentation_status,
        "hermes_visibility_status": hermes_visibility_status,
        "skill_surfaces": skill_surfaces,
        "installed_skill_count": installed_skill_count,
        "runtime_profiles": runtime_profiles,
        "runtime_templates": {
            profile: runtime_templates_for_profile(profile) for profile in CODING_RUNTIME_HANDOFF_TARGETS
        },
        "hermes_coding_team_path": hermes_coding_team_path_contract("hermes"),
        "worker_protocol": {
            "start_modes": list(HERMES_CODING_TEAM_START_MODE_IDS),
            "required_worker_ack": True,
            "required_lane_fields": [
                "worker_ref",
                "owner",
                "scope",
                "file_or_worktree_ownership",
                "result_summary",
                "verification_refs",
            ],
            "wrapper_actions": list(HERMES_CODING_TEAM_WRAPPER_ACTIONS),
            "claim_boundary": (
                "Worker protocol readiness is prompt and wrapper guidance until matching runtime_observation/v1 "
                "records exist for worker_dispatch and worker_result."
            ),
        },
        "runtime_observation_contract": {
            "record_schema": RUNTIME_OBSERVATION_SCHEMA_VERSION,
            "status_ladder": list(HERMES_CODING_TEAM_STATUS_LADDER),
            "team_worker_events": list(TEAM_WORKER_EVENTS),
            "default_target_scan_limit": target_limit,
            "record_command_template": (
                "omh runtime observe --session <session-id> --runtime-profile <hermes|omx-runtime|omo-runtime|omc-runtime> "
                "--event <runtime_start|worktree_creation|worker_dispatch|worker_result> --summary <observed evidence>"
            ),
            "worker_event_requirement": "Observed worker_dispatch and worker_result records require --worker-ref.",
        },
        "observed_runtime": runtime_observation,
        "next_actions": _next_actions(hermes_visible=hermes_visible, runtime_observation=runtime_observation),
        "claim_boundary": (
            "OMH can prepare and verify the team/swarm worker contract, wrapper actions, and observation ledger. "
            "It does not secretly launch tmux panes, spawn workers, edit code, review PRs, run CI, or merge; those "
            "become evidence only when the selected host or wrapper records matching runtime_observation/v1 events."
        ),
    }


def _skill_surfaces(paths: OmhPaths) -> list[dict[str, Any]]:
    template_names = {template.name for template in builtin_skill_templates()}
    return [
        {
            "name": name,
            "available_in_package": name in template_names,
            "installed_for_hermes": (paths.skills_dir / name / "SKILL.md").is_file(),
            "managed_skill_path": str(paths.skills_dir / name / "SKILL.md"),
            "purpose": _skill_purpose(name),
        }
        for name in TEAM_WORKER_SKILLS
    ]


def _skill_purpose(name: str) -> str:
    purposes = {
        "team": "Coordinate explicit multi-lane Hermes or runtime work with worker ownership and leader integration.",
        "ultrawork": "Run a prepared high-throughput work batch when lanes can be separated and verified.",
        "ultragoal": "Keep one durable implementation goal moving through plan, implementation, review, and verification.",
        "code-review": "Review implementation evidence before status, CI, or merge claims are treated as complete.",
    }
    return purposes.get(name, "OMH workflow surface.")


def _runtime_observation_readiness(paths: OmhPaths, *, target_limit: int | None) -> dict[str, Any]:
    observed_records: list[dict[str, Any]] = []
    errors: list[str] = []
    observed_targets = 0
    all_targets = _runtime_target_files(paths)
    targets = all_targets if target_limit is None else all_targets[: max(0, target_limit)]
    for target_type, target_json in targets:
        target, target_error = read_json_object_result(target_json)
        if target_error:
            errors.append(f"{target_json}: {target_error}")
        if not target:
            continue
        target_id_key = "session_id" if target_type == "wrapper_session" else "run_id"
        target_id = str(target.get(target_id_key) or target_json.parent.name)
        observations, observation_errors = read_runtime_observations_result(target_json.parent)
        errors.extend(observation_errors)
        target_records = runtime_observations_for_target(observations, target_type, target_id)
        if target_records:
            observed_targets += 1
            observed_records.extend(target_records)

    status = summarize_runtime_observation_status(observed_records)
    observed_worker_events = [
        record
        for record in observed_records
        if record.get("event_type") in {"worker_dispatch", "worker_result"} and record.get("status") == "observed"
    ]
    latest_worker_events = _latest_worker_events(observed_worker_events)
    observed_state = _observed_runtime_state(status)
    return {
        "status": observed_state,
        "observed_target_count": observed_targets,
        "record_count": len(observed_records),
        "scanned_target_count": len(targets),
        "target_scan_limit": target_limit,
        "scan_truncated": len(all_targets) > len(targets),
        "worker_event_count": len(observed_worker_events),
        "observed_events": status["observed_events"],
        "blocked_events": status["blocked_events"],
        "failed_events": status["failed_events"],
        "next_action": status["next_action"] if observed_records else "prepare_runtime_handoff_or_record_runtime_start",
        "latest_worker_events": latest_worker_events,
        "errors": errors,
        "claim_boundary": (
            "Observed runtime readiness is computed from local runtime_observation/v1 ledgers only. "
            "No record means no observed team, swarm, worker dispatch, or worker result."
        ),
    }


def _runtime_target_files(paths: OmhPaths) -> list[tuple[str, Path]]:
    targets = [
        ("wrapper_session", path)
        for path in paths.runtime_wrapper_sessions_dir.glob("*/session.json")
    ] + [
        ("run", path)
        for path in paths.runtime_runs_dir.glob("*/run.json")
    ]
    targets.sort(key=lambda item: (_target_activity_mtime_ns(item[1]), str(item[1])), reverse=True)
    return targets


def _target_activity_mtime_ns(target_json: Path) -> int:
    return max(_mtime_ns(target_json), _mtime_ns(target_json.parent / "runtime_observations.jsonl"))


def _mtime_ns(path: Path) -> int:
    try:
        return int(path.stat().st_mtime_ns)
    except OSError:
        return 0


def _observed_runtime_state(status: dict[str, Any]) -> str:
    if status.get("failed_events"):
        return "failed"
    if status.get("blocked_events"):
        return "blocked"
    if status.get("observed_events"):
        return "observed"
    return "not_observed"


def _latest_worker_events(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        event_type = str(record.get("event_type", ""))
        current = latest.get(event_type)
        if current is None or _observation_sort_key(record) >= _observation_sort_key(current):
            latest[event_type] = record
    return {event_type: _compact_observation(record) for event_type, record in latest.items()}


def _observation_sort_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record.get("updated_at", "")),
        str(record.get("target_type", "")),
        str(record.get("target_id", "")),
    )


def _compact_observation(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_type": str(record.get("target_type", "")),
        "target_id": str(record.get("target_id", "")),
        "runtime_profile": str(record.get("runtime_profile", "")),
        "event_type": str(record.get("event_type", "")),
        "status": str(record.get("status", "")),
        "worker_ref": str(record.get("worker_ref", "")),
        "worktree_ref": str(record.get("worktree_ref", "")),
        "summary": str(record.get("summary", "")),
        "updated_at": str(record.get("updated_at", "")),
    }


def _next_actions(*, hermes_visible: bool, runtime_observation: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    if not hermes_visible:
        actions.append("Run `omh setup` so Hermes can discover the team and ultrawork skills.")
    actions.extend(
        [
            "When the user chooses Hermes/team/swarm, prepare a runtime handoff rather than claiming execution.",
            "Use the wrapper actions `start_team` or `start_swarm` only after ownership, worktree, and verifier lanes are clear.",
            "Record `runtime_observation/v1` events as the host actually starts work, dispatches workers, receives results, verifies, reviews, and reaches CI or merge states.",
        ]
    )
    if runtime_observation.get("status") != "observed":
        actions.append("Show status as prepared_not_observed until a host or wrapper records the first runtime event.")
    return actions
