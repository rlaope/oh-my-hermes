from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..install.config_adapter import (
    ConfigChange,
    clear_memory_provider,
    memory_provider_selection,
    read_config,
    set_memory_provider,
    update_config,
)
from ..installer import OmhError
from ..plugin_bundle.omh.memory_governance import SOURCE_CLASSES
from ..plugin_bundle.omh.memory_blocks import (
    MemoryBlockError,
    blocks_dir,
    build_memory_block,
    delete_memory_block,
    read_memory_blocks,
    write_memory_block,
)
from ..plugin_bundle.omh.memory_dreaming import read_dreaming_state
from ..plugin_bundle.omh.memory_principals import parse_principal_context
from ..plugin_bundle.omh.memory_provider import OmhMemoryProvider
from ..plugin_bundle.omh.project_identity import mint_explicit_project_identity, project_identity_root, require_project_identity, resolve_project_identity
from ..plugin_bundle.omh.memory_records import prefetch_scope_allowlist
from ..workflows.memory_project_identity import build_project_identity_migration_report, migrate_project_identity, rollback_project_identity_migration
from ..plugin_bundle.omh.metadata import MEMORY_PROVIDER_NAME
from ..memory import (
    LifecycleCandidateError,
    RejectedDecisionRecallRequest,
    StaleMemoryReviewError,
    candidate_is_review_card_backed,
    apply_approved_memory_update_batch,
    apply_memory_attention_change,
    apply_memory_retirement,
    apply_memory_update_batch,
    approve_project_memory_candidate,
    build_memory_attention_change,
    build_memory_lineage,
    build_memory_perspectives,
    build_memory_retirement,
    build_memory_rollup,
    set_memory_pin,
    build_handoff_context_pack,
    build_memory_inspection,
    build_project_memory_recall_pack,
    build_project_memory_review,
    build_project_memory_status,
    MAX_RETENTION_DAYS,
    build_memory_demotion,
    capture_project_memory_candidate,
    confirm_due_project_memory_records,
    confirm_project_memory_record,
    keep_memory_record_open,
    stage_memory_demotion,
    read_memory_snapshot_file,
    reject_project_memory_candidate,
    review_memory_update_batch,
    stage_memory_update_batch,
    build_rejected_decision_recall,
)
from ..system.local_store import read_json_object_result
from ..workflows.memory_evaluation import run_memory_evaluation, run_memory_retrieval_evaluation
from ..workflows.memory_recall_incident import (
    RecallIncidentRequest,
    build_memory_recall_incident,
    write_memory_recall_incident,
)
from ..workflows.memory_lifecycle import (
    apply_memory_correction,
    apply_memory_prune,
    apply_memory_reapproval,
    apply_memory_restore,
    build_memory_correction,
    build_memory_prune,
    build_memory_reapproval,
    build_memory_restore,
)
from ..workflows.memory_lifecycle_executor import execute_memory_lifecycle
from ..workflows.memory_sources import build_memory_source_index
from ..workflows.memory_principal_migration import (
    apply_principal_migration,
    build_principal_migration_report,
    export_principal_memory,
    rollback_principal_migration,
)
from ..workflows.memory_migration import (
    build_memory_migration_inventory,
    reactivate_memory_artifact,
    write_memory_migration_ledger,
)
from .common import _paths, _print_json


def cmd_memory_project_identity(args: argparse.Namespace) -> int:
    from dataclasses import asdict

    try:
        paths = _paths(args)
        root = project_identity_root() or Path.cwd()
        if args.identity_command == "init":
            mint_explicit_project_identity(root)
            payload = asdict(resolve_project_identity(root))
        elif args.identity_command == "show":
            payload = asdict(resolve_project_identity(root))
        elif args.identity_command == "report":
            payload = build_project_identity_migration_report(paths, root=root)
        elif args.rollback:
            payload = rollback_project_identity_migration(paths, args.rollback, root=root)
        else:
            payload = migrate_project_identity(paths, approve=args.approve, root=root)
    except (OSError, ValueError):
        # These commands never expose filesystem paths from operating-system errors.
        raise OmhError("project_identity_operation_refused") from None
    _print_json(payload)
    return 0


