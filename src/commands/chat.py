from __future__ import annotations

import argparse
import json

from ..coding_delegation import CODING_EXECUTOR_TARGETS
from ..ingress import CHAT_SOURCES
from ..installer import OmhError
from ..memory import read_handoff_context_pack_file
from ..routing.chat import CONFIDENCE_LEVELS, public_route_payload, route_chat_message, routing_record_payload
from ..runtime.artifacts import create_run, summarize_delegated_coding_status, write_routing_decision
from ..targets import TARGET_METADATA_KEYS, build_target_change_notice, inspect_target_observation, record_target_observation
from ..wrapper.contract import INTERACTION_MODES, build_chat_interaction_payload, build_chat_status_interaction
from ..wrapper.sessions import (
    WrapperSessionError,
    build_wrapper_session_status,
    create_or_resume_wrapper_session,
    list_wrapper_sessions,
    prepare_wrapper_session_handoff,
    record_plan_decision,
    select_wrapper_session_executor,
    show_wrapper_session,
)
from .common import _chat_input_and_metadata, _chat_message, _explicit_source_metadata, _paths, _print_json, _resolved_executor
from .runtime import _validate_runtime_names


def cmd_chat_route(args: argparse.Namespace) -> int:
    message = _chat_message(args)
    try:
        decision = route_chat_message(message, source=args.source, limit=args.limit, min_confidence=args.min_confidence)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    payload = {"route": public_route_payload(decision, include_message=args.include_message)}
    if args.record:
        paths = _paths(args)
        selected_skill = str(decision["selected_skill"])
        selected_harness = str(decision["selected_harness"])
        _validate_runtime_names(selected_skill, selected_harness)
        run = create_run(
            paths,
            {
                "skill": selected_skill,
                "harness": selected_harness,
                "status": "started",
                "trigger": f"chat:{args.source}:{decision['action']}",
                "privacy": "metadata_only",
                "inputs_summary": f"chat route from {args.source}; {len(message)} characters; prompt body not stored",
                "outputs_summary": f"routing action {decision['action']} selected {selected_skill}",
                "verification_summary": "routing decision recorded before Hermes dispatch",
            },
        )
        routing = write_routing_decision(
            paths.runtime_runs_dir / run["run_id"],
            routing_record_payload(
                decision,
                message,
                source_event_id=args.source_event_id or "",
                channel_ref=args.channel_ref or "",
                user_ref=args.user_ref or "",
            ),
        )
        payload["runtime"] = {"run": run, "routing": routing}
    _print_json(payload)
    return 0


