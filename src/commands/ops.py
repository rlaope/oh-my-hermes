from __future__ import annotations

import argparse
from pathlib import Path

from ..installer import OmhError
from ..operator_productivity import (
    build_agent_operator_productivity_card,
    list_agent_operator_productivity_cards,
    show_agent_operator_productivity_card,
    summarize_agent_operator_productivity_card,
    validate_agent_operator_productivity_store,
    write_agent_operator_productivity_card,
)
from ..hermes_ops import (
    build_scheduled_ops_blueprint,
    list_hermes_ops_blueprints,
    show_hermes_ops_blueprint,
    summarize_hermes_ops_blueprint,
    validate_hermes_ops_store,
    write_hermes_ops_blueprint,
)
from ..operations import (
    ARTIFACT_STATUSES,
    KINDS_BY_SURFACE,
    SURFACES,
    build_operation_artifact,
    export_operations_bundle,
    list_operation_artifacts,
    show_operation_artifact,
    summarize_operation_artifact,
    validate_operations_store,
    write_operation_artifact,
)
from ..operations_data import (
    OPERATIONS_ANALYSIS_MODES,
    OPERATIONS_DATA_SHAPES,
    build_operations_data_harness,
)
from ..product_evidence_loop import (
    PRODUCT_EVIDENCE_LOOP_DECISIONS,
    REFERENCE_AVAILABILITIES,
    REFERENCE_PROVENANCES,
    build_product_evidence_loop,
)
from ..design_orchestration import (
    DESIGN_AUDIENCES,
    DESIGN_AVOID_PATTERNS,
    DESIGN_HIERARCHIES,
    DESIGN_LAYOUTS,
    DESIGN_MODES,
    DESIGN_PALETTES,
    DESIGN_PLATFORMS,
    DESIGN_PRIMARY_TASKS,
    DESIGN_SIGNATURE_ELEMENTS,
    DESIGN_SURFACES,
    DESIGN_TYPOGRAPHIES,
    build_design_orchestration,
)
from ..design_directions import (
    DESIGN_DIRECTION_OPTION_IDS,
    build_design_direction_set,
    render_design_direction_set_html,
)
from ..research_department import (
    build_research_department_plan,
    list_research_department_plans,
    show_research_department_plan,
    summarize_research_department_plan,
    validate_research_department_store,
    write_research_department_plan,
)
from ..workflows.recurring_intents import (
    ACTIVATION_OBSERVER_KINDS,
    BACKFILL_POSTURES,
    FAILURE_PAUSE_POSTURES,
    MISSED_RUN_POSTURES,
    OCCURRENCE_OBSERVER_KINDS,
    OCCURRENCE_OUTCOMES,
    OCCURRENCE_SITUATIONS,
    OVERLAP_POSTURES,
    OWNER_KINDS,
    RETRY_POSTURES,
    activate_recurring_intent,
    build_recurring_intent,
    decide_recurring_occurrence,
    list_recurring_intents,
    preview_recurring_intent,
    record_recurring_intent_occurrence,
    render_recurring_intent_list_text,
    render_recurring_intent_text,
    render_recurring_occurrence_decision_text,
    revise_recurring_intent,
    show_recurring_intent,
    summarize_recurring_intent,
    update_recurring_intent,
    validate_recurring_intent_store,
    write_recurring_intent,
)
from ..system.local_store import utc_now
from .common import _paths, _print_json, _wants_json


DEFAULT_OPS_LIST_LIMIT = 20
DEFAULT_OPS_EXPORT_LIMIT = 20
DEFAULT_BLUEPRINT_LIST_LIMIT = 20
DEFAULT_RESEARCH_DEPARTMENT_LIST_LIMIT = 20
DEFAULT_AGENT_OPS_LIST_LIMIT = 20
DEFAULT_RECURRING_INTENT_LIST_LIMIT = 20

RECURRING_INTENT_BOUNDARY = {
    "prepared_is_not_observed": True,
    "activated_is_not_executed": True,
    "omh_runs_no_scheduler": True,
    "host_schedule_created": False,
    "occurrence_executed_by_omh": False,
    "gateway_delivery_observed": False,
}


def cmd_ops_write(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        artifact = build_operation_artifact(
            surface=args.surface,
            kind=args.kind,
            title=args.title,
            summary=args.summary,
            status=args.status,
            observation_status=_observation_status(args),
            source=args.source,
            inputs_summary=args.inputs_summary,
            sections=args.section or [],
            decisions=args.decision or [],
            action_items=args.action or [],
            metrics=args.metric or [],
            references=args.reference or [],
            assumptions=args.assumption or [],
        )
        written = write_operation_artifact(paths, artifact)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "omh_ops_write_result/v1",
            "artifact": written,
            "store": {
                "omh_home": str(paths.omh_home),
                "operations_dir": str(paths.operations_dir),
                "index_path": str(paths.operations_index_path),
                "index_authority": "cache_only",
            },
            "boundary": {
                "prepared_is_not_observed": written["observation_status"] in {"prepared", "not_observed"},
                "ppt_scope": "markdown_or_json_outline_only",
            },
        }
    )
    return 0


