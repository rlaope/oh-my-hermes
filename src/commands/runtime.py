from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from ..codex_progress import summarize_codex_jsonl_file
from ..executor_progress import (
    ExecutorProgressError,
    PROGRESS_EVENT_TYPES,
    build_progress_binding,
    build_safe_progress_signal,
    compact_suppressed_observation,
    observe_executor_progress,
    project_active_executor_status,
    read_progress_binding,
    write_progress_binding,
)
from ..external_effect_receipts import (
    CLAIM_BOUNDARY as EXTERNAL_EFFECT_CLAIM_BOUNDARY,
    compact_external_effect_receipt,
    project_external_effects,
    read_external_effect_mint_failures,
    read_external_effect_receipts,
    validate_external_effect_receipt_store,
)
from ..workflows.external_action_readiness import (
    ExternalActionReadinessError,
    answer_external_action_readiness,
    evidence_from_external_effect_receipt,
    evidence_from_mcp_host_session,
    evidence_from_plugin_host_observation,
)
from ..mcp.bridge import read_mcp_host_sessions
from ..plugin_observations import read_plugin_host_observations
from ..workflows.approval_receipts import (
    APPROVAL_TTL_SECONDS,
    CLAIM_BOUNDARY as APPROVAL_CLAIM_BOUNDARY,
    compact_approval_receipt,
    read_approval_mint_failures,
    read_approval_receipts,
    validate_approval_receipt_store,
)
from ..goal_ledger import RUNTIME_COMPLETION_ACTIONS
from ..installer import OmhError
from ..runtime.artifacts import (
    append_journal_observation,
    CI_STATUSES,
    DEFAULT_RUN_HISTORY_LIMIT,
    DELEGATION_RESULTS,
    MERGE_STATUSES,
    PRIVACY_MODES,
    REVIEW_STATUSES,
    RUN_STATUSES,
    RUNTIME_OBSERVABLE_EVENTS,
    RUNTIME_OBSERVATION_STATUSES,
    WRAPPER_COMPLETION_STATUSES,
    create_run,
    export_runtime,
    list_runs,
    show_run,
    read_state_result,
    summarize_delegated_coding_status,
    validate_runtime,
    write_ci_record,
    write_delegation,
    write_merge_record,
    write_review_record,
    write_runtime_observation,
    write_wrapper_contract,
)
from ..runtime.generated_artifacts import (
    DEFAULT_ARTIFACT_SCAN_LIMIT,
    DEFAULT_RETENTION_DAYS,
    build_generated_artifact_cleanup_preview,
    render_generated_artifact_cleanup_preview_text,
)
from ..runtime.context_budget import (
    PROGRESS_STATUS_LEDGER_KEY,
    degrade_run_payload,
    payload_fingerprint,
    public_budget,
    record_context_emission,
    run_context_budget,
    run_show_surface,
    smaller_payload,
    unchanged_progress_status_payload,
    unchanged_run_payload,
)
from ..executors import CODING_RUNTIME_HANDOFF_TARGETS
from ..local_store import read_json_object
from ..paths import OmhPaths
from ..skill_pack import builtin_harnesses, routable_definitions
from ..team_readiness import DEFAULT_RUNTIME_TARGET_SCAN_LIMIT, build_team_worker_readiness
from ..hud import build_hud_payload
from ..plugin_bundle.omh.todo_store import (
    TODO_CLAIM_BOUNDARY,
    TodoStoreError,
    TodoValidationError,
    build_todo_record,
    clear_todo,
    todo_path,
    write_todo,
)
from .common import _paths, _print_json, _wants_json


# The next_actions that mean the run has already passed the gate a record
# command writes. Recording that gate again from one of these re-states what the
# run's own records already say; it is not a transition to something they do not
# support, so the preflight admits it.
#
# This is what makes the upgrade path for a run written before external effect
# receipts existed a supported one. Such a run sits at `report_merged` (or
# `report_merge_ready`) with no receipt for its CI or its merge, and re-recording
# the observed result is the only way to mint one -- there is deliberately no
# command that mints a receipt from operator input. Without this the operator
# could not re-record at all, or could only reach the CI half by first writing a
# `not_observed` CI record that was not true.
#
# It does not weaken the guard below it: a run short of the gate still has a
# next_action naming the evidence it is missing, and recording a higher gate from
# there stays refused, because that would contradict the record rather than
# restate it.
RECORDED_GATE_PREFLIGHT_ACTIONS = frozenset(RUNTIME_COMPLETION_ACTIONS)


def _valid_skill_names() -> set[str]:
    return {definition.name for definition in routable_definitions()}


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
    journal_events, journal_errors = paths.runtime_journal_events_path, []
    _print_json(
        {
            "schema_version": 1,
            "runtime_dir": str(paths.runtime_dir),
            "state_path": str(paths.runtime_state_path),
            "runs_dir": str(paths.runtime_runs_dir),
            "wrapper_sessions_dir": str(paths.runtime_wrapper_sessions_dir),
            "journal_path": str(journal_events),
            "journal_errors": journal_errors,
            "state": state,
            "state_error": state_error,
        }
    )
    return 0


def cmd_runtime_runs(args: argparse.Namespace) -> int:
    paths = _paths(args)
    runs = [
        {"run_id": run["run_id"], **run, "lifecycle": show_run(paths, run["run_id"]).get("lifecycle", {})}
        for run in list_runs(paths, limit=_bounded_limit(args))
    ]
    _print_json({"runs": runs})
    return 0


def _history_limit(args: argparse.Namespace) -> int | None:
    if getattr(args, "full", False):
        return None
    limit = getattr(args, "history_limit", None)
    if limit is None:
        return DEFAULT_RUN_HISTORY_LIMIT
    if int(limit) < 1:
        raise OmhError("--limit must be at least 1 unless --full is set")
    return int(limit)


def cmd_runtime_show(args: argparse.Namespace) -> int:
    paths = _paths(args)
    full = bool(getattr(args, "full", False))
    try:
        shown = show_run(paths, args.run_id, history_limit=_history_limit(args))
    except FileNotFoundError as exc:
        raise OmhError(f"runtime run not found: {args.run_id}") from exc
    surface = run_show_surface(full=full, history_limit=_history_limit(args))
    ledger = run_context_budget(paths, args.run_id, surface=surface)
    fingerprint = payload_fingerprint(shown)
    unchanged = fingerprint == ledger["last_payload_fingerprint"]
    budget = public_budget(ledger)
    if full:
        payload = {**shown, "context_budget": budget}
    elif budget["exhausted"]:
        # Exhaustion outranks the unchanged check on purpose. Both are stop
        # signals, but the degraded payload is the one that points at the
        # artifacts, and its shape is an existing contract.
        payload = degrade_run_payload(shown, budget)
    elif unchanged:
        payload = smaller_payload({**shown, "context_budget": budget}, unchanged_run_payload(shown, budget))
    else:
        payload = {**shown, "context_budget": budget}
    _print_json(payload)
    record_context_emission(
        paths,
        args.run_id,
        surface=surface,
        byte_count=len(json.dumps(payload, sort_keys=True)),
        payload_fingerprint_value=fingerprint,
    )
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
    allowed_preflight = {"record_review_evidence"} | RECORDED_GATE_PREFLIGHT_ACTIONS
    if args.status in {"passed", "not_required"} and preflight.get("next_action") not in allowed_preflight:
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
    allowed_preflight = {"record_ci_evidence"} | RECORDED_GATE_PREFLIGHT_ACTIONS
    if args.status == "passed" and preflight.get("next_action") not in allowed_preflight:
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
        status: gates | RECORDED_GATE_PREFLIGHT_ACTIONS
        for status, gates in (
            ("ready", {"record_merge_readiness"}),
            ("merged", set()),
            ("blocked", {"record_merge_readiness"}),
            ("not_ready", {"record_merge_readiness"}),
            ("not_observed", {"record_merge_readiness"}),
        )
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