def cmd_chat_interact(args: argparse.Namespace) -> int:
    try:
        if args.run_id:
            status = summarize_delegated_coding_status(_paths(args), args.run_id)
            payload = build_chat_status_interaction(
                status,
                source=args.source,
                source_metadata=_explicit_source_metadata(args),
            )
        else:
            event_or_message, source_metadata = _chat_input_and_metadata(args)
            payload = build_chat_interaction_payload(
                event_or_message,
                source=args.source,
                mode=args.mode,
                limit=args.limit,
                min_confidence=args.min_confidence,
                include_message=args.include_message,
                executor_target=_resolved_executor(args, default="choose"),
                source_metadata=source_metadata,
                target_notice=_target_notice(args, source_metadata),
            )
    except FileNotFoundError as exc:
        raise OmhError(f"runtime run not found: {args.run_id}") from exc
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_chat_session_start(args: argparse.Namespace) -> int:
    try:
        event_or_message, source_metadata = _chat_input_and_metadata(args)
        payload = create_or_resume_wrapper_session(
            _paths(args),
            event_or_message,
            source=args.source,
            limit=args.limit,
            min_confidence=args.min_confidence,
            source_metadata=source_metadata,
            executor_target=_resolved_executor(args, default="choose"),
            target_notice=_target_notice(args, source_metadata),
        )
    except (OSError, json.JSONDecodeError, ValueError, WrapperSessionError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_chat_session_decision(args: argparse.Namespace) -> int:
    try:
        _print_json(record_plan_decision(_paths(args), args.session_id, args.decision))
    except FileNotFoundError as exc:
        raise OmhError(f"wrapper session not found: {args.session_id}") from exc
    except WrapperSessionError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_chat_session_prepare_handoff(args: argparse.Namespace) -> int:
    try:
        event_or_message, source_metadata = _chat_input_and_metadata(args)
        payload = prepare_wrapper_session_handoff(
            _paths(args),
            args.session_id,
            event_or_message,
            limit=args.limit,
            include_message=args.include_message,
            source_metadata=source_metadata,
            executor_target=args.executor,
            context_pack=_context_pack(args),
        )
    except FileNotFoundError as exc:
        raise OmhError(f"wrapper session not found: {args.session_id}") from exc
    except (OSError, json.JSONDecodeError, ValueError, WrapperSessionError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def _target_notice(args: argparse.Namespace, source_metadata: dict[str, str]) -> dict[str, object] | None:
    if not _has_target_metadata(source_metadata):
        return None
    paths = _paths(args)
    auto_apply = bool(getattr(args, "auto_apply_target_change", False))
    if auto_apply:
        observation = record_target_observation(
            paths,
            source=f"chat:{args.source}",
            source_metadata=source_metadata,
            ensure_config=bool(source_metadata.get("hermes_home")),
        )
    else:
        observation = inspect_target_observation(paths, source=f"chat:{args.source}", source_metadata=source_metadata)
    return build_target_change_notice(observation, auto_applied=auto_apply)


def _context_pack(args: argparse.Namespace) -> dict[str, object] | None:
    path = getattr(args, "context_pack", None)
    if not path:
        return None
    return read_handoff_context_pack_file(path)


def _has_target_metadata(source_metadata: dict[str, str]) -> bool:
    return any(source_metadata.get(key) for key in TARGET_METADATA_KEYS)


def _add_target_metadata_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--agent-ref", default="", help="Optional Hermes agent id/name observed by the wrapper.")
    parser.add_argument("--target-ref", default="", help="Optional Hermes workspace/target id observed by the wrapper.")
    parser.add_argument("--runtime-ref", default="", help="Optional Hermes runtime id observed by the wrapper.")
    parser.add_argument("--agent-count", default="", help="Optional active Hermes agent count observed by the wrapper.")
    parser.add_argument("--target-count", default="", help="Optional active Hermes target count observed by the wrapper.")
    parser.add_argument(
        "--auto-apply-target-change",
        action="store_true",
        help="Persist observed Hermes target topology changes and register the managed skill dir when hermes_home metadata is present.",
    )


def cmd_chat_session_select_executor(args: argparse.Namespace) -> int:
    try:
        _print_json(select_wrapper_session_executor(_paths(args), args.session_id, args.executor))
    except FileNotFoundError as exc:
        raise OmhError(f"wrapper session not found: {args.session_id}") from exc
    except WrapperSessionError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_chat_session_status(args: argparse.Namespace) -> int:
    try:
        _print_json(build_wrapper_session_status(_paths(args), args.session_id))
    except FileNotFoundError as exc:
        raise OmhError(f"wrapper session not found: {args.session_id}") from exc
    return 0


def cmd_chat_session_show(args: argparse.Namespace) -> int:
    try:
        _print_json(show_wrapper_session(_paths(args), args.session_id))
    except FileNotFoundError as exc:
        raise OmhError(f"wrapper session not found: {args.session_id}") from exc
    return 0


def cmd_chat_session_list(args: argparse.Namespace) -> int:
    _print_json({"wrapper_sessions": list_wrapper_sessions(_paths(args))})
    return 0


def _add_chat_commands(sub) -> None:
    chat = sub.add_parser("chat")
    chat_sub = chat.add_subparsers(dest="chat_command", required=True)

    route = chat_sub.add_parser("route")
    route.add_argument("message", nargs="*", help="Chat message to route before dispatching to Hermes.")
    route.add_argument(
        "--source",
        choices=CHAT_SOURCES,
        default="generic",
        help="Source surface that received the chat message.",
    )
    route.add_argument("--limit", type=int, default=3, help="Maximum catalog recommendations to include.")
    route.add_argument(
        "--min-confidence",
        choices=CONFIDENCE_LEVELS,
        default="high",
        help="Minimum confidence for automatic workflow dispatch.",
    )
    route.add_argument("--stdin", action="store_true", help="Read the raw chat message from stdin.")
    route.add_argument(
        "--event-json",
        default=None,
        help="Read a Slack/Discord/Hermes-like JSON event from this path, or '-' for stdin.",
    )
    route.add_argument("--record", action="store_true", help="Record a metadata-only routing artifact under .omh/runtime.")
    route.add_argument(
        "--include-message",
        action="store_true",
        help="Include a complete routing_prompt with the raw message in stdout.",
    )
    route.add_argument("--source-event-id", default="", help="Optional source message/event id to store as metadata.")
    route.add_argument("--channel-ref", default="", help="Optional channel reference to store as metadata.")
    route.add_argument("--user-ref", default="", help="Optional user reference to store as metadata.")
    route.set_defaults(func=cmd_chat_route)

    interact = chat_sub.add_parser("interact")
    interact.add_argument("message", nargs="*", help="Chat message to turn into a wrapper-native interaction envelope.")
    interact.add_argument(
        "--source",
        choices=CHAT_SOURCES,
        default="generic",
        help="Source surface that received the chat message.",
    )
    interact.add_argument("--mode", choices=INTERACTION_MODES, default="auto", help="Interaction mode to compose.")
    interact.add_argument("--limit", type=int, default=3, help="Maximum catalog recommendations to include.")
    interact.add_argument(
        "--min-confidence",
        choices=CONFIDENCE_LEVELS,
        default="high",
        help="Minimum confidence for automatic workflow dispatch.",
    )
    interact.add_argument(
        "--executor",
        choices=CODING_EXECUTOR_TARGETS,
        default=None,
        help="Executor target for delegate-mode handoff payloads. Defaults to setup profile or explicit choice required.",
    )
    interact.add_argument("--stdin", action="store_true", help="Read the raw chat message from stdin.")
    interact.add_argument(
        "--event-json",
        default=None,
        help="Read a Slack/Discord/Hermes-like JSON event from this path, or '-' for stdin.",
    )
    interact.add_argument(
        "--include-message",
        action="store_true",
        help="Include the raw message in stdout for wrappers that dispatch immediately.",
    )
    interact.add_argument("--run", dest="run_id", default=None, help="Render a status interaction for an existing runtime run.")
    interact.add_argument("--source-event-id", default="", help="Optional source message/event id to store as metadata.")
    interact.add_argument("--channel-ref", default="", help="Optional channel reference to store as metadata.")
    interact.add_argument("--user-ref", default="", help="Optional user reference to store as metadata.")
    _add_target_metadata_options(interact)
    interact.set_defaults(func=cmd_chat_interact)

    session = chat_sub.add_parser("session")
    session_sub = session.add_subparsers(dest="session_command", required=True)

    session_start = session_sub.add_parser("start")
    session_start.add_argument("message", nargs="*", help="Chat message to bind to a wrapper session.")
    session_start.add_argument("--source", choices=CHAT_SOURCES, default="generic")
    session_start.add_argument("--limit", type=int, default=3)
    session_start.add_argument("--min-confidence", choices=CONFIDENCE_LEVELS, default="high")
    session_start.add_argument("--stdin", action="store_true")
    session_start.add_argument("--event-json", default=None)
    session_start.add_argument("--source-event-id", default="")
    session_start.add_argument("--channel-ref", default="")
    session_start.add_argument("--user-ref", default="")
    session_start.add_argument("--executor", choices=CODING_EXECUTOR_TARGETS, default=None)
    _add_target_metadata_options(session_start)
    session_start.set_defaults(func=cmd_chat_session_start)

    session_accept = session_sub.add_parser("accept-plan")
    session_accept.add_argument("session_id")
    session_accept.set_defaults(func=cmd_chat_session_decision, decision="accept")

    session_revise = session_sub.add_parser("revise-plan")
    session_revise.add_argument("session_id")
    session_revise.set_defaults(func=cmd_chat_session_decision, decision="revise")

    session_cancel = session_sub.add_parser("cancel")
    session_cancel.add_argument("session_id")
    session_cancel.set_defaults(func=cmd_chat_session_decision, decision="cancel")

    session_select = session_sub.add_parser("select-executor")
    session_select.add_argument("session_id")
    session_select.add_argument("executor", choices=tuple(value for value in CODING_EXECUTOR_TARGETS if value != "choose"))
    session_select.set_defaults(func=cmd_chat_session_select_executor)

    session_prepare = session_sub.add_parser("prepare-handoff")
    session_prepare.add_argument("session_id")
    session_prepare.add_argument("message", nargs="*", help="Original or clarified task text for the prepared handoff.")
    session_prepare.add_argument("--limit", type=int, default=3)
    session_prepare.add_argument("--stdin", action="store_true")
    session_prepare.add_argument("--event-json", default=None)
    session_prepare.add_argument("--include-message", action="store_true")
    session_prepare.add_argument("--source-event-id", default="")
    session_prepare.add_argument("--channel-ref", default="")
    session_prepare.add_argument("--user-ref", default="")
    session_prepare.add_argument("--executor", choices=tuple(value for value in CODING_EXECUTOR_TARGETS if value != "choose"), default=None)
    session_prepare.add_argument(
        "--context-pack",
        default=None,
        help="Optional handoff_context_pack/v1 JSON to attach to the prepared executor prompt when conflict-free.",
    )
    session_prepare.set_defaults(func=cmd_chat_session_prepare_handoff)

    session_status = session_sub.add_parser("status")
    session_status.add_argument("session_id")
    session_status.set_defaults(func=cmd_chat_session_status)

    session_show = session_sub.add_parser("show")
    session_show.add_argument("session_id")
    session_show.set_defaults(func=cmd_chat_session_show)

    session_list = session_sub.add_parser("list")
    session_list.set_defaults(func=cmd_chat_session_list)