def cmd_ops_data_harness(args: argparse.Namespace) -> int:
    try:
        _print_json(build_operations_data_harness(data_shape=args.data_shape, analysis_mode=args.analysis_mode))
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_ops_product_evidence_loop(args: argparse.Namespace) -> int:
    try:
        _print_json(
            build_product_evidence_loop(
                decision_scope_id=args.decision_scope_id,
                proposed_next_decision=args.proposed_next_decision,
                research_availability=args.research_availability,
                research_reference_id=args.research_reference_id,
                research_provenance=args.research_provenance,
                feedback_availability=args.feedback_availability,
                feedback_reference_id=args.feedback_reference_id,
                feedback_provenance=args.feedback_provenance,
                supplied_data_availability=args.supplied_data_availability,
                supplied_data_reference_id=args.supplied_data_reference_id,
                supplied_data_provenance=args.supplied_data_provenance,
                causal_identification_availability=args.causal_identification_availability,
                causal_identification_reference_id=args.causal_identification_reference_id,
                causal_identification_provenance=args.causal_identification_provenance,
            )
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def _context_reference_descriptor(value: str) -> tuple[str, str, str]:
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError("context_reference must be reference_kind:reference_id:provenance")
    return (parts[0], parts[1], parts[2])


def cmd_ops_design_orchestration(args: argparse.Namespace) -> int:
    try:
        _print_json(
            build_design_orchestration(
                surface=args.surface,
                audience=args.audience,
                primary_task=args.primary_task,
                platform=args.platform,
                mode=args.mode,
                context_references=tuple(_context_reference_descriptor(value) for value in args.context_reference),
                hierarchy=args.hierarchy,
                palette=args.palette,
                typography=args.typography,
                layout=args.layout,
                signature_element=args.signature_element,
                avoid_patterns=tuple(args.avoid_pattern),
            )
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def _direction_option_descriptor(value: str) -> tuple[str, str, str, str, str, str, tuple[str, ...]]:
    parts = value.split(":")
    if len(parts) != 7:
        raise ValueError(
            "option must be id:hierarchy:palette:typography:layout:signature_element:avoid1|avoid2"
        )
    avoid_patterns = tuple(pattern for pattern in parts[6].split("|") if pattern)
    if not avoid_patterns:
        raise ValueError("option must name at least one avoid pattern")
    return (parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], avoid_patterns)


def cmd_ops_design_directions(args: argparse.Namespace) -> int:
    try:
        directions = build_design_direction_set(
            surface=args.surface,
            audience=args.audience,
            primary_task=args.primary_task,
            platform=args.platform,
            mode=args.mode,
            context_references=tuple(_context_reference_descriptor(value) for value in args.context_reference),
            options=tuple(_direction_option_descriptor(value) for value in args.option),
            chosen_option=args.choose or "",
        )
        preview_path = ""
        if args.html:
            document = render_design_direction_set_html(directions)
            target = Path(args.html)
            target.parent.mkdir(parents=True, exist_ok=True)
            # newline="" so the document is byte-identical on Windows; a
            # rendered artifact that differs by platform cannot be compared.
            with target.open("w", encoding="utf-8", newline="") as handle:
                handle.write(document)
            preview_path = str(target)
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args):
        payload = dict(directions)
        if preview_path:
            payload["preview_path"] = preview_path
        _print_json(payload)
        return 0
    offered = ", ".join(str(option["option_id"]) for option in directions["options"])
    print(f"Design directions for {directions['intent']['surface']}: option {offered}")
    for option in directions["options"]:
        marker = " (chosen)" if option["option_id"] == directions["chosen_option"] else ""
        print(
            f"  {option['option_id']}{marker}: {option['hierarchy']} / {option['palette']} / "
            f"{option['typography']} / {option['layout']} / {option['signature_element']}"
        )
    if preview_path:
        print(f"Preview written to {preview_path} - open it yourself; nothing was served or launched.")
    if directions["chosen_option"]:
        print(f"Choice recorded: {directions['chosen_option']}.")
    else:
        print("No choice recorded yet. Re-run with --choose <id> once you have looked.")
    print("Prepared only. This is not implementation, visual QA, or evidence that anyone looked at the preview.")
    return 0


def cmd_ops_blueprint(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        blueprint = build_scheduled_ops_blueprint(
            " ".join(args.request),
            title=args.title,
            schedule=args.schedule,
            delivery=args.delivery,
            silence=args.silence,
            source=args.source,
        )
        written = blueprint if args.dry_run else write_hermes_ops_blueprint(paths, blueprint)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "omh_ops_blueprint_result/v1",
            "blueprint": written,
            "store": {
                "omh_home": str(paths.omh_home),
                "hermes_ops_dir": str(paths.hermes_ops_dir),
                "blueprints_dir": str(paths.hermes_ops_blueprints_dir),
                "index_path": str(paths.hermes_ops_index_path),
                "index_authority": "cache_only",
                "written": not args.dry_run,
            },
            "boundary": {
                "prepared_is_not_observed": True,
                "runtime_execution_observed": False,
                "gateway_delivery_observed": False,
                "source_retrieval_observed": False,
                "not_evidence_until_observed": list(written["not_evidence_until_observed"]),
                "observed_evidence_required": list(written["observed_evidence_required"]),
            },
        }
    )
    return 0


