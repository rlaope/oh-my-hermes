from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from ..coding_delegation import CODING_EXECUTOR_TARGETS, build_coding_delegation_payload, coding_delegation_record_payload
from ..coding.executor_capability_snapshots import (
    ExecutorCapabilitySnapshotError,
    build_executor_capability_snapshot,
    read_executor_capability_snapshot,
    validate_executor_capability_snapshot,
    write_executor_capability_snapshot,
)
from ..executor_readiness import EXECUTOR_READINESS_PROFILES, probe_executor_readiness
from ..hermes_planning import (
    build_plan_handoff_context_pack,
    build_plan_handoff_message,
    read_hermes_plan_artifact,
)
from ..ingress import CHAT_SOURCES, extract_message_text, extract_source_metadata
from ..installer import OmhError
from ..local_store import read_json_object
from ..memory import memory_recall_pack_for_handoff, read_handoff_context_pack_file, record_attached_recall_usage
from ..coding.product_family_templates import PRODUCT_FAMILIES, product_family_template
from ..coding.product_quality_harnesses import product_quality_harness
from ..coding.project_governance import discover_project_governance
from ..routing.intent import META_OR_FEEDBACK_INTENTS, classify_workflow_intent
from ..routing.localization import normalized_phrase, routing_tokens
from ..runtime.artifacts import append_journal_observation, create_prepared_coding_delegation_run, write_coding_delegation
from ..system.paths import OmhPaths
from ..workflows.blocked_work_records import mint_blocked_work_record
from ..workflows.role_context_packs import validate_accepted_role_context, write_role_context_pack
from ..wrapper.lifecycle import (
    CodingLifecycleError,
    record_codex_dispatch,
    record_codex_result,
    record_codex_verification,
    report_codex_delegation_lifecycle,
    start_codex_delegation_lifecycle,
)
from .common import _chat_input_and_metadata, _explicit_source_metadata, _paths, _print_json, _resolved_executor, _wants_json
from .dynamic_workflow import _add_dynamic_workflow_command, cmd_coding_dynamic_workflow
from .status_board import add_coding_status_board_command


_CAPABILITY_SNAPSHOT_CLAIM_BOUNDARY = (
    "Executor capability snapshots are metadata-only host observations. They are not execution evidence, "
    "verification, review, CI, merge-readiness, or merge evidence."
)
_CAPABILITY_SNAPSHOT_EXECUTOR_TARGETS = tuple(target for target in CODING_EXECUTOR_TARGETS if target != "choose")


