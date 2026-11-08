"""Hour 24 is refused at every timestamp site on every supported Python.

CPython 3.14 reads ``T24:00:00`` as the next day's midnight; 3.11 to 3.13
raise. #2261 found a toolkit script that relied on the refusal; the audit after
it routed every site whose text can arrive from outside OMH's own clock through
``omh.plugin_bundle.omh.iso_datetime.strict_fromisoformat``.

Three layers:

* the helper itself, on the real interpreter and under the 3.14 reading;
* one case per routed site (``SITES``), run under both readings by
  ``_hour_24.assert_hour_24_refused`` so CI's 3.11/3.13 lanes reach the 3.14
  path, with a control proving each site's result depends on the refusal;
* a gate that re-derives every ``fromisoformat`` reference in ``src/`` from
  source, calls and bare references (``parse = datetime.fromisoformat``) alike.
  A reference is either a guard definition, a guarded call with its case here,
  a ``date.fromisoformat`` (unchanged in 3.14), or a count pinned in
  ``UNGUARDED`` with its reason. A new raw reference fails until it takes one.

The guard itself has three hand-kept copies (``GUARD_COPIES``). Each is run on
the 3.14 reading against the bundle helper, and their ASTs must stay equal.
"""

from __future__ import annotations

import ast
import importlib
import json
import runpy
import unittest
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest import mock

from _hour_24 import HOUR_24, Lenient, Strict, assert_hour_24_refused
from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh import memory_governance as governance  # noqa: E402
from omh.plugin_bundle.omh.iso_datetime import strict_fromisoformat  # noqa: E402
from _memory_governance_fixtures import _approved_artifact, _evaluate, _iso  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
RECONCILE = SOURCE / "skills/biomedical_evidence_toolkit/scripts/reconcile.py"
SEARCH_EVIDENCE = SOURCE / "workflows/search_evidence.py"
# The three hand-kept copies of the guard, the bundle helper first. They must stay
# one function: `test_the_guard_copies_are_one_function` compares their ASTs.
GUARD_COPIES = (SOURCE / "plugin_bundle/omh/iso_datetime.py", RECONCILE, SEARCH_EVIDENCE)
_SPELLINGS_NAMES = {"_date_spellings": "date_spellings", "date_spellings": "date_spellings"}
UTC = timezone.utc
NOON = datetime(2020, 1, 1, 12, tzinfo=UTC)
NEXT_MIDNIGHT = datetime(2020, 1, 2, tzinfo=UTC)

# The definitions of the guard, one per loading boundary: the bundle module the
# `omh` package also imports, the standalone toolkit script, and
# search_evidence.py, which tests/test_search_evidence.py loads by file path
# with only the stdlib. Each holds exactly one raw call.
GUARD_DEFINITIONS = {
    ("src/plugin_bundle/omh/iso_datetime.py", "strict_fromisoformat"): 1,
    ("src/skills/biomedical_evidence_toolkit/scripts/reconcile.py", "strict_fromisoformat"): 1,
    ("src/workflows/search_evidence.py", "strict_fromisoformat"): 1,
}

