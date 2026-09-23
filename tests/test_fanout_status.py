from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli  # noqa: E402

from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_artifacts import (  # noqa: E402
    fanout_contract_digest,
    fanout_dispatch_summary_path,
    write_fanout_contract,
)
from omh.coding.executor_readiness import observe_session_binary  # noqa: E402
from omh.coding.fanout_executor_sessions import (  # noqa: E402
    SessionBinding,
    SessionCapability,
    SessionDecoder,
    observe_session_workspace,
)
from omh.coding.inflight import write_inflight_marker  # noqa: E402
from omh.coding.fanout_dispatch import dispatch_fanout  # noqa: E402
from omh.coding.fanout_status import (  # noqa: E402
    FANOUT_STATUS_SCHEMA_VERSION,
    project_fanout_status,
    render_fanout_status_text,
)
from omh.system.paths import OmhPaths  # noqa: E402

_FANOUT_ID = "fanout-0123456789ab"


def _stamp(minutes_ago: int) -> str:
    moment = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _event(
    unit_id: str,
    event: str,
    *,
    minutes_ago: int,
    status: str = "observed",
    worktree: str = "",
    owner: str = "codex",
    evidence_refs: list[str] | None = None,
    legacy: bool = False,
) -> dict[str, object]:
    """One synthetic journal event for `{fanout}-{unit}`'s run.

    `legacy=True` drops the fields later journal versions added (schema_version,
    worker_ref, evidence_refs, runtime_profile) and uses the pre-canonical event
    alias, so the roster is exercised against both the old and current shapes.
    """
    run_id = f"{_FANOUT_ID}-{unit_id}"
    record: dict[str, object] = {
        "event_id": f"{unit_id}-{event}-{minutes_ago}",
        "target_type": "run",
        "target_id": run_id,
        "run_id": run_id,
        "event": event,
        "status": status,
        "observed_at": _stamp(minutes_ago),
        "summary": f"{unit_id} {event}",
    }
    if legacy:
        return record
    record.update(
        {
            "schema_version": "omh_observation_event/v1",
            "privacy": "metadata_only",
            "worker_ref": unit_id,
            "runtime_profile": owner,
            "evidence_refs": evidence_refs or [],
        }
    )
    if worktree:
        record["worktree_ref"] = worktree
    return record


def _seed_journal(paths: OmhPaths, events: list[dict[str, object]]) -> None:
    path = paths.runtime_journal_events_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{json.dumps(event, sort_keys=True)}\n" for event in events),
        encoding="utf-8",
    )


def _roster_fixture() -> list[dict[str, object]]:
    return [
        # `core` reached the per-unit verification receipt.
        _event("core", "worktree_creation_observed", minutes_ago=90, worktree="/tmp/wt/core"),
        _event("core", "executor_dispatch_observed", minutes_ago=80, worktree="/tmp/wt/core"),
        _event(
            "core",
            "executor_result_observed",
            minutes_ago=70,
            worktree="/tmp/wt/core",
            evidence_refs=["run:core:exit0"],
        ),
        _event(
            "core",
            "unit_verification_observed",
            minutes_ago=60,
            worktree="/tmp/wt/core",
            evidence_refs=["run:core:unittest"],
        ),
        # `docs` was dispatched to a different owner and only came back with a
        # process result, written in the legacy pre-canonical shape.
        _event("docs", "worker_dispatch", minutes_ago=50, legacy=True),
        _event("docs", "worker_result", minutes_ago=40, legacy=True),
        _event(
            "docs",
            "executor_result_observed",
            minutes_ago=39,
            owner="claude-code",
            worktree="/tmp/wt/docs",
            evidence_refs=["run:docs:exit0"],
        ),
        # `flaky` failed at the executor result.
        _event("flaky", "executor_dispatch_observed", minutes_ago=30, worktree="/tmp/wt/flaky"),
        _event(
            "flaky",
            "executor_result_observed",
            minutes_ago=20,
            status="failed",
            worktree="/tmp/wt/flaky",
        ),
        # A different fanout's unit must never appear in this roster.
        {
            "schema_version": "omh_observation_event/v1",
            "event_id": "other-1",
            "target_type": "run",
            "target_id": "fanout-ffffffffffff-other",
            "run_id": "fanout-ffffffffffff-other",
            "event": "executor_dispatch_observed",
            "status": "observed",
            "observed_at": _stamp(10),
            "summary": "other fanout",
            "privacy": "metadata_only",
            "worker_ref": "other",
            "runtime_profile": "codex",
            "evidence_refs": [],
        },
    ]


