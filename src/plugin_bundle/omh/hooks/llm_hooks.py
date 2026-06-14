from __future__ import annotations

from ..omh_roles import extract_role_marker, role_context_payload
from ..runtime_reader import read_omh_hud, read_omh_status


def _token_metadata_from_kwargs(kwargs: dict) -> dict[str, object]:
    keys = (
        "tokens_remaining",
        "token_budget",
        "input_tokens",
        "output_tokens",
        "context_remaining_percent",
    )
    return {key: kwargs[key] for key in keys if kwargs.get(key) is not None}


def pre_llm_call(**kwargs) -> dict[str, str] | None:
    """Inject bounded OMH role/status context without storing prompts."""
    context_parts: list[str] = []
    if bool(kwargs.get("is_first_turn", False)):
        marker = extract_role_marker(str(kwargs.get("user_message", "") or ""))
        if marker:
            role_payload = role_context_payload(marker)
            if role_payload["status"] == "available":
                context_parts.append(
                    "\n".join(
                        [
                            f"[OMH Role: {role_payload['role']}]",
                            str(role_payload["context"]),
                            str(role_payload["claim_boundary"]),
                        ]
                    )
                )
            else:
                context_parts.append(
                    "[OMH Role Warning] "
                    f"Unknown role '{marker}'. Available roles: {', '.join(role_payload['available_roles']) or '(none)'}."
                )

    try:
        omh_home = str(kwargs.get("omh_home", "") or "") or None
        hermes_home = str(kwargs.get("hermes_home", "") or "") or None
        status = read_omh_status(omh_home=omh_home, limit=3)
        hud = read_omh_hud(
            omh_home=omh_home,
            hermes_home=hermes_home,
            preset="focused",
            limit=3,
            token_metadata=_token_metadata_from_kwargs(kwargs),
        )
    except Exception:
        status = {}
        hud = {}

    if not context_parts and not status.get("runtime_state_present") and not status.get("runs"):
        return None

    if status.get("runtime_state_present") or status.get("runs"):
        lines = [
            str(hud.get("display", {}).get("line", "[omh] status unavailable")),
            "[OMH] Native bridge status context.",
            "Evidence boundary: prepared handoffs are not execution, review, CI, merge-readiness, or merge evidence.",
        ]
        latest_run_id = status.get("latest_run_id")
        if latest_run_id:
            lines.append(f"Latest runtime run: {latest_run_id}.")
        for run in status.get("runs", [])[:3]:
            run_id = run.get("run_id", "unknown")
            workflow = run.get("workflow", "unknown")
            phase = run.get("phase", "unknown")
            observation = run.get("observation_status", "unknown")
            execution = run.get("execution_observed", False)
            review = run.get("review_observed", False)
            ci = run.get("ci_observed", False)
            merge = run.get("merge_observed", False)
            lines.append(
                f"- {run_id}: workflow={workflow}, phase={phase}, observation={observation}, "
                f"execution_observed={execution}, review_observed={review}, ci_observed={ci}, merge_observed={merge}."
            )
        lines.append("Use omh_hud for the compact status line, omh_role for role context, or omh_status for full metadata-only status.")
        context_parts.append("\n".join(lines))
    return {"context": "\n\n".join(context_parts)}