def cmd_ops_recurring_intent(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        intent = build_recurring_intent(
            " ".join(args.request),
            title=args.title,
            schedule=args.schedule,
            delivery=args.delivery,
            silence=args.silence,
            scope=args.scope_note,
            owner=args.owner,
            owner_kind=args.owner_kind,
            overlap_posture=args.overlap_posture,
            missed_run_posture=args.missed_run_posture,
            retry_posture=args.retry_posture,
            retry_max_attempts=args.retry_max_attempts,
            backfill_posture=args.backfill_posture,
            backfill_max_windows=args.backfill_max_windows,
            failure_pause_posture=args.failure_pause_posture,
            failure_pause_threshold=args.failure_pause_threshold,
            source=args.source,
        )
        written = intent if args.dry_run else write_recurring_intent(paths, intent)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return _emit_recurring_intent(args, paths, written, saved=not args.dry_run)


def cmd_ops_recurring_intent_revise(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        current = show_recurring_intent(paths, args.intent_id)
        revised = revise_recurring_intent(
            current,
            title=args.title or None,
            schedule=args.schedule if args.schedule != "" else None,
            delivery=args.delivery if args.delivery != "" else None,
            silence=args.silence if args.silence != "" else None,
            scope=args.scope_note if args.scope_note != "" else None,
            owner=args.owner if args.owner != "" else None,
            owner_kind=args.owner_kind or None,
            overlap_posture=args.overlap_posture or None,
            missed_run_posture=args.missed_run_posture or None,
            retry_posture=args.retry_posture or None,
            retry_max_attempts=args.retry_max_attempts,
            backfill_posture=args.backfill_posture or None,
            backfill_max_windows=args.backfill_max_windows,
            failure_pause_posture=args.failure_pause_posture or None,
            failure_pause_threshold=args.failure_pause_threshold,
        )
        written = update_recurring_intent(paths, revised)
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return _emit_recurring_intent(args, paths, written, saved=True)


def cmd_ops_recurring_intent_activate(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        current = show_recurring_intent(paths, args.intent_id)
        activated = activate_recurring_intent(
            current,
            observer=args.observer,
            observer_kind=args.observer_kind,
            approval_ref=args.approval_ref,
            activation_surface=args.activation_surface,
        )
        written = update_recurring_intent(paths, activated)
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return _emit_recurring_intent(args, paths, written, saved=True)


def cmd_ops_recurring_intent_occurrence(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        current = show_recurring_intent(paths, args.intent_id)
        recorded = record_recurring_intent_occurrence(
            current,
            runtime_run_ref=args.runtime_run_ref,
            runtime_surface=args.runtime_surface,
            observer=args.observer,
            observer_kind=args.observer_kind,
            outcome=args.outcome,
            reason=args.reason,
            overlapped_run_ref=args.overlapped_run_ref,
            attempt=args.attempt,
        )
        written = update_recurring_intent(paths, recorded)
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return _emit_recurring_intent(args, paths, written, saved=True)


def cmd_ops_recurring_intent_decide(args: argparse.Namespace) -> int:
    """Report what the declared policy says about one situation. OMH runs nothing."""
    try:
        paths = _paths(args)
        intent = show_recurring_intent(paths, args.intent_id)
        decision = decide_recurring_occurrence(
            intent,
            situation=args.situation,
            now=args.now or utc_now(),
            active_run_ref=args.active_run_ref,
            missed_window_count=args.missed_window_count,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json({"schema_version": "omh_ops_recurring_intent_decision/v1", "decision": decision})
    else:
        print(render_recurring_occurrence_decision_text(decision))
    return 0


def cmd_ops_recurring_intent_list(args: argparse.Namespace) -> int:
    paths = _paths(args)
    try:
        limit = _limit_from_args(args, default=DEFAULT_RECURRING_INTENT_LIST_LIMIT)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    all_records = list_recurring_intents(paths)
    records = all_records if limit is None else all_records[-limit:]
    payload = {
        "schema_version": "omh_ops_recurring_intent_list/v1",
        "count": len(records),
        "total_count": len(all_records),
        "limit": limit if limit is not None else "all",
        "truncated": limit is not None and len(all_records) > len(records),
        "summary_only": True,
        "index_authority": "cache_only",
        "intents": [summarize_recurring_intent(record) for record in records],
    }
    if _wants_json(args):
        _print_json(payload)
    else:
        print(render_recurring_intent_list_text(payload))
    return 0


def cmd_ops_recurring_intent_show(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        intent = show_recurring_intent(paths, args.intent_id)
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json({"schema_version": "omh_ops_recurring_intent_show/v1", "intent": intent})
    else:
        print(render_recurring_intent_text(intent))
    return 0


def _emit_recurring_intent(args: argparse.Namespace, paths, record: dict, *, saved: bool) -> int:
    """One writer for every recurring-intent surface so the boundary never drifts.

    An unsaved intent emits the preview payload the wrapper reads back to the
    user before saving; both shapes carry `intent`, `store`, and `boundary`, so
    a consumer that only reads those does not have to branch.
    """
    if not _wants_json(args):
        print(render_recurring_intent_text(record))
        return 0
    store = {
        "omh_home": str(paths.omh_home),
        "hermes_ops_dir": str(paths.hermes_ops_dir),
        "recurring_intents_dir": str(paths.recurring_intents_dir),
        "index_path": str(paths.recurring_intents_index_path),
        "index_authority": "cache_only",
        "written": saved,
    }
    boundary = {
        **RECURRING_INTENT_BOUNDARY,
        "not_evidence_until_observed": list(record["not_evidence_until_observed"]),
        "observed_evidence_required": list(record["observed_evidence_required"]),
    }
    payload = (
        {"schema_version": "omh_ops_recurring_intent_result/v1", "intent": record}
        if saved
        else dict(preview_recurring_intent(record))
    )
    payload["store"] = store
    payload["boundary"] = boundary
    _print_json(payload)
    return 0


def cmd_ops_research_department(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        plan = build_research_department_plan(
            " ".join(args.request),
            title=args.title,
            topic=args.topic,
            cadence=args.cadence,
            delivery=args.delivery,
            storage=args.storage,
            knowledge_store=args.knowledge_store,
            synthesis_tool=args.synthesis_tool,
            source=args.source,
            sources=args.source_boundary or [],
            notebooklm=args.notebooklm,
            obsidian=args.obsidian,
        )
        written = plan if args.dry_run else write_research_department_plan(paths, plan)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "omh_ops_research_department_result/v1",
            "plan": written,
            "store": {
                "omh_home": str(paths.omh_home),
                "research_department_dir": str(paths.research_department_dir),
                "plans_dir": str(paths.research_department_plans_dir),
                "index_path": str(paths.research_department_index_path),
                "index_authority": "cache_only",
                "written": not args.dry_run,
            },
            "boundary": {
                "prepared_is_not_observed": True,
                "source_retrieval_observed": False,
                "synthesis_tool_query_observed": False,
                "knowledge_store_write_observed": False,
                "notebooklm_execution_observed": False,
                "obsidian_write_observed": False,
                "gateway_delivery_observed": False,
                "not_evidence_until_observed": list(written["not_evidence_until_observed"]),
                "observed_evidence_required": list(written["observed_evidence_required"]),
            },
        }
    )
    return 0


def cmd_ops_agent_review(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        card = build_agent_operator_productivity_card(
            " ".join(args.request),
            title=args.title,
            focus=args.focus,
            source=args.source,
        )
        written = card if args.dry_run else write_agent_operator_productivity_card(paths, card)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "omh_ops_agent_review_result/v1",
            "card": written,
            "store": {
                "omh_home": str(paths.omh_home),
                "agent_ops_dir": str(paths.agent_operator_productivity_dir),
                "cards_dir": str(paths.agent_operator_productivity_cards_dir),
                "index_path": str(paths.agent_operator_productivity_index_path),
                "index_authority": "cache_only",
                "written": not args.dry_run,
            },
            "boundary": {
                "prepared_is_not_observed": True,
                "source_retrieval_observed": False,
                "executor_dispatch_observed": False,
                "executor_session_attached": False,
                "implementation_observed": False,
                "verification_passed": False,
                "review_passed": False,
                "ci_passed": False,
                "merge_observed": False,
                "not_evidence_until_observed": list(written["not_evidence_until_observed"]),
                "observed_evidence_required": list(written["observed_evidence_required"]),
            },
        }
    )
    return 0


def cmd_ops_list(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        surface = args.surface or None
        limit = _limit_from_args(args, default=DEFAULT_OPS_LIST_LIMIT)
        all_records = list_operation_artifacts(paths, surface=surface)
        records = all_records if limit is None else all_records[-limit:]
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "omh_ops_list/v1",
            "surface": args.surface or "all",
            "count": len(records),
            "total_count": len(all_records),
            "limit": limit if limit is not None else "all",
            "truncated": limit is not None and len(all_records) > len(records),
            "summary_only": True,
            "index_authority": "cache_only",
            "artifacts": [summarize_operation_artifact(record) for record in records],
        }
    )
    return 0


def cmd_ops_agent_review_list(args: argparse.Namespace) -> int:
    paths = _paths(args)
    try:
        limit = _limit_from_args(args, default=DEFAULT_AGENT_OPS_LIST_LIMIT)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    all_records = list_agent_operator_productivity_cards(paths)
    records = all_records if limit is None else all_records[-limit:]
    _print_json(
        {
            "schema_version": "omh_ops_agent_review_list/v1",
            "count": len(records),
            "total_count": len(all_records),
            "limit": limit if limit is not None else "all",
            "truncated": limit is not None and len(all_records) > len(records),
            "summary_only": True,
            "index_authority": "cache_only",
            "cards": [summarize_agent_operator_productivity_card(record) for record in records],
        }
    )
    return 0


def cmd_ops_research_department_list(args: argparse.Namespace) -> int:
    paths = _paths(args)
    try:
        limit = _limit_from_args(args, default=DEFAULT_RESEARCH_DEPARTMENT_LIST_LIMIT)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    all_records = list_research_department_plans(paths)
    records = all_records if limit is None else all_records[-limit:]
    _print_json(
        {
            "schema_version": "omh_ops_research_department_list/v1",
            "count": len(records),
            "total_count": len(all_records),
            "limit": limit if limit is not None else "all",
            "truncated": limit is not None and len(all_records) > len(records),
            "summary_only": True,
            "index_authority": "cache_only",
            "plans": [summarize_research_department_plan(record) for record in records],
        }
    )
    return 0


def cmd_ops_agent_review_show(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        card = show_agent_operator_productivity_card(paths, args.card_id)
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"schema_version": "omh_ops_agent_review_show/v1", "card": card})
    return 0


def cmd_ops_show(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        artifact = show_operation_artifact(paths, args.artifact_id)
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"schema_version": "omh_ops_show/v1", "artifact": artifact})
    return 0


def cmd_ops_research_department_show(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        plan = show_research_department_plan(paths, args.plan_id)
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"schema_version": "omh_ops_research_department_show/v1", "plan": plan})
    return 0