def cmd_runtime_observe(args: argparse.Namespace) -> int:
    paths = _paths(args)
    target_type = "run" if args.run_id else "wrapper_session"
    target_id = args.run_id or args.session_id
    if not target_id:
        raise OmhError("runtime observe requires --run or --session")
    target_dir = (
        paths.runtime_runs_dir / target_id
        if target_type == "run"
        else paths.runtime_wrapper_sessions_dir / target_id
    )
    required_file = target_dir / ("run.json" if target_type == "run" else "session.json")
    if not required_file.exists():
        raise OmhError(f"runtime {target_type} not found: {target_id}")
    write_legacy_observation = _validate_runtime_observation_target(target_dir, target_type, args.runtime_profile)
    participants = [item.strip() for item in (args.participants or "").split(",") if item.strip()]
    try:
        observation_payload = {
            "target_type": target_type,
            "target_id": target_id,
            "runtime_profile": args.runtime_profile,
            "event_type": args.event,
            "status": args.status,
            "participants": participants,
            "worktree_ref": args.worktree_ref or "",
            "worker_ref": args.worker_ref or "",
            "evidence_refs": args.evidence_ref or [],
            "summary": args.summary or "",
        }
        if write_legacy_observation:
            observation = write_runtime_observation(target_dir, observation_payload)
            journal_event = None
        else:
            observation = {}
            journal_event = append_journal_observation(
                paths,
                {
                    "target_type": target_type,
                    "target_id": target_id,
                    "run_id": target_id if target_type == "run" else "",
                    "runtime_profile": args.runtime_profile,
                    "event": args.event,
                    "status": args.status,
                    "evidence_refs": args.evidence_ref or [],
                    "summary": args.summary or "",
                    "source": "runtime_observe",
                    "worktree_ref": args.worktree_ref or "",
                    "worker_ref": args.worker_ref or "",
                },
            )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    payload: dict[str, object] = {"observation": observation}
    if journal_event:
        payload["journal_event"] = journal_event
    if target_type == "run":
        payload["status"] = summarize_delegated_coding_status(paths, target_id)
    _print_json(payload)
    return 0


def cmd_runtime_progress_bind(args: argparse.Namespace) -> int:
    paths = _paths(args)
    target_type, target_id = _progress_target(args)
    _require_progress_target(paths, target_type, target_id)
    try:
        binding = build_progress_binding(
            target_type=target_type,
            target_id=target_id,
            executor_profile=args.executor_profile,
            observed_hermes_execution=bool(args.observed_hermes_execution),
            codex_session_ref=args.codex_session_ref or "",
            codex_thread_ref=args.codex_thread_ref or "",
            claude_session_ref=args.claude_session_ref or "",
            process_session_id=args.process_session_id or "",
            worktree=args.worktree or "",
            branch=args.branch or "",
            pid=args.pid,
            source=args.source or "",
            channel_ref=args.channel_ref or "",
            thread_ref=args.thread_ref or "",
            delivery_target=args.delivery_target or "",
            evidence_refs=args.evidence_ref or [],
        )
        write_progress_binding(paths, binding)
    except ExecutorProgressError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"binding": binding})
    return 0


def cmd_runtime_progress_observe(args: argparse.Namespace) -> int:
    paths = _paths(args)
    target_type, target_id = _progress_target(args)
    try:
        binding = read_progress_binding(paths, target_type, target_id)
    except (OSError, ValueError, ExecutorProgressError) as exc:
        raise OmhError(f"executor progress binding could not be read: {exc}") from exc
    if not binding:
        raise OmhError(f"executor progress binding not found for {target_type}: {target_id}")
    try:
        codex_summary = summarize_codex_jsonl_file(args.codex_log_jsonl, evidence_refs=args.evidence_ref or []) if args.codex_log_jsonl else None
        profile_summary = _profile_progress_summary(args)
        _reject_ignored_progress_inputs(
            executor_profile=str(binding.get("executor_profile", "")),
            codex_summary=codex_summary,
            profile_summary=profile_summary,
        )
        signal = build_safe_progress_signal(
            executor_profile=str(binding.get("executor_profile", "")),
            process_status=args.process_status or "",
            codex_progress_summary=codex_summary,
            profile_progress_summary=profile_summary,
            git_status_short=args.git_status_short,
            git_diff_stat=args.git_diff_stat,
            explicit_event_type=args.event or "",
            explicit_summary=args.summary or "",
            evidence_refs=args.evidence_ref or [],
            observed_hermes_execution=str(binding.get("executor_profile", "")) == "hermes_local",
        )
        payload = observe_executor_progress(
            paths,
            binding,
            signal,
            source_language=args.source_language or "",
        )
    except (OSError, ValueError, ExecutorProgressError) as exc:
        raise OmhError(str(exc)) from exc
    if not bool(getattr(args, "full", False)) and not payload.get("reported"):
        payload = smaller_payload(payload, compact_suppressed_observation(payload))
    _print_json(payload)
    return 0


def cmd_runtime_progress_status(args: argparse.Namespace) -> int:
    paths = _paths(args)
    full = bool(getattr(args, "full", False))
    limit = _bounded_limit(args)
    shown = project_active_executor_status(paths, limit=limit)
    # Keyed by limit for the same reason `runtime show` is keyed by history
    # limit: a different limit is a different projection.
    surface = f"progress_status:{limit}"
    ledger = run_context_budget(paths, PROGRESS_STATUS_LEDGER_KEY, surface=surface)
    fingerprint = payload_fingerprint(shown)
    if not full and fingerprint == ledger["last_payload_fingerprint"]:
        payload = smaller_payload(shown, unchanged_progress_status_payload(shown, ledger))
    else:
        payload = shown
    # Plain text is the default here for the same reason it is everywhere else
    # in omh: this projection is one full binding record per executor, and
    # printing it raw put roughly fifteen kilobytes of JSON in front of whoever
    # asked "what is running?". `--json` (or OMH_OUTPUT=json) keeps the machine
    # payload for agents and scripts.
    if _wants_json(args):
        emitted = json.dumps(payload, sort_keys=True)
        _print_json(payload)
    else:
        emitted = _render_progress_status_text(payload)
        print(emitted)
    record_context_emission(
        paths,
        PROGRESS_STATUS_LEDGER_KEY,
        surface=surface,
        # The ledger charges what was actually emitted, so a text call is not
        # billed for JSON it never printed. The fingerprint stays the payload's
        # so the suppression decision is identical in both modes.
        byte_count=len(emitted),
        payload_fingerprint_value=fingerprint,
    )
    return 0


