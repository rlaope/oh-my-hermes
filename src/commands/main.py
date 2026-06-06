from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import __version__
from ..ingress import CHAT_SOURCES, extract_message_text, extract_source_metadata
from ..routing.chat import CONFIDENCE_LEVELS, public_route_payload, route_chat_message, routing_record_payload
from ..coding_delegation import (
    CODING_EXECUTOR_TARGETS,
    build_coding_delegation_payload,
    coding_delegation_record_payload,
)
from ..wrapper.lifecycle import (
    CodingLifecycleError,
    record_codex_dispatch,
    record_codex_result,
    record_codex_verification,
    report_codex_delegation_lifecycle,
    start_codex_delegation_lifecycle,
)
from ..config_adapter import ensure_external_dir, read_config, remove_external_dir, write_config
from ..demo import DEFAULT_ORCHESTRATION_MESSAGE, build_orchestration_demo
from ..doctor import doctor_ok, run_doctor
from ..hashutil import sha256_file
from ..hermes_planning import attach_plan_artifact_to_wrapper_contract, build_hermes_plan_payload, write_hermes_plan
from ..installer import OmhError, install_skill_pack, uninstall_skill_pack
from ..local_store import atomic_write_text
from ..manifest import read_manifest
from ..paths import resolve_paths
from ..playbooks import inspect_playbook, list_playbooks, recommend_playbooks
from ..probe import probe_capabilities
from ..routing.recommend import recommend_skills
from ..release import RELEASE_CHANNELS, package_url_for
from ..runtime.artifacts import (
    CI_STATUSES,
    DELEGATION_RESULTS,
    MERGE_STATUSES,
    PRIVACY_MODES,
    REVIEW_STATUSES,
    RUN_STATUSES,
    create_prepared_coding_delegation_run,
    create_run,
    export_runtime,
    list_runs,
    read_state,
    read_state_result,
    show_run,
    summarize_delegated_coding_status,
    update_state,
    validate_runtime,
    write_ci_record,
    write_coding_delegation,
    write_delegation,
    write_merge_record,
    write_review_record,
    write_routing_decision,
    write_wrapper_contract,
)
from ..skills.render import workflow_reference_markdown, workflow_reference_payload
from ..skills.validation import harness_inspection_payload, harness_summary_payload, validate_catalog_contract
from ..skill_pack import builtin_harnesses, builtin_definitions
from ..snippet import WORKSPACE_SNIPPET
from ..workflow_state import (
    LIFECYCLE_OUTCOMES,
    WorkflowStateError,
    clear_workflow_state,
    finish_workflow_state,
    list_workflow_states,
    start_workflow_state,
)
from ..wrapper.contract import INTERACTION_MODES, build_chat_interaction_payload, build_chat_status_interaction
from ..wrapper.sessions import (
    WrapperSessionError,
    build_wrapper_session_status,
    create_or_resume_wrapper_session,
    list_wrapper_sessions,
    prepare_wrapper_session_handoff,
    record_plan_decision,
    show_wrapper_session,
)


def _paths(args: argparse.Namespace):
    return resolve_paths(args.omh_home, args.hermes_home)


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def cmd_install(args: argparse.Namespace) -> int:
    _print_json(_install_result(args))
    return 0


def _install_result(args: argparse.Namespace) -> dict[str, object]:
    paths = _paths(args)
    try:
        release = package_url_for(args.channel, args.version or "", args.package_url or "")
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if args.channel == "local" and not (args.from_skills_dir or args.source):
        raise OmhError("local channel requires --from-skills-dir or --source")
    source_dir = Path(args.from_skills_dir or args.source).expanduser().resolve() if (args.from_skills_dir or args.source) else None
    source = str(source_dir) if source_dir else "builtin"
    result = install_skill_pack(paths, source=source, source_dir=source_dir, force=args.force, dry_run=args.dry_run)
    result.update({"release_channel": release.channel, "release_version": release.version, "release_package_url": release.package_url})
    if not args.dry_run:
        update_state(
            paths,
            {
                "package": "oh-my-hermes-agent",
                "version": __version__,
                "manifest_path": str(paths.manifest_path),
                "manifest_sha256": sha256_file(paths.manifest_path),
                "source": source,
                "release_channel": release.channel,
                "release_version": release.version,
                "release_package_url": release.package_url,
                "installed_skills": len(result.get("skills", [])),
                "skills_dir": str(paths.skills_dir),
            },
        )
    return result


def cmd_update(args: argparse.Namespace) -> int:
    return cmd_install(args)


def cmd_convert(args: argparse.Namespace) -> int:
    args.source = args.from_skills_dir
    args.channel = "local"
    args.version = ""
    args.package_url = ""
    return cmd_install(args)


def cmd_apply(args: argparse.Namespace) -> int:
    _print_json(_apply_result(args))
    return 0


def _apply_result(args: argparse.Namespace) -> dict[str, object]:
    paths = _paths(args)
    current = read_config(paths.hermes_config_path)
    try:
        change = ensure_external_dir(current, paths.skills_dir)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if not args.dry_run and change.changed:
        write_config(paths.hermes_config_path, change.text)
    if not args.dry_run:
        update_state(
            paths,
            {
                "hermes_config_path": str(paths.hermes_config_path),
                "last_applied_skills_dir": str(paths.skills_dir),
                "external_dir_registered": str(paths.skills_dir) in read_config(paths.hermes_config_path),
            },
        )
    return {"changed": change.changed, "message": change.message, "config": str(paths.hermes_config_path), "skills_dir": str(paths.skills_dir), "dry_run": args.dry_run}