def cmd_ops_blueprint_show(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        blueprint = show_hermes_ops_blueprint(paths, args.blueprint_id)
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"schema_version": "omh_ops_blueprint_show/v1", "blueprint": blueprint})
    return 0


def cmd_ops_validate(args: argparse.Namespace) -> int:
    paths = _paths(args)
    result = validate_operations_store(paths)
    blueprint_result = validate_hermes_ops_store(paths)
    recurring_intent_result = validate_recurring_intent_store(paths)
    research_department_result = validate_research_department_store(paths)
    agent_ops_result = validate_agent_operator_productivity_store(paths)
    result["hermes_ops_blueprints"] = blueprint_result
    result["recurring_intents"] = recurring_intent_result
    result["research_department_plans"] = research_department_result
    result["agent_ops_reviews"] = agent_ops_result
    result["ok"] = (
        bool(result["ok"])
        and bool(blueprint_result["ok"])
        and bool(recurring_intent_result["ok"])
        and bool(research_department_result["ok"])
        and bool(agent_ops_result["ok"])
    )
    _print_json(result)
    return 0 if result["ok"] else 1


def cmd_ops_blueprint_list(args: argparse.Namespace) -> int:
    paths = _paths(args)
    try:
        limit = _limit_from_args(args, default=DEFAULT_BLUEPRINT_LIST_LIMIT)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    all_records = list_hermes_ops_blueprints(paths)
    records = all_records if limit is None else all_records[-limit:]
    _print_json(
        {
            "schema_version": "omh_ops_blueprint_list/v1",
            "count": len(records),
            "total_count": len(all_records),
            "limit": limit if limit is not None else "all",
            "truncated": limit is not None and len(all_records) > len(records),
            "summary_only": True,
            "index_authority": "cache_only",
            "blueprints": [summarize_hermes_ops_blueprint(record) for record in records],
        }
    )
    return 0