def cmd_memory_status(args: argparse.Namespace) -> int:
    try:
        payload = build_project_memory_status(_paths(args))
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_capture(args: argparse.Namespace) -> int:
    try:
        summary = " ".join(args.summary).strip()
        content = sys.stdin.read() if args.stdin else str(args.content or "")
        if not summary:
            raise ValueError("memory capture requires a summary")
        _validate_capture_governance_args(args)
        payload = capture_project_memory_candidate(
            _paths(args),
            summary,
            content=content,
            record_type=args.type,
            scope_kind=args.scope_kind,
            scope_ref=(require_project_identity() if args.scope_kind == "project" and args.scope_ref is None else args.scope_ref),
            source=args.source,
            source_ref=args.source_ref,
            tags=args.tag or [],
            ttl_days=args.ttl_days,
            stale_after_days=args.stale_after_days,
            stale_after=args.stale_after,
            expires_at=args.expires_at,
            retention_class=args.retention_class,
            derived_from=args.derived_from or [],
            observer=args.observer,
            observed=args.observed,
            principal_context=_read_optional_json(args.principal_context),
            audience_principals=args.audience_principal or [],
            unresolved=bool(getattr(args, "unresolved", False)),
        )
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_review(args: argparse.Namespace) -> int:
    try:
        payload = build_project_memory_review(
            _paths(args),
            candidate_id=args.candidate,
            limit=_optional_positive_int(args.limit, "--limit") or 20,
        )
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def _review_revision_refusal(candidate_id: str, reason_code: str, detail: str) -> dict[str, object]:
    """One refused review decision, shaped like every other memory control result."""
    return {
        "schema_version": "project_memory_review_refusal/v1",
        "applied": False,
        "candidate_id": candidate_id,
        "reason_code": reason_code,
        "detail": detail,
        "next_action": (
            "Re-read the card with `omh memory review --candidate "
            f"{candidate_id}` and pass its review_revision with --candidate-revision."
        ),
        "claim_boundary": (
            "A refused project-memory review changed no OMH-local candidate, record, or review decision, "
            "and never touched Hermes global or internal memory."
        ),
    }


def _missing_review_revision(paths, args: argparse.Namespace) -> dict[str, object] | None:
    """Refuse an unproven decision on a candidate the review queue renders a card for.

    Scoped to card-backed candidates on purpose. A v2 correction/restore
    candidate never gets a card, so requiring a revision there would demand a
    value no surface produces and break the one approve verb the operator has;
    those keep their existing lifecycle guard. An unreadable or missing
    candidate falls through to the workflow call, which owns that error.
    """
    if str(getattr(args, "candidate_revision", "") or ""):
        return None
    candidate, error = read_json_object_result(paths.memory_dir / "candidates" / f"{args.candidate_id}.json")
    if candidate is None or error is not None or not candidate_is_review_card_backed(candidate):
        return None
    return _review_revision_refusal(
        str(args.candidate_id),
        "review_revision_required",
        "An interactive review decision must name the review revision of the card it read.",
    )