class FanoutStatusProjectionTests(unittest.TestCase):
    def test_roster_projects_units_from_journal_events(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            _seed_journal(paths, _roster_fixture())

            roster = project_fanout_status(paths, _FANOUT_ID)

            self.assertEqual(roster["schema_version"], FANOUT_STATUS_SCHEMA_VERSION)
            self.assertEqual(roster["fanout_id"], _FANOUT_ID)
            self.assertEqual([unit["unit_id"] for unit in roster["units"]], ["core", "docs", "flaky"])
            core, docs, flaky = roster["units"]
            self.assertEqual(core["lifecycle_state"], "unit_verification_observed")
            self.assertEqual(core["owner"], "codex")
            self.assertEqual(core["worktree_path"], "/tmp/wt/core")
            self.assertEqual(core["evidence_ref_count"], 2)
            self.assertGreaterEqual(core["last_event_age_seconds"], 3600)
            self.assertEqual(docs["lifecycle_state"], "process_succeeded")
            self.assertEqual(docs["owner"], "claude-code")
            self.assertEqual(flaky["lifecycle_state"], "dispatched_not_succeeded")
            self.assertEqual(roster["unit_count"], 3)

    def test_legacy_events_do_not_crash_or_invent_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            # Legacy-only unit: no schema_version, no worker_ref, aliased names.
            _seed_journal(
                paths,
                [
                    _event("legacy", "worker_dispatch", minutes_ago=20, legacy=True),
                    _event("legacy", "worker_result", minutes_ago=10, legacy=True),
                ],
            )

            roster = project_fanout_status(paths, _FANOUT_ID)

            self.assertEqual([unit["unit_id"] for unit in roster["units"]], ["legacy"])
            unit = roster["units"][0]
            self.assertEqual(unit["lifecycle_state"], "process_succeeded")
            self.assertEqual(unit["owner"], "unknown")
            self.assertEqual(unit["worktree_path"], "unknown")
            self.assertEqual(unit["evidence_ref_count"], 0)

    def test_persisted_v1_executor_session_remains_resumable_in_status(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            repository.mkdir()
            subprocess.run(("git", "init", "-q"), cwd=repository, check=True)
            (repository / "tracked").write_text("base\n", encoding="utf-8")
            subprocess.run(("git", "add", "tracked"), cwd=repository, check=True)
            subprocess.run(
                ("git", "-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-qm", "base"),
                cwd=repository,
                check=True,
            )
            worktree = root / "unit"
            subprocess.run(
                ("git", "worktree", "add", "-qb", "unit/status", str(worktree)),
                cwd=repository,
                check=True,
            )
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            contract = write_fanout_contract(
                paths,
                build_fanout_contract(
                    "Persist a legacy executor session.",
                    [{"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["src/"]}],
                ),
            )
            fanout_id = str(contract["fanout_id"])
            run_ref = f"{fanout_id}-core"
            executable = root / "codex"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            identity = observe_session_binary(str(executable), env={"PATH": os.environ.get("PATH", "")})
            workspace = observe_session_workspace(str(worktree))
            self.assertIsNotNone(identity)
            self.assertIsNotNone(workspace)
            assert identity is not None and workspace is not None
            attempt_id = "22345678-1234-4234-8234-123456789abc"
            binding = SessionBinding(
                fanout_id,
                "core",
                run_ref,
                attempt_id,
                fanout_contract_digest(contract),
                str(worktree.resolve()),
                workspace.incarnation,
                workspace.head,
                workspace.head,
            )
            decoder = SessionDecoder(SessionCapability("codex", "codex_exec_json", identity, "1.2.3"))
            decoder.observe(
                {"type": "thread.started", "thread_id": "12345678-1234-4234-8234-123456789abc"},
                event_ref="stdout:1",
            )
            persisted = decoder.receipt(binding, end_head=workspace.head).to_dict()
            persisted["schema_version"] = "fanout_executor_session/v1"
            binary_identity = persisted["binary_identity"]
            assert isinstance(binary_identity, dict)
            binary_identity.pop("launch_path")
            event = _event("core", "executor_session_observed", minutes_ago=1)
            event.update(
                {
                    "target_id": run_ref,
                    "run_id": run_ref,
                    "worker_ref": "core",
                    "attempt_id": attempt_id,
                    "worktree_ref": str(worktree.resolve()),
                    "executor_session": persisted,
                }
            )
            _seed_journal(paths, [event])

            roster = project_fanout_status(paths, fanout_id)

            resume = roster["units"][0]["resume"]
            self.assertTrue(resume["available"])
            self.assertEqual(resume["argv"][0], str(executable.resolve()))

    def test_integration_ready_requires_verification_and_merge_order_position(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            _seed_journal(
                paths,
                [
                    _event("alpha", "executor_dispatch_observed", minutes_ago=40),
                    _event("alpha", "executor_result_observed", minutes_ago=35),
                    _event("beta", "executor_dispatch_observed", minutes_ago=30),
                    _event("beta", "executor_result_observed", minutes_ago=25),
                    _event("beta", "unit_verification_observed", minutes_ago=20),
                ],
            )

            roster = project_fanout_status(paths, _FANOUT_ID)

            by_unit = {unit["unit_id"]: unit for unit in roster["units"]}
            # `beta` has its own verification receipt, but `alpha` sits ahead of
            # it without one, so nothing is integration ready.
            self.assertEqual(by_unit["beta"]["lifecycle_state"], "unit_verification_observed")
            self.assertEqual(by_unit["alpha"]["lifecycle_state"], "process_succeeded")
            self.assertEqual(roster["integration_ready_units"], [])

    def test_integration_ready_needs_the_whole_observed_chain(self) -> None:
        """Verification alone is not integration eligibility; the sidecar rung counts."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            _seed_journal(
                paths,
                [
                    _event("alpha", "executor_dispatch_observed", minutes_ago=40),
                    _event("alpha", "executor_result_observed", minutes_ago=35),
                    _event("alpha", "unit_result_validated", minutes_ago=32),
                    _event("alpha", "unit_verification_observed", minutes_ago=30),
                    _event("beta", "executor_dispatch_observed", minutes_ago=25),
                    _event("beta", "executor_result_observed", minutes_ago=20),
                    _event("beta", "unit_verification_observed", minutes_ago=15),
                ],
            )

            roster = project_fanout_status(paths, _FANOUT_ID)

            by_unit = {unit["unit_id"]: unit for unit in roster["units"]}
            self.assertEqual(by_unit["alpha"]["lifecycle_state"], "integration_ready")
            # `beta` never had a validated result sidecar observed.
            self.assertEqual(by_unit["beta"]["lifecycle_state"], "unit_verification_observed")
            self.assertEqual(roster["integration_ready_units"], ["alpha"])

    def test_summary_text_never_promotes_state_over_events(self) -> None:
        """A journal summary echoing success cannot lift the lifecycle state."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            misleading = _event("liar", "executor_dispatch_observed", minutes_ago=5)
            misleading["summary"] = "unit_verification_observed integration_ready all checks passed"
            _seed_journal(paths, [misleading])

            roster = project_fanout_status(paths, _FANOUT_ID)

            self.assertEqual(roster["units"][0]["lifecycle_state"], "dispatched_not_succeeded")
            self.assertEqual(roster["integration_ready_units"], [])

    def test_render_lists_one_line_per_unit(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            _seed_journal(paths, _roster_fixture())

            text = render_fanout_status_text(project_fanout_status(paths, _FANOUT_ID))

            self.assertIn(_FANOUT_ID, text)
            self.assertIn("core", text)
            self.assertIn("unit_verification_observed", text)
            self.assertIn("codex", text)

    def test_empty_fanout_reports_no_units_observed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            _seed_journal(
                paths,
                [
                    {
                        "schema_version": "omh_observation_event/v1",
                        "event_id": "fanout-level-1",
                        "target_type": "run",
                        "target_id": _FANOUT_ID,
                        "run_id": _FANOUT_ID,
                        "event": "prepared_handoff_created",
                        "status": "observed",
                        "observed_at": _stamp(5),
                        "summary": "contract frozen",
                        "privacy": "metadata_only",
                        "evidence_refs": [],
                    }
                ],
            )

            roster = project_fanout_status(paths, _FANOUT_ID)

            self.assertEqual(roster["units"], [])
            self.assertEqual(roster["unit_count"], 0)
            self.assertIn("no unit events", render_fanout_status_text(roster).lower())

    def test_unknown_fanout_id_raises_naming_the_id(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            _seed_journal(paths, _roster_fixture())

            with self.assertRaises(ValueError) as caught:
                project_fanout_status(paths, "fanout-aaaaaaaaaaaa")

            self.assertIn("fanout-aaaaaaaaaaaa", str(caught.exception))

    def test_malformed_fanout_id_raises_naming_the_id(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            _seed_journal(paths, _roster_fixture())

            with self.assertRaises(ValueError) as caught:
                project_fanout_status(paths, "nope")

            self.assertIn("nope", str(caught.exception))


class _FakeCompleted:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode
        self.stdout = "done"
        self.stderr = ""


def _real_git_runner(argv, **kwargs):
    """Run git for real; answer any agent-CLI spawn with a clean exit."""
    if argv[0] == "git":
        return subprocess.run(argv, **kwargs)
    return _FakeCompleted(0)


class FanoutStatusAgainstRealDispatchTests(unittest.TestCase):
    def test_roster_reads_events_a_real_dispatch_wrote(self) -> None:
        """The roster's unit discovery must match the dispatcher's run_ref convention."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True, text=True)
            (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
            subprocess.run(["git", "add", "seed.txt"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"],
                cwd=repo, check=True, capture_output=True, text=True,
            )
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
            ).stdout.strip()
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            goal = "split the sample feature across agents"
            contract = write_fanout_contract(
                paths,
                build_fanout_contract(
                    goal,
                    [
                        {"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["src/core/"]},
                        {"unit_id": "docs", "title": "Docs", "owner": "claude-code", "file_scope": ["docs/"]},
                    ],
                ),
            )
            dispatch_fanout(
                paths,
                contract,
                goal_text=goal,
                repo_root=repo,
                base_sha=sha,
                runner=_real_git_runner,
                readiness=lambda paths, profile, **kwargs: {"status": "ready", "profile": profile},
            )

            roster = project_fanout_status(paths, str(contract["fanout_id"]))

            by_unit = {unit["unit_id"]: unit for unit in roster["units"]}
            self.assertEqual(sorted(by_unit), ["core", "docs"])
            self.assertEqual(by_unit["core"]["lifecycle_state"], "process_succeeded")
            self.assertEqual(by_unit["core"]["owner"], "codex")
            self.assertEqual(by_unit["docs"]["owner"], "claude-code")
            self.assertTrue(by_unit["core"]["worktree_path"].endswith("repo-fanout-core"))
            # Nothing observed a verification receipt or a validated sidecar.
            self.assertEqual(roster["integration_ready_units"], [])


class FanoutStatusCliTests(unittest.TestCase):
    def test_cli_renders_roster_rows(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            _seed_journal(paths, _roster_fixture())
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, stdout, stderr = run_cli(
                base + ["coding", "fanout", "status", "--fanout-id", _FANOUT_ID],
                output_json=False,
            )

            self.assertEqual(status, 0, stderr)
            self.assertIn("core", stdout)
            self.assertIn("unit_verification_observed", stdout)
            self.assertIn("process_succeeded", stdout)

    def test_cli_json_output_carries_schema_version(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            _seed_journal(paths, _roster_fixture())
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, stdout, stderr = run_cli(
                base + ["coding", "fanout", "status", "--fanout-id", _FANOUT_ID, "--json"]
            )

            self.assertEqual(status, 0, stderr)
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], FANOUT_STATUS_SCHEMA_VERSION)
            self.assertEqual(len(payload["units"]), 3)

    def test_cli_writes_no_state_and_no_events(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            _seed_journal(paths, _roster_fixture())
            before = sorted(
                (str(path.relative_to(root)), path.stat().st_mtime_ns)
                for path in (root / ".omh").rglob("*")
                if path.is_file()
            )
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, _stdout, stderr = run_cli(
                base + ["coding", "fanout", "status", "--fanout-id", _FANOUT_ID],
                output_json=False,
            )

            self.assertEqual(status, 0, stderr)
            after = sorted(
                (str(path.relative_to(root)), path.stat().st_mtime_ns)
                for path in (root / ".omh").rglob("*")
                if path.is_file()
            )
            self.assertEqual(before, after)

    def test_cli_unknown_fanout_id_exits_nonzero_naming_the_id(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            _seed_journal(paths, _roster_fixture())
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, stdout, stderr = run_cli(
                base + ["coding", "fanout", "status", "--fanout-id", "nope"],
                output_json=False,
            )

            self.assertNotEqual(status, 0)
            self.assertIn("nope", stdout + stderr)


class FanoutStatusUnitProgressTests(unittest.TestCase):
    """The supervisor poll loop's inputs: is this unit's WORK moving, and is
    it over? Neither question is a ladder rung, and neither can move
    `lifecycle_state` -- see the module docstring's scoped exception."""

    def _stalled_marker(self, paths: OmhPaths, unit_id: str = "core") -> None:
        write_inflight_marker(paths, _FANOUT_ID, unit_id, {
            "owner": "codex",
            "run_ref": f"{_FANOUT_ID}-{unit_id}",
            "worktree": f"/tmp/wt/{unit_id}",
            "started_at": _stamp(40),
            "unit_state": "progress_stalled",
            "state_reason": "repeated_error:error: unable to read file, retrying (n=<n>)",
            "stalled_for_seconds": "1920",
        })

    def test_a_stalled_marker_reaches_the_json_roster_as_non_terminal(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            _seed_journal(paths, _roster_fixture())
            self._stalled_marker(paths)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, stdout, stderr = run_cli(
                base + ["coding", "fanout", "status", "--fanout-id", _FANOUT_ID, "--json"]
            )

            self.assertEqual(status, 0, stderr)
            payload = json.loads(stdout)
            core = {unit["unit_id"]: unit for unit in payload["units"]}["core"]
            self.assertEqual(core["unit_state"], "progress_stalled")
            self.assertIs(core["terminal"], False)
            self.assertEqual(core["unit_state_source"], "inflight_marker")
            self.assertTrue(core["progress"]["reason"].startswith("repeated_error:"))
            self.assertEqual(core["progress"]["seconds_since_new_output"], 1920)
            # The roster-level stop condition the poll loop reads.
            self.assertIn("core", payload["stuck_units"])
            self.assertIs(payload["all_units_terminal"], False)
            # The ladder is untouched: the marker moved no rung.
            self.assertEqual(core["lifecycle_state"], "unit_verification_observed")

    def test_the_text_roster_names_the_stuck_unit(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            _seed_journal(paths, _roster_fixture())
            self._stalled_marker(paths)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, stdout, stderr = run_cli(
                base + ["coding", "fanout", "status", "--fanout-id", _FANOUT_ID],
                output_json=False,
            )

            self.assertEqual(status, 0, stderr)
            self.assertIn("progress_stalled", stdout)
            self.assertIn("1920s since new output", stdout)
            self.assertIn("not terminal", stdout)
            self.assertIn("Stuck, needs intervention: core", stdout)

    def test_a_dispatch_summary_supplies_the_state_after_exit(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            _seed_journal(paths, _roster_fixture())
            summary_path = fanout_dispatch_summary_path(paths, _FANOUT_ID)
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(json.dumps({
                "fanout_id": _FANOUT_ID,
                "units": [
                    {"unit_id": "core", "unit_state": "verified", "unit_state_reason": "",
                     "progress": {"stalled_for_seconds": 0}},
                    {"unit_id": "docs", "unit_state": "failed", "unit_state_reason": "result_missing",
                     "progress": {"stalled_for_seconds": 12}},
                ],
            }), encoding="utf-8")

            roster = project_fanout_status(paths, _FANOUT_ID)
            by_unit = {unit["unit_id"]: unit for unit in roster["units"]}

            self.assertEqual(by_unit["core"]["unit_state"], "verified")
            self.assertIs(by_unit["core"]["terminal"], True)
            self.assertEqual(by_unit["core"]["unit_state_source"], "dispatch_summary")
            self.assertEqual(by_unit["docs"]["unit_state"], "failed")
            self.assertEqual(by_unit["docs"]["progress"]["reason"], "result_missing")
            self.assertIs(by_unit["docs"]["terminal"], True)
            self.assertEqual(roster["stuck_units"], [])
            # `flaky` has neither marker nor summary row, so the fanout is not
            # done -- absent evidence must never read as finished.
            self.assertEqual(by_unit["flaky"]["unit_state"], "unknown")
            self.assertIs(by_unit["flaky"]["terminal"], False)
            self.assertEqual(by_unit["flaky"]["unit_state_source"], "none")
            self.assertIsNone(by_unit["flaky"]["progress"]["seconds_since_new_output"])
            self.assertIs(roster["all_units_terminal"], False)

    def test_a_unit_refused_before_its_spawn_is_terminal_and_named(self) -> None:
        # The workspace preflight (#1489) refuses a unit before it spawns: the
        # summary row carries a stuck `unit_state` and the preflight's own
        # `reason`, with no marker and no progress evidence. Nothing exists to
        # move it, so reporting it non-terminal would hang a poll loop forever
        # on a unit that never started.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            _seed_journal(paths, _roster_fixture())
            summary_path = fanout_dispatch_summary_path(paths, _FANOUT_ID)
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(json.dumps({
                "fanout_id": _FANOUT_ID,
                "units": [{
                    "unit_id": "core",
                    "status": "worktree_failed",
                    "reason_code": "workspace_preflight_blocked",
                    "failure_kind": "workspace_blocked",
                    "unit_state": "permission_blocked",
                    "reason": "worktree is not writable",
                }],
            }), encoding="utf-8")

            roster = project_fanout_status(paths, _FANOUT_ID)
            core = {unit["unit_id"]: unit for unit in roster["units"]}["core"]

            self.assertEqual(core["unit_state"], "permission_blocked")
            self.assertIs(core["terminal"], True)
            self.assertEqual(core["unit_state_source"], "dispatch_summary")
            # The preflight's own wording survives; a pre-spawn refusal never
            # reached the code that writes `unit_state_reason`.
            self.assertEqual(core["progress"]["reason"], "worktree is not writable")
            self.assertIsNone(core["progress"]["seconds_since_new_output"])
            # Terminal and still needing a human: both are true at once, and
            # the roster says so rather than picking one.
            self.assertIn("core", roster["stuck_units"])
            self.assertIn("needs intervention: core", render_fanout_status_text(roster))

    def test_a_blocked_unit_with_only_a_failure_kind_still_explains_itself(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            _seed_journal(paths, _roster_fixture())
            summary_path = fanout_dispatch_summary_path(paths, _FANOUT_ID)
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(json.dumps({
                "fanout_id": _FANOUT_ID,
                "units": [{"unit_id": "core", "unit_state": "data_missing",
                           "failure_kind": "workspace_blocked"}],
            }), encoding="utf-8")

            core = {u["unit_id"]: u for u in project_fanout_status(paths, _FANOUT_ID)["units"]}["core"]

            self.assertEqual(core["progress"]["reason"], "workspace_blocked")
            self.assertIs(core["terminal"], True)

    def test_a_live_marker_outranks_a_stale_summary_row(self) -> None:
        # A marker means this unit is in flight NOW; a summary row from an
        # earlier dispatch of the same id must not report over it.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            _seed_journal(paths, _roster_fixture())
            summary_path = fanout_dispatch_summary_path(paths, _FANOUT_ID)
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(json.dumps({
                "fanout_id": _FANOUT_ID,
                "units": [{"unit_id": "core", "unit_state": "verified"}],
            }), encoding="utf-8")
            self._stalled_marker(paths)

            roster = project_fanout_status(paths, _FANOUT_ID)
            core = {unit["unit_id"]: unit for unit in roster["units"]}["core"]

            self.assertEqual(core["unit_state"], "progress_stalled")
            self.assertEqual(core["unit_state_source"], "inflight_marker")
            self.assertIs(core["terminal"], False)

    def test_a_roster_with_no_progress_evidence_renders_as_it_always_did(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            _seed_journal(paths, _roster_fixture())

            roster = project_fanout_status(paths, _FANOUT_ID)
            text = render_fanout_status_text(roster)

            for unit in roster["units"]:
                self.assertEqual(unit["unit_state"], "unknown")
                self.assertIs(unit["terminal"], False)
            self.assertNotIn("  work:", text)
            self.assertNotIn("Stuck, needs intervention", text)
            self.assertIs(roster["all_units_terminal"], False)

    def test_a_marker_with_no_assessed_state_claims_nothing(self) -> None:
        # Written before the first stdout snapshot: it proves a spawn, not
        # that the work is moving.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            _seed_journal(paths, _roster_fixture())
            write_inflight_marker(paths, _FANOUT_ID, "core", {
                "owner": "codex", "run_ref": f"{_FANOUT_ID}-core",
                "worktree": "/tmp/wt/core", "started_at": _stamp(1),
            })

            roster = project_fanout_status(paths, _FANOUT_ID)
            core = {unit["unit_id"]: unit for unit in roster["units"]}["core"]

            self.assertEqual(core["unit_state"], "unknown")
            self.assertEqual(core["unit_state_source"], "none")
            self.assertIs(core["terminal"], False)


if __name__ == "__main__":
    unittest.main()
