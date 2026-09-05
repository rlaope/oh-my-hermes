"""Tests for the executor-neutral verification plan, receipt, and single-flight machinery.

Issue #1292: verification becomes a revision-bound plan of typed check nodes
whose immutable receipts are shared across consumers, with read-only checks
dispatching as a bounded parallel wave and stateful checks serializing. Every
concurrency assertion below subscribes to a `threading.Event` before
triggering the action and awaits it with a bounded timeout — no sleeps.
"""

from __future__ import annotations

import dataclasses
import json
import os
import threading
import subprocess
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from omh.coding.verification_plan import (  # noqa: E402
    VERIFICATION_PLAN_SCHEMA_VERSION,
    compile_verification_plan,
    receipt_key,
    toolchain_digest,
    verification_execution_environment,
)
from omh.coding.verification_receipts import (  # noqa: E402
    VERIFICATION_RECEIPT_SCHEMA_VERSION,
    SingleFlight,
    load_receipt,
    receipt_file_lock,
    receipt_path,
    receipts_dir,
    store_receipt,
)
from omh.coding.fanout_dispatch import _verification_worktree_revision  # noqa: E402
from omh.coding.verification_execution import VerificationExecutionGate  # noqa: E402
from omh.coding.verification_integration import run_post_integration_verification  # noqa: E402
from omh.coding.verification_runner import (  # noqa: E402
    PlanRunContext,
    PlanRunResult,
    run_verification_plan,
)
from omh.system.paths import OmhPaths  # noqa: E402

_FANOUT_ID = "fanout-abcdef123456"
_UNIT_ID = "core"

_A = "python3 -m unittest tests.test_a"
_B = "python3 -m unittest tests.test_b"
_C = "python3 -m unittest tests.test_c"

_SECRET_OUTPUT = "s3cret-output-that-must-never-reach-a-receipt"
_SECRET_ENV = "s3cret-env-value-that-must-never-reach-a-receipt"


def _unit(commands: list[str], checks: list[dict[str, object]] | None = None) -> dict[str, object]:
    unit: dict[str, object] = {"verification_commands": list(commands)}
    if checks is not None:
        unit["verification_checks"] = checks
    return unit


def _compile(unit: dict[str, object]):
    plan = compile_verification_plan(unit, fanout_id=_FANOUT_ID, unit_id=_UNIT_ID)
    assert plan is not None
    return plan


def _context(
    paths: OmhPaths,
    worktree: Path,
    *,
    revision: str | None = "rev1",
    max_workers: int = 4,
    integration_ready=lambda: False,
    single_flight: SingleFlight | None = None,
) -> PlanRunContext:
    return PlanRunContext(
        paths=paths,
        worktree=worktree,
        revision=revision,
        max_workers=max_workers,
        integration_ready=integration_ready,
        single_flight=single_flight if single_flight is not None else SingleFlight(),
    )


def _passing(node):
    return ("passed", "", None)


class VerificationPlanCompilationTests(unittest.TestCase):
    def test_a_metadata_free_unit_compiles_to_a_serial_stateful_plan(self) -> None:
        # Given a unit declaring bare commands and no per-check metadata
        plan = _compile(_unit([_A, _B]))

        # When the plan is compiled, Then every node defaults to a serial,
        # stateful, unit-tier check with no edges and the default claim scope.
        self.assertEqual(plan.schema_version, VERIFICATION_PLAN_SCHEMA_VERSION)
        self.assertEqual(plan.fanout_id, _FANOUT_ID)
        self.assertEqual(plan.unit_id, _UNIT_ID)
        self.assertEqual(len(plan.nodes), 2)
        for node in plan.nodes:
            self.assertEqual(node.tier, "unit")
            self.assertEqual(node.safety, "stateful")
            self.assertEqual(node.depends_on, ())
            self.assertEqual(node.claim_scope, "unit_verification")
            self.assertGreater(node.timeout, 0)
        self.assertTrue(plan.is_serial)
        self.assertIn("not", plan.claim_boundary)

    def test_declared_metadata_sets_tier_safety_and_dependency_edges(self) -> None:
        # Given a unit whose checks declare tiers, safety, and an edge
        plan = _compile(
            _unit(
                [_A, _B, _C],
                checks=[
                    {"command": _A, "id": "red", "safety": "read_only"},
                    {"command": _B, "id": "green", "safety": "read_only", "depends_on": ["red"]},
                    {"command": _C, "id": "gate", "tier": "integration"},
                ],
            )
        )

        # When compiled, Then the nodes carry the declared shape and the plan
        # is no longer the serial fallback.
        nodes = {node.declared_id: node for node in plan.nodes}
        self.assertEqual(nodes["red"].safety, "read_only")
        self.assertEqual(nodes["green"].depends_on, ("red",))
        self.assertEqual(nodes["gate"].tier, "integration")
        self.assertEqual(nodes["gate"].safety, "stateful")
        self.assertFalse(plan.is_serial)

    def test_declared_resource_and_scope_are_preserved_for_integrated_checks(self) -> None:
        # Given a stateful full gate claiming integrated verification evidence
        plan = _compile(
            _unit(
                [_C],
                checks=[
                    {
                        "command": _C,
                        "id": "full-gate",
                        "tier": "integration",
                        "safety": "stateful",
                        "resource_class": "shared_repo",
                        "claim_scope": "integrated_verification",
                    }
                ],
            )
        )

        # When compiled, Then its declared serialization resource and closed
        # integrated claim scope survive rather than falling back to unit CPU.
        node = plan.nodes[0]
        self.assertEqual(node.resource_class, "shared_repo")
        self.assertEqual(node.claim_scope, "integrated_verification")

    def test_check_ids_are_stable_for_identical_inputs_and_distinct_otherwise(self) -> None:
        # Given two compilations of the same unit
        first = _compile(_unit([_A, _B]))
        second = _compile(_unit([_A, _B]))

        # When the check ids are compared, Then identical inputs give
        # identical ids and a changed command gives a changed id.
        self.assertEqual(
            [node.check_id for node in first.nodes],
            [node.check_id for node in second.nodes],
        )
        other = _compile(_unit([_A, _C]))
        self.assertNotEqual(first.nodes[1].check_id, other.nodes[1].check_id)

    def test_a_unit_without_commands_compiles_to_nothing(self) -> None:
        self.assertIsNone(
            compile_verification_plan({"verification_commands": []}, fanout_id=_FANOUT_ID, unit_id=_UNIT_ID)
        )
        self.assertIsNone(compile_verification_plan({}, fanout_id=_FANOUT_ID, unit_id=_UNIT_ID))


