from __future__ import annotations

import errno
from datetime import datetime, timezone
import hashlib

from ..awareness import (
    awareness_context_match_degradation,
    awareness_context_matches_message,
    awareness_primer_context,
    awareness_route_hint,
    awareness_route_hint_context_from_payload,
)
from ..context_brief import build_context_brief
from ..degradation import (
    COMPONENT_LOCALIZED_ROUTING_TEXT,
    COMPONENT_RUNTIME_STATUS_READ,
    degradation_payload,
    safe_error_type,
)
from ..awareness_delivery import claim_route_guidance_delivery, record_awareness_delivery
from ..host_context import record_active_main_agent_model
from ..host_observation import observe_plugin_hook_call
from ..omh_roles import extract_role_marker, role_context_payload
from ..runtime_reader import read_omh_activity, read_omh_hud, read_omh_status
from ..status_board_reader import (
    last_running_work_board_fingerprint,
    read_running_work_board,
    record_running_work_board_emission,
    render_running_work_block_text,
    running_work_board_fingerprint,
)


def _token_metadata_from_kwargs(kwargs: dict) -> dict[str, object]:
    keys = (
        "tokens_remaining",
        "token_budget",
        "input_tokens",
        "output_tokens",
        "context_remaining_percent",
    )
    return {key: kwargs[key] for key in keys if kwargs.get(key) is not None}


def _record_delivery(
    *,
    delivered: bool,
    route_hint: bool,
    context_chars: int,
    omh_home: str | None,
    session_id: str = "",
    route_fingerprint: str = "",
) -> None:
    """Note that this hook ran. Never let bookkeeping break the hook itself."""
    try:
        record_awareness_delivery(
            delivered=delivered,
            route_hint=route_hint,
            context_chars=context_chars,
            observed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            omh_home=omh_home or "",
            session_id=session_id,
            route_fingerprint=route_fingerprint,
        )
    except (OSError, ValueError, TypeError):
        return