def cmd_uninstall(args: argparse.Namespace) -> int:
    paths = _paths(args)
    current = read_config(paths.hermes_config_path)
    try:
        change = remove_external_dir(current, paths.skills_dir)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if not args.dry_run and change.changed:
        write_config(paths.hermes_config_path, change.text)
    result = uninstall_skill_pack(paths, remove_files=args.remove_files and not args.dry_run)
    result.update({"config_changed": change.changed, "dry_run": args.dry_run})
    _print_json(result)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    manifest = read_manifest(_paths(args).manifest_path)
    _print_json(manifest or {"skills": [], "message": "not installed"})
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    payload = _doctor_result(args)
    _print_json(payload)
    return 0 if payload["ok"] else 1


def _doctor_result(args: argparse.Namespace) -> dict[str, object]:
    paths = _paths(args)
    checks = run_doctor(paths)
    runtime_writable = any(check.name == "runtime_artifacts" and check.ok for check in checks)
    runtime_state_readable = not any(check.name == "runtime_state" and not check.ok for check in checks)
    if runtime_writable and runtime_state_readable:
        update_state(
            paths,
            {
                "last_doctor": {
                    "ok": doctor_ok(checks),
                    "checks": {check.name: check.ok for check in checks},
                }
            },
        )
    return {"ok": doctor_ok(checks), "checks": [check.__dict__ for check in checks]}


def cmd_setup(args: argparse.Namespace) -> int:
    steps: dict[str, object] = {"install": _install_result(args)}
    if args.skip_apply:
        steps["apply"] = {"skipped": True, "message": "Skipped Hermes config registration because --skip-apply was set."}
    else:
        steps["apply"] = _apply_result(args)

    if args.skip_doctor:
        doctor_payload: dict[str, object] = {"ok": True, "skipped": True, "message": "Skipped doctor check because --skip-doctor was set."}
    elif args.dry_run:
        doctor_payload = {"ok": True, "skipped": True, "message": "Skipped doctor check because setup --dry-run does not write install artifacts."}
    else:
        doctor_payload = _doctor_result(args)
    steps["doctor"] = doctor_payload

    ok = bool(doctor_payload["ok"])
    if not args.dry_run:
        update_state(
            _paths(args),
            {
                "last_setup": {
                    "ok": ok,
                    "apply_skipped": bool(args.skip_apply),
                    "doctor_skipped": bool(args.skip_doctor),
                }
            },
        )
    _print_json({"ok": ok, "steps": steps, "dry_run": args.dry_run})
    return 0 if ok else 1


def cmd_recommend(args: argparse.Namespace) -> int:
    if args.limit < 1:
        raise OmhError("recommend --limit must be at least 1")
    query = " ".join(args.task).strip()
    if not query:
        raise OmhError("recommend requires a task description")
    _print_json({"query": query, "recommendations": recommend_skills(query, limit=args.limit)})
    return 0


def cmd_playbook_list(args: argparse.Namespace) -> int:
    _print_json(list_playbooks())
    return 0


def cmd_playbook_inspect(args: argparse.Namespace) -> int:
    try:
        _print_json(inspect_playbook(args.id))
    except KeyError as exc:
        raise OmhError(f"unknown playbook: {args.id}") from exc
    return 0