def _render_progress_status_text(payload: dict) -> str:
    """Compact human board for `runtime progress-status`.

    Handles both shapes the command can emit: the full projection, and the
    suppressed `unchanged_since_last_emission` replacement that carries counts
    instead of rows. Rendering only the full shape would print an empty board on
    every repeated call, which reads as "everything stopped" when nothing moved.
    """
    if payload.get("unchanged_since_last_emission"):
        return "\n".join(
            [
                "Executor progress status: unchanged since the last emission.",
                f"  Active executors: {payload.get('active_executor_count', 0)}",
                f"  Stale executors: {payload.get('stale_executor_count', 0)}",
                f"  Next: {payload.get('next_action', '')}",
                f"  Full output: {payload.get('full_output_command', '')}",
                str(payload.get("claim_boundary", "")),
            ]
        )
    active = [row for row in payload.get("active_executors", []) or [] if isinstance(row, dict)]
    stale = [row for row in payload.get("stale_executors", []) or [] if isinstance(row, dict)]
    lines = [f"Executor progress status ({len(active)} active, {len(stale)} stale)"]
    if not active and not stale:
        lines.append("  No executor progress observed.")
    for label, rows in (("Active", active), ("Stale", stale)):
        if not rows:
            continue
        lines.append(f"{label}:")
        lines.extend(f"  {_progress_status_row_text(row)}" for row in rows)
    lines.append(str(payload.get("claim_boundary", "")))
    return "\n".join(line for line in lines if line)


def _progress_status_row_text(row: dict) -> str:
    event = row.get("latest_event", {})
    event = event if isinstance(event, dict) else {}
    # The summary is the only free text on the row and it already passed the
    # observe-side sanitizer; everything else is an identifier or a status word.
    parts = [
        f"{row.get('target_type', 'unknown')} {row.get('target_id', 'unknown')}",
        str(row.get("executor_profile", "") or "unknown"),
        str(event.get("event_type", "") or "no_observed_event"),
        f"observed {row.get('latest_observed_at', '') or 'unknown'}",
    ]
    line = " — ".join(parts)
    summary = str(event.get("summary", "") or "")
    return f"{line} — {summary}" if summary else line


def _validate_runtime_observation_target(target_dir, target_type: str, runtime_profile: str) -> bool:
    expected_profile = _expected_runtime_profile_for_target(target_dir, target_type)
    if expected_profile is None:
        return True
    if not expected_profile:
        if target_type == "wrapper_session":
            raise OmhError("runtime observe requires a runtime_handoff_prepared wrapper session")
        run = read_json_object(target_dir / "run.json")
        coding = read_json_object(target_dir / "coding_delegation.json")
        if (
            isinstance(run, dict)
            and run.get("artifact_kind") == "prepared_coding_delegation"
            and isinstance(coding, dict)
        ):
            return False
        raise OmhError("runtime observe cannot record runtime events for this non-runtime handoff run")
    if runtime_profile != expected_profile:
        raise OmhError(f"runtime observation profile mismatch: expected {expected_profile}, got {runtime_profile}")
    return True


def _expected_runtime_profile_for_target(target_dir, target_type: str) -> str | None:
    if target_type == "wrapper_session":
        session = read_json_object(target_dir / "session.json")
        if not isinstance(session, dict) or session.get("status") != "runtime_handoff_prepared":
            return ""
        return _runtime_profile_from_handoff(session.get("runtime_handoff")) or str(session.get("selected_executor_profile") or "")
    run = read_json_object(target_dir / "run.json")
    coding = read_json_object(target_dir / "coding_delegation.json")
    if isinstance(coding, dict):
        if coding.get("work_owner_mode") == "runtime_handoff":
            return _runtime_profile_from_handoff(coding.get("runtime_handoff")) or str(coding.get("selected_executor_profile") or "")
        return "" if isinstance(run, dict) and run.get("artifact_kind") == "prepared_coding_delegation" else None
    return "" if isinstance(run, dict) else None


def _runtime_profile_from_handoff(handoff: object) -> str:
    if not isinstance(handoff, dict):
        return ""
    selected = str(handoff.get("selected_executor_profile") or "")
    runtime_profile = handoff.get("runtime_profile")
    if isinstance(runtime_profile, dict):
        return str(runtime_profile.get("profile") or selected)
    return selected


def _progress_target(args: argparse.Namespace) -> tuple[str, str]:
    if getattr(args, "run_id", None):
        return "run", str(args.run_id)
    if getattr(args, "session_id", None):
        return "wrapper_session", str(args.session_id)
    raise OmhError("progress command requires --run or --session")


def _require_progress_target(paths, target_type: str, target_id: str) -> None:
    if target_type == "run":
        if not (paths.runtime_runs_dir / target_id / "run.json").exists():
            raise OmhError(f"runtime run not found: {target_id}")
        return
    if target_type == "wrapper_session":
        if not (paths.runtime_wrapper_sessions_dir / target_id / "session.json").exists():
            raise OmhError(f"runtime wrapper_session not found: {target_id}")
        return
    raise OmhError(f"unsupported progress target type: {target_type}")


def _reject_ignored_progress_inputs(
    *,
    executor_profile: str,
    codex_summary: dict[str, object] | None,
    profile_summary: dict[str, object] | None,
) -> None:
    """Fail when the caller described progress this binding will not read.

    `build_safe_progress_signal` picks exactly one summary by executor profile:
    codex bindings read `--codex-log-jsonl`, every other profile reads the
    `--profile-*` flags. Passing the wrong pair used to be accepted silently,
    and the observation was then inferred from an empty summary -- so an
    operator who described a failing test run got a generic status back and no
    indication that their input had been discarded. That is a failure relabelled
    as a normal result, which this repo's broad-exception policy exists to keep
    out.
    """
    if executor_profile == "codex" and profile_summary is not None and codex_summary is None:
        raise OmhError(
            "codex progress bindings read --codex-log-jsonl; the --profile-* flags would be ignored. "
            "Pass --codex-log-jsonl, or use --event/--summary to state the observation explicitly."
        )
    if executor_profile != "codex" and codex_summary is not None:
        raise OmhError(
            f"--codex-log-jsonl only applies to codex bindings; this binding is {executor_profile}. "
            "Use the --profile-* flags instead."
        )


