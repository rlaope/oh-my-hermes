from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli  # noqa: E402

from omh.coding.fanout import (  # noqa: E402
    build_fanout_contract,
    detect_boundary_overlaps,
    is_degenerate_single_unit,
    merge_order,
    single_unit_redirect,
)
from omh.coding.fanout_artifacts import read_fanout_contract, write_fanout_contract  # noqa: E402
from omh.coding.fanout_contracts import FanoutContractError  # noqa: E402
from omh.system.paths import OmhPaths  # noqa: E402


_UNITS = [
    {"unit_id": "core", "title": "Refactor core", "owner": "codex", "file_scope": ["src/auth/"], "depends_on": []},
    {"unit_id": "tests", "title": "Add tests", "owner": "claude-code", "file_scope": ["tests/auth/"], "depends_on": ["core"]},
    {"unit_id": "docs", "title": "Update docs", "owner": None, "file_scope": ["docs/auth.md"], "depends_on": []},
]


class FanoutEngineTests(unittest.TestCase):
    def test_contract_is_deterministic_and_prepared_only(self) -> None:
        first = build_fanout_contract("refactor auth and cover it", _UNITS, source="discord")
        second = build_fanout_contract("refactor auth and cover it", _UNITS, source="discord")

        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], "fanout_contract/v1")
        self.assertEqual(first["status"], "prepared_not_observed")
        self.assertEqual(first["merge_plan"]["merge_order"], ["core", "docs", "tests"])
        self.assertNotIn("refactor auth and cover it", json.dumps(first))
        self.assertFalse(first["goal"]["raw_prompt_stored"])
        self.assertIn("not dispatch", first["claim_boundary"])

    def test_unit_boundaries_derive_do_not_touch_and_neutral_handoff(self) -> None:
        contract = build_fanout_contract("split work", _UNITS)
        units = {unit["unit_id"]: unit for unit in contract["units"]}

        self.assertEqual(units["core"]["boundary"]["do_not_touch"], ["docs/auth.md", "tests/auth/"])
        self.assertEqual(units["core"]["branch_suggestion"], "agent/core")
        self.assertEqual(units["core"]["handoff"]["executor_target"], "codex")
        self.assertEqual(units["docs"]["handoff"]["executor_target"], "choose")
        self.assertIsNone(units["docs"]["owner"])
        for unit in contract["units"]:
            self.assertEqual(unit["handoff"]["dispatch_policy"], "prepare_only")
            self.assertEqual(unit["handoff"]["status"], "prepared_not_observed")
            self.assertEqual(unit["status"], "prepared")

    def test_overlap_without_dependency_is_rejected(self) -> None:
        with self.assertRaises(FanoutContractError):
            build_fanout_contract(
                "x",
                [
                    {"unit_id": "a", "file_scope": ["src/shared.py"]},
                    {"unit_id": "b", "file_scope": ["src/shared.py"]},
                ],
            )

    def test_overlap_with_dependency_is_noted_and_ordered(self) -> None:
        contract = build_fanout_contract(
            "x",
            [
                {"unit_id": "a", "file_scope": ["src/shared.py"]},
                {"unit_id": "b", "file_scope": ["src/shared.py", "src/b.py"], "depends_on": ["a"]},
            ],
        )
        notes = contract["merge_plan"]["conflict_risk_notes"]

        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["units"], ["a", "b"])
        self.assertEqual(notes[0]["shared_files"], ["src/shared.py"])
        self.assertEqual(contract["merge_plan"]["merge_order"], ["a", "b"])

    def test_dependency_cycle_is_rejected(self) -> None:
        with self.assertRaises(FanoutContractError):
            merge_order(
                [
                    {"unit_id": "a", "file_scope": ["1"], "depends_on": ["b"]},
                    {"unit_id": "b", "file_scope": ["2"], "depends_on": ["a"]},
                ]
            )

    def test_empty_boundary_unknown_owner_and_unknown_dependency_are_rejected(self) -> None:
        with self.assertRaises(FanoutContractError):
            build_fanout_contract("x", [{"unit_id": "a", "file_scope": []}, {"unit_id": "b", "file_scope": ["f"]}])
        with self.assertRaises(FanoutContractError):
            build_fanout_contract(
                "x",
                [
                    {"unit_id": "a", "owner": "skynet", "file_scope": ["f1"]},
                    {"unit_id": "b", "file_scope": ["f2"]},
                ],
            )
        with self.assertRaises(FanoutContractError):
            build_fanout_contract(
                "x",
                [
                    {"unit_id": "a", "file_scope": ["f1"], "depends_on": ["ghost"]},
                    {"unit_id": "b", "file_scope": ["f2"]},
                ],
            )

    def test_single_unit_is_degenerate_redirect(self) -> None:
        units = [_UNITS[0]]

        self.assertTrue(is_degenerate_single_unit(units))
        redirect = single_unit_redirect(units)
        self.assertEqual(redirect["schema_version"], "fanout_redirect/v1")
        self.assertEqual(redirect["next_command"], "omh coding delegate")

    def test_merge_order_tie_break_is_deterministic(self) -> None:
        units = [
            {"unit_id": "zeta", "file_scope": ["z"]},
            {"unit_id": "alpha", "file_scope": ["a"]},
            {"unit_id": "mid", "file_scope": ["m"], "depends_on": ["zeta", "alpha"]},
        ]

        self.assertEqual(merge_order(units), ["alpha", "zeta", "mid"])

    def test_overlap_detector_returns_no_notes_for_disjoint_units(self) -> None:
        self.assertEqual(detect_boundary_overlaps(_UNITS), [])


