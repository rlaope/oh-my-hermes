from __future__ import annotations

from ..executors import HERMES_CODING_TEAM_STATUS_LADDER


def hermes_coding_team_body() -> str:
    return (
        "The Hermes coding path is prepared with solo/team/swarm choices, worker protocol, worktree guidance, "
        "and a full runtime observation ladder. This is not Hermes coding, worker, worktree, review, CI, or merge evidence."
    )


def hermes_coding_team_claim_boundary() -> str:
    evidence_names = ", ".join(_event_label(event) for event in HERMES_CODING_TEAM_STATUS_LADDER)
    return (
        "Hermes coding path is prepared only; "
        f"{evidence_names} require matching runtime_observation/v1 evidence before the wrapper can claim them."
    )


def hermes_coding_team_extra_action_specs(*, selected_executor_profile: str | None = None) -> list[dict[str, object]]:
    payload = {"selected_executor_profile": selected_executor_profile} if selected_executor_profile else {}
    return [
        {
            "id": "show_coding_team_path",
            "label": "Show team path",
            "style": "secondary",
            "enabled": True,
            "payload": dict(payload),
        },
        {
            "id": "record_runtime_observation",
            "label": "Record observation",
            "style": "secondary",
            "enabled": False,
            "payload": dict(payload),
        },
    ]


def _event_label(event: str) -> str:
    return event.replace("_", " ")