def _profile_progress_summary(args: argparse.Namespace) -> dict[str, object] | None:
    """The non-codex progress summary: every field is the caller's own sentence.

    Nothing here is observed by omh. `status` is `--profile-status` verbatim,
    the latest event is `--profile-latest-event` verbatim, and
    `observable_activity` is empty because there is no stream to read activity
    out of. The codex path is the contrast: `summarize_codex_jsonl_file` derives
    its summary from a log this repo parsed, counted, and hashed.

    `build_safe_progress_signal` stamps that difference onto the signal
    (`progress_summary_source`), and the lane refuses to let anything built here
    corroborate an end state the same caller narrated -- otherwise one
    `omh runtime progress observe` call closes its own binding by passing
    `--profile-status completed_or_passed_observed` next to
    `--profile-latest-event workflow_completed`. Reporting an end state stays
    possible; it needs `--process-status`, git flags, or an explicit `--event`.
    """
    if not (args.profile_status or args.profile_event_count is not None or args.profile_latest_event or args.profile_summary):
        return None
    return {
        "status": args.profile_status or "activity_observed",
        "event_count": args.profile_event_count or 0,
        "latest_progress_event": {"event_type": args.profile_latest_event or ""},
        "observable_activity": [],
        "summary": args.profile_summary or "",
    }


def _add_progress_target_args(parser: argparse.ArgumentParser) -> None:
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--run", dest="run_id", default=None)
    target.add_argument("--session", dest="session_id", default=None)


def _add_progress_bind_args(parser: argparse.ArgumentParser) -> None:
    _add_progress_target_args(parser)
    parser.add_argument(
        "--executor-profile",
        required=True,
        help="codex, claude-code/claude_code, or hermes_local with observed execution.",
    )
    parser.add_argument("--observed-hermes-execution", action="store_true")
    parser.add_argument("--codex-session-ref", default="")
    parser.add_argument("--codex-thread-ref", default="")
    parser.add_argument("--claude-session-ref", default="")
    parser.add_argument("--process-session-id", default="")
    parser.add_argument("--pid", default=None)
    parser.add_argument("--worktree", default="")
    parser.add_argument("--branch", default="")
    parser.add_argument("--source", default="")
    parser.add_argument("--channel-ref", default="")
    parser.add_argument("--thread-ref", default="")
    parser.add_argument("--delivery-target", default="")
    parser.add_argument("--evidence-ref", action="append")
    parser.set_defaults(func=cmd_runtime_progress_bind)


def _add_progress_observe_args(parser: argparse.ArgumentParser) -> None:
    _add_progress_target_args(parser)
    parser.add_argument(
        "--full",
        action="store_true",
        help="Print the complete binding record even when the observation reported nothing.",
    )
    parser.add_argument("--process-status", default="")
    # Default None, not "": passing the flag with an empty value means "git was
    # checked and reports nothing changed", which is what contradicts a reported
    # change. Omitting the flag means nobody looked and contradicts nothing.
    parser.add_argument("--git-status-short", default=None)
    parser.add_argument("--git-diff-stat", default=None)
    # Choices are the shared progress vocabulary, so the CLI and the record
    # validator cannot disagree. `unmapped_source_event` is deliberately
    # offered: it is the visible answer for an owner word this vocabulary does
    # not map, and hiding it would leave a caller observing one with no way to
    # say so.
    parser.add_argument(
        "--event",
        choices=PROGRESS_EVENT_TYPES,
        default="",
        help=(
            "Declare the observed progress event. Use unmapped_source_event when the executor reported an "
            "event this vocabulary does not map; the source event name is retained and no activity is claimed."
        ),
    )
    parser.add_argument("--summary", default="")
    parser.add_argument("--codex-log-jsonl", default=None)
    parser.add_argument(
        "--profile-status",
        default="",
        help=(
            "What the executor reported about itself. Recorded as caller-reported narration: it cannot "
            "corroborate an end state it also narrated. Use --process-status, the git flags, or --event "
            "to report an observation."
        ),
    )
    parser.add_argument("--profile-event-count", type=int, default=None)
    parser.add_argument("--profile-latest-event", default="")
    parser.add_argument("--profile-summary", default="")
    parser.add_argument("--source-language", default="")
    parser.add_argument("--evidence-ref", action="append")
    parser.set_defaults(func=cmd_runtime_progress_observe)


def _add_progress_status_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--all", action="store_true")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Always print the full projection, even when nothing changed since the last call.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    parser.set_defaults(func=cmd_runtime_progress_status)


def cmd_runtime_receipts(args: argparse.Namespace) -> int:
    """Read observed external effect receipts. There is deliberately no mint command.

    A receipt exists because an acting surface observed an external effect.
    Letting an operator type one in would make this store exactly the kind of
    self-reported evidence it exists to replace.
    """
    paths = _paths(args)
    run_id = getattr(args, "run_id", None)
    limit = _bounded_limit(args)
    store_path = paths.runtime_external_effect_receipts_path
    receipts = [
        compact_external_effect_receipt(receipt)
        for receipt in read_external_effect_receipts(paths, run_id=run_id, limit=limit)
    ]
    # Unscoped on purpose: this is the one surface that reports on the whole
    # store, so a run-less receipt -- every adapter delivery is one -- is
    # validated here or nowhere. `validate_run_dir` only ever sees the records
    # carrying its own run id.
    store = validate_external_effect_receipt_store(store_path)
    mint_failures = read_external_effect_mint_failures(store_path)
    payload: dict[str, object] = {
        "schema_version": "runtime_external_effect_receipts_view/v1",
        "run_id": run_id or "",
        "store_path": str(store_path),
        "receipts": receipts,
        "store_ok": store["ok"],
        "store_errors": store["errors"],
        "receipt_count": store["receipt_count"],
        # An effect whose mint failed has no receipt at all, which is exactly
        # what this view exists to make visible, so failures are never scoped
        # away by --run.
        "mint_failures": _bounded_tail(mint_failures, limit),
        "mint_failure_count": len(mint_failures),
        "claim_boundary": EXTERNAL_EFFECT_CLAIM_BOUNDARY,
    }
    if run_id:
        payload["projection"] = _run_external_effect_projection(paths, run_id)
        # A run-scoped read would otherwise omit every run-less effect in
        # silence, so the same call reports them as their own class rather than
        # leaving `message_sent` looking like something that never happened.
        unbound = read_external_effect_receipts(paths, run_id="")
        payload["unbound_receipts"] = [
            compact_external_effect_receipt(receipt) for receipt in _bounded_tail(unbound, limit)
        ]
        payload["unbound_receipt_count"] = len(unbound)
    if _wants_json(args):
        _print_json(payload)
    else:
        print(_render_receipts_text(payload))
    return 0