def cmd_coding_delegate(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        source_metadata: dict[str, str] = {}
        plan_artifact: dict[str, object] | None = None
        context_pack = _context_pack(args)
        executor_target = _resolved_executor_for_delegate(args)
        if args.from_plan:
            if args.event_json or args.stdin or args.message:
                raise ValueError("coding delegate --from-plan cannot be combined with --stdin, --event-json, or message arguments")
            artifact = read_hermes_plan_artifact(args.from_plan)
            if artifact.get("schema_version") != "hermes_plan/v1":
                raise ValueError("coding delegate --from-plan requires a hermes_plan/v1 artifact")
            plan_status = str(artifact.get("status", ""))
            if plan_status != "accepted" and not args.allow_draft_plan:
                raise ValueError("coding delegate --from-plan requires an accepted plan; use hermes plan-accept or --allow-draft-plan")
            message = build_plan_handoff_message(artifact)
            source_metadata.update(_plan_source_metadata(artifact))
            plan_artifact = _coding_plan_artifact(artifact)
            if context_pack is None:
                context_pack = build_plan_handoff_context_pack(artifact, executor_target=executor_target)
        elif args.event_json:
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
        memory_recall_pack = memory_recall_pack_for_handoff(paths, message, executor_target=executor_target)
        payload = build_coding_delegation_payload(
            message,
            source=args.source,
            limit=args.limit,
            include_message=args.include_message or args.include_message_full,
            message_context_mode="full" if args.include_message_full else "bounded",
            source_metadata=source_metadata,
            executor_target=executor_target,
            context_pack=context_pack,
            memory_recall_pack=memory_recall_pack,
            plan_artifact=plan_artifact,
            capability_snapshot_directory=paths.omh_home / "coding" / "executor-capability-snapshots",
            project_root=args.project_root or None,
            governance_default=args.governance_default,
            product_family=args.product_family or None,
        )
        record_attached_recall_usage(paths, payload)
        if plan_artifact:
            _apply_plan_handoff_source(payload)
            _accept_handoff_role_context(paths, payload)
        if payload.get("delegation_policy") or _payload_choice_required(payload):
            from ..executor_readiness import executor_choice_context

            payload["executor_choice_context"] = executor_choice_context(paths)
        # The decision is recorded here, before anything decides whether a *run*
        # is worth creating, and unconditionally on `--record`. That ordering is
        # the whole point of the change: a denied gate collapses the selection,
        # skips the run, writes no `coding_delegation.json`, and appends no
        # journal event, so until now the one build whose reasoning most needed
        # to outlive the turn was the one that left nothing behind. The store is
        # runtime-wide precisely so it can hold a decision that has no run.
        payload["blocked_work_record"] = _record_coding_decision(paths, payload)
        runtime_skip_reason = ""
        if args.record:
            runtime_skip_reason = _coding_delegate_record_readiness_skip_reason(
                message,
                force_record=bool(args.force_record or args.from_plan),
            )
            if not runtime_skip_reason:
                runtime_skip_reason = _coding_delegate_runtime_skip_reason(payload)
            if not runtime_skip_reason:
                runtime_skip_reason = _coding_delegate_record_readiness_skip_reason(
                    message,
                    force_record=bool(args.force_record or args.from_plan),
                    require_dispatchable_requirements=True,
                )
        if runtime_skip_reason:
            if runtime_skip_reason == "requirements_or_dispatch_intent_missing":
                payload["status"] = "blocked_requirements_missing"
                payload["recorded"] = False
            payload["runtime"] = {
                "recorded": False,
                "reason": runtime_skip_reason,
                "run_created": False,
                "record_status": _coding_delegate_record_status(runtime_skip_reason),
                "record_notice": _coding_delegate_record_notice(runtime_skip_reason),
                "next_action": _coding_delegate_record_next_action(runtime_skip_reason),
            }
        elif args.record:
            delegation = payload["delegation"]
            if not isinstance(delegation, dict):
                raise OmhError("coding delegation payload is missing delegation")
            run = create_prepared_coding_delegation_run(
                paths,
                {
                    "skill": str(delegation["recommended_workflow"]),
                    "harness": str(delegation["recommended_harness"]),
                    "trigger": f"coding:{args.source}:{delegation['action']}",
                    "privacy": "metadata_only",
                    "inputs_summary": _inputs_summary(args.source, message, plan_artifact=plan_artifact),
                    "outputs_summary": f"prepared {delegation['action']} for {delegation['recommended_workflow']}",
                    "verification_summary": "prepared_not_observed; executor work is not observed by omh",
                },
            )
            record = write_coding_delegation(
                paths.runtime_runs_dir / run["run_id"],
                coding_delegation_record_payload(payload, message, source_metadata=source_metadata),
            )
            if plan_artifact:
                append_journal_observation(
                    paths,
                    {
                        "target_type": "run",
                        "target_id": run["run_id"],
                        "run_id": run["run_id"],
                        "workflow": str(delegation["recommended_workflow"]),
                        "harness": str(delegation["recommended_harness"]),
                        "phase": "prepared",
                        "event": "prepared_handoff_created",
                        "status": "observed",
                        "source": "coding_delegate_from_plan",
                        "plan_artifact": plan_artifact.get("path", ""),
                        "plan_status": plan_artifact.get("status", ""),
                        "summary": "Prepared coding handoff from accepted Hermes plan artifact.",
                    },
                )
            payload["runtime"] = {"run": run, "coding_delegation": record}
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def _record_coding_decision(paths: OmhPaths, payload: dict[str, object]) -> dict[str, object]:
    """Persist the gate's decision, and never fail the command over it.

    `mint_blocked_work_record` returns its refusals and write failures rather
    than raising, for the reason the approval store does: this runs after the
    verdict has already been reached, and letting an unwritable store fail the
    command would turn a missing record into a request that looks like it was
    never judged.

    The decision block is built by `coding.coding_delegation` from the one gate
    verdict. Nothing is re-decided here; if the block is absent the payload came
    from a path that reached no verdict, and there is no decision to record.
    """
    decision = payload.get("blocked_work_decision")
    if not isinstance(decision, dict):
        return {"recorded": False, "reason": "no_action_gate_verdict"}
    return mint_blocked_work_record(
        paths,
        source=str(decision.get("source", "")),
        outcome=str(decision.get("outcome", "")),
        reason_domain=str(decision.get("reason_domain", "")),
        reason_code=str(decision.get("reason_code", "")),
        owner=str(decision.get("owner", "")),
        safety_profile_revision=str(decision.get("safety_profile_revision", "")),
        class_shape=[str(label) for label in decision.get("class_shape", []) or []],
    )


def _coding_delegate_runtime_skip_reason(payload: dict[str, object]) -> str:
    selection = payload.get("executor_selection")
    if isinstance(selection, dict) and selection.get("choice_required") is True:
        return "executor_choice_required"
    if payload.get("work_owner_mode") == "prompt_only_handoff":
        return "prompt_only_handoff_is_wrapper_session_only"
    if payload.get("work_owner_mode") == "runtime_handoff":
        return "runtime_handoff_is_wrapper_session_only"
    if payload.get("work_owner_mode") == "retained_hermes":
        return "retained_hermes_has_no_executor_handoff"
    if payload.get("selected_executor_profile") != "codex" or not isinstance(payload.get("executor_handoff"), dict):
        return "codex_executor_handoff_required_for_runtime_record"
    return ""


def _resolved_executor_for_delegate(args: argparse.Namespace) -> str:
    if getattr(args, "executor", None):
        return str(args.executor)
    if getattr(args, "from_plan", None):
        return "codex"
    return _resolved_executor(args, default="generic")


def _plan_source_metadata(artifact: dict[str, object]) -> dict[str, str]:
    return {
        "plan_artifact_path": str(artifact.get("path", "")),
        "plan_artifact_sha256": str(artifact.get("sha256", "")),
        "plan_artifact_status": str(artifact.get("status", "")),
        "plan_task_sha256": str(artifact.get("task_statement_sha256", "")),
        "plan_task_length": str(artifact.get("task_statement_length", 0)),
    }


def _coding_plan_artifact(artifact: dict[str, object]) -> dict[str, object]:
    return {
        "path": str(artifact.get("path", "")),
        "kind": "hermes_plan",
        "schema_version": str(artifact.get("schema_version", "hermes_plan/v1")),
        "status": str(artifact.get("status", "")),
        "sha256": str(artifact.get("sha256", "")),
        "task_statement_sha256": str(artifact.get("task_statement_sha256", "")),
        "task_statement_length": int(artifact.get("task_statement_length", 0) or 0),
    }


def _accept_handoff_role_context(paths: OmhPaths, payload: dict[str, object]) -> None:
    """Acceptance gate: a plan-backed handoff names one pack hash and stores it.

    This is where "prepared" becomes "accepted" in this repository -- a coding
    handoff built from a Hermes plan artifact, which `--from-plan` refuses to
    read unless the plan carries status `accepted` or the operator explicitly
    allowed a draft. Two things happen and neither is optional: the handoff is
    refused if it does not name exactly one immutable pack hash, and the pack
    it names is written into the content-addressed store so the pin stays
    resolvable after the payload is gone.

    Storing is not a mutation of anything already accepted. The destination is
    derived from the content, so a later, different pack lands beside this one
    instead of over it, and a handoff pinned to the old hash keeps resolving to
    the old guidance.
    """
    for key in ("executor_handoff", "runtime_handoff", "prompt_handoff"):
        handoff = payload.get(key)
        if not isinstance(handoff, dict):
            continue
        errors = validate_accepted_role_context(handoff, f"coding_delegation {key}")
        if errors:
            raise ValueError("; ".join(errors))
        write_role_context_pack(paths, handoff["role_context_pack"])


def _apply_plan_handoff_source(payload: dict[str, object]) -> None:
    plan_artifact = payload.get("plan_artifact")
    plan_status = str(plan_artifact.get("status", "")) if isinstance(plan_artifact, dict) else ""
    is_draft = plan_status == "draft"
    task_source = "draft_plan_artifact" if is_draft else "accepted_plan_artifact"
    scope_instruction = (
        "Use the explicitly allowed draft Hermes plan artifact as the executor request; "
        "verify unresolved decisions before acting."
        if is_draft
        else "Use the accepted Hermes plan artifact as the executor request."
    )
    for key, brief_key in (
        ("executor_handoff", "execution_brief"),
        ("runtime_handoff", "runtime_brief"),
        ("prompt_handoff", ""),
    ):
        handoff = payload.get(key)
        if not isinstance(handoff, dict):
            continue
        if brief_key and isinstance(handoff.get(brief_key), dict):
            handoff[brief_key]["task_source"] = task_source
        scope = handoff.get("scope")
        if isinstance(scope, list):
            scope.insert(0, scope_instruction)
        handoff["dispatch_contract"] = str(handoff.get("dispatch_contract", "")) + "; plan_artifact_context_required"


def _inputs_summary(source: str, message: str, *, plan_artifact: dict[str, object] | None) -> str:
    if plan_artifact:
        plan_status = str(plan_artifact.get("status", ""))
        return (
            f"{source} coding delegation from {plan_status or 'unknown-status'} plan artifact; "
            f"plan_sha256={plan_artifact.get('sha256', '')}; message_length={len(message)}"
        )
    return f"{source} coding delegation request; message_length={len(message)}"


def _coding_delegate_record_readiness_skip_reason(
    message: str,
    *,
    force_record: bool = False,
    require_dispatchable_requirements: bool = False,
) -> str:
    intent = classify_workflow_intent(message)
    if intent.missing_requirements_cues:
        return "requirements_or_dispatch_intent_missing"
    if intent.intent_class in META_OR_FEEDBACK_INTENTS and not intent.explicit_execution:
        return "requirements_or_dispatch_intent_missing"
    if require_dispatchable_requirements and (
        not _coding_delegate_dispatch_intent_present(intent, force_record=force_record)
        or not _coding_delegate_requirements_present(message)
    ):
        return "requirements_or_dispatch_intent_missing"
    return ""


def _coding_delegate_dispatch_intent_present(intent: object, *, force_record: bool = False) -> bool:
    return bool(force_record or getattr(intent, "explicit_execution", False))


_VAGUE_RECORD_TOKENS = frozenset(
    {
        "agent",
        "code",
        "codex",
        "coding",
        "cleanup",
        "delegate",
        "fix",
        "handoff",
        "implement",
        "implementation",
        "improve",
        "maybe",
        "pr",
        "ready",
        "refactor",
        "request",
        "review",
        "risky",
        "task",
        "update",
    }
)


def _coding_delegate_requirements_present(message: str) -> bool:
    normalized = normalized_phrase(message)
    tokens = set(routing_tokens(message, stopwords=set()))
    concrete_tokens = {token for token in tokens if len(token) > 1 and token not in _VAGUE_RECORD_TOKENS}
    if len(concrete_tokens) >= 2:
        return True
    if re.search(r"(?:src|tests|docs|\.github)/|[A-Za-z_][A-Za-z0-9_./-]*\.[A-Za-z0-9]+", message):
        return True
    concrete_phrases = (
        "api",
        "module",
        "repo",
        "auth",
        "router",
        "runtime",
        "workflow",
        "기능",
        "이슈",
        "변경",
        "버그",
        "라우팅",
        "워크플로",
    )
    return any(phrase in normalized for phrase in concrete_phrases) and len(tokens) >= 3


def _coding_delegate_record_status(reason: str) -> str:
    if reason == "requirements_or_dispatch_intent_missing":
        return "blocked_requirements_missing"
    if reason == "executor_choice_required":
        return "record_skipped_until_executor_selected"
    return "record_skipped"


def _coding_delegate_record_notice(reason: str) -> str:
    if reason == "requirements_or_dispatch_intent_missing":
        return "Coding delegate record blocked until concrete requirements and explicit dispatch intent are present; no run was created."
    if reason == "executor_choice_required":
        return "Runtime record skipped until executor selected; no run was created."
    if reason == "prompt_only_handoff_is_wrapper_session_only":
        return "Runtime record skipped because prompt-only handoffs stay in wrapper session state."
    if reason == "runtime_handoff_is_wrapper_session_only":
        return "Runtime record skipped because runtime handoffs stay prepared until runtime evidence is observed."
    if reason == "retained_hermes_has_no_executor_handoff":
        return "Runtime record skipped because retained Hermes guidance has no executor handoff."
    return "Runtime record skipped because a Codex executor handoff is required before creating a run."


def _coding_delegate_record_next_action(reason: str) -> str:
    if reason == "requirements_or_dispatch_intent_missing":
        return "ask_requirements_or_prepare_plan"
    if reason == "executor_choice_required":
        return "select_executor_then_record"
    if reason == "prompt_only_handoff_is_wrapper_session_only":
        return "copy_prompt_or_select_run_backed_executor"
    if reason == "runtime_handoff_is_wrapper_session_only":
        return "observe_runtime_start_before_recording_execution"
    if reason == "retained_hermes_has_no_executor_handoff":
        return "continue_in_hermes_or_select_executor"
    return "select_codex_executor_for_run_backed_record"


def _context_pack(args: argparse.Namespace) -> dict[str, object] | None:
    path = getattr(args, "context_pack", None)
    if not path:
        return None
    return read_handoff_context_pack_file(path)


def cmd_coding_lifecycle_start(args: argparse.Namespace) -> int:
    if not args.record:
        raise OmhError("coding lifecycle start requires --record")
    if args.executor != "codex":
        raise OmhError("coding lifecycle is Codex-only for run-backed tracking; use coding delegate for prompt-only or runtime handoffs")
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
            context_pack=_context_pack(args),
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


def cmd_coding_executor_readiness(args: argparse.Namespace) -> int:
    try:
        _print_json(
            probe_executor_readiness(
                _paths(args),
                args.executor,
                force=bool(args.force),
                dry_run=bool(args.dry_run),
            )
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_coding_capability_snapshot_prepare(args: argparse.Namespace) -> int:
    try:
        _print_json(_build_capability_snapshot(args))
    except (ExecutorCapabilitySnapshotError, OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_coding_capability_snapshot_record(args: argparse.Namespace) -> int:
    try:
        snapshot = _build_capability_snapshot(args)
        path = _capability_snapshot_path(args)
        persisted = write_executor_capability_snapshot(path, snapshot)
    except (ExecutorCapabilitySnapshotError, OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "snapshot": persisted,
            "snapshot_path": str(path),
            "claim_boundary": _CAPABILITY_SNAPSHOT_CLAIM_BOUNDARY,
        }
    )
    return 0


def cmd_coding_capability_snapshot_inspect(args: argparse.Namespace) -> int:
    try:
        path = _capability_snapshot_path(args)
        snapshot = read_executor_capability_snapshot(path)
        if snapshot is None:
            raise ValueError(f"executor capability snapshot not found: {path}")
        if snapshot.get("executor") != args.executor:
            raise ValueError(f"executor capability snapshot executor does not match --executor {args.executor}")
    except (ExecutorCapabilitySnapshotError, OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "snapshot": snapshot,
            "snapshot_path": str(path),
            "claim_boundary": _CAPABILITY_SNAPSHOT_CLAIM_BOUNDARY,
        }
    )
    return 0


def cmd_coding_capability_snapshot_validate(args: argparse.Namespace) -> int:
    try:
        path = _capability_snapshot_path(args)
        snapshot = read_json_object(path)
        if snapshot is None:
            raise ValueError(f"executor capability snapshot not found: {path}")
        errors = validate_executor_capability_snapshot(snapshot)
        if snapshot.get("executor") != args.executor:
            errors.append(f"snapshot executor does not match --executor {args.executor}")
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "valid": not errors,
            "errors": errors,
            "snapshot_path": str(path),
            "claim_boundary": _CAPABILITY_SNAPSHOT_CLAIM_BOUNDARY,
        }
    )
    return 0 if not errors else 1


