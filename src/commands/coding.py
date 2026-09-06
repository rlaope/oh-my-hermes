from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

from ..coding_delegation import CODING_EXECUTOR_TARGETS, build_coding_delegation_payload, coding_delegation_record_payload
from ..coding.diagnostic_execution import DiagnosticExecutionEngine
from ..coding.fanout_final_review_hook import FinalReviewWaveEngine
from ..coding.final_review_local_engine import (
    FinalReviewLocalEngineConfig,
    FinalReviewLocalEngineError,
    HermesFinalReviewEngine,
)
from ..coding.local_diagnostic_engine import build_local_diagnostic_engine
from ..coding.executor_capability_snapshots import (
    ExecutorCapabilitySnapshotError,
    build_executor_capability_snapshot,
    read_executor_capability_snapshot,
    validate_executor_capability_snapshot,
    write_executor_capability_snapshot,
)
from ..coding.executor_skill_discovery import (
    discovered_executor_skills,
    skill_selection_card,
    suggested_skill_sequence,
)
from ..coding.executors import EXECUTOR_PROFILES
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
from ..coding.request_complexity import recommend_model_for_complexity, score_request_complexity
from ..plugin_bundle.omh.hermes_delegation import effective_mixture_category_chains
from ..routing.intent import META_OR_FEEDBACK_INTENTS, classify_workflow_intent
from ..routing.localization import normalized_phrase, routing_tokens
from ..runtime.artifacts import append_journal_observation, create_prepared_coding_delegation_run, write_coding_delegation
from ..runtime.records import OBSERVED_RESULTS, WRAPPER_COMPLETION_STATUSES
from ..system.paths import OmhPaths, continuity_write_target
from ..workflows.blocked_work_records import mint_blocked_work_record
from ..workflows.goal_ledger import (
    create_goal_ledger,
    goal_ledger_path,
    merge_obligation_criterion,
    record_goal_checkpoint,
)
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
from .hermes_child import add_hermes_child_command
from .status_board import add_coding_status_board_command


_CAPABILITY_SNAPSHOT_CLAIM_BOUNDARY = (
    "Executor capability snapshots are metadata-only host observations. They are not execution evidence, "
    "verification, review, CI, merge-readiness, or merge evidence."
)
_CAPABILITY_SNAPSHOT_EXECUTOR_TARGETS = tuple(target for target in CODING_EXECUTOR_TARGETS if target != "choose")
_MODEL_CONTRACT_INVENTORY_MAX_BYTES = 1_048_576
_MODEL_CONTRACT_SOURCE_LINEAGE_FIELD = "provenance"


def _model_contract_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, entry in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = entry
    return value


def _reject_model_contract_json_constant(_value: str) -> object:
    raise ValueError("non-finite JSON number")


def _parse_finite_model_contract_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite JSON number")
    return parsed


def _read_model_contract_inventory(path_text: str) -> dict[str, object]:
    try:
        if path_text == "-":
            raw = sys.stdin.read(_MODEL_CONTRACT_INVENTORY_MAX_BYTES + 1)
            encoded = raw.encode("utf-8")
        else:
            with Path(path_text).expanduser().open("rb") as handle:
                encoded = handle.read(_MODEL_CONTRACT_INVENTORY_MAX_BYTES + 1)
            raw = encoded.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise OmhError("model contract audit inventory is not readable UTF-8 JSON") from exc
    if len(encoded) > _MODEL_CONTRACT_INVENTORY_MAX_BYTES:
        raise OmhError(
            f"model contract audit inventory exceeds {_MODEL_CONTRACT_INVENTORY_MAX_BYTES} bytes"
        )
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_model_contract_json_object,
            parse_constant=_reject_model_contract_json_constant,
            parse_float=_parse_finite_model_contract_json_float,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise OmhError("model contract audit inventory is not valid JSON") from exc
    if not isinstance(value, dict):
        raise OmhError("model contract audit inventory must contain a JSON object")
    return value