def _run_external_effect_projection(paths: OmhPaths, run_id: str) -> dict:
    """One run's effect projection, the same one `delegation-status` reports.

    `requested` and `attempted` are projected from what the run's own records
    ask for, so a projection built from the receipt store alone structurally
    cannot reach either: it would print `requested 0` for a run
    `omh runtime delegation-status` reports as `requested 1` at the same
    instant, and a human comparing the two surfaces would be looking at a
    contradiction that is not in the data.

    A run with no `run.json` has no records to project from -- `--run` accepts
    any string -- so the store-only projection is the honest answer there.
    """
    try:
        status = summarize_delegated_coding_status(paths, run_id)
    except FileNotFoundError:
        return project_external_effects(paths, run_id)
    projection = status.get("external_effects")
    return projection if isinstance(projection, dict) else project_external_effects(paths, run_id)


def _bounded_tail(rows: list, limit: int | None) -> list:
    if limit is None:
        return list(rows)
    return list(rows[-limit:]) if limit > 0 else []


def _receipt_row_line(row: dict) -> str:
    # `or "unknown"` rather than a `.get` default: a closed-vocabulary field
    # renders empty when the stored value is not in its vocabulary, and an empty
    # cell would read as a dangling em-dash rather than as an unreadable record.
    return (
        f"  {row.get('action') or 'unknown'} — {row.get('observed_result') or 'unknown'} — "
        f"{row.get('acting_surface') or 'unknown'} — ref {row.get('external_ref') or 'unnamed'} — "
        f"{row.get('receipt_id', '')}"
    )


def _render_receipts_text(payload: dict) -> str:
    receipts = [row for row in payload.get("receipts", []) or [] if isinstance(row, dict)]
    lines = [f"External effect receipts ({len(receipts)} shown)"]
    if not receipts:
        lines.append("  No observed external effect receipts.")
    lines.extend(_receipt_row_line(row) for row in receipts)
    if "unbound_receipts" in payload:
        unbound = [row for row in payload.get("unbound_receipts", []) or [] if isinstance(row, dict)]
        lines.append(f"  Run-less effects ({len(unbound)} of {payload.get('unbound_receipt_count', 0)} shown)")
        if not unbound:
            lines.append("    None. Adapter deliveries and other session-scoped effects would appear here.")
        lines.extend(f"  {_receipt_row_line(row)}" for row in unbound)
    projection = payload.get("projection")
    if isinstance(projection, dict):
        states = ", ".join(
            f"{state} {len(projection.get(state, []) or [])}"
            for state in ("requested", "attempted", "succeeded", "failed", "unknown")
        )
        lines.append(f"  Effects: {states}")
    failures = [row for row in payload.get("mint_failures", []) or [] if isinstance(row, dict)]
    if payload.get("mint_failure_count"):
        lines.append(f"  Unrecorded mints: {payload.get('mint_failure_count', 0)}")
        for row in failures:
            lines.append(
                f"    {row.get('action', 'unknown')} — {row.get('outcome', 'unknown')} — "
                f"{row.get('acting_surface', 'unknown')} — effect {row.get('effect_id', '')}"
            )
        lines.append("    These external effects were observed and have no receipt.")
    if not payload.get("store_ok", True):
        errors = [str(error) for error in payload.get("store_errors", []) or []]
        lines.append(f"  Store errors: {len(errors)}")
        lines.extend(f"    {error}" for error in errors[:10])
    lines.append(str(payload.get("claim_boundary", "")))
    return "\n".join(line for line in lines if line)


ACTION_READINESS_VIEW_SCHEMA_VERSION = "runtime_action_readiness_view/v1"
DEFAULT_ACTION_READINESS_SCAN_LIMIT = 20
# The output of this surface is a fixed shape -- one answer, at most eight
# rejected rows, at most this many store faults -- no matter how large the
# evidence stores grow. That is why it is registered as a bounded surface: an
# agent asking "can you do it yet" every thirty seconds buys the same size
# answer every time.
MAX_ACTION_READINESS_STORE_ERRORS = 8

_ACTION_READINESS_HEADLINES = {
    "ready": "Yes — ready now",
    "blocked": "No — blocked",
    "not_observed": "Unknown — nothing has been observed",
    "stale": "Unknown — the last observation is stale",
    "failed": "No — the last attempt failed",
}


def cmd_runtime_action_readiness(args: argparse.Namespace) -> int:
    """Answer "can Hermes do this now?" for one requested outcome (#809).

    Read-only, and deliberately without a way to assert readiness: every tier
    above `installed` comes from a record some other surface wrote after it
    observed something. A flag that said "this is ready" would put back exactly
    the confusion between configuration and capability this surface removes.

    There is no answer store and no `--prior`. The durable state is the evidence
    stores themselves, and they are re-read in full on every call, so a corrupt
    line appended today cannot erase what valid records already say: the
    last-valid-state preservation the contract requires is structural here
    rather than remembered. Unreadable lines are reported as store faults in the
    same breath.
    """
    paths = _paths(args)
    limit = _bounded_limit(args)
    outcome_id = str(getattr(args, "outcome_id", "") or "")
    surface = str(getattr(args, "surface", "") or "")
    action = str(getattr(args, "action", "") or "").strip() or outcome_id

    plugin_records, plugin_errors = read_plugin_host_observations(paths, limit=limit)
    mcp_records, mcp_errors = read_mcp_host_sessions(paths, limit=limit)
    receipts = read_external_effect_receipts(paths, effect_id=outcome_id, limit=limit)

    # Host records are surface-scoped, so they are filtered by host here;
    # receipts are outcome-scoped and were already selected by effect id.
    from_plugin = _adapted_evidence(
        [record for record in plugin_records if str(record.get("host", "")) == surface],
        evidence_from_plugin_host_observation,
    )
    from_mcp = _adapted_evidence(
        [record for record in mcp_records if str(record.get("host", "")) == surface],
        evidence_from_mcp_host_session,
    )
    from_receipts = _adapted_evidence(receipts, evidence_from_external_effect_receipt)
    evidence = [*from_plugin, *from_mcp, *from_receipts]
    counts = {
        "plugin_host_observation": len(from_plugin),
        "mcp_host_session": len(from_mcp),
        "external_effect_receipt": len(from_receipts),
    }

    try:
        answer = answer_external_action_readiness(
            outcome_id=outcome_id,
            action=action,
            surface=surface,
            evidence=evidence,
        )
    except ExternalActionReadinessError as exc:
        raise OmhError(str(exc)) from exc

    store_errors = [str(error) for error in (*plugin_errors, *mcp_errors)]
    payload: dict[str, object] = {
        "schema_version": ACTION_READINESS_VIEW_SCHEMA_VERSION,
        "answer": answer,
        "evidence_sources": counts,
        "scanned_limit": limit or 0,
        "store_errors": store_errors[:MAX_ACTION_READINESS_STORE_ERRORS],
        "store_error_count": len(store_errors),
    }
    if _wants_json(args):
        _print_json(payload)
    else:
        print(_render_action_readiness_text(payload))
    return 0


