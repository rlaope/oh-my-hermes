from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from ..coding.executors import canonical_executor_profile
from ..codex_progress import (
    build_codex_prompt_handling_contract,
    build_codex_review_summary,
    summarize_codex_jsonl_file,
    summarize_codex_jsonl_text,
)
from ..coding_delegation import CODING_EXECUTOR_TARGETS
from ..ingress import CHAT_SOURCES, extract_message_text
from ..install.skill_registration import managed_command_runtime, registered_skill_dir
from ..installer import OmhError
from ..mission_control import build_mission_control
from ..memory import read_handoff_context_pack_file
from ..paths import managed_current_workflow_pack_dir
from ..quality.routing_question_corpus import (
    RoutingQuestionCorpusError,
    build_routing_question_corpus,
    format_routing_question_corpus,
    format_routing_question_score,
    read_answer_source,
    read_routing_question_corpus,
    score_routing_question_answers,
)
from ..routing.action_copy import next_action_label
from ..plugin_bundle.omh.route_answer_store import route_answer_dir
from ..plugin_bundle.omh.route_question_mode import read_route_question_mode
from ..quality.route_question_shadow_report import (
    build_route_question_shadow_report,
    format_route_question_shadow_report,
)
from ..routing.route_plan import public_workflow_identifier
from ..routing.route_question import apply_route_question_mode
from ..routing.chat import CONFIDENCE_LEVELS, public_route_payload, route_chat_event, routing_record_payload
from ..runtime.artifacts import create_run, summarize_delegated_coding_status, write_routing_decision
from ..system.local_store import atomic_write_json
from ..targets import TARGET_METADATA_KEYS, build_target_change_notice, inspect_target_observation, record_target_observation
from ..wrapper.contract import INTERACTION_MODES, RENDER_PROFILES, build_chat_interaction_payload, build_chat_status_interaction
from ..wrapper.executor_sessions import (
    EXECUTOR_SESSION_OBSERVED_RESULTS,
    ExecutorSessionError,
    attach_executor_session,
    open_executor_session,
    record_executor_session_result,
    request_executor_session_verification,
)
from ..wrapper.native_commands import NATIVE_COMMAND_SOURCES, build_native_command_surface
from ..wrapper.route_hints import build_chat_route_hint_payload
from ..wrapper.work_artifact_actions import build_work_artifact_copy_action
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
from ..workflows.domain_project_context import bind_cli_project
from ..evidence import confidence_label
from .common import (
    _chat_input_and_metadata,
    _chat_message,
    _command_hermes_session_id,
    _explicit_source_metadata,
    _paths,
    _print_json,
    _wants_json,
    add_revision_guard_arguments,
)
from .runtime import _validate_runtime_names


def cmd_chat_route(args: argparse.Namespace) -> int:
    if bool(getattr(args, "summary", False)) and bool(getattr(args, "json", False)):
        raise OmhError("--summary and --json cannot be used together")
    event_or_message, _ = _chat_input_and_metadata(args)
    try:
        policy = _chat_route_skill_policy(args)
        decision = route_chat_event(
            event_or_message,
            source=args.source,
            limit=args.limit,
            min_confidence=args.min_confidence,
            skill_policy=policy,
        )
        message = "GitHub tracker event" if "tracker_content" in decision else extract_message_text(event_or_message)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    # The mode comes from the OMH config of this home, never from the route
    # or the caller. It shapes what the surface hands out; the record below
    # keeps the router's own decision and says what the mode did to it.
    route_question_mode = read_route_question_mode(_paths(args).omh_home)
    payload = {
        "route": apply_route_question_mode(
            public_route_payload(decision, include_message=args.include_message),
            route_question_mode["mode"],
        )
    }
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
                route_question_mode=route_question_mode,
            ),
        )
        payload["runtime"] = {"run": run, "routing": routing}
    if bool(getattr(args, "summary", False)):
        _print_chat_route_summary(payload)
    elif _wants_json(args):
        _print_json(payload)
    else:
        _print_chat_route_summary(payload)
    return 0


def _chat_route_skill_policy(args: argparse.Namespace) -> dict[str, object] | None:
    inline = getattr(args, "skill_policy_json", None)
    path = getattr(args, "skill_policy_file", None)
    if inline is not None and path is not None:
        raise ValueError("skill policy accepts either inline JSON or a file, not both")
    if inline is None and path is None:
        return None
    raw = inline if inline is not None else Path(path).expanduser().read_text(encoding="utf-8")
    policy = json.loads(raw)
    if not isinstance(policy, dict):
        raise ValueError("skill policy JSON must be an object")
    return policy


