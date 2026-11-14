from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from omh.coding.hermes_child_receipts import load_hermes_child_receipt
from omh.quality.paired_run_decision import build_paired_run_decision, parse_paired_run_decision
from omh.quality.paired_run_model import (
    ArmRole,
    ArmSpec,
    BehaviorVerdict,
    InfrastructureStatus,
    PairedRunValidationError,
    RunResultInput,
    TaskSpec,
)
from test_paired_run_decision_contract import _request
from paired_run_support import write_observed_receipt


class PairedRunSecurityTests(unittest.TestCase):
    def test_real_library_flow_opens_no_socket(self) -> None:
        with TemporaryDirectory(prefix="omh-paired-security-") as raw:
            home = (Path(raw) / ".omh").resolve()
            write_observed_receipt(home, "run-1")
            with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
                receipt = load_hermes_child_receipt(home, "run-1")
                record = build_paired_run_decision(_request(home), home)
        self.assertEqual(receipt.claim, "observed")
        self.assertEqual(record.schema_version, "paired_run_decision/v2")

    def test_parser_rejects_resource_exhaustion_before_recursive_validation(self) -> None:
        with TemporaryDirectory(prefix="omh-paired-limits-") as raw:
            home = (Path(raw) / ".omh").resolve()
            valid = json.loads(build_paired_run_decision(_request(home), home).to_json())
        cases = (
            "x" * 1_048_577,
            "[" * 17 + "]" * 17,
            json.dumps({**valid, "decision_id": "x" * 513}),
            json.dumps({**valid, "tasks": valid["tasks"] * 129}),
            json.dumps({**valid, "results": valid["results"] * 257}),
            json.dumps({
                **valid,
                "baseline": {**valid["baseline"], "exposed_skills": [f"skill-{index:03d}" for index in range(129)]},
            }),
        )
        for candidate in cases:
            with self.subTest(size=len(candidate)), self.assertRaises(PairedRunValidationError):
                parse_paired_run_decision(candidate)
        with patch("omh.quality.paired_run_validation.json.loads", side_effect=RecursionError):
            with self.assertRaises(PairedRunValidationError):
                parse_paired_run_decision("{}")

    def test_parser_wraps_hostile_integer_conversion_error(self) -> None:
        document = '{"schema_version":' + "9" * 5_000 + "}"
        with self.assertRaises(PairedRunValidationError):
            parse_paired_run_decision(document)

    def test_parser_accepts_near_limit_canonical_decision(self) -> None:
        tasks = tuple(
            TaskSpec(
                f"task-{index:03d}",
                f"criteria-{index:03d}",
                f"{index:064x}",
            )
            for index in range(128)
        )
        results = tuple(
            RunResultInput(
                task.task_id,
                arm,
                InfrastructureStatus.NOT_OBSERVED,
                BehaviorVerdict.NOT_OBSERVED,
                None,
            )
            for task in tasks
            for arm in ArmRole
        )
        with TemporaryDirectory(prefix="omh-paired-near-limit-") as raw:
            request = replace(
                _request((Path(raw) / ".omh").resolve()),
                baseline=ArmSpec(
                    "base", "hermes", "model-a",
                    tuple(f"skill-{index:03d}" for index in range(128)),
                ),
                tasks=tasks,
                max_total_runs=256,
                results=results,
            )
            document = build_paired_run_decision(request).to_json()
        self.assertEqual(len(parse_paired_run_decision(document).tasks), 128)

    def test_hostile_metadata_never_crosses_builder_boundary(self) -> None:
        with TemporaryDirectory(prefix="omh-paired-hostile-") as raw:
            request = _request((Path(raw) / ".omh").resolve())
            candidates = (
                replace(request, decision_id="https://attacker.example"),
                replace(request, execution_revision="line\nbreak"),
                replace(request, execution_revision="x" * 161),
                replace(request, execution_revision="secret-token"),
            )
            for candidate in candidates:
                with self.subTest(candidate=candidate), self.assertRaises(PairedRunValidationError):
                    build_paired_run_decision(candidate)


if __name__ == "__main__":
    unittest.main()