def _adapted_evidence(records: list, adapt) -> list[dict]:
    """Every record this adapter could read as evidence, dropping the rest.

    A record the adapter returns nothing for is not weaker evidence: it is a
    state that says nothing about whether the outcome can happen now, such as an
    effect a surface observed start and could not classify.
    """
    adapted = [adapt(record) for record in records]
    return [item for item in adapted if item is not None]


def _render_action_readiness_text(payload: dict) -> str:
    answer = payload.get("answer")
    answer = answer if isinstance(answer, dict) else {}
    state = str(answer.get("state", ""))
    counts = payload.get("evidence_sources")
    counts = counts if isinstance(counts, dict) else {}
    lines = [
        f"Can Hermes do this now? {_ACTION_READINESS_HEADLINES.get(state, 'Unknown')}",
        f"  Outcome: {answer.get('outcome_id', '')} — {answer.get('action', '')}",
        f"  Surface: {answer.get('surface', '')}",
        f"  State: {state} (strongest evidence: {answer.get('evidence_tier', '')})",
        f"  Why: {answer.get('reason', '')}",
        f"  Next: {answer.get('next_step', '')}",
        f"  Evidence: {answer.get('accepted_count', 0)} in scope, "
        f"{answer.get('rejected_count', 0)} rejected ({answer.get('evidence_integrity', '')})",
        "  Read from: " + ", ".join(f"{name} {counts.get(name, 0)}" for name in sorted(counts)),
    ]
    for row in answer.get("rejected_evidence", []) or []:
        if isinstance(row, dict):
            lines.append(f"    rejected record {row.get('index', '')}: {row.get('reason', '')}")
    if payload.get("store_error_count"):
        lines.append(f"  Store faults: {payload.get('store_error_count', 0)}")
        lines.extend(f"    {error}" for error in payload.get("store_errors", []) or [])
    lines.append(str(answer.get("claim_boundary", "")))
    return "\n".join(line for line in lines if line)


def cmd_runtime_approvals(args: argparse.Namespace) -> int:
    """Read recorded approval receipts. There is deliberately no grant command.

    An approval exists because an operator answered a confirmation. A CLI flag
    that minted one would make this store exactly the kind of self-asserted
    evidence it exists to replace -- whoever typed the flag would be granting
    themselves the permission the confirmation was supposed to ask about.

    Freshness is computed here, at read time, and never read off the record: the
    store has no retention or cleanup, so an expired approval stays on disk
    forever and only the reader can say whether it still means anything.
    """
    paths = _paths(args)
    run_id = getattr(args, "run_id", None)
    limit = _bounded_limit(args)
    store_path = paths.runtime_approval_receipts_path
    receipts = [
        compact_approval_receipt(receipt)
        for receipt in read_approval_receipts(paths, run_id=run_id, limit=limit)
    ]
    # Unscoped on purpose: this is the one surface that reports on the whole
    # store, so a fault on a receipt belonging to another run is still visible
    # here rather than nowhere.
    store = validate_approval_receipt_store(store_path)
    mint_failures = read_approval_mint_failures(store_path)
    payload: dict[str, object] = {
        "schema_version": "runtime_approval_receipts_view/v1",
        "run_id": run_id or "",
        "store_path": str(store_path),
        "receipts": receipts,
        "store_ok": store["ok"],
        "store_errors": store["errors"],
        "receipt_count": store["receipt_count"],
        # An answered confirmation whose mint failed has no receipt at all,
        # which is exactly what this view exists to make visible, so failures
        # are never scoped away by --run.
        "mint_failures": _bounded_tail(mint_failures, limit),
        "mint_failure_count": len(mint_failures),
        "expires_after_seconds": APPROVAL_TTL_SECONDS,
        "claim_boundary": APPROVAL_CLAIM_BOUNDARY,
    }
    if _wants_json(args):
        _print_json(payload)
    else:
        print(_render_approvals_text(payload))
    return 0


def _approval_row_line(row: dict) -> str:
    # `or "unknown"` rather than a `.get` default: a closed-vocabulary field
    # renders empty when the stored value is not in its vocabulary, and an empty
    # cell would read as a dangling em-dash rather than as an unreadable record.
    freshness = "expired" if row.get("expired") else "live"
    return (
        f"  {row.get('decision') or 'unknown'} — {row.get('approved_action') or 'unknown'} — "
        f"{row.get('scope_class') or 'unknown'} {row.get('scope_ref') or 'unnamed'} — "
        f"owner {row.get('owner') or 'unknown'} — {freshness} — {row.get('receipt_id', '')}"
    )


def _render_approvals_text(payload: dict) -> str:
    receipts = [row for row in payload.get("receipts", []) or [] if isinstance(row, dict)]
    lines = [f"Approval receipts ({len(receipts)} shown)"]
    if not receipts:
        lines.append("  No recorded approvals.")
    lines.extend(_approval_row_line(row) for row in receipts)
    lines.append(f"  Approval window: {payload.get('expires_after_seconds', 0)}s, evaluated at read time.")
    failures = [row for row in payload.get("mint_failures", []) or [] if isinstance(row, dict)]
    if payload.get("mint_failure_count"):
        lines.append(f"  Unrecorded answers: {payload.get('mint_failure_count', 0)}")
        for row in failures:
            lines.append(
                f"    {row.get('decision', 'unknown')} — {row.get('outcome', 'unknown')} — "
                f"{row.get('approved_action', 'unknown')} — approval {row.get('approval_id', '')}"
            )
        lines.append("    These confirmations were answered and have no receipt.")
    if not payload.get("store_ok", True):
        errors = [str(error) for error in payload.get("store_errors", []) or []]
        lines.append(f"  Store errors: {len(errors)}")
        lines.extend(f"    {error}" for error in errors[:10])
    lines.append(str(payload.get("claim_boundary", "")))
    return "\n".join(line for line in lines if line)


def cmd_runtime_artifacts(args: argparse.Namespace) -> int:
    """Show which locally generated artifacts are current, and preview cleanup.

    Read-only by construction, and deliberately so: there is no `--delete` and
    no confirm flag that would grow into one. The projection reports what could
    be removed and why; removing it is the operator's own act, outside OMH.

    `now` is read here, at the process edge, and passed into the projection.
    Every retention verdict downstream is a pure function of that one value, so
    two calls against the same store and the same stamp answer identically.
    """
    limit = None if getattr(args, "all", False) else int(getattr(args, "limit", DEFAULT_ARTIFACT_SCAN_LIMIT))
    if limit is not None and limit < 1:
        raise OmhError("--limit must be at least 1 unless --all is set")
    retention_days = int(getattr(args, "retention_days", DEFAULT_RETENTION_DAYS))
    if retention_days < 1:
        raise OmhError("--retention-days must be at least 1")
    payload = build_generated_artifact_cleanup_preview(
        _paths(args),
        now=datetime.now(timezone.utc),
        retention_days=retention_days,
        limit=limit,
    )
    if _wants_json(args):
        _print_json(payload)
    else:
        print(render_generated_artifact_cleanup_preview_text(payload))
    return 0