def cmd_playbook_recommend(args: argparse.Namespace) -> int:
    query = " ".join(args.task).strip()
    try:
        _print_json(recommend_playbooks(query, limit=args.limit))
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return 0


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
                executor_target=args.executor,
                source_metadata=source_metadata,
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
        )
    except FileNotFoundError as exc:
        raise OmhError(f"wrapper session not found: {args.session_id}") from exc
    except (OSError, json.JSONDecodeError, ValueError, WrapperSessionError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
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


def cmd_coding_delegate(args: argparse.Namespace) -> int:
    try:
        source_metadata: dict[str, str] = {}
        if args.event_json:
            raw = (
                sys.stdin.read()
                if args.event_json == "-"
                else Path(args.event_json).expanduser().read_text(encoding="utf-8")
            )
            event = json.loads(raw)
            message = extract_message_text(event)
            source_metadata = extract_source_metadata(event)
        elif args.stdin:
            message = sys.stdin.read().strip()
        else:
            message = " ".join(args.message).strip()
        source_metadata.update(_explicit_source_metadata(args))
        payload = build_coding_delegation_payload(
            message,
            source=args.source,
            limit=args.limit,
            include_message=args.include_message,
            source_metadata=source_metadata,
            executor_target=args.executor,
        )
        if args.record:
            delegation = payload["delegation"]
            if not isinstance(delegation, dict):
                raise OmhError("coding delegation payload is missing delegation")
            paths = _paths(args)
            run = create_prepared_coding_delegation_run(
                paths,
                {
                    "skill": str(delegation["recommended_workflow"]),
                    "harness": str(delegation["recommended_harness"]),
                    "trigger": f"coding:{args.source}:{delegation['action']}",
                    "privacy": "metadata_only",
                    "inputs_summary": f"{args.source} coding delegation request; message_length={len(message)}",
                    "outputs_summary": f"prepared {delegation['action']} for {delegation['recommended_workflow']}",
                    "verification_summary": "prepared_not_observed; executor work is not observed by omh",
                },
            )
            record = write_coding_delegation(
                paths.runtime_runs_dir / run["run_id"],
                coding_delegation_record_payload(payload, message, source_metadata=source_metadata),
            )
            payload["runtime"] = {"run": run, "coding_delegation": record}
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_coding_lifecycle_start(args: argparse.Namespace) -> int:
    if not args.record:
        raise OmhError("coding lifecycle start requires --record")
    try:
        event_or_message, source_metadata = _chat_input_and_metadata(args)
        message = extract_message_text(event_or_message)
        payload = start_codex_delegation_lifecycle(
            _paths(args),
            message,
            source=args.source,
            source_metadata=source_metadata,
            limit=args.limit,
            include_message=args.include_message,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_coding_lifecycle_dispatch(args: argparse.Namespace) -> int:
    try:
        _print_json(record_codex_dispatch(_paths(args), args.run_id))
    except FileNotFoundError as exc:
        raise OmhError(f"runtime run not found: {args.run_id}") from exc
    except CodingLifecycleError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_coding_lifecycle_result(args: argparse.Namespace) -> int:
    participants = [item.strip() for item in (args.participants or "").split(",") if item.strip()]
    try:
        _print_json(
            record_codex_result(
                _paths(args),
                args.run_id,
                result=args.result,
                participants=participants or ["codex"],
                evidence_refs=args.evidence_ref or [],
            )
        )
    except FileNotFoundError as exc:
        raise OmhError(f"runtime run not found: {args.run_id}") from exc
    except CodingLifecycleError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_coding_lifecycle_verify(args: argparse.Namespace) -> int:
    try:
        _print_json(
            record_codex_verification(
                _paths(args),
                args.run_id,
                completion_status=args.completion_status,
                gaps=args.gap or [],
            )
        )
    except FileNotFoundError as exc:
        raise OmhError(f"runtime run not found: {args.run_id}") from exc
    except CodingLifecycleError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_coding_lifecycle_report(args: argparse.Namespace) -> int:
    try:
        _print_json(report_codex_delegation_lifecycle(_paths(args), args.run_id))
    except FileNotFoundError as exc:
        raise OmhError(f"runtime run not found: {args.run_id}") from exc
    return 0


def cmd_hermes_plan(args: argparse.Namespace) -> int:
    try:
        source_metadata: dict[str, str] = {}
        if args.event_json:
            raw = (
                sys.stdin.read()
                if args.event_json == "-"
                else Path(args.event_json).expanduser().read_text(encoding="utf-8")
            )
            event = json.loads(raw)
            message = extract_message_text(event)
            source_metadata = extract_source_metadata(event)
        elif args.stdin:
            message = sys.stdin.read().strip()
        else:
            message = " ".join(args.message).strip()
        source_metadata.update(_explicit_source_metadata(args))
        payload = build_hermes_plan_payload(
            message,
            source=args.source,
            limit=args.limit,
            source_metadata=source_metadata,
        )
        if args.record:
            artifact = write_hermes_plan(_paths(args), payload)
            payload["artifact"] = artifact
            attach_plan_artifact_to_wrapper_contract(payload, artifact)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def _explicit_source_metadata(args: argparse.Namespace) -> dict[str, str]:
    return {
        key: value
        for key, value in {
            "source_event_id": args.source_event_id,
            "channel_ref": args.channel_ref,
            "user_ref": args.user_ref,
        }.items()
        if value
    }


def _chat_input_and_metadata(args: argparse.Namespace) -> tuple[dict[str, object] | str, dict[str, str]]:
    try:
        if args.event_json:
            raw = (
                sys.stdin.read()
                if args.event_json == "-"
                else Path(args.event_json).expanduser().read_text(encoding="utf-8")
            )
            event = json.loads(raw)
            if not isinstance(event, dict):
                raise ValueError("chat event must be an object")
            metadata = extract_source_metadata(event)
            metadata.update(_explicit_source_metadata(args))
            return event, metadata
        if args.stdin:
            return sys.stdin.read().strip(), _explicit_source_metadata(args)
        return " ".join(args.message).strip(), _explicit_source_metadata(args)
    except (OSError, json.JSONDecodeError, ValueError):
        raise


def _chat_message(args: argparse.Namespace) -> str:
    try:
        if args.event_json:
            raw = (
                sys.stdin.read()
                if args.event_json == "-"
                else Path(args.event_json).expanduser().read_text(encoding="utf-8")
            )
            return extract_message_text(json.loads(raw))
        if args.stdin:
            return sys.stdin.read().strip()
        return " ".join(args.message).strip()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc


def _valid_skill_names() -> set[str]:
    return {definition.name for definition in builtin_definitions()}


def _valid_harness_names() -> set[str]:
    return {harness.name for harness in builtin_harnesses()}


def _validate_runtime_names(skill: str, harness: str) -> None:
    if skill not in _valid_skill_names():
        raise OmhError(f"unknown skill for runtime record: {skill}")
    if harness not in _valid_harness_names():
        raise OmhError(f"unknown harness for runtime record: {harness}")


def cmd_runtime_status(args: argparse.Namespace) -> int:
    paths = _paths(args)
    state, state_error = read_state_result(paths)
    _print_json(
        {
            "schema_version": 1,
            "runtime_dir": str(paths.runtime_dir),
            "state_path": str(paths.runtime_state_path),
            "runs_dir": str(paths.runtime_runs_dir),
            "wrapper_sessions_dir": str(paths.runtime_wrapper_sessions_dir),
            "state": state,
            "state_error": state_error,
        }
    )
    return 0


def cmd_runtime_runs(args: argparse.Namespace) -> int:
    _print_json({"runs": list_runs(_paths(args))})
    return 0


def cmd_runtime_show(args: argparse.Namespace) -> int:
    try:
        _print_json(show_run(_paths(args), args.run_id))
    except FileNotFoundError as exc:
        raise OmhError(f"runtime run not found: {args.run_id}") from exc
    return 0


def cmd_runtime_delegation_status(args: argparse.Namespace) -> int:
    try:
        _print_json(summarize_delegated_coding_status(_paths(args), args.run_id))
    except FileNotFoundError as exc:
        raise OmhError(f"runtime run not found: {args.run_id}") from exc
    return 0


def cmd_runtime_record(args: argparse.Namespace) -> int:
    _validate_runtime_names(args.skill, args.harness)
    run = create_run(
        _paths(args),
        {
            "skill": args.skill,
            "harness": args.harness,
            "status": args.status,
            "trigger": args.trigger or "",
            "privacy": args.privacy,
            "inputs_summary": args.inputs_summary or "",
            "outputs_summary": args.outputs_summary or "",
            "verification_summary": args.verification_summary or "",
        },
    )
    _print_json({"run": run})
    return 0


def cmd_runtime_delegate(args: argparse.Namespace) -> int:
    paths = _paths(args)
    run_dir = paths.runtime_runs_dir / args.run_id
    if not (run_dir / "run.json").exists():
        raise OmhError(f"runtime run not found: {args.run_id}")
    observed = args.observed
    result = args.result
    if args.not_observed:
        observed = False
        result = result or "not_observed"
    elif observed:
        result = result or "completed"
    else:
        result = result or "not_available"
    participants = [item.strip() for item in (args.participants or "").split(",") if item.strip()]
    try:
        delegation = write_delegation(
            run_dir,
            {
                "requested": args.requested,
                "observed": observed,
                "participants": participants,
                "result": result,
                "evidence_refs": args.evidence_ref or [],
                "message": args.message or "",
            },
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"delegation": delegation})
    return 0


def cmd_runtime_wrapper(args: argparse.Namespace) -> int:
    paths = _paths(args)
    run_dir = paths.runtime_runs_dir / args.run_id
    if not (run_dir / "run.json").exists():
        raise OmhError(f"runtime run not found: {args.run_id}")
    try:
        wrapper = write_wrapper_contract(
            run_dir,
            {
                "prompt_dispatched": args.prompt_dispatched,
                "hermes_response_observed": args.response_observed,
                "verification_observed": args.verification_observed,
                "completion_status": args.completion_status,
                "unobserved_gaps": args.gap or [],
                "message": args.message or "",
            },
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"wrapper": wrapper})
    return 0