def cmd_memory_approve(args: argparse.Namespace) -> int:
    paths = _paths(args)
    refusal = _missing_review_revision(paths, args)
    if refusal is not None:
        _print_json(refusal)
        return 1
    try:
        reviewer_context = parse_principal_context(_read_optional_json(args.principal_context))
        payload = approve_project_memory_candidate(
            paths,
            args.candidate_id,
            approved_by=args.approved_by,
            retention_class=args.retention_class,
            expected_revision=args.candidate_revision,
            reviewer_principal=(
                str(reviewer_context.get("principal"))
                if reviewer_context is not None and reviewer_context.get("actor_kind") == "human"
                else None
            ),
            unresolved=bool(getattr(args, "unresolved", False)),
        )
    except StaleMemoryReviewError as exc:
        _print_json(_review_revision_refusal(str(args.candidate_id), "stale_review", str(exc)))
        return 1
    except LifecycleCandidateError:
        if args.retention_class is not None:
            raise OmhError(
                "lifecycle candidates keep their reviewed retention class; "
                "--retention-class applies only to plain approvals"
            ) from None
        if bool(getattr(args, "unresolved", False)):
            # A correction or restore candidate carries its reviewed
            # resolution marker; the answer to an open question is the
            # correction itself, not a flag on its reapproval.
            raise OmhError(
                "lifecycle candidates keep their reviewed resolution marker; "
                "--unresolved applies only to plain approvals"
            ) from None
        # Correction/restore candidates approve through the lifecycle
        # executor so the replacement payload and revision survive; the
        # operator keeps one approve verb either way.
        try:
            plan = build_memory_reapproval(
                paths,
                args.candidate_id,
                reviewer_claim=args.approved_by,
                now=datetime.now(timezone.utc),
                principal_context=_read_optional_json(args.principal_context),
            )
            payload = dict(plan.report) if not plan.report.get("eligible") else apply_memory_reapproval(
                paths,
                plan,
                transaction_executor=execute_memory_lifecycle,
                principal_context=_read_optional_json(args.principal_context),
            )
        except (OSError, ValueError) as exc:
            raise OmhError(str(exc)) from exc
    except FileNotFoundError as exc:
        raise OmhError(f"memory candidate not found: {args.candidate_id}") from exc
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_reject(args: argparse.Namespace) -> int:
    paths = _paths(args)
    refusal = _missing_review_revision(paths, args)
    if refusal is not None:
        _print_json(refusal)
        return 1
    try:
        payload = reject_project_memory_candidate(
            paths,
            args.candidate_id,
            rejected_by=args.rejected_by,
            reason=args.reason,
            expected_revision=args.candidate_revision,
        )
    except StaleMemoryReviewError as exc:
        _print_json(_review_revision_refusal(str(args.candidate_id), "stale_review", str(exc)))
        return 1
    except FileNotFoundError as exc:
        raise OmhError(f"memory candidate not found: {args.candidate_id}") from exc
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_recall(args: argparse.Namespace) -> int:
    try:
        query = " ".join(args.query).strip()
        paths = _paths(args)
        automatic = args.scope_kind is None and args.scope_ref is None
        resolution = resolve_project_identity()
        payload = build_project_memory_recall_pack(
            paths,
            query,
            executor_target=args.executor,
            session_id=args.session_id,
            scope_kind=args.scope_kind,
            scope_ref=args.scope_ref,
            limit=_optional_positive_int(args.limit, "--limit") or 6,
            max_chars=_optional_positive_int(args.max_chars, "--max-chars"),
            include_stale=args.include_stale,
            include_archived=args.include_archived,
            allowed_scopes=prefetch_scope_allowlist(project_identity=resolution.identity, session_id=args.session_id) if automatic else None,
            inspection=not automatic,
            observer=args.observer,
            observed=args.observed,
            query_intent=args.intent,
            principal_context=_read_optional_json(args.principal_context),
            shared_surface=bool(args.principal_context),
        )
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_recall_incident(args: argparse.Namespace) -> int:
    try:
        request = RecallIncidentRequest(
            record_id=args.record_id,
            claim_digest=args.claim_digest,
            query=args.query,
            session_id=args.session_id,
            scope_kind=args.scope_kind,
            scope_ref=args.scope_ref,
            observer=args.observer,
            observed=args.observed,
            limit=args.limit,
            max_chars=args.max_chars,
            provider_served_count=args.provider_served_count,
        )
        paths = _paths(args)
        if args.write:
            payload = write_memory_recall_incident(paths, request)
        else:
            payload = build_memory_recall_incident(paths, request)
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_rollup(args: argparse.Namespace) -> int:
    try:
        payload = build_memory_rollup(
            _paths(args),
            tag=args.tag,
            scope_kind=args.scope_kind,
            scope_ref=args.scope_ref,
            apply=args.apply,
        )
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_pin(args: argparse.Namespace) -> int:
    try:
        payload = set_memory_pin(_paths(args), args.record_id, pinned=True)
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_unpin(args: argparse.Namespace) -> int:
    try:
        payload = set_memory_pin(_paths(args), args.record_id, pinned=False)
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_demote(args: argparse.Namespace) -> int:
    try:
        build = stage_memory_demotion if args.stage else build_memory_demotion
        payload = build(
            _paths(args),
            file_label=args.file,
            max_entries=_optional_positive_int(args.max, "--max") or 5,
        )
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_confirm(args: argparse.Namespace) -> int:
    if bool(args.all_due) == bool(args.record_id):
        raise OmhError("pass exactly one of <record-id> or --all-due")
    try:
        if args.all_due:
            if args.stale_after:
                raise OmhError("--stale-after pins one record to one date; --all-due takes --stale-after-days")
            payload = confirm_due_project_memory_records(
                _paths(args),
                confirmed_by=args.confirmed_by,
                stale_after_days=args.stale_after_days,
            )
        else:
            payload = confirm_project_memory_record(
                _paths(args),
                args.record_id,
                confirmed_by=args.confirmed_by,
                stale_after_days=args.stale_after_days,
                stale_after=args.stale_after,
            )
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_keep_open(args: argparse.Namespace) -> int:
    """The 'still open' answer: reset one open record's reminder clock, change nothing else."""
    try:
        payload = keep_memory_record_open(_paths(args), args.record_id)
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    # A refusal (not open, expired, missing) changed nothing and must not read
    # as success to a shell that only checks the status.
    return 0 if bool(payload.get("applied")) else 1