def cmd_runtime_validate(args: argparse.Namespace) -> int:
    result = validate_runtime(_paths(args), args.run_id)
    _print_json(result)
    return 0 if result["ok"] else 1


def cmd_runtime_export(args: argparse.Namespace) -> int:
    _print_json(
        export_runtime(
            _paths(args),
            redacted=args.redacted,
            limit=_bounded_limit(args),
            full=not args.summary,
            run_id=args.run_id,
        )
    )
    return 0


def cmd_runtime_team_readiness(args: argparse.Namespace) -> int:
    target_limit = None if getattr(args, "all", False) else int(getattr(args, "limit", DEFAULT_RUNTIME_TARGET_SCAN_LIMIT))
    if target_limit is not None and target_limit < 1:
        raise OmhError("--limit must be at least 1 unless --all is set")
    _print_json(build_team_worker_readiness(_paths(args), target_limit=target_limit))
    return 0


def _bounded_limit(args: argparse.Namespace) -> int | None:
    if getattr(args, "all", False):
        return None
    limit = int(getattr(args, "limit", 50))
    if limit < 1:
        raise OmhError("--limit must be at least 1 unless --all is set")
    return limit


def cmd_runtime_todo_set(args: argparse.Namespace) -> int:
    paths = _paths(args)
    if args.items_json is not None:
        try:
            items = json.loads(args.items_json)
        except json.JSONDecodeError as error:
            _print_json({"status": "invalid_todo", "error": f"--items-json is not valid JSON: {error}"})
            return 1
    else:
        items = [{"text": text, "state": "pending"} for text in args.items]
    session_ref = args.session_ref
    try:
        record = build_todo_record(args.title, items, source="cli", session_ref=session_ref)
        write_todo(paths.omh_home, record)
    except (TodoValidationError, TodoStoreError) as error:
        _print_json({"status": "invalid_todo", "error": str(error)})
        return 1
    _print_json(
        {
            "status": "written",
            "path": str(todo_path(paths.omh_home, session_ref)),
            "todo": build_hud_payload(paths, session_ref=session_ref)["todo"],
            "claim_boundary": TODO_CLAIM_BOUNDARY,
        }
    )
    return 0


def cmd_runtime_todo_clear(args: argparse.Namespace) -> int:
    paths = _paths(args)
    session_ref = args.session_ref
    try:
        cleared = clear_todo(paths.omh_home, session_ref)
    except TodoStoreError as error:
        _print_json({"status": "invalid_todo", "error": str(error)})
        return 1
    _print_json(
        {
            "status": "cleared" if cleared else "already_absent",
            "path": str(todo_path(paths.omh_home, session_ref)),
        }
    )
    return 0


def cmd_runtime_todo_show(args: argparse.Namespace) -> int:
    payload = build_hud_payload(_paths(args), session_ref=args.session_ref)
    _print_json(
        {
            "status": "read",
            "todo": payload["todo"],
            "todo_lines": payload["display"]["todo_lines"],
            "claim_boundary": TODO_CLAIM_BOUNDARY,
        }
    )
    return 0