# Raw `datetime.fromisoformat` references the audit left in place: how many
# each function holds, and why its text can never carry hour 24.
UNGUARDED: dict[tuple[str, str], tuple[int, str]] = {
    ("src/coding/hermes_child_receipts.py", "load_hermes_child_receipt"):
        (1, "re-reads observed_at only after validate_routing_observation (guarded) accepted it"),
    ("src/install/self_update_state.py", "_held_by_gateways"):
        (1, "activated_at is written by _record_activation from now() or the activation marker's marker_written_at, itself now()"),
    ("src/maintenance/doctor.py", "_awareness_delivery_check"):
        (1, "first_attempted_at comes from record_awareness_delivery, whose one caller (hooks/llm_hooks.py) passes a strftime clock stamp"),
    ("src/maintenance/update_check_recovery.py", "evaluate_update_check"):
        (1, "parses now.isoformat() built two lines above"),
    ("src/maintenance/update_check_state.py", "interval_elapsed"):
        (1, "last_checked_at is only written by update_check_recovery, from now_iso"),
    ("src/plugin_bundle/omh/completion_store.py", "_checkpoint"):
        (1, "todo updated_at is stamped by todo_store on every write, never taken from input"),
    ("src/plugin_bundle/omh/egress_attempt_receipts.py", "AttemptStore._validate_row"):
        (1, "re-validates rows the store wrote itself with _utc_now()"),
    ("src/plugin_bundle/omh/memory_session_lens.py", "_published_before"):
        (1, "published_at is stamped by memory_provider's _utc_now()"),
    ("src/plugin_bundle/omh/native_todo.py", "_held_by_omh_todo"):
        (1, "todo updated_at is stamped by todo_store on every write, never taken from input"),
    ("src/plugin_bundle/omh/work_resume.py", "_timestamp"):
        (1, "reads only todo updated_at, stamped by todo_store on every write"),
    ("src/skills/ai_job_search_toolkit/scripts/job_state.py", "timestamp"):
        (1, "guarded in place by the exact round trip #2261 added"),
    ("src/workflows/lifecycle_growth_configuration_identity.py", "observation_order"):
        (1, "only given observations built by parse_observation, whose observed_at passed lifecycle_growth_configuration_values.timestamp (guarded)"),
    ("src/workflows/memory.py", "last_prefetch_status"):
        (1, "served_at is formatted by memory_prefetch_receipt._stamp from a datetime, never copied from text"),
    ("src/workflows/memory_project_identity.py", "migrate_project_identity"):
        (1, "created_at is now.isoformat() from the same call, or the receipt that call wrote"),
    ("src/workflows/memory_project_identity.py", "rollback_project_identity_migration"):
        (1, "created_at is read back from the receipt migrate_project_identity wrote"),
    ("src/workflows/memory_sync_fidelity_receipts.py", "SyncReceipt.clock"):
        (1, "SyncReceipt is only built after observed_at passed memory_sync_fidelity_validation.observed_at (guarded)"),
    ("src/workflows/web_qa_observation.py", "_parse"):
        (1, "only ever given the canonical output of _utc (guarded)"),
    ("src/workflows/web_qa_observation_plan.py", "_subject"):
        (2, "parses the canonical output of _utc_timestamp (guarded)"),
}


def _explicit_identity(module: Any, stamp: str) -> str:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "project-identity.json"
        path.write_text(json.dumps({
            "schema_version": module.EXPLICIT_SCHEMA_VERSION, "identity": "prj:" + "0" * 64,
            "created_at": stamp, "resolver_version": module.RESOLVER_VERSION,
        }), encoding="utf-8")
        return module._explicit(path)


def _clarification_record(stamp: str, field: str) -> dict[str, object]:
    record: dict[str, object] = {
        "schema_version": "fanout_clarification_request/v1", "fanout_id": "fanout-1", "unit_id": "unit-a",
        "run_ref": "run-1", "base_sha": "0" * 40, "contract_digest": "sha256:" + "0" * 64,
        "goal_attempt_id": "goal-1", "worktree_path": "unit-a", "attempt_id": "attempt-1",
        "input_required": {
            "decision_id": "pick-format", "question": "Which format?", "blocking_reason": "two formats fit",
            "answer_shape": {"kind": "options", "options": ["json", "yaml"]},
            "affected_unit_ids": ["unit-a"], "redacted_context": [],
        },
        "workspace": {}, "decision_id": "pick-format", "round": 1, "answer": None,
        "request_event_ref": "", "answer_event_ref": None, "redispatch_event_ref": None,
        "requested_at": "2020-01-01T00:00:00+00:00", "expires_at": "2020-01-02T00:00:00+00:00",
        "state": "prepared_not_answered", "privacy": "bounded_decision_metadata", "history": [],
    }
    record[field] = stamp
    return record


def _with_errors(call: Callable[[str, str, list[str]], object]) -> Callable[[str], object]:
    def run(stamp: str) -> object:
        errors: list[str] = []
        return call(stamp, "/stamp", errors), errors
    return run


def _capacity_input(stamp: str) -> str:
    field = {"value": None, "class": "unknown", "source": "unknown", "observed_at": stamp}
    return json.dumps({"schema_version": "route_capacity_input/v1", "context_window_tokens": field})


def _expiring_artifact(stamp: str) -> dict[str, object]:
    artifact, review = _approved_artifact()
    artifact["retention"] = {**artifact["retention"], "expires_at": stamp}  # type: ignore[dict-item]
    return _evaluate(artifact, review, now=NOON + timedelta(days=1))


def _open_ceiling(stamp: str) -> dict[str, object]:
    artifact, review = _approved_artifact()
    artifact["staleness"] = {"resolution": "open", "open_expires_at": stamp}
    return _evaluate(artifact, review, now=NOON + timedelta(days=1))