def _build_capability_snapshot(args: argparse.Namespace) -> dict[str, object]:
    raw = _read_capability_snapshot_json(args.capabilities_json)
    capabilities: dict[str, dict[str, object]] = {}
    for name, value in raw.items():
        if not isinstance(value, dict):
            raise ValueError("--capabilities-json values must be objects")
        capabilities[name] = value
    return build_executor_capability_snapshot(
        executor=args.executor,
        capabilities=capabilities,
        recorded_at=args.recorded_at or None,
    )


def _read_capability_snapshot_json(path_text: str) -> dict[str, object]:
    raw = sys.stdin.read() if path_text == "-" else Path(path_text).expanduser().read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("--capabilities-json must contain a JSON object")
    return value


def _capability_snapshot_path(args: argparse.Namespace) -> Path:
    explicit_path = getattr(args, "snapshot_path", "")
    if explicit_path:
        return Path(explicit_path).expanduser()
    # Same directory the readiness recheck reads at dispatch time, named once
    # on OmhPaths so the two surfaces cannot drift to different folders.
    return _paths(args).executor_capability_snapshots_dir / f"{args.executor}.json"


def cmd_coding_governance_discover(args: argparse.Namespace) -> int:
    try:
        _print_json(discover_project_governance(args.project_root, decision=args.governance_default))
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_coding_templates_show(args: argparse.Namespace) -> int:
    try:
        _print_json(product_family_template(args.family))
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_coding_quality_harness_show(args: argparse.Namespace) -> int:
    try:
        _print_json(product_quality_harness(args.family))
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def _payload_choice_required(payload: dict[str, object]) -> bool:
    selection = payload.get("executor_selection")
    return isinstance(selection, dict) and bool(selection.get("choice_required"))


