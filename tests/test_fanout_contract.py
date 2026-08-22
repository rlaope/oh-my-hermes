from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli  # noqa: E402

from omh.coding.executor_capability_snapshots import (  # noqa: E402
    build_executor_capability_snapshot,
    executor_capability_snapshot_path,
    write_executor_capability_snapshot,
)
from omh.coding.fanout import (  # noqa: E402
    build_fanout_contract,
    detect_boundary_overlaps,
    is_degenerate_single_unit,
    merge_order,
    missing_spawn_plan_fields,
    normalized_spawn_plan,
    require_spawn_plan,
    single_unit_redirect,
    spawn_plan_required,
)
from omh.coding.fanout_artifacts import read_fanout_contract, write_fanout_contract  # noqa: E402
from omh.coding.fanout_contracts import (  # noqa: E402
    FANOUT_CONTRACT_KEYS,
    FANOUT_CONTRACT_OPTIONAL_KEYS,
    FANOUT_SPAWN_PLAN_FIELDS,
    FANOUT_SPAWN_PLAN_THRESHOLD,
    FanoutContractError,
    MAX_SPAWN_PLAN_FIELD_CHARS,
    MAX_UNIT_VERIFICATION_COMMAND_CHARS,
    MAX_UNIT_VERIFICATION_COMMANDS,
    verification_command_argv,
)
from omh.system.paths import OmhPaths  # noqa: E402


_UNITS = [
    {"unit_id": "core", "title": "Refactor core", "owner": "codex", "file_scope": ["src/auth/"], "depends_on": []},
    {"unit_id": "tests", "title": "Add tests", "owner": "claude-code", "file_scope": ["tests/auth/"], "depends_on": ["core"]},
    {"unit_id": "docs", "title": "Update docs", "owner": None, "file_scope": ["docs/auth.md"], "depends_on": []},
]

_SPAWN_PLAN = {
    "why_parallel": "Five disjoint subsystems each own their own test lane.",
    "why_not_single_unit": "One executor would serialize five unrelated verification loops.",
    "independence": "No unit reads or writes another unit's file_scope.",
    "expected_evidence_shape": "Per-unit run record plus the unit's own focused test command.",
}


def _wide_units(count: int = FANOUT_SPAWN_PLAN_THRESHOLD + 1) -> list[dict[str, object]]:
    """A split one unit wider than the threshold, with disjoint boundaries."""
    return [
        {"unit_id": f"u{index}", "title": f"Unit {index}", "owner": None, "file_scope": [f"src/u{index}/"], "depends_on": []}
        for index in range(count)
    ]


class FanoutEngineTests(unittest.TestCase):
    def test_contract_is_deterministic_and_prepared_only(self) -> None:
        first = build_fanout_contract("refactor auth and cover it", _UNITS, source="discord")
        second = build_fanout_contract("refactor auth and cover it", _UNITS, source="discord")

        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], "fanout_contract/v2")
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

    def test_contract_freezes_the_live_safety_profile_revision(self) -> None:
        """The revision frozen at build time is the live one at build time.

        Without this the dispatch-boundary re-check has nothing to compare
        against and never fires on a contract produced today.
        """
        from omh.quality.safety_preflight import safety_profile_revision

        contract = build_fanout_contract("freeze the profile", _UNITS)

        self.assertEqual(contract["safety_profile_revision"], safety_profile_revision())
        self.assertEqual(contract["schema_version"], "fanout_contract/v2")
        self.assertEqual(contract, build_fanout_contract("freeze the profile", _UNITS))

    def test_a_contract_without_the_frozen_revision_still_round_trips(self) -> None:
        """Contracts frozen before the field keep their exact shape on disk."""
        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")
            contract = build_fanout_contract("older contract", _UNITS)
            contract["schema_version"] = "fanout_contract/v1"
            for unit in contract["units"]:
                unit["handoff"].pop("executor_capability_snapshot", None)
                unit["handoff"].pop("executor_capability_snapshot_policy", None)
            del contract["safety_profile_revision"]

            write_fanout_contract(paths, contract)

            stored = read_fanout_contract(paths, str(contract["fanout_id"]))
            self.assertNotIn("safety_profile_revision", stored)
            self.assertEqual(stored["schema_version"], "fanout_contract/v1")


