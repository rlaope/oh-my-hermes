from __future__ import annotations

from ..playbooks import inspect_playbook, list_playbooks
from ..plugin_bundle.omh.awareness import awareness_primer_payload
from .schema import PLAYBOOK_CAPABILITY_SCHEMA_VERSION, PREPARED_NOT_OBSERVED


PLAYBOOK_WORKFLOW_CONTEXT_RULE = (
    "Use OMH playbooks as situation-level workflow maps: choose the nearest playbook for the user's request, then route "
    "to the named skills, roles, harnesses, or wrapper actions without claiming hidden execution."
)


def playbook_capabilities() -> list[dict[str, object]]:
    awareness = awareness_primer_payload()
    chat_rule = str(awareness.get("chat_rule") or "")
    fallback_rule = str(awareness.get("fallback_rule") or "")
    evidence_boundary = str(awareness.get("evidence_boundary") or "")
    playbooks = list_playbooks().get("playbooks", [])
    if not isinstance(playbooks, list):
        return []
    return [
        _playbook_capability(
            playbook,
            details=_playbook_details(str(playbook.get("id") or "")),
            chat_rule=chat_rule,
            fallback_rule=fallback_rule,
            evidence_boundary=evidence_boundary,
        )
        for playbook in playbooks
        if isinstance(playbook, dict)
    ]


def _playbook_capability(
    playbook: dict[str, object],
    *,
    details: dict[str, object],
    chat_rule: str,
    fallback_rule: str,
    evidence_boundary: str,
) -> dict[str, object]:
    playbook_id = str(playbook.get("id") or "")
    stages = _stage_list(details.get("stages"))
    return {
        "schema_version": PLAYBOOK_CAPABILITY_SCHEMA_VERSION,
        "id": playbook_id,
        "display_name": str(playbook.get("title") or playbook_id),
        "runtime_claim": "playbook_guidance_not_execution",
        "summary": str(playbook.get("summary") or ""),
        "use_when": str(playbook.get("use_when") or ""),
        "intent_tags": _string_list(playbook.get("intent_tags")),
        "pipeline": _string_list(playbook.get("pipeline")),
        "retained_by_hermes": _string_list(playbook.get("retained_by_hermes")),
        "delegated_to_executor": _string_list(playbook.get("delegated_to_executor")),
        "stage_count": int(playbook.get("stage_count") or 0),
        "primary_owner_role": _primary_owner(stages),
        "stage_owners": _stage_owners(stages),
        "available_wrapper_actions": _available_wrapper_actions(stages),
        "first_stage": _first_stage(stages),
        "not_evidence_until_observed": _string_list(playbook.get("not_evidence_until_observed")),
        "workflow_context_rule": PLAYBOOK_WORKFLOW_CONTEXT_RULE,
        "chat_rule": chat_rule,
        "fallback_rule": fallback_rule,
        "evidence_boundary": evidence_boundary,
        "prepared_is_not": PREPARED_NOT_OBSERVED,
        "source_refs": ["src/catalogs/playbooks.py"],
    }


def _playbook_details(playbook_id: str) -> dict[str, object]:
    if not playbook_id:
        return {}
    try:
        payload = inspect_playbook(playbook_id)
    except ValueError:
        return {}
    playbook = payload.get("playbook", {})
    return playbook if isinstance(playbook, dict) else {}


def _stage_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [stage for stage in value if isinstance(stage, dict)]


def _primary_owner(stages: list[dict[str, object]]) -> str:
    for stage in stages:
        owner = str(stage.get("owner") or "")
        if owner and owner not in {"hermes", "oh-my-hermes", "wrapper"}:
            return owner
    if stages:
        return str(stages[0].get("owner") or "")
    return ""


def _stage_owners(stages: list[dict[str, object]]) -> list[str]:
    owners = []
    seen = set()
    for stage in stages:
        owner = str(stage.get("owner") or "")
        if owner and owner not in seen:
            seen.add(owner)
            owners.append(owner)
    return owners


def _available_wrapper_actions(stages: list[dict[str, object]]) -> list[str]:
    actions = []
    seen = set()
    for stage in stages:
        for action in _string_list(stage.get("wrapper_actions")):
            if action not in seen:
                seen.add(action)
                actions.append(action)
    return actions


def _first_stage(stages: list[dict[str, object]]) -> dict[str, object]:
    if not stages:
        return {}
    stage = stages[0]
    return {
        "id": str(stage.get("id") or ""),
        "title": str(stage.get("title") or ""),
        "owner": str(stage.get("owner") or ""),
        "contract": str(stage.get("contract") or ""),
        "wrapper_actions": _string_list(stage.get("wrapper_actions")),
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]