class ReceiptKeyTests(unittest.TestCase):
    def test_structured_verification_environment_excludes_ambient_secrets(self) -> None:
        environment = verification_execution_environment(
            {
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": "tests",
                "OMH_FANOUT_DEPTH": "1",
                "OMH_FANOUT_LINEAGE": "fanout:core",
                "API_TOKEN": "low-entropy-secret",
                "UNRELATED_SETTING": "not-declared",
            }
        )

        self.assertEqual(
            environment,
            {
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": "tests",
                "OMH_FANOUT_DEPTH": "1",
                "OMH_FANOUT_LINEAGE": "fanout:core",
            },
        )

    def test_identical_inputs_share_a_key_and_every_component_change_invalidates_it(self) -> None:
        # Given a node and its key components
        with TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            node = _compile(_unit([_A])).nodes[0]
            toolchain = toolchain_digest(node, worktree=worktree)
            base = receipt_key(node, repo_identity="repo", revision="rev1", toolchain=toolchain)

            # When nothing changes, Then the key is stable.
            self.assertEqual(base, receipt_key(node, repo_identity="repo", revision="rev1", toolchain=toolchain))

            # When any single component changes, Then the key changes.
            self.assertNotEqual(
                base, receipt_key(node, repo_identity="repo", revision="rev2", toolchain=toolchain)
            )
            self.assertNotEqual(
                base, receipt_key(node, repo_identity="other-repo", revision="rev1", toolchain=toolchain)
            )
            self.assertNotEqual(
                base, receipt_key(node, repo_identity="repo", revision="rev1", toolchain="other-toolchain")
            )
            scoped = dataclasses.replace(node, claim_scope="integration_gate")
            self.assertNotEqual(
                base, receipt_key(scoped, repo_identity="repo", revision="rev1", toolchain=toolchain)
            )

            # When the command changes by one argv token, Then the key changes.
            other_node = _compile(_unit([_C])).nodes[0]
            self.assertNotEqual(
                base,
                receipt_key(other_node, repo_identity="repo", revision="rev1", toolchain=toolchain),
            )

    def test_execution_policy_metadata_invalidates_a_receipt_key(self) -> None:
        # Given one check and the receipt key it currently resolves to
        with TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            node = _compile(_unit([_A])).nodes[0]
            toolchain = toolchain_digest(node, worktree=worktree)
            base = receipt_key(node, repo_identity="repo", revision="rev1", toolchain=toolchain)

            # When any execution-affecting policy changes, Then the receipt
            # must not be reusable even though its command is identical.
            for changed in (
                dataclasses.replace(node, tier="integration"),
                dataclasses.replace(node, safety="read_only"),
                dataclasses.replace(node, resource_class="shared_repo"),
                dataclasses.replace(node, timeout=1),
                dataclasses.replace(node, depends_on=("red",)),
            ):
                with self.subTest(changed=changed):
                    self.assertNotEqual(
                        base,
                        receipt_key(changed, repo_identity="repo", revision="rev1", toolchain=toolchain),
                    )

    def test_the_toolchain_digest_covers_env_overrides_and_lockfiles(self) -> None:
        # Given two nodes differing only in a leading env override
        with TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            plain = _compile(_unit([_A])).nodes[0]
            with_env = _compile(_unit([f"OMH_VERIFY={_SECRET_ENV} {_A}"])).nodes[0]

            # When the digests are computed, Then the env override changes the
            # digest without ever storing the value.
            self.assertNotEqual(
                toolchain_digest(plain, worktree=worktree),
                toolchain_digest(with_env, worktree=worktree),
            )

            # When a lockfile appears in the worktree, Then the digest moves.
            before = toolchain_digest(plain, worktree=worktree)
            (worktree / "uv.lock").write_text("locked\n", encoding="utf-8")
            self.assertNotEqual(before, toolchain_digest(plain, worktree=worktree))
            self.assertNotEqual(
                toolchain_digest(plain, worktree=worktree, environment={"LANG": "one"}),
                toolchain_digest(plain, worktree=worktree, environment={"LANG": "two"}),
            )