def cmd_runtime_review(args: argparse.Namespace) -> int:
    paths = _paths(args)
    run_dir = paths.runtime_runs_dir / args.run_id
    if not (run_dir / "run.json").exists():
        raise OmhError(f"runtime run not found: {args.run_id}")
    preflight = summarize_delegated_coding_status(paths, args.run_id)
    if args.status in {"passed", "not_required"} and preflight.get("next_action") != "record_review_evidence":
        raise OmhError(f"cannot record review {args.status} while next_action is {preflight.get('next_action')}")
    review_status = preflight.get("review", {})
    if args.status == "not_required" and isinstance(review_status, dict) and review_status.get("required"):
        raise OmhError("cannot mark required review as not_required")
    try:
        review = write_review_record(
            run_dir,
            {
                "status": args.status,
                "required": args.status != "not_required",
                "reviewer": args.reviewer or "",
                "evidence_refs": args.evidence_ref or [],
                "summary": args.summary or "",
            },
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"review": review, "status": summarize_delegated_coding_status(paths, args.run_id)})
    return 0


def cmd_runtime_ci(args: argparse.Namespace) -> int:
    paths = _paths(args)
    run_dir = paths.runtime_runs_dir / args.run_id
    if not (run_dir / "run.json").exists():
        raise OmhError(f"runtime run not found: {args.run_id}")
    preflight = summarize_delegated_coding_status(paths, args.run_id)
    if args.status == "passed" and preflight.get("next_action") != "record_ci_evidence":
        raise OmhError(f"cannot record passed CI while next_action is {preflight.get('next_action')}")
    ci_status = preflight.get("ci", {})
    if args.status == "not_required" and isinstance(ci_status, dict) and ci_status.get("required"):
        raise OmhError("cannot mark required CI as not_required")
    try:
        ci = write_ci_record(
            run_dir,
            {
                "status": args.status,
                "required": args.status != "not_required",
                "provider": args.provider or "",
                "checks": args.check or [],
                "evidence_refs": args.evidence_ref or [],
                "summary": args.summary or "",
            },
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"ci": ci, "status": summarize_delegated_coding_status(paths, args.run_id)})
    return 0


def cmd_runtime_merge(args: argparse.Namespace) -> int:
    paths = _paths(args)
    run_dir = paths.runtime_runs_dir / args.run_id
    if not (run_dir / "run.json").exists():
        raise OmhError(f"runtime run not found: {args.run_id}")
    selected_statuses = [
        status
        for status, selected in (
            ("ready", args.ready),
            ("merged", args.merged),
            ("blocked", args.blocked),
            (args.status, bool(args.status)),
        )
        if selected
    ]
    if len(selected_statuses) > 1:
        raise OmhError("runtime merge accepts only one of --ready, --merged, --blocked, or --status")
    status = selected_statuses[0] if selected_statuses else None
    if not status:
        raise OmhError("runtime merge requires --ready, --merged, --blocked, or --status")
    preflight = summarize_delegated_coding_status(paths, args.run_id)
    allowed_preflight = {
        "ready": {"record_merge_readiness", "report_merge_ready"},
        "merged": {"report_merge_ready"},
        "blocked": {"record_merge_readiness", "report_merge_ready"},
        "not_ready": {"record_merge_readiness", "report_merge_ready", "report_completion_with_evidence"},
        "not_observed": {"record_merge_readiness", "report_merge_ready", "report_completion_with_evidence"},
    }
    if status in allowed_preflight and preflight.get("next_action") not in allowed_preflight[status]:
        raise OmhError(f"cannot record merge {status} while next_action is {preflight.get('next_action')}")
    try:
        merge = write_merge_record(
            run_dir,
            {
                "status": status,
                "target_branch": args.target_branch or "",
                "merge_commit": args.merge_commit or "",
                "evidence_refs": args.evidence_ref or [],
                "summary": args.summary or "",
            },
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"merge": merge, "status": summarize_delegated_coding_status(paths, args.run_id)})
    return 0