def cmd_coding_model_route(args: argparse.Namespace) -> int:
    from ..coding.executors import EXECUTOR_PROFILES
    from ..coding.model_routing import (
        EXECUTOR_MODEL_OPTIONS,
        MODEL_ROLES,
        resolve_model_route,
        route_provenance,
    )

    if getattr(args, "explain", False):
        profiles = [args.executor] if args.executor else list(EXECUTOR_MODEL_OPTIONS)
        unknown = [profile for profile in profiles if profile not in EXECUTOR_MODEL_OPTIONS]
        if unknown:
            raise OmhError(f"--explain covers catalog profiles only; unknown: {', '.join(unknown)}")
        cells = []
        cell_lines = []
        for profile in profiles:
            for role in MODEL_ROLES:
                route = resolve_model_route(profile, role=role)
                provenance, _vocabulary = route_provenance(route)
                chain = route.get("chain", [])
                cells.append(
                    {
                        "executor_profile": profile,
                        "role": role,
                        "selected_model": route.get("selected_model", ""),
                        "selected_reasoning_effort": route.get("selected_reasoning_effort", ""),
                        "status": route.get("status", ""),
                        "provenance": provenance,
                        "chain": chain,
                    }
                )
                # The text line is built here, from the same locals the cell
                # was built from, so nothing re-reads provenance off a payload
                # (route_provenance is the sole sanctioned accessor).
                chain_text = " > ".join(
                    f"{entry.get('model_id')}"
                    + (f" {entry.get('reasoning_effort')}" if entry.get("reasoning_effort") else "")
                    + ("*" if entry.get("selected") else "")
                    for entry in chain
                )
                selected_model = str(route.get("selected_model", "") or "")
                selected_effort = str(route.get("selected_reasoning_effort", "") or "")
                cell_lines.append(
                    f"- {profile:12s} {role:15s} -> "
                    f"{selected_model or 'executor default'}"
                    + (f" {selected_effort}" if selected_effort else "")
                    + f"  [{provenance}]  chain: {chain_text or '-'}"
                )
        catalogless = sorted(set(EXECUTOR_PROFILES) - set(EXECUTOR_MODEL_OPTIONS) - {"choose"})
        matrix = {
            "schema_version": "coding_model_route_matrix/v1",
            "cells": cells,
            "catalogless_profiles": catalogless,
            "claim_boundary": (
                "An effective-route matrix is prepared resolution metadata only; it is not dispatch, "
                "execution, or provider availability evidence."
            ),
        }
        if _wants_json(args):
            _print_json(matrix)
            return 0
        lines = ["Effective model routes (profile x role):"] + cell_lines
        if catalogless:
            lines.append(
                "Profiles without a model catalog (executor CLI default applies): " + ", ".join(catalogless)
            )
        lines.append(str(matrix["claim_boundary"]))
        print("\n".join(lines))
        return 0

    if not args.executor:
        raise OmhError("--executor is required unless --explain is given")
    local_catalog = None
    if getattr(args, "from_inventory", False):
        local_catalog = _local_model_catalogs().get(str(args.executor or "").strip().casefold())
    route = resolve_model_route(
        args.executor,
        requested_model=args.model or "",
        requested_effort=args.effort or "",
        role=args.role or "",
        requested_domain=getattr(args, "domain", None) or "",
        requested_depth=getattr(args, "depth", None) or "",
        local_catalog=local_catalog,
    )
    if _wants_json(args):
        _print_json(route)
        return 0
    provenance, _vocabulary = route_provenance(route)
    selected = str(route.get("selected_model", "") or "")
    effort = str(route.get("selected_reasoning_effort", "") or "")
    selected_label = " ".join(part for part in (selected, effort) if part) or "executor default"
    lines = [
        f"Model route for {route['executor_profile']}: {selected_label} ({route['status']}, {provenance})",
    ]
    chain = route.get("chain", [])
    if chain:
        chain_text = " > ".join(
            f"{entry.get('model_id')}"
            + (f" {entry.get('reasoning_effort')}" if entry.get("reasoning_effort") else "")
            + ("*" if entry.get("selected") else "")
            for entry in chain
        )
        lines.append(f"chain: {chain_text}")
    effort_change = route.get("effort_change")
    if isinstance(effort_change, dict) and effort_change.get("kind") not in (None, "", "unchanged"):
        lines.append(
            f"effort: requested `{effort_change.get('requested')}` -> `{effort_change.get('selected') or 'CLI default'}` "
            f"({effort_change.get('kind')}: {effort_change.get('reason')})"
        )
    for candidate in route.get("candidates", []):
        roles = ", ".join(str(role) for role in candidate.get("recommended_roles", []))
        lines.append(f"- candidate {candidate.get('model_id')} [{candidate.get('tier')}] roles: {roles or 'any'}")
    for reason in route.get("reasons", []):
        lines.append(f"note: {reason}")
    lines.append(str(route.get("claim_boundary", "")))
    print("\n".join(lines))
    return 0


def cmd_coding_model_inventory(args: argparse.Namespace) -> int:
    from ..coding.model_inventory import local_model_inventory

    inventory = local_model_inventory()
    if _wants_json(args):
        _print_json(inventory)
        return 0
    sources = inventory.get("sources", {})
    cli_presence = sources.get("cli_presence", {}) if isinstance(sources, dict) else {}
    commands = cli_presence.get("commands", {}) if isinstance(cli_presence, dict) else {}
    on_path = sorted(command for command, found in commands.items() if found)
    lines = [
        "Local model inventory (read-time observation):",
        f"Agent CLIs on PATH: {', '.join(on_path) or 'none'}",
    ]
    models = inventory.get("available_models", [])
    if models:
        lines.append("Locally-configured models:")
        for entry in models:
            variants = ", ".join(str(variant) for variant in entry.get("variants", []))
            lines.append(
                f"- {entry.get('provider')}/{entry.get('model_id')} [{entry.get('family') or 'unknown'}]"
                + (f" variants: {variants}" if variants else "")
            )
    else:
        lines.append("Locally-configured models: none observed")
    families = inventory.get("families_present", [])
    if families:
        lines.append("Families present: " + ", ".join(str(family) for family in families))
    for note in inventory.get("domain_affinity_notes", []):
        present = ", ".join(str(family) for family in note.get("locally_present", []))
        affine = ", ".join(str(family) for family in note.get("affine_families", []))
        lines.append(f"note: {note.get('domain')} work favors {affine} (locally present: {present or 'none'})")
    if inventory.get("domain_affinity_notes"):
        lines.append(str(inventory.get("domain_affinity_claim_boundary", "")))
    for name in ("omo_agent_config", "opencode_config_providers", "opencode_auth_providers"):
        source = sources.get(name, {}) if isinstance(sources, dict) else {}
        if not isinstance(source, dict):
            continue
        detail = f"source {name}: {source.get('status', 'unknown')}"
        if source.get("rejected"):
            detail += f" ({source['rejected']} entries rejected by the metadata shape gate)"
        lines.append(detail)
    lines.append(str(inventory.get("claim_boundary", "")))
    print("\n".join(lines))
    return 0


def _local_model_catalogs() -> dict[str, dict[str, object]]:
    """Observe the local inventory once and key its derived catalog by profile.

    The I/O boundary lives here in the command layer: the route resolver and
    contract builder receive the catalog as data and stay pure.
    """
    from ..coding.model_inventory import inventory_model_catalog, local_model_inventory

    catalog = inventory_model_catalog(local_model_inventory())
    if catalog is None:
        return {}
    return {str(catalog.get("executor_profile", "")): catalog}


def cmd_coding_composition_guide(args: argparse.Namespace) -> int:
    from ..coding.model_routing import model_family
    from ..coding.unit_prompt_protocol import (
        GOAL_ECHO_PROTOCOL,
        MAIN_AGENT_COMPOSITION_CALIBRATIONS,
        REVIEW_ROLE_PROTOCOL,
        VERIFICATION_STOP_PROTOCOL,
        composition_calibration_for_model,
    )

    delegation_protocol = {
        "goal_echo": GOAL_ECHO_PROTOCOL,
        "verification_stop": VERIFICATION_STOP_PROTOCOL,
        "review_cap": REVIEW_ROLE_PROTOCOL,
        "applies_to": (
            "EVERY delegated or reviewer prompt the main agent composes — runtime-native "
            "spawns included, not only bridge-dispatched fanout units."
        ),
    }

    model = str(args.model or "").strip()
    if model:
        payload: dict[str, object] = {
            "schema_version": "composition_guide/v1",
            "model_id": model,
            "family": model_family(model) or "unknown",
            "calibration": composition_calibration_for_model(model),
            "delegation_protocol": delegation_protocol,
        }
        if _wants_json(args):
            _print_json(payload)
            return 0
        print(f"Composition guidance for `{model}` ({payload['family']} family):")
        print(str(payload["calibration"]))
        print("Delegation protocol (embed in every delegated or reviewer prompt, runtime-native included):")
        print(f"- {GOAL_ECHO_PROTOCOL}")
        print(f"- {VERIFICATION_STOP_PROTOCOL}")
        print(f"- {REVIEW_ROLE_PROTOCOL}")
        return 0
    payload = {
        "schema_version": "composition_guide/v1",
        "calibrations": dict(MAIN_AGENT_COMPOSITION_CALIBRATIONS),
        "delegation_protocol": delegation_protocol,
    }
    if _wants_json(args):
        _print_json(payload)
        return 0
    lines = ["Main-agent composition calibrations by model family:"]
    for family, block in MAIN_AGENT_COMPOSITION_CALIBRATIONS.items():
        lines.append(f"- {family}: {block}")
    print("\n".join(lines))
    return 0