class ReceiptPathSafetyTests(unittest.TestCase):
    def test_receipt_path_accepts_equivalent_windows_extended_namespaces(self) -> None:
        """Windows may resolve a missing child through the extended namespace."""
        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")
            key = "d" * 64
            directory = receipts_dir(paths)
            destination = directory / f"{key}.json"
            home = PureWindowsPath(r"C:\Users\runneradmin\AppData\Local\Temp\receipt-test\.omh")
            receipt_directory = home / "coding" / "verification-receipts"
            receipt_destination = receipt_directory / f"{key}.json"
            extended_directory = PureWindowsPath(
                r"\\?\C:\Users\runneradmin\AppData\Local\Temp\receipt-test\.omh\coding\verification-receipts"
            )
            extended_destination = extended_directory / f"{key}.json"
            unc_home = PureWindowsPath(r"\\server\share\receipt-test\.omh")
            extended_unc_directory = PureWindowsPath(
                r"\\?\UNC\server\share\receipt-test\.omh\coding\verification-receipts"
            )
            extended_unc_destination = extended_unc_directory / f"{key}.json"

            for label, resolved_directory, resolved_destination, resolved_home in (
                ("extended DOS destination", receipt_directory, extended_destination, home),
                ("extended DOS directory", extended_directory, receipt_destination, home),
                ("extended UNC", extended_unc_directory, extended_unc_destination, unc_home),
            ):
                with self.subTest(label=label):
                    resolved = {
                        paths.omh_home: resolved_home,
                        directory: resolved_directory,
                        destination: resolved_destination,
                    }

                    def resolve(path: Path, *, strict: bool = False) -> PureWindowsPath:
                        self.assertFalse(strict)
                        return resolved[path]

                    self.assertFalse(directory.exists())
                    with patch.object(Path, "resolve", autospec=True, side_effect=resolve):
                        self.assertEqual(receipt_path(paths, key), destination)
                    self.assertFalse(directory.exists())

    def test_receipt_path_rejects_extended_windows_namespace_escapes(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")
            key = "e" * 64
            directory = receipts_dir(paths)
            destination = directory / f"{key}.json"
            home = PureWindowsPath(r"C:\Users\runneradmin\AppData\Local\Temp\receipt-test\.omh")
            receipt_directory = home / "coding" / "verification-receipts"

            for label, resolved_directory, resolved_destination, error in (
                (
                    "directory",
                    PureWindowsPath(r"\\?\C:\Users\runneradmin\AppData\Local\Temp\outside"),
                    None,
                    "verification receipt directory escapes omh home",
                ),
                (
                    "destination",
                    receipt_directory,
                    PureWindowsPath(rf"\\?\C:\Users\runneradmin\AppData\Local\Temp\receipt-test\.omh\coding\outside\{key}.json"),
                    "verification receipt destination escapes receipt directory",
                ),
            ):
                with self.subTest(label=label):
                    resolved = {paths.omh_home: home, directory: resolved_directory}
                    if resolved_destination is not None:
                        resolved[destination] = resolved_destination

                    def resolve(path: Path, *, strict: bool = False) -> PureWindowsPath:
                        self.assertFalse(strict)
                        return resolved[path]

                    with patch.object(Path, "resolve", autospec=True, side_effect=resolve):
                        with self.assertRaisesRegex(ValueError, error):
                            receipt_path(paths, key)

    def test_receipt_paths_accept_only_64_lowercase_hex_keys(self) -> None:
        # Given a receipt store and malformed caller-supplied keys
        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")

            # When every receipt path boundary receives malformed input, Then
            # it rejects rather than normalizing a traversal-shaped filename.
            for key in ("../../../outside", "A" * 64, "a" * 63, "a" * 65):
                with self.subTest(key=key):
                    with self.assertRaises(ValueError):
                        receipt_path(paths, key)
                    with self.assertRaises(ValueError):
                        load_receipt(paths, key)
                    with self.assertRaises(ValueError):
                        store_receipt(paths, {"receipt_key": key})
                    with self.assertRaises(ValueError):
                        with receipt_file_lock(paths, key, timeout_seconds=1):
                            pass

            # Then the one accepted filename remains contained in the receipt directory.
            key = "a" * 64
            self.assertEqual(receipt_path(paths, key).parent, receipts_dir(paths))

    def test_receipt_store_refuses_symlinked_directory_and_destination(self) -> None:
        # Given a receipt directory or filename redirected through a symlink
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            key = "b" * 64
            destination = receipts_dir(paths) / f"{key}.json"
            destination.parent.mkdir(parents=True)
            outside = root / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            os.symlink(outside, destination)

            # When the public receipt boundary resolves the destination, Then
            # it refuses the symlink instead of following it outside the store.
            with self.assertRaises(ValueError):
                receipt_path(paths, key)

            destination.unlink()
            receipts_dir(paths).rmdir()
            redirected = root / "redirected-receipts"
            redirected.mkdir()
            os.symlink(redirected, receipts_dir(paths))
            with self.assertRaises(ValueError):
                receipt_path(paths, key)

    def test_valid_receipts_still_round_trip_through_the_safe_path(self) -> None:
        # Given an exactly shaped receipt key
        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")
            key = "c" * 64
            receipt = {
                "schema_version": VERIFICATION_RECEIPT_SCHEMA_VERSION,
                "receipt_key": key,
                "status": "passed",
            }

            # When it is stored and loaded, Then the contained destination is usable.
            store_receipt(paths, receipt)
            self.assertEqual(load_receipt(paths, key), receipt)


class WorktreeRevisionTests(unittest.TestCase):
    def test_an_untracked_worktree_has_no_reusable_revision(self) -> None:
        # Given a real checkout with untracked content
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
            subprocess.run(
                ["git", "-c", "user.name=test", "-c", "user.email=test@example.test", "commit", "-qm", "seed"],
                cwd=repo,
                check=True,
            )
            (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")

            # When revision evidence is resolved, Then the dirty checkout has no reusable key.
            self.assertIsNone(_verification_worktree_revision(subprocess.run, repo))


class SingleFlightTests(unittest.TestCase):
    def test_two_consumers_share_one_produce_call(self) -> None:
        # Given one key claimed by two concurrent consumers
        flight = SingleFlight()
        entered = threading.Event()
        release = threading.Event()
        calls: list[str] = []

        def produce() -> str:
            calls.append("ran")
            entered.set()
            self.assertTrue(release.wait(timeout=5))
            return "result"

        outcomes: list[tuple[str, bool]] = []

        def consume() -> None:
            outcomes.append(flight.run("key", produce))

        first = threading.Thread(target=consume)
        first.start()
        # Subscribe before triggering: the owner is inside produce before the
        # second consumer starts, so both must land on the one call.
        self.assertTrue(entered.wait(timeout=5))
        second = threading.Thread(target=consume)
        second.start()
        release.set()
        first.join(timeout=5)
        second.join(timeout=5)

        # Then exactly one produce ran and the second consumer reused it.
        self.assertEqual(calls, ["ran"])
        self.assertEqual(sorted(outcomes), [("result", False), ("result", True)])

    def test_distinct_keys_run_distinct_produces(self) -> None:
        flight = SingleFlight()
        self.assertEqual(flight.run("one", lambda: 1), (1, False))
        self.assertEqual(flight.run("two", lambda: 2), (2, False))


class PlanRunResultTests(unittest.TestCase):
    def test_an_empty_plan_is_hold_not_pass(self) -> None:
        # Given no verification outcomes
        result = PlanRunResult(outcomes=())

        # When the aggregate is evaluated, Then absence of evidence is HOLD.
        self.assertFalse(result.all_passed)


class VerificationEngineTests(unittest.TestCase):
    def _setup(self, tmp: str) -> tuple[OmhPaths, Path]:
        root = Path(tmp)
        worktree = root / "worktree"
        worktree.mkdir()
        return OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes"), worktree

    def test_independent_read_only_checks_overlap_and_the_dependent_waits(self) -> None:
        # Given read-only checks A and B and a dependent full check C
        with TemporaryDirectory() as tmp:
            paths, worktree = self._setup(tmp)
            plan = _compile(
                _unit(
                    [_A, _B, _C],
                    checks=[
                        {"command": _A, "id": "a", "safety": "read_only"},
                        {"command": _B, "id": "b", "safety": "read_only"},
                        {"command": _C, "id": "c", "depends_on": ["a", "b"]},
                    ],
                )
            )
            started = {"a": threading.Event(), "b": threading.Event()}
            finished = {"a": threading.Event(), "b": threading.Event()}
            overlapped: list[str] = []
            c_saw_producers_done: list[bool] = []

            def run_node(node):
                if node.declared_id in started:
                    started[node.declared_id].set()
                    # Both must be in flight at once; a serial engine times
                    # this wait out and records no overlap.
                    if started["a"].wait(timeout=5) and started["b"].wait(timeout=5):
                        overlapped.append(node.declared_id)
                    finished[node.declared_id].set()
                    return ("passed", "", None)
                c_saw_producers_done.append(finished["a"].is_set() and finished["b"].is_set())
                return ("passed", "", None)

            # When the plan runs with wave width available
            result = run_verification_plan(_context(paths, worktree), plan, run_node=run_node)

            # Then A and B overlapped, C started only after both finished, and
            # every node passed.
            self.assertEqual(sorted(overlapped), ["a", "b"])
            self.assertEqual(c_saw_producers_done, [True])
            self.assertEqual([outcome.status for outcome in result.outcomes], ["passed"] * 3)
            self.assertTrue(result.all_passed)
            self.assertEqual(result.failures, [])

    def test_a_failed_red_check_blocks_the_green_dependent(self) -> None:
        # Given a GREEN check whose required RED evidence fails
        with TemporaryDirectory() as tmp:
            paths, worktree = self._setup(tmp)
            plan = _compile(
                _unit(
                    [_A, _B],
                    checks=[
                        {"command": _A, "id": "red", "safety": "read_only"},
                        {"command": _B, "id": "green", "depends_on": ["red"]},
                    ],
                )
            )
            submitted: list[str] = []

            def run_node(node):
                submitted.append(node.declared_id)
                return ("failed", "exit 1: red", None) if node.declared_id == "red" else ("passed", "", None)

            # When the plan runs
            result = run_verification_plan(_context(paths, worktree), plan, run_node=run_node)

            # Then GREEN was never submitted, is recorded blocked, and the
            # aggregate cannot pass.
            self.assertEqual(submitted, ["red"])
            outcomes = {outcome.node.declared_id: outcome for outcome in result.outcomes}
            self.assertEqual(outcomes["red"].status, "failed")
            self.assertEqual(outcomes["green"].status, "skipped")
            self.assertIn("red", outcomes["green"].detail)
            self.assertFalse(result.all_passed)
            self.assertEqual(len(result.failures), 1)

    def test_a_green_check_never_starts_before_its_red_evidence_lands(self) -> None:
        # Given a slow RED check and a GREEN check gated on it
        with TemporaryDirectory() as tmp:
            paths, worktree = self._setup(tmp)
            plan = _compile(
                _unit(
                    [_A, _B],
                    checks=[
                        {"command": _A, "id": "red", "safety": "read_only"},
                        {"command": _B, "id": "green", "safety": "read_only", "depends_on": ["red"]},
                    ],
                )
            )
            red_started = threading.Event()
            red_release = threading.Event()
            order: list[str] = []

            def run_node(node):
                order.append(node.declared_id)
                if node.declared_id == "red":
                    red_started.set()
                    self.assertTrue(red_release.wait(timeout=5))
                return ("passed", "", None)

            result_holder: list[object] = []
            engine = threading.Thread(
                target=lambda: result_holder.append(
                    run_verification_plan(_context(paths, worktree), plan, run_node=run_node)
                )
            )
            engine.start()

            # When RED is still running, Then GREEN has not started.
            self.assertTrue(red_started.wait(timeout=5))
            self.assertEqual(order, ["red"])
            red_release.set()
            engine.join(timeout=5)

            # Then GREEN ran after RED finished and the plan passed.
            self.assertEqual(order, ["red", "green"])
            self.assertTrue(result_holder[0].all_passed)

    def test_post_integration_refuses_missing_producer_evidence(self) -> None:
        # Given a full gate and no producer completion evidence
        with TemporaryDirectory() as tmp:
            paths, worktree = self._setup(tmp)
            plan = _compile(
                _unit(
                    [_C],
                    checks=[{"command": _C, "id": "full", "tier": "integration"}],
                )
            )
            calls: list[str] = []

            # When the explicit post-integration surface is called early
            held = run_post_integration_verification(
                _context(paths, worktree), plan, producer_evidence=False,
                run_node=lambda node: (calls.append(node.declared_id), "passed", "", None)[1:],
            )

            # Then no full gate runs and the result stays HOLD.
            self.assertEqual(calls, [])
            self.assertTrue(held.deferred)
            self.assertFalse(held.all_passed)

    def test_post_integration_consumers_share_one_full_gate_receipt(self) -> None:
        # Given two consumers of one exact integrated revision
        with TemporaryDirectory() as tmp:
            paths, worktree = self._setup(tmp)
            plan = _compile(
                _unit(
                    [_C],
                    checks=[
                        {
                            "command": _C,
                            "id": "full",
                            "tier": "integration",
                            "resource_class": "shared_repo",
                            "claim_scope": "integrated_verification",
                        }
                    ],
                )
            )
            calls: list[str] = []

            def run_node(node):
                calls.append(node.declared_id)
                return "passed", "", None

            # When both consumers name the same integrated tree revision
            first = run_post_integration_verification(
                _context(paths, worktree, revision="integrated-tree"), plan,
                producer_evidence=True, run_node=run_node,
            )
            second = run_post_integration_verification(
                _context(paths, worktree, revision="integrated-tree", single_flight=SingleFlight()), plan,
                producer_evidence=True, run_node=run_node,
            )

            # Then the complete gate process runs once and the next consumer reuses it.
            self.assertEqual(calls, ["full"])
            self.assertFalse(first.outcomes[0].reused)
            self.assertTrue(second.outcomes[0].reused)
            self.assertEqual(first.outcomes[0].receipt_key, second.outcomes[0].receipt_key)

    def test_a_second_consumer_at_the_same_revision_reuses_the_receipt(self) -> None:
        # Given a plan that already ran at one revision
        with TemporaryDirectory() as tmp:
            paths, worktree = self._setup(tmp)
            plan = _compile(
                _unit([_A], checks=[{"command": _A, "id": "a", "safety": "read_only"}])
            )
            calls: list[str] = []

            def run_node(node):
                calls.append(node.declared_id)
                return ("passed", "", None)

            first = run_verification_plan(_context(paths, worktree), plan, run_node=run_node)
            self.assertEqual(calls, ["a"])
            self.assertFalse(first.outcomes[0].reused)

            # When a second consumer (fresh single-flight, same store) resolves
            # the same revision/command/toolchain/scope, Then no process starts
            # and the outcome names the same receipt.
            second = run_verification_plan(
                _context(paths, worktree, single_flight=SingleFlight()), plan, run_node=run_node
            )
            self.assertEqual(calls, ["a"])
            self.assertTrue(second.outcomes[0].reused)
            self.assertEqual(second.outcomes[0].receipt_key, first.outcomes[0].receipt_key)
            self.assertTrue(second.all_passed)

    def test_a_revision_change_invalidates_the_receipt(self) -> None:
        # Given a receipt stored at rev1
        with TemporaryDirectory() as tmp:
            paths, worktree = self._setup(tmp)
            plan = _compile(
                _unit([_A], checks=[{"command": _A, "id": "a", "safety": "read_only"}])
            )
            calls: list[str] = []

            def run_node(node):
                calls.append(node.declared_id)
                return ("passed", "", None)

            run_verification_plan(_context(paths, worktree, revision="rev1"), plan, run_node=run_node)

            # When the revision moves, Then the check runs fresh.
            rerun = run_verification_plan(
                _context(paths, worktree, revision="rev2", single_flight=SingleFlight()),
                plan,
                run_node=run_node,
            )
            self.assertEqual(len(calls), 2)
            self.assertFalse(rerun.outcomes[0].reused)

    def test_a_scope_insufficient_receipt_is_treated_as_missing_evidence(self) -> None:
        # Given a stored receipt whose claim scope does not cover the node
        with TemporaryDirectory() as tmp:
            paths, worktree = self._setup(tmp)
            plan = _compile(
                _unit([_A], checks=[{"command": _A, "id": "a", "safety": "read_only"}])
            )
            node = plan.nodes[0]
            key = receipt_key(
                node,
                repo_identity=str(worktree.resolve()),
                revision="rev1",
                toolchain=toolchain_digest(node, worktree=worktree),
            )
            store_receipt(
                paths,
                {
                    "schema_version": VERIFICATION_RECEIPT_SCHEMA_VERSION,
                    "receipt_key": str(key),
                    "check_id": node.check_id,
                    "status": "passed",
                    "claim_scope": "style_only",
                    "revision": "rev1",
                },
            )
            calls: list[str] = []

            def run_node(candidate):
                calls.append(candidate.declared_id)
                return ("passed", "", None)

            # When the engine resolves the key, Then the under-scoped receipt
            # is not evidence and the check runs fresh.
            result = run_verification_plan(_context(paths, worktree), plan, run_node=run_node)
            self.assertEqual(calls, ["a"])
            self.assertFalse(result.outcomes[0].reused)

    def test_stateful_checks_never_overlap(self) -> None:
        # Given two stateful checks in one resource class
        with TemporaryDirectory() as tmp:
            paths, worktree = self._setup(tmp)
            plan = _compile(_unit([_A, _B]))  # metadata-free: all stateful
            first_started = threading.Event()
            second_started = threading.Event()
            overlapped: list[bool] = []

            def run_node(node):
                if node.declared_id == "check-0":
                    first_started.set()
                    # If the engine let the sibling in, this wait returns True.
                    overlapped.append(second_started.wait(timeout=2))
                else:
                    self.assertTrue(first_started.wait(timeout=5))
                    second_started.set()
                return ("passed", "", None)

            # When the plan runs with wave width to spare, Then the stateful
            # checks still serialize.
            result = run_verification_plan(_context(paths, worktree, max_workers=4), plan, run_node=run_node)
            self.assertEqual(overlapped, [False])
            self.assertTrue(result.all_passed)

    def test_a_shared_dispatch_gate_serializes_stateful_checks_across_plans(self) -> None:
        # Given two simultaneously-run plans sharing a stateful resource
        with TemporaryDirectory() as tmp:
            paths, worktree = self._setup(tmp)
            first = _compile(_unit([_A], checks=[{"command": _A, "safety": "stateful", "resource_class": "shared-repo"}]))
            second = _compile(_unit([_B], checks=[{"command": _B, "safety": "stateful", "resource_class": "shared-repo"}]))
            gate = VerificationExecutionGate(max_workers=2)
            first_started = threading.Event()
            second_started = threading.Event()
            release = threading.Event()
            overlaps: list[bool] = []

            def first_run(_node):
                first_started.set()
                overlaps.append(second_started.wait(timeout=2))
                self.assertTrue(release.wait(timeout=5))
                return "passed", "", None

            def second_run(_node):
                self.assertTrue(first_started.wait(timeout=5))
                second_started.set()
                return "passed", "", None

            # When the plans start concurrently, Then the second check cannot
            # acquire the shared resource while the first owns it.
            first_thread = threading.Thread(
                target=lambda: run_verification_plan(
                    dataclasses.replace(_context(paths, worktree), execution_gate=gate), first, run_node=first_run
                )
            )
            second_thread = threading.Thread(
                target=lambda: run_verification_plan(
                    dataclasses.replace(_context(paths, worktree), execution_gate=gate), second, run_node=second_run
                )
            )
            first_thread.start()
            self.assertTrue(first_started.wait(timeout=5))
            second_thread.start()
            self.assertTrue(first_started.wait(timeout=5))
            release.set()
            first_thread.join(timeout=5)
            second_thread.join(timeout=5)
            gate.shutdown()

            self.assertEqual(overlaps, [False])
            self.assertTrue(second_started.is_set())

    def test_a_shared_dispatch_gate_bounds_read_only_checks_across_plans(self) -> None:
        # Given two simultaneous two-node plans and one dispatch-wide width of two
        with TemporaryDirectory() as tmp:
            paths, worktree = self._setup(tmp)
            first = _compile(_unit([_A, _B], checks=[{"command": _A, "safety": "read_only"}, {"command": _B, "safety": "read_only"}]))
            second = _compile(_unit([_C, "python3 -m unittest tests.test_d"], checks=[{"command": _C, "safety": "read_only"}, {"command": "python3 -m unittest tests.test_d", "safety": "read_only"}]))
            gate = VerificationExecutionGate(max_workers=2)
            lock = threading.Lock()
            pair_started = threading.Event()
            release = threading.Event()
            inflight = 0
            maximum = 0

            def run_node(_node):
                nonlocal inflight, maximum
                with lock:
                    inflight += 1
                    maximum = max(maximum, inflight)
                    if inflight == 2:
                        pair_started.set()
                self.assertTrue(release.wait(timeout=5))
                with lock:
                    inflight -= 1
                return "passed", "", None

            # When both plans compete for the same gate, Then neither plan can
            # create its own extra wave beyond the dispatch policy.
            threads = [
                threading.Thread(
                    target=lambda plan=plan: run_verification_plan(
                        dataclasses.replace(_context(paths, worktree), execution_gate=gate), plan, run_node=run_node
                    )
                )
                for plan in (first, second)
            ]
            for thread in threads:
                thread.start()
            self.assertTrue(pair_started.wait(timeout=5))
            self.assertEqual(maximum, 2)
            release.set()
            for thread in threads:
                thread.join(timeout=5)
            gate.shutdown()

            self.assertEqual(maximum, 2)

    def test_the_wave_width_never_exceeds_the_policy_bound(self) -> None:
        # Given six read-only checks and a policy width of two
        with TemporaryDirectory() as tmp:
            paths, worktree = self._setup(tmp)
            checks = [
                {"command": f"python3 -m unittest tests.test_{index}", "id": f"n{index}", "safety": "read_only"}
                for index in range(6)
            ]
            plan = _compile(_unit([str(check["command"]) for check in checks], checks=checks))
            lock = threading.Lock()
            inflight = 0
            max_inflight = 0
            pair_started = threading.Event()
            gate = threading.Event()

            def run_node(node):
                nonlocal inflight, max_inflight
                with lock:
                    inflight += 1
                    max_inflight = max(max_inflight, inflight)
                    if inflight == 2:
                        pair_started.set()
                self.assertTrue(gate.wait(timeout=5))
                with lock:
                    inflight -= 1
                return ("passed", "", None)

            result_holder: list[object] = []
            engine = threading.Thread(
                target=lambda: result_holder.append(
                    run_verification_plan(
                        _context(paths, worktree, max_workers=2), plan, run_node=run_node
                    )
                )
            )
            engine.start()

            # When the first wave is in flight, Then exactly two checks are
            # running — never more than the policy width.
            self.assertTrue(pair_started.wait(timeout=5))
            self.assertEqual(max_inflight, 2)
            gate.set()
            engine.join(timeout=5)
            self.assertEqual(max_inflight, 2)
            self.assertTrue(result_holder[0].all_passed)

    def test_parallel_and_serial_waves_reach_the_identical_decision(self) -> None:
        # Given one evidence set executed two ways
        with TemporaryDirectory() as tmp:
            checks = [
                {"command": _A, "id": "a", "safety": "read_only"},
                {"command": _B, "id": "b", "safety": "read_only"},
                {"command": _C, "id": "c", "depends_on": ["a", "b"]},
            ]
            plan = _compile(_unit([_A, _B, _C], checks=checks))
            decisions: list[tuple[tuple[str, ...], tuple[str, ...], bool]] = []
            for index, width in enumerate((1, 4)):
                root = Path(tmp) / f"run{index}"
                worktree = root / "worktree"
                worktree.mkdir(parents=True)
                paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
                result = run_verification_plan(
                    _context(paths, worktree, max_workers=width), plan, run_node=_passing
                )
                decisions.append(
                    (
                        tuple(outcome.node.declared_id for outcome in result.outcomes),
                        tuple(outcome.status for outcome in result.outcomes),
                        result.all_passed,
                    )
                )

            # Then the serial and parallel waves agree exactly.
            self.assertEqual(decisions[0], decisions[1])

    def test_an_integration_check_waits_for_the_fan_in_gate(self) -> None:
        # Given an integration-tier check and a closed producer gate
        with TemporaryDirectory() as tmp:
            paths, worktree = self._setup(tmp)
            plan = _compile(
                _unit(
                    [_A, _B],
                    checks=[
                        {"command": _A, "id": "unit-check", "safety": "read_only"},
                        {"command": _B, "id": "gate", "tier": "integration"},
                    ],
                )
            )
            submitted: list[str] = []

            def run_node(node):
                submitted.append(node.declared_id)
                return ("passed", "", None)

            # When the gate is closed, Then the integration check is deferred —
            # recorded, never run — and the aggregate stays short of passed.
            held = run_verification_plan(_context(paths, worktree), plan, run_node=run_node)
            self.assertEqual(submitted, ["unit-check"])
            outcomes = {outcome.node.declared_id: outcome for outcome in held.outcomes}
            self.assertEqual(outcomes["gate"].status, "skipped")
            self.assertTrue(outcomes["gate"].deferred)
            self.assertTrue(held.deferred)
            self.assertFalse(held.all_passed)

            # When the gate opens (producer lanes fanned in), Then the check runs.
            open_result = run_verification_plan(
                _context(paths, worktree, integration_ready=lambda: True, single_flight=SingleFlight()),
                plan,
                run_node=run_node,
            )
            self.assertIn("gate", submitted)
            self.assertTrue(open_result.all_passed)

    def test_secret_bearing_environment_runs_fresh_without_a_persisted_receipt(self) -> None:
        # Given a structured check with a low-entropy secret environment value
        with TemporaryDirectory() as tmp:
            paths, worktree = self._setup(tmp)
            command = f"PIN=1234 {_A}"
            plan = _compile(_unit([command], checks=[{"command": command, "id": "pin-check"}]))
            calls: list[str] = []

            def run_node(node):
                calls.append(node.declared_id)
                return "passed", "", None

            # When it resolves twice at the same revision, Then the secret-bearing
            # environment disables receipt reuse rather than persisting a guessable key.
            first = run_verification_plan(_context(paths, worktree), plan, run_node=run_node)
            second = run_verification_plan(
                _context(paths, worktree, single_flight=SingleFlight()), plan, run_node=run_node
            )
            self.assertTrue(first.all_passed)
            self.assertTrue(second.all_passed)
            self.assertEqual(calls, ["pin-check", "pin-check"])
            self.assertIsNone(first.outcomes[0].receipt_key)
            self.assertIsNone(second.outcomes[0].receipt_key)
            self.assertFalse(receipts_dir(paths).exists())

    def test_receipts_retain_metadata_only(self) -> None:
        # Given a failing check whose output and env carry secret-shaped text
        with TemporaryDirectory() as tmp:
            paths, worktree = self._setup(tmp)
            command = f"OMH_VERIFY={_SECRET_ENV} {_A}"
            plan = _compile(_unit([command], checks=[{"command": command, "id": "a"}]))

            def run_node(node):
                return ("failed", f"exit 1: {_SECRET_OUTPUT}", None)

            result = run_verification_plan(_context(paths, worktree), plan, run_node=run_node)
            self.assertFalse(result.all_passed)

            # When the stored receipt is inspected, Then it carries exactly the
            # metadata schema and none of the secret-shaped bytes.
            stored = list(receipts_dir(paths).glob("*.json"))
            self.assertEqual(len(stored), 1)
            raw = stored[0].read_bytes()
            self.assertNotIn(_SECRET_OUTPUT.encode(), raw)
            self.assertNotIn(_SECRET_ENV.encode(), raw)
            self.assertNotIn(command.encode(), raw)
            receipt = json.loads(raw)
            self.assertEqual(receipt["schema_version"], VERIFICATION_RECEIPT_SCHEMA_VERSION)
            for field in (
                "receipt_key",
                "check_id",
                "status",
                "queued_at",
                "started_at",
                "finished_at",
                "duration_seconds",
                "reused",
                "reuse_count",
                "revision",
                "depends_on",
                "claim_scope",
                "observation_source",
                "claim_boundary",
            ):
                self.assertIn(field, receipt)
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(receipt["revision"], "rev1")
            self.assertEqual(receipt["receipt_key"], result.outcomes[0].receipt_key)
            self.assertEqual(receipt_path(paths, result.outcomes[0].receipt_key), stored[0])


if __name__ == "__main__":
    unittest.main()