def cmd_chat_route_hint(args: argparse.Namespace) -> int:
    if bool(getattr(args, "summary", False)) and bool(getattr(args, "json", False)):
        raise OmhError("--summary and --json cannot be used together")
    try:
        event_or_message, source_metadata = _chat_input_and_metadata(args)
        message = extract_message_text(event_or_message) if isinstance(event_or_message, dict) else str(event_or_message)
        payload = build_chat_route_hint_payload(
            message,
            source=args.source,
            max_hints=args.max_hints,
            source_metadata=source_metadata,
            include_prompt_context=args.prompt_context,
            # The homes are what the answerer ladder is read from; without
            # them the payload still carries the question, with no ladder.
            paths=_paths(args),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    if bool(getattr(args, "summary", False)):
        _print_chat_route_hint_summary(payload)
    elif _wants_json(args):
        _print_json(payload)
    else:
        _print_chat_route_hint_summary(payload)
    return 0


def cmd_chat_route_questions_export(args: argparse.Namespace) -> int:
    """Export both shipped routing corpora as typed route questions.

    The payload is large, so stdout carries a summary unless `--json` asks for
    the whole thing; `--output` always writes the full corpus.
    """
    try:
        payload = build_routing_question_corpus(source=args.source, limit=args.limit)
        if args.output:
            atomic_write_json(Path(args.output).expanduser(), payload)
    except (OSError, RoutingQuestionCorpusError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json(payload)
    else:
        print(format_routing_question_corpus(payload))
    return 0


def cmd_chat_route_questions_score(args: argparse.Namespace) -> int:
    """Score an answer set against an exported corpus.

    The deterministic arm is always in the report, so an answering arm is read
    next to the router it would replace. `--answers` is optional: without it
    the report is the deterministic arm alone, which is the offline baseline.

    The exit status is 0 whenever a report was produced. A poor score is a
    result, not a command failure; only input that cannot be read as a corpus
    or as answers fails the command.
    """
    overrides: dict[str, float] = {}
    if args.fits_dispatch is not None:
        overrides["fits_dispatch"] = args.fits_dispatch
    if args.fits_clarify is not None:
        overrides["fits_clarify"] = args.fits_clarify
    try:
        corpus = read_routing_question_corpus(Path(args.corpus).expanduser())
        records = read_answer_source(Path(args.answers).expanduser()) if args.answers else []
        payload = score_routing_question_answers(corpus, records, thresholds=overrides or None)
        if args.output:
            atomic_write_json(Path(args.output).expanduser(), payload)
    except (OSError, json.JSONDecodeError, RoutingQuestionCorpusError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json(payload)
    else:
        print(format_routing_question_score(payload))
    return 0


def cmd_chat_route_questions_report(args: argparse.Namespace) -> int:
    """Join recorded route answers to recorded routes over a window and report it.

    Defaults read this OMH home: answers from `runtime/route-questions/`,
    routes from `runtime/runs/` (`omh chat route --record`) and from the
    wrapper-session event logs (live turns that built a question). The exit status is 0 whenever a report was
    produced, an empty window included -- its rates say `percent: null`
    rather than failing the command.
    """
    paths = _paths(args)
    answers = Path(args.answers).expanduser() if args.answers else route_answer_dir(paths.omh_home)
    runs = Path(args.runs).expanduser() if args.runs else paths.runtime_runs_dir
    sessions = Path(args.sessions).expanduser() if args.sessions else paths.runtime_wrapper_sessions_dir
    try:
        payload = build_route_question_shadow_report(
            answers, runs, sessions_dir=sessions, since=args.since, model=args.model or ""
        )
        if args.output:
            atomic_write_json(Path(args.output).expanduser(), payload)
    except (OSError, RoutingQuestionCorpusError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json(payload)
    else:
        print(format_route_question_shadow_report(payload))
    return 0


def cmd_chat_interact(args: argparse.Namespace) -> int:
    if bool(getattr(args, "summary", False)) and bool(getattr(args, "json", False)):
        raise OmhError("--summary and --json cannot be used together")
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
            invocation_cwd = Path.cwd()
            payload = build_chat_interaction_payload(
                event_or_message,
                source=args.source,
                mode=args.mode,
                limit=args.limit,
                min_confidence=args.min_confidence,
                include_message=args.include_message,
                executor_target=_requested_executor(args),
                source_metadata=source_metadata,
                target_notice=_target_notice(args, source_metadata),
                paths=_paths(args),
                skill_policy=_chat_route_skill_policy(args),
                platform_context=_platform_context(args),
                hermes_session_id=_command_hermes_session_id(),
                _host_project_binding_factory=lambda: bind_cli_project(invocation_cwd),
            )
    except FileNotFoundError as exc:
        raise OmhError(f"runtime run not found: {args.run_id}") from exc
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    if bool(getattr(args, "summary", False)):
        _print_chat_interaction_summary(payload)
    elif _wants_json(args):
        _print_json(payload)
    else:
        _print_chat_interaction_summary(payload)
    return 0


def _requested_executor(args: argparse.Namespace) -> str:
    """The owner the person named with ``--executor``, or "choose".

    The setup-profile default is not resolved here: the wrapper reads it
    itself and labels it `setup_profile`, so it is never taken for an owner
    named in this request (it does not bypass the genre veto and is not
    recorded as an explicit choice). The owner that runs is the same.
    """
    explicit = str(getattr(args, "executor", None) or "").strip()
    return explicit or "choose"


def cmd_chat_session_start(args: argparse.Namespace) -> int:
    try:
        event_or_message, source_metadata = _chat_input_and_metadata(args)
        invocation_cwd = Path.cwd()
        payload = create_or_resume_wrapper_session(
            _paths(args),
            event_or_message,
            source=args.source,
            limit=args.limit,
            min_confidence=args.min_confidence,
            source_metadata=source_metadata,
            executor_target=_requested_executor(args),
            target_notice=_target_notice(args, source_metadata),
            platform_context=_platform_context(args),
            hermes_session_id=_command_hermes_session_id(),
            _host_project_binding_factory=lambda: bind_cli_project(invocation_cwd),
        )
    except (OSError, json.JSONDecodeError, ValueError, WrapperSessionError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def _revision_guard(args: argparse.Namespace) -> dict[str, object]:
    """The guard arguments a chat session mutation forwards to the record write.

    Read through getattr so subcommands that do not reach a guarded write stay
    unaffected, and normalized the same way the goal CLI does: an absent
    --mutation-id is None ("no id supplied"), never the empty string.
    """
    return {
        "expected_revision": getattr(args, "expected_revision", None),
        "mutation_id": getattr(args, "mutation_id", "") or None,
    }


def cmd_chat_session_decision(args: argparse.Namespace) -> int:
    try:
        _print_json(record_plan_decision(_paths(args), args.session_id, args.decision, **_revision_guard(args)))
    except FileNotFoundError as exc:
        raise OmhError(f"wrapper session not found: {args.session_id}") from exc
    # StaleRecordMutation / MutationHistoryEvicted / ConflictingMutationReplay
    # are ValueErrors raised by the guarded write, and reach the user as
    # "omh: <message>" rather than a traceback.
    except (ValueError, WrapperSessionError) as exc:
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
            retarget=bool(getattr(args, "retarget", False)),
            hermes_session_id=_command_hermes_session_id(),
            **_revision_guard(args),
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
            # The path setup registers: never the running generation's own pack.
            registered_dir=registered_skill_dir(
                paths, current=managed_current_workflow_pack_dir(), runtime=managed_command_runtime
            ),
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


def _as_mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _text(value: object, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


_INLINE_INTERNAL_ID_RE = re.compile(r"\s\(`[-A-Za-z0-9_:]+`\)")


def _summary_text(value: object, default: str = "") -> str:
    return _INLINE_INTERNAL_ID_RE.sub("", _text(value, default))


def _action_label_without_id(action: str, label: str = "") -> str:
    normalized = action.strip()
    if not normalized:
        return ""
    resolved_label = label.strip() or next_action_label(normalized)
    return resolved_label or normalized


_ROUTE_ACTION_LABELS = {
    "clarify": "asking one clarification",
    "dispatch": "routing to a workflow",
    "fallback": "answering without a workflow",
}



def _route_action_label_without_id(action: str) -> str:
    normalized = action.strip()
    return _action_label_without_id(normalized, _ROUTE_ACTION_LABELS.get(normalized, ""))


def _status_label_without_id(status: str) -> str:
    """The status a person reads in the route summary.

    Was a private map here saying `prepared, not observed` while the status
    board said `prepared_not_observed` and the menubar said
    `prepared not observed` -- three vocabularies for one state. Routed through
    `omh.evidence.labels` so all three agree, and so an unrecognized value fails
    closed instead of being spelled out with its underscores replaced.
    """
    normalized = status.strip()
    if not normalized:
        return ""
    return confidence_label(normalized)


def _format_summary_action(action: dict[str, object]) -> str:
    action_id = _text(action.get("id"), "action")
    label = _text(action.get("label"), action_id)
    enabled = bool(action.get("enabled", True))
    state_label = "enabled" if enabled else "disabled"
    label_with_id = _action_label_without_id(action_id, label)
    return f"- {label_with_id} - {state_label}"


def _print_chat_interaction_summary(payload: dict[str, object]) -> None:
    response = _as_mapping(payload.get("chat_response"))
    route = _as_mapping(payload.get("route"))
    state = _as_mapping(response.get("state"))
    route_explanation = _as_mapping(route.get("route_explanation"))
    source = _text(payload.get("source"), "generic")
    # The explanation's `selected_workflow` is the public identifier; `state`
    # and `route` hold catalog keys. A `Workflow:` line a person reads has to
    # name something they can type back (#1249), so the public one leads.
    selected_workflow = _text(
        route_explanation.get("selected_workflow")
        or state.get("selected_workflow")
        or route.get("selected_skill")
        or response.get("kind"),
        "unknown",
    )
    next_action = _text(payload.get("next_action") or state.get("next_action") or route.get("action"), "unknown")
    next_action_label_text = _text(
        payload.get("next_action_label")
        or state.get("next_action_label")
        or _as_mapping(state.get("workflow_explanation")).get("route_next_action_label")
        or route_explanation.get("next_action_label"),
        next_action_label(next_action) if next_action != "unknown" else "",
    )
    print("OMH chat interaction")
    print(f"Source: {source}")
    print(f"Workflow: {selected_workflow}")
    print(f"Next action: {_action_label_without_id(next_action, next_action_label_text)}")

    headline = _summary_text(response.get("headline") or response.get("plain_headline"))
    body = _summary_text(response.get("body") or response.get("plain_body"))
    if headline or body:
        print()
        if headline:
            print(headline)
        if body:
            print(body)

    actions = [action for action in _as_list(response.get("actions")) if isinstance(action, dict)]
    if actions:
        print()
        print("Actions:")
        action_limit = 12
        for action in actions[:action_limit]:
            print(_format_summary_action(action))
        if len(actions) > action_limit:
            print(f"- ... {len(actions) - action_limit} more action(s) in --json")

    not_evidence = [
        _text(item)
        for item in (
            _as_list(state.get("evidence_not_observed"))
            or _as_list(route_explanation.get("not_evidence_yet"))
            or _as_list(response.get("not_evidence_yet"))
        )
        if _text(item)
    ]
    if not_evidence:
        print()
        print("Not evidence yet:")
        for item in not_evidence[:6]:
            print(f"- {item}")

    boundary = _text(response.get("claim_boundary") or route_explanation.get("claim_boundary"))
    if boundary:
        print()
        print("Boundary:")
        print(f"  {boundary}")

    print()
    print("Use --json for the full machine-readable payload.")


def _print_chat_route_summary(payload: dict[str, object]) -> None:
    route = _as_mapping(payload.get("route"))
    route_explanation = _as_mapping(route.get("route_explanation"))
    selected_workflow = _text(route_explanation.get("selected_workflow") or route.get("selected_skill"), "unknown")
    selected_harness = _text(route.get("selected_harness") or route_explanation.get("selected_harness"), "unknown")
    action = _text(route.get("action") or route_explanation.get("action"), "unknown")
    source = _text(route.get("source"), "generic")
    confidence = _text(route.get("confidence") or route_explanation.get("confidence"), "unknown")
    score = _text(route.get("score") or route_explanation.get("score"), "0")
    next_action = _text(route_explanation.get("next_action") or _first_recommendation_value(route, "next_action"), "unknown")
    next_action_label_text = _text(
        route_explanation.get("next_action_label"),
        next_action_label(next_action) if next_action != "unknown" else "",
    )

    print("OMH chat route")
    print(f"Source: {source}")
    print(f"Workflow: {selected_workflow}")
    print(f"Harness: {selected_harness}")
    print(f"Action: {_route_action_label_without_id(action)}")
    print(f"Next action: {_action_label_without_id(next_action, next_action_label_text)}")
    print(f"Confidence: {confidence} (score {score})")

    why = _summary_text(route_explanation.get("why_this_workflow") or route.get("reason"))
    if why:
        print()
        print("Why:")
        print(f"  {why}")

    recommended_reply = _summary_text(route_explanation.get("recommended_reply"))
    if recommended_reply:
        print()
        print("Reply:")
        print(f"  {recommended_reply}")

    primary_action_hint = _summary_text(route_explanation.get("primary_action_hint"))
    if primary_action_hint:
        print()
        print("Action hint:")
        print(f"  {primary_action_hint}")

    recommendations = [item for item in _as_list(route.get("recommendations")) if isinstance(item, dict)]
    if recommendations:
        print()
        print("Top recommendations:")
        for item in recommendations[:5]:
            skill = public_workflow_identifier(_text(item.get("skill"), "unknown"))
            item_next = _text(item.get("next_action"), "unknown")
            item_next_label = _text(item.get("next_action_label"), next_action_label(item_next))
            item_confidence = _text(item.get("confidence"), "unknown")
            item_score = _text(item.get("score"), "0")
            print(f"- {skill}: {_action_label_without_id(item_next, item_next_label)} ({item_confidence}, score {item_score})")

    route_plan = _as_mapping(route.get("workflow_route_plan"))
    steps = [item for item in _as_list(route_plan.get("steps")) if isinstance(item, dict)]
    if steps:
        print()
        print("Route plan:")
        for step in steps[:6]:
            order = _text(step.get("order"), "?")
            stage = _text(step.get("stage"), "stage")
            skill = _text(step.get("skill"), "workflow")
            status = _text(step.get("status"), "prepared_not_observed")
            print(f"- {order}. {stage}: {skill} - {_status_label_without_id(status)}")

    not_evidence = [_text(item) for item in _as_list(route_explanation.get("not_evidence_yet")) if _text(item)]
    if not_evidence:
        print()
        print("Not evidence yet:")
        for item in not_evidence[:6]:
            print(f"- {item}")

    boundary = _text(route_explanation.get("claim_boundary") or _first_recommendation_value(route, "evidence_boundary"))
    if boundary:
        print()
        print("Boundary:")
        print(f"  {boundary}")

    run = _as_mapping(_as_mapping(payload.get("runtime")).get("run"))
    if run:
        print()
        print("Runtime record:")
        print(f"  run_id: {_text(run.get('run_id'), 'unknown')}")
        print("  status: recorded metadata only")

    print()
    print("Use --json for the full machine-readable route payload.")


def _print_chat_route_hint_summary(payload: dict[str, object]) -> None:
    response = _as_mapping(payload.get("chat_response"))
    # A direct-answer card offers no workflow, so the summary reads the card
    # rather than the hint rail beside it: no hinted workflow, cues, or tool
    # checkpoint. `--json` still carries the hint.
    answers_directly = response.get("kind") == "direct_answer_route_hint"
    route_hint = {} if answers_directly else _as_mapping(payload.get("route_hint"))
    state = _as_mapping(response.get("state"))
    state_route_hint = _as_mapping(state.get("route_hint"))
    hints = [item for item in _as_list(route_hint.get("hints")) if isinstance(item, dict)]
    primary_hint = hints[0] if hints else {}
    status = "direct_answer" if answers_directly else _text(route_hint.get("status") or ("hinted" if hints else "no_hint"), "unknown")
    fallback_workflow = "none" if status in {"no_hint", "direct_answer"} else "unknown"
    selected_workflow = _text(
        route_hint.get("primary_workflow")
        or route_hint.get("selected_workflow")
        or state_route_hint.get("primary_workflow")
        or state.get("selected_workflow"),
        fallback_workflow,
    )
    next_action = _text(
        route_hint.get("primary_next_action")
        or state_route_hint.get("primary_next_action")
        or state.get("next_action"),
        "open_picker_or_clarify" if status == "no_hint" else "unknown",
    )
    next_action_label_text = _text(
        route_hint.get("primary_next_action_label")
        or state_route_hint.get("primary_next_action_label")
        or primary_hint.get("next_action_label"),
        next_action_label(next_action) if next_action != "unknown" else "",
    )
    source = _text(payload.get("source"), "generic")
    hint_count = len(hints)

    print("OMH route hint")
    print(f"Source: {source}")
    print(f"Status: {status}")
    print(f"Workflow: {selected_workflow}")
    print(f"Next action: {_action_label_without_id(next_action, next_action_label_text)}")
    print(f"Hints: {hint_count}")

    matched_cues = _text_items(_as_list(primary_hint.get("matched_cues")))
    if matched_cues:
        print(f"Matched cues: {_join_text_items(matched_cues)}")
    adjacent_workflows = _text_items(
        _as_list(route_hint.get("adjacent_workflows")) or _as_list(primary_hint.get("adjacent_workflows"))
    )
    if adjacent_workflows:
        print(f"Adjacent workflows: {_join_text_items(adjacent_workflows)}")

    headline = _summary_text(response.get("headline"))
    body = _summary_text(response.get("body"))
    if headline or body:
        print()
        if headline:
            print(headline)
        if body:
            print(body)

    if hints:
        print()
        print("Hint details:")
        for hint in hints[:5]:
            workflow = _text(hint.get("workflow"), "unknown")
            lane = _text(hint.get("lane"), "unknown")
            action = _text(hint.get("next_action"), "unknown")
            action_label = _text(hint.get("next_action_label"), next_action_label(action))
            reason = _summary_text(hint.get("reason"))
            print(f"- {workflow}: {_action_label_without_id(action, action_label)} ({lane})")
            hint_cues = _text_items(_as_list(hint.get("matched_cues")))
            if hint_cues:
                print(f"  matched: {_join_text_items(hint_cues)}")
            if reason:
                print(f"  why: {reason}")

    actions = [action for action in _as_list(response.get("actions")) if isinstance(action, dict)]
    if actions:
        print()
        print("Actions:")
        printed_rows: set[str] = set()
        for action in actions:
            row = _format_summary_action(action)
            if row in printed_rows:
                continue
            printed_rows.add(row)
            print(row)
            if len(printed_rows) >= 6:
                break

    checkpoint = {} if answers_directly else _as_mapping(payload.get("generic_tool_checkpoint"))
    checkpoint_body = _summary_text(checkpoint.get("body"))
    if checkpoint_body:
        print()
        print("Checkpoint:")
        print(f"  {checkpoint_body}")

    not_evidence = [
        _text(item)
        for item in (
            _as_list(route_hint.get("not_executed"))
            or _as_list(_first_hint_value(route_hint, "not_evidence_yet"))
            or _as_list(checkpoint.get("not_evidence_yet"))
        )
        if _text(item)
    ]
    if not_evidence:
        print()
        print("Not evidence yet:")
        for item in not_evidence[:6]:
            print(f"- {item}")

    prompt_context = _text(payload.get("prompt_context"))
    if prompt_context:
        print()
        print("Prompt context: included")

    boundary = _summary_text(payload.get("claim_boundary") or response.get("claim_boundary") or route_hint.get("claim_boundary"))
    if boundary:
        print()
        print("Boundary:")
        print(f"  {boundary}")

    print()
    print("Use --json for the full machine-readable route hint payload.")


def _first_hint_value(route_hint: dict[str, object], key: str) -> object:
    hints = _as_list(route_hint.get("hints"))
    if not hints or not isinstance(hints[0], dict):
        return ""
    return hints[0].get(key, "")


def _text_items(items: list[object]) -> list[str]:
    return [_text(item) for item in items if _text(item)]


def _join_text_items(items: list[str], limit: int = 6) -> str:
    visible = items[:limit]
    suffix = f", +{len(items) - limit} more" if len(items) > limit else ""
    return ", ".join(visible) + suffix


def _first_recommendation_value(route: dict[str, object], key: str) -> object:
    recommendations = _as_list(route.get("recommendations"))
    if not recommendations or not isinstance(recommendations[0], dict):
        return ""
    return recommendations[0].get(key, "")


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


def _add_render_profile_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--render-profile",
        choices=RENDER_PROFILES,
        default="",
        help="Override the source default rendering profile for this adapter surface.",
    )


def _add_platform_context_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--platform",
        default="",
        help=(
            "Registered platform id (for example whatsapp or signal) the adapter serves. "
            "Merged into --platform-context-json as platform_context.platform."
        ),
    )
    parser.add_argument(
        "--platform-context-json",
        default=None,
        help=(
            "Inline JSON object carrying the platform context: platform plus "
            "conversation_ref/thread_ref/user_ref and optional limits, capabilities, or "
            "render_profile. Refs must be adapter-generated opaque values -- prefixed or "
            "hashed by the adapter (for example discord-channel-<snowflake>), never raw "
            "phone numbers, emails, JIDs, or native numeric IDs. Validated into an "
            "omh_platform_envelope/v1 before any write; unsafe refs fail closed."
        ),
    )


def _platform_context(args: argparse.Namespace) -> dict[str, object] | None:
    """Merge --platform and --platform-context-json into one context mapping.

    Returns None when neither flag is present so legacy calls stay exactly
    legacy. Fails closed on malformed JSON, a non-object document, or a
    --platform that contradicts the document's platform key.
    """
    platform = str(getattr(args, "platform", "") or "").strip()
    raw = getattr(args, "platform_context_json", None)
    context: dict[str, object] = {}
    if raw is not None:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OmhError(f"--platform-context-json is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise OmhError("--platform-context-json must be a JSON object")
        context = dict(parsed)
    if platform:
        declared = context.get("platform")
        if declared is not None and str(declared) != platform:
            raise OmhError(
                f"--platform {platform!r} contradicts --platform-context-json platform {declared!r}"
            )
        context["platform"] = platform
    if not context:
        return None
    return context


def _add_codex_observation_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--codex-session-ref", default="", help="Observed Codex session id suitable for resume contracts.")
    parser.add_argument("--codex-thread-ref", default="", help="Observed Codex thread/conversation reference when distinct from the session id.")
    parser.add_argument("--codex-log-jsonl", default=None, help="Observed Codex JSONL/process output to summarize; raw events are not echoed.")
    parser.add_argument("--codex-log-ref", default="", help="Evidence reference for the observed Codex log source.")


def cmd_chat_session_select_executor(args: argparse.Namespace) -> int:
    try:
        _print_json(
            select_wrapper_session_executor(_paths(args), args.session_id, args.executor, **_revision_guard(args))
        )
    except FileNotFoundError as exc:
        raise OmhError(f"wrapper session not found: {args.session_id}") from exc
    except (ValueError, WrapperSessionError) as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_chat_session_status(args: argparse.Namespace) -> int:
    try:
        _print_json(build_wrapper_session_status(_paths(args), args.session_id))
    except FileNotFoundError as exc:
        raise OmhError(f"wrapper session not found: {args.session_id}") from exc
    return 0


def cmd_chat_session_artifacts(args: argparse.Namespace) -> int:
    try:
        status = build_wrapper_session_status(_paths(args), args.session_id)
    except FileNotFoundError as exc:
        raise OmhError(f"wrapper session not found: {args.session_id}") from exc
    _print_json(build_work_artifact_copy_action(status, artifact_id=args.artifact_id or ""))
    return 0


def cmd_chat_session_mission_control(args: argparse.Namespace) -> int:
    try:
        _print_json(build_mission_control(_paths(args), args.session_id))
    except FileNotFoundError as exc:
        raise OmhError(f"wrapper session not found: {args.session_id}") from exc
    return 0


def cmd_chat_session_open_executor(args: argparse.Namespace) -> int:
    try:
        codex_progress = _codex_progress_from_args(args)
        _print_json(
            open_executor_session(
                _paths(args),
                args.session_id,
                observed=args.observed,
                external_session_ref=args.external_session_ref or "",
                evidence_refs=args.evidence_ref or [],
                summary=args.summary or "",
                codex_session_ref=args.codex_session_ref or "",
                codex_thread_ref=args.codex_thread_ref or "",
                codex_progress_summary=codex_progress,
            )
        )
    except FileNotFoundError as exc:
        raise OmhError(f"wrapper session not found: {args.session_id}") from exc
    except (OSError, ExecutorSessionError, WrapperSessionError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_chat_session_attach_executor(args: argparse.Namespace) -> int:
    try:
        codex_progress = _codex_progress_from_args(args)
        _print_json(
            attach_executor_session(
                _paths(args),
                args.session_id,
                external_session_ref=args.external_session_ref,
                evidence_refs=args.evidence_ref or [],
                summary=args.summary or "",
                codex_session_ref=args.codex_session_ref or "",
                codex_thread_ref=args.codex_thread_ref or "",
                codex_progress_summary=codex_progress,
            )
        )
    except FileNotFoundError as exc:
        raise OmhError(f"wrapper session not found: {args.session_id}") from exc
    except (OSError, ExecutorSessionError, WrapperSessionError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_chat_session_record_executor(args: argparse.Namespace) -> int:
    try:
        codex_progress = _codex_progress_from_args(args)
        _print_json(
            record_executor_session_result(
                _paths(args),
                args.session_id,
                result=args.result,
                evidence_refs=args.evidence_ref or [],
                summary=args.summary or "",
                codex_progress_summary=codex_progress,
            )
        )
    except FileNotFoundError as exc:
        raise OmhError(f"wrapper session not found: {args.session_id}") from exc
    except (OSError, ExecutorSessionError, WrapperSessionError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_chat_session_request_verification(args: argparse.Namespace) -> int:
    try:
        _print_json(
            request_executor_session_verification(
                _paths(args),
                args.session_id,
                evidence_refs=args.evidence_ref or [],
                summary=args.summary or "",
            )
        )
    except FileNotFoundError as exc:
        raise OmhError(f"wrapper session not found: {args.session_id}") from exc
    except (ExecutorSessionError, WrapperSessionError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
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


def cmd_chat_native_command(args: argparse.Namespace) -> int:
    try:
        _print_json(build_native_command_surface(args.source))
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_chat_codex_progress(args: argparse.Namespace) -> int:
    try:
        if args.jsonl:
            progress = summarize_codex_jsonl_file(args.jsonl, evidence_refs=args.evidence_ref or [])
        else:
            text = sys.stdin.read() if args.stdin else ""
            progress = summarize_codex_jsonl_text(text, evidence_refs=args.evidence_ref or [], source="stdin")
    except OSError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "codex_progress_adapter/v1",
            "progress": progress,
            "chat_summary": progress.get("chat_summary", ""),
            "adapter_contract": {
                "purpose": "Turn raw Codex JSONL or process output into compact chat-safe progress/final summaries.",
                "raw_events_exposed": False,
                "hidden_reasoning_exposed": False,
                "claim_boundary": progress.get("claim_boundary", ""),
            },
        }
    )
    return 0


def cmd_chat_codex_review(args: argparse.Namespace) -> int:
    try:
        progress = _codex_progress_from_args(args)
        review = _codex_review_from_args(args, progress_summary=progress)
        if review is None:
            review = build_codex_review_summary(
                progress_summary=progress,
                codex_session_ref=args.codex_session_ref or "",
                codex_thread_ref=args.codex_thread_ref or "",
                external_session_ref=args.external_session_ref or "",
                evidence_refs=args.evidence_ref or [],
            )
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "codex_review_adapter/v1",
            "codex_review": review,
            "chat_summary": review.get("human_summary", ""),
            "adapter_contract": review.get("adapter_contract", {}),
        }
    )
    return 0


def cmd_chat_codex_followup(args: argparse.Namespace) -> int:
    message = _chat_message(args)
    if not message:
        raise OmhError("codex-followup requires a new prompt")
    try:
        progress = _codex_progress_from_args(args)
        session_ref = args.codex_session_ref or ""
        thread_ref = args.codex_thread_ref or ""
        external_ref = args.external_session_ref or ""
        wrapper_session: dict[str, object] = {}
        if args.session_id:
            status = build_wrapper_session_status(_paths(args), args.session_id)
            executor_status = status.get("executor_session_status", {}) if isinstance(status.get("executor_session_status"), dict) else {}
            codex_session = executor_status.get("codex_session", {}) if isinstance(executor_status.get("codex_session"), dict) else {}
            codex_progress = executor_status.get("codex_progress", {}) if isinstance(executor_status.get("codex_progress"), dict) else {}
            session_ref = session_ref or str(codex_session.get("session_ref", ""))
            thread_ref = thread_ref or str(codex_session.get("thread_ref", ""))
            external_ref = external_ref or str(codex_session.get("external_session_ref", ""))
            if progress is None and codex_progress:
                progress = codex_progress
            wrapper_session = {
                "session_id": args.session_id,
                "session_status": status.get("session_status", ""),
                "executor_session": executor_status.get("executor_session", ""),
                "dispatch": executor_status.get("dispatch", ""),
                "result": executor_status.get("result", ""),
                "verification": executor_status.get("verification", ""),
            }
        evidence_refs = list(args.evidence_ref or [])
        review_summary = _codex_review_from_args(
            args,
            progress_summary=progress,
            codex_session_ref=session_ref,
            codex_thread_ref=thread_ref,
            external_session_ref=external_ref,
        )
        payload = build_codex_prompt_handling_contract(
            new_prompt=message,
            progress_summary=progress,
            codex_session_ref=session_ref,
            codex_thread_ref=thread_ref,
            external_session_ref=external_ref,
            wrapper_session_id=args.session_id or "",
            same_goal=bool(args.same_goal),
            evidence_refs=evidence_refs,
            codex_review_summary=review_summary,
        )
        if wrapper_session:
            payload["wrapper_session"] = wrapper_session
    except FileNotFoundError as exc:
        raise OmhError(f"wrapper session not found: {args.session_id}") from exc
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def _codex_progress_from_args(args: argparse.Namespace) -> dict[str, object] | None:
    path = getattr(args, "codex_log_jsonl", None)
    if not path:
        return None
    refs = list(getattr(args, "evidence_ref", None) or [])
    log_ref = str(getattr(args, "codex_log_ref", "") or "").strip()
    if log_ref:
        refs.append(log_ref)
    return summarize_codex_jsonl_file(Path(path), evidence_refs=refs)


def _codex_review_from_args(
    args: argparse.Namespace,
    *,
    progress_summary: dict[str, object] | None = None,
    codex_session_ref: str = "",
    codex_thread_ref: str = "",
    external_session_ref: str = "",
) -> dict[str, object] | None:
    status = str(getattr(args, "codex_review_status", "") or "").strip()
    summary = str(getattr(args, "codex_review_summary", "") or "").strip()
    finding_count = getattr(args, "codex_review_finding_count", None)
    reviewer = str(getattr(args, "codex_reviewer", "") or "codex")
    if not status and not summary and finding_count is None:
        return None
    return build_codex_review_summary(
        review_status=status or "not_observed",
        reviewer=reviewer,
        summary=summary,
        finding_count=finding_count,
        progress_summary=progress_summary,
        codex_session_ref=codex_session_ref or str(getattr(args, "codex_session_ref", "") or ""),
        codex_thread_ref=codex_thread_ref or str(getattr(args, "codex_thread_ref", "") or ""),
        external_session_ref=external_session_ref or str(getattr(args, "external_session_ref", "") or ""),
        evidence_refs=list(getattr(args, "evidence_ref", None) or []),
    )


def _add_codex_review_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--codex-review-status", default="", help="Observed Codex review status, such as passed or changes_requested.")
    parser.add_argument("--codex-review-summary", default="", help="Human-readable Codex review summary; raw logs are not echoed.")
    parser.add_argument("--codex-review-finding-count", type=int, default=None, help="Optional observed count of summarized Codex review findings.")
    parser.add_argument("--codex-reviewer", default="codex", help="Observed reviewer label for the Codex review summary.")


def _add_chat_commands(sub) -> None:
    chat = sub.add_parser("chat", help="Turn wrapper chat events into OMH routing, handoff, and status envelopes.")
    chat_sub = chat.add_subparsers(dest="chat_command", required=True)

    route = chat_sub.add_parser("route", help="Route a plain chat message to the most relevant OMH workflow.")
    route.add_argument("message", nargs="*", help="Chat message to route before dispatching to Hermes.")
    route.add_argument(
        "--source",
        choices=CHAT_SOURCES,
        default="generic",
        help="Source surface that received the chat message.",
    )
    route.add_argument("--limit", type=int, default=3, help="Maximum catalog recommendations to include.")
    route.add_argument(
        "--skill-policy-json",
        help="Agent-facing OMH-first skill governance policy JSON; native Hermes skills remain recommendations.",
    )
    route.add_argument(
        "--skill-policy-file",
        help="Path to an agent-facing OMH-first skill governance policy JSON object.",
    )
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
    route.add_argument(
        "--summary",
        action="store_true",
        help="Print a compact human-readable route summary. This is the default.",
    )
    route.add_argument(
        "--json",
        action="store_true",
        help="Print the full machine-readable JSON route payload.",
    )
    route.set_defaults(func=cmd_chat_route)

    route_hint = chat_sub.add_parser(
        "route-hint",
        help="Print a lightweight OMH workflow hint card without recording routing or execution evidence.",
    )
    route_hint.add_argument("message", nargs="*", help="Chat message to preview before a workflow is selected.")
    route_hint.add_argument(
        "--source",
        choices=CHAT_SOURCES,
        default="generic",
        help="Source surface that received the chat message.",
    )
    route_hint.add_argument("--stdin", action="store_true", help="Read the raw chat message from stdin.")
    route_hint.add_argument(
        "--event-json",
        default=None,
        help="Read a Slack/Discord/Hermes-like JSON event from this path, or '-' for stdin.",
    )
    route_hint.add_argument("--source-event-id", default="", help="Optional source message/event id to expose as metadata.")
    route_hint.add_argument("--channel-ref", default="", help="Optional channel reference to expose as metadata.")
    route_hint.add_argument("--user-ref", default="", help="Optional user reference to expose as metadata.")
    route_hint.add_argument("--max-hints", type=int, default=2, help="Maximum route hints to include.")
    route_hint.add_argument(
        "--prompt-context",
        action="store_true",
        help="Also include the compact plugin-style prompt context string for wrappers that inject context manually.",
    )
    route_hint.add_argument(
        "--summary",
        action="store_true",
        help="Print a compact human-readable route-hint summary. This is the default.",
    )
    route_hint.add_argument(
        "--json",
        action="store_true",
        help="Print the full machine-readable JSON route-hint payload.",
    )
    route_hint.set_defaults(func=cmd_chat_route_hint)

    interact = chat_sub.add_parser("interact", help="Build the wrapper/Hermes interaction card for a chat message.")
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
        "--skill-policy-json",
        help="Agent-facing OMH-first skill governance policy JSON; native Hermes skills remain recommendations.",
    )
    interact.add_argument(
        "--skill-policy-file",
        help="Path to an agent-facing OMH-first skill governance policy JSON object.",
    )
    interact.add_argument(
        "--executor",
        type=canonical_executor_profile,
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
    interact.add_argument(
        "--summary",
        action="store_true",
        help="Print a compact human-readable operator summary. This is the default.",
    )
    interact.add_argument(
        "--json",
        action="store_true",
        help="Print the full machine-readable JSON envelope.",
    )
    _add_render_profile_option(interact)
    _add_target_metadata_options(interact)
    _add_platform_context_options(interact)
    interact.set_defaults(func=cmd_chat_interact)

    native_command = chat_sub.add_parser("native-command", help="Print the platform-native OMH command registration contract.")
    native_command.add_argument(
        "--source",
        choices=NATIVE_COMMAND_SOURCES,
        default="generic",
        help="Target messenger or Hermes surface for the command manifest.",
    )
    native_command.set_defaults(func=cmd_chat_native_command)

    codex_progress = chat_sub.add_parser(
        "codex-progress",
        help="Summarize raw Codex JSONL or process output into compact chat-safe progress text.",
    )
    codex_progress.add_argument("--jsonl", default=None, help="Path to observed Codex JSONL or process output.")
    codex_progress.add_argument("--stdin", action="store_true", help="Read observed Codex JSONL or process output from stdin.")
    codex_progress.add_argument("--evidence-ref", action="append", help="Evidence reference for the observed log/source.")
    codex_progress.set_defaults(func=cmd_chat_codex_progress)

    codex_review = chat_sub.add_parser(
        "codex-review",
        help="Summarize observed Codex review context without raw logs or hidden reasoning.",
    )
    codex_review.add_argument("--external-session-ref", default="", help="Observed Codex thread/session reference from the wrapper.")
    codex_review.add_argument("--codex-session-ref", default="", help="Observed Codex session id suitable for resume contracts.")
    codex_review.add_argument("--codex-thread-ref", default="", help="Observed Codex thread/conversation reference when distinct from the session id.")
    codex_review.add_argument("--codex-log-jsonl", default=None, help="Observed Codex JSONL/process output to summarize; raw events are not echoed.")
    codex_review.add_argument("--codex-log-ref", default="", help="Evidence reference for the observed Codex log source.")
    codex_review.add_argument("--evidence-ref", action="append", help="Evidence reference for the observed review/session/log/source.")
    _add_codex_review_options(codex_review)
    codex_review.set_defaults(func=cmd_chat_codex_review)

    codex_followup = chat_sub.add_parser(
        "codex-followup",
        help="Summarize active Codex progress and recommend safe handling for a new prompt.",
    )
    codex_followup.add_argument("message", nargs="*", help="New user prompt to handle without echoing raw text in the result.")
    codex_followup.add_argument("--stdin", action="store_true", help="Read the new user prompt from stdin.")
    codex_followup.add_argument("--event-json", default=None, help="Read a Slack/Discord/Hermes-like JSON event for the new prompt.")
    codex_followup.add_argument("--session-id", default="", help="Existing wrapper session id that may already have observed Codex metadata.")
    codex_followup.add_argument("--same-goal", action="store_true", help="Wrapper-observed assertion that the new prompt belongs to the same goal.")
    codex_followup.add_argument("--external-session-ref", default="", help="Observed Codex thread/session reference from the wrapper.")
    codex_followup.add_argument("--codex-session-ref", default="", help="Observed Codex session id suitable for resume contracts.")
    codex_followup.add_argument("--codex-thread-ref", default="", help="Observed Codex thread/conversation reference when distinct from the session id.")
    codex_followup.add_argument("--codex-log-jsonl", default=None, help="Observed Codex JSONL/process output to summarize; raw events are not echoed.")
    codex_followup.add_argument("--codex-log-ref", default="", help="Evidence reference for the observed Codex log source.")
    codex_followup.add_argument("--evidence-ref", action="append", help="Evidence reference for the observed session/log/source.")
    _add_codex_review_options(codex_followup)
    codex_followup.set_defaults(func=cmd_chat_codex_followup)

    route_questions = chat_sub.add_parser(
        "route-questions",
        help="Export the shipped routing corpora as typed route questions, and score answers against them.",
    )
    route_questions_sub = route_questions.add_subparsers(dest="route_questions_command", required=True)

    route_questions_export = route_questions_sub.add_parser(
        "export",
        help="Write both shipped routing corpora as route_question/v1 items with their expected answers.",
    )
    route_questions_export.add_argument(
        "--source",
        choices=CHAT_SOURCES,
        default="discord",
        help="Source surface the corpora are routed as; the shipped corpora are measured on discord.",
    )
    route_questions_export.add_argument(
        "--limit",
        type=int,
        default=3,
        help=(
            "Maximum candidate workflows carried into a question built from the router's "
            "recommendations. It does not cut a question built from an undecidable route's "
            "candidate handoff, which is the one a live route asks; leave it at 3 so those "
            "match. An answer recorded against a shortlist cut differently, such as a "
            "route-hint question's two candidates, still joins by message and is reported "
            "with digest_match false."
        ),
    )
    route_questions_export.add_argument("--output", default=None, help="Write the full corpus JSON to this path.")
    route_questions_export.add_argument(
        "--json",
        action="store_true",
        help="Print the full corpus to stdout instead of a summary.",
    )
    route_questions_export.set_defaults(func=cmd_chat_route_questions_export)

    route_questions_score = route_questions_sub.add_parser(
        "score",
        help="Score answer rows against an exported corpus; the deterministic arm is always included.",
    )
    route_questions_score.add_argument("--corpus", required=True, help="Path to an exported routing_question_corpus/v1 file.")
    route_questions_score.add_argument(
        "--answers",
        default=None,
        help="JSONL file of routing_question_answers/v1 rows, or a directory of route_question_answer/v1 records.",
    )
    route_questions_score.add_argument(
        "--fits-dispatch",
        type=float,
        default=None,
        help="Override the fit level at which an answer set counts as a dispatch.",
    )
    route_questions_score.add_argument(
        "--fits-clarify",
        type=float,
        default=None,
        help="Override the fit level at which an answer set counts as a clarification.",
    )
    route_questions_score.add_argument("--output", default=None, help="Write the full score report JSON to this path.")
    route_questions_score.add_argument(
        "--json",
        action="store_true",
        help="Print the full score report to stdout instead of a summary.",
    )
    route_questions_score.set_defaults(func=cmd_chat_route_questions_score)

    route_questions_report = route_questions_sub.add_parser(
        "report",
        help=(
            "Join recorded route answers to the routes `omh chat route --record` recorded, by message hash, "
            "and report decline, invalid-answer, and agreement rates plus a per-turn cost estimate."
        ),
    )
    route_questions_report.add_argument(
        "--answers",
        default=None,
        help="Directory of route_question_answer/v1 records; defaults to this OMH home's runtime/route-questions.",
    )
    route_questions_report.add_argument(
        "--runs",
        default=None,
        help="Directory of recorded runs holding routing.json; defaults to this OMH home's runtime/runs.",
    )
    route_questions_report.add_argument(
        "--sessions",
        default=None,
        help="Directory of wrapper sessions whose events.jsonl carry live route questions; defaults to this OMH home's.",
    )
    route_questions_report.add_argument(
        "--since",
        default=None,
        help="ISO-8601 UTC lower bound for both sides; omitted, the router source's mtime; empty for every record.",
    )
    route_questions_report.add_argument(
        "--model",
        default="",
        help="Price the declared turn shape at this model's list price; omitted, the cost is reported unpriced.",
    )
    route_questions_report.add_argument("--output", default=None, help="Write the full report JSON to this path.")
    route_questions_report.add_argument(
        "--json",
        action="store_true",
        help="Print the full report to stdout instead of a summary.",
    )
    route_questions_report.set_defaults(func=cmd_chat_route_questions_report)

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
    _add_render_profile_option(session_start)
    session_start.add_argument("--executor", type=canonical_executor_profile, choices=CODING_EXECUTOR_TARGETS, default=None)
    _add_target_metadata_options(session_start)
    _add_platform_context_options(session_start)
    session_start.set_defaults(func=cmd_chat_session_start)

    # Every chat session subcommand below reaches a guarded session.json write,
    # so each carries the same two guard flags: the guarantee is "the wrapper
    # submits the revision it rendered", and it is unreachable from a surface
    # that cannot pass one.
    session_accept = session_sub.add_parser("accept-plan")
    session_accept.add_argument("session_id")
    add_revision_guard_arguments(session_accept)
    session_accept.set_defaults(func=cmd_chat_session_decision, decision="accept")

    session_revise = session_sub.add_parser("revise-plan")
    session_revise.add_argument("session_id")
    add_revision_guard_arguments(session_revise)
    session_revise.set_defaults(func=cmd_chat_session_decision, decision="revise")

    session_cancel = session_sub.add_parser("cancel")
    session_cancel.add_argument("session_id")
    add_revision_guard_arguments(session_cancel)
    session_cancel.set_defaults(func=cmd_chat_session_decision, decision="cancel")

    session_select = session_sub.add_parser("select-executor")
    session_select.add_argument("session_id")
    session_select.add_argument("executor", type=canonical_executor_profile, choices=tuple(value for value in CODING_EXECUTOR_TARGETS if value != "choose"))
    add_revision_guard_arguments(session_select)
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
    session_prepare.add_argument("--executor", type=canonical_executor_profile, choices=tuple(value for value in CODING_EXECUTOR_TARGETS if value != "choose"), default=None)
    session_prepare.add_argument(
        "--context-pack",
        default=None,
        help="Optional handoff_context_pack/v1 JSON to attach to the prepared executor prompt when conflict-free.",
    )
    session_prepare.add_argument(
        "--retarget",
        action="store_true",
        help=(
            "Move the already-accepted plan to the --executor owner without replanning it. Preserves scope, "
            "criteria, and verification, and reports the owner-specific and capability differences."
        ),
    )
    add_revision_guard_arguments(session_prepare)
    session_prepare.set_defaults(func=cmd_chat_session_prepare_handoff)

    session_status = session_sub.add_parser("status")
    session_status.add_argument("session_id")
    session_status.set_defaults(func=cmd_chat_session_status)

    session_artifacts = session_sub.add_parser(
        "artifacts",
        help=(
            "List the copyable work artifacts for one session under stable ids, or print the exact text of "
            "one with --artifact-id. Prepared metadata only; copying is not dispatch or evidence."
        ),
    )
    session_artifacts.add_argument("session_id")
    session_artifacts.add_argument(
        "--artifact-id",
        default="",
        help="Return the exact text of one listed artifact instead of the id listing.",
    )
    session_artifacts.set_defaults(func=cmd_chat_session_artifacts)

    mission_control = session_sub.add_parser(
        "mission-control",
        help="Show the executor-neutral task journey, recovery safety, and merge-evidence boundary for one session.",
    )
    mission_control.add_argument("session_id")
    mission_control.set_defaults(func=cmd_chat_session_mission_control)

    session_open_executor = session_sub.add_parser("open-executor")
    session_open_executor.add_argument("session_id")
    session_open_executor.add_argument(
        "--observed",
        action="store_true",
        help="Record that the wrapper observed opening or dispatching to the selected executor session.",
    )
    session_open_executor.add_argument("--external-session-ref", default="")
    session_open_executor.add_argument("--evidence-ref", action="append")
    session_open_executor.add_argument("--summary", default="")
    _add_codex_observation_options(session_open_executor)
    session_open_executor.set_defaults(func=cmd_chat_session_open_executor)

    session_attach_executor = session_sub.add_parser("attach-executor")
    session_attach_executor.add_argument("session_id")
    session_attach_executor.add_argument("--external-session-ref", required=True)
    session_attach_executor.add_argument("--evidence-ref", action="append")
    session_attach_executor.add_argument("--summary", default="")
    _add_codex_observation_options(session_attach_executor)
    session_attach_executor.set_defaults(func=cmd_chat_session_attach_executor)

    session_record_executor = session_sub.add_parser("record-executor")
    session_record_executor.add_argument("session_id")
    session_record_executor.add_argument("--result", choices=EXECUTOR_SESSION_OBSERVED_RESULTS, required=True)
    session_record_executor.add_argument("--evidence-ref", action="append")
    session_record_executor.add_argument("--summary", default="")
    session_record_executor.add_argument("--codex-log-jsonl", default=None, help="Observed Codex JSONL/process output to summarize; raw events are not echoed.")
    session_record_executor.add_argument("--codex-log-ref", default="", help="Evidence reference for the observed Codex log source.")
    session_record_executor.set_defaults(func=cmd_chat_session_record_executor)

    session_request_verification = session_sub.add_parser("request-verification")
    session_request_verification.add_argument("session_id")
    session_request_verification.add_argument("--evidence-ref", action="append")
    session_request_verification.add_argument("--summary", default="")
    session_request_verification.set_defaults(func=cmd_chat_session_request_verification)

    session_show = session_sub.add_parser("show")
    session_show.add_argument("session_id")
    session_show.set_defaults(func=cmd_chat_session_show)

    session_list = session_sub.add_parser("list")
    session_list.set_defaults(func=cmd_chat_session_list)