def pre_llm_call(**kwargs) -> dict[str, object] | None:
    """Inject bounded OMH role/status context without storing prompts."""
    record_active_main_agent_model(kwargs.get("model"))
    observe_plugin_hook_call("pre_llm_call", kwargs)
    context_parts: list[str] = []
    payload: dict[str, object] = {}
    user_message = str(kwargs.get("user_message", "") or "")
    is_first_turn = bool(kwargs.get("is_first_turn", False))
    include_awareness = kwargs.get("include_omh_awareness", True) is not False
    route_hint_context = ""
    route_hint_payload: dict[str, object] | None = None
    route_fingerprint = ""
    session_id = str(kwargs.get("session_id", "") or "")
    message_matches_awareness = False
    degraded: list[tuple[str, str]] = []
    if include_awareness:
        if is_first_turn:
            route_hint_payload = awareness_route_hint(user_message)
            route_hint_context = awareness_route_hint_context_from_payload(route_hint_payload)
            message_matches_awareness = bool(route_hint_context)
            route_degradation = route_hint_payload.get("degradation")
            if isinstance(route_degradation, dict):
                for row in route_degradation.get("components", []):
                    if isinstance(row, dict):
                        degraded.append((str(row.get("component", "")), str(row.get("error_type", ""))))
        else:
            # The matcher is called exactly when it is called today; the
            # `is_first_turn` short circuit is preserved because the cache-count
            # tests depend on it. The accessor reads the same cache entry the
            # matcher just populated, so it costs a hit and never a miss.
            message_matches_awareness = awareness_context_matches_message(user_message)
            match_error = awareness_context_match_degradation(user_message)
            if match_error:
                degraded.append((COMPONENT_LOCALIZED_ROUTING_TEXT, match_error))
        if message_matches_awareness and route_hint_payload is None:
            route_hint_payload = awareness_route_hint(user_message)
            route_hint_context = awareness_route_hint_context_from_payload(route_hint_payload)
        if route_hint_context:
            route_fingerprint = hashlib.sha256(route_hint_context.encode("utf-8")).hexdigest()
            if not claim_route_guidance_delivery(
                session_id=session_id,
                route_fingerprint=route_fingerprint,
                omh_home=str(kwargs.get("omh_home", "") or ""),
            ):
                route_hint_context = ""
                message_matches_awareness = False
    should_include_awareness = (
        include_awareness
        and (bool(route_hint_context) or message_matches_awareness)
    )
    if should_include_awareness:
        context_parts.append(awareness_primer_context())
        payload["omh_context_brief"] = build_context_brief(
            user_message,
            source=str(kwargs.get("source") or kwargs.get("host") or "pre_llm_call"),
            max_hints=2,
            include_prompt_context=False,
            route_hint_payload=route_hint_payload,
        )
        if route_hint_context:
            context_parts.append(route_hint_context)
        brief = payload.get("omh_context_brief")
        if isinstance(brief, dict):
            for row in brief.get("degradation", {}).get("components", []):
                if isinstance(row, dict):
                    degraded.append((str(row.get("component", "")), str(row.get("error_type", ""))))

    marker = extract_role_marker(user_message)
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

    omh_home: str | None = None
    try:
        omh_home = str(kwargs.get("omh_home", "") or "") or None
        hermes_home = str(kwargs.get("hermes_home", "") or "") or None
        try:
            activity = read_omh_activity(omh_home=omh_home, limit=3)
        except Exception as exc:
            # Keep the historical degradation component stable while moving
            # the hot path from full status to the active-only projection.
            error_type = "RuntimeError" if getattr(exc, "errno", None) == errno.ELOOP else type(exc).__name__
            degraded.append((COMPONENT_RUNTIME_STATUS_READ, safe_error_type(error_type)))
            activity = {"active_executors": []}
        if activity.get("active_executors"):
            status = read_omh_status(omh_home=omh_home, limit=3)
            hud = read_omh_hud(
                omh_home=omh_home,
                hermes_home=hermes_home,
                status=status,
                preset="focused",
                limit=3,
                token_metadata=_token_metadata_from_kwargs(kwargs),
            )
        else:
            status = activity
            hud = {}
    except Exception as exc:
        # The read raised. Without this the next branch reads the empty status
        # as `runtime_state_present` being false, so a failed status read looks
        # exactly like a host with nothing to report.
        status = {}
        hud = {}
        error_type = "RuntimeError" if getattr(exc, "errno", None) == errno.ELOOP else type(exc).__name__
        degraded.append((COMPONENT_RUNTIME_STATUS_READ, safe_error_type(error_type)))

    if include_awareness and is_first_turn and status.get("active_executors") and not should_include_awareness:
        context_parts.insert(0, awareness_primer_context())
        payload["omh_context_brief"] = build_context_brief(
            user_message,
            source=str(kwargs.get("source") or kwargs.get("host") or "pre_llm_call"),
            max_hints=2,
            include_prompt_context=False,
            route_hint_payload=route_hint_payload,
        )
        brief = payload.get("omh_context_brief")
        if isinstance(brief, dict):
            for row in brief.get("degradation", {}).get("components", []):
                if isinstance(row, dict):
                    degraded.append((str(row.get("component", "")), str(row.get("error_type", ""))))

    board = read_running_work_board(omh_home, limit=6)
    running_count = int(board.get("running_count", 0) or 0)
    # Two or more concurrently running coding units IS the "multi-session
    # orchestration is in flight" condition -- no fixed keyword phrasing can
    # cover every way a user's message might arrive while that is true, but a
    # live running-unit count cannot be phrased around. One running unit is
    # ordinary single-session work, not evidence of orchestration, so the
    # threshold is a count (>= 2), never a keyword match.
    board_fingerprint = running_work_board_fingerprint(board) if running_count >= 2 else ""
    show_running_work = running_count >= 2 and board_fingerprint != last_running_work_board_fingerprint(omh_home)

    degradation = degradation_payload(degraded)
    if (
        not context_parts
        and not degradation
        and not status.get("active_executors")
        and not show_running_work
    ):
        return None

    if status.get("active_executors"):
        lines = [
            str(hud.get("display", {}).get("line", "[omh] status unavailable")),
            "[OMH] Native bridge status context.",
            "Evidence boundary: prepared handoffs are not execution, review, CI, merge-readiness, or merge evidence.",
        ]
        latest_run_id = status.get("latest_run_id")
        if latest_run_id:
            lines.append(f"Latest runtime run: {latest_run_id}.")
        for executor in status.get("active_executors", [])[:3]:
            profile = executor.get("executor_profile") or executor.get("executor") or "unknown"
            target_type = executor.get("target_type") or "unknown"
            state = executor.get("state") or "active"
            latest_event = executor.get("latest_event", {})
            event_status = latest_event.get("status", "") if isinstance(latest_event, dict) else ""
            suffix = f", status={event_status}" if event_status else ""
            lines.append(
                f"- active executor: profile={profile}, target_type={target_type}, state={state}{suffix}."
            )
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
    if show_running_work:
        board_text = render_running_work_block_text(board)
        context_parts.append(board_text)
        record_running_work_board_emission(omh_home, byte_count=len(board_text), fingerprint=board_fingerprint)
    if degradation:
        payload["omh_degradation"] = degradation
        # Component labels only: error types stay in the structured payload, so
        # the model-facing text is minimal and stable.
        context_parts.append(
            "[OMH Degraded] components="
            + ",".join(str(row["component"]) for row in degradation["components"])
            + ". An OMH-local delegated call failed and a reduced local fallback answered. "
            "This is a local call failure, not a genuine standalone host. It is an observation of "
            "that failure only: not execution, review, CI, merge-readiness, or merge evidence."
        )
    payload["context"] = "\n\n".join(context_parts)
    _record_delivery(
        delivered=True,
        route_hint=bool(route_hint_context),
        context_chars=len(payload["context"]),
        omh_home=omh_home,
        session_id=session_id,
        route_fingerprint=route_fingerprint,
    )
    return payload