class FanoutArtifactTests(unittest.TestCase):
    def test_writer_persists_metadata_only_contract_under_omh_home(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")
            contract = build_fanout_contract("persist me", _UNITS)

            written = write_fanout_contract(paths, contract)
            contract_path = Path(written["artifacts"]["contract_path"])

            self.assertTrue(contract_path.is_file())
            self.assertTrue(contract_path.is_relative_to(paths.fanout_contracts_dir))
            self.assertEqual(written["artifacts"]["privacy"], "metadata_only")
            self.assertEqual(read_fanout_contract(paths, contract["fanout_id"])["fanout_id"], contract["fanout_id"])

    def test_writer_rejects_invalid_id_and_symlinked_storage(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")

            with self.assertRaises(ValueError):
                write_fanout_contract(paths, {"fanout_id": "../escape"})

            outside = Path(tmp) / "outside"
            outside.mkdir()
            paths.fanout_contracts_dir.parent.mkdir(parents=True)
            paths.fanout_contracts_dir.symlink_to(outside)
            contract = build_fanout_contract("symlink guard", _UNITS)
            with self.assertRaises(ValueError):
                write_fanout_contract(paths, contract)


class FanoutCliTests(unittest.TestCase):
    def _units_file(self, root: Path) -> Path:
        units_path = root / "units.json"
        units_path.write_text(json.dumps(_UNITS), encoding="utf-8")
        return units_path

    def test_fanout_prepare_records_contract_and_never_dispatches(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, stdout, stderr = run_cli(
                base
                + [
                    "coding",
                    "fanout",
                    "prepare",
                    "--goal",
                    "refactor",
                    "auth",
                    "safely",
                    "--units",
                    str(self._units_file(root)),
                    "--record",
                ]
            )

            self.assertEqual(status, 0, stderr)
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], "fanout_contract/v1")
            self.assertEqual(payload["status"], "prepared_not_observed")
            for unit in payload["units"]:
                self.assertEqual(unit["handoff"]["dispatch_policy"], "prepare_only")
            # Negative guards: freezing a contract is not dispatch and creates
            # no run records; unit evidence lands on runs the operator starts.
            for forbidden in ("worker_dispatch", "start_team", "start_swarm"):
                self.assertNotIn(forbidden, stdout)
            self.assertFalse((root / ".omh" / "runtime" / "runs").exists())
            self.assertNotIn('"executor_profile": "codex"', stdout)
            self.assertTrue((root / ".omh" / "coding" / "fanout" / payload["fanout_id"] / "fanout_contract.json").is_file())

    def test_fanout_validate_reports_errors_without_writing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "bad.json"
            bad.write_text(
                json.dumps(
                    [
                        {"unit_id": "a", "file_scope": ["src/f.py"]},
                        {"unit_id": "b", "file_scope": ["src/f.py"]},
                    ]
                ),
                encoding="utf-8",
            )
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, stdout, stderr = run_cli(base + ["coding", "fanout", "validate", "--units", str(bad)])

            self.assertEqual(status, 1)
            payload = json.loads(stdout)
            self.assertFalse(payload["ok"])
            self.assertIn("depends_on edge", payload["error"])
            self.assertFalse((root / ".omh" / "coding").exists())

    def test_fanout_show_projects_not_observed_units(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            status, stdout, _ = run_cli(
                base
                + ["coding", "fanout", "prepare", "--goal", "g", "--units", str(self._units_file(root)), "--record"]
            )
            self.assertEqual(status, 0)
            fanout_id = json.loads(stdout)["fanout_id"]

            status, stdout, stderr = run_cli(base + ["coding", "fanout", "show", fanout_id])

            self.assertEqual(status, 0, stderr)
            board = json.loads(stdout)
            self.assertEqual(board["schema_version"], "fanout_board/v1")
            self.assertEqual(board["merge_order"], ["core", "docs", "tests"])
            for unit in board["units"].values():
                self.assertEqual(unit["observed_run_status"], "not_observed")

    def test_fanout_single_unit_redirects_to_delegate(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            single = root / "single.json"
            single.write_text(json.dumps([_UNITS[0]]), encoding="utf-8")
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, stdout, stderr = run_cli(
                base + ["coding", "fanout", "prepare", "--goal", "g", "--units", str(single)]
            )

            self.assertEqual(status, 0, stderr)
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], "fanout_redirect/v1")
            self.assertEqual(payload["next_command"], "omh coding delegate")


if __name__ == "__main__":
    unittest.main()