def cmd_runtime_validate(args: argparse.Namespace) -> int:
    result = validate_runtime(_paths(args), args.run_id)
    _print_json(result)
    return 0 if result["ok"] else 1


def cmd_runtime_export(args: argparse.Namespace) -> int:
    _print_json(export_runtime(_paths(args), redacted=args.redacted))
    return 0


def cmd_snippet(args: argparse.Namespace) -> int:
    if args.dry_run or not args.output:
        print(WORKSPACE_SNIPPET.rstrip())
        return 0
    output = Path(args.output).expanduser().resolve()
    atomic_write_text(output, WORKSPACE_SNIPPET)
    _print_json({"written": str(output)})
    return 0


def cmd_docs_workflows(args: argparse.Namespace) -> int:
    if args.json:
        if args.check:
            raise OmhError("docs workflows --json cannot be combined with --check")
        if args.output:
            raise OmhError("docs workflows --json cannot be combined with --output")
        _print_json(workflow_reference_payload())
        return 0
    content = workflow_reference_markdown()
    output = Path(args.output).expanduser().resolve() if args.output else Path("docs/WORKFLOWS.md").resolve()
    if args.check:
        try:
            current = output.read_text(encoding="utf-8")
        except OSError as exc:
            raise OmhError(f"workflow docs check failed: {exc}") from exc
        if current != content:
            raise OmhError(f"workflow docs are stale: {output}")
        _print_json({"ok": True, "checked": str(output)})
        return 0
    if args.output:
        atomic_write_text(output, content)
        _print_json({"written": str(output)})
        return 0
    print(content.rstrip())
    return 0


def cmd_harness_list(args: argparse.Namespace) -> int:
    _print_json(harness_summary_payload())
    return 0


def cmd_harness_inspect(args: argparse.Namespace) -> int:
    try:
        _print_json(harness_inspection_payload(args.name))
    except KeyError as exc:
        raise OmhError(f"unknown harness: {args.name}") from exc
    return 0


def cmd_harness_validate(args: argparse.Namespace) -> int:
    result = validate_catalog_contract()
    _print_json(result)
    return 0 if result["ok"] else 1


def cmd_state_status(args: argparse.Namespace) -> int:
    paths = _paths(args)
    states, errors = list_workflow_states(paths)
    if args.workflow:
        states = [state for state in states if state.get("workflow") == args.workflow]
        errors = [error for error in errors if f"{args.workflow}-state.json" in error["path"]]
    active = [state for state in states if state.get("active")]
    _print_json(
        {
            "schema_version": 1,
            "state_dir": str(paths.workflow_state_dir),
            "states": states,
            "active": active,
            "errors": errors,
            "ok": not errors,
        }
    )
    return 0 if not errors else 1


def cmd_state_start(args: argparse.Namespace) -> int:
    try:
        state = start_workflow_state(_paths(args), args.workflow, args.note or "")
    except WorkflowStateError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"state": state})
    return 0


def cmd_state_finish(args: argparse.Namespace) -> int:
    try:
        state = finish_workflow_state(_paths(args), args.workflow, args.outcome, args.note or "")
    except WorkflowStateError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"state": state})
    return 0


def cmd_state_clear(args: argparse.Namespace) -> int:
    try:
        removed = clear_workflow_state(_paths(args), args.workflow)
    except WorkflowStateError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"removed": removed, "workflow": args.workflow})
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    _print_json(probe_capabilities(_paths(args)))
    return 0


def cmd_demo_orchestration(args: argparse.Namespace) -> int:
    message = " ".join(args.message).strip() or DEFAULT_ORCHESTRATION_MESSAGE
    try:
        _print_json(build_orchestration_demo(message, source=args.source, limit=args.limit))
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def _add_common_install_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--from-skills-dir", default=None, help="Import skills from a local skill directory.")
    p.add_argument("--source", default=None, help="Mockable local source directory for install/update.")
    p.add_argument("--channel", choices=RELEASE_CHANNELS, default="preview", help="Release channel metadata for this install/update.")
    p.add_argument("--version", default="", help="Stable release version such as 0.1.0 or v0.1.0.")
    p.add_argument("--package-url", default="", help="Explicit release archive URL for support and audit metadata.")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")