def cmd_ops_export(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        surface = args.surface or None
        limit = _limit_from_args(args, default=DEFAULT_OPS_EXPORT_LIMIT)
        total_count = len(list_operation_artifacts(paths, surface=surface))
        exported = export_operations_bundle(paths, surface=surface, format=args.format, limit=limit)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "omh_ops_export_result/v1",
            "format": args.format,
            "surface": args.surface or "all",
            "limit": limit if limit is not None else "all",
            "total_count": total_count,
            "exported_count": total_count if limit is None else min(total_count, limit),
            "truncated": limit is not None and total_count > limit,
            "index_authority": "cache_only",
            "ppt_scope": "markdown_or_json_outline_only",
            "export": exported,
        }
    )
    return 0


def _observation_status(args: argparse.Namespace) -> str:
    if args.observed:
        return "observed"
    if args.mixed:
        return "mixed"
    if args.not_observed:
        return "not_observed"
    return "prepared"


def _optional_positive_int(value: int | None) -> int | None:
    if value is None:
        return None
    if value < 1:
        raise ValueError("--limit must be at least 1")
    return value


def _limit_from_args(args: argparse.Namespace, *, default: int) -> int | None:
    if args.all:
        return None
    return _optional_positive_int(args.limit) if args.limit is not None else default


def _add_artifact_args(parser: argparse.ArgumentParser, *, surface: str, default_kind: str) -> None:
    parser.set_defaults(func=cmd_ops_write, surface=surface)
    parser.add_argument("--kind", choices=KINDS_BY_SURFACE[surface], default=default_kind)
    parser.add_argument("--title", required=True)
    parser.add_argument("--summary", default="")
    parser.add_argument("--status", choices=ARTIFACT_STATUSES, default="draft")
    parser.add_argument("--source", default="")
    parser.add_argument("--inputs-summary", default="")
    parser.add_argument("--section", action="append")
    parser.add_argument("--decision", action="append")
    parser.add_argument("--action", action="append")
    parser.add_argument("--metric", action="append")
    parser.add_argument("--reference", action="append")
    parser.add_argument("--assumption", action="append")
    observation = parser.add_mutually_exclusive_group()
    observation.add_argument("--observed", action="store_true", help="Mark the artifact as observed with supplied evidence.")
    observation.add_argument("--mixed", action="store_true", help="Mark the artifact as a mix of prepared and observed content.")
    observation.add_argument("--not-observed", action="store_true", help="Mark the artifact as explicitly not observed.")


def _add_recurring_intent_shape_args(parser: argparse.ArgumentParser, *, revising: bool = False) -> None:
    """The fields that shape a recurring intent, spelled identically on build and revise.

    On revise an empty string means "leave this field alone", which is why the
    two parsers share one definition instead of drifting into two vocabularies.
    """
    parser.add_argument("--schedule", default="", help="Explicit schedule/cadence hint.")
    parser.add_argument("--delivery", default="", help="Explicit delivery target hint.")
    parser.add_argument("--silence", default="", help="Explicit silence/no-change policy hint.")
    parser.add_argument("--scope", dest="scope_note", default="", help="What this recurring work is allowed to touch.")
    parser.add_argument("--owner", default="", help="Owner accountable for this recurring work.")
    parser.add_argument(
        "--owner-kind",
        choices=("", *OWNER_KINDS) if revising else OWNER_KINDS,
        default="" if revising else "unassigned",
        help="Kind of owner accountable for this recurring work.",
    )
    # The five failure-policy decisions. Each one must be explicit before an
    # approved runtime surface can activate the intent, and none of them has a
    # silent default: the parser default is the same `unspecified` sentinel the
    # record uses, so "not passed" never reads as "chosen".
    parser.add_argument(
        "--overlap-posture",
        choices=("", *OVERLAP_POSTURES) if revising else OVERLAP_POSTURES,
        default="" if revising else "unspecified",
        help="What happens when an occurrence is still running; must be explicit before activation.",
    )
    parser.add_argument(
        "--missed-run-posture",
        choices=("", *MISSED_RUN_POSTURES) if revising else MISSED_RUN_POSTURES,
        default="" if revising else "unspecified",
        help="What happens to a window that was missed; must be explicit before activation.",
    )
    parser.add_argument(
        "--retry-posture",
        choices=("", *RETRY_POSTURES) if revising else RETRY_POSTURES,
        default="" if revising else "unspecified",
        help="What happens after a failed occurrence; must be explicit before activation.",
    )
    parser.add_argument(
        "--retry-max-attempts",
        type=int,
        default=None if revising else 0,
        help="Maximum retry attempts; required by retry_bounded and refused by any other retry posture.",
    )
    parser.add_argument(
        "--backfill-posture",
        choices=("", *BACKFILL_POSTURES) if revising else BACKFILL_POSTURES,
        default="" if revising else "unspecified",
        help="Whether older missed windows are replayed; must be explicit before activation.",
    )
    parser.add_argument(
        "--backfill-max-windows",
        type=int,
        default=None if revising else 0,
        help="Maximum older windows to backfill; required by backfill_bounded_window and refused otherwise.",
    )
    parser.add_argument(
        "--failure-pause-posture",
        choices=("", *FAILURE_PAUSE_POSTURES) if revising else FAILURE_PAUSE_POSTURES,
        default="" if revising else "unspecified",
        help="Whether repeated failure pauses this intent; must be explicit before activation.",
    )
    parser.add_argument(
        "--failure-pause-threshold",
        type=int,
        default=None if revising else 0,
        help="Consecutive failures that pause this intent; required by pause_after_consecutive_failures.",
    )


def _add_recurring_intent_json_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")