def _add_runtime_commands(sub) -> None:
    from .run_efficiency import add_runtime_efficiency_command
    from .run_health import add_runtime_health_summary_command
    from .runtime_artifact_shape import add_runtime_artifacts_show_shape_command

    runtime = sub.add_parser("runtime", help="Read and record local prepared-vs-observed runtime evidence.")
    runtime_sub = runtime.add_subparsers(dest="runtime_command", required=True)

    runtime_status = runtime_sub.add_parser("status")
    runtime_status.set_defaults(func=cmd_runtime_status)

    add_runtime_efficiency_command(runtime_sub)
    add_runtime_health_summary_command(runtime_sub)

    runtime_runs = runtime_sub.add_parser("runs")
    runtime_runs.add_argument("--limit", type=int, default=50, help="Maximum recent runs to return. Use --all for an unbounded listing.")
    runtime_runs.add_argument("--all", action="store_true", help="Return all runs.")
    runtime_runs.set_defaults(func=cmd_runtime_runs)

    runtime_show = runtime_sub.add_parser("show")
    runtime_show.add_argument("run_id")
    runtime_show.add_argument(
        "--limit",
        dest="history_limit",
        type=int,
        default=None,
        help=f"Tail size for events, runtime observations, and journal events (default: {DEFAULT_RUN_HISTORY_LIMIT}).",
    )
    runtime_show.add_argument(
        "--full",
        action="store_true",
        help="Emit the full run history and bypass the observe-context budget. Expensive for agent context.",
    )
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
    runtime_wrapper.add_argument("--completion-status", choices=WRAPPER_COMPLETION_STATUSES, default="unknown")
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

    runtime_observe = runtime_sub.add_parser("observe")
    target = runtime_observe.add_mutually_exclusive_group(required=True)
    target.add_argument("--run", dest="run_id", default=None)
    target.add_argument("--session", dest="session_id", default=None)
    runtime_observe.add_argument("--runtime-profile", choices=CODING_RUNTIME_HANDOFF_TARGETS, required=True)
    # The milestone ladder plus the three terminal events. Before this the CLI
    # offered the ladder only, so `cancelled` was journalable in principle --
    # `CANONICAL_OBSERVATION_EVENTS` has always had it -- and unreachable in
    # practice: an in-process caller could append one and an operator could not.
    runtime_observe.add_argument("--event", choices=RUNTIME_OBSERVABLE_EVENTS, required=True)
    runtime_observe.add_argument("--status", choices=RUNTIME_OBSERVATION_STATUSES, default="observed")
    runtime_observe.add_argument("--participants", default="")
    runtime_observe.add_argument("--worktree-ref", default="")
    runtime_observe.add_argument("--worker-ref", default="")
    runtime_observe.add_argument("--evidence-ref", action="append")
    runtime_observe.add_argument("--summary", default="")
    runtime_observe.set_defaults(func=cmd_runtime_observe)

    progress_bind = runtime_sub.add_parser(
        "progress-bind",
        help="Create a metadata-only executor progress binding for a run or wrapper session.",
    )
    _add_progress_bind_args(progress_bind)

    progress_observe = runtime_sub.add_parser(
        "progress-observe",
        help="Record one safe executor progress observation and compact report.",
    )
    _add_progress_observe_args(progress_observe)

    progress_status = runtime_sub.add_parser(
        "progress-status",
        help="Project active/stale executor progress from persisted artifacts only.",
    )
    _add_progress_status_args(progress_status)

    progress = runtime_sub.add_parser(
        "progress",
        help="Create, observe, and project live executor progress reports.",
    )
    progress_sub = progress.add_subparsers(dest="runtime_progress_command", required=True)
    progress_bind_nested = progress_sub.add_parser(
        "bind",
        help="Create a metadata-only executor progress binding for a run or wrapper session.",
    )
    _add_progress_bind_args(progress_bind_nested)
    progress_observe_nested = progress_sub.add_parser(
        "observe",
        help="Record one safe executor progress observation and compact report.",
    )
    _add_progress_observe_args(progress_observe_nested)
    progress_status_nested = progress_sub.add_parser(
        "status",
        help="Project active/stale executor progress from persisted artifacts only.",
    )
    _add_progress_status_args(progress_status_nested)

    runtime_receipts = runtime_sub.add_parser(
        "receipts",
        help="Read observed external effect receipts. Read-only: receipts come only from acting surfaces.",
    )
    runtime_receipts.add_argument(
        "--run",
        dest="run_id",
        default=None,
        help=(
            "Limit to one runtime run. Run-less effects, such as adapter deliveries, are still listed "
            "separately, and unrecorded mints are never scoped away."
        ),
    )
    runtime_receipts.add_argument("--limit", type=int, default=50, help="Maximum recent receipts to return. Use --all for every receipt.")
    runtime_receipts.add_argument("--all", action="store_true", help="Return all receipts.")
    runtime_receipts.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    runtime_receipts.set_defaults(func=cmd_runtime_receipts)

    runtime_action_readiness = runtime_sub.add_parser(
        "action-readiness",
        help=(
            "Answer whether one requested external outcome can be done now, from recorded evidence only. "
            "Read-only: readiness above the installed tier cannot be asserted, only observed."
        ),
    )
    runtime_action_readiness.add_argument(
        "--outcome",
        dest="outcome_id",
        required=True,
        help="The requested outcome this answer is about. Matches an external effect id when one exists.",
    )
    runtime_action_readiness.add_argument(
        "--surface",
        required=True,
        help="The host or connector the outcome runs over, as recorded by host observations.",
    )
    runtime_action_readiness.add_argument(
        "--action",
        default="",
        help="One bounded line naming what the user asked for. Defaults to the outcome id.",
    )
    runtime_action_readiness.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_ACTION_READINESS_SCAN_LIMIT,
        help="Maximum recent records to scan per evidence store.",
    )
    runtime_action_readiness.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    runtime_action_readiness.set_defaults(func=cmd_runtime_action_readiness)

    runtime_approvals = runtime_sub.add_parser(
        "approvals",
        help="Read recorded approval receipts. Read-only: approvals come only from the confirmation flow.",
    )
    runtime_approvals.add_argument(
        "--run",
        dest="run_id",
        default=None,
        help="Limit to one runtime run. Unrecorded answers are never scoped away.",
    )
    runtime_approvals.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum recent approvals to return. Use --all for every approval.",
    )
    runtime_approvals.add_argument("--all", action="store_true", help="Return all approvals.")
    runtime_approvals.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    runtime_approvals.set_defaults(func=cmd_runtime_approvals)

    runtime_artifacts = runtime_sub.add_parser(
        "artifacts",
        help=(
            "Show which locally generated artifacts are current or superseded, what replaced them, why each "
            "is retained, and which could be removed. Dry run: this never deletes anything."
        ),
    )
    runtime_artifacts.add_argument(
        "--retention-days",
        dest="retention_days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help=f"Days a superseded artifact is kept before it reads as removable (default: {DEFAULT_RETENTION_DAYS}).",
    )
    runtime_artifacts.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_ARTIFACT_SCAN_LIMIT,
        help=f"Maximum recent artifacts to project per kind (default: {DEFAULT_ARTIFACT_SCAN_LIMIT}).",
    )
    runtime_artifacts.add_argument("--all", action="store_true", help="Project every stored artifact.")
    runtime_artifacts.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    runtime_artifacts.set_defaults(func=cmd_runtime_artifacts)
    runtime_artifacts_sub = runtime_artifacts.add_subparsers(dest="runtime_artifacts_command")
    add_runtime_artifacts_show_shape_command(runtime_artifacts_sub)

    runtime_validate = runtime_sub.add_parser("validate")
    runtime_validate.add_argument("--run", dest="run_id", default=None)
    runtime_validate.set_defaults(func=cmd_runtime_validate)

    runtime_export = runtime_sub.add_parser("export")
    runtime_export.add_argument("--redacted", action="store_true", default=True)
    runtime_export.add_argument("--no-redact", dest="redacted", action="store_false")
    runtime_export.add_argument("--limit", type=int, default=50, help="Maximum recent runs and wrapper sessions to include. Use --all to export all.")
    runtime_export.add_argument("--all", action="store_true", help="Export all runs and wrapper sessions.")
    runtime_export.add_argument("--run", dest="run_id", default=None, help="Export one runtime run and its journal events.")
    runtime_export.add_argument("--summary", action="store_true", help="Export run/session records without full event payloads.")
    runtime_export.set_defaults(func=cmd_runtime_export)

    runtime_team_readiness = runtime_sub.add_parser(
        "team-readiness",
        help="Inspect Hermes/team/swarm worker contract readiness without claiming worker execution.",
    )
    runtime_team_readiness.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_RUNTIME_TARGET_SCAN_LIMIT,
        help="Maximum recent runtime targets to inspect for observations. Use --all for an unbounded scan.",
    )
    runtime_team_readiness.add_argument("--all", action="store_true", help="Inspect all runtime targets.")
    runtime_team_readiness.set_defaults(func=cmd_runtime_team_readiness)

    runtime_todo = runtime_sub.add_parser(
        "todo",
        help=(
            "Agent/operator surface: declare, clear, or read the metadata-only plan todo "
            "list rendered by OMH HUD surfaces."
        ),
    )
    todo_sub = runtime_todo.add_subparsers(dest="runtime_todo_command", required=True)
    todo_set = todo_sub.add_parser("set", help="Write the todo list (agent/operator surface; items are declarations, not evidence).")
    todo_set.add_argument("--title", default="", help="Optional short plan title for the panel header.")
    todo_items = todo_set.add_mutually_exclusive_group(required=True)
    todo_items.add_argument(
        "--item",
        dest="items",
        action="append",
        default=None,
        help="Pending todo item text; repeat for multiple items in display order.",
    )
    todo_items.add_argument(
        "--items-json",
        default=None,
        help='JSON array of {"text", "state"} objects with state pending, active, or done.',
    )
    todo_set.set_defaults(func=cmd_runtime_todo_set)
    todo_clear = todo_sub.add_parser("clear", help="Remove the todo list from the HUD surfaces.")
    todo_clear.set_defaults(func=cmd_runtime_todo_clear)
    todo_show = todo_sub.add_parser("show", help="Read the current todo projection exactly as HUD surfaces see it.")
    todo_show.set_defaults(func=cmd_runtime_todo_show)
    for todo_command in (todo_set, todo_clear, todo_show):
        todo_command.add_argument(
            "--session",
            dest="session_ref",
            default="",
            help=(
                "Hermes session id the todo belongs to. Omit for the home-wide list; "
                "show without it reads as the live TUI session would."
            ),
        )