def _add_top_level_commands(sub) -> None:
    setup = sub.add_parser("setup")
    _add_common_install_options(setup)
    setup.add_argument("--skip-apply", action="store_true", help="Install skills without registering them in Hermes config.")
    setup.add_argument("--skip-doctor", action="store_true", help="Skip the final doctor check.")
    setup.set_defaults(func=cmd_setup)

    install = sub.add_parser("install")
    _add_common_install_options(install)
    install.set_defaults(func=cmd_install)

    update = sub.add_parser("update")
    _add_common_install_options(update)
    update.set_defaults(func=cmd_update)

    convert = sub.add_parser("convert")
    convert.add_argument("--from-skills-dir", required=True)
    convert.add_argument("--force", action="store_true")
    convert.add_argument("--dry-run", action="store_true")
    convert.set_defaults(func=cmd_convert)

    apply = sub.add_parser("apply")
    apply.add_argument("--dry-run", action="store_true")
    apply.set_defaults(func=cmd_apply)

    uninstall = sub.add_parser("uninstall")
    uninstall.add_argument("--remove-files", action="store_true")
    uninstall.add_argument("--dry-run", action="store_true")
    uninstall.set_defaults(func=cmd_uninstall)

    list_cmd = sub.add_parser("list")
    list_cmd.set_defaults(func=cmd_list)

    doctor = sub.add_parser("doctor")
    doctor.set_defaults(func=cmd_doctor)

    recommend = sub.add_parser("recommend")
    recommend.add_argument("task", nargs="+", help="Task description to map to OMHM workflow skills.")
    recommend.add_argument("--limit", type=int, default=5, help="Maximum recommendations to return.")
    recommend.set_defaults(func=cmd_recommend)

    snippet = sub.add_parser("snippet")
    snippet.add_argument("--dry-run", action="store_true")
    snippet.add_argument("--output", default=None)
    snippet.set_defaults(func=cmd_snippet)

    probe = sub.add_parser("probe")
    probe.set_defaults(func=cmd_probe)


def _add_docs_commands(sub) -> None:
    docs = sub.add_parser("docs")
    docs_sub = docs.add_subparsers(dest="docs_command", required=True)

    docs_workflows = docs_sub.add_parser("workflows")
    docs_workflows.add_argument("--output", default=None)
    docs_workflows.add_argument("--check", action="store_true")
    docs_workflows.add_argument("--json", action="store_true", help="Print machine-readable workflow and harness catalog metadata.")
    docs_workflows.set_defaults(func=cmd_docs_workflows)


def _add_harness_commands(sub) -> None:
    harness = sub.add_parser("harness")
    harness_sub = harness.add_subparsers(dest="harness_command", required=True)

    harness_list = harness_sub.add_parser("list")
    harness_list.set_defaults(func=cmd_harness_list)

    harness_inspect = harness_sub.add_parser("inspect")
    harness_inspect.add_argument("name")
    harness_inspect.set_defaults(func=cmd_harness_inspect)

    harness_validate = harness_sub.add_parser("validate")
    harness_validate.set_defaults(func=cmd_harness_validate)


def _add_playbook_commands(sub) -> None:
    playbook = sub.add_parser("playbook")
    playbook_sub = playbook.add_subparsers(dest="playbook_command", required=True)

    playbook_list = playbook_sub.add_parser("list")
    playbook_list.set_defaults(func=cmd_playbook_list)

    playbook_inspect = playbook_sub.add_parser("inspect")
    playbook_inspect.add_argument("id")
    playbook_inspect.set_defaults(func=cmd_playbook_inspect)

    playbook_recommend = playbook_sub.add_parser("recommend")
    playbook_recommend.add_argument("task", nargs="+", help="Natural-language request to map to an OMH playbook.")
    playbook_recommend.add_argument("--limit", type=int, default=3, help="Maximum playbooks to return.")
    playbook_recommend.set_defaults(func=cmd_playbook_recommend)


def _add_demo_commands(sub) -> None:
    demo = sub.add_parser("demo")
    demo_sub = demo.add_subparsers(dest="demo_command", required=True)

    orchestration = demo_sub.add_parser("orchestration")
    orchestration.add_argument(
        "message",
        nargs="*",
        help="Optional natural-language request for the deterministic orchestration demo.",
    )
    orchestration.add_argument("--source", choices=CHAT_SOURCES, default="discord")
    orchestration.add_argument("--limit", type=int, default=3)
    orchestration.set_defaults(func=cmd_demo_orchestration)


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
        default="codex",
        help="Executor target for delegate-mode handoff payloads.",
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
    session_prepare.set_defaults(func=cmd_chat_session_prepare_handoff)

    session_status = session_sub.add_parser("status")
    session_status.add_argument("session_id")
    session_status.set_defaults(func=cmd_chat_session_status)

    session_show = session_sub.add_parser("show")
    session_show.add_argument("session_id")
    session_show.set_defaults(func=cmd_chat_session_show)

    session_list = session_sub.add_parser("list")
    session_list.set_defaults(func=cmd_chat_session_list)


