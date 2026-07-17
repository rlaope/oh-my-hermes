"""Local, metadata-only guidance for OMH-led Hermes task orchestration."""

from __future__ import annotations

from collections.abc import Mapping

from ..local_store import read_json_object
from ..paths import OmhPaths
from ..runtime.records import validate_wrapper_session_record


ORCHESTRATION_GUIDANCE_SCHEMA_VERSION = "omh_orchestration_guidance/v1"
_AUTONOMY_PATTERN_THRESHOLD = 2
_ACCEPTED_SESSION_STATUSES = frozenset(
    {
        "plan_accepted",
        "executor_selected",
        "prompt_handoff_prepared",
        "runtime_handoff_prepared",
        "handoff_prepared",
    }
)


def build_omh_orchestration_guidance(
    route: Mapping[str, object],
    *,
    source_metadata: Mapping[str, str],
    paths: OmhPaths | None,
) -> dict[str, object]:
    """Recommend OMH-led problem solving without claiming work was executed."""
    selected_skill = _nonempty_text(route.get("selected_skill")) or "oh-my-hermes"
    selected_harness = _nonempty_text(route.get("selected_harness"))
    user_ref = _nonempty_text(source_metadata.get("user_ref"))
    accepted_count = _accepted_pattern_count(paths, user_ref, selected_skill)
    autonomous = accepted_count >= _AUTONOMY_PATTERN_THRESHOLD
    native_candidates = _string_list(route.get("native_skill_recommendations"))
    return {
        "schema_version": ORCHESTRATION_GUIDANCE_SCHEMA_VERSION,
        "mode": "autonomous_pattern" if autonomous else "guided_first_use",
        "selected_workflow": selected_skill,
        "selected_harness": selected_harness,
        "accepted_pattern_count": accepted_count,
        "next_action": "continue_omh_orchestration" if autonomous else "recommend_omh_orchestration",
        "confirmation": {
            "required": False,
            "policy": "optional_first_use" if not autonomous else "pattern_based_autonomy",
            "boundary": "Gates still apply to destructive, credentialed, external-write, deploy, and executor-dispatch actions.",
        },
        "problem_solving_contract": {
            "steps": [
                "frame_problem_and_success_criteria",
                "select_omh_workflow_and_harness",
                "use_native_hermes_capabilities_as_needed",
                "preserve_prepared_and_observed_evidence_boundary",
            ],
            "boundary": "Prepared guidance only; not research, execution, review, CI, or merge evidence.",
        },
        "native_skill_governance": {
            "role": "subordinate_capability",
            "candidate_skills": native_candidates,
            "can_override_omh": False,
            "selection_policy": "OMH selects the workflow; Hermes-native skills are optional capabilities within that workflow.",
        },
    }


def _accepted_pattern_count(paths: OmhPaths | None, user_ref: str, selected_skill: str) -> int:
    if paths is None or not user_ref or not paths.runtime_wrapper_sessions_dir.exists():
        return 0
    count = 0
    for session_path in paths.runtime_wrapper_sessions_dir.glob("*/session.json"):
        session = read_json_object(session_path)
        if (
            not session
            or validate_wrapper_session_record(session)
            or session.get("status") not in _ACCEPTED_SESSION_STATUSES
            or session.get("decision") != "plan_accepted"
        ):
            continue
        metadata = session.get("source_metadata")
        route = session.get("route")
        if not isinstance(metadata, Mapping) or not isinstance(route, Mapping):
            continue
        if metadata.get("user_ref") == user_ref and route.get("selected_skill") == selected_skill:
            count += 1
    return count


def _nonempty_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]