class FanoutSpawnPlanTests(unittest.TestCase):
    """The gate that refuses a wide split nobody justified (#gajae spawn-gate)."""

    def test_a_split_at_or_below_the_threshold_needs_no_plan(self) -> None:
        for count in (2, FANOUT_SPAWN_PLAN_THRESHOLD):
            with self.subTest(count=count):
                self.assertFalse(spawn_plan_required(count))
                contract = build_fanout_contract("split work", _wide_units(count))
                self.assertNotIn("spawn_plan", contract)

    def test_a_split_needing_no_plan_gains_no_contract_key(self) -> None:
        # The gate is additive: the contract every existing caller freezes must
        # not gain a key, or every stored contract reads as drift. Key set is
        # the whole story because `atomic_write_json` sorts keys on the way out.
        contract = build_fanout_contract("refactor auth and cover it", _UNITS, source="discord")
        self.assertEqual(
            sorted(contract),
            sorted((*FANOUT_CONTRACT_KEYS, "safety_profile_revision")),
        )
        self.assertNotIn("spawn_plan", contract)

    def test_a_hollow_plan_is_refused_rather_than_frozen_as_a_receipt(self) -> None:
        # The regression that matters: a scaffolded-but-unfilled plan used to
        # be truthy, so it added a `spawn_plan` key full of empty strings to a
        # contract that had none -- drift AND a receipt asserting a
        # justification nobody wrote. Refusing keeps both from happening.
        for hollow in ({}, {"why_parallel": "four disjoint subsystems"}, {"independence": "   "}):
            with self.subTest(plan=hollow):
                with self.assertRaises(FanoutContractError) as caught:
                    build_fanout_contract("split work", _UNITS, spawn_plan=hollow)
                message = str(caught.exception)
                self.assertIn("incomplete", message)
                # It names the escape hatch, since below the threshold the
                # operator can simply drop the key.
                self.assertIn("remove the spawn_plan", message)

    def test_a_hollow_plan_above_the_threshold_reports_the_threshold_instead(self) -> None:
        with self.assertRaises(FanoutContractError) as caught:
            build_fanout_contract("split work five ways", _wide_units(), spawn_plan={})
        message = str(caught.exception)
        self.assertIn("threshold", message)
        # The plan IS present, so neither branch may tell the operator to add
        # one -- they are looking straight at it.
        self.assertNotIn("add a spawn_plan", message)
        self.assertIn("incomplete", message)
        # Above the threshold, deleting the key is not a remedy.
        self.assertNotIn("remove the spawn_plan", message)

    def test_a_structurally_invalid_wide_split_fails_on_structure_not_on_the_plan(self) -> None:
        # The gate must run LAST. Otherwise an operator writes four paragraphs
        # of justification for a decomposition that can never be frozen, and
        # only learns it is invalid on the next attempt.
        overlapping = [
            {"unit_id": f"u{i}", "file_scope": ["src/shared/"], "depends_on": []}
            for i in range(FANOUT_SPAWN_PLAN_THRESHOLD + 1)
        ]
        with self.assertRaises(FanoutContractError) as caught:
            build_fanout_contract("split work five ways", overlapping)
        self.assertIn("depends_on edge", str(caught.exception))
        self.assertNotIn("spawn-plan", str(caught.exception))

        cyclic = _wide_units()
        cyclic[0]["depends_on"] = [cyclic[1]["unit_id"]]
        cyclic[1]["depends_on"] = [cyclic[0]["unit_id"]]
        with self.assertRaises(FanoutContractError) as caught:
            build_fanout_contract("split work five ways", cyclic)
        self.assertIn("cycle", str(caught.exception))

    def test_a_wide_split_without_a_plan_is_rejected_by_name(self) -> None:
        units = _wide_units()
        self.assertTrue(spawn_plan_required(len(units)))

        with self.assertRaises(FanoutContractError) as caught:
            build_fanout_contract("split work five ways", units)

        message = str(caught.exception)
        self.assertIn(f"{len(units)}-unit split", message)
        self.assertIn(f"{FANOUT_SPAWN_PLAN_THRESHOLD}-unit spawn-plan threshold", message)
        for field in FANOUT_SPAWN_PLAN_FIELDS:
            self.assertIn(field, message)

    def test_a_wide_split_with_a_complete_plan_freezes_and_records_it(self) -> None:
        units = _wide_units()

        contract = build_fanout_contract("split work five ways", units, spawn_plan=_SPAWN_PLAN)

        plan = contract["spawn_plan"]
        self.assertEqual(plan["schema_version"], "fanout_spawn_plan/v1")
        self.assertEqual(plan["unit_count"], len(units))
        self.assertEqual(plan["threshold"], FANOUT_SPAWN_PLAN_THRESHOLD)
        self.assertEqual(plan["why_parallel"], _SPAWN_PLAN["why_parallel"])
        # A justification is not evidence, and the contract has to say so.
        self.assertIn("not evidence", plan["claim_boundary"])

    def test_an_incomplete_plan_names_only_the_fields_still_unanswered(self) -> None:
        units = _wide_units()
        partial = {**_SPAWN_PLAN, "independence": "   ", "expected_evidence_shape": ""}

        with self.assertRaises(FanoutContractError) as caught:
            build_fanout_contract("split work five ways", units, spawn_plan=partial)

        message = str(caught.exception)
        self.assertIn("independence", message)
        self.assertIn("expected_evidence_shape", message)
        self.assertNotIn("why_parallel", message)
        self.assertNotIn("why_not_single_unit", message)

    def test_a_non_string_answer_is_refused_rather_than_frozen_as_its_repr(self) -> None:
        # `str(value)` would accept any of these and freeze a Python repr into
        # a JSON contract -- "['a', 'b']", "True" -- passing the blank check
        # while being exactly the answer-nobody-wrote the gate refuses.
        for value in ([ "a", "b" ], 1, True, {"cmd": "pytest"}, 4000.0):
            with self.subTest(value=value):
                with self.assertRaises(FanoutContractError) as caught:
                    normalized_spawn_plan({**_SPAWN_PLAN, "why_parallel": value})
                self.assertIn("must be a string", str(caught.exception))

        # None reads as unsupplied, not as a shape error.
        self.assertEqual(
            missing_spawn_plan_fields(normalized_spawn_plan({**_SPAWN_PLAN, "independence": None})),
            ["independence"],
        )
        self.assertEqual(missing_spawn_plan_fields(_SPAWN_PLAN), [])

    def test_plan_fields_are_bounded_and_collapsed(self) -> None:
        collapsed = normalized_spawn_plan({**_SPAWN_PLAN, "why_parallel": "  two   lines\n  here  "})
        self.assertEqual(collapsed["why_parallel"], "two lines here")

        with self.assertRaises(FanoutContractError) as caught:
            normalized_spawn_plan({**_SPAWN_PLAN, "independence": "x" * (MAX_SPAWN_PLAN_FIELD_CHARS + 1)})
        self.assertIn(str(MAX_SPAWN_PLAN_FIELD_CHARS), str(caught.exception))

    def test_a_non_object_plan_is_a_shape_error_not_a_missing_field_list(self) -> None:
        with self.assertRaises(FanoutContractError) as caught:
            normalized_spawn_plan(["why_parallel"])
        self.assertIn("must be an object", str(caught.exception))

    def test_a_complete_plan_supplied_under_the_threshold_is_kept_rather_than_dropped(self) -> None:
        contract = build_fanout_contract("split work", _UNITS, spawn_plan=_SPAWN_PLAN)

        self.assertEqual(contract["spawn_plan"]["unit_count"], len(_UNITS))
        self.assertEqual(contract["spawn_plan"]["why_parallel"], _SPAWN_PLAN["why_parallel"])
        self.assertEqual(sorted(contract), sorted((*FANOUT_CONTRACT_KEYS, *FANOUT_CONTRACT_OPTIONAL_KEYS)))

    def test_the_operator_cannot_overwrite_the_contract_side_plan_fields(self) -> None:
        # `**accepted_spawn_plan` splats into the contract, so the normalizer
        # must build a fresh dict from the declared fields rather than copying
        # whatever the operator sent.
        contract = build_fanout_contract(
            "split work",
            _UNITS,
            spawn_plan={**_SPAWN_PLAN, "schema_version": "attacker/v9", "threshold": 999, "unit_count": 1},
        )

        plan = contract["spawn_plan"]
        self.assertEqual(plan["schema_version"], "fanout_spawn_plan/v1")
        self.assertEqual(plan["threshold"], FANOUT_SPAWN_PLAN_THRESHOLD)
        self.assertEqual(plan["unit_count"], len(_UNITS))

    def test_the_gate_stays_deterministic(self) -> None:
        units = _wide_units()
        first = build_fanout_contract("split work five ways", units, spawn_plan=_SPAWN_PLAN)
        second = build_fanout_contract("split work five ways", units, spawn_plan=_SPAWN_PLAN)

        self.assertEqual(first, second)

    def test_require_spawn_plan_returns_none_when_nothing_was_supplied(self) -> None:
        self.assertIsNone(require_spawn_plan(FANOUT_SPAWN_PLAN_THRESHOLD, None))


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
    def test_prepare_freezes_recorded_and_prepared_owner_snapshots(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            recorded = build_executor_capability_snapshot(
                executor="codex",
                capabilities={
                    "edit_format_patch": {
                        "status": "host_observed",
                        "scope": {"surface": "local_cli"},
                        "evidence_ref": "probe:patch-edit",
                        "observed_at": "2026-08-13T12:00:00Z",
                    }
                },
                recorded_at="2026-08-13T12:01:00Z",
            )
            write_executor_capability_snapshot(
                executor_capability_snapshot_path(
                    omh_home / "coding" / "executor-capability-snapshots",
                    "codex",
                ),
                recorded,
            )
            units_path = root / "units.json"
            units_path.write_text(
                json.dumps(
                    [
                        {
                            "unit_id": "code",
                            "title": "Code",
                            "owner": "codex",
                            "file_scope": ["src/"],
                        },
                        {
                            "unit_id": "docs",
                            "title": "Docs",
                            "owner": "claude-code",
                            "file_scope": ["docs/"],
                        },
                    ]
                ),
                encoding="utf-8",
            )

            code, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "--hermes-home",
                    str(root / ".hermes"),
                    "coding",
                    "fanout",
                    "prepare",
                    "--goal",
                    "split",
                    "work",
                    "--units",
                    str(units_path),
                ]
            )

        self.assertEqual(code, 0, stderr)
        contract = json.loads(stdout)
        by_unit = {str(unit["unit_id"]): unit for unit in contract["units"]}
        code_snapshot = by_unit["code"]["handoff"]["executor_capability_snapshot"]
        docs_snapshot = by_unit["docs"]["handoff"]["executor_capability_snapshot"]
        self.assertEqual(code_snapshot["recorded_at"], recorded["recorded_at"])
        self.assertEqual(
            code_snapshot["capabilities"]["edit_format_patch"],
            recorded["capabilities"]["edit_format_patch"],
        )
        self.assertEqual(
            docs_snapshot["capabilities"]["worktree_isolation"]["status"],
            "prepared",
        )

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
            self.assertEqual(payload["schema_version"], "fanout_contract/v2")
            self.assertEqual(payload["status"], "prepared_not_observed")
            for unit in payload["units"]:
                self.assertEqual(unit["handoff"]["dispatch_policy"], "prepare_only")
                if unit["owner"] is not None:
                    self.assertEqual(
                        unit["handoff"]["executor_capability_snapshot_policy"],
                        "frozen_required",
                    )
            # Negative guards: freezing a contract is not dispatch and creates
            # no run records; unit evidence lands on runs the operator starts.
            for forbidden in ("worker_dispatch", "start_team", "start_swarm"):
                self.assertNotIn(forbidden, stdout)
            self.assertFalse((root / ".omh" / "runtime" / "runs").exists())
            self.assertNotIn('"executor_profile": "codex"', stdout)
            self.assertTrue((root / ".omh" / "coding" / "fanout" / payload["fanout_id"] / "fanout_contract.json").is_file())

    def test_fanout_brief_omits_non_scalar_model_route_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = [
                "--omh-home",
                str(root / ".omh"),
                "--hermes-home",
                str(root / ".hermes"),
            ]
            status, stdout, stderr = run_cli(
                base
                + [
                    "coding",
                    "fanout",
                    "prepare",
                    "--goal",
                    "split",
                    "work",
                    "--units",
                    str(self._units_file(root)),
                    "--record",
                ]
            )
            self.assertEqual(status, 0, stderr)
            fanout_id = json.loads(stdout)["fanout_id"]
            contract_path = (
                root
                / ".omh"
                / "coding"
                / "fanout"
                / fanout_id
                / "fanout_contract.json"
            )
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["units"][0]["handoff"]["model_route"] = {
                "schema_version": "coding_model_route/v2",
                "selected_model": {"INVALID_DICT_SENTINEL": "secret"},
                "selected_reasoning_effort": ["xhigh"],
                "chain": [],
            }
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            status, stdout, stderr = run_cli(
                base + ["coding", "fanout", "brief", fanout_id, "--json"]
            )

        self.assertEqual(status, 0, stderr)
        self.assertNotIn("INVALID_DICT_SENTINEL", stdout)
        unit = json.loads(stdout)["units"][0]
        self.assertEqual(unit["model"], "executor_default")
        self.assertEqual(unit["reasoning_effort"], "")

    def test_fanout_dispatch_refuses_invalid_evidence_before_git_resolution(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = [
                "--omh-home",
                str(root / ".omh"),
                "--hermes-home",
                str(root / ".hermes"),
            ]
            status, stdout, stderr = run_cli(
                base
                + [
                    "coding",
                    "fanout",
                    "prepare",
                    "--goal",
                    "split",
                    "work",
                    "--units",
                    str(self._units_file(root)),
                    "--record",
                ]
            )
            self.assertEqual(status, 0, stderr)
            fanout_id = json.loads(stdout)["fanout_id"]
            contract_path = (
                root
                / ".omh"
                / "coding"
                / "fanout"
                / fanout_id
                / "fanout_contract.json"
            )
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["units"][0]["handoff"]["executor_capability_snapshot"] = "invalid"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            goal = root / "goal.txt"
            goal.write_text("split work", encoding="utf-8")

            with mock.patch(
                "subprocess.run",
                side_effect=AssertionError("git resolution ran"),
            ):
                status, stdout, stderr = run_cli(
                    base
                    + [
                        "coding",
                        "fanout",
                        "dispatch",
                        fanout_id,
                        "--goal-file",
                        str(goal),
                        "--repo-root",
                        str(root),
                    ]
                )

        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("provenance digest does not match", stderr)

    def test_recorded_v2_cannot_be_relabelled_as_legacy(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = [
                "--omh-home",
                str(root / ".omh"),
                "--hermes-home",
                str(root / ".hermes"),
            ]
            status, stdout, stderr = run_cli(
                base
                + [
                    "coding",
                    "fanout",
                    "prepare",
                    "--goal",
                    "split",
                    "work",
                    "--units",
                    str(self._units_file(root)),
                    "--record",
                ]
            )
            self.assertEqual(status, 0, stderr)
            fanout_id = json.loads(stdout)["fanout_id"]
            contract_path = (
                root / ".omh" / "coding" / "fanout" / fanout_id / "fanout_contract.json"
            )
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["schema_version"] = "fanout_contract/v1"
            for unit in contract["units"]:
                unit["handoff"].pop("executor_capability_snapshot", None)
                unit["handoff"].pop("executor_capability_snapshot_policy", None)
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            goal = root / "goal.txt"
            goal.write_text("split work", encoding="utf-8")

            with mock.patch(
                "subprocess.run",
                side_effect=AssertionError("git resolution ran"),
            ):
                status, stdout, stderr = run_cli(
                    base
                    + [
                        "coding",
                        "fanout",
                        "dispatch",
                        fanout_id,
                        "--goal-file",
                        str(goal),
                        "--repo-root",
                        str(root),
                    ]
                )

        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("schema provenance", stderr)

    def test_legacy_contract_requires_migration_before_dispatch(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            contract = build_fanout_contract("split work", _UNITS)
            contract["schema_version"] = "fanout_contract/v1"
            for unit in contract["units"]:
                unit["handoff"].pop("executor_capability_snapshot", None)
                unit["handoff"].pop("executor_capability_snapshot_policy", None)
            recorded = write_fanout_contract(paths, contract)
            fanout_id = str(recorded["fanout_id"])
            (
                paths.fanout_contracts_dir
                / fanout_id
                / "contract_provenance.json"
            ).unlink()
            base = [
                "--omh-home",
                str(paths.omh_home),
                "--hermes-home",
                str(paths.hermes_home),
            ]

            status, stdout, stderr = run_cli(
                base + ["coding", "fanout", "migrate-legacy", fanout_id]
            )
            self.assertEqual(status, 0, stderr)
            preview = json.loads(stdout)
            self.assertEqual(preview["status"], "confirmation_required")
            status, stdout, stderr = run_cli(
                base
                + [
                    "coding",
                    "fanout",
                    "migrate-legacy",
                    fanout_id,
                    "--confirm-contract-sha256",
                    preview["contract_sha256"],
                ]
            )
            self.assertEqual(status, 0, stderr)
            migrated = json.loads(stdout)
            self.assertEqual(migrated["schema_version"], "fanout_contract/v2")
            for unit in migrated["units"]:
                if unit["owner"] is not None:
                    self.assertEqual(
                        unit["handoff"]["executor_capability_snapshot_policy"],
                        "frozen_required",
                    )

            status, stdout, stderr = run_cli(
                base + ["coding", "fanout", "migrate-legacy", fanout_id]
            )
            self.assertEqual(status, 2)
            self.assertEqual(stdout, "")
            self.assertIn("already uses fanout_contract/v2", stderr)

    def test_legacy_migration_refuses_drifted_existing_provenance(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            contract = build_fanout_contract("split work", _UNITS)
            contract["schema_version"] = "fanout_contract/v1"
            for unit in contract["units"]:
                unit["handoff"].pop("executor_capability_snapshot", None)
                unit["handoff"].pop("executor_capability_snapshot_policy", None)
            recorded = write_fanout_contract(paths, contract)
            contract_path = Path(recorded["artifacts"]["contract_path"])
            tampered = json.loads(contract_path.read_text(encoding="utf-8"))
            tampered["units"][0]["boundary"]["file_scope"] = ["tampered/"]
            contract_path.write_text(json.dumps(tampered), encoding="utf-8")

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(paths.omh_home),
                    "--hermes-home",
                    str(paths.hermes_home),
                    "coding",
                    "fanout",
                    "migrate-legacy",
                    str(recorded["fanout_id"]),
                ]
            )

        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("provenance is invalid", stderr)

    def test_legacy_migration_normalizes_unsafe_owner_errors(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            contract = build_fanout_contract("split work", _UNITS)
            contract["schema_version"] = "fanout_contract/v1"
            contract["units"][0]["owner"] = "x" * 100_000
            contract["units"][0]["handoff"]["executor_target"] = "x" * 100_000
            for unit in contract["units"]:
                unit["handoff"].pop("executor_capability_snapshot", None)
                unit["handoff"].pop("executor_capability_snapshot_policy", None)
            recorded = write_fanout_contract(paths, contract)
            provenance_path = (
                paths.fanout_contracts_dir
                / str(recorded["fanout_id"])
                / "contract_provenance.json"
            )
            provenance_path.unlink()

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(paths.omh_home),
                    "--hermes-home",
                    str(paths.hermes_home),
                    "coding",
                    "fanout",
                    "migrate-legacy",
                    str(recorded["fanout_id"]),
                ]
            )
            digest = json.loads(stdout)["contract_sha256"]
            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(paths.omh_home),
                    "--hermes-home",
                    str(paths.hermes_home),
                    "coding",
                    "fanout",
                    "migrate-legacy",
                    str(recorded["fanout_id"]),
                    "--confirm-contract-sha256",
                    digest,
                ]
            )

        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertNotIn("Traceback", stderr)
        self.assertLess(len(stderr), 500)

    def test_legacy_migration_rejects_invalid_unit_container_cleanly(self) -> None:
        for units in (None, 7):
            with self.subTest(units=units), TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
                contract = build_fanout_contract("split work", _UNITS)
                contract["schema_version"] = "fanout_contract/v1"
                contract["units"] = units
                recorded = write_fanout_contract(paths, contract)

                status, stdout, stderr = run_cli(
                    [
                        "--omh-home",
                        str(paths.omh_home),
                        "--hermes-home",
                        str(paths.hermes_home),
                        "coding",
                        "fanout",
                        "migrate-legacy",
                        str(recorded["fanout_id"]),
                    ]
                )

            self.assertEqual(status, 2)
            self.assertEqual(stdout, "")
            self.assertNotIn("Traceback", stderr)
            self.assertLess(len(stderr), 500)

    def test_legacy_migration_rejects_malformed_unit_objects_before_write(self) -> None:
        mutations = (
            lambda units: units.__setitem__(0, {}),
            lambda units: units[0].__setitem__("handoff", None),
            lambda units: units[0].__setitem__("handoff", "invalid"),
            lambda units: units[0]["boundary"].__setitem__(
                "file_scope",
                [{"not": "a string"}],
            ),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate), TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
                contract = build_fanout_contract("split work", _UNITS)
                contract["schema_version"] = "fanout_contract/v1"
                mutate(contract["units"])
                recorded = write_fanout_contract(paths, contract)

                status, stdout, stderr = run_cli(
                    [
                        "--omh-home",
                        str(paths.omh_home),
                        "--hermes-home",
                        str(paths.hermes_home),
                        "coding",
                        "fanout",
                        "migrate-legacy",
                        str(recorded["fanout_id"]),
                    ]
                )

                persisted = read_fanout_contract(paths, str(recorded["fanout_id"]))

            self.assertEqual(status, 2)
            self.assertEqual(stdout, "")
            self.assertNotIn("Traceback", stderr)
            self.assertEqual(persisted["schema_version"], "fanout_contract/v1")

    def test_goal_mismatch_refuses_before_git_resolution(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = [
                "--omh-home",
                str(root / ".omh"),
                "--hermes-home",
                str(root / ".hermes"),
            ]
            status, stdout, stderr = run_cli(
                base
                + [
                    "coding",
                    "fanout",
                    "prepare",
                    "--goal",
                    "split",
                    "work",
                    "--units",
                    str(self._units_file(root)),
                    "--record",
                ]
            )
            self.assertEqual(status, 0, stderr)
            fanout_id = json.loads(stdout)["fanout_id"]
            goal = root / "goal.txt"
            goal.write_text("different goal", encoding="utf-8")

            with mock.patch(
                "subprocess.run",
                side_effect=AssertionError("git resolution ran"),
            ):
                status, stdout, stderr = run_cli(
                    base
                    + [
                        "coding",
                        "fanout",
                        "dispatch",
                        fanout_id,
                        "--goal-file",
                        str(goal),
                        "--repo-root",
                        str(root),
                    ]
                )

        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("goal text does not match", stderr)

    def test_fanout_brief_bounds_invalid_owner_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = [
                "--omh-home",
                str(root / ".omh"),
                "--hermes-home",
                str(root / ".hermes"),
            ]
            status, stdout, stderr = run_cli(
                base
                + [
                    "coding",
                    "fanout",
                    "prepare",
                    "--goal",
                    "split",
                    "work",
                    "--units",
                    str(self._units_file(root)),
                    "--record",
                ]
            )
            self.assertEqual(status, 0, stderr)
            fanout_id = json.loads(stdout)["fanout_id"]
            contract_path = (
                root / ".omh" / "coding" / "fanout" / fanout_id / "fanout_contract.json"
            )
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["units"][0]["owner"] = "x" * 100_000
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            status, stdout, stderr = run_cli(
                base + ["coding", "fanout", "brief", fanout_id, "--json"]
            )

        self.assertEqual(status, 0, stderr)
        self.assertLess(len(stdout), 10_000)
        self.assertEqual(json.loads(stdout)["units"][0]["owner"], "choose")

    def test_fanout_brief_bounds_oversized_model_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = [
                "--omh-home",
                str(root / ".omh"),
                "--hermes-home",
                str(root / ".hermes"),
            ]
            status, stdout, stderr = run_cli(
                base
                + [
                    "coding",
                    "fanout",
                    "prepare",
                    "--goal",
                    "split",
                    "work",
                    "--units",
                    str(self._units_file(root)),
                    "--record",
                ]
            )
            self.assertEqual(status, 0, stderr)
            fanout_id = json.loads(stdout)["fanout_id"]
            contract_path = (
                root / ".omh" / "coding" / "fanout" / fanout_id / "fanout_contract.json"
            )
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            oversized = "SENTINEL-" + ("x" * 100_000)
            contract["units"][0]["handoff"]["model_route"] = {
                "schema_version": oversized,
                "selected_model": oversized,
                "selected_reasoning_effort": oversized,
                "chain": [{}, {"model_id": oversized}],
            }
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            status, stdout, stderr = run_cli(
                base + ["coding", "fanout", "brief", fanout_id, "--json"]
            )

        self.assertEqual(status, 0, stderr)
        self.assertLess(len(stdout), 10_000)
        unit = json.loads(stdout)["units"][0]
        for field in (
            "model",
            "model_label",
            "model_alternative",
            "reasoning_effort",
            "route_schema_version",
        ):
            self.assertLessEqual(len(unit[field]), 200)

    def test_fanout_dispatch_rejects_open_provenance_schema(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = [
                "--omh-home",
                str(root / ".omh"),
                "--hermes-home",
                str(root / ".hermes"),
            ]
            status, stdout, stderr = run_cli(
                base
                + [
                    "coding",
                    "fanout",
                    "prepare",
                    "--goal",
                    "split",
                    "work",
                    "--units",
                    str(self._units_file(root)),
                    "--record",
                ]
            )
            self.assertEqual(status, 0, stderr)
            fanout_id = json.loads(stdout)["fanout_id"]
            provenance_path = (
                root / ".omh" / "coding" / "fanout" / fanout_id / "contract_provenance.json"
            )
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance["unexpected"] = {"nested": "value"}
            provenance["privacy"] = "public"
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
            goal = root / "goal.txt"
            goal.write_text("split work", encoding="utf-8")

            with mock.patch(
                "subprocess.run",
                side_effect=AssertionError("git resolution ran"),
            ):
                status, stdout, stderr = run_cli(
                    base
                    + [
                        "coding",
                        "fanout",
                        "dispatch",
                        fanout_id,
                        "--goal-file",
                        str(goal),
                        "--repo-root",
                        str(root),
                    ]
                )

        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("provenance", stderr)

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

    def test_fanout_prepare_refuses_a_wide_split_without_a_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            wide = root / "wide.json"
            wide.write_text(json.dumps(_wide_units()), encoding="utf-8")
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, stdout, stderr = run_cli(
                base
                + ["coding", "fanout", "prepare", "--goal", "split", "five", "ways", "--units", str(wide), "--record"]
            )

            # `prepare` reports contract errors the way every other one is
            # reported: OmhError to stderr, exit 2. `validate` is the surface
            # that answers with a JSON verdict and exit 1.
            self.assertEqual(status, 2)
            self.assertIn("spawn-plan threshold", stderr)
            # A refused freeze writes nothing.
            self.assertFalse((root / ".omh" / "coding").exists())

    def test_fanout_prepare_accepts_a_plan_carried_in_the_units_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            wide = root / "wide.json"
            wide.write_text(
                json.dumps({"units": _wide_units(), "spawn_plan": _SPAWN_PLAN}),
                encoding="utf-8",
            )
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, stdout, stderr = run_cli(
                base
                + ["coding", "fanout", "prepare", "--goal", "split", "five", "ways", "--units", str(wide), "--record"]
            )

            self.assertEqual(status, 0, stderr)
            payload = json.loads(stdout)
            self.assertEqual(payload["spawn_plan"]["unit_count"], FANOUT_SPAWN_PLAN_THRESHOLD + 1)
            stored = read_fanout_contract(
                OmhPaths(root / ".omh", root / ".hermes"), payload["fanout_id"]
            )
            self.assertEqual(stored["spawn_plan"], payload["spawn_plan"])

    def test_a_malformed_plan_reaches_the_operator_as_a_shape_error(self) -> None:
        # Coercing a non-object to None at the CLI boundary made "wrong shape"
        # indistinguishable from "nothing sent": under the threshold the plan
        # vanished silently, and over it the operator was told to add a plan
        # they had already added.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            for name, units in (("narrow", _UNITS), ("wide", _wide_units())):
                path = root / f"{name}.json"
                path.write_text(
                    json.dumps({"units": units, "spawn_plan": "why_parallel: disjoint subsystems"}),
                    encoding="utf-8",
                )
                with self.subTest(payload=name):
                    status, _, stderr = run_cli(
                        base + ["coding", "fanout", "prepare", "--goal", "split", "it", "--units", str(path)]
                    )
                    self.assertEqual(status, 2)
                    self.assertIn("spawn_plan must be an object", stderr)

                    status, stdout, _ = run_cli(base + ["coding", "fanout", "validate", "--units", str(path)])
                    self.assertEqual(status, 1)
                    self.assertIn("spawn_plan must be an object", json.loads(stdout)["error"])

    def test_validate_answers_with_json_even_when_a_unit_is_not_an_object(self) -> None:
        # `_normalized_unit` used to run outside the try, so this escaped as a
        # traceback with an empty stdout while still exiting 1 -- the same code
        # as the documented invalid-payload path, so a wrapper parsed "".
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "bad.json"
            bad.write_text(json.dumps({"units": ["oops", "also-oops"]}), encoding="utf-8")
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, stdout, _ = run_cli(base + ["coding", "fanout", "validate", "--units", str(bad)])

            self.assertEqual(status, 1)
            payload = json.loads(stdout)
            self.assertFalse(payload["ok"])
            self.assertIn("must be an object", payload["error"])
            # The contract this command advertises: both keys on every path.
            self.assertEqual(payload["unit_count"], 2)
            self.assertFalse(payload["spawn_plan_required"])

    def test_a_misspelled_spawn_plan_key_is_named_rather_than_dropped(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            for spelling in ("spawnPlan", "spawn-plan", "SPAWN_PLAN"):
                path = root / f"{spelling}.json"
                path.write_text(json.dumps({"units": _UNITS, spelling: _SPAWN_PLAN}), encoding="utf-8")
                with self.subTest(spelling=spelling):
                    status, _, stderr = run_cli(
                        base + ["coding", "fanout", "prepare", "--goal", "split", "it", "--units", str(path)]
                    )
                    self.assertEqual(status, 2)
                    self.assertIn(spelling, stderr)
                    self.assertIn("did you mean", stderr)

    def test_fanout_validate_reports_the_requirement_before_prepare_refuses(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            narrow = root / "narrow.json"
            narrow.write_text(json.dumps(_UNITS), encoding="utf-8")
            status, stdout, stderr = run_cli(base + ["coding", "fanout", "validate", "--units", str(narrow)])
            self.assertEqual(status, 0, stderr)
            self.assertFalse(json.loads(stdout)["spawn_plan_required"])

            wide = root / "wide.json"
            wide.write_text(json.dumps(_wide_units()), encoding="utf-8")
            status, stdout, _ = run_cli(base + ["coding", "fanout", "validate", "--units", str(wide)])
            self.assertEqual(status, 1)
            refused = json.loads(stdout)
            self.assertIn("spawn-plan threshold", refused["error"])
            # The refusal is exactly when a wrapper needs to know a plan is
            # wanted, so the flag rides the error payload too.
            self.assertTrue(refused["spawn_plan_required"])
            self.assertEqual(refused["unit_count"], FANOUT_SPAWN_PLAN_THRESHOLD + 1)

            planned = root / "planned.json"
            planned.write_text(json.dumps({"units": _wide_units(), "spawn_plan": _SPAWN_PLAN}), encoding="utf-8")
            status, stdout, stderr = run_cli(base + ["coding", "fanout", "validate", "--units", str(planned)])
            self.assertEqual(status, 0, stderr)
            self.assertTrue(json.loads(stdout)["spawn_plan_required"])

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
            self.assertEqual(board["context_budget"]["history_limit"], 20)
            self.assertEqual(board["context_budget"]["watched_run_count"], 0)
            self.assertEqual(board["context_budget"]["budget_exhausted_units"], [])
            self.assertEqual(board["context_budget"]["next_action"], "wait_for_executor_evidence")

    def test_fanout_show_history_limit_is_bounded_and_validated(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            status, stdout, _ = run_cli(
                base
                + ["coding", "fanout", "prepare", "--goal", "g", "--units", str(self._units_file(root)), "--record"]
            )
            self.assertEqual(status, 0)
            fanout_id = json.loads(stdout)["fanout_id"]

            status, stdout, stderr = run_cli(base + ["coding", "fanout", "show", fanout_id, "--full"])
            self.assertEqual(status, 0, stderr)
            self.assertIsNone(json.loads(stdout)["context_budget"]["history_limit"])

            status, stdout, stderr = run_cli(base + ["coding", "fanout", "show", fanout_id, "--limit", "5"])
            self.assertEqual(status, 0, stderr)
            self.assertEqual(json.loads(stdout)["context_budget"]["history_limit"], 5)

            status, _, stderr = run_cli(base + ["coding", "fanout", "show", fanout_id, "--limit", "0"])
            self.assertEqual(status, 2)
            self.assertIn("--limit must be at least 1", stderr)

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

    def test_fanout_prepare_normalizes_an_unsafe_owner_error(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            units = root / "unsafe.json"
            units.write_text(
                json.dumps(
                    [
                        {"unit_id": "core", "owner": "../codex", "file_scope": ["src/"]},
                        {"unit_id": "tests", "owner": "codex", "file_scope": ["tests/"]},
                    ]
                ),
                encoding="utf-8",
            )

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(root / ".omh"),
                    "--hermes-home",
                    str(root / ".hermes"),
                    "coding",
                    "fanout",
                    "prepare",
                    "--goal",
                    "split",
                    "work",
                    "--units",
                    str(units),
                ]
            )

        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("safe snapshot filename", stderr)
        self.assertNotIn("Traceback", stderr)


class FanoutVerificationCommandTests(unittest.TestCase):
    def _with_commands(self, commands: object) -> list[dict[str, object]]:
        units = [dict(unit) for unit in _UNITS]
        units[0]["verification_commands"] = commands
        return units

    def test_absent_field_leaves_the_contract_byte_identical(self) -> None:
        without = build_fanout_contract("split work", _UNITS)
        declared_empty = build_fanout_contract("split work", self._with_commands([]))

        self.assertEqual(without, declared_empty)
        for unit in without["units"]:
            self.assertNotIn("verification_commands", unit)
            # The prose checks are untouched by the new field either way.
            self.assertEqual(
                unit["integration_checks"],
                [
                    "unit tests covering the unit's file_scope pass",
                    "no edits outside boundary.file_scope",
                ],
            )

    def test_declared_commands_are_normalized_onto_the_owning_unit_only(self) -> None:
        contract = build_fanout_contract(
            "split work",
            self._with_commands(["  python  -m   unittest  ", "python -c 'print(1)'"]),
        )
        units = {unit["unit_id"]: unit for unit in contract["units"]}

        self.assertEqual(
            units["core"]["verification_commands"],
            ["python -m unittest", "python -c 'print(1)'"],
        )
        self.assertNotIn("verification_commands", units["tests"])
        self.assertNotIn("verification_commands", units["docs"])

    def test_blank_entry_is_refused_rather_than_dropped(self) -> None:
        for bad in ([""], ["   "], ["python -m unittest", ""], [None], [42]):
            with self.subTest(commands=bad):
                with self.assertRaises(FanoutContractError) as raised:
                    build_fanout_contract("split work", self._with_commands(bad))
                self.assertIn("verification_commands entries must be non-empty", str(raised.exception))

    def test_non_list_payload_is_refused(self) -> None:
        with self.assertRaises(FanoutContractError) as raised:
            build_fanout_contract("split work", self._with_commands("python -m unittest"))
        self.assertIn("must be a list of command strings", str(raised.exception))

    def test_count_and_length_caps_are_enforced(self) -> None:
        too_many = [f"python -c 'print({index})'" for index in range(MAX_UNIT_VERIFICATION_COMMANDS + 1)]
        with self.assertRaises(FanoutContractError) as raised:
            build_fanout_contract("split work", self._with_commands(too_many))
        self.assertIn(f"at most {MAX_UNIT_VERIFICATION_COMMANDS} commands", str(raised.exception))

        too_long = ["python -c " + "a" * MAX_UNIT_VERIFICATION_COMMAND_CHARS]
        with self.assertRaises(FanoutContractError) as raised:
            build_fanout_contract("split work", self._with_commands(too_long))
        self.assertIn(f"at most {MAX_UNIT_VERIFICATION_COMMAND_CHARS} chars", str(raised.exception))

        at_cap = [f"python -c 'print({index})'" for index in range(MAX_UNIT_VERIFICATION_COMMANDS)]
        contract = build_fanout_contract("split work", self._with_commands(at_cap))
        units = {unit["unit_id"]: unit for unit in contract["units"]}
        self.assertEqual(len(units["core"]["verification_commands"]), MAX_UNIT_VERIFICATION_COMMANDS)

    def test_unrunnable_command_is_refused_at_freeze_time(self) -> None:
        for bad in ("python -c 'unbalanced", "PYTHONPATH=tests"):
            with self.subTest(command=bad):
                with self.assertRaises(FanoutContractError):
                    build_fanout_contract("split work", self._with_commands([bad]))

    def test_command_split_keeps_leading_env_assignments_out_of_the_argv(self) -> None:
        env, argv = verification_command_argv("PYTHONPATH=tests uv run python -m unittest")

        self.assertEqual(env, {"PYTHONPATH": "tests"})
        self.assertEqual(argv, ["uv", "run", "python", "-m", "unittest"])

        env, argv = verification_command_argv("python -c 'print(1)'")
        self.assertEqual(env, {})
        self.assertEqual(argv, ["python", "-c", "print(1)"])

        # No shell runs these, so a pipe is an argument rather than an operator.
        _env, argv = verification_command_argv("python -c 'print(1)' | tee log")
        self.assertEqual(argv, ["python", "-c", "print(1)", "|", "tee", "log"])


if __name__ == "__main__":
    unittest.main()