def cmd_coding_fanout_prepare(args: argparse.Namespace) -> int:
    from ..coding.fanout import build_fanout_contract, is_degenerate_single_unit, single_unit_redirect
    from ..coding.fanout_artifacts import write_fanout_contract
    from ..coding.fanout_contracts import FanoutContractError
    from ..coding.model_routing import EXECUTOR_MODEL_OPTIONS

    units = _read_fanout_units(args.units)
    if is_degenerate_single_unit(units):
        _print_json(single_unit_redirect(units))
        return 0
    # The inventory is observed only when some unit names a profile without a
    # built-in catalog — a codex/claude-only contract must stay byte-identical
    # across machines regardless of what local config exists.
    needs_inventory = any(
        isinstance(unit, dict)
        and str(unit.get("owner", "") or "")
        and str(unit.get("owner", "") or "") not in EXECUTOR_MODEL_OPTIONS
        for unit in units
    )
    try:
        contract = build_fanout_contract(
            " ".join(args.goal).strip(),
            units,
            source=args.source,
            source_metadata=_explicit_source_metadata(args),
            local_catalogs=_local_model_catalogs() if needs_inventory else {},
        )
    except FanoutContractError as exc:
        raise OmhError(str(exc)) from exc
    if args.record:
        contract = write_fanout_contract(_paths(args), contract)
    _print_json(contract)
    return 0


def cmd_coding_fanout_validate(args: argparse.Namespace) -> int:
    from ..coding.fanout import detect_boundary_overlaps, merge_order, validate_fanout_units, _normalized_unit
    from ..coding.fanout_contracts import FanoutContractError

    units = [_normalized_unit(unit, index) for index, unit in enumerate(_read_fanout_units(args.units))]
    try:
        validate_fanout_units(units)
        notes = detect_boundary_overlaps(units)
        order = merge_order(units)
    except FanoutContractError as exc:
        _print_json({"schema_version": "fanout_validation/v1", "ok": False, "error": str(exc)})
        return 1
    _print_json(
        {
            "schema_version": "fanout_validation/v1",
            "ok": True,
            "unit_count": len(units),
            "merge_order": order,
            "conflict_risk_notes": notes,
        }
    )
    return 0


def cmd_coding_fanout_show(args: argparse.Namespace) -> int:
    from ..coding.fanout_artifacts import read_fanout_contract
    from ..runtime.artifacts import show_run
    from ..runtime.context_budget import payload_fingerprint, run_context_budget, smaller_payload

    paths = _paths(args)
    try:
        contract = read_fanout_contract(paths, args.fanout_id)
    except (OSError, ValueError) as exc:
        raise OmhError(f"fanout contract not found: {exc}") from exc

    full = bool(getattr(args, "full", False))
    history_limit = None if full else _fanout_history_limit(args)
    units = contract.get("units", [])
    status_by_unit: dict[str, object] = {}
    watched_runs: list[str] = []
    exhausted_units: list[str] = []
    for unit in units:
        if not isinstance(unit, dict):
            continue
        run_ref = str(unit.get("run_ref", ""))
        observed = "not_observed"
        latest_event = ""
        history: dict[str, object] = {}
        if run_ref and (paths.runtime_runs_dir / run_ref / "run.json").exists():
            try:
                shown = show_run(paths, run_ref, history_limit=history_limit)
            except (OSError, ValueError, KeyError):
                shown = None
            if isinstance(shown, dict):
                watched_runs.append(run_ref)
                shown_history = shown.get("history")
                if isinstance(shown_history, dict):
                    journal_bounds = shown_history.get("journal_events")
                    history = journal_bounds if isinstance(journal_bounds, dict) else {}
                events = [event for event in shown.get("journal_events", []) or [] if isinstance(event, dict)]
                if events:
                    latest = events[-1]
                    latest_event = str(latest.get("event", ""))
                    observed = str(latest.get("status", "not_observed"))
                else:
                    observed = "run_recorded_no_observations"
                if run_context_budget(paths, run_ref, surface="fanout_show")["exhausted"]:
                    exhausted_units.append(str(unit.get("unit_id")))
        status_by_unit[str(unit.get("unit_id"))] = {
            "prepared_status": unit.get("status", "prepared"),
            "observed_run_status": observed,
            "latest_observed_event": latest_event,
            "run_ref": run_ref,
            "journal_event_counts": history,
        }
    board = {
        "schema_version": "fanout_board/v1",
        "fanout_id": contract.get("fanout_id"),
        "merge_order": contract.get("merge_plan", {}).get("merge_order", []),
        "units": status_by_unit,
    }
    fingerprint = payload_fingerprint(board)
    context_budget = {
        "history_limit": history_limit,
        "watched_run_count": len(watched_runs),
        "budget_exhausted_units": exhausted_units,
        "policy": "timed_polling_rejected; raw_log_dumping_rejected",
        "next_action": (
            "read_full_history_from_artifacts_instead_of_repeating_this_command"
            if exhausted_units
            else "wait_for_executor_evidence"
        ),
    }
    if not full and _fanout_board_unchanged(paths, watched_runs, fingerprint):
        full_board = {**board, "context_budget": context_budget, "claim_boundary": contract.get("claim_boundary", "")}
        payload = smaller_payload(full_board, {
            "schema_version": "fanout_board_unchanged/v1",
            "fanout_id": contract.get("fanout_id"),
            "unchanged_since_last_emission": True,
            "delta": {},
            "context_budget": context_budget,
            "next_action": "wait_for_new_observed_evidence_instead_of_repeating_this_command",
            "full_output_command": f"omh coding fanout show {contract.get('fanout_id')} --full",
            "claim_boundary": contract.get("claim_boundary", ""),
        })
    else:
        payload = {**board, "context_budget": context_budget, "claim_boundary": contract.get("claim_boundary", "")}
    _print_json(payload)
    _record_fanout_board_emission(paths, watched_runs, payload, fingerprint)
    return 0


_FANOUT_BRIEF_SUMMARY_LIMIT = 200
# The generic messenger soft ceiling (`max_recommended_chars` in
# `_MESSENGER_GENERIC_CEILING`, src/wrapper/contract.py). Mirrored as a local
# constant because a command module must not reach into wrapper internals for
# one integer. Past it, the plain-text brief keeps the first rows that fit and
# states the omission instead of emitting output a messenger clips arbitrarily.
_FANOUT_BRIEF_TEXT_SOFT_LIMIT = 1600
_FANOUT_BRIEF_CLAIM_BOUNDARY = (
    "A fanout briefing joins the frozen contract with observed dispatch and journal metadata only. "
    "It is not verification, review, CI, merge-readiness, or merge evidence; unknown fields stay "
    "unknown rather than being inferred."
)