def cmd_memory_attention(args: argparse.Namespace) -> int:
    try:
        change = apply_memory_attention_change if args.apply else build_memory_attention_change
        payload = change(
            _paths(args),
            args.record_id,
            tier=args.tier,
            reason=args.reason,
            query=" ".join(args.query).strip(),
            limit=_optional_positive_int(args.limit, "--limit") or 6,
        )
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_perspectives(args: argparse.Namespace) -> int:
    try:
        payload = build_memory_perspectives(_paths(args))
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_sources(args: argparse.Namespace) -> int:
    """Index the store by source, or enumerate one source's records.

    Always 0 on a completed read. There is no work here that can fail to
    happen: an empty selection is an answer, and which answer it is -- an
    empty store, a store that never recorded a source, or a source this store
    never saw -- is in `selected.outcome`, alongside the indeterminate records
    this selector cannot exclude. A shell must read those, not the status.
    """
    try:
        payload = build_memory_source_index(
            _paths(args),
            source=args.source,
            limit=_optional_positive_int(args.limit, "--limit"),
        )
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_lineage(args: argparse.Namespace) -> int:
    try:
        payload = build_memory_lineage(_paths(args), args.record_id, depth=args.depth)
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_rejected_recall(args: argparse.Namespace) -> int:
    try:
        request = RejectedDecisionRecallRequest(
            " ".join(args.query).strip(),
            args.scope_kind,
            args.scope_ref,
            tuple(args.tag or []),
            args.include_stale,
            args.limit,
        )
        payload = build_rejected_decision_recall(_paths(args), request)
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_inspect(args: argparse.Namespace) -> int:
    try:
        inspection = build_memory_inspection(
            _paths(args),
            wrapper_snapshot=_read_optional_json(args.fixture),
            scope_kind=args.scope_kind,
            scope_ref=args.scope_ref,
            session_limit=_optional_positive_int(args.session_limit, "--session-limit"),
            summary=args.summary,
            review_item_limit=_optional_positive_int(args.review_item_limit, "--review-item-limit"),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(inspection)
    return 0


def cmd_memory_pack(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        inspection = None
        wrapper_snapshot = _read_optional_json(args.fixture)
        if wrapper_snapshot is not None:
            inspection = build_memory_inspection(
                paths,
                wrapper_snapshot=wrapper_snapshot,
                scope_kind=args.scope_kind,
                scope_ref=args.scope_ref,
                session_limit=_optional_positive_int(args.session_limit, "--session-limit"),
                review_item_limit=_optional_positive_int(args.review_item_limit, "--review-item-limit"),
            )
        pack = build_handoff_context_pack(
            paths,
            inspection=inspection,
            executor_target=args.executor,
            session_id=args.session_id,
            scope_kind=args.scope_kind,
            scope_ref=args.scope_ref,
            session_limit=_optional_positive_int(args.session_limit, "--session-limit"),
            context_limit=_optional_positive_int(args.context_limit, "--context-limit") or 12,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(pack)
    return 0


def cmd_memory_apply(args: argparse.Namespace) -> int:
    try:
        batch = _read_required_json(args.batch)
        result = apply_memory_update_batch(_paths(args), batch, dry_run=args.dry_run)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        _control_payload(
            result,
            reason_code="review_required",
            next_action="Stage the batch with `memory batch-stage --batch <path>`, then review every exact item before apply.",
            claim_boundary="Direct batch compatibility is review-required and does not claim prompt use or a completed scope mutation without an operation receipt.",
        )
    )
    return 0


def cmd_memory_inventory(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        inventory = build_memory_migration_inventory(paths)
        payload = write_memory_migration_ledger(paths, inventory) if args.write_ledger else inventory
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        _control_payload(
            payload,
            reason_code="inventory_ledger_written" if args.write_ledger else "inventory_dry_run",
            next_action="Review each review-required artifact before reactivation; inventory does not grant replay eligibility.",
            claim_boundary="Inventory is metadata-only and report-first; it does not approve, reactivate, quarantine, or claim memory use.",
        )
    )
    return 0


def cmd_memory_reactivate(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        if not _has_exact_review_linkage(paths, args.artifact_id, args.revision, args.review_id):
            payload: dict[str, object] = {
                "schema_version": "memory_reactivation/v1",
                "applied": False,
                "reason_code": "matching_immutable_review_required",
                "artifact_identity": {},
            }
        else:
            payload = reactivate_memory_artifact(paths, args.artifact_id, review_id=args.review_id, apply=args.apply)
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    if bool(payload.get("applied")) and not isinstance(payload.get("receipt"), dict):
        payload = {**payload, "applied": False, "reason_code": "operation_receipt_missing"}
    _print_json(
        _control_payload(
            payload,
            next_action=(
                "Apply the exact reviewed artifact with `--apply`."
                if payload.get("reason_code") == "apply_required"
                else "Inspect the returned operation receipt; only the exact reviewed artifact was eligible for reactivation."
            ),
            claim_boundary="Reactivation is exact-artifact review control only; no replay, prompt use, provider, or executor use is claimed.",
        )
    )
    return 0


def cmd_memory_batch_stage(args: argparse.Namespace) -> int:
    try:
        payload = stage_memory_update_batch(_paths(args), _read_required_json(args.batch))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        _control_payload(
            payload,
            reason_code="pending_review",
            next_action="Record one exact remember, refuse, or defer decision for every staged item.",
            claim_boundary="Staged batch candidates are review-only and never prompt eligible; no completed scope mutation is claimed without a receipt.",
        )
    )
    return 0


def cmd_memory_batch_review(args: argparse.Namespace) -> int:
    try:
        payload = review_memory_update_batch(
            _paths(args),
            args.batch_id,
            _read_required_json(args.decisions),
            reviewer_label=args.reviewer_label,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        _control_payload(
            payload,
            reason_code="reviewed",
            next_action="Run `memory batch-apply <batch-id> --apply` only when every exact decision is remember.",
            claim_boundary="Review output is immutable decision metadata; it does not claim a completed scope mutation, prompt use, or executor use without an operation receipt.",
        )
    )
    return 0


def cmd_memory_batch_apply(args: argparse.Namespace) -> int:
    if not args.apply:
        _print_json(
            _control_payload(
                {
                    "schema_version": "memory_update_batch_receipt/v1",
                    "status": "review_required",
                    "reason_code": "apply_required",
                    "applied": False,
                    "batch_id": args.batch_id,
                },
                next_action="Inspect exact immutable review decisions, then rerun with `--apply`.",
                claim_boundary="No scope mutation is claimed without an explicit apply and returned operation receipt.",
            )
        )
        return 0
    try:
        payload = apply_approved_memory_update_batch(_paths(args), args.batch_id)
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    if bool(payload.get("applied")) and not isinstance(payload.get("receipt"), dict):
        payload = {**payload, "applied": False, "status": "failed", "reason_code": "operation_receipt_missing"}
    _print_json(
        _control_payload(
            payload,
            next_action="Inspect the returned operation receipt; refused, deferred, missing, or tampered reviews remain fail-closed.",
            claim_boundary="Batch apply reports only its returned operation receipt; it is not evidence of prompt, provider, or executor use.",
        )
    )
    return 0


def cmd_memory_restore(args: argparse.Namespace) -> int:
    return _cmd_memory_lifecycle(args, "restore")


def cmd_memory_prune(args: argparse.Namespace) -> int:
    return _cmd_memory_lifecycle(args, "prune")


def cmd_memory_correct(args: argparse.Namespace) -> int:
    return _cmd_memory_lifecycle(args, "correct")


def cmd_memory_evaluate(args: argparse.Namespace) -> int:
    try:
        payload = run_memory_evaluation(
            args.profile,
            repetitions=_optional_positive_int(args.repetitions, "--repetitions") or 3,
            seed=args.seed,
        )
        if args.output:
            output = Path(args.output).expanduser()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_recall_suite(args: argparse.Namespace) -> int:
    """One offline command that decides whether recall still selects correctly.

    The exit status is the gate: a retrieval regression makes this command
    fail, so it can stand in CI ahead of a ranking, pin, decay, tier, lens,
    budget, or staleness change without anyone having to read the report first.
    """
    try:
        payload = run_memory_retrieval_evaluation(target_revision=str(args.revision or ""))
        if args.output:
            output = Path(args.output).expanduser()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0 if bool(payload.get("passed")) else 1


def cmd_memory_blocks(args: argparse.Namespace) -> int:
    paths = _paths(args)
    blocks = read_memory_blocks(paths.omh_home, tier=args.tier)
    _print_json(
        {
            "schema_version": "omh_memory_block_listing/v1",
            "blocks": [block.to_summary() for block in blocks],
            "block_count": len(blocks),
            "store_dir": str(blocks_dir(paths.omh_home)),
            "claim_boundary": (
                "Block listings are prepared OMH context; they are not evidence that Hermes read "
                "a block or that any memory was written."
            ),
        }
    )
    return 0


def cmd_memory_block_set(args: argparse.Namespace) -> int:
    try:
        value = sys.stdin.read() if args.stdin else str(args.value or "")
        block = build_memory_block(
            args.label,
            value,
            description=args.description,
            limit=args.limit,
            tier=args.tier,
        )
        path = write_memory_block(_paths(args).omh_home, block)
    except MemoryBlockError as exc:
        raise OmhError(str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"schema_version": "omh_memory_block_write/v1", "written": True, "path": str(path), "block": block.to_summary()})
    return 0


def cmd_memory_block_remove(args: argparse.Namespace) -> int:
    try:
        removed = delete_memory_block(_paths(args).omh_home, args.label, args.tier)
    except MemoryBlockError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"schema_version": "omh_memory_block_remove/v1", "removed": removed, "label": args.label, "tier": args.tier})
    return 0