def cmd_coding_model_contract_audit(args: argparse.Namespace) -> int:
    from ..coding.model_contract_coverage import build_model_contract_coverage, coverage_exit_code

    try:
        report = build_model_contract_coverage(
            _read_model_contract_inventory(args.inventory),
            required_models=args.required_model,
            recommended_models=args.recommended_model,
            intentional_exclusions=args.intentional_exclusion,
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json(report)
    else:
        comparison = report.get("comparison")
        summary = comparison.get("summary") if isinstance(comparison, dict) else None
        if not isinstance(summary, dict):
            raise OmhError("model contract audit produced an invalid summary")
        status_counts = summary.get("status_counts")
        if not isinstance(status_counts, dict):
            raise OmhError("model contract audit produced invalid status counts")
        print(f"Model contract coverage: {summary.get('outcome', 'unknown')}")
        print(f"Comparison digest: {report['comparison_digest']}")
        print(
            "Coverage: "
            + ", ".join(
                f"{name}={count}"
                for name, count in status_counts.items()
            )
        )
        print(str(report["claim_boundary"]))
    return coverage_exit_code(report)


def cmd_coding_delegate(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        source_metadata: dict[str, str] = {}
        plan_artifact: dict[str, object] | None = None
        context_pack = _context_pack(args)
        executor_target = _resolved_executor_for_delegate(args)
        # `--explicit-owner-choice` is a SEPARATE, deliberate flag from
        # `--executor`: bare `--executor` alone stays exactly as conservative
        # as before (see `test_grounded_operator_examples_keep_non_coding_handoffs_conservative`
        # and `test_runtime_delegation_status_does_not_dispatch_fallback_or_clarify`
        # in tests/test_cli.py, both of which pass `--executor` for a
        # generic or ambiguous message and require `clarify`). A caller sets
        # this flag only when it already knows the coding owner was named
        # for THIS run -- an agent relaying the operator's own owner-naming
        # chat message, or an explicit maestro-engine choice -- never as a
        # wrapper/script default.
        explicit_owner_choice = bool(getattr(args, "explicit_owner_choice", False))
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
            explicit_owner_choice=explicit_owner_choice,
            context_pack=context_pack,
            memory_recall_pack=memory_recall_pack,
            plan_artifact=plan_artifact,
            capability_snapshot_directory=paths.omh_home / "coding" / "executor-capability-snapshots",
            project_root=args.project_root or None,
            governance_default=args.governance_default,
            product_family=args.product_family or None,
            # The user's own chains, so the advisory complexity recommendation
            # resolves to models they configured rather than to a name this
            # repo hardcoded. Reading stays here; the builder stays pure.
            model_chains=effective_mixture_category_chains(paths.omh_home),
            requested_model=getattr(args, "model", None) or "",
            requested_effort=getattr(args, "effort", None) or "",
        )
        record_attached_recall_usage(paths, payload)
        if plan_artifact:
            _apply_plan_handoff_source(payload)
            _accept_handoff_role_context(paths, payload)
        if payload.get("delegation_policy") or _payload_choice_required(payload):
            from ..coding.owner_fit import accepted_plan_from_delegation
            from ..executor_readiness import executor_choice_context

            # Same plan the payload's own `coding_owner_fit` block was derived
            # from, so the ranked card and the report cannot disagree.
            payload["executor_choice_context"] = executor_choice_context(
                paths,
                plan=accepted_plan_from_delegation(payload),
            )
        # The decision is recorded here, before anything decides whether a *run*
        # is worth creating, and unconditionally on `--record`. That ordering is
        # the whole point of the change: a denied gate collapses the selection,
        # skips the run, writes no `coding_delegation.json`, and appends no
        # journal event, so until now the one build whose reasoning most needed
        # to outlive the turn was the one that left nothing behind. The store is
        # runtime-wide precisely so it can hold a decision that has no run.
        payload["blocked_work_record"] = _record_coding_decision(paths, payload)
        # An explicit merge/deploy obligation is OMH-owned durable state: record
        # it in the OMH goal ledger here, beside the blocked-work decision and on
        # the same unconditional path, so the obligation outlives the turn even
        # when no run is created. A delegated subtask completing is not this
        # obligation completing; the required merge criterion keeps the goal open
        # until the merge/deploy is observed.
        payload["delegation_continuity_record"] = _record_delegation_continuity(paths, payload)
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
            # The delegated run is a linked subtask of the obligation, never the
            # obligation itself: record it as an in_progress checkpoint so the
            # goal can be reconciled against it after resume without upgrading a
            # subtask's completion into the parent goal's.
            _link_delegation_continuity_run(paths, payload, str(run["run_id"]))
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


def _record_delegation_continuity(paths: OmhPaths, payload: dict[str, object]) -> dict[str, object]:
    """Persist an outstanding merge/deploy obligation as an OMH goal ledger.

    The builder prepares the `delegation_continuity` block (obligation, prepared
    goal slug, the OMH-state-root write policy); the durable write lives here, in
    the command layer, so the builder stays offline. This mirrors
    `_record_coding_decision`: it never fails the command over a store error, and
    it re-derives the ledger's location from `continuity_write_target(paths)` so
    it can only ever write under the OMH goals directory -- never into a product
    repo's `.omo`/`.omx`/`.document-harness` runtime-evidence dirs.

    The goal is created active with a REQUIRED merge/deploy criterion carrying no
    evidence, so it stays open until the merge/deploy is observed. An existing
    ledger under the prepared slug is linked, not overwritten, so a re-delegated
    obligation keeps its in-progress history.
    """
    block = payload.get("delegation_continuity")
    if not isinstance(block, dict):
        return {"recorded": False, "reason": "no_delegation_continuity"}
    obligation = str(block.get("obligation", "")).strip()
    if not obligation:
        return {"recorded": False, "reason": "no_obligation"}
    durable = block.get("durable_record")
    goal_id = str(durable.get("goal_id", "")).strip() if isinstance(durable, dict) else ""
    if not goal_id:
        return {"recorded": False, "reason": "no_goal_id"}
    target = continuity_write_target(paths)
    try:
        path = goal_ledger_path(paths, goal_id)
        if path.exists():
            return {
                "recorded": True,
                "created": False,
                "linked": True,
                "goal_id": goal_id,
                "goal_ledger_path": str(path),
                "state_root": target["state_root"],
            }
        create_goal_ledger(
            paths,
            f"coding-delegation:{obligation}:{goal_id}",
            [merge_obligation_criterion(obligation)],
            goal_id=goal_id,
            source="coding_delegation",
            objective_summary=(
                f"Outstanding {obligation} obligation from a coding delegation; a delegated "
                "subtask completing is not this obligation being met."
            ),
        )
    except (OSError, ValueError) as exc:
        return {"recorded": False, "reason": "goal_ledger_write_failed", "error": str(exc)}
    return {
        "recorded": True,
        "created": True,
        "linked": False,
        "goal_id": goal_id,
        "goal_ledger_path": str(goal_ledger_path(paths, goal_id)),
        "state_root": target["state_root"],
    }


def _link_delegation_continuity_run(paths: OmhPaths, payload: dict[str, object], run_id: str) -> None:
    """Link the delegated run to the obligation goal as an in_progress checkpoint.

    The checkpoint references no acceptance criterion and carries no evidence, so
    linking a subtask never satisfies the required merge/deploy criterion: the
    goal stays open until the merge/deploy is observed. Never fails the command
    over a store error, mirroring the decision and continuity records above.
    """
    record = payload.get("delegation_continuity_record")
    if not isinstance(record, dict) or not record.get("recorded"):
        return
    goal_id = str(record.get("goal_id", "")).strip()
    if not goal_id or not run_id:
        return
    block = payload.get("delegation_continuity")
    obligation = str(block.get("obligation", "")).strip() if isinstance(block, dict) else "merge"
    try:
        record_goal_checkpoint(
            paths,
            goal_id,
            f"Delegated coding run linked to the outstanding {obligation} obligation.",
            status="in_progress",
            linked_runtime_run_id=run_id,
        )
    except (OSError, ValueError):
        return


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


def cmd_coding_executor_skills(args: argparse.Namespace) -> int:
    if args.profile == "hermes":
        raise OmhError("Hermes-native selection bypasses maestro; use the Hermes runtime path.")
    project_root = Path(args.project_root) if args.project_root else None
    payload = discovered_executor_skills(args.profile, project_root=project_root)
    unit_role = getattr(args, "unit_role", "") or ""
    if unit_role:
        payload = dict(payload)
        payload["suggested_sequence"] = suggested_skill_sequence(payload, unit_role)
        card = skill_selection_card(payload, unit_role)
        if card is not None:
            payload["selection_card"] = card
    _print_json(payload)
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


def _parsed_chain_entry(raw: str) -> dict[str, str]:
    """Split one `model[:effort]` CLI token, only when the tail IS an effort.

    Model ids legitimately carry colon tags (`qwen2.5-coder:7b`,
    `openai/gpt-4o:2024-08-06`), so an unconditional last-colon split would
    silently tear the tag off into a bogus reasoning effort. The tail is
    treated as an effort only when it names a known effort level; anything
    else keeps the whole token as the model id.
    """
    from ..coding.model_routing import REASONING_EFFORT_LADDER

    text = str(raw or "").strip()
    if ":" in text:
        model_id, tail = text.rsplit(":", 1)
        effort = tail.strip().casefold()
        if model_id.strip() and effort in (*REASONING_EFFORT_LADDER, "auto"):
            return {"model_id": model_id.strip(), "reasoning_effort": effort}
    return {"model_id": text, "reasoning_effort": ""}


def _stdin_is_tty() -> bool:
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _chain_display_text(chain) -> str:
    return " > ".join(
        str(entry.get("model_id", ""))
        + (f" {entry.get('reasoning_effort')}" if entry.get("reasoning_effort") else "")
        for entry in chain
    )


def category_maestro_interview(paths) -> int:
    """Numbered per-profile/category interview over the Maestro category table.

    Mirrors `omh model-chains interview` (the native lane's editor): Enter
    keeps the current chain, choosing the built-in default clears an operator
    override, and a custom entry goes through the same validation `set` uses.
    Non-interactive callers get a refusal that names the scriptable path
    instead of a hanging prompt.
    """
    from ..coding.category_maestro import (
        CATEGORY_MAESTRO_PROFILES,
        clear_category_maestro_chain,
        read_category_maestro_config,
        set_category_maestro_chain,
    )
    from ..coding.model_routing import BUILTIN_CATEGORY_MODELS, MODEL_CATEGORIES

    if not _stdin_is_tty():
        print(
            "omh: interview needs a terminal; use `omh coding category-maestro show` and "
            "`omh coding category-maestro set <profile> <category> <model[:effort]>...` instead.",
            file=sys.stderr,
        )
        return 2
    config = read_category_maestro_config(paths.omh_home)
    operator_profiles = config.get("profiles", {}) if isinstance(config, dict) else {}
    print("Category-maestro interview — Enter keeps the current chain.")
    changed = 0
    for profile in CATEGORY_MAESTRO_PROFILES:
        walk = input(f"\nConfigure {profile}? [y/N]: ").strip().casefold()
        if walk not in ("y", "yes"):
            continue
        operator_categories = operator_profiles.get(profile, {})
        for category in MODEL_CATEGORIES:
            operator_chain = (
                operator_categories.get(category) if isinstance(operator_categories, dict) else None
            )
            builtin_chain = BUILTIN_CATEGORY_MODELS[profile].get(category, ())
            current = operator_chain if operator_chain else builtin_chain
            source = "operator" if operator_chain else "built-in"
            options: list[str] = [f"keep current ({source}): {_chain_display_text(current)}"]
            if operator_chain:
                options.append(f"built-in default: {_chain_display_text(builtin_chain)}")
            options.append("custom entry (`model[:effort], ...`)")
            print(f"\n[{profile} / {category}]")
            for index, label in enumerate(options, start=1):
                print(f"  {index}) {label}")
            raw = input(f"choose 1-{len(options)} [1]: ").strip() or "1"
            try:
                pick = int(raw)
            except ValueError:
                pick = 0
            if not 1 <= pick <= len(options):
                print("  unrecognized choice; keeping current")
                continue
            if pick == 1:
                continue
            if operator_chain and pick == 2:
                clear_category_maestro_chain(paths.omh_home, profile, category)
                changed += 1
                continue
            custom = input("  chain: ").strip()
            entries = [
                _parsed_chain_entry(token)
                for token in (piece.strip() for piece in custom.split(","))
                if token
            ]
            try:
                set_category_maestro_chain(paths.omh_home, profile, category, entries)
            except ValueError as exc:
                print(f"  {exc}; keeping current")
                continue
            changed += 1
    if not changed:
        print("\nNo changes.")
        return 0
    from ..coding.category_maestro import category_maestro_path

    print(f"\nSaved {changed} chain{'' if changed == 1 else 's'} to {category_maestro_path(paths.omh_home)}.")
    return 0


def cmd_coding_category_maestro(args: argparse.Namespace) -> int:
    from ..coding.category_maestro import (
        CATEGORY_MAESTRO_PROFILES,
        category_maestro_path,
        clear_category_maestro_chain,
        read_category_maestro_config,
        set_category_maestro_chain,
    )
    from ..coding.model_routing import BUILTIN_CATEGORY_MODELS, MODEL_CATEGORIES

    paths = _paths(args)
    command = args.category_maestro_command
    if command == "interview":
        return category_maestro_interview(paths)
    if command == "set":
        try:
            result = set_category_maestro_chain(
                paths.omh_home,
                args.profile,
                args.category,
                [_parsed_chain_entry(entry) for entry in args.chain],
            )
        except ValueError as exc:
            raise OmhError(str(exc)) from exc
        if _wants_json(args):
            _print_json(result)
            return 0
        chain_text = " > ".join(
            str(entry["model_id"]) + (f" {entry['reasoning_effort']}" if entry.get("reasoning_effort") else "")
            for entry in result["chain"]
        )
        print(
            f"category-maestro: {result['profile']} {result['category']} -> {chain_text}\n"
            f"written to {result['path']}"
        )
        return 0
    if command == "clear":
        try:
            result = clear_category_maestro_chain(paths.omh_home, args.profile, args.category)
        except ValueError as exc:
            raise OmhError(str(exc)) from exc
        if _wants_json(args):
            _print_json(result)
            return 0
        state = "cleared (built-in chain applies)" if result["removed"] else "was not set (built-in chain already applies)"
        print(f"category-maestro: {result['profile']} {result['category']} {state}")
        return 0
    # show (the default subcommand): the effective merged table per profile,
    # each category labeled with which basis supplies its chain.
    config = read_category_maestro_config(paths.omh_home)
    operator_profiles = config.get("profiles", {}) if isinstance(config, dict) else {}
    report_profiles: dict[str, object] = {}
    lines = [f"Category-maestro table ({category_maestro_path(paths.omh_home)}):"]
    for profile in CATEGORY_MAESTRO_PROFILES:
        operator_categories = operator_profiles.get(profile, {})
        categories: dict[str, object] = {}
        lines.append(f"- {profile}:")
        for category in MODEL_CATEGORIES:
            operator_chain = operator_categories.get(category) if isinstance(operator_categories, dict) else None
            chain = operator_chain if operator_chain else BUILTIN_CATEGORY_MODELS[profile].get(category, ())
            source = "operator" if operator_chain else "built_in"
            entries = [
                {"model_id": str(entry.get("model_id", "")), "reasoning_effort": str(entry.get("reasoning_effort", ""))}
                for entry in chain
            ]
            categories[category] = {"chain": entries, "source": source}
            chain_text = " > ".join(
                entry["model_id"] + (f" {entry['reasoning_effort']}" if entry["reasoning_effort"] else "")
                for entry in entries
            )
            marker = "*" if source == "operator" else " "
            lines.append(f"  {marker} {category:18s} {chain_text or '-'}")
        report_profiles[profile] = categories
    rejected = list(config.get("rejected", [])) if isinstance(config, dict) else []
    # Catalogless profiles are deliberately absent from this table (#1180's
    # one-basis rule); naming where THEIR categories come from keeps a pi/omo
    # operator from reading this as "pi has no category routing".
    catalogless_note = (
        "omo-runtime (host CLI: pi/senpi) and other catalogless profiles are not configured here: "
        "their categories resolve from the locally-derived model catalog (omo config) — see "
        "`omh coding model-route --executor omo-runtime --from-inventory`."
    )
    payload = {
        "schema_version": "omh_category_maestro_report/v1",
        "path": str(category_maestro_path(paths.omh_home)),
        "configured": config is not None,
        "profiles": report_profiles,
        "rejected": rejected,
        "catalogless_note": catalogless_note,
        "claim_boundary": (
            "This table is prepared routing metadata only; it is not dispatch, execution, "
            "entitlement, or provider availability evidence."
        ),
    }
    if _wants_json(args):
        _print_json(payload)
        return 0
    if rejected:
        lines.append("rejected config pieces:")
        lines.extend(f"  ! {note}" for note in rejected)
    lines.append("* = operator override from category-maestro.json; others are built-in defaults.")
    lines.append(catalogless_note)
    print("\n".join(lines))
    return 0


def cmd_coding_model_route(args: argparse.Namespace) -> int:
    from ..coding.executors import EXECUTOR_PROFILES
    from ..coding.model_routing import (
        EXECUTOR_MODEL_OPTIONS,
        MODEL_ROLES,
        resolve_model_route,
        route_provenance,
    )

    category_config = _operator_category_config(_paths(args))
    if getattr(args, "explain", False):
        profiles = [args.executor] if args.executor else list(EXECUTOR_MODEL_OPTIONS)
        unknown = [profile for profile in profiles if profile not in EXECUTOR_MODEL_OPTIONS]
        if unknown:
            raise OmhError(f"--explain covers catalog profiles only; unknown: {', '.join(unknown)}")
        cells = []
        cell_lines = []
        for profile in profiles:
            for role in MODEL_ROLES:
                route = resolve_model_route(profile, role=role, category_config=category_config)
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
    active_models = None
    if getattr(args, "from_inventory", False):
        inventory = _local_model_inventory()
        local_catalog = _catalog_from_inventory(inventory).get(
            str(args.executor or "").strip().casefold()
        )
        if str(args.executor or "").strip().casefold() == "hermes":
            active_models = _confirmed_active_models(inventory)
    recommendation_overrides = None
    recommendation_path = getattr(args, "recommendations", None)
    if recommendation_path:
        from ..coding.model_recommendations import load_recommendation_overrides

        try:
            recommendation_overrides = load_recommendation_overrides(recommendation_path)
        except (OSError, ValueError) as exc:
            raise OmhError(str(exc)) from exc
    route = resolve_model_route(
        args.executor,
        requested_model=args.model or "",
        requested_effort=args.effort or "",
        role=args.role or "",
        requested_domain=getattr(args, "domain", None) or "",
        requested_depth=getattr(args, "depth", None) or "",
        requested_category=getattr(args, "category", None) or "",
        category_config=category_config,
        local_catalog=local_catalog,
        active_models=active_models,
        recommendation_overrides=recommendation_overrides,
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


def cmd_coding_model_routing_status(args: argparse.Namespace) -> int:
    from ..maintenance.advisory import build_model_routing_status

    payload = build_model_routing_status(
        _paths(args),
        discovery_home=Path(args.discovery_home).expanduser() if args.discovery_home else None,
    )
    if _wants_json(args):
        _print_json(payload)
        return 0
    models = payload["models"]
    hermes = payload["hermes"]
    maestro = payload["maestro"]
    owner = payload["owner_learning"]
    confirmed = ", ".join(str(entry["model_id"]) for entry in models["confirmed"]) or "none"
    discovered = ", ".join(str(entry["model_id"]) for entry in models["discovered_only"]) or "none"
    aliases = ", ".join(f"{name}={target}" for name, target in hermes["aliases"].items()) or "none"
    print("Model routing status (local metadata only):")
    print(f"Confirmed active: {confirmed}")
    print(f"Discovered only (not execution proof): {discovered}")
    print(f"Hermes aliases ({hermes['status']}): {aliases}")
    print(f"Maestro missing recommendation heads: {', '.join(maestro['missing_heads']) or 'none'}")
    print(f"Owner learning: {owner['status']}")
    print(f"Next action: {payload['next_action']}")
    print(str(payload["claim_boundary"]))
    return 0


def cmd_coding_model_routing_reset(args: argparse.Namespace) -> int:
    from ..routing.owner_preference import (
        empty_owner_preference_state,
        owner_preference_path,
        reset_owner_preference,
        validate_owner_preference,
        write_owner_preference,
    )
    from ..system.local_store import read_json_object_result, utc_now

    paths = _paths(args)
    path = owner_preference_path(paths)
    previous_status = "missing"
    if path.exists():
        state, error = read_json_object_result(path)
        validation_errors = validate_owner_preference(state) if state is not None else []
        if error or state is None or validation_errors:
            detail = error or "; ".join(validation_errors) or "expected JSON object"
            raise OmhError(
                f"owner preference state is corrupt at {path}: {detail}; "
                "repair or archive it before reset (no file was changed)"
            )
        previous_status = "present"
    else:
        state = empty_owner_preference_state()
    try:
        reset = reset_owner_preference(
            state,
            route_family=args.route_family,
            reason=args.reason,
            occurred_at=utc_now(),
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    written = write_owner_preference(paths, reset)
    payload = {
        "schema_version": "model_routing_reset/v1",
        "status": "reset",
        "previous_state": previous_status,
        "route_family": args.route_family,
        "reason": args.reason,
        "path": str(written),
        "reset_scope": "owner_preference_metadata_only",
        "next_action": "Run `omh coding model-routing status` to verify the route now requires an explicit owner choice.",
        "claim_boundary": (
            "Reset changes only OMH owner-preference metadata. It does not change Hermes aliases, "
            "provider credentials, recommendations, model availability, or execution state."
        ),
    }
    if _wants_json(args):
        _print_json(payload)
    else:
        print(f"Reset owner preference for {args.route_family} ({previous_status} state).")
        print(str(payload["next_action"]))
        print(str(payload["claim_boundary"]))
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


def _operator_category_config(paths) -> dict[str, object] | None:
    """Read the category-maestro override table; the file's presence is the opt-in.

    Dropped config pieces are surfaced on stderr here — the loader names them
    precisely so a typo'd category is visible during the prepare/route/run
    that ignored it, not only in `category-maestro show`. stdout stays clean
    for the JSON contracts these commands print.
    """
    from ..coding.category_maestro import read_category_maestro_config

    config = read_category_maestro_config(paths.omh_home)
    if isinstance(config, dict):
        for note in config.get("rejected", []):
            print(f"omh: category-maestro: ignored {note}", file=sys.stderr)
    return config


def _local_model_catalogs() -> dict[str, dict[str, object]]:
    """Observe the local inventory once and key its derived catalog by profile.

    The I/O boundary lives here in the command layer: the route resolver and
    contract builder receive the catalog as data and stay pure.
    """
    return _catalog_from_inventory(_local_model_inventory())


def _local_model_inventory() -> dict[str, object]:
    from ..coding.model_inventory import local_model_inventory

    return local_model_inventory()


def _catalog_from_inventory(inventory: dict[str, object]) -> dict[str, dict[str, object]]:
    from ..coding.model_inventory import inventory_model_catalog

    catalog = inventory_model_catalog(inventory)
    if catalog is None:
        return {}
    return {str(catalog.get("executor_profile", "")): catalog}


def _confirmed_active_models(inventory: dict[str, object]) -> list[dict[str, object]]:
    discovery = inventory.get("model_discovery")
    observations = discovery.get("observations", []) if isinstance(discovery, dict) else []
    active: list[dict[str, object]] = []
    for observation in observations:
        if not isinstance(observation, dict) or observation.get("status") != "confirmed_active":
            continue
        model_id = str(observation.get("model_id", ""))
        provider = str(observation.get("provider", ""))
        if not model_id:
            continue
        active.append(
            {
                "model_alias": model_id.rsplit("/", 1)[-1],
                "model_id": model_id,
                "provider": provider,
                "provider_family": provider,
                "model_family": "",
                "compatible_owners": ["hermes"],
                "status": "confirmed_active",
            }
        )
    return active


def cmd_coding_complexity(args: argparse.Namespace) -> int:
    """Score one request and print the advisory model-class recommendation."""
    message = " ".join(args.message).strip() if args.message else (sys.stdin.read().strip() if args.stdin else "")
    if not message:
        raise OmhError("coding complexity requires a request description or --stdin")
    paths = _paths(args)
    complexity = score_request_complexity(message, routed_skill=args.skill or "")
    recommendation = recommend_model_for_complexity(
        complexity,
        chains=effective_mixture_category_chains(paths.omh_home),
        requested_model=args.model or "",
        requested_effort=args.effort or "",
    )
    payload = {
        "schema_version": "coding_complexity_report/v1",
        "complexity": complexity,
        "recommendation": recommendation,
    }
    if _wants_json(args):
        _print_json(payload)
        return 0
    print(f"Complexity: {complexity['tier']} (score {complexity['score']})")
    print("Signals (score is their sum; no other input moves the tier):")
    for signal in complexity["signals"]:
        print(f"  {signal['weight']:+d}  {signal['name']}: {', '.join(signal['evidence'])}")
    if not complexity["signals"]:
        print("  (none fired; the score is 0)")
    resolved = recommendation["resolved"]
    print(f"Recommended model class: {recommendation['model_class']} at effort {recommendation['reasoning_effort']}")
    if resolved:
        print(f"  Your chain head for that class: {resolved['model']} [{recommendation['chain_status']}]")
    else:
        print(f"  No model resolved from your chains [{recommendation['chain_status']}]")
    if recommendation["status"] == "superseded_by_user_override":
        override = recommendation["user_override"]
        print(f"Your explicit choice wins: model={override['model'] or '-'} effort={override['reasoning_effort'] or '-'}")
    return 0


def cmd_coding_model_contract(args: argparse.Namespace) -> int:
    from ..coding.model_contracts import (
        dynamic_effort_guidance,
        model_contract,
        model_contract_projection,
    )
    from ..coding.model_routing import model_family

    model = str(args.model or "").strip()
    contract = model_contract(model)
    projection = model_contract_projection(model)
    if contract is None or projection is None:
        raise OmhError(
            f"no documented contract for `{model}`; the route resolver keeps treating it by family "
            f"(`{model_family(model) or 'unknown'}`) and the catalog alone"
        )
    executor = str(getattr(args, "executor", "") or "").strip()
    payload: dict[str, object] = {
        "schema_version": "model_contract_report/v1",
        "requested_model": model,
        "family": model_family(model) or "unknown",
        "projection": projection,
        "contract": dict(contract),
        "effort_policy": dynamic_effort_guidance(model, executor),
    }
    if _wants_json(args):
        _print_json(payload)
        return 0
    print(
        f"Requested `{projection['requested_model']}` resolves by "
        f"{projection[_MODEL_CONTRACT_SOURCE_LINEAGE_FIELD]} to `{projection['contract_model_id']}` "
        f"with reasoning mode `{projection['reasoning_mode']}` and "
        f"service tier `{projection['service_tier']}`."
    )
    print(f"Documented contract for `{contract['model_id']}` ({payload['family']} family):")
    print(f"- reasoning efforts: {', '.join(contract['reasoning_efforts'])} (floor `{contract['effort_floor']}`)")
    for effort, detail in dict(contract.get("unsupported_efforts", {})).items():
        print(f"- `{effort}`: {detail}")
    print(f"- tool calling: {contract['tool_calling']['api']} API — {contract['tool_calling']['note']}")
    print(f"- unsupported parameters: {', '.join(contract['unsupported_parameters'])}")
    print(
        f"- context {contract['context_window_tokens']:,} tokens; input {contract['max_input_tokens']:,}; "
        f"output {contract['max_output_tokens']:,}; knowledge cutoff {contract['knowledge_cutoff']}"
    )
    policy = payload["effort_policy"]
    if isinstance(policy, dict):
        print(f"- effort policy ({policy['mode']}): {policy['mechanism']}")
        if policy.get("note"):
            print(f"  {policy['note']}")
    print(f"- sources ({contract['sources_read']}):")
    for source in contract["sources"]:
        print(f"  {source}")
    print(str(contract["claim_boundary"]))
    return 0


def cmd_coding_composition_guide(args: argparse.Namespace) -> int:
    from ..coding.model_contracts import dynamic_effort_guidance
    from ..coding.model_routing import model_family
    from ..coding.unit_prompt_protocol import (
        GOAL_ECHO_PROTOCOL,
        MAIN_AGENT_COMPOSITION_CALIBRATIONS,
        MODEL_COMPOSITION_CALIBRATIONS,
        PROMPT_CACHE_COMPOSITION_PROTOCOL,
        REVIEW_ROLE_PROTOCOL,
        VERIFICATION_STOP_PROTOCOL,
        composition_calibration_for_model,
    )

    delegation_protocol = {
        "goal_echo": GOAL_ECHO_PROTOCOL,
        "verification_stop": VERIFICATION_STOP_PROTOCOL,
        "review_cap": REVIEW_ROLE_PROTOCOL,
        "prompt_cache": PROMPT_CACHE_COMPOSITION_PROTOCOL,
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
        effort_policy = dynamic_effort_guidance(model, str(getattr(args, "executor", "") or ""))
        if effort_policy is not None:
            payload["effort_policy"] = effort_policy
        if _wants_json(args):
            _print_json(payload)
            return 0
        print(f"Composition guidance for `{model}` ({payload['family']} family):")
        print(str(payload["calibration"]))
        if effort_policy is not None:
            print(f"Effort policy ({effort_policy['mode']}): {effort_policy['mechanism']}")
        print("Delegation protocol (embed in every delegated or reviewer prompt, runtime-native included):")
        print(f"- {GOAL_ECHO_PROTOCOL}")
        print(f"- {VERIFICATION_STOP_PROTOCOL}")
        print(f"- {REVIEW_ROLE_PROTOCOL}")
        print(f"- {PROMPT_CACHE_COMPOSITION_PROTOCOL}")
        return 0
    payload = {
        "schema_version": "composition_guide/v1",
        "calibrations": dict(MAIN_AGENT_COMPOSITION_CALIBRATIONS),
        "model_calibrations": dict(MODEL_COMPOSITION_CALIBRATIONS),
        "delegation_protocol": delegation_protocol,
    }
    if _wants_json(args):
        _print_json(payload)
        return 0
    lines = ["Main-agent composition calibrations by model family:"]
    for family, block in MAIN_AGENT_COMPOSITION_CALIBRATIONS.items():
        lines.append(f"- {family}: {block}")
    lines.append("Prompt-cache discipline (every family):")
    lines.append(f"- {PROMPT_CACHE_COMPOSITION_PROTOCOL}")
    print("\n".join(lines))
    return 0


def cmd_coding_fanout_prepare(args: argparse.Namespace) -> int:
    from ..coding.executor_capability_snapshots import (
        ExecutorCapabilitySnapshotError,
        resolved_executor_capability_snapshot,
    )
    from ..coding.fanout import build_fanout_contract, is_degenerate_single_unit, single_unit_redirect
    from ..coding.fanout_artifacts import write_fanout_contract
    from ..coding.fanout_contracts import FanoutContractError
    from ..coding.model_routing import EXECUTOR_MODEL_OPTIONS

    units, spawn_plan = _read_fanout_payload(args.units)
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
        paths = _paths(args)
        owners = {
            str(unit.get("owner", "") or "")
            for unit in units
            if isinstance(unit, dict) and str(unit.get("owner", "") or "")
        }
        capability_snapshots = {
            owner: resolved_executor_capability_snapshot(
                owner,
                paths.executor_capability_snapshots_dir,
            )
            for owner in sorted(owners)
        }
        contract = build_fanout_contract(
            " ".join(args.goal).strip(),
            units,
            source=args.source,
            source_metadata=_explicit_source_metadata(args),
            local_catalogs=_local_model_catalogs() if needs_inventory else {},
            category_config=_operator_category_config(paths),
            capability_snapshots=capability_snapshots,
            spawn_plan=spawn_plan,
        )
    except (FanoutContractError, ExecutorCapabilitySnapshotError) as exc:
        raise OmhError(str(exc)) from exc
    if args.record:
        contract = write_fanout_contract(paths, contract)
    _print_json(contract)
    return 0


def cmd_coding_fanout_validate(args: argparse.Namespace) -> int:
    from ..coding.fanout import (
        detect_boundary_overlaps,
        merge_order,
        require_spawn_plan,
        spawn_plan_required,
        validate_fanout_units,
        _normalized_unit,
    )
    from ..coding.fanout_contracts import FanoutContractError

    raw_units, spawn_plan = _read_fanout_payload(args.units)
    # Computed before the gate, and reported on both paths: a wrapper deciding
    # whether to ask the operator for a plan needs this answer most when the
    # gate has just refused. `spawn_plan_required` is pure and cannot raise.
    requires_plan = spawn_plan_required(len(raw_units))
    try:
        # Inside the try, because `_normalized_unit` raises on a non-object
        # entry too. Outside it, a malformed unit escaped as a traceback with
        # an empty stdout, and a wrapper following this command's documented
        # contract parsed that empty string as JSON.
        units = [_normalized_unit(unit, index) for index, unit in enumerate(raw_units)]
        validate_fanout_units(units)
        # Same checks `prepare` runs, in the same order, so `validate` cannot
        # report a split that `prepare` will then refuse to freeze — including
        # the spawn-plan gate running last, after the structural ones.
        notes = detect_boundary_overlaps(units)
        order = merge_order(units)
        require_spawn_plan(len(units), spawn_plan)
    except FanoutContractError as exc:
        _print_json(
            {
                "schema_version": "fanout_validation/v1",
                "ok": False,
                # `raw_units`, not `units`: a malformed entry means `units` was
                # never bound, and the caller still needs the count it sent.
                "unit_count": len(raw_units),
                "spawn_plan_required": requires_plan,
                "error": str(exc),
            }
        )
        return 1
    _print_json(
        {
            "schema_version": "fanout_validation/v1",
            "ok": True,
            "unit_count": len(units),
            "spawn_plan_required": requires_plan,
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


def _brief_decline_reason(dispatched: dict) -> str:
    """The unit's own negative-conclusive reason, when it validly reported one.

    Empty for every ordinary failure: an exit code alone reports `failed`
    already, and that is not this. Set only when the executor's own validated
    `fanout_unit_result/v1` sidecar named `process_status` `process_declined` --
    a distinct, structured claim that the work cannot be done at all, never a
    retry candidate.
    """
    unit_result = dispatched.get("unit_result")
    if not isinstance(unit_result, dict):
        return ""
    if str(unit_result.get("process_status", "")) != "process_declined":
        return ""
    return str(unit_result.get("decline_reason", ""))


def _brief_recovery(dispatched: dict) -> dict[str, object]:
    """The salvage line for one unit: outcome, size, and how to get the patch.

    `unknown` when the unit was never dispatched, matching how every other
    field in this view reports an absent observation rather than inferring one.
    A successful unit is never probed, so it reports `not_applicable`.
    """
    record = dispatched.get("recovery")
    if not isinstance(record, dict):
        if not dispatched:
            return {"outcome": "unknown"}
        return {"outcome": "not_applicable"}
    brief: dict[str, object] = {"outcome": str(record.get("outcome", "unknown"))}
    for key in ("paths_changed", "lines_changed", "diff_bytes", "recover_with", "recovery_ref", "reason"):
        if key in record:
            brief[key] = record[key]
    return brief


def _bounded_fanout_brief_scalar(value: object) -> str:
    from ..system.metadata_safety import redact_metadata_text

    if not isinstance(value, str):
        return ""
    return redact_metadata_text(value, limit=80)


def cmd_coding_fanout_brief(args: argparse.Namespace) -> int:
    from ..coding.fanout_artifacts import fanout_dispatch_summary_path, read_fanout_contract
    from ..coding.fanout_contracts import FANOUT_UNIT_OWNERS, PREPARED_NOT_OBSERVED
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
        selected_model = model_route.get("selected_model", "")
        selected_effort = model_route.get("selected_reasoning_effort", "")
        model_id = _bounded_fanout_brief_scalar(selected_model)
        effort = _bounded_fanout_brief_scalar(selected_effort)
        # One human-readable label per subagent, e.g. "gpt-5.6-sol xhigh" —
        # what a briefing renders next to the unit without joining two fields.
        # The format is a stable part of fanout_briefing/v1 and is built by
        # the same `model_label_for` helper the status board uses, so the two
        # surfaces cannot drift apart. The chain alternative ships as the
        # separate additive `model_alternative` field, never as a suffix here.
        model_label = model_label_for(model_id, effort)
        chain = model_route.get("chain", []) if isinstance(model_route.get("chain"), list) else []
        alternative_value = chain[1].get("model_id", "") if len(chain) > 1 and isinstance(chain[1], dict) else ""
        model_alternative = _bounded_fanout_brief_scalar(alternative_value)
        route_schema_version = model_route.get("schema_version", "")
        route_version = _bounded_fanout_brief_scalar(route_schema_version)
        owner_value = unit.get("owner")
        owner = (
            owner_value
            if isinstance(owner_value, str) and owner_value in FANOUT_UNIT_OWNERS
            else "choose"
        )
        units.append(
            {
                "unit_id": unit_id,
                "owner": owner,
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
                # The salvage signal, beside the other failure annotation this
                # view already carries. Without it the operator reads
                # `status: failed`, deletes the unit worktree so a re-dispatch
                # can recreate it, and destroys the work the recovery record
                # exists to preserve.
                "recovery": _brief_recovery(dispatched),
                "decline_reason": _brief_decline_reason(dispatched),
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


def cmd_coding_fanout_status(args: argparse.Namespace) -> int:
    """Render one fanout's unit roster from observed journal events.

    Read-only by construction: the projection touches the observation journal
    and nothing else, so this surface can never advance a unit, revive one, or
    record that someone looked.
    """
    from ..coding.fanout_status import project_fanout_status, render_fanout_status_text

    paths = _paths(args)
    try:
        roster = project_fanout_status(paths, args.fanout_id)
    except (OSError, ValueError) as exc:
        raise OmhError(f"fanout status unavailable: {exc}") from exc
    if _wants_json(args):
        _print_json(roster)
    else:
        print(render_fanout_status_text(roster))
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
        # Owner and model are ONE field visually: "codex (gpt-5.6-sol xhigh)".
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


def _failure_recovery_kwargs(args: argparse.Namespace) -> dict:
    """Resolve the failure-recovery inputs the dispatch engine takes.

    The interview runs only when `--on-failure` is left at `report` AND stdin is
    a real terminal AND `--no-interactive` was not passed: a named mode is the
    operator answering on the command line, and a pipe or a CI job must never
    block on a prompt that nobody can see.
    """
    from ..coding.dispatch_failure_recovery import (
        ON_FAILURE_REPORT,
        OnFailureModeError,
        parse_on_failure,
    )
    from ..executors import EXECUTOR_PROFILES

    try:
        mode, target_owner = parse_on_failure(
            getattr(args, "on_failure", "") or "", known_owners=EXECUTOR_PROFILES
        )
    except OnFailureModeError as exc:
        raise OmhError(str(exc)) from exc
    interactive = (
        mode == ON_FAILURE_REPORT
        and not getattr(args, "no_interactive", False)
        and sys.stdin.isatty()
    )
    routing = {
        "model": getattr(args, "hermes_model", "") or "",
        "provider": getattr(args, "hermes_provider", "") or "",
        "reasoning": getattr(args, "hermes_reasoning", "") or "",
    }
    return {
        "ignore_limit_signal": bool(getattr(args, "ignore_limit_signal", False)),
        "on_failure": mode,
        "retarget_owner": target_owner,
        "interactive": interactive,
        "read_line": input if interactive else None,
        # stderr, so a caller piping the dispatch JSON reads a clean document.
        "write_line": _write_stderr_line,
        "hermes_routing": routing,
    }


def _write_stderr_line(line: str) -> None:
    print(line, file=sys.stderr)


def _fanout_dispatch_exit_code(summary: dict) -> int:
    """130 for a cut-short batch, 1 for a refusal, 0 otherwise.

    A spawn-guard refusal exits non-zero on purpose: the summary is still
    printed as JSON so a wrapper can read `refusal_reason`, but a shell that
    only checks the status must not read "nothing was dispatched" as success.
    """
    if summary.get("interrupted"):
        return 130
    if summary.get("refused"):
        return 1
    return 0


def cmd_coding_fanout_dispatch(
    args: argparse.Namespace,
    *,
    diagnostic_engine: DiagnosticExecutionEngine | None = None,
    final_review_engine: FinalReviewWaveEngine | None = None,
) -> int:
    import subprocess as _subprocess

    from ..coding.fanout_artifacts import (
        read_fanout_contract,
        read_fanout_contract_provenance,
    )
    from ..coding.fanout_dispatch import dispatch_fanout, fanout_dispatch_preflight
    from ..coding.fanout_journal import FanoutJournalError, read_fanout_run_journal
    from ..coding.parallelism_policy import read_parallelism_policy, resolve_fanout_concurrency

    paths = _paths(args)
    recovery_kwargs = _failure_recovery_kwargs(args)
    selected_diagnostic_engine = (
        (diagnostic_engine or build_local_diagnostic_engine())
        if args.diagnostics
        else None
    )
    try:
        parallelism = read_parallelism_policy(paths)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    concurrency = resolve_fanout_concurrency(parallelism, args.concurrency)
    try:
        contract = read_fanout_contract(paths, args.fanout_id)
        read_fanout_contract_provenance(
            paths,
            args.fanout_id,
            contract,
        )
    except (OSError, ValueError) as exc:
        raise OmhError(f"fanout contract not found: {exc}") from exc
    resume_journal = None
    if args.resume_journal:
        # Refused loudly rather than treated as an empty prior run: reading an
        # unusable journal as "nothing happened" would re-dispatch every unit,
        # including the ones a replay would destroy.
        try:
            resume_journal = read_fanout_run_journal(
                Path(args.resume_journal).expanduser(),
                expected_fanout_id=str(args.fanout_id),
            )
        except FanoutJournalError as exc:
            raise OmhError(f"{exc} ({exc.reason_code})") from exc
    goal_text = sys.stdin.read() if args.goal_file == "-" else Path(args.goal_file).expanduser().read_text(encoding="utf-8")
    if bool(args.integration_worktree) != bool(args.integration_revision):
        raise OmhError("--integration-worktree and --integration-revision must be supplied together")
    if args.integration_worktree and not args.run_verification:
        raise OmhError("--integration-worktree and --integration-revision require --run-verification")
    integrated_worktree = (
        Path(args.integration_worktree).expanduser().resolve() if args.integration_worktree else None
    )
    selected_final_review_engine = (
        final_review_engine if getattr(args, "final_review", False) else None
    )
    if getattr(args, "final_review", False) and selected_final_review_engine is None:
        if integrated_worktree is None or not args.integration_revision:
            raise OmhError(
                "--final-review requires --integration-worktree and "
                "--integration-revision"
            )
        try:
            selected_final_review_engine = HermesFinalReviewEngine(
                FinalReviewLocalEngineConfig(
                    worktree=integrated_worktree,
                    goal_text=goal_text,
                    provider=str(args.hermes_provider),
                    model=str(args.hermes_model),
                    reasoning=str(args.hermes_reasoning or "medium"),
                    timeout_seconds=min(float(args.timeout), 900.0),
                )
            )
        except FinalReviewLocalEngineError as exc:
            raise OmhError(str(exc)) from exc
    repo_root = Path(args.repo_root).expanduser().resolve()
    try:
        preflight = fanout_dispatch_preflight(
            paths,
            contract,
            only_units=args.unit,
            goal_text=goal_text,
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if preflight["invalid_selected"]:
        summary = dispatch_fanout(
            paths,
            contract,
            goal_text=goal_text,
            repo_root=repo_root,
            base_sha="",
            concurrency=concurrency["applied"],
            adaptive_concurrency=bool(args.adaptive_concurrency),
            per_owner_lanes=parallelism["per_owner"],
            concurrency_policy=concurrency,
            max_depth=parallelism["max_depth"],
            spawn_ceiling=parallelism["run_spawn_ceiling"],
            max_retries=parallelism["max_retries"],
            timeout=args.timeout,
            only_units=args.unit,
            dry_run=bool(args.dry_run),
            run_verification=bool(args.run_verification),
            integrated_worktree=integrated_worktree,
            integrated_revision=args.integration_revision or None,
            resume_journal=resume_journal,
            goal_attempt_id=args.goal_attempt_id,
            goal_attempt_progressed=bool(args.goal_attempt_progressed),
            review_dispatch_budget=args.review_dispatch_budget,
            diagnostic_engine=selected_diagnostic_engine,
            final_review_engine=selected_final_review_engine,
            emit_health_events=bool(args.health_events),
            **recovery_kwargs,
        )
        _print_json(summary)
        return _fanout_dispatch_exit_code(summary)
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
            # The ref is carried alongside the SHA it resolved to so each
            # worktree add can re-check that the base has not moved between
            # this single resolve and the unit's own creation.
            source_ref=args.base_ref,
            concurrency=concurrency["applied"],
            adaptive_concurrency=bool(args.adaptive_concurrency),
            per_owner_lanes=parallelism["per_owner"],
            concurrency_policy=concurrency,
            max_depth=parallelism["max_depth"],
            spawn_ceiling=parallelism["run_spawn_ceiling"],
            max_retries=parallelism["max_retries"],
            timeout=args.timeout,
            only_units=args.unit,
            dry_run=bool(args.dry_run),
            run_verification=bool(args.run_verification),
            integrated_worktree=integrated_worktree,
            integrated_revision=args.integration_revision or None,
            resume_journal=resume_journal,
            goal_attempt_id=args.goal_attempt_id,
            goal_attempt_progressed=bool(args.goal_attempt_progressed),
            review_dispatch_budget=args.review_dispatch_budget,
            diagnostic_engine=selected_diagnostic_engine,
            final_review_engine=selected_final_review_engine,
            emit_health_events=bool(args.health_events),
            **recovery_kwargs,
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(summary)
    return _fanout_dispatch_exit_code(summary)


def cmd_coding_run(args: argparse.Namespace) -> int:
    """Build a one-unit fanout contract for an explicitly-chosen owner and dispatch it now.

    This is the single-invocation surface for the case the fanout ceremony was
    never built for: one already-chosen coding owner running one prepared
    task. It drives the SAME `build_fanout_contract` / `write_fanout_contract`
    / `dispatch_fanout` machinery `omh coding fanout prepare` and `omh coding
    fanout dispatch` already use -- never a parallel spawn implementation --
    so per-unit worktree isolation, the executor-progress HUD binding, model
    routing and the dispatch-model-preference fallback, session/thread id
    capture, unit result intake, and the run summary all apply unchanged.

    `--model`/`--effort` are this run's own explicit choice: precedence is
    `--model` flag > routed handoff model > dispatch-models.json preference >
    the executor CLI's own default. The value passes through to the spawned
    CLI unvalidated; an unknown model surfaces as that CLI's own observed
    exit failure, never a silent fallback.

    Dispatch stays explicit per invocation and never merges; running this
    command against an explicitly-named owner IS the opt-in -- there is no
    separate propose/freeze step to expose to a caller that already knows
    what it wants run.
    """
    import subprocess as _subprocess

    from ..coding.executor_capability_snapshots import (
        ExecutorCapabilitySnapshotError,
        resolved_executor_capability_snapshot,
    )
    from ..coding.fanout import build_fanout_contract
    from ..coding.fanout_artifacts import write_fanout_contract
    from ..coding.fanout_contracts import FanoutContractError
    from ..coding.fanout_dispatch import dispatch_fanout
    from ..coding.model_routing import EXECUTOR_MODEL_OPTIONS
    from ..coding.parallelism_policy import read_parallelism_policy, resolve_fanout_concurrency

    paths = _paths(args)
    if args.goal_file:
        goal_text = (
            sys.stdin.read()
            if args.goal_file == "-"
            else Path(args.goal_file).expanduser().read_text(encoding="utf-8")
        )
    else:
        goal_text = " ".join(args.goal or []).strip()
    if not goal_text.strip():
        raise OmhError("coding run requires a goal: pass --goal words, or --goal-file")

    unit: dict[str, object] = {
        "unit_id": args.unit_id,
        "title": " ".join(goal_text.split())[:120],
        "owner": args.owner,
        "file_scope": args.file_scope or ["."],
        "depends_on": [],
        # An explicit `--model` here routes through the same
        # `model_route_for_unit` machinery `omh coding fanout prepare` units
        # already use (see `_contract_unit` in fanout.py): it becomes the
        # unit's frozen `handoff.model_route`, which the dispatch-model
        # preference in dispatch_fanout only ever fills a GAP in, never
        # overrides. That gives the documented precedence for free: this
        # flag > dispatch-models.json preference > the executor CLI's own
        # default -- passthrough, unvalidated, exactly like `model-route
        # --model`.
        "model": args.model or "",
        "reasoning_effort": args.effort or "",
        # A declared work category routes through the category-maestro merged
        # table exactly like a fanout unit's `category` field; `--model` still
        # wins (requested > category chain head).
        "category": getattr(args, "category", None) or "",
    }
    needs_inventory = args.owner not in EXECUTOR_MODEL_OPTIONS
    try:
        capability_snapshots = {
            args.owner: resolved_executor_capability_snapshot(
                args.owner,
                paths.executor_capability_snapshots_dir,
            )
        }
        contract = build_fanout_contract(
            goal_text,
            [unit],
            source=args.source,
            source_metadata=_explicit_source_metadata(args),
            local_catalogs=_local_model_catalogs() if needs_inventory else {},
            category_config=_operator_category_config(paths),
            capability_snapshots=capability_snapshots,
        )
    except (FanoutContractError, ExecutorCapabilitySnapshotError) as exc:
        raise OmhError(str(exc)) from exc
    # Recorded unconditionally, unlike `fanout prepare --record`: the whole
    # point of this command is to run the unit now, and `omh coding fanout
    # show/brief/reap` need the contract on disk to project it afterward.
    contract = write_fanout_contract(paths, contract)

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
        parallelism = read_parallelism_policy(paths)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    concurrency = resolve_fanout_concurrency(parallelism, None)
    try:
        summary = dispatch_fanout(
            paths,
            contract,
            goal_text=goal_text,
            repo_root=repo_root,
            base_sha=resolved.stdout.strip(),
            source_ref=args.base_ref,
            concurrency=concurrency["applied"],
            per_owner_lanes=parallelism["per_owner"],
            concurrency_policy=concurrency,
            max_depth=parallelism["max_depth"],
            spawn_ceiling=parallelism["run_spawn_ceiling"],
            max_retries=parallelism["max_retries"],
            timeout=args.timeout,
            dry_run=bool(args.dry_run),
            run_verification=bool(args.run_verification),
            **_failure_recovery_kwargs(args),
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    payload = {
        "schema_version": "coding_run/v1",
        "fanout_id": contract.get("fanout_id", ""),
        "unit_id": args.unit_id,
        "owner": args.owner,
        "isolation": "isolated_worktree",
        "dispatch": summary,
        "claim_boundary": (
            "This drives the same fanout propose/freeze/dispatch machinery as "
            "`omh coding fanout dispatch`, scoped to one unit. Dispatch is not "
            "review, CI, or merge evidence, and it never merges."
        ),
    }
    _print_json(payload)
    return _fanout_dispatch_exit_code(summary)


def cmd_coding_fanout_reap(args: argparse.Namespace) -> int:
    from ..coding.fanout_reap import reap_fanout_units

    paths = _paths(args)
    report = reap_fanout_units(paths, args.fanout_id, pids=args.pid or None)
    _print_json(report)
    if report.get("status") != "observed":
        return 1
    # A candidate that survived or could not be signalled is a failed
    # remediation; exiting 0 would let `reap && rm -rf <worktree>` proceed
    # against a live agent.
    failed = any(
        row.get("status") in {"still_alive", "refused_permission"}
        for row in report.get("candidates", [])
    )
    return 1 if failed else 0


def cmd_coding_fanout_migrate_legacy(args: argparse.Namespace) -> int:
    from copy import deepcopy

    from ..coding.executor_capability_snapshots import (
        resolved_executor_capability_snapshot,
    )
    from ..coding.fanout_dispatch import fanout_dispatch_preflight
    from ..coding.fanout_artifacts import read_fanout_contract, write_fanout_contract
    from ..coding.fanout_artifacts import (
        fanout_contract_digest,
        fanout_contract_provenance_path,
        read_fanout_contract_provenance,
    )
    from ..coding.fanout_contracts import (
        FANOUT_CONTRACT_SCHEMA_VERSION,
        LEGACY_FANOUT_CONTRACT_SCHEMA_VERSION,
    )

    paths = _paths(args)
    try:
        contract = read_fanout_contract(paths, args.fanout_id)
    except (OSError, ValueError) as exc:
        raise OmhError(f"fanout contract not found: {exc}") from exc
    schema_version = contract.get("schema_version")
    if schema_version == FANOUT_CONTRACT_SCHEMA_VERSION:
        raise OmhError("fanout contract already uses fanout_contract/v2")
    if schema_version != LEGACY_FANOUT_CONTRACT_SCHEMA_VERSION:
        raise OmhError("only fanout_contract/v1 can be migrated")
    units = contract.get("units")
    if not isinstance(units, list):
        raise OmhError("legacy fanout contract units must be a list")
    digest = fanout_contract_digest(contract)
    provenance_path = fanout_contract_provenance_path(paths, args.fanout_id)
    if provenance_path.exists():
        try:
            read_fanout_contract_provenance(paths, args.fanout_id, contract)
        except (OSError, ValueError) as exc:
            raise OmhError(
                f"legacy fanout provenance is invalid; migration refused: {exc}"
            ) from exc
    elif args.confirm_contract_sha256 != digest:
        _print_json(
            {
                "schema_version": "fanout_legacy_migration_preview/v1",
                "fanout_id": args.fanout_id,
                "status": "confirmation_required",
                "contract_sha256": digest,
                "next_command": (
                    "omh coding fanout migrate-legacy "
                    f"{args.fanout_id} --confirm-contract-sha256 {digest}"
                ),
                "claim_boundary": (
                    "This digest confirms the exact local legacy payload selected "
                    "for migration. It is corruption detection, not authentication "
                    "against a writer who controls OMH home."
                ),
            }
        )
        return 0
    migrated = deepcopy(contract)
    migrated["schema_version"] = FANOUT_CONTRACT_SCHEMA_VERSION
    migrated_units = migrated.get("units")
    if not isinstance(migrated_units, list):
        raise OmhError("legacy fanout contract units must be a list")
    try:
        for unit in migrated_units:
            if not isinstance(unit, dict):
                raise ValueError("legacy fanout contract units must be objects")
            owner = unit.get("owner")
            handoff = unit.get("handoff")
            if (
                not isinstance(unit.get("unit_id"), str)
                or not unit["unit_id"]
                or not isinstance(unit.get("title"), str)
                or not isinstance(unit.get("run_ref"), str)
                or not unit["run_ref"]
            ):
                raise ValueError("legacy fanout contract unit identity is invalid")
            if owner is not None and not isinstance(owner, str):
                raise ValueError("legacy fanout contract owner is invalid")
            if not isinstance(handoff, dict):
                raise ValueError("legacy fanout contract handoff is invalid")
            expected_target = owner if owner is not None else "choose"
            if (
                handoff.get("schema_version") != "fanout_unit_handoff/v1"
                or handoff.get("executor_target") != expected_target
                or handoff.get("dispatch_policy") != "prepare_only"
            ):
                raise ValueError("legacy fanout contract handoff identity is invalid")
            boundary = unit.get("boundary")
            if not isinstance(boundary, dict):
                raise ValueError("legacy fanout contract boundary is invalid")
            for field in ("file_scope", "do_not_touch"):
                values = boundary.get(field)
                if (
                    not isinstance(values, list)
                    or (field == "file_scope" and not values)
                    or not all(
                        isinstance(value, str) and value.strip()
                        for value in values
                    )
                ):
                    raise ValueError(
                        f"legacy fanout contract boundary.{field} is invalid"
                    )
            dependencies = unit.get("depends_on")
            if not isinstance(dependencies, list) or not all(
                isinstance(dependency, str) and dependency
                for dependency in dependencies
            ):
                raise ValueError("legacy fanout contract dependencies are invalid")
            if owner is None:
                continue
            snapshot = resolved_executor_capability_snapshot(
                owner,
                paths.executor_capability_snapshots_dir,
            )
            handoff["executor_capability_snapshot_policy"] = "frozen_required"
            handoff["executor_capability_snapshot"] = snapshot
    except ValueError as exc:
        raise OmhError(f"legacy fanout migration refused: {exc}") from exc
    migrated.pop("artifacts", None)
    try:
        fanout_dispatch_preflight(paths, migrated)
        recorded = write_fanout_contract(paths, migrated)
    except (OSError, ValueError) as exc:
        raise OmhError(f"could not migrate fanout contract: {exc}") from exc
    _print_json(recorded)
    return 0


def _read_fanout_payload(units_arg: str) -> tuple[list[dict[str, object]], object]:
    """The unit list, plus the spawn plan when the object form carries one.

    The plan rides in the same payload rather than behind a second flag: it
    justifies this exact split, and an operator who edits the units without
    editing the justification is the case the gate exists to catch.

    The plan is returned exactly as written, unvalidated. Coercing a malformed
    one to None here would make "you sent the wrong shape" indistinguishable
    from "you sent nothing", and the shape error is the one an operator who
    typed a string instead of an object actually needs.
    """
    raw = sys.stdin.read() if units_arg == "-" else Path(units_arg).expanduser().read_text(encoding="utf-8")
    payload = json.loads(raw)
    units = payload.get("units") if isinstance(payload, dict) else payload
    if not isinstance(units, list):
        raise OmhError("fanout units input must be a JSON list (or an object with a 'units' list)")
    if not isinstance(payload, dict):
        return units, None
    _reject_near_miss_key(payload, "spawn_plan")
    return units, payload.get("spawn_plan")


def _reject_near_miss_key(payload: dict[str, object], expected: str) -> None:
    """Refuse a key that is the expected one with different punctuation or case.

    `spawnPlan` and `spawn-plan` are both natural spellings, and `.get` drops
    either without a word — worst below the threshold, where the operator's
    justification is silently discarded and the frozen contract says nothing
    was supplied.
    """
    if expected in payload:
        return
    flattened = expected.replace("_", "")
    for key in payload:
        if str(key).replace("_", "").replace("-", "").lower() == flattened:
            raise OmhError(f"unknown key {key!r} in fanout units payload; did you mean {expected!r}?")


def cmd_coding_commit_plan(args: argparse.Namespace) -> int:
    import subprocess as _subprocess

    from ..coding.commit_planning import (
        CommitPlanError,
        build_commit_plan,
        parse_status_porcelain_z,
    )

    def _read_source(path_text: str) -> str:
        return sys.stdin.read() if path_text == "-" else Path(path_text).expanduser().read_text(encoding="utf-8")

    try:
        if args.status_file:
            status_payload = _read_source(args.status_file)
        else:
            repo_root = Path(args.repo_root).expanduser().resolve()
            if not (repo_root / ".git").exists():
                raise OmhError(f"--repo-root is not a git checkout root: {repo_root}")
            # Read-only metadata probes, same class as the worktree observation
            # ledger reads: nothing is staged, committed, or mutated.
            status = _subprocess.run(
                ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if status.returncode != 0:
                raise OmhError(f"git status failed in {repo_root}: {status.stderr.strip()}")
            status_payload = status.stdout
        files = parse_status_porcelain_z(status_payload)
        if not files:
            raise OmhError("nothing to plan: the working tree has no changed files")
        plan = build_commit_plan(files)
    except CommitPlanError as exc:
        raise OmhError(str(exc)) from exc
    except (OSError, ValueError, _subprocess.TimeoutExpired) as exc:
        raise OmhError(f"could not gather commit-plan inputs: {exc}") from exc
    _print_json(plan)
    return 0


def _add_failure_recovery_arguments(parser) -> None:
    """The failure-recovery flags shared by `fanout dispatch` and `coding run`.

    Both surfaces funnel into the same `dispatch_fanout`, so a recovery option
    that exists on one and not the other would be a difference in the CLI only.
    """
    parser.add_argument(
        "--on-failure",
        default="report",
        metavar="report|retarget:<owner>|hermes|wait",
        help=(
            "What to do with units that failed as auth_shaped or limit_shaped. 'report' (default) "
            "prints the repair card and the options and changes nothing, or runs the interactive "
            "interview when stdin is a terminal. A named mode is applied without prompting."
        ),
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Never prompt, even on a terminal; --on-failure alone decides.",
    )
    parser.add_argument(
        "--ignore-limit-signal",
        action="store_true",
        help=(
            "Spawn even when this machine observed a fresh limit-shaped or auth-shaped failure for "
            "the unit's owner, re-observing the provider's answer directly."
        ),
    )
    parser.add_argument("--hermes-model", default="", help="Hermes model alias for recovery or final-review lanes.")
    parser.add_argument("--hermes-provider", default="", help="Hermes provider alias for recovery or final-review lanes.")
    parser.add_argument("--hermes-reasoning", default="", help="Hermes reasoning alias for recovery or final-review lanes.")


def _add_coding_commands(sub) -> None:
    from .paired_run import add_coding_paired_run_command

    coding = sub.add_parser("coding", help="Prepare executor-neutral or tracked coding handoff artifacts.")
    coding_sub = coding.add_subparsers(dest="coding_command", required=True)
    add_coding_paired_run_command(coding_sub)

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
    # Default None resolves through the setup profile's `parallelism` block
    # (default_concurrency 5, global_concurrency 8 unless edited); an
    # explicit flag still wins, clamped to the global ceiling. Adaptive mode
    # reads that same resolved width as its admission ceiling.
    fanout_dispatch.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help=(
            "Pool width override; defaults to parallelism.default_concurrency, is clamped "
            "to global_concurrency, and is the ceiling in adaptive mode."
        ),
    )
    fanout_dispatch.add_argument(
        "--adaptive-concurrency",
        action="store_true",
        help=(
            "Use the --concurrency ceiling; start at 2 and grow after clean completions; "
            "provider-limit pressure halves it, including recovered retries."
        ),
    )
    fanout_dispatch.add_argument("--timeout", type=int, default=1800, help="Per-unit subprocess timeout in seconds.")
    fanout_dispatch.add_argument("--unit", action="append", default=None, help="Dispatch only these unit ids (repeatable).")
    fanout_dispatch.add_argument("--dry-run", action="store_true", help="Resolve readiness, argv, and worktree paths; spawn nothing.")
    fanout_dispatch.add_argument(
        "--run-verification",
        action="store_true",
        help="Run each unit's contract verification_commands in its worktree after its sidecar validates.",
    )
    diagnostics = fanout_dispatch.add_mutually_exclusive_group()
    diagnostics.add_argument(
        "--diagnostics",
        action="store_true",
        help="Run optional allowlisted local post-GREEN diagnostics; an injected engine may override.",
    )
    diagnostics.add_argument(
        "--no-diagnostics",
        dest="diagnostics",
        action="store_false",
        help="Disable the optional post-GREEN diagnostic hook (the default).",
    )
    fanout_dispatch.set_defaults(diagnostics=False)
    fanout_dispatch.add_argument(
        "--final-review",
        action="store_true",
        help=(
            "Run four immutable read-only Hermes review lenses after "
            "integration GREEN."
        ),
    )
    health_events = fanout_dispatch.add_mutually_exclusive_group()
    health_events.add_argument(
        "--health-events",
        dest="health_events",
        action="store_true",
        help="Emit bounded metadata-only critical-path lifecycle evidence.",
    )
    health_events.add_argument(
        "--no-health-events",
        dest="health_events",
        action="store_false",
        help="Disable critical-path lifecycle evidence emission (the default).",
    )
    fanout_dispatch.set_defaults(health_events=False)
    fanout_dispatch.add_argument(
        "--integration-worktree",
        default="",
        help="Explicit clean checkout containing the integrated producer result for full gates.",
    )
    fanout_dispatch.add_argument(
        "--integration-revision",
        default="",
        help="Exact HEAD^{tree} expected for --integration-worktree; required with it.",
    )
    fanout_dispatch.add_argument(
        "--goal-attempt-id",
        default="attempt-1",
        help="Stable identity for the current goal attempt (default: attempt-1).",
    )
    fanout_dispatch.add_argument(
        "--goal-attempt-progressed",
        action="store_true",
        help="Allow a new attempt id to reset review allowances after concrete progress.",
    )
    fanout_dispatch.add_argument(
        "--review-dispatch-budget",
        type=int,
        default=1,
        help="Maximum eligible dispatches per normalized reviewer role and goal attempt.",
    )
    fanout_dispatch.add_argument(
        "--resume-journal",
        default="",
        help=(
            "Resume from a prior run's run_journal.json: re-dispatch only units that "
            "failed with no observed side effect, un-skip their dependents, and never "
            "re-run a unit that already succeeded."
        ),
    )
    _add_failure_recovery_arguments(fanout_dispatch)
    fanout_dispatch.set_defaults(func=cmd_coding_fanout_dispatch)

    fanout_migrate = fanout_sub.add_parser(
        "migrate-legacy",
        help="Convert a recorded fanout_contract/v1 into frozen-evidence v2 before dispatch.",
    )
    fanout_migrate.add_argument("fanout_id")
    fanout_migrate.add_argument(
        "--confirm-contract-sha256",
        default="",
        help=(
            "Required only for pre-provenance v1 artifacts; confirms the exact "
            "digest printed by the preview."
        ),
    )
    fanout_migrate.set_defaults(func=cmd_coding_fanout_migrate_legacy)

    fanout_brief = fanout_sub.add_parser(
        "brief",
        help="Join the frozen contract with observed dispatch/journal metadata into one per-unit briefing.",
    )
    fanout_brief.add_argument("fanout_id", nargs="?", default=None, help="Fanout id; omit to list known fanouts.")
    fanout_brief.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    fanout_brief.set_defaults(func=cmd_coding_fanout_brief)

    fanout_status = fanout_sub.add_parser(
        "status",
        help="Project a read-only per-unit roster for one fanout from observed journal events.",
    )
    fanout_status.add_argument(
        "--fanout-id",
        required=True,
        help="Fanout id whose unit roster is projected from the observation journal.",
    )
    fanout_status.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    fanout_status.set_defaults(func=cmd_coding_fanout_status)

    fanout_reap = fanout_sub.add_parser(
        "reap",
        help=(
            "Terminate marker-named unit process groups for one fanout. Verify the dispatcher is dead "
            "first — a live dispatcher's running units are equally marker-named. Refuses any pid the "
            "markers do not name; never kills by process name."
        ),
    )
    fanout_reap.add_argument("fanout_id", help="Fanout id whose inflight markers name the candidate pids.")
    fanout_reap.add_argument(
        "--pid",
        type=int,
        action="append",
        help="Restrict to specific marker-named pids; default reaps every marker-named pid.",
    )
    fanout_reap.set_defaults(func=cmd_coding_fanout_reap)

    run_cmd = coding_sub.add_parser(
        "run",
        help=(
            "Single-invocation bridge: build a one-unit fanout contract for an explicitly "
            "chosen coding owner and dispatch it immediately (isolated worktree, never merges; "
            "running this command against a named owner is itself the opt-in)."
        ),
    )
    run_cmd.add_argument(
        "--owner",
        choices=EXECUTOR_PROFILES,
        required=True,
        help="The coding owner explicitly chosen for this run.",
    )
    run_goal = run_cmd.add_mutually_exclusive_group(required=True)
    run_goal.add_argument("--goal", nargs="+", help="Task/prompt text for this run.")
    run_goal.add_argument("--goal-file", help="File with the task/prompt text, or '-' for stdin.")
    run_cmd.add_argument("--unit-id", default="run", help="Unit id for the frozen contract (lowercase slug).")
    run_cmd.add_argument(
        "--file-scope",
        action="append",
        default=None,
        help="Boundary path(s) this run may touch (repeatable); defaults to the whole repo ('.').",
    )
    run_cmd.add_argument("--source", choices=CHAT_SOURCES, default="generic")
    run_cmd.add_argument("--repo-root", default=".", help="Repository the unit worktree branches from.")
    run_cmd.add_argument("--base-ref", default="HEAD", help="Ref resolved once to a SHA the unit branch starts from.")
    run_cmd.add_argument("--timeout", type=int, default=1800, help="Subprocess timeout in seconds.")
    run_cmd.add_argument("--dry-run", action="store_true", help="Resolve readiness, argv, and worktree paths; spawn nothing.")
    run_cmd.add_argument(
        "--run-verification",
        action="store_true",
        help="Run the unit's contract verification_commands in its worktree after the process exits 0.",
    )
    run_cmd.add_argument(
        "--model",
        default=None,
        help=(
            "Explicit model id for this run; always passes through unvalidated. Precedence: this flag "
            "beats a routed handoff model, which beats the dispatch-models.json preference, which beats "
            "the executor CLI's own default."
        ),
    )
    run_cmd.add_argument("--effort", default=None, help="Reasoning effort for profiles that support one.")
    run_cmd.add_argument(
        "--category",
        default=None,
        help=(
            "OMO/ULW model category for this run (ultrabrain, deep, architect, quick, writing, "
            "visual-engineering, artistry, unspecified-high, unspecified-low); resolved through the "
            "category-maestro table when one is configured. --model still wins."
        ),
    )
    _add_failure_recovery_arguments(run_cmd)
    run_cmd.set_defaults(func=cmd_coding_run)

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
        "--category",
        default=None,
        help=(
            "OMO/ULW model category, orthogonal to role: visual-engineering, ultrabrain, deep, "
            "architect, artistry, quick, unspecified-low, unspecified-high, or writing; ulw-* aliases accepted."
        ),
    )
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
    model_route.add_argument(
        "--recommendations",
        default=None,
        help="Optional model_recommendation_overrides/v2 JSON file for editable routing order.",
    )
    model_route.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    model_route.set_defaults(func=cmd_coding_model_route)

    category_maestro = coding_sub.add_parser(
        "category-maestro",
        help=(
            "Operator category->model chains for the Maestro dispatch lane "
            "(the same category mixture the Hermes-native delegation lane routes by)."
        ),
    )
    category_maestro_sub = category_maestro.add_subparsers(dest="category_maestro_command", required=True)
    category_maestro_show = category_maestro_sub.add_parser(
        "show",
        help="Render the effective category table per dispatchable profile, operator overrides marked.",
    )
    category_maestro_show.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    category_maestro_show.set_defaults(func=cmd_coding_category_maestro)
    category_maestro_set = category_maestro_sub.add_parser(
        "set",
        help="Override one category's model chain for one profile (written to ~/.omh/routing/category-maestro.json).",
    )
    category_maestro_set.add_argument("profile", help="Dispatchable profile: codex or claude-code.")
    category_maestro_set.add_argument(
        "category",
        help="Model category (ultrabrain, deep, architect, quick, writing, visual-engineering, artistry, unspecified-high, unspecified-low).",
    )
    category_maestro_set.add_argument(
        "chain",
        nargs="+",
        help=(
            "Chain entries in order, each `model[:effort]`, e.g. gpt-5.6-sol:xhigh. The tail after the "
            "last colon is taken as the effort only when it is a known level (off, minimal, low, medium, "
            "high, xhigh, max, auto); other colon tags stay part of the model id."
        ),
    )
    category_maestro_set.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    category_maestro_set.set_defaults(func=cmd_coding_category_maestro)
    category_maestro_clear = category_maestro_sub.add_parser(
        "clear",
        help="Remove one category override so the built-in chain applies again.",
    )
    category_maestro_clear.add_argument("profile", help="Dispatchable profile: codex or claude-code.")
    category_maestro_clear.add_argument("category", help="Model category to clear.")
    category_maestro_clear.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    category_maestro_clear.set_defaults(func=cmd_coding_category_maestro)
    category_maestro_interview_cmd = category_maestro_sub.add_parser(
        "interview",
        help="Walk each profile's categories with numbered choices on a terminal (Enter keeps the current chain).",
    )
    category_maestro_interview_cmd.set_defaults(func=cmd_coding_category_maestro)

    model_routing = coding_sub.add_parser(
        "model-routing",
        help="Inspect local model routing readiness or reset owner-learning metadata.",
    )
    model_routing_sub = model_routing.add_subparsers(dest="model_routing_command", required=True)
    model_routing_status = model_routing_sub.add_parser(
        "status",
        help="Explain discovered/confirmed models, Hermes aliases, Maestro recommendations, and owner learning.",
    )
    model_routing_status.add_argument(
        "--discovery-home",
        default=None,
        help="Local home whose allowlisted coding-agent metadata roots are scanned (default: Hermes home's parent).",
    )
    model_routing_status.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    model_routing_status.set_defaults(func=cmd_coding_model_routing_status)
    model_routing_reset = model_routing_sub.add_parser(
        "reset",
        help="Reset one learned coding-owner preference; no model/provider configuration is changed.",
    )
    model_routing_reset.add_argument("--route-family", required=True, help="Opaque route-family id to reset.")
    model_routing_reset.add_argument("--reason", default="operator_reset", help="Opaque metadata reason for the reset.")
    model_routing_reset.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    model_routing_reset.set_defaults(func=cmd_coding_model_routing_reset)

    model_inventory = coding_sub.add_parser(
        "model-inventory",
        help="Report which coding models are locally activated (metadata-only, reporting-only).",
    )
    model_inventory.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    model_inventory.set_defaults(func=cmd_coding_model_inventory)

    model_contract_audit = coding_sub.add_parser(
        "model-contract-audit",
        help=(
            "Compare a bounded local JSON model inventory with shipped contracts; "
            "network-free and reporting-only."
        ),
    )
    model_contract_audit.add_argument(
        "--inventory",
        required=True,
        help="Local JSON inventory path, or - for stdin (maximum 1048576 bytes).",
    )
    model_contract_audit.add_argument(
        "--required-model",
        action="append",
        default=[],
        help="Model id whose missing contract blocks the audit; repeatable.",
    )
    model_contract_audit.add_argument(
        "--recommended-model",
        action="append",
        default=[],
        help="Model id whose missing contract is advisory; repeatable.",
    )
    model_contract_audit.add_argument(
        "--intentional-exclusion",
        action="append",
        default=[],
        help="Model id intentionally outside OMH contract coverage; repeatable.",
    )
    model_contract_audit.add_argument(
        "--json",
        action="store_true",
        help="Emit the stable model_contract_coverage/v1 payload.",
    )
    model_contract_audit.set_defaults(func=cmd_coding_model_contract_audit)

    complexity = coding_sub.add_parser(
        "complexity",
        help="Score a request's complexity and show the advisory model-class recommendation.",
    )
    complexity.add_argument("message", nargs="*", help="Request text to score.")
    complexity.add_argument("--stdin", action="store_true", help="Read the request text from standard input.")
    complexity.add_argument("--skill", default=None, help="Routed workflow name, so its capability family can weigh in.")
    complexity.add_argument(
        "--model",
        default=None,
        help="Explicit model id; supersedes the recommendation, which is still printed for disclosure.",
    )
    complexity.add_argument(
        "--effort",
        default=None,
        help="Explicit reasoning effort; supersedes the recommended effort.",
    )
    complexity.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    complexity.set_defaults(func=cmd_coding_complexity)

    composition_guide = coding_sub.add_parser(
        "composition-guide",
        help="Composition calibration for the MAIN agent's own model family (how to compose splits and unit prompts).",
    )
    composition_guide.add_argument(
        "--model",
        default=None,
        help="The main agent's own model id (for example claude-fable-5-1, gpt-5.6-sol, kimi-k3); omit to list all families.",
    )
    composition_guide.add_argument(
        "--executor",
        default=None,
        help="Executor profile the composer prepares for; selects the per-turn or mid-conversation effort policy for models with a documented contract.",
    )
    composition_guide.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    composition_guide.set_defaults(func=cmd_coding_composition_guide)

    model_contract = coding_sub.add_parser(
        "model-contract",
        help="Print a vendor-documented exact contract or bounded declared projection (efforts, limits, tools, pricing, sources); metadata only.",
    )
    model_contract.add_argument(
        "--model",
        required=True,
        help="Exact or explicitly declared model id, provider prefix welcome (for example gpt-6-astra, openai/gpt-6-astra-pro-fast).",
    )
    model_contract.add_argument(
        "--executor",
        default=None,
        help="Executor profile to resolve the effort policy against; omit for the per-turn policy.",
    )
    model_contract.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    model_contract.set_defaults(func=cmd_coding_model_contract)

    add_hermes_child_command(coding_sub)
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
    delegate.add_argument(
        "--explicit-owner-choice",
        action="store_true",
        help=(
            "The coding owner was named explicitly for THIS run (an operator/agent choice, "
            "never a caller default) -- bypasses the retained-workflow genre veto for a "
            "non-coding-shaped brief when combined with --executor; a bare --executor alone "
            "never does."
        ),
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
    # These two annotate the prepared handoff's advisory complexity
    # recommendation and nothing else: they record that the caller already
    # chose, so the recommendation is reported as superseded rather than
    # silently dropped. They do not route -- `omh coding run --model/--effort`
    # is the flag pair that reaches a dispatch argv.
    delegate.add_argument(
        "--model",
        default=None,
        help="Model already chosen for this request; supersedes the prepared complexity recommendation.",
    )
    delegate.add_argument(
        "--effort",
        default=None,
        help="Reasoning effort already chosen for this request; supersedes the recommended effort.",
    )
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

    commit_plan = coding_sub.add_parser(
        "commit-plan",
        help="Prepare a deterministic commit-split plan from observed working-tree metadata (read-only; never commits).",
    )
    commit_plan.add_argument("--repo-root", default=".", help="Git checkout root to read status metadata from.")
    commit_plan.add_argument(
        "--status-file",
        default="",
        help="Pre-captured `git status --porcelain=v1 -z` output ('-' for stdin) instead of probing --repo-root.",
    )
    commit_plan.set_defaults(func=cmd_coding_commit_plan)

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
    lifecycle_result.add_argument("--result", choices=OBSERVED_RESULTS, required=True)
    lifecycle_result.add_argument("--participants", default="codex")
    lifecycle_result.add_argument("--evidence-ref", action="append")
    lifecycle_result.set_defaults(func=cmd_coding_lifecycle_result)

    lifecycle_verify = lifecycle_sub.add_parser("verify")
    lifecycle_verify.add_argument("--run", dest="run_id", required=True)
    lifecycle_verify.add_argument("--completion-status", choices=tuple(v for v in WRAPPER_COMPLETION_STATUSES if v != "started"), default="completed")
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

    executor_skills = coding_sub.add_parser(
        "executor-skills",
        help=(
            "Report locally discovered skills for one coding-agent profile (read-only, metadata-only; "
            "declared, not observed)."
        ),
    )
    executor_skills.add_argument(
        "--profile",
        choices=EXECUTOR_PROFILES,
        required=True,
        help="Coding-agent profile to probe. Hermes-native selection is rejected; maestro never routes it here.",
    )
    executor_skills.add_argument(
        "--project-root", default="", help="Optional project root to also probe project-local Claude Code skills."
    )
    executor_skills.add_argument(
        "--unit-role",
        default="",
        help="Optional unit role; also returns a suggested skill sequence and, when a real choice exists, a selection card.",
    )
    executor_skills.add_argument("--json", action="store_true", help="Emit the machine payload (the default output).")
    executor_skills.set_defaults(func=cmd_coding_executor_skills)


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
