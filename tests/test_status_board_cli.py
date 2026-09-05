"""CLI contract for `omh coding status-board`.

The projection itself is covered by tests/test_coding_status_board.py; these
tests cover only what the command adds: plain text by default, `--json` as the
opt-in, a refused non-positive limit, and the bounded-surface declaration.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.coding.context_safety import coding_progress_policy_enforcement  # noqa: E402
from omh.coding.status_board import CODING_STATUS_BOARD_SCHEMA_VERSION  # noqa: E402
from omh.system.paths import resolve_paths  # noqa: E402

# Must satisfy omh.coding.fanout_contracts.FANOUT_ID_PATTERN; the fanout
# directory layout is the one `omh coding fanout dispatch` writes.
_FANOUT_ID = "fanout-0123456789ab"


def _base(root: Path) -> list[str]:
    return ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]


def _write_dispatched_unit(root: Path) -> None:
    paths = resolve_paths(root / ".omh", root / ".hermes")
    fanout_dir = paths.fanout_contracts_dir / _FANOUT_ID
    fanout_dir.mkdir(parents=True, exist_ok=True)
    (fanout_dir / "fanout_contract.json").write_text(
        json.dumps({"fanout_id": _FANOUT_ID, "units": [{"unit_id": "core", "title": "Core work"}]}),
        encoding="utf-8",
    )
    (fanout_dir / "dispatch_summary.json").write_text(
        json.dumps(
            {
                "fanout_id": _FANOUT_ID,
                "units": [
                    {
                        "unit_id": "core",
                        "run_ref": "run-core",
                        "owner": "codex",
                        "model": "gpt-5.6-sol",
                        "reasoning_effort": "xhigh",
                        "status": "completed",
                        "duration_seconds": 92,
                        "tokens_total": 12345,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class StatusBoardCliTests(unittest.TestCase):
    def test_empty_state_renders_text_instead_of_crashing(self) -> None:
        with TemporaryDirectory() as tmp:
            status, stdout, stderr = run_cli(
                _base(Path(tmp)) + ["coding", "status-board"], output_json=False
            )
        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        self.assertIn("Coding status board", stdout)
        self.assertIn("No coding work observed.", stdout)

    def test_plain_text_is_the_default(self) -> None:
        """Without `--json` the raw payload must not reach stdout at all."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_dispatched_unit(root)
            status, stdout, stderr = run_cli(_base(root) + ["coding", "status-board"], output_json=False)
        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        self.assertNotIn(CODING_STATUS_BOARD_SCHEMA_VERSION, stdout)
        self.assertNotIn('"schema_version"', stdout)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(stdout)
        # The board still shows the row, just as a column instead of JSON.
        self.assertIn("Core work", stdout)
        self.assertIn("gpt-5.6-sol xhigh", stdout)
        self.assertIn("12,345", stdout)

    def test_json_opt_in_emits_the_schema_versioned_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_dispatched_unit(root)
            status, stdout, stderr = run_cli(
                _base(root) + ["coding", "status-board", "--json"], output_json=False
            )
        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], CODING_STATUS_BOARD_SCHEMA_VERSION)
        self.assertEqual(payload["unit_count"], 1)
        self.assertEqual(payload["units"][0]["label"], "Core work")
        self.assertIn("not result", payload["claim_boundary"])

    def test_limit_caps_the_rendered_rows(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_dispatched_unit(root)
            status, stdout, stderr = run_cli(
                _base(root) + ["coding", "status-board", "--limit", "1", "--json"], output_json=False
            )
        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        self.assertEqual(len(json.loads(stdout)["units"]), 1)

    def test_a_non_positive_limit_is_refused_not_coerced(self) -> None:
        """`--limit 0` would print a board with no rows but a non-zero count."""
        for value in ("0", "-1"):
            with self.subTest(limit=value), TemporaryDirectory() as tmp:
                status, stdout, stderr = run_cli(
                    _base(Path(tmp)) + ["coding", "status-board", "--limit", value], output_json=False
                )
                self.assertNotEqual(status, 0)
                self.assertEqual(stdout, "")
                self.assertIn("--limit must be at least 1", stderr)


class StatusBoardBoundedSurfaceTests(unittest.TestCase):
    def test_the_board_is_declared_a_bounded_surface(self) -> None:
        self.assertIn("omh coding status-board", coding_progress_policy_enforcement()["bounded_surfaces"])


class ProgressStatusPlainTextTests(unittest.TestCase):
    """The neighbouring status command must follow the same plain-text default.

    `runtime progress-status` used to call `_print_json` unconditionally, so a
    human asking what was running got one full binding record per executor as
    raw JSON. Shipping a text board next to that leaves the surface half
    readable, which is why the fix belongs with the board.
    """

    def _bound_and_observed(self, base: list[str]) -> None:
        status, stdout, stderr = run_cli(
            base + ["runtime", "record", "--skill", "oh-my-hermes", "--harness", "coding-handling"]
        )
        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        run_id = json.loads(stdout)["run"]["run_id"]
        status, _stdout, stderr = run_cli(
            base
            + [
                "runtime", "progress-bind", "--run", run_id,
                "--executor-profile", "claude_code", "--claude-session-ref", "sess-1",
            ]
        )
        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        status, _stdout, stderr = run_cli(
            base
            + [
                "runtime", "progress-observe", "--run", run_id,
                "--process-status", "running",
                "--profile-status", "running",
                "--profile-latest-event", "repo_exploration",
                "--profile-summary", "inspecting",
            ]
        )
        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)

    def test_progress_status_renders_text_by_default(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = _base(root)
            self._bound_and_observed(base)
            status, stdout, stderr = run_cli(base + ["runtime", "progress-status"], output_json=False)
        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        self.assertIn("Executor progress status (1 active, 0 stale)", stdout)
        self.assertIn("claude_code", stdout)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(stdout)

    def test_progress_status_empty_state_renders_text(self) -> None:
        with TemporaryDirectory() as tmp:
            status, stdout, stderr = run_cli(
                _base(Path(tmp)) + ["runtime", "progress-status"], output_json=False
            )
        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        self.assertIn("No executor progress observed.", stdout)

    def test_progress_status_json_opt_in_still_emits_the_projection(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = _base(root)
            self._bound_and_observed(base)
            status, stdout, stderr = run_cli(base + ["runtime", "progress-status", "--json"], output_json=False)
        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "omh_executor_progress_projection/v1")
        self.assertEqual(payload["active_executors"][0]["executor_profile"], "claude_code")

    def test_a_repeated_text_call_reports_the_suppressed_shape(self) -> None:
        """The compact replacement carries counts, not rows; it must still render."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = _base(root)
            self._bound_and_observed(base)
            run_cli(base + ["runtime", "progress-status"], output_json=False)
            status, stdout, stderr = run_cli(base + ["runtime", "progress-status"], output_json=False)
        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        self.assertIn("unchanged since the last emission", stdout)
        self.assertIn("Active executors: 1", stdout)


if __name__ == "__main__":
    unittest.main()