def cmd_coding_fanout_brief(args: argparse.Namespace) -> int:
    from ..coding.fanout_artifacts import fanout_dispatch_summary_path, read_fanout_contract
    from ..coding.fanout_contracts import PREPARED_NOT_OBSERVED
    from ..coding.status_board import model_label_for
    from ..local_store import read_json_object_result
    from ..runtime.artifacts import show_run
    from ..system.metadata_safety import redact_metadata_text

    paths = _paths(args)
    fanout_id = getattr(args, "fanout_id", None)
    if not fanout_id:
        listing = _fanout_brief_listing(paths)
        if _wants_json(args):
            _print_json(listing)
        else:
            print(_render_fanout_brief_listing_text(listing))
        return 0
    try:
        contract = read_fanout_contract(paths, fanout_id)
    except (OSError, ValueError) as exc:
        raise OmhError(f"fanout contract not found: {exc}") from exc
    dispatch_summary, summary_error = read_json_object_result(fanout_dispatch_summary_path(paths, str(fanout_id)))
    dispatched_units = {
        str(entry.get("unit_id", "")): entry
        for entry in (dispatch_summary or {}).get("units", [])
        if isinstance(entry, dict)
    }
    units = []
    watched_runs: list[str] = []
    merge_plan = contract.get("merge_plan", {}) if isinstance(contract.get("merge_plan"), dict) else {}
    merge_order = [str(unit_id) for unit_id in merge_plan.get("merge_order", [])]
    contract_units = [unit for unit in contract.get("units", []) if isinstance(unit, dict)]
    # Brief follows the merge plan like the dispatch wavefront does; contract
    # units missing from the plan (defensive only) keep their contract order.
    order_index = {unit_id: index for index, unit_id in enumerate(merge_order)}
    contract_units.sort(key=lambda unit: order_index.get(str(unit.get("unit_id", "")), len(order_index)))
    for unit in contract_units:
        unit_id = str(unit.get("unit_id", ""))
        handoff = unit.get("handoff", {}) if isinstance(unit.get("handoff"), dict) else {}
        model_route = handoff.get("model_route", {}) if isinstance(handoff.get("model_route"), dict) else {}
        dispatched = dispatched_units.get(unit_id, {})
        run_ref = str(unit.get("run_ref", ""))
        latest_summary = ""
        observed_status = "not_observed"
        if run_ref and (paths.runtime_runs_dir / run_ref / "run.json").exists():
            try:
                shown = show_run(paths, run_ref, history_limit=1)
            except (OSError, ValueError, KeyError):
                shown = None
            if isinstance(shown, dict):
                watched_runs.append(run_ref)
                events = [event for event in shown.get("journal_events", []) or [] if isinstance(event, dict)]
                if events:
                    # Journal summaries written before the write-site redaction
                    # landed may still carry raw output; redact again at this
                    # egress so the briefing never re-exports it.
                    latest_summary = redact_metadata_text(
                        str(events[-1].get("summary", "")), limit=_FANOUT_BRIEF_SUMMARY_LIMIT
                    )
                    observed_status = str(events[-1].get("status", "not_observed"))
                else:
                    observed_status = "run_recorded_no_observations"
        status = str(dispatched.get("status", "") or "") or PREPARED_NOT_OBSERVED
        model_id = str(model_route.get("selected_model", "") or "")
        effort = str(model_route.get("selected_reasoning_effort", "") or "")
        # One human-readable label per subagent, e.g. "gpt-5-codex xhigh" —
        # what a briefing renders next to the unit without joining two fields.
        # The format is a stable part of fanout_briefing/v1 and is built by
        # the same `model_label_for` helper the status board uses, so the two
        # surfaces cannot drift apart. The chain alternative ships as the
        # separate additive `model_alternative` field, never as a suffix here.
        model_label = model_label_for(model_id, effort)
        chain = model_route.get("chain", []) if isinstance(model_route.get("chain"), list) else []
        model_alternative = str(chain[1].get("model_id", "")) if len(chain) > 1 and isinstance(chain[1], dict) else ""
        route_version = str(model_route.get("schema_version", "") or "") if model_route else ""
        units.append(
            {
                "unit_id": unit_id,
                "owner": str(handoff.get("executor_target", "choose")),
                "model": model_id or "executor_default",
                "reasoning_effort": effort,
                "model_label": model_label,
                "model_alternative": model_alternative,
                "route_schema_version": route_version,
                "session_ref": str(dispatched.get("session_ref", "") or "") or "unknown",
                "status": status,
                "observed_run_status": observed_status,
                "elapsed_seconds": dispatched.get("duration_seconds", "unknown"),
                "tokens_total": dispatched.get("tokens_total", "unknown"),
                "limit_shaped": bool(dispatched.get("limit_shaped", False)),
                "summary": latest_summary,
            }
        )
    payload = {
        "schema_version": "fanout_briefing/v1",
        "fanout_id": contract.get("fanout_id"),
        "merge_order": merge_order,
        "dispatch_observed_at": (dispatch_summary or {}).get("observed_at", ""),
        "units": units,
        "generated_from": ["fanout_contract", "dispatch_summary", "run_journal"],
        "claim_boundary": _FANOUT_BRIEF_CLAIM_BOUNDARY,
    }
    if summary_error:
        payload["summary_error"] = str(summary_error)
    if _wants_json(args):
        _print_json(payload)
    else:
        print(_render_fanout_brief_text(payload))
    _record_fanout_brief_emission(paths, watched_runs, payload)
    return 0


from ..coding.model_routing import CODING_MODEL_ROUTE_V1_SCHEMA_VERSION as _MODEL_ROUTE_V1_VERSION


def _render_fanout_brief_text(payload: dict) -> str:
    header = f"Fanout {payload.get('fanout_id')} briefing:"
    unit_lines = [_fanout_brief_unit_line(unit) for unit in payload.get("units", [])]
    trailer_lines = []
    if payload.get("summary_error"):
        trailer_lines.append(f"warning: dispatch summary unreadable ({payload['summary_error']})")
    trailer_lines.append(str(payload.get("claim_boundary", "")))
    text = "\n".join([header, *unit_lines, *trailer_lines])
    if len(text) <= _FANOUT_BRIEF_TEXT_SOFT_LIMIT:
        return text
    # Keep the longest row prefix that fits under the messenger soft ceiling
    # together with the omission line; the omission is stated as its own line
    # so a reader never mistakes a truncated brief for a complete one.
    keep = len(unit_lines) - 1
    while keep > 0:
        candidate = "\n".join(
            [header, *unit_lines[:keep], _fanout_brief_overflow_line(len(unit_lines) - keep), *trailer_lines]
        )
        if len(candidate) <= _FANOUT_BRIEF_TEXT_SOFT_LIMIT:
            return candidate
        keep -= 1
    return "\n".join([header, _fanout_brief_overflow_line(len(unit_lines)), *trailer_lines])


def _fanout_brief_unit_line(unit: dict) -> str:
    elapsed = unit.get("elapsed_seconds", "unknown")
    elapsed_text = f"{elapsed}s" if isinstance(elapsed, (int, float)) else "elapsed unknown"
    tokens = unit.get("tokens_total", "unknown")
    tokens_text = f"{tokens} tokens" if isinstance(tokens, (int, float)) else "tokens unknown"
    # The (alt: …) suffix lives in plain text only; a route without a
    # second chain entry (including every v1 route) renders no suffix at
    # all — a chain that does not exist is not an unknown value.
    model_text = str(unit.get("model_label", "executor default"))
    alternative = str(unit.get("model_alternative", "") or "")
    if alternative:
        model_text += f", alt: {alternative}"
    route_version = str(unit.get("route_schema_version", "") or "")
    if route_version == _MODEL_ROUTE_V1_VERSION:
        model_text += " [schema v1]"
    parts = [
        str(unit.get("unit_id", "")),
        # Owner and model are ONE field visually: "codex (gpt-5-codex xhigh)".
        # The status board's bullet renderer abandoned the standalone
        # "— (model)" field because a dash around a parenthetical doubled the
        # separator; the brief follows the same convention.
        f"{unit.get('owner', '')} ({model_text})",
        str(unit.get("status", "")),
        elapsed_text,
        tokens_text,
        f"session {unit.get('session_ref', 'unknown')}",
    ]
    line = "- " + " — ".join(parts)
    summary = str(unit.get("summary", "") or "")
    if summary:
        line += f" — {summary}"
    return line


def _fanout_brief_overflow_line(omitted: int) -> str:
    return f"… +{omitted} more units — omh coding fanout brief --json"


def _render_fanout_brief_listing_text(listing: dict) -> str:
    fanouts = listing.get("fanouts", [])
    if not fanouts:
        return "No fanout contracts recorded."
    lines = ["Known fanouts:"]
    for entry in fanouts:
        observed = entry.get("last_dispatch_observed_at") or "never dispatched"
        lines.append(f"- {entry.get('fanout_id')} — {entry.get('unit_count')} units — last dispatch: {observed}")
    lines.append(str(listing.get("next_action", "")))
    return "\n".join(lines)


def _record_fanout_brief_emission(paths, watched_runs: list[str], payload: dict) -> None:
    from ..runtime.context_budget import record_context_emission

    if not watched_runs:
        return
    per_run = len(json.dumps(payload, sort_keys=True)) // len(watched_runs)
    for run_ref in watched_runs:
        record_context_emission(paths, run_ref, surface="fanout_brief", byte_count=per_run)


