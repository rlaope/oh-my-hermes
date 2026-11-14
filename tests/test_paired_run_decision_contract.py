from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from omh.coding.hermes_child_receipts import (
    VerifiedHermesChildReceipt,
    load_hermes_child_receipt,
)
from omh.quality.paired_run_decision import SCHEMA_VERSION, build_paired_run_decision, parse_paired_run_decision
from omh.quality.paired_run_model import ArmRole, ArmSpec, BehaviorVerdict, InfrastructureStatus, PairedRunRequest, RunResultInput, TaskSpec
from omh.quality.paired_run_validation import PairedRunValidationError
from paired_run_support import paired_evaluation_binding, write_observed_receipt

_INPUT_DIGEST = "a" * 64


def _receipt(home: Path, run_id: str) -> VerifiedHermesChildReceipt:
    return load_hermes_child_receipt(home, run_id)


def _request(
    root: Path,
    verdicts: tuple[BehaviorVerdict, BehaviorVerdict] = (
        BehaviorVerdict.PASS,
        BehaviorVerdict.FAIL,
    ),
) -> PairedRunRequest:
    root = root.resolve()
    receipts = []
    for run_id, arm, model, skills in (
        ("baseline-run", "baseline", "model-a", ()),
        ("variant-run", "variant", "model-b", ("skill-a", "skill-b")),
    ):
        write_observed_receipt(
            root,
            run_id,
            evaluation_binding=paired_evaluation_binding(
                task_id="task-1", criteria_ref="criteria-1",
                input_digest=_INPUT_DIGEST, arm=arm, executor="hermes",
                model=model, exposed_skills=skills,
                execution_revision="rev-abc",
            ),
        )
        receipts.append(_receipt(root, run_id))
    return PairedRunRequest(
        decision_id="decision-1",
        supersedes_decision_ref=None,
        baseline=ArmSpec("base", "hermes", "model-a", ()),
        variant=ArmSpec("variant", "hermes", "model-b", ("skill-a", "skill-b")),
        tasks=(TaskSpec("task-1", "criteria-1", _INPUT_DIGEST),),
        max_total_runs=2,
        max_dispatch_seconds=900,
        execution_revision="rev-abc",
        recorded_at="2026-08-27T00:01:00Z",
        results=(
            RunResultInput("task-1", ArmRole.BASELINE, InfrastructureStatus.OBSERVED, verdicts[0], receipts[0]),
            RunResultInput("task-1", ArmRole.VARIANT, InfrastructureStatus.OBSERVED, verdicts[1], receipts[1]),
        ),
    )


