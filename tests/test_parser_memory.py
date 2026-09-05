from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.commands.main import build_parser


class MemoryParserTests(unittest.TestCase):
    def test_new_memory_control_commands_parse_with_explicit_gates(self) -> None:
        cases = (
            (["memory", "inventory"], "cmd_memory_inventory"),
            (["memory", "inventory", "--write-ledger"], "cmd_memory_inventory"),
            (["memory", "reactivate", "legacy-record", "--revision", "1", "--review-id", "review-record"], "cmd_memory_reactivate"),
            (["memory", "batch-stage", "--batch", "batch.json"], "cmd_memory_batch_stage"),
            (["memory", "batch-review", "batch-one", "--decisions", "decisions.json"], "cmd_memory_batch_review"),
            (["memory", "batch-apply", "batch-one", "--apply"], "cmd_memory_batch_apply"),
            (["memory", "restore", "record-one", "--revision", "1"], "cmd_memory_restore"),
            (["memory", "prune", "record-one", "--revision", "1", "--apply", "--confirm-hard-delete-local"], "cmd_memory_prune"),
            (["memory", "correct", "record-one", "--revision", "1", "Corrected summary"], "cmd_memory_correct"),
            (["memory", "lineage", "record-one"], "cmd_memory_lineage"),
            (["memory", "lineage", "record-one", "--depth", "5"], "cmd_memory_lineage"),
            (["memory", "perspectives"], "cmd_memory_perspectives"),
            (["memory", "pin", "record-one"], "cmd_memory_pin"),
            (["memory", "unpin", "record-one"], "cmd_memory_unpin"),
            (["memory", "attention", "record-one", "--tier", "reference"], "cmd_memory_attention"),
            (["memory", "attention", "record-one", "--tier", "archive", "--apply"], "cmd_memory_attention"),
            (["memory", "recall", "query", "--include-archived"], "cmd_memory_recall"),
            (["memory", "rollup", "--tag", "deploy"], "cmd_memory_rollup"),
            (["memory", "rollup", "--tag", "deploy", "--apply"], "cmd_memory_rollup"),
            (["memory", "capture", "summary", "--observed", "codex"], "cmd_memory_capture"),
            (["memory", "recall", "query", "--observer", "operator", "--observed", "codex"], "cmd_memory_recall"),
            (["memory", "confirm", "record-one"], "cmd_memory_confirm"),
            (["memory", "confirm", "--all-due", "--stale-after-days", "120"], "cmd_memory_confirm"),
            (["memory", "confirm", "record-one", "--stale-after", "2027-01-15"], "cmd_memory_confirm"),
            (["memory", "approve", "cand-one", "--retention-class", "durable"], "cmd_memory_approve"),
            (["memory", "capture", "summary", "--stale-after", "2027-01-15"], "cmd_memory_capture"),
            (["memory", "capture", "summary", "--expires-at", "2027-01-15T09:00:00Z"], "cmd_memory_capture"),
            (["memory", "demote"], "cmd_memory_demote"),
            (["memory", "demote", "--file", "USER.md", "--max", "3", "--stage"], "cmd_memory_demote"),
        )

        for argv, handler_name in cases:
            with self.subTest(argv=argv):
                args = build_parser().parse_args(argv)
                self.assertEqual(args.func.__name__, handler_name)

    def test_memory_confirm_requires_exactly_one_target(self) -> None:
        from omh.installer import OmhError

        for argv in (["memory", "confirm"], ["memory", "confirm", "record-one", "--all-due"]):
            with self.subTest(argv=argv):
                args = build_parser().parse_args(argv)
                with self.assertRaises(OmhError):
                    args.func(args)

    def test_memory_capture_rejects_invalid_source_class_at_parser_boundary(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            build_parser().parse_args(["memory", "capture", "--source-class", "unknown", "summary"])
        self.assertEqual(raised.exception.code, 2)

    def test_memory_capture_collects_repeatable_derived_from_refs(self) -> None:
        args = build_parser().parse_args(
            ["memory", "capture", "summary", "--derived-from", "mem_a", "--derived-from", "mem_b"]
        )
        self.assertEqual(args.derived_from, ["mem_a", "mem_b"])

    def test_memory_attention_rejects_an_unknown_tier_at_the_parser_boundary(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            build_parser().parse_args(["memory", "attention", "record-one", "--tier", "cold-storage"])
        self.assertEqual(raised.exception.code, 2)

    def test_memory_attention_requires_an_explicit_tier(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            build_parser().parse_args(["memory", "attention", "record-one"])
        self.assertEqual(raised.exception.code, 2)

    def test_memory_attention_defaults_to_report_only(self) -> None:
        args = build_parser().parse_args(["memory", "attention", "record-one", "--tier", "archive"])
        self.assertFalse(args.apply)

    def test_memory_lineage_defaults_to_three_hops(self) -> None:
        args = build_parser().parse_args(["memory", "lineage", "record-one"])
        self.assertEqual(args.depth, 3)

    def test_memory_review_actions_accept_a_candidate_revision(self) -> None:
        for argv in (
            ["memory", "approve", "cand-one", "--candidate-revision", "rev_abc"],
            ["memory", "reject", "cand-one", "--candidate-revision", "rev_abc"],
        ):
            with self.subTest(argv=argv):
                self.assertEqual(build_parser().parse_args(argv).candidate_revision, "rev_abc")

    def test_memory_review_actions_default_to_no_revision(self) -> None:
        args = build_parser().parse_args(["memory", "approve", "cand-one"])
        self.assertEqual(args.candidate_revision, "")


class MemoryReviewRevisionCliTests(unittest.TestCase):
    """The CLI review path refuses a stale or unproven card without writing."""

    def _capture(self, tmp: Path) -> tuple[list[str], str]:
        homes = ["--omh-home", str(tmp / ".omh"), "--hermes-home", str(tmp / ".hermes")]
        status, stdout, _stderr = run_cli(
            [*homes, "memory", "capture", "Deploys go through staging first"]
        )
        self.assertEqual(status, 0, stdout)
        return homes, str(json.loads(stdout)["candidate"]["candidate_id"])

    def _revision(self, homes: list[str], candidate_id: str) -> str:
        status, stdout, _stderr = run_cli([*homes, "memory", "review", "--candidate", candidate_id])
        self.assertEqual(status, 0, stdout)
        return str(json.loads(stdout)["cards"][0]["review_revision"])

    def test_approve_without_a_revision_refuses_and_writes_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            homes, candidate_id = self._capture(root)

            status, stdout, _stderr = run_cli([*homes, "memory", "approve", candidate_id])

            payload = json.loads(stdout)
            self.assertNotEqual(status, 0)
            self.assertEqual(payload["reason_code"], "review_revision_required")
            self.assertFalse(payload["applied"])
            self.assertFalse((root / ".omh" / "memory" / "records").exists())

    def test_approve_with_a_stale_revision_refuses_and_writes_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            homes, candidate_id = self._capture(root)
            self._revision(homes, candidate_id)

            status, stdout, _stderr = run_cli(
                [*homes, "memory", "approve", candidate_id, "--candidate-revision", "rev_" + "0" * 32]
            )

            payload = json.loads(stdout)
            self.assertNotEqual(status, 0)
            self.assertEqual(payload["reason_code"], "stale_review")
            self.assertFalse(payload["applied"])
            self.assertFalse((root / ".omh" / "memory" / "records").exists())

    def test_stale_review_refusal_never_echoes_caller_revision(self) -> None:
        sensitive_revision = "JBSWY3DPEHPK3PXP" * 3
        for action in ("approve", "reject"):
            with self.subTest(action=action), TemporaryDirectory() as tmp:
                root = Path(tmp)
                homes, candidate_id = self._capture(root)

                status, stdout, stderr = run_cli(
                    [*homes, "memory", action, candidate_id, "--candidate-revision", sensitive_revision]
                )

                payload = json.loads(stdout)
                self.assertNotEqual(status, 0)
                self.assertEqual(payload["reason_code"], "stale_review")
                self.assertEqual(
                    payload["detail"],
                    "stale_review: the candidate changed after the reviewed card was rendered; re-read it and decide again",
                )
                self.assertNotIn(sensitive_revision, stdout)
                self.assertNotIn(sensitive_revision, stderr)
                self.assertFalse((root / ".omh" / "memory" / "records").exists())

    def test_approve_and_reject_with_the_displayed_revision_succeed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            homes, candidate_id = self._capture(root)

            status, stdout, _stderr = run_cli(
                [*homes, "memory", "approve", candidate_id, "--candidate-revision", self._revision(homes, candidate_id)]
            )
            self.assertEqual(status, 0, stdout)
            self.assertEqual(json.loads(stdout)["decision"], "approved_manual")

            status, stdout, _stderr = run_cli([*homes, "memory", "capture", "Deploys skip staging on Fridays"])
            self.assertEqual(status, 0, stdout)
            second = str(json.loads(stdout)["candidate"]["candidate_id"])
            status, stdout, _stderr = run_cli(
                [*homes, "memory", "reject", second, "--candidate-revision", self._revision(homes, second)]
            )

            self.assertEqual(status, 0, stdout)
            self.assertEqual(json.loads(stdout)["decision"], "rejected")


if __name__ == "__main__":
    unittest.main()