def cmd_memory_dream(args: argparse.Namespace) -> int:
    """Report whether consolidation is due. Never consolidates: that needs a model.

    Without `--evaluate` this reads the counters and writes nothing. It used to
    build a provider and `initialize` it before looking at `args.evaluate`, and
    `initialize` ends by settling the previous session's unconsolidated turns --
    so asking the status question raised a brief, stamped its reasons as fired,
    zeroed the turn counter, and lowered `compaction_pending`. The standing
    conditions (`headroom_below_floor`, `duplicate_records`, `expiring_records`)
    are suppressed while their exact string is unchanged, so the next real brief
    stayed silent about a condition nobody had cleared.

    `--evaluate` no longer initializes either. The evaluation it reports is now
    its own first one, under the `manual` trigger it actually is, rather than
    the second reading of a `session_start_recovery` that never happened.
    """
    paths = _paths(args)
    payload: dict[str, object] = {}
    if args.evaluate:
        provider = OmhMemoryProvider(paths.omh_home, hermes_home=paths.hermes_home)
        payload = dict(provider.consolidation_due())
    payload["state"] = read_dreaming_state(paths.omh_home)
    payload["evaluated"] = bool(args.evaluate)
    _print_json(payload)
    return 0


def cmd_memory_retire(args: argparse.Namespace) -> int:
    """Report expired records, or move them into the archive with --apply. Never deletes."""
    paths = _paths(args)
    window_days = _optional_positive_int(args.window_days, "--window-days") or 7
    record_id = str(getattr(args, "record_id", "") or "").strip() or None
    try:
        if args.apply:
            payload = apply_memory_retirement(paths, window_days=window_days, record_id=record_id)
        else:
            payload = build_memory_retirement(paths, window_days=window_days, record_id=record_id)
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return _memory_retire_exit_code(payload)