def _add_ops_commands(sub) -> None:
    from .design_direction_iterations import add_ops_design_direction_iterations_command
    from .memory_provider_posture import add_ops_memory_provider_posture_command
    from .permission_rehearsal import add_ops_permission_rehearsal_command
    from .plugin_risk_audit import add_ops_plugin_risk_audit_command
    from .provider_profile_posture import add_ops_provider_profile_posture_command
    from .prompt_compatibility import add_ops_prompt_compatibility_command
    from .realtime_voice_readiness import add_ops_realtime_voice_readiness_command
    from .rules_import import add_ops_rules_import_command
    from .toolcall_rules import add_ops_toolcall_rules_command

    ops = sub.add_parser("ops", help="Create, inspect, validate, and export local operations artifacts.")
    ops_sub = ops.add_subparsers(dest="ops_command", required=True)

    add_ops_provider_profile_posture_command(ops_sub)
    add_ops_memory_provider_posture_command(ops_sub)
    add_ops_prompt_compatibility_command(ops_sub)
    add_ops_realtime_voice_readiness_command(ops_sub)
    add_ops_rules_import_command(ops_sub)
    add_ops_plugin_risk_audit_command(ops_sub)
    add_ops_toolcall_rules_command(ops_sub)
    add_ops_permission_rehearsal_command(ops_sub)
    add_ops_design_direction_iterations_command(ops_sub)

    data_harness = ops_sub.add_parser(
        "data-harness",
        help="Prepare metadata-only operational data collection and relationship-analysis guardrails.",
    )
    data_harness.add_argument("--data-shape", choices=OPERATIONS_DATA_SHAPES, required=True)
    data_harness.add_argument("--analysis-mode", choices=OPERATIONS_ANALYSIS_MODES, required=True)
    data_harness.set_defaults(func=cmd_ops_data_harness)

    product_evidence_loop = ops_sub.add_parser(
        "product-evidence-loop",
        help="Prepare a metadata-only product evidence card without retrieving sources or accepting a decision.",
    )
    product_evidence_loop.add_argument("--decision-scope-id", required=True)
    product_evidence_loop.add_argument("--proposed-next-decision", choices=PRODUCT_EVIDENCE_LOOP_DECISIONS, required=True)
    for prefix in ("research", "feedback", "supplied-data", "causal-identification"):
        destination = prefix.replace("-", "_")
        product_evidence_loop.add_argument(
            f"--{prefix}-availability",
            choices=REFERENCE_AVAILABILITIES,
            default="not_supplied",
            dest=f"{destination}_availability",
        )
        product_evidence_loop.add_argument(f"--{prefix}-reference-id", default="", dest=f"{destination}_reference_id")
        product_evidence_loop.add_argument(
            f"--{prefix}-provenance",
            choices=("",) + REFERENCE_PROVENANCES,
            default="",
            dest=f"{destination}_provenance",
        )
    product_evidence_loop.set_defaults(func=cmd_ops_product_evidence_loop)

    design_orchestration = ops_sub.add_parser(
        "design-orchestration",
        help="Prepare a metadata-only executor-neutral design orchestration contract.",
    )
    design_orchestration.add_argument("--surface", choices=DESIGN_SURFACES, required=True)
    design_orchestration.add_argument("--audience", choices=DESIGN_AUDIENCES, required=True)
    design_orchestration.add_argument("--primary-task", choices=DESIGN_PRIMARY_TASKS, required=True)
    design_orchestration.add_argument("--platform", choices=DESIGN_PLATFORMS, required=True)
    design_orchestration.add_argument("--mode", choices=DESIGN_MODES, required=True)
    design_orchestration.add_argument("--context-reference", action="append", required=True)
    design_orchestration.add_argument("--hierarchy", choices=DESIGN_HIERARCHIES, required=True)
    design_orchestration.add_argument("--palette", choices=DESIGN_PALETTES, required=True)
    design_orchestration.add_argument("--typography", choices=DESIGN_TYPOGRAPHIES, required=True)
    design_orchestration.add_argument("--layout", choices=DESIGN_LAYOUTS, required=True)
    design_orchestration.add_argument("--signature-element", choices=DESIGN_SIGNATURE_ELEMENTS, required=True)
    design_orchestration.add_argument("--avoid-pattern", action="append", choices=DESIGN_AVOID_PATTERNS, required=True)
    design_orchestration.set_defaults(func=cmd_ops_design_orchestration)

    design_directions = ops_sub.add_parser(
        "design-directions",
        help="Offer two to four design directions and record which one was chosen.",
    )
    design_directions.add_argument("--surface", choices=DESIGN_SURFACES, required=True)
    design_directions.add_argument("--audience", choices=DESIGN_AUDIENCES, required=True)
    design_directions.add_argument("--primary-task", choices=DESIGN_PRIMARY_TASKS, required=True)
    design_directions.add_argument("--platform", choices=DESIGN_PLATFORMS, required=True)
    design_directions.add_argument("--mode", choices=DESIGN_MODES, required=True)
    design_directions.add_argument("--context-reference", action="append", required=True)
    design_directions.add_argument(
        "--option",
        action="append",
        required=True,
        metavar="ID:HIERARCHY:PALETTE:TYPOGRAPHY:LAYOUT:SIGNATURE:AVOID|AVOID",
        help="A direction to offer. Repeat two to four times, ids a, b, c, d in order.",
    )
    design_directions.add_argument(
        "--choose",
        choices=DESIGN_DIRECTION_OPTION_IDS,
        help="Record this option as chosen. Omit while the choice is still open.",
    )
    design_directions.add_argument(
        "--html",
        help="Write the self-contained static preview here. No server is started and no browser is opened.",
    )
    design_directions.set_defaults(func=cmd_ops_design_directions)

    rhythm = ops_sub.add_parser("rhythm", help="Create an operating rhythm artifact such as a meeting or retro record.")
    _add_artifact_args(rhythm, surface="operating-rhythm", default_kind="meeting")

    report = ops_sub.add_parser("report", help="Create a report package or PPT-ready outline artifact.")
    _add_artifact_args(report, surface="report-package", default_kind="status-package")

    reliability = ops_sub.add_parser("reliability", help="Create a reliability review artifact such as an SLO or postmortem review.")
    _add_artifact_args(reliability, surface="reliability-review", default_kind="service-review")

    blueprint = ops_sub.add_parser("blueprint", help="Prepare a Hermes scheduled ops blueprint without creating runtime automation.")
    blueprint.add_argument("request", nargs="+", help="Natural-language scheduled ops request.")
    blueprint.add_argument("--title", default="")
    blueprint.add_argument("--schedule", default="", help="Explicit schedule/cadence hint.")
    blueprint.add_argument("--delivery", default="", help="Explicit delivery target hint.")
    blueprint.add_argument("--silence", default="", help="Explicit silence/no-change policy hint.")
    blueprint.add_argument("--source", default="", help="Optional metadata source label.")
    blueprint.add_argument("--dry-run", action="store_true", help="Print the prepared blueprint without writing it.")
    blueprint.set_defaults(func=cmd_ops_blueprint)

    recurring_intent = ops_sub.add_parser(
        "recurring-intent",
        help="Prepare a paused recurring intent from a natural-language request; OMH never activates or runs it.",
    )
    recurring_intent.add_argument("request", nargs="+", help="Natural-language recurring work request.")
    recurring_intent.add_argument("--title", default="")
    _add_recurring_intent_shape_args(recurring_intent)
    recurring_intent.add_argument("--source", default="", help="Optional metadata source label.")
    recurring_intent.add_argument("--dry-run", action="store_true", help="Print the preview without saving it.")
    _add_recurring_intent_json_arg(recurring_intent)
    recurring_intent.set_defaults(func=cmd_ops_recurring_intent)

    recurring_intent_revise = ops_sub.add_parser(
        "recurring-intent-revise",
        help="Revise a stored recurring intent; the new revision pauses it again so activation is re-observed.",
    )
    recurring_intent_revise.add_argument("intent_id")
    recurring_intent_revise.add_argument("--title", default="")
    _add_recurring_intent_shape_args(recurring_intent_revise, revising=True)
    _add_recurring_intent_json_arg(recurring_intent_revise)
    recurring_intent_revise.set_defaults(func=cmd_ops_recurring_intent_revise)

    recurring_intent_activate = ops_sub.add_parser(
        "recurring-intent-activate",
        help="Record that an approved runtime surface activated a recurring intent. OMH does not activate it.",
    )
    recurring_intent_activate.add_argument("intent_id")
    recurring_intent_activate.add_argument("--observer", required=True, help="Who or what observed the activation.")
    recurring_intent_activate.add_argument("--observer-kind", choices=ACTIVATION_OBSERVER_KINDS, default="approved_runtime_surface")
    recurring_intent_activate.add_argument("--approval-ref", required=True, help="Recorded approval reference.")
    recurring_intent_activate.add_argument(
        "--activation-surface",
        required=True,
        help="The approved runtime surface that performed the activation.",
    )
    _add_recurring_intent_json_arg(recurring_intent_activate)
    recurring_intent_activate.set_defaults(func=cmd_ops_recurring_intent_activate)

    recurring_intent_occurrence = ops_sub.add_parser(
        "recurring-intent-occurrence",
        help="Link one observed runtime run back to the exact recurring intent revision it ran under.",
    )
    recurring_intent_occurrence.add_argument("intent_id")
    recurring_intent_occurrence.add_argument(
        "--runtime-run-ref",
        default="",
        help="Run reference owned by the runtime. Required by ran and failed, refused by every other outcome.",
    )
    recurring_intent_occurrence.add_argument("--runtime-surface", required=True, help="Runtime surface that ran it.")
    recurring_intent_occurrence.add_argument("--observer", required=True, help="Who or what observed the run.")
    recurring_intent_occurrence.add_argument("--observer-kind", choices=OCCURRENCE_OBSERVER_KINDS, default="approved_runtime_surface")
    recurring_intent_occurrence.add_argument("--outcome", choices=OCCURRENCE_OUTCOMES, default="ran")
    recurring_intent_occurrence.add_argument(
        "--reason",
        default="",
        help="Policy reason nothing ran. Required by skipped, missed, and queued so a non-run is never silent.",
    )
    recurring_intent_occurrence.add_argument(
        "--overlapped-run-ref",
        default="",
        help="The run this occurrence overlapped, skipped behind, or queued behind.",
    )
    recurring_intent_occurrence.add_argument("--attempt", type=int, default=1, help="Attempt number under the retry policy.")
    _add_recurring_intent_json_arg(recurring_intent_occurrence)
    recurring_intent_occurrence.set_defaults(func=cmd_ops_recurring_intent_occurrence)

    recurring_intent_decide = ops_sub.add_parser(
        "recurring-intent-decide",
        help="Report what a recurring intent's declared failure policy says about one situation. OMH runs nothing.",
    )
    recurring_intent_decide.add_argument("intent_id")
    recurring_intent_decide.add_argument(
        "--situation",
        choices=OCCURRENCE_SITUATIONS,
        required=True,
        help="The situation the approved runtime surface observed.",
    )
    recurring_intent_decide.add_argument(
        "--active-run-ref",
        default="",
        help="Run reference still active; required by prior_run_active so an overlap can never be unnamed.",
    )
    recurring_intent_decide.add_argument("--missed-window-count", type=int, default=0, help="How many windows were missed.")
    recurring_intent_decide.add_argument("--now", default="", help="Caller timestamp; defaults to the current UTC time.")
    _add_recurring_intent_json_arg(recurring_intent_decide)
    recurring_intent_decide.set_defaults(func=cmd_ops_recurring_intent_decide)

    recurring_intent_list = ops_sub.add_parser("recurring-intent-list", help="List stored recurring intents.")
    recurring_intent_list.add_argument("--limit", type=int, default=None)
    recurring_intent_list.add_argument("--all", action="store_true", help="Return all intent summaries instead of the default bounded window.")
    _add_recurring_intent_json_arg(recurring_intent_list)
    recurring_intent_list.set_defaults(func=cmd_ops_recurring_intent_list)

    recurring_intent_show = ops_sub.add_parser("recurring-intent-show", help="Show one stored recurring intent by id.")
    recurring_intent_show.add_argument("intent_id")
    _add_recurring_intent_json_arg(recurring_intent_show)
    recurring_intent_show.set_defaults(func=cmd_ops_recurring_intent_show)

    research_department = ops_sub.add_parser(
        "research-department",
        help="Prepare a Scout/Analyst/Briefer research department workflow without running research.",
    )
    research_department.add_argument("request", nargs="+", help="Natural-language research operations request.")
    research_department.add_argument("--title", default="")
    research_department.add_argument("--topic", default="", help="Explicit research topic or watch area.")
    research_department.add_argument("--cadence", default="", help="Explicit cadence hint such as daily or weekly.")
    research_department.add_argument("--delivery", default="", help="Explicit delivery target hint.")
    research_department.add_argument("--storage", default="", help="Compatibility alias for --knowledge-store.")
    research_department.add_argument("--knowledge-store", default="", help="Knowledge store target such as markdown folder, note vault, or database.")
    research_department.add_argument("--synthesis-tool", default="", help="Knowledge synthesis tool hint such as Hermes synthesis, NotebookLM, or local RAG.")
    research_department.add_argument("--source", default="", help="Optional metadata source label.")
    research_department.add_argument("--source-boundary", action="append", help="Allowed source, source family, or scope boundary.")
    research_department.add_argument(
        "--notebooklm",
        choices=("unknown", "available", "unavailable", "preferred"),
        default="unknown",
        help="Compatibility alias for a NotebookLM synthesis-tool readiness hint; OMH does not probe or invoke it.",
    )
    research_department.add_argument(
        "--obsidian",
        choices=("unknown", "available", "unavailable", "preferred"),
        default="unknown",
        help="Compatibility alias for an Obsidian knowledge-store readiness hint; OMH does not probe or write to it.",
    )
    research_department.add_argument("--dry-run", action="store_true", help="Print the prepared plan without writing it.")
    research_department.set_defaults(func=cmd_ops_research_department)

    agent_review = ops_sub.add_parser(
        "agent-review",
        help="Prepare a manager-facing agent ops review card for research, coding, review, and status productivity.",
    )
    agent_review.add_argument("request", nargs="+", help="Natural-language agent operations management request.")
    agent_review.add_argument("--title", default="")
    agent_review.add_argument("--focus", choices=("auto", "mixed", "research", "coding", "review", "status"), default="auto")
    agent_review.add_argument("--source", default="", help="Optional metadata source label.")
    agent_review.add_argument("--dry-run", action="store_true", help="Print the prepared card without writing it.")
    agent_review.set_defaults(func=cmd_ops_agent_review)

    blueprint_list = ops_sub.add_parser("blueprint-list", help="List prepared Hermes scheduled ops blueprints.")
    blueprint_list.add_argument("--limit", type=int, default=None)
    blueprint_list.add_argument("--all", action="store_true", help="Return all blueprint summaries instead of the default bounded window.")
    blueprint_list.set_defaults(func=cmd_ops_blueprint_list)

    blueprint_show = ops_sub.add_parser("blueprint-show", help="Show one prepared Hermes scheduled ops blueprint by id.")
    blueprint_show.add_argument("blueprint_id")
    blueprint_show.set_defaults(func=cmd_ops_blueprint_show)

    research_department_list = ops_sub.add_parser("research-department-list", help="List prepared research department plans.")
    research_department_list.add_argument("--limit", type=int, default=None)
    research_department_list.add_argument("--all", action="store_true", help="Return all plan summaries instead of the default bounded window.")
    research_department_list.set_defaults(func=cmd_ops_research_department_list)

    research_department_show = ops_sub.add_parser("research-department-show", help="Show one research department plan by id.")
    research_department_show.add_argument("plan_id")
    research_department_show.set_defaults(func=cmd_ops_research_department_show)

    agent_review_list = ops_sub.add_parser("agent-review-list", help="List prepared agent ops review cards.")
    agent_review_list.add_argument("--limit", type=int, default=None)
    agent_review_list.add_argument("--all", action="store_true", help="Return all cards instead of the default bounded window.")
    agent_review_list.set_defaults(func=cmd_ops_agent_review_list)

    agent_review_show = ops_sub.add_parser("agent-review-show", help="Show one prepared agent ops review card by id.")
    agent_review_show.add_argument("card_id")
    agent_review_show.set_defaults(func=cmd_ops_agent_review_show)

    list_cmd = ops_sub.add_parser("list", help="List operations artifacts from local storage.")
    list_cmd.add_argument("--surface", choices=SURFACES, default="")
    list_cmd.add_argument("--limit", type=int, default=None)
    list_cmd.add_argument("--all", action="store_true", help="Return all artifact summaries instead of the default bounded window.")
    list_cmd.set_defaults(func=cmd_ops_list)

    show = ops_sub.add_parser("show", help="Show one operations artifact by id.")
    show.add_argument("artifact_id")
    show.set_defaults(func=cmd_ops_show)

    validate = ops_sub.add_parser("validate", help="Validate operations artifacts and cache metadata.")
    validate.set_defaults(func=cmd_ops_validate)

    export = ops_sub.add_parser("export", help="Export operations artifacts as JSON or Markdown content inside JSON output.")
    export.add_argument("--surface", choices=SURFACES, default="")
    export.add_argument("--format", choices=("json", "markdown"), default="json")
    export.add_argument("--limit", type=int, default=None)
    export.add_argument("--all", action="store_true", help="Export all matching artifacts instead of the default bounded window.")
    export.set_defaults(func=cmd_ops_export)