def _add_coding_commands(sub) -> None:
    coding = sub.add_parser("coding")
    coding_sub = coding.add_subparsers(dest="coding_command", required=True)

    delegate = coding_sub.add_parser("delegate")
    delegate.add_argument("message", nargs="*", help="Coding task description to prepare for executor delegation.")
    delegate.add_argument(
        "--source",
        choices=CHAT_SOURCES,
        default="generic",
        help="Source surface that received the coding request.",
    )
    delegate.add_argument("--limit", type=int, default=3, help="Maximum catalog recommendations to include.")
    delegate.add_argument(
        "--executor",
        choices=CODING_EXECUTOR_TARGETS,
        default="generic",
        help="Optional coding executor target for wrapper handoff payloads.",
    )
    delegate.add_argument("--stdin", action="store_true", help="Read the raw coding task from stdin.")
    delegate.add_argument(
        "--event-json",
        default=None,
        help="Read a Slack/Discord/Hermes-like JSON event from this path, or '-' for stdin.",
    )
    delegate.add_argument(
        "--include-message",
        action="store_true",
        help="Include raw message and expanded delegation prompt in stdout for non-logging wrappers.",
    )
    delegate.add_argument("--record", action="store_true", help="Record a metadata-only coding delegation artifact under .omh/runtime.")
    delegate.add_argument("--source-event-id", default="", help="Optional source message/event id to store as metadata.")
    delegate.add_argument("--channel-ref", default="", help="Optional channel reference to store as metadata.")
    delegate.add_argument("--user-ref", default="", help="Optional user reference to store as metadata.")
    delegate.set_defaults(func=cmd_coding_delegate)

    lifecycle = coding_sub.add_parser("lifecycle")
    lifecycle_sub = lifecycle.add_subparsers(dest="lifecycle_command", required=True)

    lifecycle_start = lifecycle_sub.add_parser("start")
    lifecycle_start.add_argument("message", nargs="*", help="Coding task description to prepare for Codex lifecycle tracking.")
    lifecycle_start.add_argument(
        "--source",
        choices=CHAT_SOURCES,
        default="generic",
        help="Source surface that received the coding request.",
    )
    lifecycle_start.add_argument("--limit", type=int, default=3, help="Maximum catalog recommendations to include.")
    lifecycle_start.add_argument("--executor", choices=("codex",), default="codex", help="Coding executor target.")
    lifecycle_start.add_argument("--record", action="store_true", help="Record a metadata-only prepared lifecycle run.")
    lifecycle_start.add_argument("--stdin", action="store_true", help="Read the raw coding task from stdin.")
    lifecycle_start.add_argument(
        "--event-json",
        default=None,
        help="Read a Slack/Discord/Hermes-like JSON event from this path, or '-' for stdin.",
    )
    lifecycle_start.add_argument(
        "--include-message",
        action="store_true",
        help="Include raw message and expanded executor prompt in stdout for immediate wrapper dispatch.",
    )
    lifecycle_start.add_argument("--source-event-id", default="", help="Optional source message/event id to store as metadata.")
    lifecycle_start.add_argument("--channel-ref", default="", help="Optional channel reference to store as metadata.")
    lifecycle_start.add_argument("--user-ref", default="", help="Optional user reference to store as metadata.")
    lifecycle_start.set_defaults(func=cmd_coding_lifecycle_start)

    lifecycle_dispatch = lifecycle_sub.add_parser("dispatch")
    lifecycle_dispatch.add_argument("--run", dest="run_id", required=True)
    lifecycle_dispatch.set_defaults(func=cmd_coding_lifecycle_dispatch)

    lifecycle_result = lifecycle_sub.add_parser("result")
    lifecycle_result.add_argument("--run", dest="run_id", required=True)
    lifecycle_result.add_argument("--result", choices=("completed", "blocked", "failed"), required=True)
    lifecycle_result.add_argument("--participants", default="codex")
    lifecycle_result.add_argument("--evidence-ref", action="append")
    lifecycle_result.set_defaults(func=cmd_coding_lifecycle_result)

    lifecycle_verify = lifecycle_sub.add_parser("verify")
    lifecycle_verify.add_argument("--run", dest="run_id", required=True)
    lifecycle_verify.add_argument("--completion-status", choices=("completed", "blocked", "failed", "unknown"), default="completed")
    lifecycle_verify.add_argument("--gap", action="append")
    lifecycle_verify.set_defaults(func=cmd_coding_lifecycle_verify)

    lifecycle_report = lifecycle_sub.add_parser("report")
    lifecycle_report.add_argument("--run", dest="run_id", required=True)
    lifecycle_report.set_defaults(func=cmd_coding_lifecycle_report)


def _add_hermes_commands(sub) -> None:
    hermes = sub.add_parser("hermes")
    hermes_sub = hermes.add_subparsers(dest="hermes_command", required=True)

    plan = hermes_sub.add_parser("plan")
    plan.add_argument("message", nargs="*", help="Task description to turn into a Hermes-facing planning scaffold.")
    plan.add_argument(
        "--source",
        choices=CHAT_SOURCES,
        default="generic",
        help="Source surface that received the planning request.",
    )
    plan.add_argument("--limit", type=int, default=3, help="Maximum catalog recommendations to include.")
    plan.add_argument("--stdin", action="store_true", help="Read the raw planning task from stdin.")
    plan.add_argument(
        "--event-json",
        default=None,
        help="Read a Slack/Discord/Hermes-like JSON event from this path, or '-' for stdin.",
    )
    plan.add_argument("--record", action="store_true", help="Write the plan under .hermes/plans.")
    plan.add_argument("--source-event-id", default="", help="Optional source message/event id to store as metadata.")
    plan.add_argument("--channel-ref", default="", help="Optional channel reference to store as metadata.")
    plan.add_argument("--user-ref", default="", help="Optional user reference to store as metadata.")
    plan.set_defaults(func=cmd_hermes_plan)