def _fanout_brief_listing(paths) -> dict[str, object]:
    from ..coding.fanout_artifacts import fanout_dispatch_summary_path
    from ..local_store import read_json_object_result

    entries = []
    contracts_dir = paths.fanout_contracts_dir
    if contracts_dir.is_dir():
        for child in sorted(contracts_dir.iterdir()):
            contract_path = child / "fanout_contract.json"
            if not contract_path.is_file():
                continue
            try:
                summary_path = fanout_dispatch_summary_path(paths, child.name)
            except ValueError:
                # A stray directory that does not match the fanout id pattern
                # is not a managed contract; skip it rather than guessing.
                continue
            contract, _ = read_json_object_result(contract_path)
            summary, _ = read_json_object_result(summary_path)
            entries.append(
                {
                    "fanout_id": child.name,
                    "unit_count": len((contract or {}).get("units", [])),
                    "last_dispatch_observed_at": (summary or {}).get("observed_at", ""),
                }
            )
    return {
        "schema_version": "fanout_briefing_listing/v1",
        "fanouts": entries,
        "next_action": "run `omh coding fanout brief <fanout-id>` for one fanout's unit briefing",
        "claim_boundary": _FANOUT_BRIEF_CLAIM_BOUNDARY,
    }


def _fanout_board_unchanged(paths, watched_runs: list[str], fingerprint: str) -> bool:
    """True when every watched run already saw exactly this board.

    The ledger is keyed per run while the board spans several, so a board only
    counts as unchanged if no watched run has newer state than the last
    emission. A partially-changed board still prints in full.
    """
    from ..runtime.context_budget import run_context_budget

    if not watched_runs:
        return False
    return all(
        run_context_budget(paths, run_ref, surface="fanout_show")["last_payload_fingerprint"] == fingerprint
        for run_ref in watched_runs
    )


def _fanout_history_limit(args: argparse.Namespace) -> int:
    from ..runtime.artifacts import DEFAULT_RUN_HISTORY_LIMIT

    limit = getattr(args, "history_limit", None)
    if limit is None:
        return DEFAULT_RUN_HISTORY_LIMIT
    if int(limit) < 1:
        raise OmhError("--limit must be at least 1 unless --full is set")
    return int(limit)


def _record_fanout_board_emission(paths, watched_runs: list[str], payload: dict, fingerprint: str = "") -> None:
    from ..runtime.context_budget import record_context_emission

    if not watched_runs:
        return
    per_run = len(json.dumps(payload, sort_keys=True)) // len(watched_runs)
    for run_ref in watched_runs:
        record_context_emission(
            paths,
            run_ref,
            surface="fanout_show",
            byte_count=per_run,
            payload_fingerprint_value=fingerprint,
        )