def _revalidation_deadline(stamp: str) -> dict[str, object]:
    artifact, review = _approved_artifact(revalidation={"deadline": stamp})
    return _evaluate(artifact, review, now=NOON + timedelta(days=1))


def _stale_override(module: Any, *, deadline: str, expires: str) -> dict[str, object]:
    artifact, _review = _approved_artifact()
    override = {
        "artifact_identity": governance.stable_artifact_identity(artifact), "run_id": "run-1",
        "confirmed_at": _iso(NOON), "revalidation_deadline": deadline, "expires_at": expires,
    }
    return module.validate_stale_override(override, artifact, NEXT_MIDNIGHT, NOON, "run-1")


# (src path, enclosing function) -> (module, one case per guarded call in it).
# Each case maps a stamp to the site's observable result.
Case = Callable[[Any], Callable[[str], object]]
SITES: dict[tuple[str, str], tuple[str, list[Case]]] = {
    ("src/coding/action_gate.py", "_stamp_age_seconds._parse"): (
        "omh.coding.action_gate", [lambda m: lambda s: m._stamp_age_seconds(s, "2020-01-03T00:00:00Z")]),
    ("src/tui/bot_board.py", "_record_time"): ("omh.tui.bot_board", [lambda m: m._record_time]),
    ("src/maintenance/hermes_gateway.py", "_iso_epoch"): ("omh.maintenance.hermes_gateway", [lambda m: m._iso_epoch]),
    ("src/coding/executor_auth_signals.py", "_age_seconds"): (
        "omh.coding.executor_auth_signals", [lambda m: m._age_seconds]),
    ("src/coding/executor_capability_snapshots.py", "_is_timestamp"): (
        "omh.coding.executor_capability_snapshots", [lambda m: m._is_timestamp]),
    ("src/coding/executor_local_workflow_selection.py", "_parsed_timestamp"): (
        "omh.coding.executor_local_workflow_selection", [lambda m: m._parsed_timestamp]),
    ("src/coding/executor_progress.py", "_parse_time"): (
        "omh.coding.executor_progress", [lambda m: m._parse_time]),
    ("src/coding/fanout_clarification.py", "clarification_state"): (
        "omh.coding.fanout_clarification",
        [lambda m: lambda s: m.clarification_state({"state": "prepared_not_answered", "expires_at": s}, NOON)]),
    ("src/coding/fanout_clarification_records.py", "parse_clarification_record"): (
        "omh.coding.fanout_clarification_records",
        [lambda m: lambda s: m.parse_clarification_record(_clarification_record(s, "requested_at"))]),
    ("src/coding/fanout_status.py", "_parse_timestamp"): (
        "omh.coding.fanout_status", [lambda m: m._parse_timestamp]),
    ("src/coding/pre_handoff_readiness.py", "_stamp_age_seconds._parse"): (
        "omh.coding.pre_handoff_readiness",
        [lambda m: lambda s: m._stamp_age_seconds(s, "2020-01-03T00:00:00Z", 10**6)]),
    ("src/coding/routing_observation.py", "validate_routing_observation"): (
        "omh.coding.routing_observation", [lambda m: lambda s: m.validate_routing_observation({"observed_at": s})]),
    ("src/coding/skill_load_protocol.py", "parse_time"): (
        "omh.coding.skill_load_protocol", [lambda m: m.parse_time]),
    ("src/coding/status_board.py", "_parse_timestamp"): (
        "omh.coding.status_board", [lambda m: m._parse_timestamp]),
    ("src/plugin_bundle/omh/_governance_evaluation.py", "evaluate_memory_replay"): (
        "omh.plugin_bundle.omh._governance_evaluation",
        [lambda m: _expiring_artifact, lambda m: _open_ceiling, lambda m: _revalidation_deadline]),
    ("src/plugin_bundle/omh/_governance_overrides.py", "validate_stale_override"): (
        "omh.plugin_bundle.omh._governance_overrides",
        [lambda m: lambda s: _stale_override(m, deadline=s, expires=_iso(NOON + timedelta(hours=1))),
         lambda m: lambda s: _stale_override(m, deadline=_iso(NEXT_MIDNIGHT), expires=s)]),
    ("src/plugin_bundle/omh/activity_observer_events.py", "parse_stamp"): (
        "omh.plugin_bundle.omh.activity_observer_events", [lambda m: m.parse_stamp]),
    ("src/plugin_bundle/omh/context_budget_plan_capacity.py", "parse_route_capacity_input"): (
        "omh.plugin_bundle.omh.context_budget_plan_capacity",
        [lambda m: lambda s: m.parse_route_capacity_input(_capacity_input(s))]),
    ("src/plugin_bundle/omh/dag_run.py", "_park_deadline"): (
        "omh.plugin_bundle.omh.dag_run", [lambda m: lambda s: m._park_deadline(s, NOON.timestamp())]),
    ("src/plugin_bundle/omh/dispatch_outcomes.py", "_parse_timestamp"): (
        "omh.plugin_bundle.omh.dispatch_outcomes", [lambda m: m._parse_timestamp]),
    ("src/plugin_bundle/omh/hermes_memory.py", "_parse_expires_at"): (
        "omh.plugin_bundle.omh.hermes_memory", [lambda m: m._parse_expires_at]),
    ("src/plugin_bundle/omh/memory_blocks.py", "_timestamp"): (
        "omh.plugin_bundle.omh.memory_blocks", [lambda m: m._timestamp]),
    ("src/plugin_bundle/omh/memory_governance.py", "_parse_deadline"): (
        "omh.plugin_bundle.omh.memory_governance", [lambda m: m._parse_deadline]),
    ("src/plugin_bundle/omh/memory_recall_support.py", "_parse_utc"): (
        "omh.plugin_bundle.omh.memory_recall_support", [lambda m: m._parse_utc]),
    ("src/plugin_bundle/omh/memory_recall_support.py", "_parse_utc_naive_as_utc"): (
        "omh.plugin_bundle.omh.memory_recall_support", [lambda m: m._parse_utc_naive_as_utc]),
    ("src/plugin_bundle/omh/memory_session_digest.py", "stamp_epoch"): (
        "omh.plugin_bundle.omh.memory_session_digest", [lambda m: m.stamp_epoch]),
    ("src/plugin_bundle/omh/owner_preference_record.py", "valid_timestamp"): (
        "omh.plugin_bundle.omh.owner_preference_record", [lambda m: m.valid_timestamp]),
    ("src/plugin_bundle/omh/project_identity.py", "_explicit"): (
        "omh.plugin_bundle.omh.project_identity", [lambda m: lambda s: _explicit_identity(m, s)]),
    ("src/plugin_bundle/omh/runtime_reader.py", "_epoch_seconds"): (
        "omh.plugin_bundle.omh.runtime_reader", [lambda m: m._epoch_seconds]),
    ("src/plugin_bundle/omh/search_state.py", "_clock"): (
        "omh.plugin_bundle.omh.search_state", [lambda m: m._clock]),
    ("src/plugin_bundle/omh/todo_store.py", "_stamp_epoch"): (
        "omh.plugin_bundle.omh.todo_store", [lambda m: m._stamp_epoch]),
    ("src/plugin_bundle/omh/todo_store.py", "_validated_stamp"): (
        "omh.plugin_bundle.omh.todo_store", [lambda m: lambda s: m._validated_stamp(s, "done", "done_at")]),
    ("src/quality/agent_debug_incident.py", "_epoch"): (
        "omh.quality.agent_debug_incident", [lambda m: m._epoch]),
    ("src/quality/capability_gap_scout.py", "_parse_timestamp"): (
        "omh.quality.capability_gap_scout", [lambda m: m._parse_timestamp]),
    ("src/quality/evidence_records.py", "_parse_timestamp"): (
        "omh.quality.evidence_records", [lambda m: m._parse_timestamp]),
    ("src/quality/paired_run_values.py", "is_utc_z"): (
        "omh.quality.paired_run_values", [lambda m: m.is_utc_z]),
    ("src/quality/specialist_work.py", "_parse_timestamp"): (
        "omh.quality.specialist_work", [lambda m: m._parse_timestamp]),
    ("src/runtime/critical_path_health_source_parsing.py", "timestamp_ms"): (
        "omh.runtime.critical_path_health_source_parsing", [lambda m: m.timestamp_ms]),
    ("src/runtime/generated_artifacts.py", "_parse_stamp"): (
        "omh.runtime.generated_artifacts", [lambda m: m._parse_stamp]),
    ("src/surfaces/hermes_processes.py", "_coerce_datetime"): (
        "omh.surfaces.hermes_processes", [lambda m: m._coerce_datetime]),
    ("src/surfaces/menubar_status.py", "_parse_datetime"): (
        "omh.surfaces.menubar_status", [lambda m: m._parse_datetime]),
    ("src/tui/panels.py", "_epoch"): ("omh.tui.panels", [lambda m: m._epoch]),
    ("src/workflows/_memory_lifecycle_scan.py", "parse_time"): (
        "omh.workflows._memory_lifecycle_scan", [lambda m: m.parse_time]),
    ("src/workflows/_memory_migration_reactivation_data.py", "_time"): (
        "omh.workflows._memory_migration_reactivation_data", [lambda m: m._time]),
    ("src/workflows/_memory_store_validation.py", "parse_time"): (
        "omh.workflows._memory_store_validation", [lambda m: m.parse_time]),
    ("src/workflows/approval_receipts.py", "_parse_stamp"): (
        "omh.workflows.approval_receipts", [lambda m: m._parse_stamp]),
    ("src/workflows/decision_gate_receipts.py", "_timestamp"): (
        "omh.workflows.decision_gate_receipts", [lambda m: m._timestamp]),
    ("src/workflows/decision_gates.py", "_connector_receipt_errors"): (
        "omh.workflows.decision_gates", [lambda m: lambda s: m._connector_receipt_errors({"observed_at": s})]),
    ("src/workflows/decision_gates.py", "_connector_transaction_errors"): (
        "omh.workflows.decision_gates", [lambda m: lambda s: m._connector_transaction_errors({"decided_at": s})]),
    ("src/workflows/external_action_readiness.py", "_parse_stamp"): (
        "omh.workflows.external_action_readiness", [lambda m: m._parse_stamp]),
    ("src/workflows/goal_journey.py", "_parse_time"): ("omh.workflows.goal_journey", [lambda m: m._parse_time]),
    ("src/workflows/hermes_ops.py", "_stamp"): ("omh.workflows.hermes_ops", [lambda m: m._stamp]),
    ("src/workflows/lifecycle_growth_analysis.py", "_observed_time"): (
        "omh.workflows.lifecycle_growth_analysis", [lambda m: m._observed_time]),
    ("src/workflows/lifecycle_growth_configuration_values.py", "timestamp"): (
        "omh.workflows.lifecycle_growth_configuration_values", [lambda m: m.timestamp]),
    ("src/workflows/loop_executor_observations.py", "observed_time"): (
        "omh.workflows.loop_executor_observations", [lambda m: m.observed_time]),
    ("src/workflows/loop_validation_primitives.py", "is_utc_rfc3339"): (
        "omh.workflows.loop_validation_primitives", [lambda m: m.is_utc_rfc3339]),
    ("src/workflows/materials.py", "_stamp"): ("omh.workflows.materials", [lambda m: m._stamp]),
    ("src/workflows/memory_batches.py", "_parse_time"): ("omh.workflows.memory_batches", [lambda m: m._parse_time]),
    ("src/workflows/memory_sync_fidelity_validation.py", "observed_at"): (
        "omh.workflows.memory_sync_fidelity_validation", [lambda m: m.observed_at]),
    ("src/workflows/operations.py", "_stamp"): ("omh.workflows.operations", [lambda m: m._stamp]),
    ("src/workflows/paper_learning.py", "_stamp"): ("omh.workflows.paper_learning", [lambda m: m._stamp]),
    ("src/workflows/plugin_catalog_snapshots.py", "_parse_stamp"): (
        "omh.workflows.plugin_catalog_snapshots", [lambda m: m._parse_stamp]),
    ("src/workflows/product_discovery_artifacts.py", "_stamp"): (
        "omh.workflows.product_discovery_artifacts", [lambda m: lambda s: m._stamp(s, "observed_at")]),
    ("src/workflows/product_discovery_validation.py", "_time"): (
        "omh.workflows.product_discovery_validation", [lambda m: m._time]),
    ("src/workflows/production_readiness_structural.py", "_timestamp"): (
        "omh.workflows.production_readiness_structural", [lambda m: m._timestamp]),
    ("src/workflows/provider_profile_posture.py", "_host_observations"): (
        "omh.workflows.provider_profile_posture",
        [lambda m: lambda s: m._host_observations([{"kind": "host-kind", "reference": "host-ref", "observed_at": s}])]),
    ("src/workflows/realtime_voice_trial_receipts.py", "_parse_stamp"): (
        "omh.workflows.realtime_voice_trial_receipts", [lambda m: m._parse_stamp]),
    ("src/workflows/recurring_intents.py", "_stamp"): ("omh.workflows.recurring_intents", [lambda m: m._stamp]),
    ("src/workflows/rejected_decision_evidence.py", "_timestamp"): (
        "omh.workflows.rejected_decision_evidence", [lambda m: m._timestamp]),
    ("src/workflows/research_department.py", "_stamp"): ("omh.workflows.research_department", [lambda m: m._stamp]),
    ("src/workflows/research_source_recovery.py", "_is_iso_timestamp"): (
        "omh.workflows.research_source_recovery", [lambda m: m._is_iso_timestamp]),
    ("src/workflows/sales_pipeline_gates.py", "parse_timestamp"): (
        "omh.workflows.sales_pipeline_gates", [lambda m: m.parse_timestamp]),
    ("src/workflows/search_amplification.py", "_stamp"): (
        "omh.workflows.search_amplification", [lambda m: _with_errors(m._stamp)]),
    ("src/workflows/search_evidence.py", "_timestamp"): (
        "omh.workflows.search_evidence", [lambda m: _with_errors(m._timestamp)]),
    ("src/workflows/session_activity_receipts.py", "parse_utc_stamp"): (
        "omh.workflows.session_activity_receipts", [lambda m: m.parse_utc_stamp]),
    ("src/workflows/temporal_source_receipts.py", "_parse_stamp"): (
        "omh.workflows.temporal_source_receipts", [lambda m: m._parse_stamp]),
    ("src/workflows/visual_summary.py", "_stamp"): ("omh.workflows.visual_summary", [lambda m: m._stamp]),
    ("src/workflows/web_qa_comparison.py", "_time"): ("omh.workflows.web_qa_comparison", [lambda m: m._time]),
    ("src/workflows/web_qa_motion_capture_store.py", "_utc"): (
        "omh.workflows.web_qa_motion_capture_store", [lambda m: lambda s: m._utc(s, "captured_at")]),
    ("src/workflows/web_qa_observation.py", "_utc"): (
        "omh.workflows.web_qa_observation", [lambda m: lambda s: m._utc(s, "captured_at")]),
    ("src/workflows/web_qa_observation_plan.py", "_utc_timestamp"): (
        "omh.workflows.web_qa_observation_plan", [lambda m: lambda s: m._utc_timestamp(s, "starts_at")]),
    ("src/workflows/workspace_bindings.py", "_parse_stamp"): (
        "omh.workflows.workspace_bindings", [lambda m: m._parse_stamp]),
}