def _add_runtime_commands(sub) -> None:
    runtime = sub.add_parser("runtime")
    runtime_sub = runtime.add_subparsers(dest="runtime_command", required=True)

    runtime_status = runtime_sub.add_parser("status")
    runtime_status.set_defaults(func=cmd_runtime_status)

    runtime_runs = runtime_sub.add_parser("runs")
    runtime_runs.set_defaults(func=cmd_runtime_runs)

    runtime_show = runtime_sub.add_parser("show")
    runtime_show.add_argument("run_id")
    runtime_show.set_defaults(func=cmd_runtime_show)

    runtime_delegation_status = runtime_sub.add_parser("delegation-status")
    runtime_delegation_status.add_argument("--run", dest="run_id", required=True)
    runtime_delegation_status.set_defaults(func=cmd_runtime_delegation_status)

    runtime_record = runtime_sub.add_parser("record")
    runtime_record.add_argument("--skill", required=True)
    runtime_record.add_argument("--harness", required=True)
    runtime_record.add_argument("--status", choices=RUN_STATUSES, default="unknown")
    runtime_record.add_argument("--trigger", default="")
    runtime_record.add_argument("--privacy", choices=PRIVACY_MODES, default="metadata_only")
    runtime_record.add_argument("--inputs-summary", default="")
    runtime_record.add_argument("--outputs-summary", default="")
    runtime_record.add_argument("--verification-summary", default="")
    runtime_record.set_defaults(func=cmd_runtime_record)

    runtime_delegate = runtime_sub.add_parser("delegate")
    runtime_delegate.add_argument("--run", dest="run_id", required=True)
    runtime_delegate.add_argument("--requested", action="store_true")
    observation = runtime_delegate.add_mutually_exclusive_group()
    observation.add_argument("--observed", action="store_true")
    observation.add_argument("--not-observed", action="store_true")
    runtime_delegate.add_argument("--result", choices=DELEGATION_RESULTS, default=None)
    runtime_delegate.add_argument("--participants", default="")
    runtime_delegate.add_argument("--evidence-ref", action="append")
    runtime_delegate.add_argument("--message", default="")
    runtime_delegate.set_defaults(func=cmd_runtime_delegate)

    runtime_wrapper = runtime_sub.add_parser("wrapper")
    runtime_wrapper.add_argument("--run", dest="run_id", required=True)
    runtime_wrapper.add_argument("--prompt-dispatched", action="store_true")
    runtime_wrapper.add_argument("--response-observed", action="store_true")
    runtime_wrapper.add_argument("--verification-observed", action="store_true")
    runtime_wrapper.add_argument("--completion-status", choices=("started", "completed", "blocked", "failed", "unknown"), default="unknown")
    runtime_wrapper.add_argument("--gap", action="append")
    runtime_wrapper.add_argument("--message", default="")
    runtime_wrapper.set_defaults(func=cmd_runtime_wrapper)

    runtime_review = runtime_sub.add_parser("review")
    runtime_review.add_argument("--run", dest="run_id", required=True)
    runtime_review.add_argument("--status", choices=REVIEW_STATUSES, required=True)
    runtime_review.add_argument("--reviewer", default="")
    runtime_review.add_argument("--evidence-ref", action="append")
    runtime_review.add_argument("--summary", default="")
    runtime_review.set_defaults(func=cmd_runtime_review)

    runtime_ci = runtime_sub.add_parser("ci")
    runtime_ci.add_argument("--run", dest="run_id", required=True)
    runtime_ci.add_argument("--status", choices=CI_STATUSES, required=True)
    runtime_ci.add_argument("--provider", default="")
    runtime_ci.add_argument("--check", action="append")
    runtime_ci.add_argument("--evidence-ref", action="append")
    runtime_ci.add_argument("--summary", default="")
    runtime_ci.set_defaults(func=cmd_runtime_ci)

    runtime_merge = runtime_sub.add_parser("merge")
    runtime_merge.add_argument("--run", dest="run_id", required=True)
    merge_status = runtime_merge.add_mutually_exclusive_group()
    merge_status.add_argument("--ready", action="store_true")
    merge_status.add_argument("--merged", action="store_true")
    merge_status.add_argument("--blocked", action="store_true")
    merge_status.add_argument("--status", choices=MERGE_STATUSES, default=None)
    runtime_merge.add_argument("--target-branch", default="")
    runtime_merge.add_argument("--merge-commit", default="")
    runtime_merge.add_argument("--evidence-ref", action="append")
    runtime_merge.add_argument("--summary", default="")
    runtime_merge.set_defaults(func=cmd_runtime_merge)

    runtime_validate = runtime_sub.add_parser("validate")
    runtime_validate.add_argument("--run", dest="run_id", default=None)
    runtime_validate.set_defaults(func=cmd_runtime_validate)

    runtime_export = runtime_sub.add_parser("export")
    runtime_export.add_argument("--redacted", action="store_true", default=True)
    runtime_export.add_argument("--no-redact", dest="redacted", action="store_false")
    runtime_export.set_defaults(func=cmd_runtime_export)


def _add_state_commands(sub) -> None:
    state = sub.add_parser("state")
    state_sub = state.add_subparsers(dest="state_command", required=True)

    state_status = state_sub.add_parser("status")
    state_status.add_argument("--workflow", default=None)
    state_status.set_defaults(func=cmd_state_status)

    state_start = state_sub.add_parser("start")
    state_start.add_argument("--workflow", required=True)
    state_start.add_argument("--note", default="")
    state_start.set_defaults(func=cmd_state_start)

    state_finish = state_sub.add_parser("finish")
    state_finish.add_argument("--workflow", required=True)
    state_finish.add_argument("--outcome", choices=LIFECYCLE_OUTCOMES, default="finished")
    state_finish.add_argument("--note", default="")
    state_finish.set_defaults(func=cmd_state_finish)

    state_clear = state_sub.add_parser("clear")
    state_clear.add_argument("--workflow", required=True)
    state_clear.set_defaults(func=cmd_state_clear)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="omh", description="Install oh-my-hermes skills for Hermes Agent.")
    parser.add_argument("--omh-home", default=None)
    parser.add_argument("--hermes-home", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    _add_top_level_commands(sub)
    _add_docs_commands(sub)
    _add_harness_commands(sub)
    _add_playbook_commands(sub)
    _add_demo_commands(sub)
    _add_chat_commands(sub)
    _add_coding_commands(sub)
    _add_hermes_commands(sub)
    _add_runtime_commands(sub)
    _add_state_commands(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except OmhError as exc:
        print(f"omh: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