class PairedRunDecisionContractTests(unittest.TestCase):
    def test_builds_closed_recomputable_full_matrix_contract(self) -> None:
        # Given
        with TemporaryDirectory() as raw:
            home = (Path(raw) / ".omh").resolve()
            request = _request(home)
            # When
            record = build_paired_run_decision(request, home)
            parsed = parse_paired_run_decision(record.to_json(), home)
            payload = json.loads(record.to_json())
        # Then
        self.assertEqual(SCHEMA_VERSION, "paired_run_decision/v2")
        self.assertEqual(parsed.task_set_digest, payload["task_set_digest"])
        self.assertEqual(payload["outcome"], "baseline_dominates")
        self.assertEqual(len(payload["results"]), 2)
        self.assertEqual(
            payload["claim_boundary"],
            "behavior_from_signed_local_omh_dispatch_observation",
        )
        self.assertIn("max_dispatch_seconds", payload)
        self.assertIn("input_digest", payload["tasks"][0])

    def test_not_observed_placeholder_and_infra_error_receipt_boundary(self) -> None:
        placeholder = RunResultInput(
            "task-1", ArmRole.BASELINE, InfrastructureStatus.NOT_OBSERVED,
            BehaviorVerdict.NOT_OBSERVED, None,
        )
        self.assertEqual(placeholder.infrastructure_status.value, "not_observed")
        with self.assertRaises(PairedRunValidationError):
            RunResultInput(
                "task-1", ArmRole.VARIANT, InfrastructureStatus.INFRA_ERROR,
                BehaviorVerdict.NOT_OBSERVED, None,
            )
        with self.assertRaises(PairedRunValidationError):
            RunResultInput(
                "task-1", ArmRole.VARIANT, InfrastructureStatus.INFRA_ERROR,
                BehaviorVerdict.NOT_OBSERVED, {"status": "failed"},
            )

    def test_only_completed_receipt_authorizes_behavior_verdict(self) -> None:
        with TemporaryDirectory(prefix="omh-nonterminal-") as raw:
            home = (Path(raw) / ".omh").resolve()
            write_observed_receipt(home, "failed-run", "failed")
            receipt = _receipt(home, "failed-run")
            with self.assertRaises(PairedRunValidationError):
                RunResultInput("task-1", ArmRole.BASELINE, InfrastructureStatus.OBSERVED, BehaviorVerdict.FAIL, receipt)
            infra = RunResultInput("task-1", ArmRole.BASELINE, InfrastructureStatus.INFRA_ERROR, BehaviorVerdict.NOT_OBSERVED, receipt)
        self.assertEqual(infra.infrastructure_status, InfrastructureStatus.INFRA_ERROR)

    def test_plain_mapping_never_authorizes_behavior_verdict(self) -> None:
        with self.assertRaises(PairedRunValidationError):
            RunResultInput(
                "task-1",
                ArmRole.BASELINE,
                InfrastructureStatus.OBSERVED,
                BehaviorVerdict.PASS,
                {"run_id": "forged"},
            )

    def test_task_and_result_permutations_serialize_canonically(self) -> None:
        with TemporaryDirectory(prefix="omh-canonical-") as raw:
            home = (Path(raw) / ".omh").resolve()
            write_observed_receipt(
                home, "failed-run", "failed",
                evaluation_binding=paired_evaluation_binding(
                    task_id="task-a", criteria_ref="criteria-a",
                    input_digest="c" * 64, arm="baseline", executor="hermes",
                    model="model-a", exposed_skills=(),
                    execution_revision="rev-canonical",
                ),
            )
            failed = _receipt(home, "failed-run")
            tasks = (
                TaskSpec("task-b", "criteria-b", "b" * 64),
                TaskSpec("task-a", "criteria-a", "c" * 64),
            )
            rows = (
                RunResultInput("task-b", ArmRole.VARIANT, InfrastructureStatus.NOT_OBSERVED, BehaviorVerdict.NOT_OBSERVED, None),
                RunResultInput("task-a", ArmRole.BASELINE, InfrastructureStatus.INFRA_ERROR, BehaviorVerdict.NOT_OBSERVED, failed),
                RunResultInput("task-a", ArmRole.VARIANT, InfrastructureStatus.NOT_OBSERVED, BehaviorVerdict.NOT_OBSERVED, None),
                RunResultInput("task-b", ArmRole.BASELINE, InfrastructureStatus.NOT_OBSERVED, BehaviorVerdict.NOT_OBSERVED, None),
            )
            base = PairedRunRequest(
                "canonical-1", None, ArmSpec("base", "hermes", "model-a", ()),
                ArmSpec("variant", "hermes", "model-b", ("skill-b", "skill-a")),
                tasks, 1, 900, "rev-canonical", "2026-08-27T00:00:00Z", rows,
            )
            first = build_paired_run_decision(base, home)
            second = build_paired_run_decision(
                replace(
                    base,
                    tasks=tuple(reversed(tasks)),
                    results=tuple(reversed(rows)),
                ),
                home,
            )
        self.assertEqual(
            (first.task_set_digest, first.aggregate, first.outcome, first.to_json()),
            (second.task_set_digest, second.aggregate, second.outcome, second.to_json()),
        )
        payload = json.loads(first.to_json())
        payload["tasks"].reverse()
        with self.assertRaises(PairedRunValidationError):
            parse_paired_run_decision(json.dumps(payload))

    def test_builder_and_parser_reject_boundary_and_canonicality_faults(self) -> None:
        with TemporaryDirectory(prefix="omh-boundary-") as raw:
            request_home = (Path(raw) / ".omh").resolve()
            request = _request(request_home)
            invalid_requests = (
                replace(request, variant=replace(request.variant, arm_id=request.baseline.arm_id)),
                replace(request, baseline=replace(request.baseline, executor="https://evil.example")),
                replace(
                    request,
                    tasks=(TaskSpec("task\nbody", "criteria-1", _INPUT_DIGEST),),
                ),
                replace(request, execution_revision="secret-token"),
                replace(request, recorded_at="2026-08-27T00:01:00"),
            )
            for candidate in invalid_requests:
                with self.subTest(candidate=candidate), self.assertRaises(PairedRunValidationError):
                    build_paired_run_decision(candidate)
            valid = json.loads(build_paired_run_decision(request, request_home).to_json())
        mutations = (
            lambda item: item["variant"].update({"arm_id": item["baseline"]["arm_id"]}),
            lambda item: item["baseline"].update({"executor": "https://evil.example"}),
            lambda item: item.update({"execution_revision": "x" * 161}),
            lambda item: item.update({"recorded_at": "2026-08-27T00:01:00"}),
            lambda item: item.update({"recorded_at": "2026-08-27T01:01:00+01:00"}),
            lambda item: item["results"][0].update({"receipt_verified_at": "2026-08-27T00:00:00"}),
            lambda item: item.update({"task_set_digest": "abc"}),
            lambda item: item["baseline"].update({"exposure_digest": "abc"}),
            lambda item: item.update({"results": list(reversed(item["results"]))}),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                candidate = json.loads(json.dumps(valid))
                mutate(candidate)
                with self.assertRaises(PairedRunValidationError):
                    parse_paired_run_decision(json.dumps(candidate))