def fromisoformat_references() -> tuple[Counter[tuple[str, str]], Counter[tuple[str, str]]]:
    """Guarded calls, and raw ``<receiver>.fromisoformat`` references other than ``date.``, per function.

    A raw reference counts whether it is called or not: ``map(datetime.fromisoformat, ...)``
    and ``parse = datetime.fromisoformat`` reach the same unguarded parser.
    """
    guarded: Counter[tuple[str, str]] = Counter()
    raw: Counter[tuple[str, str]] = Counter()

    def visit(node: ast.AST, scope: list[str], path: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(child, [*scope, child.name], path)
                continue
            key = (path, ".".join(scope))
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "strict_fromisoformat":
                guarded[key] += 1
            if (isinstance(child, ast.Attribute) and child.attr == "fromisoformat"
                    and not (isinstance(child.value, ast.Name) and child.value.id == "date")):
                raw[key] += 1
            visit(child, scope, path)

    for source in sorted(SOURCE.rglob("*.py")):
        path = source.relative_to(ROOT).as_posix()
        visit(ast.parse(source.read_text(encoding="utf-8")), [], path)
    return guarded, raw


class _GuardShape(ast.NodeTransformer):
    """A guard copy as code: no docstring, no annotation, one name for the spellings helper."""

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        self.generic_visit(node)
        node.name = _SPELLINGS_NAMES.get(node.name, node.name)
        node.returns = None
        first = node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            node.body = node.body[1:]
        return node

    def visit_arg(self, node: ast.arg) -> ast.arg:
        node.annotation = None
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST | None:
        if node.value is None:
            return None
        return ast.Assign(targets=[node.target], value=self.visit(node.value))

    def visit_Name(self, node: ast.Name) -> ast.Name:
        node.id = _SPELLINGS_NAMES.get(node.id, node.id)
        return node


def guard_body(source: str) -> str:
    """The normalized AST of a module's ``strict_fromisoformat`` and its spellings helper."""
    functions = sorted(
        (node for node in ast.parse(source).body
         if isinstance(node, ast.FunctionDef) and node.name in {"strict_fromisoformat", *_SPELLINGS_NAMES}),
        key=lambda node: _SPELLINGS_NAMES.get(node.name, node.name),
    )
    names = [_SPELLINGS_NAMES.get(node.name, node.name) for node in functions]
    if names != ["date_spellings", "strict_fromisoformat"]:
        raise AssertionError(f"expected one strict_fromisoformat and one date_spellings, found {names}")
    return ast.dump(ast.Module(body=[_GuardShape().visit(node) for node in functions], type_ignores=[]))


class HelperTests(unittest.TestCase):
    def test_hour_24_is_refused_in_every_spelling_on_this_interpreter(self) -> None:
        for text in ("2026-10-24T24:00:00", "2026-10-24T24:00:00Z", "2026-10-24T24:00:00+09:00",
                     "2026-10-24 24:00", "2026-10-24T24", "20261024T240000", "2026-12-31T24:00:00.000000",
                     "2026-W43-6T24:00", "2026W436T24", "2026-W43T24:00", "2026-W44-7T24:00"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "hour must be in 0..23"):
                strict_fromisoformat(text)

    def test_every_other_input_reads_as_fromisoformat_reads_it(self) -> None:
        for text in ("2026-10-25T00:00:00", "2026-10-25T00:00:00Z", "2026-10-24", "20261024", "2026-W43",
                     "2026W43", "2026-W43-1T00:00", "2026W431T00", "2026-W43-6", "2027-01-01T00:00:00-05:00",
                     "2026-10-24T23:59:59.999999+00:00", "2026-10-24T12:30", "2021-01-03T00:00"):
            with self.subTest(text=text):
                self.assertEqual(strict_fromisoformat(text), datetime.fromisoformat(text))
        for text in ("2026-10-24T25:00:00", "2026-10-24T24:00:01", "2026-02-30T00:00:00", "not a time"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                strict_fromisoformat(text)

    def test_the_3_14_reading_is_refused_on_any_interpreter(self) -> None:
        from omh.plugin_bundle.omh import iso_datetime

        for text in ("2026-10-24T24:00:00", "2026-12-31T24:00:00+00:00", "2026-02-28 24:00:00"):
            with self.subTest(text=text):
                with mock.patch.object(iso_datetime, "datetime", Lenient):
                    self.assertEqual(Lenient.fromisoformat(text).time(), datetime.min.time())
                    with self.assertRaisesRegex(ValueError, "hour must be in 0..23"):
                        strict_fromisoformat(text)
                    midnight = text[:10] + "T00:00:00" + text[19:]
                    self.assertEqual(strict_fromisoformat(midnight), datetime.fromisoformat(midnight))


class SiteTests(unittest.TestCase):
    def test_every_guarded_site_refuses_the_3_14_reading_of_hour_24(self) -> None:
        for (path, function), (module_name, cases) in SITES.items():
            module = importlib.import_module(module_name)
            for index, case in enumerate(cases):
                with self.subTest(site=f"{path}::{function}", case=index):
                    assert_hour_24_refused(self, module, case(module))

    def test_biomedical_reconcile_script_refuses_the_3_14_reading_of_hour_24(self) -> None:
        def outcome(reading: type[datetime], call: str, args: tuple[object, ...], guarded: bool = True) -> object:
            with mock.patch("datetime.datetime", reading):
                api = runpy.run_path(str(RECONCILE))
            function = api[call]
            if not guarded:
                function.__globals__["strict_fromisoformat"] = reading.fromisoformat
            try:
                return "returned", function(*args)
            except ValueError as exc:
                return "raised", str(exc)

        cases = {
            "timestamp": (HOUR_24,),
            "freshness": (HOUR_24, "2020-01-05T00:00:00+00:00", "last_update_posted"),
        }
        for call, args in cases.items():
            with self.subTest(call=call):
                strict = outcome(Strict, call, args)
                self.assertEqual(outcome(Lenient, call, args), strict)
                self.assertNotEqual(outcome(Lenient, call, args, guarded=False), strict)


class SourceGateTests(unittest.TestCase):
    def test_every_raw_fromisoformat_reference_is_a_guard_or_has_a_pinned_reason(self) -> None:
        _guarded, raw = fromisoformat_references()
        expected = {**GUARD_DEFINITIONS, **{key: count for key, (count, _reason) in UNGUARDED.items()}}
        unexplained = sorted(f"{path}::{function} ({count})" for (path, function), count in raw.items()
                             if expected.get((path, function)) != count)
        self.assertEqual(unexplained, [], (
            "CPython 3.14 reads T24:00:00 as the next midnight and 3.11-3.13 refuse it. Route these "
            "references through omh.plugin_bundle.omh.iso_datetime.strict_fromisoformat and add a case "
            "to SITES, or pin their count in UNGUARDED with why their text never comes from outside "
            "OMH's own clock."
        ))
        stale = sorted(f"{p}::{f}" for p, f in expected if (p, f) not in raw)
        self.assertEqual(stale, [], "these entries no longer name a raw fromisoformat reference")

    def test_the_gate_sees_references_that_are_not_calls(self) -> None:
        source = "from datetime import date, datetime\ndef f(xs):\n    parse = datetime.fromisoformat\n" \
                 "    return list(map(datetime.fromisoformat, xs)), date.fromisoformat(xs[0])\n"
        with TemporaryDirectory() as tmp, mock.patch(f"{__name__}.SOURCE", Path(tmp)), \
                mock.patch(f"{__name__}.ROOT", Path(tmp)):
            (Path(tmp) / "probe.py").write_text(source, encoding="utf-8")
            _guarded, raw = fromisoformat_references()
        self.assertEqual(dict(raw), {("probe.py", "f"): 2})

    def test_every_guarded_call_has_exactly_its_cases(self) -> None:
        guarded, _raw = fromisoformat_references()
        script = RECONCILE.relative_to(ROOT).as_posix()
        mismatched = sorted(
            f"{path}::{function} ({count} calls, {len(SITES.get((path, function), ('', []))[1])} cases)"
            for (path, function), count in guarded.items()
            if path != script and len(SITES.get((path, function), ("", []))[1]) != count
        )
        self.assertEqual(mismatched, [])
        self.assertEqual(sorted(key for key in SITES if key not in guarded), [], "SITES names a call that is gone")
        self.assertEqual(sorted(f for p, f in guarded if p == script), ["freshness", "timestamp"])

    def test_every_guard_copy_reads_as_the_bundle_helper_does(self) -> None:
        # Each copy runs on the 3.14 reading, whatever the interpreter: on 3.11 and
        # 3.13, raw fromisoformat already refuses hour 24, so a copy that ran on the
        # real parser there would compare nothing for exactly the inputs it guards.
        # The reference is the bundle helper on the real interpreter, which on 3.11
        # to 3.13 is raw fromisoformat itself.
        texts = ("2026-10-24T24:00:00", "2026-10-24T24:00:00Z".replace("Z", "+00:00"), "2026-12-31 24:00",
                 "20261024T24", "2026-W43-6T24:00", "2026-W43T24", "2026-10-25T00:00:00", "2026-W43",
                 "2026W431T00", "2026-10-24", "2026-10-24T12:30:00+09:00", "2026-10-24T25:00", "not a time")

        def outcome(parse: Callable[[str], datetime], text: str) -> object:
            try:
                return parse(text)
            except ValueError as exc:
                return "raised: " + str(exc).split(",")[0]

        for path in GUARD_COPIES:
            with mock.patch("datetime.datetime", Lenient):
                copy = runpy.run_path(str(path))["strict_fromisoformat"]
            for text in texts:
                with self.subTest(copy=path.name, text=text):
                    self.assertEqual(outcome(copy, text), outcome(strict_fromisoformat, text))

    def test_the_guard_copies_are_one_function(self) -> None:
        bodies = {path.name: guard_body(path.read_text(encoding="utf-8")) for path in GUARD_COPIES}
        drifted = sorted(name for name, body in bodies.items() if body != bodies[GUARD_COPIES[0].name])
        self.assertEqual(drifted, [], (
            "these copies of strict_fromisoformat / date_spellings no longer match "
            "src/plugin_bundle/omh/iso_datetime.py; change all three together"
        ))

    def test_the_drift_check_sees_a_changed_copy(self) -> None:
        source = RECONCILE.read_text(encoding="utf-8")
        self.assertIn("time(0)", source)
        self.assertNotEqual(guard_body(source.replace("time(0)", "time(1)")), guard_body(source))
        self.assertNotEqual(guard_body(source.replace("weekday == 1", "weekday == 7")), guard_body(source))


if __name__ == "__main__":
    unittest.main()