_RETIRE_TARGET_REFUSALS = frozenset({"record_not_found", "not_expired"})


def _memory_retire_exit_code(payload: Any) -> int:
    """0 only when nothing the caller asked for failed to happen.

    A targeted `omh memory retire <id>` that found no such record, or a
    settled live record it refuses to archive, did not do what it was asked;
    a shell reading only the status must not be told it did. The untargeted
    sweep keeps its own vocabulary: an empty sweep is a clean store, not a
    failure. Generic failure signals -- a refused or interrupted run, or a
    unit that failed -- are never success either, so this mapper cannot be
    passed by refusing everything or by ignoring everything.
    """
    summary = payload if isinstance(payload, dict) else {}
    if summary.get("refused") or summary.get("interrupted"):
        return 1
    units = summary.get("units")
    if isinstance(units, list) and any(isinstance(unit, dict) and unit.get("failure_kind") for unit in units):
        return 1
    if str(summary.get("target_record_id", "") or ""):
        skipped = summary.get("skipped")
        if isinstance(skipped, list) and any(
            isinstance(row, dict) and str(row.get("reason", "")) in _RETIRE_TARGET_REFUSALS for row in skipped
        ):
            return 1
    return 0


def cmd_memory_principal_migration(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        if args.report:
            payload = build_principal_migration_report(paths)
        elif args.plan:
            if not args.apply:
                raise ValueError("--plan requires --apply")
            payload = apply_principal_migration(paths, _read_required_json(args.plan))
        else:
            if not args.rollback or not args.apply:
                raise ValueError("--rollback requires an operation id and --apply")
            payload = rollback_principal_migration(paths, args.rollback)
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0 if payload.get("applied", True) else 1


def cmd_memory_principal_export(args: argparse.Namespace) -> int:
    try:
        payload = export_principal_memory(_paths(args), _read_required_json(args.principal_context))
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_provider(args: argparse.Namespace) -> int:
    """Show, take, or hand back Hermes' single external memory-provider slot."""
    paths = _paths(args)
    path = paths.hermes_config_path
    if not (args.enable or args.disable):
        # Status only: nothing to write, so nothing to serialize against.
        text = read_config(path)
        change = None
    else:
        def _claim(config_text: str) -> ConfigChange:
            if args.enable:
                return set_memory_provider(config_text, MEMORY_PROVIDER_NAME)
            return clear_memory_provider(config_text, MEMORY_PROVIDER_NAME)

        try:
            change = update_config(path, _claim, omh_home=paths.omh_home, dry_run=bool(args.dry_run))
        except OSError as exc:
            # A `ConfigWriteRefused` is already an `OmhError` and propagates
            # with the subclass that names its cause; only a bare OSError
            # from the write still needs wrapping, as it did before.
            raise OmhError(str(exc)) from exc
        text = change.text
    selection = memory_provider_selection(change.text if change is not None else text)
    _print_json(
        {
            "schema_version": "omh_memory_provider_status/v1",
            "provider": selection,
            "is_omh": selection == MEMORY_PROVIDER_NAME,
            "config_path": str(path),
            "config_exists": path.is_file(),
            "changed": bool(change.changed) if change is not None else False,
            "reason": change.message if change is not None else "status only",
            "dry_run": bool(args.dry_run),
            "next_action": (
                "Restart Hermes for a provider change to take effect; run `omh setup` first if the "
                "bundle is not installed."
            ),
            "claim_boundary": (
                "This reports and edits Hermes' config selection only. It is not evidence that "
                "Hermes loaded the provider, ran a hook, or changed any memory."
            ),
        }
    )
    return 0


def _cmd_memory_lifecycle(args: argparse.Namespace, operation: str) -> int:
    try:
        paths = _paths(args)
        revision = _required_positive_int(args.revision, "--revision")
        now = datetime.now(timezone.utc)
        principal_context = _read_optional_json(args.principal_context)
        if operation == "restore":
            plan = build_memory_restore(paths, args.record_id, revision, now=now, principal_context=principal_context)
        elif operation == "prune":
            plan = build_memory_prune(paths, args.record_id, revision, now=now, principal_context=principal_context)
        else:
            summary = " ".join(args.summary).strip()
            if not summary:
                raise ValueError("memory correct requires a summary")
            plan = build_memory_correction(
                paths,
                args.record_id,
                revision,
                summary,
                now=now,
                principal_context=principal_context,
            )
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc

    payload = dict(plan.report)
    if args.apply and not payload.get("eligible"):
        pass
    elif args.apply and operation == "prune" and not args.confirm_hard_delete_local:
        payload = {
            **payload,
            "reason_code": "hard_delete_confirmation_required",
            "next_action": "Apply only with --confirm-hard-delete-local; the receipt is not deletion or erasure proof.",
        }
    elif args.apply:
        state = _existing_memory_operation_state(paths, plan.operation_id)
        if state in {"failed", "interrupted", "corrupt"}:
            payload = _lifecycle_operation_state_payload(plan, state)
        else:
            try:
                result = _apply_memory_lifecycle_plan(paths, plan, operation, principal_context)
            except ValueError as exc:
                state = _existing_memory_operation_state(paths, plan.operation_id)
                if state in {"failed", "interrupted", "corrupt"}:
                    payload = _lifecycle_operation_state_payload(plan, state)
                else:
                    raise OmhError(str(exc)) from exc
            else:
                if not bool(result.get("applied")) or not isinstance(result.get("receipt"), dict):
                    raise OmhError("operation_receipt_missing")
                payload = {
                    **result,
                    "reason_code": {"restore": "restored", "prune": "pruned", "correct": "corrected"}[operation],
                }
    _print_json(
        _control_payload(
            payload,
            claim_boundary="Lifecycle reports are OMH-local target-set plans only; no mutation is claimed without a returned lifecycle operation receipt.",
        )
    )
    return 0


def _apply_memory_lifecycle_plan(
    paths,
    plan,
    operation: str,
    principal_context: dict[str, object] | None,
) -> dict[str, object]:
    if operation == "restore":
        return apply_memory_restore(
            paths,
            plan,
            transaction_executor=execute_memory_lifecycle,
            principal_context=principal_context,
        )
    if operation == "prune":
        return apply_memory_prune(
            paths,
            plan,
            transaction_executor=execute_memory_lifecycle,
            confirm_hard_delete_local=True,
            principal_context=principal_context,
        )
    return apply_memory_correction(
        paths,
        plan,
        transaction_executor=execute_memory_lifecycle,
        principal_context=principal_context,
    )


def _lifecycle_operation_state_payload(plan, state: str) -> dict[str, object]:
    return {
        **plan.report,
        "reason_code": f"operation_{state}",
        "operation_id": plan.operation_id,
        "operation_state": state,
        "next_action": plan.report["next_action"],
        "claim_boundary": "No lifecycle mutation is claimed because the existing store operation is not completed and returned no lifecycle receipt.",
    }


def _existing_memory_operation_state(paths, operation_id: str) -> str:
    record_path = paths.memory_operations_dir / f"{operation_id}.json"
    if record_path.is_symlink():
        return "corrupt"
    record, error = read_json_object_result(record_path)
    state = str(record.get("state", "")) if record is not None and error is None else ""
    return state if state in {"failed", "interrupted", "completed", "corrupt"} else ""


def _has_exact_review_linkage(paths, artifact_id: str, revision: int, review_id: str) -> bool:
    if _required_positive_int(revision, "--revision") < 1 or not review_id or Path(review_id).name != review_id:
        return False
    for directory in (paths.memory_dir / "reviews", paths.memory_dir / "block_reviews"):
        path = directory / f"{review_id}.json"
        if path.is_symlink():
            continue
        review, error = read_json_object_result(path)
        identity = review.get("artifact_identity") if review is not None and error is None else None
        if (
            isinstance(identity, dict)
            and review.get("review_id") == review_id
            and identity.get("id") == artifact_id
            and identity.get("revision") == revision
        ):
            return True
    return False


def _validate_capture_governance_args(args: argparse.Namespace) -> None:
    if args.source_class not in SOURCE_CLASSES:
        raise ValueError("unsupported memory source class")
    if args.source_class != "omh_local":
        raise ValueError("memory capture accepts only omh_local source class; external context is not OMH-reviewed")
    _optional_positive_int(args.ttl_days, "--ttl-days", maximum=MAX_RETENTION_DAYS)
    _optional_positive_int(args.stale_after_days, "--stale-after-days", maximum=MAX_RETENTION_DAYS)
    if args.retention_class == "volatile" and args.stale_after_days is not None:
        raise ValueError("volatile memory cannot set --stale-after-days")
    if args.retention_class == "durable" and args.ttl_days is not None:
        raise ValueError("durable memory cannot set --ttl-days")


def _control_payload(
    payload: dict[str, object],
    *,
    reason_code: str | None = None,
    next_action: str | None = None,
    claim_boundary: str,
) -> dict[str, object]:
    result = dict(payload)
    if reason_code is not None:
        result.setdefault("reason_code", reason_code)
    if next_action is not None:
        result.setdefault("next_action", next_action)
    result.setdefault("claim_boundary", claim_boundary)
    return result


def _read_optional_json(path: str | None) -> dict[str, object] | None:
    if not path:
        return None
    return read_memory_snapshot_file(path)


def _read_required_json(path: str) -> dict[str, object]:
    raw = sys.stdin.read() if path == "-" else Path(path).expanduser().read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("memory JSON input must be an object")
    return data


def _optional_positive_int(value: int | None, flag: str, *, maximum: int | None = None) -> int | None:
    if value is None:
        return None
    if value < 1:
        raise ValueError(f"{flag} must be at least 1")
    # An unbounded day count reached `_days_after`, where
    # `created_at + timedelta(days=N)` raises OverflowError -- which is not a
    # ValueError, so it escaped this surface's error handling and printed a raw
    # Python traceback where every other bad flag prints `omh: ...`.
    if maximum is not None and value > maximum:
        raise ValueError(f"{flag} must be at most {maximum}")
    return value


def _required_positive_int(value: int | None, flag: str) -> int:
    result = _optional_positive_int(value, flag)
    if result is None:
        raise ValueError(f"{flag} is required")
    return result


def _add_memory_commands(sub) -> None:
    from .memory_parser import add_memory_commands

    add_memory_commands(sub)