def cmd_coding_fanout_dispatch(args: argparse.Namespace) -> int:
    import subprocess as _subprocess

    from ..coding.fanout_artifacts import read_fanout_contract
    from ..coding.fanout_dispatch import dispatch_fanout

    paths = _paths(args)
    try:
        contract = read_fanout_contract(paths, args.fanout_id)
    except (OSError, ValueError) as exc:
        raise OmhError(f"fanout contract not found: {exc}") from exc
    goal_text = sys.stdin.read() if args.goal_file == "-" else Path(args.goal_file).expanduser().read_text(encoding="utf-8")
    repo_root = Path(args.repo_root).expanduser().resolve()
    resolved = _subprocess.run(
        ["git", "rev-parse", args.base_ref],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        timeout=30,
    )
    if resolved.returncode != 0:
        raise OmhError(f"could not resolve --base-ref {args.base_ref!r} in {repo_root}: {resolved.stderr.strip()}")
    try:
        summary = dispatch_fanout(
            paths,
            contract,
            goal_text=goal_text,
            repo_root=repo_root,
            base_sha=resolved.stdout.strip(),
            concurrency=args.concurrency,
            timeout=args.timeout,
            only_units=args.unit,
            dry_run=bool(args.dry_run),
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(summary)
    return 0


def _read_fanout_units(units_arg: str) -> list[dict[str, object]]:
    raw = sys.stdin.read() if units_arg == "-" else Path(units_arg).expanduser().read_text(encoding="utf-8")
    payload = json.loads(raw)
    units = payload.get("units") if isinstance(payload, dict) else payload
    if not isinstance(units, list):
        raise OmhError("fanout units input must be a JSON list (or an object with a 'units' list)")
    return units


def _add_coding_commands(sub) -> None:
    coding = sub.add_parser("coding", help="Prepare executor-neutral or tracked coding handoff artifacts.")
    coding_sub = coding.add_subparsers(dest="coding_command", required=True)

    fanout = coding_sub.add_parser(
        "fanout",
        help="Validate and freeze a proposed parallel work split into a fanout contract (agent/backend surface).",
    )
    fanout_sub = fanout.add_subparsers(dest="fanout_command", required=True)

    fanout_prepare = fanout_sub.add_parser("prepare")
    fanout_prepare.add_argument("--goal", nargs="+", required=True, help="Accepted user goal being split.")
    fanout_prepare.add_argument("--units", required=True, help="JSON unit list path, or '-' for stdin.")
    fanout_prepare.add_argument("--source", choices=CHAT_SOURCES, default="generic")
    fanout_prepare.add_argument("--record", action="store_true", help="Persist the contract under ~/.omh/coding/fanout/.")
    fanout_prepare.set_defaults(func=cmd_coding_fanout_prepare)

    fanout_validate = fanout_sub.add_parser("validate")
    fanout_validate.add_argument("--units", required=True, help="JSON unit list path, or '-' for stdin.")
    fanout_validate.set_defaults(func=cmd_coding_fanout_validate)

    fanout_show = fanout_sub.add_parser("show")
    fanout_show.add_argument("fanout_id")
    fanout_show.add_argument(
        "--limit",
        dest="history_limit",
        type=int,
        default=None,
        help="Per-unit run history tail read while projecting the board (default: 20).",
    )
    fanout_show.add_argument(
        "--full",
        action="store_true",
        help="Read each unit's full run history. Expensive for agent context.",
    )
    fanout_show.set_defaults(func=cmd_coding_fanout_show)

    fanout_dispatch = fanout_sub.add_parser(
        "dispatch",
        help="Opt-in local bridge: spawn each unit's local agent CLI in an isolated worktree (never merges).",
    )
    fanout_dispatch.add_argument("fanout_id")
    fanout_dispatch.add_argument("--goal-file", required=True, help="File with the goal text frozen at prepare time ('-' for stdin).")
    fanout_dispatch.add_argument("--repo-root", default=".", help="Repository the unit worktrees branch from.")
    fanout_dispatch.add_argument("--base-ref", default="HEAD", help="Ref resolved once to a SHA all unit branches start from.")
    fanout_dispatch.add_argument("--concurrency", type=int, default=2)
    fanout_dispatch.add_argument("--timeout", type=int, default=1800, help="Per-unit subprocess timeout in seconds.")
    fanout_dispatch.add_argument("--unit", action="append", default=None, help="Dispatch only these unit ids (repeatable).")
    fanout_dispatch.add_argument("--dry-run", action="store_true", help="Resolve readiness, argv, and worktree paths; spawn nothing.")
    fanout_dispatch.set_defaults(func=cmd_coding_fanout_dispatch)

    fanout_brief = fanout_sub.add_parser(
        "brief",
        help="Join the frozen contract with observed dispatch/journal metadata into one per-unit briefing.",
    )
    fanout_brief.add_argument("fanout_id", nargs="?", default=None, help="Fanout id; omit to list known fanouts.")
    fanout_brief.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    fanout_brief.set_defaults(func=cmd_coding_fanout_brief)

    model_route = coding_sub.add_parser(
        "model-route",
        help="Resolve the prepared model route for one executor profile (metadata only, never invocation).",
    )
    model_route.add_argument(
        "--executor",
        default=None,
        help="Executor profile, for example codex or claude-code. Required unless --explain is given.",
    )
    model_route.add_argument("--model", default=None, help="Explicit model id; always passes through unvalidated.")
    model_route.add_argument("--effort", default=None, help="Reasoning effort for profiles that support one.")
    model_route.add_argument("--role", default=None, help="Subagent role: brain, implementation, design_visual, review, docs, research.")
    model_route.add_argument(
        "--explain",
        action="store_true",
        help="Render the effective profile x role resolution matrix with full chains and provenance.",
    )
    model_route.add_argument(
        "--domain",
        default=None,
        help=(
            "Declared work domain (for example x_platform_data); advisorily reorders a "
            "locally-derived chain toward affine families, recorded in the route, never a veto."
        ),
    )
    model_route.add_argument(
        "--depth",
        default=None,
        help="Research-lane depth dial: shallow, standard, or deep (explicit, never inferred).",
    )
    model_route.add_argument(
        "--from-inventory",
        action="store_true",
        dest="from_inventory",
        help=(
            "Consult the locally-derived model catalog (fingerprint-recorded) for profiles without "
            "a built-in catalog; built-in catalogs always win."
        ),
    )
    model_route.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    model_route.set_defaults(func=cmd_coding_model_route)

    model_inventory = coding_sub.add_parser(
        "model-inventory",
        help="Report which coding models are locally activated (metadata-only, reporting-only).",
    )
    model_inventory.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    model_inventory.set_defaults(func=cmd_coding_model_inventory)

    composition_guide = coding_sub.add_parser(
        "composition-guide",
        help="Composition calibration for the MAIN agent's own model family (how to compose splits and unit prompts).",
    )
    composition_guide.add_argument(
        "--model",
        default=None,
        help="The main agent's own model id (for example claude-fable-5, gpt-5.6-sol, kimi-k3); omit to list all families.",
    )
    composition_guide.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    composition_guide.set_defaults(func=cmd_coding_composition_guide)

    add_coding_status_board_command(coding_sub)

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
        default=None,
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
        help="Include bounded previews and artifact refs for the raw message and expanded delegation prompt.",
    )
    delegate.add_argument(
        "--include-message-full",
        action="store_true",
        help="Include the verbatim raw message and expanded prompts. For wrappers that dispatch the prompt directly.",
    )
    delegate.add_argument("--record", action="store_true", help="Record a metadata-only coding delegation artifact under .omh/runtime.")
    delegate.add_argument(
        "--force-record",
        action="store_true",
        help="Override the meta/test readiness guard when an operator intentionally records a prepared Codex handoff.",
    )
    delegate.add_argument(
        "--context-pack",
        default=None,
        help="Optional handoff_context_pack/v1 JSON to attach to the prepared executor prompt when conflict-free.",
    )
    delegate.add_argument(
        "--from-plan",
        default=None,
        help="Read an accepted hermes_plan/v1 Markdown artifact and use it as executor context.",
    )
    delegate.add_argument(
        "--allow-draft-plan",
        action="store_true",
        help="Allow --from-plan to use a draft plan. Intended only for explicit operator overrides.",
    )
    delegate.add_argument("--source-event-id", default="", help="Optional source message/event id to store as metadata.")
    delegate.add_argument("--channel-ref", default="", help="Optional channel reference to store as metadata.")
    delegate.add_argument("--user-ref", default="", help="Optional user reference to store as metadata.")
    delegate.add_argument("--project-root", default="", help="Explicit project root for read-only governance discovery.")
    delegate.add_argument(
        "--governance-default",
        choices=("not_applicable", "accept", "decline"),
        default="not_applicable",
        help="Explicit advisory-default decision for a project without discovered governance.",
    )
    delegate.add_argument("--product-family", choices=PRODUCT_FAMILIES, default="", help="Optional prepared product-family template.")
    delegate.set_defaults(func=cmd_coding_delegate)

    governance = coding_sub.add_parser("governance", help="Discover explicit-root project governance for prepared handoffs.")
    governance_sub = governance.add_subparsers(dest="governance_command", required=True)
    discover = governance_sub.add_parser("discover")
    discover.add_argument("--project-root", required=True, help="Explicit project root to inspect read-only.")
    discover.add_argument("--governance-default", choices=("not_applicable", "accept", "decline"), default="not_applicable")
    discover.set_defaults(func=cmd_coding_governance_discover)

    templates = coding_sub.add_parser("templates", help="Show prepared product-family coding templates.")
    templates_sub = templates.add_subparsers(dest="templates_command", required=True)
    show_template = templates_sub.add_parser("show")
    show_template.add_argument("--family", choices=PRODUCT_FAMILIES, required=True)
    show_template.set_defaults(func=cmd_coding_templates_show)

    quality_harness = coding_sub.add_parser("quality-harness", help="Show prepared product-family quality harness guidance.")
    quality_harness_sub = quality_harness.add_subparsers(dest="quality_harness_command", required=True)
    show_quality_harness = quality_harness_sub.add_parser("show")
    show_quality_harness.add_argument("--family", choices=PRODUCT_FAMILIES, required=True)
    show_quality_harness.set_defaults(func=cmd_coding_quality_harness_show)

    _add_dynamic_workflow_command(coding_sub)
    _add_capability_snapshot_commands(coding_sub)

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
    lifecycle_start.add_argument("--executor", choices=CODING_EXECUTOR_TARGETS, default="codex", help="Coding executor target.")
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
    lifecycle_start.add_argument(
        "--context-pack",
        default=None,
        help="Optional handoff_context_pack/v1 JSON to attach to the prepared Codex lifecycle handoff when conflict-free.",
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

    readiness = coding_sub.add_parser(
        "executor-readiness",
        help="Probe or preview first-use coding agent readiness for wrapper fallback decisions.",
    )
    readiness.add_argument("--executor", choices=EXECUTOR_READINESS_PROFILES, required=True)
    readiness.add_argument("--force", action="store_true", help="Run the probe even if a first-use result is already cached.")
    readiness.add_argument("--dry-run", action="store_true", help="Return the probe contract without running or caching it.")
    readiness.set_defaults(func=cmd_coding_executor_readiness)


def _add_capability_snapshot_commands(coding_sub) -> None:
    snapshots = coding_sub.add_parser(
        "capability-snapshot",
        help="Prepare, persist, inspect, or validate metadata-only executor capability snapshots.",
    )
    snapshot_sub = snapshots.add_subparsers(dest="capability_snapshot_command", required=True)

    prepare = snapshot_sub.add_parser("prepare", help="Build a capability snapshot without writing it.")
    _add_capability_snapshot_build_arguments(prepare)
    prepare.set_defaults(func=cmd_coding_capability_snapshot_prepare)

    record = snapshot_sub.add_parser("record", help="Persist a capability snapshot under .omh or an explicit local path.")
    _add_capability_snapshot_build_arguments(record)
    record.add_argument("--path", dest="snapshot_path", default="", help="Optional local output path for this snapshot.")
    record.set_defaults(func=cmd_coding_capability_snapshot_record)

    inspect = snapshot_sub.add_parser("inspect", help="Read one locally persisted capability snapshot.")
    _add_capability_snapshot_read_arguments(inspect)
    inspect.set_defaults(func=cmd_coding_capability_snapshot_inspect)

    validate = snapshot_sub.add_parser("validate", help="Validate one locally persisted capability snapshot.")
    _add_capability_snapshot_read_arguments(validate)
    validate.set_defaults(func=cmd_coding_capability_snapshot_validate)


def _add_capability_snapshot_build_arguments(parser) -> None:
    parser.add_argument(
        "--executor",
        choices=_CAPABILITY_SNAPSHOT_EXECUTOR_TARGETS,
        required=True,
        help="Selected coding executor profile.",
    )
    parser.add_argument(
        "--capabilities-json",
        required=True,
        help="Path to a metadata-only JSON object keyed by supported capability name, or '-' for stdin.",
    )
    parser.add_argument("--recorded-at", default="", help="Optional ISO-8601 timestamp; defaults to the local record time.")


def _add_capability_snapshot_read_arguments(parser) -> None:
    parser.add_argument(
        "--executor",
        choices=_CAPABILITY_SNAPSHOT_EXECUTOR_TARGETS,
        required=True,
        help="Selected coding executor profile.",
    )
    parser.add_argument("--path", dest="snapshot_path", default="", help="Optional local snapshot path to inspect or validate.")
