from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import threading
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli  # noqa: E402

from omh.coding.executor_readiness import (  # noqa: E402
    live_readiness_binding,
    probe_executor_readiness,
)
from omh.coding.executor_capability_snapshots import (  # noqa: E402
    build_executor_capability_snapshot,
    executor_capability_snapshot_path,
    write_executor_capability_snapshot,
)
from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_artifacts import write_fanout_contract  # noqa: E402
from omh.coding.fanout_artifacts import fanout_dispatch_summary_path  # noqa: E402
from omh.coding.fanout_artifacts import fanout_unit_recovery_path  # noqa: E402
from omh.coding.fanout_artifacts import unit_result_path  # noqa: E402
from omh.coding.fanout_journal import (  # noqa: E402
    RESUME_HOLD_DECLINED,
    TERMINAL_DECLINED,
    build_fanout_run_journal,
    plan_fanout_resume,
)
from omh.coding.fanout_dispatch import (  # noqa: E402
    FANOUT_DEPTH_ENV_VAR,
    _integrated_checkout_contains_producer_heads,
    FANOUT_LINEAGE_ENV_VAR,
    _MAX_RECOVERY_PATHS,
    _apply_integration_readiness,
    _owner_skill_discoveries,
    _parse_numstat,
    _stdout_fenced_json_blocks,
    _unit_verification_is_observed,
    dispatch_fanout,
    dispatch_model_preferences_path,
    verify_goal_matches_contract,
)
from omh.coding.verification_execution import VerificationExecutionGate  # noqa: E402
from omh.coding.parallelism_policy import (  # noqa: E402
    FANOUT_MAX_DEPTH_DEFAULT,
    FANOUT_RUN_SPAWN_CEILING_DEFAULT,
)
from omh.coding.executor_progress import read_progress_binding  # noqa: E402
from omh.runtime.artifacts import append_journal_observation, create_run, show_run  # noqa: E402
from omh.system.local_store import atomic_write_json, utc_now  # noqa: E402
from omh.system.output_truncation import resolve_spill_reference  # noqa: E402
from omh.system.paths import OmhPaths  # noqa: E402

_GOAL = "split the sample feature across agents"
_UNITS = [
    {"unit_id": "core", "title": "Core work", "owner": "codex", "file_scope": ["src/core/"]},
    {"unit_id": "docs", "title": "Docs work", "owner": "claude-code", "file_scope": ["docs/"]},
    {"unit_id": "tests", "title": "Test work", "owner": "codex", "file_scope": ["tests/"], "depends_on": ["core"]},
]


def _git(repo: Path, *argv: str) -> None:
    subprocess.run(["git", *argv], cwd=str(repo), check=True, capture_output=True, text=True)


def _make_repo(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    # One tracked file at the base commit, so a unit that MOVES it produces a
    # rename git actually detects rather than an add/delete pair.
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "seed.txt")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout.strip()
    return repo, sha


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _agent_runner(*, fail_units: set[str] | None = None, timeout_units: set[str] | None = None):
    """Route git commands to the real subprocess; fake agent CLI spawns."""

    spawned: list[list[str]] = []

    def runner(argv, **kwargs):
        if argv[0] == "git":
            return subprocess.run(argv, **kwargs)
        spawned.append(list(argv))
        prompt = " ".join(argv)
        for unit_id in timeout_units or set():
            if "Work unit:" in prompt and unit_id in prompt:
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 0))
        for unit_id in fail_units or set():
            if unit_id in prompt:
                return _FakeCompleted(1, f"unit {unit_id} failed")
        return _FakeCompleted(0, "done")

    runner.spawned = spawned
    return runner


def _ready(paths, profile, **kwargs):
    return {"status": "ready", "profile": profile}


def _unit_result_payload(contract, sha: str, unit_id: str = "core", **overrides):
    unit = next(entry for entry in contract["units"] if entry["unit_id"] == unit_id)
    payload = {
        "schema_version": "fanout_unit_result/v1",
        "unit_id": unit_id,
        "run_id": unit["run_ref"],
        "fanout_id": contract["fanout_id"],
        "base_sha": sha,
        "head_sha": sha,
        "process_status": "process_succeeded",
        "changed_paths": [],
        "checks": [],
        "findings": [],
    }
    payload.update(overrides)
    return payload


def _stub_executor_script(root: Path) -> Path:
    """Real subprocess fixture that writes, omits, or corrupts a sidecar."""
    script = root / "stub_executor.py"
    script.write_text(
        """import json\nimport pathlib\nimport sys\n\nmode, path, payload = sys.argv[1:]\ntarget = pathlib.Path(path)\nif mode != \"missing\":\n    target.parent.mkdir(parents=True, exist_ok=True)\n    if mode == \"corrupt\":\n        target.write_text(\"{not-json\", encoding=\"utf-8\")\n    else:\n        target.write_text(json.dumps(json.loads(payload)), encoding=\"utf-8\")\n""",
        encoding="utf-8",
    )
    return script


def _sidecar_script_runner(script: Path, mode: str, sidecar: Path, payload: dict[str, object]):
    spawned: list[list[str]] = []

    def runner(argv, **kwargs):
        if argv[0] == "git":
            return subprocess.run(argv, **kwargs)
        spawned.append(list(argv))
        return subprocess.run(
            [sys.executable, str(script), mode, str(sidecar), json.dumps(payload)],
            cwd=kwargs.get("cwd"),
            text=True,
            capture_output=True,
            timeout=kwargs.get("timeout"),
        )

    runner.spawned = spawned
    return runner


_SECRET = "s3cret-source-line-that-must-never-leave-the-worktree"


def _writing_runner(
    *,
    fail_units: set[str] | None = None,
    write_units: set[str] | None = None,
    timeout_units: set[str] | None = None,
    break_git_diff: bool = False,
    break_git_add: bool = False,
    latin1_units: set[str] | None = None,
    unicode_units: set[str] | None = None,
    wide_units: set[str] | None = None,
    rename_units: set[str] | None = None,
):
    """Like `_agent_runner`, but the fake agent leaves real files behind.

    Units named in `write_units` write a file into their worktree before the
    spawn returns, which is what gives the recovery probe something to measure.
    """
    spawned: list[list[str]] = []

    def owns(prompt: str, unit_id: str) -> bool:
        # The branch line is the only unit-unique string in the prompt: every
        # unit's do_not_touch list names its siblings' paths, so a bare
        # substring match on the id fires for the wrong unit.
        return f"agent/{unit_id} in the current worktree" in prompt

    def runner(argv, **kwargs):
        if argv[0] == "git":
            if break_git_diff and "diff" in argv:
                return _FakeCompleted(128, "")
            # `argv[:2]`, not `"add" in argv`: `git worktree add` creates the
            # unit worktree, and faulting that would fail the unit before the
            # recovery probe is ever reached.
            if break_git_add and argv[:2] == ["git", "add"]:
                return _FakeCompleted(128, "")
            return subprocess.run(argv, **kwargs)
        spawned.append(list(argv))
        prompt = " ".join(argv)
        cwd = Path(str(kwargs.get("cwd", ".")))
        for unit_id in write_units or set():
            if owns(prompt, unit_id):
                (cwd / f"{unit_id}_partial.py").write_text(f"# {_SECRET}\nvalue = 1\n", encoding="utf-8")
        for unit_id in latin1_units or set():
            if owns(prompt, unit_id):
                # Bytes that are not valid UTF-8, in a file git treats as TEXT
                # (binary detection needs a NUL in the first 8000 bytes). This
                # is what used to abort the whole dispatch.
                (cwd / f"{unit_id}_latin1.txt").write_bytes("caf\xe9 partial work\n".encode("latin-1"))
        for unit_id in unicode_units or set():
            if owns(prompt, unit_id):
                (cwd / "análisis_你好.py").write_text("value = 1\n", encoding="utf-8")
        for unit_id in wide_units or set():
            if owns(prompt, unit_id):
                for index in range(_MAX_RECOVERY_PATHS + 3):
                    (cwd / f"{unit_id}_{index:03d}.py").write_text(f"value = {index}\n", encoding="utf-8")
        for unit_id in rename_units or set():
            if owns(prompt, unit_id):
                # `seed.txt` is committed at base, so moving it is a rename
                # git detects rather than an add/delete pair.
                (cwd / "seed_moved.txt").write_text((cwd / "seed.txt").read_text(encoding="utf-8"), encoding="utf-8")
                (cwd / "seed.txt").unlink()
        for unit_id in timeout_units or set():
            if owns(prompt, unit_id):
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 0))
        for unit_id in fail_units or set():
            if owns(prompt, unit_id):
                return _FakeCompleted(1, f"unit {unit_id} failed")
        return _FakeCompleted(0, "done")

    runner.spawned = spawned
    return runner


class FanoutUnitResultIntakeTests(unittest.TestCase):
    def _setup(self, tmp: str):
        root = Path(tmp)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, _UNITS))
        sidecar = unit_result_path(paths, contract["fanout_id"], "core")
        script = _stub_executor_script(root)
        return paths, repo, sha, contract, sidecar, script

    def _dispatch(self, paths, repo, sha, contract, runner):
        return dispatch_fanout(
            paths,
            contract,
            goal_text=_GOAL,
            repo_root=repo,
            base_sha=sha,
            only_units=["core"],
            runner=runner,
            readiness=_ready,
        )

    def test_valid_sidecar_is_validated_journaled_and_prompted_at_exact_path(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, sidecar, script = self._setup(tmp)
            payload = _unit_result_payload(contract, sha)
            runner = _sidecar_script_runner(script, "valid", sidecar, payload)

            summary = self._dispatch(paths, repo, sha, contract, runner)

            core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]
            self.assertTrue(core["process_succeeded"])
            self.assertTrue(core["result_schema_valid"])
            self.assertEqual(core["unit_result_status"], "unit_result_validated")
            self.assertEqual(core["unit_result"]["schema_version"], "fanout_unit_result/v1")
            prompt = " ".join(runner.spawned[0])
            self.assertIn(str(sidecar), prompt)
            self.assertIn("observed_by", prompt)
            self.assertIn("observation_source", prompt)
            events = [event["event"] for event in show_run(paths, core["run_ref"])["journal_events"]]
            self.assertIn("unit_result_validated", events)

    def test_a_declined_unit_reaches_the_journal_distinctly_and_resume_holds_it(self) -> None:
        # #H end-to-end: a unit that validly reports `process_declined` must
        # (a) never be selected by a resume plan and (b) land in the journal
        # under its own terminal state, not folded into `failed`.
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, sidecar, script = self._setup(tmp)
            payload = _unit_result_payload(
                contract, sha, process_status="process_declined", decline_reason="target_not_found"
            )

            def runner(argv, **kwargs):
                if argv[0] == "git":
                    return subprocess.run(argv, **kwargs)
                sidecar.parent.mkdir(parents=True, exist_ok=True)
                sidecar.write_text(json.dumps(payload), encoding="utf-8")
                return _FakeCompleted(3, "cannot be done: target not found")

            summary = self._dispatch(paths, repo, sha, contract, runner)

            core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]
            self.assertFalse(core["process_succeeded"])
            self.assertTrue(core["result_schema_valid"])
            self.assertEqual(core["unit_result"]["process_status"], "process_declined")
            self.assertEqual(core["unit_result"]["decline_reason"], "target_not_found")

            journal = build_fanout_run_journal(summary)
            row = {entry["unit_id"]: entry for entry in journal["units"]}["core"]
            self.assertEqual(row["terminal_state"], TERMINAL_DECLINED)
            self.assertEqual(row["decline_reason"], "target_not_found")

            plan = plan_fanout_resume(journal, order=["core"], depends_on={"core": []})
            self.assertEqual(plan["decisions"][0]["action"], RESUME_HOLD_DECLINED)
            self.assertEqual(plan["selected_units"], [])
            self.assertIn("core", plan["held_units"])

    def test_missing_sidecar_is_explicit_without_erasing_process_success(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, sidecar, script = self._setup(tmp)
            runner = _sidecar_script_runner(
                script, "missing", sidecar, _unit_result_payload(contract, sha)
            )

            summary = self._dispatch(paths, repo, sha, contract, runner)

            core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]
            self.assertTrue(core["process_succeeded"])
            self.assertFalse(core["result_schema_valid"])
            self.assertEqual(core["unit_result_status"], "unit_result_missing")
            self.assertNotIn("unit_result", core)
            events = show_run(paths, core["run_ref"])["journal_events"]
            missing = next(event for event in events if event["event"] == "unit_result_missing")
            self.assertEqual(missing["status"], "observed")
            self.assertEqual(missing["evidence_refs"], [])
            self.assertIn("missing", missing["summary"])

    def _stdout_block_runner(self, stdout: str, *, sidecar_payload: dict[str, object] | None = None, sidecar: Path | None = None):
        """Fake agent spawn that emits `stdout` and optionally writes a sidecar."""
        spawned: list[list[str]] = []

        def runner(argv, **kwargs):
            if argv[0] == "git":
                return subprocess.run(argv, **kwargs)
            spawned.append(list(argv))
            if sidecar_payload is not None and sidecar is not None:
                sidecar.parent.mkdir(parents=True, exist_ok=True)
                sidecar.write_text(json.dumps(sidecar_payload), encoding="utf-8")
            return _FakeCompleted(0, stdout)

        runner.spawned = spawned
        return runner

    def test_missing_sidecar_falls_back_to_validated_stdout_block(self) -> None:
        """The return protocol's redundant fenced block is machine-read when the
        contracted sidecar file never appears: same schema, same identity
        validation, and the LAST block is the return (the report ends with it)."""
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, sidecar, script = self._setup(tmp)
            payload = _unit_result_payload(contract, sha)
            stdout = (
                "Earlier tool output that quotes a block:\n"
                "```json\n{\"not\": \"the return\"}\n```\n"
                "Final report prose.\n"
                "```json\n" + json.dumps(payload, indent=2) + "\n```\n"
            )
            runner = self._stdout_block_runner(stdout)

            summary = self._dispatch(paths, repo, sha, contract, runner)

            core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]
            self.assertTrue(core["process_succeeded"])
            self.assertTrue(core["result_schema_valid"])
            self.assertEqual(core["unit_result_status"], "unit_result_validated")
            self.assertEqual(core["unit_result_source"], "stdout_fenced_block")
            self.assertEqual(core["unit_result"]["schema_version"], "fanout_unit_result/v1")
            events = show_run(paths, core["run_ref"])["journal_events"]
            validated = next(event for event in events if event["event"] == "unit_result_validated")
            self.assertEqual(validated["status"], "observed")
            self.assertEqual(validated["evidence_refs"], [])
            self.assertIn("stdout fenced json block", validated["summary"])

    def test_stdout_block_faces_the_same_identity_validation(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, sidecar, script = self._setup(tmp)
            payload = _unit_result_payload(contract, sha, base_sha="f" * 40)
            stdout = "```json\n" + json.dumps(payload) + "\n```\n"
            runner = self._stdout_block_runner(stdout)

            summary = self._dispatch(paths, repo, sha, contract, runner)

            core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]
            self.assertTrue(core["process_succeeded"])
            self.assertFalse(core["result_schema_valid"])
            self.assertEqual(core["unit_result_status"], "unit_result_invalid")
            self.assertIn("stdout fenced json block", core["unit_result_error"])
            self.assertIn("base_sha", core["unit_result_error"])
            self.assertNotIn("unit_result", core)

    def test_a_written_sidecar_stays_primary_over_a_disagreeing_stdout_block(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, sidecar, script = self._setup(tmp)
            stdout = "```json\n{\"schema_version\": \"garbage\"}\n```\n"
            runner = self._stdout_block_runner(
                stdout,
                sidecar_payload=_unit_result_payload(contract, sha),
                sidecar=sidecar,
            )

            summary = self._dispatch(paths, repo, sha, contract, runner)

            core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]
            self.assertTrue(core["result_schema_valid"])
            self.assertEqual(core["unit_result_source"], "sidecar")

    def test_fenced_block_scan_takes_closed_blocks_only(self) -> None:
        self.assertEqual(_stdout_fenced_json_blocks(""), [])
        self.assertEqual(_stdout_fenced_json_blocks("prose only\n"), [])
        text = "a\n```json\n{\"x\": 1}\n```\nb\n  ```json  \n{\"y\": 2}\n```\n```json\n{\"unclosed\": true}\n"
        self.assertEqual(_stdout_fenced_json_blocks(text), ['{"x": 1}', '{"y": 2}'])

    def test_invalid_sidecar_names_the_validator_field_error(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, sidecar, script = self._setup(tmp)
            payload = _unit_result_payload(
                contract,
                sha,
                checks=[
                    {
                        "command": "uv run python -m unittest",
                        "status": "green",
                        "evidence_ref": None,
                        "reported_by": "executor",
                        "observed_by": None,
                        "observation_source": None,
                    }
                ],
            )
            runner = _sidecar_script_runner(script, "valid", sidecar, payload)

            summary = self._dispatch(paths, repo, sha, contract, runner)

            core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]
            self.assertTrue(core["process_succeeded"])
            self.assertFalse(core["result_schema_valid"])
            self.assertEqual(core["unit_result_status"], "unit_result_invalid")
            self.assertIn("checks[0].status", core["unit_result_error"])
            self.assertNotIn("unit_result", core)
            events = show_run(paths, core["run_ref"])["journal_events"]
            invalid = next(event for event in events if event["event"] == "unit_result_invalid")
            self.assertEqual(invalid["status"], "observed")
            self.assertEqual(invalid["evidence_refs"], [str(sidecar)])
            self.assertIn("checks[0].status", invalid["summary"])

    def test_foreign_identity_sidecar_is_invalid_and_never_echoed(self) -> None:
        foreign_values = {
            "unit_id": "docs",
            "run_id": "fanout-ffffffffffff-docs",
            "fanout_id": "fanout-ffffffffffff",
            "base_sha": "f" * 40,
        }
        for field, foreign_value in foreign_values.items():
            with self.subTest(field=field), TemporaryDirectory() as tmp:
                paths, repo, sha, contract, sidecar, script = self._setup(tmp)
                payload = _unit_result_payload(contract, sha, **{field: foreign_value})
                runner = _sidecar_script_runner(script, "valid", sidecar, payload)

                summary = self._dispatch(paths, repo, sha, contract, runner)

                core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]
                self.assertFalse(core["result_schema_valid"])
                self.assertEqual(core["unit_result_status"], "unit_result_invalid")
                self.assertIn(field, core["unit_result_error"])
                self.assertIn(repr(foreign_value), core["unit_result_error"])
                self.assertNotIn("unit_result", core)

    def test_executor_cannot_launder_a_check_as_dispatcher_observed(self) -> None:
        violations = (
            {
                "reported_by": "dispatcher",
                "observed_by": None,
                "observation_source": None,
            },
            {
                "reported_by": "executor",
                "observed_by": "dispatcher",
                "observation_source": "journal:invented-observation",
            },
            {
                "reported_by": "executor",
                "observed_by": None,
                "observation_source": "journal:invented-observation",
            },
        )
        for violation in violations:
            with self.subTest(violation=violation), TemporaryDirectory() as tmp:
                paths, repo, sha, contract, sidecar, script = self._setup(tmp)
                payload = _unit_result_payload(
                    contract,
                    sha,
                    checks=[
                        {
                            "command": "uv run python -m unittest",
                            "status": "passed",
                            "evidence_ref": "executor:test-output",
                            **violation,
                        }
                    ],
                )
                runner = _sidecar_script_runner(script, "valid", sidecar, payload)

                summary = self._dispatch(paths, repo, sha, contract, runner)

                core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]
                self.assertFalse(core["result_schema_valid"])
                self.assertEqual(core["unit_result_status"], "unit_result_invalid")
                self.assertIn("checks[0].reported_by", core["unit_result_error"])
                self.assertNotIn("unit_result", core)
                self.assertFalse(core["unit_verification_observed"])
                self.assertFalse(core["integration_ready"])

    def test_executor_pass_report_stays_reported_not_observed_and_not_ready(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, sidecar, script = self._setup(tmp)
            payload = _unit_result_payload(
                contract,
                sha,
                checks=[
                    {
                        "command": "uv run python -m unittest",
                        "status": "passed",
                        "evidence_ref": "executor:test-output",
                        "reported_by": "executor",
                        "observed_by": None,
                        "observation_source": None,
                    }
                ],
            )
            runner = _sidecar_script_runner(script, "valid", sidecar, payload)

            summary = self._dispatch(paths, repo, sha, contract, runner)

            core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]
            check = core["unit_result"]["checks"][0]
            self.assertEqual(check["reported_by"], "executor")
            self.assertIsNone(check["observed_by"])
            self.assertIsNone(check["observation_source"])
            self.assertFalse(core["unit_verification_observed"])
            self.assertFalse(core["integration_ready"])
            self.assertEqual(summary["integration_ready_units"], [])

    def test_executor_unknown_keys_do_not_reach_persisted_summary(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, sidecar, script = self._setup(tmp)
            payload = _unit_result_payload(
                contract,
                sha,
                executor_secret="must-not-persist",
                checks=[
                    {
                        "command": "uv run python -m unittest",
                        "status": "passed",
                        "evidence_ref": None,
                        "reported_by": "executor",
                        "observed_by": None,
                        "observation_source": None,
                        "executor_note": "must-not-persist-either",
                    }
                ],
            )
            runner = _sidecar_script_runner(script, "valid", sidecar, payload)

            self._dispatch(paths, repo, sha, contract, runner)

            stored = json.loads(
                fanout_dispatch_summary_path(paths, contract["fanout_id"]).read_text(encoding="utf-8")
            )
            serialized = json.dumps(stored)
            self.assertNotIn("executor_secret", serialized)
            self.assertNotIn("executor_note", serialized)
            self.assertNotIn("must-not-persist", serialized)

    def test_unit_result_path_is_contained_and_rejects_escaping_ids(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")
            expected = paths.fanout_contracts_dir / "fanout-0123456789ab" / "unit_results" / "core.json"
            self.assertEqual(unit_result_path(paths, "fanout-0123456789ab", "core"), expected)
            with self.assertRaises(ValueError):
                unit_result_path(paths, "fanout-0123456789ab", "../escape")

    def test_verification_receipt_buried_beyond_show_run_tail_remains_observed(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")
            run_ref = "fanout-0123456789ab-core"
            create_run(paths, {"run_id": run_ref, "skill": "fanout-unit", "harness": "test"})
            base = {
                "target_type": "run",
                "target_id": run_ref,
                "run_id": run_ref,
                "status": "observed",
                "worker_ref": "core",
            }
            append_journal_observation(paths, {**base, "event": "worker_dispatch"})
            append_journal_observation(paths, {**base, "event": "worker_result"})
            append_journal_observation(paths, {**base, "event": "unit_verification_observed"})
            for index in range(26):
                append_journal_observation(
                    paths,
                    {**base, "event": "worker_result", "summary": f"filler {index}"},
                )

            self.assertNotIn(
                "unit_verification_observed",
                [event["event"] for event in show_run(paths, run_ref)["journal_events"]],
            )
            self.assertTrue(_unit_verification_is_observed(paths, run_ref))


class FanoutDispatchEngineTests(unittest.TestCase):
    def _setup(self, tmp: str):
        root = Path(tmp)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, _UNITS))
        return paths, repo, sha, contract

    def test_review_dispatch_budget_is_attempt_scoped(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            by_unit = {entry["unit_id"]: entry for entry in contract["units"]}
            by_unit["core"]["handoff"]["model_route"] = {
                "status": "routed",
                "role": "code-review",
                "selected_model": "",
                "selected_reasoning_effort": "",
            }
            by_unit["docs"]["handoff"]["model_route"] = {
                "status": "routed",
                "role": "code-reviewer",
                "selected_model": "",
                "selected_reasoning_effort": "",
            }

            first = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                concurrency=1,
                only_units=["core", "docs"],
                runner=_agent_runner(),
                readiness=_ready,
                goal_attempt_id="attempt-1",
                review_dispatch_budget=1,
            )
            second_runner = _agent_runner()
            second = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                concurrency=1,
                only_units=["core", "docs"],
                runner=second_runner,
                readiness=_ready,
                goal_attempt_id="attempt-1",
                review_dispatch_budget=1,
            )

            first_statuses = [entry["status"] for entry in first["units"]]
            second_by_unit = {entry["unit_id"]: entry for entry in second["units"]}
            self.assertEqual(first_statuses.count("completed"), 1)
            self.assertEqual(first_statuses.count("review_dispatch_budget_exhausted"), 1)
            self.assertEqual(second_by_unit["docs"]["status"], "review_dispatch_budget_exhausted")
            self.assertEqual(second_by_unit["docs"]["reason_code"], "review_dispatch_no_progress")
            self.assertEqual(second_runner.spawned, [])

    def test_review_dispatch_budget_reservation_is_atomic(self) -> None:
        import threading as _threading

        goal = "atomically reserve one review dispatch"
        units = [
            {
                "unit_id": unit_id,
                "title": unit_id,
                "owner": "codex",
                "file_scope": [f"review/{unit_id}/"],
                "role": role,
            }
            for unit_id, role in (("review-a", "code-review"), ("review-b", "code-reviewer"))
        ]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            contract = write_fanout_contract(paths, build_fanout_contract(goal, units))
            ready_barrier = _threading.Barrier(2)
            runner = _agent_runner()

            def both_ready(paths_, profile, **kwargs):
                ready_barrier.wait(timeout=2)
                return {"status": "ready", "profile": profile}

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=goal,
                repo_root=repo,
                base_sha=sha,
                concurrency=2,
                runner=runner,
                readiness=both_ready,
                goal_attempt_id="attempt-atomic",
                review_dispatch_budget=1,
            )

            statuses = [entry["status"] for entry in summary["units"]]
            self.assertEqual(statuses.count("completed"), 1)
            self.assertEqual(statuses.count("review_dispatch_budget_exhausted"), 1)
            self.assertEqual(len(runner.spawned), 1)

    def test_review_dispatch_budget_is_independent_per_normalized_role(self) -> None:
        goal = "budget distinct review roles independently"
        role_aliases = (
            ("code-review", "CODE_REVIEWER"),
            ("manual-qa", "MANUAL_QA"),
            ("final-gate", "FINAL_GATE"),
        )
        units = [
            {
                "unit_id": f"lane-{role_index}-{alias_index}",
                "title": alias,
                "owner": "codex",
                "file_scope": [f"review/{role_index}/{alias_index}/"],
                "role": alias,
            }
            for role_index, aliases in enumerate(role_aliases)
            for alias_index, alias in enumerate(aliases)
        ]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            contract = write_fanout_contract(
                paths,
                build_fanout_contract(
                    goal,
                    units,
                    spawn_plan={
                        "why_parallel": "Three independent review roles inspect disjoint evidence.",
                        "why_not_single_unit": "One reviewer role cannot substitute for the other gates.",
                        "independence": "Each role reads a separate review scope.",
                        "expected_evidence_shape": "One result for each role and spelling alias.",
                    },
                ),
            )

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=goal,
                repo_root=repo,
                base_sha=sha,
                concurrency=1,
                runner=_agent_runner(),
                readiness=_ready,
                goal_attempt_id="attempt-aliases",
                review_dispatch_budget=1,
            )

            statuses = [entry["status"] for entry in summary["units"]]
            self.assertEqual(statuses.count("completed"), 3)
            self.assertEqual(statuses.count("review_dispatch_budget_exhausted"), 3)
            exhausted_roles = {
                entry["review_dispatch_budget"]["role"]
                for entry in summary["units"]
                if entry["status"] == "review_dispatch_budget_exhausted"
            }
            self.assertEqual(exhausted_roles, {"code-review", "manual-qa", "final-gate"})

    def test_spawn_ceiling_denial_does_not_consume_durable_review_allowance(self) -> None:
        goal = "preserve review allowance after spawn ceiling denial"
        units = [
            {
                "unit_id": unit_id,
                "title": unit_id,
                "owner": "codex",
                "file_scope": [f"review/{unit_id}/"],
                "role": "code-review",
            }
            for unit_id in ("review-a", "review-b")
        ]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            contract = write_fanout_contract(paths, build_fanout_contract(goal, units))
            common = {
                "goal_text": goal,
                "repo_root": repo,
                "base_sha": sha,
                "concurrency": 1,
                "readiness": _ready,
                "goal_attempt_id": "attempt-ceiling",
                "review_dispatch_budget": 2,
                "spawn_ceiling": 1,
            }

            first = dispatch_fanout(paths, contract, runner=_agent_runner(), **common)
            second_runner = _agent_runner()
            second = dispatch_fanout(
                paths,
                contract,
                only_units=["review-b"],
                runner=second_runner,
                **common,
            )

            first_by_unit = {entry["unit_id"]: entry for entry in first["units"]}
            second_by_unit = {entry["unit_id"]: entry for entry in second["units"]}
            self.assertEqual(first_by_unit["review-a"]["status"], "completed")
            self.assertEqual(first_by_unit["review-b"]["status"], "spawn_ceiling_reached")
            self.assertEqual(second_by_unit["review-b"]["status"], "completed")
            self.assertEqual(len(second_runner.spawned), 1)

    def test_review_dispatch_budget_charges_only_after_readiness(self) -> None:
        goal = "charge only review lanes that pass readiness"
        units = [
            {
                "unit_id": "denied-review",
                "title": "Denied review",
                "owner": "codex",
                "file_scope": ["review/denied/"],
                "role": "review",
            },
            {
                "unit_id": "ready-review",
                "title": "Ready review",
                "owner": "claude-code",
                "file_scope": ["review/ready/"],
                "role": "review",
            },
        ]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            contract = write_fanout_contract(paths, build_fanout_contract(goal, units))

            def owner_readiness(paths_, profile, **kwargs):
                return {"status": "missing" if profile == "codex" else "ready", "profile": profile}

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=goal,
                repo_root=repo,
                base_sha=sha,
                concurrency=1,
                runner=_agent_runner(),
                readiness=owner_readiness,
                goal_attempt_id="attempt-readiness",
                review_dispatch_budget=1,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["denied-review"]["status"], "executor_not_ready")
            self.assertEqual(by_unit["ready-review"]["status"], "completed")

    def test_review_dispatch_budget_does_not_charge_non_review_lanes(self) -> None:
        goal = "leave implementation lanes outside review accounting"
        units = [
            {
                "unit_id": f"build-{index}",
                "title": f"Build {index}",
                "owner": "codex",
                "file_scope": [f"src/{index}/"],
                "role": "implementation",
            }
            for index in range(2)
        ]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            contract = write_fanout_contract(paths, build_fanout_contract(goal, units))
            runner = _agent_runner()

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=goal,
                repo_root=repo,
                base_sha=sha,
                concurrency=2,
                runner=runner,
                readiness=_ready,
                goal_attempt_id="attempt-build",
                review_dispatch_budget=1,
            )

            self.assertTrue(all(entry["status"] == "completed" for entry in summary["units"]))
            self.assertEqual(len(runner.spawned), 2)

    def test_review_dispatch_budget_resets_only_for_progressed_new_attempt(self) -> None:
        goal = "reset review budget only after progress"
        units = [
            {
                "unit_id": f"review-{index}",
                "title": f"Review {index}",
                "owner": "codex",
                "file_scope": [f"review/{index}/"],
                "role": "review",
            }
            for index in range(2)
        ]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            contract = write_fanout_contract(paths, build_fanout_contract(goal, units))
            common = {
                "goal_text": goal,
                "repo_root": repo,
                "base_sha": sha,
                "concurrency": 1,
                "readiness": _ready,
                "review_dispatch_budget": 1,
            }
            dispatch_fanout(
                paths,
                contract,
                runner=_agent_runner(),
                goal_attempt_id="attempt-1",
                **common,
            )

            denied_runner = _agent_runner()
            denied = dispatch_fanout(
                paths,
                contract,
                runner=denied_runner,
                goal_attempt_id="attempt-2",
                **common,
            )
            progressed_runner = _agent_runner()
            progressed = dispatch_fanout(
                paths,
                contract,
                runner=progressed_runner,
                goal_attempt_id="attempt-2",
                goal_attempt_progressed=True,
                **common,
            )

            denied_by_unit = {entry["unit_id"]: entry for entry in denied["units"]}
            progressed_by_unit = {entry["unit_id"]: entry for entry in progressed["units"]}
            self.assertEqual(denied_by_unit["review-1"]["status"], "review_dispatch_budget_exhausted")
            self.assertEqual(denied_by_unit["review-1"]["reason_code"], "review_dispatch_attempt_not_progressed")
            self.assertEqual(denied_runner.spawned, [])
            self.assertEqual(progressed_by_unit["review-1"]["status"], "completed")
            self.assertEqual(len(progressed_runner.spawned), 1)

    def test_summary_discloses_how_the_pool_width_was_chosen(self) -> None:
        # The command layer resolves the parallelism policy and hands the
        # resolution in; the dispatch record must answer "why did only N run
        # at once" without re-deriving policy state after the fact.
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["core"],
                runner=_agent_runner(),
                readiness=_ready,
                per_owner_lanes={"codex": 2},
                concurrency_policy={
                    "applied": 5,
                    "source": "policy_default",
                    "global_concurrency": 8,
                    "clamped": False,
                },
            )

            self.assertEqual(summary["concurrency"]["applied"], 5)
            self.assertEqual(summary["concurrency"]["source"], "policy_default")

    def test_owner_gate_limits_simultaneous_spawns_for_a_configured_owner(self) -> None:
        # Enforcement, not just the summary echo: with a codex lane width of
        # one and three parallel-safe codex units, no two codex spawns may
        # ever overlap, while the unconfigured claude-code owner is ungated
        # and the whole batch still completes.
        import threading as _threading
        import time as _time

        goal = "gate the codex lane"
        units = [
            {"unit_id": f"cx{index}", "title": f"Codex {index}", "owner": "codex", "file_scope": [f"src/cx{index}/"]}
            for index in range(3)
        ] + [{"unit_id": "cc", "title": "Claude work", "owner": "claude-code", "file_scope": ["docs/"]}]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            contract = write_fanout_contract(paths, build_fanout_contract(goal, units))
            lock = _threading.Lock()
            live = {"codex": 0}
            max_live = {"codex": 0}

            def runner(argv, **kwargs):
                if argv[0] == "git":
                    return subprocess.run(argv, **kwargs)
                is_codex = argv[0] == "codex"
                if is_codex:
                    with lock:
                        live["codex"] += 1
                        max_live["codex"] = max(max_live["codex"], live["codex"])
                _time.sleep(0.05)
                if is_codex:
                    with lock:
                        live["codex"] -= 1
                return _FakeCompleted(0, "done")

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=goal,
                repo_root=repo,
                base_sha=sha,
                concurrency=4,
                per_owner_lanes={"codex": 1},
                runner=runner,
                readiness=_ready,
            )

            self.assertEqual(max_live["codex"], 1)
            statuses = {entry["unit_id"]: entry["process_succeeded"] for entry in summary["units"]}
            self.assertTrue(all(statuses.values()), statuses)

    def test_summary_omits_the_concurrency_block_when_none_was_resolved(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["core"],
                runner=_agent_runner(),
                readiness=_ready,
            )

            self.assertNotIn("concurrency", summary)

    def test_summary_process_succeeded_only_on_exit_zero(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["core"],
                runner=_agent_runner(),
                readiness=_ready,
            )

            core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]
            self.assertTrue(core["process_succeeded"])
            self.assertFalse(core["result_schema_valid"])
            self.assertFalse(core["unit_verification_observed"])
            self.assertFalse(core["integration_ready"])
            self.assertEqual(summary["integration_ready_units"], [])

    def test_summary_nonzero_exit_has_no_success_or_downstream_status(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["core"],
                runner=_agent_runner(fail_units={"Core"}),
                readiness=_ready,
            )

            core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]
            self.assertFalse(core["process_succeeded"])
            self.assertFalse(core["result_schema_valid"])
            self.assertFalse(core["unit_verification_observed"])
            self.assertFalse(core["integration_ready"])
            self.assertEqual(summary["integration_ready_units"], [])

    def test_integration_ready_requires_full_ladder_in_merge_order(self) -> None:
        units = [
            {
                "unit_id": unit_id,
                "process_succeeded": True,
                "result_schema_valid": True,
                "unit_verification_observed": True,
            }
            for unit_id in ("core", "docs")
        ]

        _apply_integration_readiness(units)

        self.assertTrue(units[0]["integration_ready"])
        self.assertTrue(units[1]["integration_ready"])

        units[0]["unit_verification_observed"] = False
        _apply_integration_readiness(units)

        self.assertFalse(units[0]["integration_ready"])
        self.assertFalse(units[1]["integration_ready"])

    def test_choice_required_route_blocks_the_unit_fail_closed(self) -> None:
        """A frozen choice_required route must never dispatch on the silent
        executor default: the unit reports model_choice_required, stays
        un-merge-ready, and its dependents block (issue #716, option 2)."""
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            for unit in contract["units"]:
                if unit["unit_id"] == "core":
                    unit["handoff"]["model_route"] = {
                        "schema_version": "coding_model_route/v2",
                        "status": "choice_required",
                        "provenance": "role_unchained",
                        "selected_model": "",
                        "selected_reasoning_effort": "",
                    }
            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=_agent_runner(),
                readiness=_ready,
            )
            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["core"]["status"], "model_choice_required")
            self.assertFalse(by_unit["core"]["integration_ready"])
            self.assertIn("re-prepare", by_unit["core"]["reason"])
            self.assertNotIn("core", summary["integration_ready_units"])
            # The dependent of the blocked unit must not build on an
            # unstarted base; the independent unit still completes.
            self.assertNotEqual(by_unit["tests"]["status"], "completed")
            self.assertEqual(by_unit["docs"]["status"], "completed")

    def test_happy_path_dispatches_units_and_records_observed_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            runner = _agent_runner()

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=runner,
                readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["core"]["status"], "completed")
            self.assertEqual(by_unit["docs"]["status"], "completed")
            self.assertEqual(by_unit["tests"]["status"], "completed")
            self.assertEqual(summary["integration_ready_units"], [])
            self.assertFalse(summary["auto_merge"])
            self.assertIn("exited 0", summary["dependency_bar"])
            # observed evidence per unit run
            shown = show_run(paths, by_unit["core"]["run_ref"])
            events = [e["event"] for e in shown["journal_events"]]
            self.assertIn("executor_dispatch_observed", events)
            self.assertIn("executor_result_observed", events)
            # worktrees created per unit, never merged
            self.assertTrue((repo.parent / "repo-fanout-core").exists())
            self.assertNotIn(["git", "merge"], runner.spawned)

    def test_dependent_unit_waits_and_failure_blocks_only_dependents(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=_agent_runner(fail_units={"Core"}),
                readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["core"]["status"], "failed")
            self.assertEqual(by_unit["tests"]["status"], "blocked_by_dependency")
            self.assertEqual(by_unit["docs"]["status"], "completed")
            self.assertEqual(summary["integration_ready_units"], [])

    def test_timeout_records_failed_unit(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                timeout=5,
                runner=_agent_runner(timeout_units={"Docs"}),
                readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["docs"]["status"], "failed")
            self.assertEqual(by_unit["docs"]["exit_code"], 124)

    def test_readiness_refusal_skips_unit_without_fabricating_a_run(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            def not_ready(paths_, profile, **kwargs):
                return {"status": "missing", "profile": profile}

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=_agent_runner(),
                readiness=not_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["core"]["status"], "executor_not_ready")
            self.assertFalse((paths.runtime_runs_dir / by_unit["core"]["run_ref"]).exists())
            # No card when the probe carried none: `missing` is already a named
            # gap, and inventing a repair path here would be a claim.
            self.assertNotIn("repair_card", by_unit["core"])

    def test_a_stale_owner_carries_its_repair_card_into_the_unit_result(self) -> None:
        """The #837 recheck at the handoff boundary: a decision that no longer
        describes this machine reads `stale`, and the unit result says which
        prerequisite moved instead of only that the owner was not ready."""
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            binding = live_readiness_binding(paths, "codex")
            atomic_write_json(
                paths.executor_readiness_path,
                {
                    "schema_version": "executor_readiness_cache/v1",
                    "profiles": {
                        "codex": {
                            "schema_version": "executor_readiness/v1",
                            "profile": "codex",
                            "status": "ready",
                            "observed_once": True,
                            "updated_at": "2026-01-01T00:00:00Z",
                            "readiness_binding": {
                                **binding,
                                "axes": {**binding["axes"], "tool": "0" * 64},
                            },
                        }
                    },
                },
                private=True,
            )

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=_agent_runner(),
                readiness=probe_executor_readiness,
                # The real probe runs here, so keep it to the one owner whose
                # cache this test seeded: an unseeded owner would probe its CLI
                # for real and make the test depend on the host's PATH.
                only_units=["core"],
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["core"]["status"], "executor_not_ready")
            self.assertEqual(by_unit["core"]["readiness_status"], "stale")
            card = by_unit["core"]["repair_card"]
            self.assertEqual(card["changed_axes"], ["tool"])
            self.assertEqual(card["status"], "prepared_not_observed")
            self.assertFalse((paths.runtime_runs_dir / by_unit["core"]["run_ref"]).exists())

    def test_dry_run_plans_without_spawning_or_creating_runs(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            runner = _agent_runner()

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                dry_run=True,
                runner=runner,
                readiness=_ready,
            )

            self.assertTrue(all(entry["status"] == "dry_run_planned" for entry in summary["units"]))
            self.assertEqual(runner.spawned, [])
            self.assertFalse(paths.runtime_runs_dir.exists())
            self.assertFalse((repo.parent / "repo-fanout-core").exists())

    def test_resume_skips_completed_units(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            first = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=_agent_runner(),
                readiness=_ready,
            )
            self.assertEqual(len({e["unit_id"] for e in first["units"] if e["status"] == "completed"}), 3)

            rerun_runner = _agent_runner()
            second = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=rerun_runner,
                readiness=_ready,
            )

            self.assertTrue(all(entry["status"] == "already_completed" for entry in second["units"]))
            self.assertEqual(rerun_runner.spawned, [])

    def test_atomic_refusal_preserves_previously_completed_units(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            first = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["core"],
                runner=_agent_runner(),
                readiness=_ready,
            )
            self.assertEqual(
                {entry["unit_id"]: entry for entry in first["units"]}["core"]["status"],
                "completed",
            )
            docs = {entry["unit_id"]: entry for entry in contract["units"]}["docs"]
            docs["handoff"]["executor_capability_snapshot"] = "not-a-snapshot"

            second = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=_agent_runner(),
                readiness=lambda *args, **kwargs: self.fail(
                    "atomic refusal must not run readiness"
                ),
            )

            by_unit = {entry["unit_id"]: entry for entry in second["units"]}
            self.assertEqual(by_unit["core"]["status"], "already_completed")
            self.assertTrue(by_unit["core"]["process_succeeded"])
            self.assertEqual(by_unit["docs"]["status"], "capability_snapshot_invalid")
            stored = json.loads(
                fanout_dispatch_summary_path(paths, str(contract["fanout_id"])).read_text(
                    encoding="utf-8"
                )
            )
            stored_core = {entry["unit_id"]: entry for entry in stored["units"]}["core"]
            self.assertTrue(stored_core["process_succeeded"])

    def test_argv_templates_for_both_spawnable_profiles(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            runner = _agent_runner()

            dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=runner,
                readiness=_ready,
            )

            heads = {tuple(argv[:2]) for argv in runner.spawned}
            self.assertIn(("codex", "exec"), heads)
            claude_argv = next(argv for argv in runner.spawned if argv[0] == "claude")
            self.assertEqual(claude_argv[1], "-p")
            # No unit here routes a model, and neither profile ships a
            # dispatch-model default (see _SHIPPED_DISPATCH_MODEL_DEFAULTS
            # and test_codex_dispatch_model_ships_with_no_default /
            # test_claude_code_unit_ships_with_no_default_dispatch_model), so
            # the base template shows through byte-identical with no
            # appended `--model`.
            self.assertEqual(
                claude_argv[3:],
                [
                    "--permission-mode",
                    "acceptEdits",
                    "--allowedTools",
                    "Bash(git add:*),Bash(git commit:*)",
                ],
            )
            self.assertIn("Work unit:", claude_argv[2])

    def test_missing_cli_maps_to_exit_127(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            def runner(argv, **kwargs):
                if argv[0] == "git":
                    return subprocess.run(argv, **kwargs)
                raise FileNotFoundError(argv[0])

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=runner,
                readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["core"]["status"], "failed")
            self.assertEqual(by_unit["core"]["exit_code"], 127)

    def test_unsupported_profile_falls_back_and_blocks_dependents_with_pointer(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            units = [
                {"unit_id": "manual", "owner": "hermes", "file_scope": ["notes/"]},
                {"unit_id": "auto", "owner": "codex", "file_scope": ["src/"], "depends_on": ["manual"]},
            ]
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units))

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=_agent_runner(),
                readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["manual"]["status"], "unsupported_for_local_dispatch")
            self.assertIn("prepared prompt", by_unit["manual"]["fallback"])
            self.assertEqual(by_unit["auto"]["status"], "blocked_by_dependency")
            self.assertEqual(by_unit["auto"]["blocked_on"], ["manual"])

    def test_partial_redispatch_consumes_previously_completed_dependency(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["core"],
                runner=_agent_runner(),
                readiness=_ready,
            )

            (repo.parent / "repo-fanout-tests").exists()
            second = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["tests"],
                runner=_agent_runner(),
                readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in second["units"]}
            self.assertEqual(by_unit["core"]["status"], "already_completed")
            self.assertEqual(by_unit["tests"]["status"], "completed")
            self.assertEqual(by_unit["docs"]["status"], "not_selected")

    def test_goal_divergence_is_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            with self.assertRaises(ValueError):
                verify_goal_matches_contract(contract, "a different goal entirely")
            with self.assertRaises(ValueError):
                dispatch_fanout(
                    paths,
                    contract,
                    goal_text="a different goal entirely",
                    repo_root=repo,
                    base_sha=sha,
                    runner=_agent_runner(),
                    readiness=_ready,
                )

    def test_existing_worktree_path_errors_instead_of_reuse(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            (repo.parent / "repo-fanout-core").mkdir()

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=_agent_runner(),
                readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["core"]["status"], "worktree_failed")
            self.assertIn("already exists", by_unit["core"]["reason"])


class FanoutUnitRecoveryTests(unittest.TestCase):
    """A failed unit still owns its worktree; the summary must say what survived."""

    def _setup(self, tmp: str):
        root = Path(tmp)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, _UNITS))
        return paths, repo, sha, contract

    def _dispatch(self, paths, repo, sha, contract, runner):
        return dispatch_fanout(
            paths,
            contract,
            goal_text=_GOAL,
            repo_root=repo,
            base_sha=sha,
            runner=runner,
            readiness=_ready,
        )

    def test_a_failed_unit_that_wrote_files_reports_recoverable_work(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = self._dispatch(
                paths, repo, sha, contract,
                _writing_runner(fail_units={"docs"}, write_units={"docs"}),
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            recovery = by_unit["docs"]["recovery"]
            self.assertEqual(by_unit["docs"]["status"], "failed")
            self.assertFalse(by_unit["docs"]["integration_ready"])
            self.assertEqual(recovery["outcome"], "recovery_available")
            self.assertEqual(recovery["schema_version"], "fanout_unit_recovery/v1")
            self.assertEqual(recovery["paths"], ["docs_partial.py"])
            self.assertEqual(recovery["paths_changed"], 1)
            self.assertFalse(recovery["paths_truncated"])
            self.assertGreater(recovery["diff_bytes"], 0)
            self.assertEqual(len(recovery["diff_sha256"]), 64)
            self.assertIn("git -C", recovery["recover_with"])
            self.assertIn("not verification", recovery["claim_boundary"])
            self.assertEqual(summary["recovery_available_units"], ["docs"])

    def test_the_recovery_record_carries_metadata_and_never_content(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = self._dispatch(
                paths, repo, sha, contract,
                _writing_runner(fail_units={"docs"}, write_units={"docs"}),
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            recovery = by_unit["docs"]["recovery"]
            # The whole point of hashing the diff instead of storing it.
            self.assertNotIn(_SECRET, json.dumps(summary))
            stored = Path(recovery["recovery_ref"])
            self.assertTrue(stored.is_file())
            stored_text = stored.read_text(encoding="utf-8")
            self.assertNotIn(_SECRET, stored_text)
            self.assertIn(recovery["diff_sha256"], stored_text)
            # Persisted under the fanout's own directory, nowhere else.
            self.assertEqual(
                stored,
                fanout_unit_recovery_path(paths, contract["fanout_id"], "docs"),
            )

    def test_a_failed_unit_that_wrote_nothing_reports_no_changes(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = self._dispatch(paths, repo, sha, contract, _writing_runner(fail_units={"docs"}))

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["docs"]["recovery"]["outcome"], "no_changes")
            self.assertNotIn("recovery_ref", by_unit["docs"]["recovery"])
            self.assertEqual(summary["recovery_available_units"], [])

    def test_a_completed_unit_is_never_probed_for_recovery(self) -> None:
        # Negative guard: a successful unit's work is reached by merging its
        # branch, not by salvage. Capturing there would imply the opposite.
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = self._dispatch(paths, repo, sha, contract, _writing_runner(write_units={"docs"}))

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["docs"]["status"], "completed")
            self.assertNotIn("recovery", by_unit["docs"])
            self.assertEqual(summary["recovery_available_units"], [])

    def test_a_timed_out_unit_still_gets_its_partial_work_measured(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = self._dispatch(
                paths, repo, sha, contract,
                _writing_runner(timeout_units={"docs"}, write_units={"docs"}),
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["docs"]["exit_code"], 124)
            self.assertEqual(by_unit["docs"]["recovery"]["outcome"], "recovery_available")
            self.assertEqual(summary["recovery_available_units"], ["docs"])

    def test_a_broken_git_probe_degrades_instead_of_failing_the_unit(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = self._dispatch(
                paths, repo, sha, contract,
                _writing_runner(fail_units={"docs"}, write_units={"docs"}, break_git_diff=True),
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            # The unit result survives; only the salvage report degrades.
            self.assertEqual(by_unit["docs"]["status"], "failed")
            self.assertEqual(by_unit["docs"]["exit_code"], 1)
            self.assertEqual(by_unit["docs"]["recovery"]["outcome"], "capture_failed")
            self.assertEqual(summary["recovery_available_units"], [])

    def test_non_utf8_partial_work_is_measured_instead_of_aborting_the_dispatch(self) -> None:
        # Regression: the probe decoded the patch with text=True, which raises
        # UnicodeDecodeError (a ValueError, caught by neither except arm) on a
        # latin-1 partial file. It escaped _dispatch_unit through future.result()
        # and killed the whole run before the summary was ever written.
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = self._dispatch(
                paths, repo, sha, contract,
                _writing_runner(fail_units={"docs"}, latin1_units={"docs"}),
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            recovery = by_unit["docs"]["recovery"]
            self.assertEqual(recovery["outcome"], "recovery_available")
            self.assertEqual(recovery["paths"], ["docs_latin1.txt"])
            self.assertEqual(len(recovery["diff_sha256"]), 64)
            # Every other unit's telemetry survived, and the summary was written.
            self.assertEqual(by_unit["core"]["status"], "completed")
            self.assertTrue(fanout_dispatch_summary_path(paths, contract["fanout_id"]).is_file())

    def test_the_digest_matches_the_bytes_git_actually_emits(self) -> None:
        # The digest is the only thing that makes the record verifiable, so it
        # has to describe git's raw output -- not a decode/re-encode round trip
        # through whatever the host locale happens to be.
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = self._dispatch(
                paths, repo, sha, contract,
                _writing_runner(fail_units={"docs"}, latin1_units={"docs"}),
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            recovery = by_unit["docs"]["recovery"]
            worktree = Path(recovery["worktree_path"])
            emitted = subprocess.run(
                ["git", "diff", sha], cwd=str(worktree), capture_output=True, check=True
            ).stdout
            self.assertEqual(recovery["diff_bytes"], len(emitted))
            self.assertEqual(recovery["diff_sha256"], hashlib.sha256(emitted).hexdigest())

    def test_an_unmeasurable_worktree_is_not_reported_as_empty(self) -> None:
        # `git add -N` failing (a stale index.lock is the plausible aftermath of
        # the timeout path) leaves `git diff` exit-0 and empty, which used to be
        # indistinguishable from a unit that genuinely wrote nothing. The
        # operator would be told there is nothing to salvage and re-run.
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = self._dispatch(
                paths, repo, sha, contract,
                _writing_runner(fail_units={"docs"}, write_units={"docs"}, break_git_add=True),
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            recovery = by_unit["docs"]["recovery"]
            self.assertEqual(recovery["outcome"], "capture_failed")
            self.assertIn("could not be measured", recovery["reason"])
            self.assertEqual(summary["recovery_available_units"], [])
            # The work really is on disk; the probe just could not prove it.
            self.assertTrue((Path(repo).parent / "repo-fanout-docs" / "docs_partial.py").is_file())

    def test_a_wide_failure_caps_its_path_list_and_says_so(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = self._dispatch(
                paths, repo, sha, contract,
                _writing_runner(fail_units={"docs"}, wide_units={"docs"}),
            )

            recovery = {entry["unit_id"]: entry for entry in summary["units"]}["docs"]["recovery"]
            self.assertEqual(recovery["paths_changed"], _MAX_RECOVERY_PATHS + 3)
            self.assertEqual(len(recovery["paths"]), _MAX_RECOVERY_PATHS)
            self.assertTrue(recovery["paths_truncated"])

    def test_a_renamed_file_is_measured_as_both_of_its_paths(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = self._dispatch(
                paths, repo, sha, contract,
                _writing_runner(fail_units={"docs"}, rename_units={"docs"}),
            )

            recovery = {entry["unit_id"]: entry for entry in summary["units"]}["docs"]["recovery"]
            self.assertEqual(recovery["paths"], ["seed.txt", "seed_moved.txt"])
            self.assertEqual(recovery["paths_changed"], 2)

    def test_numstat_parsing_handles_renames_binaries_and_awkward_paths(self) -> None:
        # `-z` framing: normal records end at NUL; a rename emits an empty path
        # field followed by two more NUL-separated tokens.
        self.assertEqual(_parse_numstat("1\t0\ta.py\0"), (["a.py"], 1))
        self.assertEqual(_parse_numstat("3\t2\tsrc/a.py\0004\t0\tsrc/b.py\0"), (["src/a.py", "src/b.py"], 9))
        self.assertEqual(_parse_numstat("1\t1\t\0old.py\0new.py\0"), (["new.py", "old.py"], 2))
        # Binary files report `-` for both counts and contribute no lines.
        self.assertEqual(_parse_numstat("-\t-\timg.png\0"), (["img.png"], 0))
        # `-z` turns off C-quoting, so a tab or a trailing space survives intact.
        self.assertEqual(_parse_numstat("1\t0\thas\ttab.txt\0"), (["has\ttab.txt"], 1))
        self.assertEqual(_parse_numstat("1\t0\ttrailing \0"), (["trailing "], 1))
        self.assertEqual(_parse_numstat(""), ([], 0))

    def test_recover_with_survives_a_worktree_path_containing_spaces(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "My Projects"
            root.mkdir()
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, _UNITS))

            summary = self._dispatch(
                paths, repo, sha, contract,
                _writing_runner(fail_units={"docs"}, write_units={"docs"}),
            )

            recovery = {entry["unit_id"]: entry for entry in summary["units"]}["docs"]["recovery"]
            self.assertIn(" ", recovery["worktree_path"])
            # Quoted, so the printed command is actually paste-able.
            self.assertIn(shlex.quote(recovery["worktree_path"]), recovery["recover_with"])
            argv = shlex.split(recovery["recover_with"])
            self.assertEqual(argv[:3], ["git", "-C", recovery["worktree_path"]])

    def test_a_partial_redispatch_keeps_an_earlier_units_recovery_rollup(self) -> None:
        # `_merged_dispatch_summary` exists so re-dispatching one unit does not
        # erase another's telemetry. It recomputed integration_ready_units but not
        # recovery_available_units, so the stored summary contradicted the very
        # recovery record it had just merged.
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            self._dispatch(
                paths, repo, sha, contract,
                _writing_runner(fail_units={"docs"}, write_units={"docs"}),
            )
            stored = json.loads(
                fanout_dispatch_summary_path(paths, contract["fanout_id"]).read_text(encoding="utf-8")
            )
            self.assertEqual(stored["recovery_available_units"], ["docs"])

            dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=_writing_runner(),
                readiness=_ready,
                only_units=["tests"],
            )

            stored = json.loads(
                fanout_dispatch_summary_path(paths, contract["fanout_id"]).read_text(encoding="utf-8")
            )
            by_unit = {entry["unit_id"]: entry for entry in stored["units"]}
            self.assertEqual(by_unit["docs"]["recovery"]["outcome"], "recovery_available")
            self.assertEqual(stored["recovery_available_units"], ["docs"])

    def test_a_partial_measurement_is_never_reported_as_recoverable(self) -> None:
        # `git add -N` failing plus ANY tracked change used to yield
        # `recovery_available` whose paths and recover_with omitted every file
        # the unit created -- a patch that deletes a file and salvages nothing.
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = self._dispatch(
                paths, repo, sha, contract,
                _writing_runner(
                    fail_units={"docs"}, write_units={"docs"}, rename_units={"docs"}, break_git_add=True
                ),
            )

            recovery = {entry["unit_id"]: entry for entry in summary["units"]}["docs"]["recovery"]
            self.assertEqual(recovery["outcome"], "capture_failed")
            self.assertIn("not a complete patch", recovery["reason"])
            # The worktree is not empty, and the record says so, so nobody
            # deletes it on the strength of a "nothing here" answer.
            self.assertGreater(recovery["tracked_paths_seen"], 0)
            self.assertNotIn("recover_with", recovery)
            self.assertEqual(summary["recovery_available_units"], [])

    def test_a_non_utf8_path_survives_the_probe_intact(self) -> None:
        # `-z` disables git's C-quoting, so paths arrive as raw bytes. Decoding
        # them through the host locale silently renamed them in the record.
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = self._dispatch(
                paths, repo, sha, contract,
                _writing_runner(fail_units={"docs"}, unicode_units={"docs"}),
            )

            recovery = {entry["unit_id"]: entry for entry in summary["units"]}["docs"]["recovery"]
            self.assertEqual(recovery["outcome"], "recovery_available")
            self.assertEqual(recovery["paths"], ["análisis_你好.py"])

    def test_the_persisted_record_carries_the_same_keys_as_the_summary_copy(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = self._dispatch(
                paths, repo, sha, contract,
                _writing_runner(fail_units={"docs"}, write_units={"docs"}),
            )

            recovery = {entry["unit_id"]: entry for entry in summary["units"]}["docs"]["recovery"]
            stored = json.loads(Path(recovery["recovery_ref"]).read_text(encoding="utf-8"))
            # One schema_version must mean one shape. The ref used to be
            # assigned after the file was already written.
            self.assertEqual(sorted(stored), sorted(recovery))
            self.assertEqual(stored["recovery_ref"], recovery["recovery_ref"])

    def test_a_unit_that_could_not_rerun_keeps_its_earlier_recovery(self) -> None:
        # `worktree_failed` says nothing about what the earlier attempt left,
        # so the rollup must not drop the unit -- its record is still on disk.
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            first = self._dispatch(
                paths, repo, sha, contract,
                _writing_runner(fail_units={"docs"}, write_units={"docs"}),
            )
            self.assertEqual(first["recovery_available_units"], ["docs"])

            # The worktree still exists, so re-dispatch cannot create it.
            second = dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                runner=_writing_runner(), readiness=_ready, only_units=["docs"],
            )

            by_unit = {entry["unit_id"]: entry for entry in second["units"]}
            self.assertEqual(by_unit["docs"]["status"], "worktree_failed")
            self.assertEqual(by_unit["docs"]["recovery"]["outcome"], "recovery_available")
            self.assertEqual(second["recovery_available_units"], ["docs"])
            stored = json.loads(
                fanout_dispatch_summary_path(paths, contract["fanout_id"]).read_text(encoding="utf-8")
            )
            self.assertEqual(stored["recovery_available_units"], ["docs"])

    def test_a_later_success_clears_the_stale_recovery_record(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            first = self._dispatch(
                paths, repo, sha, contract,
                _writing_runner(fail_units={"docs"}, write_units={"docs"}),
            )
            record_path = Path({e["unit_id"]: e for e in first["units"]}["docs"]["recovery"]["recovery_ref"])
            self.assertTrue(record_path.is_file())

            # Operator salvages, then clears the worktree AND its branch so a
            # re-dispatch can create both (the creator refuses to reuse either).
            shutil.rmtree(Path(repo).parent / "repo-fanout-docs")
            _git(repo, "worktree", "prune")
            _git(repo, "branch", "-D", "agent/docs")
            second = dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                runner=_writing_runner(), readiness=_ready, only_units=["docs"],
            )

            by_unit = {entry["unit_id"]: entry for entry in second["units"]}
            self.assertEqual(by_unit["docs"]["status"], "completed")
            self.assertNotIn("recovery", by_unit["docs"])
            self.assertEqual(second["recovery_available_units"], [])
            # The stale file is gone, not left advertising a dead worktree.
            self.assertFalse(record_path.is_file())

    def test_a_runner_with_a_non_numeric_returncode_does_not_abort_the_dispatch(self) -> None:
        # Same failure family as the UnicodeDecodeError fixed earlier: an
        # exception escaping the probe takes the whole batch down.
        class _NoReturnCode:
            returncode = None
            stdout = ""
            stderr = ""

        def runner(argv, **kwargs):
            # argv[:2], so `git worktree add` (which creates the unit worktree)
            # is not caught by the `add` arm and the probe is actually reached.
            if argv[:2] in (["git", "diff"], ["git", "add"], ["git", "rev-parse"]):
                return _NoReturnCode()
            if argv[0] == "git":
                return subprocess.run(argv, **kwargs)
            return _FakeCompleted(1, "boom")

        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            summary = self._dispatch(paths, repo, sha, contract, runner)

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["docs"]["recovery"]["outcome"], "capture_failed")
            self.assertEqual(by_unit["docs"]["status"], "failed")

    def test_recovery_paths_reject_ids_that_would_escape_the_fanout_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            for bad in ("../escape", "a/b", "", "UPPER", "-leading"):
                with self.subTest(unit_id=bad):
                    with self.assertRaises(ValueError):
                        fanout_unit_recovery_path(paths, "fanout-0123456789ab", bad)


class FanoutDispatchCliTests(unittest.TestCase):
    def test_cli_dry_run_and_show_join(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, _sha = _make_repo(root)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            units_path = root / "units.json"
            units_path.write_text(json.dumps(_UNITS), encoding="utf-8")
            goal_path = root / "goal.txt"
            goal_path.write_text(_GOAL, encoding="utf-8")

            status, stdout, stderr = run_cli(
                base + ["coding", "fanout", "prepare", "--goal", *_GOAL.split(), "--units", str(units_path), "--record"]
            )
            self.assertEqual(status, 0, stderr)
            fanout_id = json.loads(stdout)["fanout_id"]

            status, stdout, stderr = run_cli(
                base
                + [
                    "coding",
                    "fanout",
                    "dispatch",
                    fanout_id,
                    "--goal-file",
                    str(goal_path),
                    "--repo-root",
                    str(repo),
                    "--dry-run",
                ]
            )
            self.assertEqual(status, 0, stderr)
            summary = json.loads(stdout)
            self.assertEqual(summary["schema_version"], "fanout_dispatch_summary/v1")
            self.assertTrue(summary["dry_run"])
            self.assertFalse(summary["auto_merge"])
            # Readiness is probed for real here, so statuses depend on which
            # agent CLIs exist on the host; the invariant is that nothing
            # spawns or completes under --dry-run.
            for entry in summary["units"]:
                self.assertIn(
                    entry["status"],
                    {
                        "dry_run_planned",
                        "executor_not_ready",
                        "unsupported_for_local_dispatch",
                        "blocked_by_dependency",
                    },
                )
                self.assertNotIn(entry["status"], {"completed", "failed"})

            status, stdout, stderr = run_cli(base + ["coding", "fanout", "show", fanout_id])
            self.assertEqual(status, 0, stderr)
            board = json.loads(stdout)
            for unit in board["units"].values():
                self.assertEqual(unit["observed_run_status"], "not_observed")

    def test_cli_refuses_diverged_goal_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, _sha = _make_repo(root)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            units_path = root / "units.json"
            units_path.write_text(json.dumps(_UNITS), encoding="utf-8")
            wrong_goal = root / "wrong.txt"
            wrong_goal.write_text("not the frozen goal", encoding="utf-8")

            status, stdout, _ = run_cli(
                base + ["coding", "fanout", "prepare", "--goal", *_GOAL.split(), "--units", str(units_path), "--record"]
            )
            fanout_id = json.loads(stdout)["fanout_id"]

            status, stdout, stderr = run_cli(
                base
                + [
                    "coding",
                    "fanout",
                    "dispatch",
                    fanout_id,
                    "--goal-file",
                    str(wrong_goal),
                    "--repo-root",
                    str(repo),
                    "--dry-run",
                ]
            )
            self.assertNotEqual(status, 0)
            self.assertIn("does not match the digest", stderr)


class FanoutDispatchTelemetryTests(unittest.TestCase):
    def _setup(self, tmp: str, units=None):
        root = Path(tmp)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units or _UNITS))
        return paths, repo, sha, contract

    def test_observed_units_record_timestamps_and_duration(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            summary = dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                runner=_agent_runner(), readiness=_ready,
            )
            core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]
            self.assertTrue(str(core["started_at"]).endswith("Z"))
            self.assertTrue(str(core["finished_at"]).endswith("Z"))
            self.assertGreaterEqual(float(core["duration_seconds"]), 0.0)

    def test_dispatch_summary_is_persisted_metadata_only(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                runner=_agent_runner(), readiness=_ready,
            )
            stored_path = fanout_dispatch_summary_path(paths, str(contract["fanout_id"]))
            self.assertTrue(stored_path.is_file())
            stored = json.loads(stored_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["schema_version"], "fanout_dispatch_summary/v1")
            # Persisted state stays metadata-only: no raw agent output fields.
            for entry in stored["units"]:
                self.assertNotIn("stdout", entry)
                self.assertNotIn("output_tail", entry)
                self.assertNotIn("planned_argv", entry)

    def test_spawned_unit_carries_the_recorded_capability_snapshot_for_its_owner(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            expected = build_executor_capability_snapshot(
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
                    paths.executor_capability_snapshots_dir,
                    "codex",
                ),
                expected,
            )
            contract_core = {entry["unit_id"]: entry for entry in contract["units"]}["core"]
            contract_core["handoff"]["executor_capability_snapshot"] = expected
            summary = dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                only_units=["core"], runner=_agent_runner(), readiness=_ready,
            )
            core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]
            projected = core["executor_capability_snapshot"]
            self.assertEqual(projected["recorded_at"], expected["recorded_at"])
            self.assertEqual(
                projected["capabilities"]["edit_format_patch"],
                expected["capabilities"]["edit_format_patch"],
            )
            self.assertEqual(projected["capabilities"]["persistent_eval"], {"status": "unknown"})
            self.assertEqual(core["executor_capability"]["schema_version"], "executor_capability/v1")
            stored = json.loads(
                fanout_dispatch_summary_path(paths, str(contract["fanout_id"])).read_text(encoding="utf-8")
            )
            stored_core = {entry["unit_id"]: entry for entry in stored["units"]}["core"]
            self.assertEqual(stored_core["executor_capability_snapshot"], projected)
            projected["capabilities"]["edit_format_patch"]["evidence_ref"] = "mutated"
            self.assertEqual(
                contract_core["handoff"]["executor_capability_snapshot"]["capabilities"][
                    "edit_format_patch"
                ]["evidence_ref"],
                "probe:patch-edit",
            )

    def test_invalid_frozen_capability_snapshot_refuses_dispatch_without_substitution(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            core = {entry["unit_id"]: entry for entry in contract["units"]}["core"]
            core["handoff"]["executor_capability_snapshot"] = {
                **build_executor_capability_snapshot(
                    executor="claude-code",
                    capabilities={"edit_format_patch": {"status": "unknown"}},
                    recorded_at="2026-08-13T12:01:00Z",
                ),
            }

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["core"],
                runner=_agent_runner(),
                readiness=_ready,
            )

            result = summary["units"][0]
            self.assertEqual(result["status"], "capability_snapshot_invalid")
            self.assertFalse(result["process_succeeded"])
            self.assertIn("does not match", result["reason"])

    def test_malformed_frozen_capability_snapshot_refuses_before_spawn(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            core = {entry["unit_id"]: entry for entry in contract["units"]}["core"]
            core["handoff"]["executor_capability_snapshot"] = "not-a-snapshot"

            def runner(*args, **kwargs):
                self.fail("invalid capability metadata must refuse before spawning")

            def readiness(*args, **kwargs):
                self.fail("invalid capability metadata must refuse before readiness")

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["core"],
                runner=runner,
                readiness=readiness,
            )

            result = summary["units"][0]
            self.assertEqual(result["status"], "capability_snapshot_invalid")
            self.assertIn("must be a mapping", result["reason"])

    def test_current_contract_refuses_a_deleted_frozen_snapshot(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            snapshots = {
                owner: build_executor_capability_snapshot(
                    executor=owner,
                    capabilities={"edit_format_patch": {"status": "unknown"}},
                    recorded_at="2026-08-13T12:01:00Z",
                )
                for owner in ("codex", "claude-code")
            }
            contract = build_fanout_contract(
                _GOAL,
                _UNITS,
                capability_snapshots=snapshots,
            )
            core = {entry["unit_id"]: entry for entry in contract["units"]}["core"]
            del core["handoff"]["executor_capability_snapshot"]
            del core["handoff"]["executor_capability_snapshot_policy"]

            def readiness(*args, **kwargs):
                self.fail("a missing current snapshot must refuse before readiness")

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["core"],
                runner=_agent_runner(),
                readiness=readiness,
            )

            result = summary["units"][0]
            self.assertEqual(result["status"], "capability_snapshot_invalid")
            self.assertIn("required", result["reason"])

    def test_invalid_selected_snapshot_refuses_before_any_local_discovery(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            core = {entry["unit_id"]: entry for entry in contract["units"]}["core"]
            core["handoff"]["executor_capability_snapshot"] = "not-a-snapshot"

            def readiness(*args, **kwargs):
                self.fail("atomic contract refusal must prevent every readiness probe")

            def runner(*args, **kwargs):
                self.fail("atomic contract refusal must prevent git and executor activity")

            with (
                mock.patch(
                    "omh.coding.fanout_dispatch._current_catalog_digest",
                    side_effect=AssertionError("catalog discovery ran"),
                ),
                mock.patch(
                    "omh.coding.fanout_dispatch._owner_skill_discoveries",
                    side_effect=AssertionError("skill discovery ran"),
                ),
            ):
                summary = dispatch_fanout(
                    paths,
                    contract,
                    goal_text=_GOAL,
                    repo_root=repo,
                    base_sha=sha,
                    runner=runner,
                    readiness=readiness,
                )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["core"]["status"], "capability_snapshot_invalid")
            self.assertEqual(by_unit["docs"]["status"], "capability_snapshot_invalid")
            self.assertIn("core", by_unit["docs"]["reason"])
            self.assertFalse((repo.parent / f"{repo.name}-fanout-docs").exists())

    def test_oversized_capability_name_produces_a_bounded_refusal_summary(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            core = {entry["unit_id"]: entry for entry in contract["units"]}["core"]
            snapshot = core["handoff"]["executor_capability_snapshot"]
            snapshot["capabilities"]["SENTINEL-" + ("x" * 100_000)] = {
                "status": "unknown",
                "transcript": "forbidden",
            }

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=_agent_runner(),
                readiness=_ready,
            )

            rendered = json.dumps(summary)
            self.assertLess(len(rendered), 10_000)
            self.assertNotIn("x" * 1000, rendered)

    def test_unassigned_unit_does_not_invalidate_spawnable_siblings(self) -> None:
        units = [
            {"unit_id": "core", "owner": "codex", "file_scope": ["src/"]},
            {"unit_id": "docs", "owner": None, "file_scope": ["docs/"]},
        ]
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, units=units)
            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                dry_run=True,
                runner=_agent_runner(),
                readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["core"]["status"], "dry_run_planned")
            self.assertEqual(
                by_unit["docs"]["status"],
                "unsupported_for_local_dispatch",
            )

    def test_dispatch_rejects_units_missing_from_merge_order_before_discovery(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            contract["merge_plan"]["merge_order"].remove("core")

            with (
                mock.patch(
                    "omh.coding.fanout_dispatch._current_catalog_digest",
                    side_effect=AssertionError("catalog discovery ran"),
                ),
                self.assertRaisesRegex(ValueError, "merge_order"),
            ):
                dispatch_fanout(
                    paths,
                    contract,
                    goal_text=_GOAL,
                    repo_root=repo,
                    base_sha=sha,
                    only_units=["core", "docs"],
                    runner=_agent_runner(),
                    readiness=_ready,
                )

    def test_malformed_frozen_snapshot_policy_cannot_downgrade_to_legacy(self) -> None:
        for policy in ("frozen-requird", ["frozen_required"]):
            with self.subTest(policy=policy), TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
                repo, sha = _make_repo(root)
                snapshots = {
                    owner: build_executor_capability_snapshot(
                        executor=owner,
                        capabilities={"edit_format_patch": {"status": "unknown"}},
                        recorded_at="2026-08-13T12:01:00Z",
                    )
                    for owner in ("codex", "claude-code")
                }
                contract = build_fanout_contract(
                    _GOAL,
                    _UNITS,
                    capability_snapshots=snapshots,
                )
                core = {entry["unit_id"]: entry for entry in contract["units"]}["core"]
                del core["handoff"]["executor_capability_snapshot"]
                core["handoff"]["executor_capability_snapshot_policy"] = policy

                def readiness(*args, **kwargs):
                    self.fail("a malformed policy must refuse before readiness")

                summary = dispatch_fanout(
                    paths,
                    contract,
                    goal_text=_GOAL,
                    repo_root=repo,
                    base_sha=sha,
                    only_units=["core"],
                    runner=_agent_runner(),
                    readiness=readiness,
                )

                result = summary["units"][0]
                self.assertEqual(result["status"], "capability_snapshot_invalid")
                self.assertIn("policy", result["reason"])

    def test_dispatch_binds_declared_handoff_and_snapshot_owner_before_readiness(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            snapshots = {
                owner: build_executor_capability_snapshot(
                    executor=owner,
                    capabilities={"edit_format_patch": {"status": "unknown"}},
                    recorded_at="2026-08-13T12:01:00Z",
                )
                for owner in ("codex", "claude-code")
            }
            contract = build_fanout_contract(
                _GOAL,
                _UNITS,
                capability_snapshots=snapshots,
            )
            core = {entry["unit_id"]: entry for entry in contract["units"]}["core"]
            core["handoff"]["executor_target"] = "claude-code"
            core["handoff"]["executor_capability_snapshot"] = snapshots["claude-code"]

            def readiness(*args, **kwargs):
                self.fail("owner rebinding must refuse before readiness")

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["core"],
                runner=_agent_runner(),
                readiness=readiness,
            )

            result = summary["units"][0]
            self.assertEqual(result["status"], "capability_snapshot_invalid")
            self.assertEqual(result["owner"], "codex")
            self.assertIn("owner", result["reason"])

    def test_invalid_snapshot_blocks_dependents_with_a_named_reason(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            core = {entry["unit_id"]: entry for entry in contract["units"]}["core"]
            core["handoff"]["executor_capability_snapshot"] = "not-a-snapshot"

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=_agent_runner(),
                readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["core"]["status"], "capability_snapshot_invalid")
            self.assertEqual(by_unit["tests"]["status"], "blocked_by_dependency")
            self.assertEqual(by_unit["tests"]["blocked_on"], ["core"])

    def test_not_selected_summary_reports_the_canonical_unit_owner(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            core = {entry["unit_id"]: entry for entry in contract["units"]}["core"]
            core["handoff"]["executor_target"] = "claude-code"

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["docs"],
                runner=_agent_runner(),
                readiness=_ready,
                dry_run=True,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["core"]["status"], "not_selected")
            self.assertEqual(by_unit["core"]["owner"], "codex")

    def test_legacy_handoff_without_snapshot_requires_migration(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            recorded = build_executor_capability_snapshot(
                executor="codex",
                capabilities={
                    "edit_format_patch": {
                        "status": "host_observed",
                        "scope": {"surface": "local_cli"},
                        "evidence_ref": "probe:legacy-patch",
                        "observed_at": "2026-08-13T12:00:00Z",
                    }
                },
                recorded_at="2026-08-13T12:01:00Z",
            )
            write_executor_capability_snapshot(
                executor_capability_snapshot_path(
                    paths.executor_capability_snapshots_dir,
                    "codex",
                ),
                recorded,
            )
            contract["schema_version"] = "fanout_contract/v1"
            for unit in contract["units"]:
                unit["handoff"].pop("executor_capability_snapshot", None)
                unit["handoff"].pop("executor_capability_snapshot_policy", None)
            with self.assertRaisesRegex(ValueError, "migrate-legacy"):
                dispatch_fanout(
                    paths,
                    contract,
                    goal_text=_GOAL,
                    repo_root=repo,
                    base_sha=sha,
                    only_units=["core"],
                    runner=_agent_runner(),
                    readiness=_ready,
                )

    def test_relabelled_v2_contract_cannot_request_legacy_fallback(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            contract["schema_version"] = "fanout_contract/v1"
            for unit in contract["units"]:
                unit["handoff"].pop("executor_capability_snapshot", None)
                unit["handoff"].pop("executor_capability_snapshot_policy", None)

            with self.assertRaisesRegex(ValueError, "migrate-legacy"):
                dispatch_fanout(
                    paths,
                    contract,
                    goal_text=_GOAL,
                    repo_root=repo,
                    base_sha=sha,
                    runner=_agent_runner(),
                    readiness=_ready,
                )

    def test_dry_run_does_not_persist_a_summary(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                dry_run=True, runner=_agent_runner(), readiness=_ready,
            )
            self.assertFalse(fanout_dispatch_summary_path(paths, str(contract["fanout_id"])).exists())

    def test_limit_shaped_failure_is_classified_and_recorded(self) -> None:
        with TemporaryDirectory() as tmp:
            units = [
                {"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["src/core/"]},
            ]
            other = [
                {"unit_id": "docs", "title": "Docs", "owner": "claude-code", "file_scope": ["docs/"]},
            ]
            paths, repo, sha, contract = self._setup(tmp, units=units + other)

            def runner(argv, **kwargs):
                if argv[0] == "git":
                    return subprocess.run(argv, **kwargs)
                if argv[0] == "codex":
                    return _FakeCompleted(1, "Error: You have hit your usage limit. Try again later.")
                return _FakeCompleted(0, "done")

            summary = dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                runner=runner, readiness=_ready,
            )
            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertTrue(by_unit["core"]["limit_shaped"])
            self.assertEqual(by_unit["core"]["limit_pattern"], "usage_limit")
            self.assertNotIn("limit_shaped", by_unit["docs"])
            stored = json.loads(paths.executor_limit_signals_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["profiles"]["codex"]["pattern_label"], "usage_limit")
            self.assertNotIn("claude-code", stored["profiles"])
            # Journal summary names the shape without dumping extra raw text.
            shown = show_run(paths, by_unit["core"]["run_ref"])
            result_events = [e for e in shown["journal_events"] if e["event"] == "executor_result_observed"]
            self.assertIn("limit-shaped failure (usage_limit)", result_events[-1]["summary"])

    def test_unrelated_429_and_disk_quota_text_are_not_limit_shaped(self) -> None:
        with TemporaryDirectory() as tmp:
            units = [
                {"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["src/core/"]},
                {"unit_id": "docs", "title": "Docs", "owner": "claude-code", "file_scope": ["docs/"]},
            ]
            paths, repo, sha, contract = self._setup(tmp, units=units)

            def runner(argv, **kwargs):
                if argv[0] == "git":
                    return subprocess.run(argv, **kwargs)
                if argv[0] == "codex":
                    return _FakeCompleted(1, 'Traceback: File "src/foo.py", line 429, in bar\nAssertionError')
                completed = _FakeCompleted(1, "tests failed")
                completed.stderr = "error: disk quota check skipped"
                return completed

            summary = dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                runner=runner, readiness=_ready,
            )
            for entry in summary["units"]:
                self.assertNotIn("limit_shaped", entry, entry["unit_id"])
            self.assertFalse(paths.executor_limit_signals_path.exists())

    def test_successful_dispatch_clears_a_prior_limit_signal(self) -> None:
        with TemporaryDirectory() as tmp:
            units = [{"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["src/core/"]}]
            paths, repo, sha, contract = self._setup(tmp, units=units + [
                {"unit_id": "docs", "title": "Docs", "owner": "claude-code", "file_scope": ["docs/"]},
            ])
            from omh.system.local_store import atomic_write_json

            atomic_write_json(
                paths.executor_limit_signals_path,
                {
                    "schema_version": "executor_limit_signals/v1",
                    "profiles": {"codex": {"pattern_label": "usage_limit"}},
                },
                private=True,
            )
            dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                runner=_agent_runner(), readiness=_ready,
            )
            stored = json.loads(paths.executor_limit_signals_path.read_text(encoding="utf-8"))
            self.assertNotIn("codex", stored.get("profiles", {}))

    def test_successful_exit_is_never_limit_shaped(self) -> None:
        with TemporaryDirectory() as tmp:
            units = [{"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["src/core/"]}]
            paths, repo, sha, contract = self._setup(tmp, units=units + [
                {"unit_id": "docs", "title": "Docs", "owner": "claude-code", "file_scope": ["docs/"]},
            ])

            def runner(argv, **kwargs):
                if argv[0] == "git":
                    return subprocess.run(argv, **kwargs)
                return _FakeCompleted(0, "quota discussion in output but exit 0")

            summary = dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                runner=runner, readiness=_ready,
            )
            for entry in summary["units"]:
                self.assertNotIn("limit_shaped", entry)
            self.assertFalse(paths.executor_limit_signals_path.exists())

    def test_routed_model_reaches_spawn_argv(self) -> None:
        with TemporaryDirectory() as tmp:
            units = [
                {"unit_id": "brain", "title": "Brain", "owner": "codex", "file_scope": ["src/a/"], "role": "brain"},
                {"unit_id": "ui", "title": "UI", "owner": "claude-code", "file_scope": ["src/b/"], "model": "opus"},
            ]
            paths, repo, sha, contract = self._setup(tmp, units=units)
            runner = _agent_runner()
            summary = dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                runner=runner, readiness=_ready,
            )
            spawned = {argv[0]: argv for argv in runner.spawned}
            self.assertIn("--config", spawned["codex"])
            self.assertIn("model_reasoning_effort=high", spawned["codex"])
            self.assertIn("--model", spawned["claude"])
            self.assertIn("opus", spawned["claude"])
            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["ui"]["model"], "opus")


def _progress_events(paths: OmhPaths, run_ref: str) -> list[dict[str, object]]:
    events_path = paths.runtime_runs_dir / run_ref / "executor_progress" / "events.jsonl"
    if not events_path.is_file():
        return []
    return [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]


class FanoutMediaCapabilityDispatchTests(unittest.TestCase):
    _ROUTE = {"provider": "openai", "wire_model": "gpt-5", "endpoint_mode": "default"}
    _UNIT = {
        "unit_id": "media",
        "title": "Media handoff",
        "owner": "codex",
        "file_scope": ["src/media/"],
    }

    def _snapshot(
        self,
        executor: str,
        capabilities: tuple[str, ...],
        *,
        scope: dict[str, str] | None = None,
        observed_at: str | None = None,
    ) -> dict[str, object]:
        recorded_at = observed_at or utc_now()
        return build_executor_capability_snapshot(
            executor=executor,
            capabilities={
                capability: {
                    "status": "host_observed",
                    "scope": scope or self._ROUTE,
                    "evidence_ref": f"operator:{executor}-{capability}",
                    "observed_at": recorded_at,
                }
                for capability in capabilities
            },
            recorded_at=recorded_at,
        )

    def _contract(
        self,
        temporary: str,
        *,
        capabilities: tuple[str, ...] = ("input_modality_image",),
        input_representation: object = "raw_media:image",
        transformation: dict[str, str] | None = None,
        scope: dict[str, str] | None = None,
        observed_at: str | None = None,
    ) -> tuple[OmhPaths, Path, str, dict[str, object]]:
        root = Path(temporary)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        unit = {
            **self._UNIT,
            "input_representation": input_representation,
            "transformation": transformation or {},
        }
        snapshot = self._snapshot(
            "codex",
            capabilities,
            scope=scope,
            observed_at=observed_at,
        )
        contract = write_fanout_contract(
            paths,
            build_fanout_contract(_GOAL, [unit], capability_snapshots={"codex": snapshot}),
        )
        handoff = contract["units"][0]["handoff"]
        handoff["model_route"] = dict(self._ROUTE)
        return paths, repo, sha, contract

    def _dispatch(self, paths, repo, sha, contract, *, runner, readiness=_ready, **kwargs):
        return dispatch_fanout(
            paths,
            contract,
            goal_text=_GOAL,
            repo_root=repo,
            base_sha=sha,
            runner=runner,
            readiness=readiness,
            **kwargs,
        )

    def test_dispatch_rechecks_expired_and_switched_media_routes_before_spawn(self) -> None:
        cases = (
            ("stale", self._ROUTE, "2000-01-01T00:00:00Z"),
            ("provider_switch", {**self._ROUTE, "provider": "anthropic"}, None),
            ("model_switch", {**self._ROUTE, "wire_model": "gpt-5-mini"}, None),
        )
        for label, route, observed_at in cases:
            with self.subTest(label=label), TemporaryDirectory() as temporary:
                paths, repo, sha, contract = self._contract(temporary, observed_at=observed_at)
                contract["units"][0]["handoff"]["model_route"] = route
                spawned: list[object] = []

                def runner(*args, **kwargs):
                    spawned.append((args, kwargs))
                    self.fail("invalid media capability evidence must refuse before spawn")

                def readiness(*args, **kwargs):
                    self.fail("invalid media capability evidence must refuse before readiness")

                summary = self._dispatch(paths, repo, sha, contract, runner=runner, readiness=readiness)

                self.assertEqual(summary["units"][0]["status"], "modality_unknown")
                self.assertEqual(spawned, [])

    def test_dispatch_requires_every_media_requirement_and_preserves_transformation_controls(self) -> None:
        representations = ["raw_media:image", "raw_media:audio"]
        with TemporaryDirectory() as temporary:
            paths, repo, sha, incomplete = self._contract(
                temporary,
                capabilities=("input_modality_image",),
                input_representation=representations,
            )
            summary = self._dispatch(
                paths,
                repo,
                sha,
                incomplete,
                runner=lambda *args, **kwargs: self.fail("missing audio evidence must refuse before spawn"),
                readiness=lambda *args, **kwargs: self.fail("missing audio evidence must refuse before readiness"),
            )
            self.assertEqual(summary["units"][0]["status"], "modality_unknown")

        with TemporaryDirectory() as temporary:
            paths, repo, sha, complete = self._contract(
                temporary,
                capabilities=("input_modality_image", "input_modality_audio"),
                input_representation=representations,
            )
            runner = _agent_runner()
            summary = self._dispatch(paths, repo, sha, complete, runner=runner)
            self.assertTrue(summary["units"][0]["process_succeeded"])
            self.assertEqual(len(runner.spawned), 1)

        with TemporaryDirectory() as temporary:
            transformation = {"kind": "ocr", "status": "observed", "evidence_ref": "operator:ocr"}
            paths, repo, sha, transformed = self._contract(
                temporary,
                capabilities=("input_modality_text",),
                input_representation="ocr_output",
                transformation=transformation,
            )
            runner = _agent_runner()
            summary = self._dispatch(paths, repo, sha, transformed, runner=runner)
            self.assertTrue(summary["units"][0]["process_succeeded"])
            self.assertEqual(
                transformed["units"][0]["handoff"]["executor_modality_decision"]["transformation"],
                transformation,
            )

        with TemporaryDirectory() as temporary:
            paths, repo, sha, rerouted = self._contract(
                temporary,
                capabilities=("input_modality_text",),
                input_representation="ocr_output",
                transformation=transformation,
            )
            rerouted["units"][0]["handoff"]["model_route"] = {**self._ROUTE, "provider": "anthropic"}
            summary = self._dispatch(
                paths,
                repo,
                sha,
                rerouted,
                runner=lambda *args, **kwargs: self.fail("provider-switched transformed media must not spawn"),
                readiness=lambda *args, **kwargs: self.fail("provider-switched transformed media must not probe readiness"),
            )
            self.assertEqual(summary["units"][0]["status"], "modality_unknown")

    def test_retargeted_fanout_rechecks_media_capabilities_before_a_second_spawn(self) -> None:
        with TemporaryDirectory() as temporary:
            paths, repo, sha, contract = self._contract(temporary)
            write_executor_capability_snapshot(
                executor_capability_snapshot_path(paths.executor_capability_snapshots_dir, "claude-code"),
                self._snapshot("claude-code", ("input_modality_image",)),
            )
            failing_runner = _writing_runner(fail_units={"media"}, write_units={"media"})

            def runner(argv, **kwargs):
                completed = failing_runner(argv, **kwargs)
                if argv[0] != "git" and completed.returncode:
                    return _FakeCompleted(completed.returncode, "authentication failed")
                return completed

            runner.spawned = failing_runner.spawned
            summary = self._dispatch(
                paths,
                repo,
                sha,
                contract,
                runner=runner,
                on_failure="retarget",
                retarget_owner="claude-code",
            )

            recovery = summary["failure_recovery"]["decisions"]
            self.assertEqual(recovery[0]["choice"], "retarget")
            self.assertEqual(recovery[0]["attempt"]["status"], "modality_unknown")
            self.assertEqual(len(runner.spawned), 1)


class FanoutDispatchMaestroProgressRowTests(unittest.TestCase):
    """`omh coding fanout dispatch` spawns local CLIs directly, which is the
    Maestro lane by definition; this class covers the executor-progress
    binding lifecycle those units open so the HUD's active-executor
    projection can label and drop the row, and the operator's dispatch-model
    preference that fills a gap a unit's prepared handoff left unrouted."""

    def _setup(self, tmp: str, units=None):
        root = Path(tmp)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units or _UNITS))
        return paths, repo, sha, contract

    def test_completed_unit_opens_a_maestro_binding_and_closes_it(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            core = {entry["unit_id"]: entry for entry in contract["units"]}["core"]
            run_ref = core["run_ref"]

            dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                only_units=["core"], runner=_agent_runner(), readiness=_ready,
            )

            binding = read_progress_binding(paths, "run", run_ref)
            self.assertIsNotNone(binding)
            self.assertEqual(binding["executor_profile"], "codex")
            self.assertEqual(binding["delivery"]["source"], "fanout_dispatch")
            # Closed the moment the process ended: a closed binding drops out
            # of the HUD's active-executor projection on the next read, which
            # is what stops the row -- never a lingering live row for a
            # finished process.
            self.assertEqual(binding["state"], "closed")
            events = [event["event_type"] for event in _progress_events(paths, run_ref)]
            self.assertIn("executor_dispatched", events)
            self.assertIn("executor_completed", events)

    def test_single_unit_contract_dispatches_through_the_same_engine_and_hud_path(self) -> None:
        """`omh coding run`'s one-unit contract is not a parallel spawn path --
        it drives this exact `dispatch_fanout` engine, so the #1158
        executor-progress binding lifecycle (open on spawn, close on exit,
        which is what makes and then removes the `(claude-code/maestro
        <model>)` HUD row) applies unchanged down to a single unit. Read
        through the plugin-bundle `read_omh_hud` mirror the TUI dock actually
        reads, the same regression shape as
        `test_hud_projects_a_real_fanout_dispatch_binding_with_live_elapsed`.
        """
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        with TemporaryDirectory() as tmp:
            unit = {
                "unit_id": "run",
                "title": "Research pricing approaches",
                "owner": "claude-code",
                "file_scope": ["."],
            }
            paths, repo, sha, contract = self._setup(tmp, units=[unit])
            run_ref = contract["units"][0]["run_ref"]

            summary = dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                runner=_agent_runner(), readiness=_ready,
            )

            self.assertEqual(len(summary["units"]), 1)
            self.assertTrue(summary["units"][0]["process_succeeded"])
            binding = read_progress_binding(paths, "run", run_ref)
            self.assertIsNotNone(binding)
            self.assertEqual(binding["executor_profile"], "claude_code")
            self.assertEqual(binding["delivery"]["source"], "fanout_dispatch")
            self.assertEqual(binding["state"], "closed")
            events = [event["event_type"] for event in _progress_events(paths, run_ref)]
            self.assertIn("executor_dispatched", events)
            self.assertIn("executor_completed", events)

            # A closed binding drops out of the HUD's active-executor
            # projection on the next read -- the same behavior a multi-unit
            # fanout's finished units already have, proving the single-unit
            # path was never given a separate, unreviewed HUD lifecycle.
            payload = read_omh_hud(paths.omh_home, paths.hermes_home)
            self.assertEqual(payload["maestro"]["rows"], [])

    def test_failed_unit_also_closes_its_maestro_binding(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            core = {entry["unit_id"]: entry for entry in contract["units"]}["core"]
            run_ref = core["run_ref"]

            dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                only_units=["core"], runner=_agent_runner(fail_units={"core"}), readiness=_ready,
            )

            binding = read_progress_binding(paths, "run", run_ref)
            self.assertEqual(binding["state"], "closed")
            events = [event["event_type"] for event in _progress_events(paths, run_ref)]
            self.assertIn("executor_failed", events)

    def test_dispatched_event_carries_the_unit_title_and_routed_model(self) -> None:
        with TemporaryDirectory() as tmp:
            units = [
                {"unit_id": "core", "title": "Core work", "owner": "codex", "file_scope": ["src/core/"]},
                {"unit_id": "docs", "title": "Docs work", "owner": "claude-code", "file_scope": ["docs/"]},
            ]
            paths, repo, sha, contract = self._setup(tmp, units=units)
            core = {entry["unit_id"]: entry for entry in contract["units"]}["core"]
            run_ref = core["run_ref"]

            dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                only_units=["core"], runner=_agent_runner(), readiness=_ready,
            )

            dispatched = next(
                event for event in _progress_events(paths, run_ref) if event["event_type"] == "executor_dispatched"
            )
            self.assertEqual(dispatched["summary"], "Core work")

    def test_claude_code_unit_ships_with_no_default_dispatch_model(self) -> None:
        """A rejected model is an observed exit failure with no fallback
        walk, and no user opted into a specific model choice by dispatching a
        unit -- so, like every other profile, claude-code ships with no
        dispatch-model default (see _SHIPPED_DISPATCH_MODEL_DEFAULTS).
        `docs/FANOUT.md` documents `opus` as the recommended value an
        operator can opt into via `dispatch-models.json`
        (test_dispatch_model_preference_config_overrides_the_shipped_default
        covers that opt-in path)."""
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            docs = {entry["unit_id"]: entry for entry in contract["units"]}["docs"]
            run_ref = docs["run_ref"]
            runner = _agent_runner()

            summary = dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                only_units=["docs"], runner=runner, readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["docs"]["model"], "")
            spawned = next(argv for argv in runner.spawned if argv[0] == "claude")
            self.assertNotIn("--model", spawned)
            binding = read_progress_binding(paths, "run", run_ref)
            self.assertEqual(binding["executor_profile"], "claude_code")

    def test_dispatch_model_preference_config_overrides_the_shipped_default(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            config_path = dispatch_model_preferences_path(paths.omh_home)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(
                config_path,
                {
                    "schema_version": "omh_dispatch_model_preferences/v1",
                    "profiles": {"claude-code": "claude-fable-5"},
                },
            )
            runner = _agent_runner()

            summary = dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                only_units=["docs"], runner=runner, readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["docs"]["model"], "claude-fable-5")
            spawned = next(argv for argv in runner.spawned if argv[0] == "claude")
            self.assertIn("claude-fable-5", spawned)

    def test_dispatch_model_preference_can_be_cleared_to_the_cli_default(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            config_path = dispatch_model_preferences_path(paths.omh_home)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(
                config_path,
                {"schema_version": "omh_dispatch_model_preferences/v1", "profiles": {"claude-code": ""}},
            )
            runner = _agent_runner()

            summary = dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                only_units=["docs"], runner=runner, readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["docs"]["model"], "")
            spawned = next(argv for argv in runner.spawned if argv[0] == "claude")
            self.assertNotIn("--model", spawned)

    def test_dispatch_model_preference_never_overrides_a_routed_model(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            docs = {entry["unit_id"]: entry for entry in contract["units"]}["docs"]
            docs["handoff"]["model_route"] = {
                "schema_version": "coding_model_route/v2",
                "status": "resolved",
                "provenance": "explicit",
                "selected_model": "claude-sonnet-5",
                "selected_reasoning_effort": "medium",
            }
            runner = _agent_runner()

            summary = dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                only_units=["docs"], runner=runner, readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["docs"]["model"], "claude-sonnet-5")
            spawned = next(argv for argv in runner.spawned if argv[0] == "claude")
            self.assertIn("claude-sonnet-5", spawned)
            self.assertNotIn("opus", spawned)

    def test_codex_dispatch_model_ships_with_no_default(self) -> None:
        """No local codex CLI to confirm its `--model` value space against in
        this repo, so the conservative choice (unset = CLI default) stands
        until that is verified."""
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            runner = _agent_runner()

            summary = dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                only_units=["core"], runner=runner, readiness=_ready,
            )

            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["core"]["model"], "")
            spawned = next(argv for argv in runner.spawned if argv[0] == "codex")
            self.assertNotIn("--model", spawned)

    def test_reported_cost_and_tokens_reach_the_terminal_progress_event(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            docs = {entry["unit_id"]: entry for entry in contract["units"]}["docs"]
            run_ref = docs["run_ref"]
            claude_result = json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "session_id": "sess-cost-1",
                    "total_cost_usd": 0.4213,
                    "usage": {"input_tokens": 100, "output_tokens": 40},
                }
            )

            def runner(argv, **kwargs):
                if argv[0] == "git":
                    return subprocess.run(argv, **kwargs)
                return _FakeCompleted(0, claude_result)

            dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                only_units=["docs"], runner=runner, readiness=_ready,
            )

            completed = next(
                event for event in _progress_events(paths, run_ref) if event["event_type"] == "executor_completed"
            )
            self.assertEqual(completed["signal"]["cost_usd"], 0.4213)
            # Never estimated from tokens: the reported total is a rounded
            # pass-through, not a derivation from input/output token counts.
            self.assertNotEqual(completed["signal"]["cost_usd"], 100 + 40)


def _write_skill(root: Path, name: str, description: str) -> None:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(f"---\ndescription: {description}\n---\n", encoding="utf-8")


class FanoutDispatchSkillDiscoveryTests(unittest.TestCase):
    """Discovery wiring at the dispatch boundary: owner set, project root
    threading, the dry-run surface fields, and the prompt units actually get.
    `Path.home` is patched to a fixture home so the operator's real skill
    library never leaks into the assertions."""

    def _setup(self, tmp: str, units):
        root = Path(tmp)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units))
        return paths, repo, sha, contract

    def test_owner_set_skips_non_spawnable_owners_and_threads_project_root(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            home.mkdir()
            repo = root / "repo"
            _write_skill(repo / ".claude" / "skills", "repo-helper", "Implement the local fix")
            units = [
                {"handoff": {"executor_target": "claude-code"}},
                {"handoff": {"executor_target": "codex"}},
                {"handoff": {"executor_target": "hermes"}},
                {"handoff": {"executor_target": ""}},
                {"unit_id": "no-handoff"},
            ]
            with mock.patch("pathlib.Path.home", return_value=home):
                discoveries = _owner_skill_discoveries(units, project_root=repo)
        self.assertEqual(sorted(discoveries), ["claude-code", "codex"])
        claude = discoveries["claude-code"]
        self.assertEqual(claude["sources"]["claude_project_skills"]["status"], "present")
        repo_entries = [entry for entry in claude["skills"] if entry["source"] == "claude_project_skills"]
        self.assertEqual([entry["name"] for entry in repo_entries], ["repo-helper"])
        self.assertEqual(repo_entries[0]["invocation"], "/repo-helper")

    def test_dry_run_summary_carries_skill_selection_and_sequence_source(self) -> None:
        with TemporaryDirectory() as tmp:
            units = [
                {"unit_id": "auto", "owner": "claude-code", "file_scope": ["src/a/"]},
                {"unit_id": "declared", "owner": "claude-code", "file_scope": ["src/b/"], "skill_sequence": ["/my-flow"]},
                {"unit_id": "silent", "owner": "claude-code", "file_scope": ["src/c/"], "skill_sequence": []},
                {"unit_id": "bare", "owner": "codex", "file_scope": ["src/d/"]},
            ]
            paths, repo, sha, contract = self._setup(tmp, units)
            home = Path(tmp) / "home"
            skills = home / ".claude" / "skills"
            _write_skill(skills, "omc-plan", "Plan and decompose work before implementation")
            _write_skill(skills, "ultrawork", "Parallel implementation execution loop")
            _write_skill(skills, "code-reviewer", "Expert code review with severity-rated findings")
            with mock.patch("pathlib.Path.home", return_value=home):
                summary = dispatch_fanout(
                    paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                    dry_run=True, runner=_agent_runner(), readiness=_ready,
                )
        by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
        auto = by_unit["auto"]
        self.assertEqual(auto["skill_sequence_source"], "auto_recommended")
        first_option = auto["skill_selection"]["options"][0]
        self.assertEqual(
            [step["invocation"] for step in first_option["sequence"]],
            ["/omc-plan", "/ultrawork", "/code-reviewer"],
        )
        self.assertEqual(by_unit["declared"]["skill_sequence_source"], "declared")
        self.assertNotIn("skill_selection", by_unit["declared"])
        self.assertEqual(by_unit["silent"]["skill_sequence_source"], "declared_none")
        # An empty codex environment offers nothing to sequence.
        self.assertEqual(by_unit["bare"]["skill_sequence_source"], "none")
        self.assertNotIn("skill_sequence", by_unit["bare"])

    def test_dry_run_auto_source_names_the_riding_sequence(self) -> None:
        # One classified skill: no genuine arrangement choice, so no card —
        # but the summary must still name what will ride the prompt instead
        # of the bare word "auto".
        with TemporaryDirectory() as tmp:
            units = [
                {"unit_id": "auto", "owner": "claude-code", "file_scope": ["src/a/"]},
                {"unit_id": "other", "owner": "codex", "file_scope": ["src/b/"]},
            ]
            paths, repo, sha, contract = self._setup(tmp, units)
            home = Path(tmp) / "home"
            _write_skill(home / ".claude" / "skills", "ultrawork", "Parallel implementation execution loop")
            with mock.patch("pathlib.Path.home", return_value=home):
                summary = dispatch_fanout(
                    paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                    dry_run=True, runner=_agent_runner(), readiness=_ready,
                )
        planned = {entry["unit_id"]: entry for entry in summary["units"]}["auto"]
        self.assertEqual(planned["skill_sequence_source"], "auto")
        self.assertEqual(planned["skill_sequence"], ["/ultrawork"])
        self.assertNotIn("skill_selection", planned)

    def test_dispatch_threads_discoveries_into_unit_prompts(self) -> None:
        with TemporaryDirectory() as tmp:
            units = [
                {"unit_id": "work", "owner": "claude-code", "file_scope": ["src/"]},
                {"unit_id": "side", "owner": "codex", "file_scope": ["docs/"]},
            ]
            paths, repo, sha, contract = self._setup(tmp, units)
            home = Path(tmp) / "home"
            _write_skill(home / ".claude" / "skills", "omc-plan", "Plan and decompose work before implementation")
            _write_skill(repo / ".claude" / "skills", "repo-helper", "Implement the local fix")
            runner = _agent_runner()
            with mock.patch("pathlib.Path.home", return_value=home):
                summary = dispatch_fanout(
                    paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                    runner=runner, readiness=_ready,
                )
        by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
        self.assertEqual(by_unit["work"]["status"], "completed")
        claude_argv = next(argv for argv in runner.spawned if argv[0] == "claude")
        prompt = claude_argv[2]
        self.assertIn("Suggested skill sequence", prompt)
        # Home-level and repo-local discoveries both ride the spawned prompt.
        self.assertIn("`/omc-plan`", prompt)
        self.assertIn("`/repo-helper`", prompt)


class FanoutBriefCliTests(unittest.TestCase):
    def test_brief_surfaces_a_declined_units_reason_distinctly_from_failed(self) -> None:
        # #H requirement (c): a reporting surface must render a
        # negative-conclusive outcome distinctly from an ordinary failure.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            units = [
                {"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["src/core/"]},
            ]
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units))
            sidecar = unit_result_path(paths, contract["fanout_id"], "core")
            payload = _unit_result_payload(
                contract, sha, process_status="process_declined", decline_reason="refused_by_policy"
            )

            def runner(argv, **kwargs):
                if argv[0] == "git":
                    return subprocess.run(argv, **kwargs)
                sidecar.parent.mkdir(parents=True, exist_ok=True)
                sidecar.write_text(json.dumps(payload), encoding="utf-8")
                return _FakeCompleted(3, "refused")

            dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                runner=runner, readiness=_ready,
            )
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            status, stdout, stderr = run_cli(base + ["coding", "fanout", "brief", str(contract["fanout_id"])])
            self.assertEqual(status, 0, stderr)
            brief = json.loads(stdout)
            core = {entry["unit_id"]: entry for entry in brief["units"]}["core"]
            self.assertEqual(core["status"], "failed")
            self.assertEqual(core["decline_reason"], "refused_by_policy")

    def test_brief_leaves_decline_reason_empty_for_an_ordinary_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            units = [{"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["src/core/"]}]
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units))
            dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                runner=_agent_runner(fail_units={"core"}), readiness=_ready,
            )
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            status, stdout, stderr = run_cli(base + ["coding", "fanout", "brief", str(contract["fanout_id"])])
            self.assertEqual(status, 0, stderr)
            brief = json.loads(stdout)
            core = {entry["unit_id"]: entry for entry in brief["units"]}["core"]
            self.assertEqual(core["status"], "failed")
            self.assertEqual(core["decline_reason"], "")

    def test_brief_joins_contract_journal_and_dispatch_summary(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            units = [
                {"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["src/core/"], "role": "brain"},
                {"unit_id": "manual", "title": "Manual", "owner": "hermes", "file_scope": ["notes/"]},
            ]
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units))
            dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                runner=_agent_runner(), readiness=_ready,
            )
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            status, stdout, stderr = run_cli(base + ["coding", "fanout", "brief", str(contract["fanout_id"])])
            self.assertEqual(status, 0, stderr)
            brief = json.loads(stdout)
            self.assertEqual(brief["schema_version"], "fanout_briefing/v1")
            by_unit = {entry["unit_id"]: entry for entry in brief["units"]}
            core = by_unit["core"]
            self.assertEqual(core["owner"], "codex")
            self.assertEqual(core["model"], "gpt-5.6-terra")
            self.assertEqual(core["status"], "completed")
            self.assertEqual(core["session_ref"], "unknown")
            self.assertEqual(core["tokens_total"], "unknown")
            self.assertGreaterEqual(float(core["elapsed_seconds"]), 0.0)
            # A never-dispatched unit keeps its prepared-vs-observed shape.
            manual = by_unit["manual"]
            self.assertEqual(manual["status"], "unsupported_for_local_dispatch")
            self.assertEqual(manual["observed_run_status"], "not_observed")
            self.assertIn("unknown fields stay", brief["claim_boundary"])

    def test_brief_surfaces_chain_alternative_additively(self) -> None:
        # The JSON model_label format is a stable part of fanout_briefing/v1;
        # the chain alternative ships only as the additive model_alternative
        # field, and the (alt: …) suffix appears in plain text alone.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            units = [
                {"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["src/r/"], "role": "brain"},
                {"unit_id": "docs", "title": "Docs", "owner": "codex", "file_scope": ["docs/"], "role": "docs"},
            ]
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units))
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, stdout, stderr = run_cli(base + ["coding", "fanout", "brief", str(contract["fanout_id"])])
            self.assertEqual(status, 0, stderr)
            brief = json.loads(stdout)
            by_unit = {entry["unit_id"]: entry for entry in brief["units"]}
            # Behavior change #3 (display consequence of the chain head): the
            # model field is a concrete id, no longer executor_default, and the
            # alternative is the second chain entry (brain = deep > standard).
            core = by_unit["core"]
            self.assertEqual(core["model"], "gpt-5.6-terra")
            self.assertEqual(core["model_label"], "gpt-5.6-terra high")
            self.assertEqual(core["model_alternative"], "gpt-5.6-sol")
            # Single-entry chain (docs on codex): no alternative, empty string.
            self.assertEqual(by_unit["docs"]["model_alternative"], "")

            status, stdout, stderr = run_cli(
                base + ["coding", "fanout", "brief", str(contract["fanout_id"])], output_json=False
            )
            self.assertEqual(status, 0, stderr)
            # Owner and model read as ONE field, matching the status board's
            # bullet convention; a standalone "— (model)" field doubled the
            # separator around a parenthetical.
            self.assertIn("codex (gpt-5.6-terra high, alt: gpt-5.6-sol)", stdout)
            self.assertNotIn(" — (", stdout)
            self.assertNotIn("(gpt-5.6-sol, alt:", stdout)

    def test_brief_degrades_silently_for_v1_routes(self) -> None:
        # A persisted v1 route carries no chain[]: the alternative must be
        # absent (empty field, no suffix), never "unknown" — a chain that does
        # not exist is not an unobserved value. The v1 payload is annotated.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            units = [
                {"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["src/core/"], "role": "brain"},
                {"unit_id": "docs", "title": "Docs", "owner": "claude-code", "file_scope": ["docs/"]},
            ]
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units))
            contract_path = paths.fanout_contracts_dir / str(contract["fanout_id"]) / "fanout_contract.json"
            stored = json.loads(contract_path.read_text(encoding="utf-8"))
            for unit in stored["units"]:
                if unit["unit_id"] == "core":
                    unit["handoff"]["model_route"] = {
                        "schema_version": "coding_model_route/v1",
                        "source": "role_catalog_default",
                        "selected_model": "gpt-5.6-sol",
                        "selected_reasoning_effort": "high",
                    }
            contract_path.write_text(json.dumps(stored), encoding="utf-8")
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, stdout, stderr = run_cli(base + ["coding", "fanout", "brief", str(contract["fanout_id"])])
            self.assertEqual(status, 0, stderr)
            brief = json.loads(stdout)
            core = {entry["unit_id"]: entry for entry in brief["units"]}["core"]
            self.assertEqual(core["model_label"], "gpt-5.6-sol high")
            self.assertEqual(core["model_alternative"], "")
            self.assertEqual(core["route_schema_version"], "coding_model_route/v1")

            status, stdout, stderr = run_cli(
                base + ["coding", "fanout", "brief", str(contract["fanout_id"])], output_json=False
            )
            self.assertEqual(status, 0, stderr)
            self.assertIn("codex (gpt-5.6-sol high [schema v1])", stdout)
            self.assertNotIn(" — (", stdout)
            self.assertNotIn("alt:", stdout.split("docs")[0].split("core")[-1])

    def test_brief_renders_local_inventory_provider_model_intact(self) -> None:
        # A route frozen from a local-inventory catalog (the omo runtime path,
        # `inventory_model_catalog`) carries a provider-prefixed model id like
        # "openrouter/qwen-3.5-coder"; the slash must survive into the
        # parenthesized label unchanged in both JSON and plain text.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            units = [
                {"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["src/core/"], "role": "brain"},
                {"unit_id": "docs", "title": "Docs", "owner": "claude-code", "file_scope": ["docs/"]},
            ]
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units))
            contract_path = paths.fanout_contracts_dir / str(contract["fanout_id"]) / "fanout_contract.json"
            stored = json.loads(contract_path.read_text(encoding="utf-8"))
            for unit in stored["units"]:
                if unit["unit_id"] == "core":
                    unit["handoff"]["model_route"] = {
                        "schema_version": "coding_model_route/v2",
                        "status": "resolved",
                        "provenance": "role_chain_head",
                        "catalog_kind": "local_inventory",
                        "selected_model": "openrouter/qwen-3.5-coder",
                        "selected_reasoning_effort": "high",
                        "chain": [{"model_id": "openrouter/qwen-3.5-coder", "reasoning_effort": "high"}],
                    }
            contract_path.write_text(json.dumps(stored), encoding="utf-8")
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, stdout, stderr = run_cli(base + ["coding", "fanout", "brief", str(contract["fanout_id"])])
            self.assertEqual(status, 0, stderr)
            brief = json.loads(stdout)
            core = {entry["unit_id"]: entry for entry in brief["units"]}["core"]
            self.assertEqual(core["model_label"], "openrouter/qwen-3.5-coder high")
            self.assertEqual(core["model_alternative"], "")

            status, stdout, stderr = run_cli(
                base + ["coding", "fanout", "brief", str(contract["fanout_id"])], output_json=False
            )
            self.assertEqual(status, 0, stderr)
            self.assertIn("codex (openrouter/qwen-3.5-coder high)", stdout)
            self.assertNotIn(" — (", stdout)
            self.assertNotIn("[schema v1]", stdout)

    def test_brief_without_id_lists_known_fanouts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, _UNITS))
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            status, stdout, stderr = run_cli(base + ["coding", "fanout", "brief"])
            self.assertEqual(status, 0, stderr)
            listing = json.loads(stdout)
            self.assertEqual(listing["schema_version"], "fanout_briefing_listing/v1")
            self.assertEqual(listing["fanouts"][0]["fanout_id"], contract["fanout_id"])
            self.assertEqual(listing["fanouts"][0]["unit_count"], 3)


class FanoutBriefTextCeilingTests(unittest.TestCase):
    """The plain-text brief stays under the generic messenger soft ceiling.

    Past ~1600 chars a messenger clips the message at an arbitrary byte, so
    `_render_fanout_brief_text` keeps the first rows that fit and states the
    omission as its own line instead of emitting unbounded output.
    """

    @staticmethod
    def _payload(unit_count: int) -> dict:
        units = [
            {
                "unit_id": f"unit-{index:02d}",
                "owner": "codex",
                "model_label": "gpt-5.6-sol xhigh",
                "model_alternative": "",
                "route_schema_version": "coding_model_route/v2",
                "status": "completed",
                "elapsed_seconds": 35,
                "tokens_total": 128400,
                "session_ref": f"sess-{index:02d}",
                "summary": "implemented the slice and ran the targeted tests",
            }
            for index in range(unit_count)
        ]
        return {
            "fanout_id": "fanout-0123456789ab",
            "units": units,
            "claim_boundary": "Boundary text.",
        }

    def test_short_brief_renders_every_row_without_an_omission_line(self) -> None:
        from omh.commands.coding import _render_fanout_brief_text

        text = _render_fanout_brief_text(self._payload(3))
        self.assertEqual(text.count("- unit-"), 3)
        self.assertNotIn("more units", text)

    def test_long_brief_keeps_first_rows_and_states_the_omission(self) -> None:
        from omh.commands.coding import _FANOUT_BRIEF_TEXT_SOFT_LIMIT, _render_fanout_brief_text

        text = _render_fanout_brief_text(self._payload(40))
        self.assertLessEqual(len(text), _FANOUT_BRIEF_TEXT_SOFT_LIMIT)
        shown = text.count("- unit-")
        self.assertGreater(shown, 0)
        self.assertLess(shown, 40)
        # Merge order is preserved: what is shown is exactly the first rows.
        for index in range(shown):
            self.assertIn(f"- unit-{index:02d} —", text)
        self.assertNotIn(f"- unit-{shown:02d} —", text)
        self.assertIn(f"… +{40 - shown} more units — omh coding fanout brief --json", text)
        # The claim boundary survives truncation as the last line.
        self.assertTrue(text.endswith("Boundary text."))


_PY = shlex.quote(sys.executable)
_PASSING_COMMAND = f"{_PY} -c pass"
_FAILING_COMMAND = f"{_PY} -c 'import sys; sys.stdout.write(\"boom\"); sys.exit(3)'"
_ENV_COMMAND = f"OMH_VERIFY=1 {_PY} -c 'import os,sys; sys.exit(0 if os.environ.get(\"OMH_VERIFY\") else 1)'"
# Well over the 300-byte verification tail, so the dispatcher has to spill.
_FLOODING_COMMAND = f"{_PY} -c 'import sys; sys.stdout.write(\"flood\" * 900); sys.exit(4)'"
_FLOODING_OUTPUT = "flood" * 900


def _verification_runner(script: Path, sidecar: Path, payload: dict[str, object], *, mode: str = "valid"):
    """Agent spawns write a sidecar; verification commands really run."""
    verified: list[list[str]] = []
    verification_envs: list[dict[str, str]] = []

    def runner(argv, **kwargs):
        if argv[0] == "git":
            return subprocess.run(argv, **kwargs)
        if argv[0] in {"codex", "claude"}:
            return subprocess.run(
                [sys.executable, str(script), mode, str(sidecar), json.dumps(payload)],
                cwd=kwargs.get("cwd"),
                text=True,
                capture_output=True,
                timeout=kwargs.get("timeout"),
            )
        verified.append(list(argv))
        verification_envs.append(dict(kwargs.get("env") or {}))
        return subprocess.run(
            argv,
            cwd=kwargs.get("cwd"),
            env=kwargs.get("env"),
            text=True,
            capture_output=True,
            timeout=kwargs.get("timeout"),
        )

    runner.verified = verified
    runner.verification_envs = verification_envs
    return runner


class FanoutUnitOutputSpillTests(unittest.TestCase):
    def test_a_flooding_unit_spills_and_the_journal_line_stays_resolvable(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            contract = write_fanout_contract(
                paths, build_fanout_contract(_GOAL, [dict(unit) for unit in _UNITS])
            )
            sidecar = unit_result_path(paths, contract["fanout_id"], "core")
            payload = _unit_result_payload(contract, sha)
            flood = "flood-line\n" * 900

            def runner(argv, **kwargs):
                if argv[0] == "git":
                    return subprocess.run(argv, **kwargs)
                sidecar.parent.mkdir(parents=True, exist_ok=True)
                sidecar.write_text(json.dumps(payload), encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0, flood, "")

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["core"],
                runner=runner,
                readiness=_ready,
            )
            core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]

            record = core["output_truncation"]
            self.assertTrue(record["truncated"])
            self.assertEqual(record["reason_code"], "output_cap")
            self.assertEqual(record["original_bytes"], len(flood))
            self.assertEqual(record["kept_bytes"], 2000)
            self.assertEqual(record["spill_status"], "written")
            self.assertEqual(resolve_spill_reference(record["spill"]), flood)
            self.assertFalse(core["stderr_truncation"]["truncated"])

            events = show_run(paths, core["run_ref"])["journal_events"]
            worker = [event for event in events if event["event"] == "executor_result_observed"][-1]
            # The journal caps `summary` at 500 characters, so the notice it
            # carries is the compact one and the resolvable pointer rides in
            # `evidence_refs` where nothing can cut it in half.
            self.assertIn("[output truncated:", worker["summary"])
            self.assertIn("continuation=evidence_refs", worker["summary"])
            self.assertTrue(worker["summary"].endswith("]"))
            self.assertLess(len(worker["summary"]), 500)
            self.assertNotIn("...", worker["summary"])
            self.assertEqual(
                worker["evidence_refs"],
                [
                    f"output_spill:{record['spill']['path']}"
                    f":sha256:{record['spill']['sha256']}:{record['spill']['byte_count']}"
                ],
            )


class FanoutDispatchVerificationTests(unittest.TestCase):
    def _setup(self, tmp: str, commands: list[str], *, mode: str = "valid"):
        root = Path(tmp)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        units = [dict(unit) for unit in _UNITS]
        units[0]["verification_commands"] = commands
        contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units))
        sidecar = unit_result_path(paths, contract["fanout_id"], "core")
        runner = _verification_runner(
            _stub_executor_script(root),
            sidecar,
            _unit_result_payload(contract, sha),
            mode=mode,
        )
        return paths, repo, sha, contract, runner

    def _dispatch(self, paths, repo, sha, contract, runner, **kwargs):
        summary = dispatch_fanout(
            paths,
            contract,
            goal_text=_GOAL,
            repo_root=repo,
            base_sha=sha,
            only_units=["core"],
            runner=runner,
            readiness=_ready,
            **kwargs,
        )
        return {entry["unit_id"]: entry for entry in summary["units"]}["core"]

    def test_all_passing_commands_are_dispatcher_observed_and_flip_the_ladder(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, runner = self._setup(tmp, [_PASSING_COMMAND, _ENV_COMMAND])

            core = self._dispatch(paths, repo, sha, contract, runner, run_verification=True)

            self.assertEqual(core["verification_status"], "passed")
            self.assertEqual(len(core["verification_checks"]), 2)
            for row in core["verification_checks"]:
                self.assertEqual(row["status"], "passed")
                self.assertEqual(row["reported_by"], "dispatcher")
                self.assertEqual(row["observed_by"], "dispatcher")
                self.assertEqual(row["observation_source"], "dispatch_verification")
            self.assertNotIn("verification_failures", core)
            self.assertIn("not review, CI", core["verification_claim_boundary"])
            # The ladder flips from the journal event the run appended, not from
            # the row list: the existing reader is what advances it.
            self.assertTrue(_unit_verification_is_observed(paths, core["run_ref"]))
            self.assertTrue(core["unit_verification_observed"])
            self.assertTrue(core["integration_ready"])
            self.assertEqual(len(runner.verified), 2)

    def test_a_failing_command_keeps_the_unit_short_of_integration_ready(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, runner = self._setup(tmp, [_PASSING_COMMAND, _FAILING_COMMAND])

            core = self._dispatch(paths, repo, sha, contract, runner, run_verification=True)

            self.assertEqual(core["verification_status"], "failed")
            self.assertEqual([row["status"] for row in core["verification_checks"]], ["passed", "failed"])
            self.assertEqual(len(core["verification_failures"]), 1)
            self.assertIn("exit 3: boom", core["verification_failures"][0])
            self.assertFalse(_unit_verification_is_observed(paths, core["run_ref"]))
            self.assertFalse(core["unit_verification_observed"])
            self.assertFalse(core["integration_ready"])
            # The unit's own process still succeeded; only verification failed.
            self.assertTrue(core["process_succeeded"])
            self.assertTrue(core["result_schema_valid"])

    def test_a_short_failure_records_that_its_output_was_not_truncated(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, runner = self._setup(tmp, [_FAILING_COMMAND])

            core = self._dispatch(paths, repo, sha, contract, runner, run_verification=True)

            records = core["verification_output_truncation"]
            self.assertEqual(len(records), 1)
            self.assertFalse(records[0]["truncated"])
            self.assertEqual(records[0]["reason_code"], "not_truncated")
            self.assertNotIn("[output truncated:", core["verification_failures"][0])

    def test_a_flooding_failure_spills_and_the_failure_row_names_the_spill(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, runner = self._setup(tmp, [_FLOODING_COMMAND])

            core = self._dispatch(paths, repo, sha, contract, runner, run_verification=True)

            records = core["verification_output_truncation"]
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertTrue(record["truncated"])
            self.assertEqual(record["reason_code"], "output_cap")
            self.assertEqual(record["original_bytes"], len(_FLOODING_OUTPUT))
            self.assertEqual(record["kept_bytes"], 300)
            self.assertEqual(record["spill_status"], "written")
            # The rendered row -- the surface a reader actually sees -- says
            # truncated, why, and where the rest lives.
            detail = core["verification_failures"][0]
            self.assertIn("[output truncated:", detail)
            self.assertIn("reason=output_cap", detail)
            self.assertIn(record["spill"]["path"], detail)
            self.assertNotIn("...", detail)
            self.assertEqual(resolve_spill_reference(record["spill"]), _FLOODING_OUTPUT)

    def test_a_command_that_cannot_start_is_a_failed_check_not_a_failed_dispatch(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, runner = self._setup(
                tmp, ["omh-no-such-verification-binary --check"]
            )

            core = self._dispatch(paths, repo, sha, contract, runner, run_verification=True)

            self.assertEqual(core["verification_status"], "failed")
            self.assertEqual(core["status"], "completed")
            self.assertIn("not found on PATH", core["verification_failures"][0])

    def test_nothing_runs_without_the_explicit_flag(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, runner = self._setup(tmp, [_PASSING_COMMAND])

            core = self._dispatch(paths, repo, sha, contract, runner)

            self.assertNotIn("verification_status", core)
            self.assertNotIn("verification_checks", core)
            self.assertEqual(runner.verified, [])
            self.assertFalse(core["unit_verification_observed"])
            self.assertFalse(core["integration_ready"])

    def test_a_unit_declaring_no_commands_is_unchanged_under_the_flag(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, runner = self._setup(tmp, [])

            core = self._dispatch(paths, repo, sha, contract, runner, run_verification=True)

            self.assertNotIn("verification_status", core)
            self.assertEqual(runner.verified, [])
            self.assertFalse(core["unit_verification_observed"])

    def test_verification_waits_on_a_sidecar_that_validated(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, runner = self._setup(tmp, [_PASSING_COMMAND], mode="corrupt")

            core = self._dispatch(paths, repo, sha, contract, runner, run_verification=True)

            self.assertFalse(core["result_schema_valid"])
            self.assertNotIn("verification_status", core)
            self.assertEqual(runner.verified, [])

    def test_dry_run_names_the_commands_the_flag_would_run(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, runner = self._setup(tmp, [_PASSING_COMMAND])

            planned = self._dispatch(
                paths, repo, sha, contract, runner, dry_run=True, run_verification=True
            )
            self.assertEqual(planned["planned_verification_commands"], [_PASSING_COMMAND])

            without = self._dispatch(paths, repo, sha, contract, runner, dry_run=True)
            self.assertNotIn("planned_verification_commands", without)
            self.assertEqual(runner.verified, [])


class FanoutDispatchPlannedVerificationTests(unittest.TestCase):
    """Contracts carrying `verification_checks` metadata run through the
    revision-bound plan engine; metadata-free contracts keep the legacy loop."""

    def _setup(self, tmp: str, checks: list[dict[str, object]], *, mode: str = "valid"):
        root = Path(tmp)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        units = [dict(unit) for unit in _UNITS]
        units[0]["verification_checks"] = checks
        contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units))
        sidecar = unit_result_path(paths, contract["fanout_id"], "core")
        runner = _verification_runner(
            _stub_executor_script(root),
            sidecar,
            _unit_result_payload(contract, sha),
            mode=mode,
        )
        return paths, repo, sha, contract, runner

    def _dispatch(self, paths, repo, sha, contract, runner, **kwargs):
        summary = dispatch_fanout(
            paths,
            contract,
            goal_text=_GOAL,
            repo_root=repo,
            base_sha=sha,
            only_units=["core"],
            runner=runner,
            readiness=_ready,
            **kwargs,
        )
        return {entry["unit_id"]: entry for entry in summary["units"]}["core"]

    def test_planned_read_only_checks_pass_and_flip_the_ladder(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, runner = self._setup(
                tmp,
                [
                    {"command": _PASSING_COMMAND, "id": "unit-tests", "safety": "read_only"},
                    {"command": _ENV_COMMAND, "id": "env-gate", "safety": "read_only"},
                ],
            )

            core = self._dispatch(
                paths,
                repo,
                sha,
                contract,
                runner,
                run_verification=True,
                env={"PATH": os.environ["PATH"], "API_TOKEN": "ambient-secret"},
            )

            self.assertEqual(core["verification_status"], "passed")
            self.assertEqual(core["verification_plan_schema"], "verification_plan/v1")
            self.assertEqual(len(core["verification_checks"]), 2)
            for row in core["verification_checks"]:
                self.assertEqual(row["status"], "passed")
                self.assertEqual(row["tier"], "unit")
                self.assertTrue(row["check_id"])
                self.assertNotIn("reused", row)
            self.assertTrue(core["verification_receipts"])
            self.assertTrue(_unit_verification_is_observed(paths, core["run_ref"]))
            self.assertTrue(core["integration_ready"])
            self.assertEqual(len(runner.verified), 2)
            self.assertTrue(runner.verification_envs)
            self.assertTrue(all("API_TOKEN" not in env for env in runner.verification_envs))
            self.assertTrue(all(env["OMH_FANOUT_DEPTH"] == "1" for env in runner.verification_envs))

    def test_a_failed_red_check_blocks_its_green_dependent(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, runner = self._setup(
                tmp,
                [
                    {"command": _FAILING_COMMAND, "id": "red", "safety": "read_only"},
                    {"command": _PASSING_COMMAND, "id": "green", "depends_on": ["red"]},
                ],
            )

            core = self._dispatch(paths, repo, sha, contract, runner, run_verification=True)

            self.assertEqual(core["verification_status"], "failed")
            self.assertEqual(
                [row["status"] for row in core["verification_checks"]], ["failed", "skipped"]
            )
            # GREEN never started: exactly one process ran.
            self.assertEqual(len(runner.verified), 1)
            self.assertFalse(_unit_verification_is_observed(paths, core["run_ref"]))
            self.assertFalse(core["integration_ready"])

    def test_a_metadata_free_contract_keeps_the_legacy_serial_rows(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            units = [dict(unit) for unit in _UNITS]
            units[0]["verification_commands"] = [_PASSING_COMMAND, _ENV_COMMAND]
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units))
            sidecar = unit_result_path(paths, contract["fanout_id"], "core")
            runner = _verification_runner(
                _stub_executor_script(root), sidecar, _unit_result_payload(contract, sha)
            )

            core = self._dispatch(paths, repo, sha, contract, runner, run_verification=True)

            self.assertEqual(core["verification_status"], "passed")
            self.assertNotIn("verification_plan_schema", core)
            for row in core["verification_checks"]:
                self.assertNotIn("check_id", row)
                self.assertNotIn("reused", row)
            self.assertEqual(
                [row["command"] for row in core["verification_checks"]],
                [_PASSING_COMMAND, _ENV_COMMAND],
            )
            self.assertTrue(core["integration_ready"])

    def _two_unit_setup(
        self, tmp: str, checks: list[dict[str, object]], *, producer_head_outside_integrated: bool = False
    ):
        root = Path(tmp)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        producer_head_sha = sha
        if producer_head_outside_integrated:
            branch = subprocess.run(
                ["git", "branch", "--show-current"], cwd=repo, check=True, text=True, capture_output=True
            ).stdout.strip()
            _git(repo, "checkout", "-qb", "producer")
            (repo / "producer.txt").write_text("producer\n", encoding="utf-8")
            _git(repo, "add", "producer.txt")
            _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "producer")
            producer_head_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
            ).stdout.strip()
            _git(repo, "checkout", "-q", branch)
        units = [dict(_UNITS[0]), dict(_UNITS[1])]
        units[0]["verification_checks"] = checks
        contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units))
        script = _stub_executor_script(root)
        sidecars = {
            "codex": (
                unit_result_path(paths, contract["fanout_id"], "core"),
                _unit_result_payload(contract, sha, "core", head_sha=producer_head_sha),
            ),
            "claude": (
                unit_result_path(paths, contract["fanout_id"], "docs"),
                _unit_result_payload(contract, sha, "docs"),
            ),
        }
        verified: list[list[str]] = []

        def runner(argv, **kwargs):
            if argv[0] == "git":
                return subprocess.run(argv, **kwargs)
            if argv[0] in sidecars:
                sidecar, payload = sidecars[argv[0]]
                return subprocess.run(
                    [sys.executable, str(script), "valid", str(sidecar), json.dumps(payload)],
                    cwd=kwargs.get("cwd"),
                    text=True,
                    capture_output=True,
                    timeout=kwargs.get("timeout"),
                )
            verified.append(list(argv))
            return subprocess.run(
                argv,
                cwd=kwargs.get("cwd"),
                env=kwargs.get("env"),
                text=True,
                capture_output=True,
                timeout=kwargs.get("timeout"),
            )

        runner.verified = verified
        return paths, repo, sha, contract, runner

    def test_an_integration_check_runs_after_the_producer_lanes_fan_in(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, runner = self._two_unit_setup(
                tmp,
                [
                    {"command": _PASSING_COMMAND, "id": "unit-tests", "safety": "read_only"},
                    {"command": _ENV_COMMAND, "id": "full-gate", "tier": "integration"},
                ],
            )

            integrated_revision = subprocess.run(
                ["git", "rev-parse", "HEAD^{tree}"], cwd=repo, check=True, text=True, capture_output=True
            ).stdout.strip()
            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=runner,
                readiness=_ready,
                run_verification=True,
                integrated_worktree=repo,
                integrated_revision=integrated_revision,
            )
            entries = {entry["unit_id"]: entry for entry in summary["units"]}
            core = entries["core"]

            self.assertEqual(entries["docs"]["status"], "completed")
            self.assertEqual(core["producer_head_sha"], sha)
            self.assertEqual(core["verification_status"], "passed")
            rows = core["verification_checks"]
            self.assertEqual([row["tier"] for row in rows], ["unit", "integration"])
            # The full gate is bound to the supplied integrated checkout, not
            # a producer receipt: only the unit-tier command could run there.
            self.assertNotIn("reused", rows[0])
            self.assertNotIn("reused", rows[1])
            # The unit-tier check ran once in its producer worktree; the full
            # gate ran once after fan-in against the explicit integrated tree.
            self.assertEqual(len(runner.verified), 2)
            self.assertTrue(core["unit_verification_observed"])
            self.assertTrue(core["integration_ready"])

    def test_selected_lane_fan_in_runs_an_integrated_gate_without_unselected_units(self) -> None:
        # Given a two-unit contract where only core is selected for this dispatch
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, runner = self._two_unit_setup(
                tmp,
                [
                    {"command": _PASSING_COMMAND, "id": "unit-tests", "safety": "read_only"},
                    {"command": _ENV_COMMAND, "id": "full-gate", "tier": "integration"},
                ],
            )
            integrated_revision = subprocess.run(
                ["git", "rev-parse", "HEAD^{tree}"], cwd=repo, check=True, text=True, capture_output=True
            ).stdout.strip()

            # When the selected producer completes against the clean integrated checkout
            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["core"],
                runner=runner,
                readiness=_ready,
                run_verification=True,
                integrated_worktree=repo,
                integrated_revision=integrated_revision,
            )

            # Then only core contributes producer evidence and its valid broad gate runs.
            entries = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(entries["docs"]["status"], "not_selected")
            self.assertEqual(entries["core"]["verification_status"], "passed")
            self.assertEqual([row["tier"] for row in entries["core"]["verification_checks"]], ["unit", "integration"])
            self.assertEqual(len(runner.verified), 2)

    def test_an_integration_gate_holds_when_the_supplied_tree_revision_is_stale(self) -> None:
        # Given producer work and an explicitly supplied integrated checkout
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, runner = self._two_unit_setup(
                tmp,
                [
                    {"command": _PASSING_COMMAND, "id": "unit-tests", "safety": "read_only"},
                    {"command": _ENV_COMMAND, "id": "full-gate", "tier": "integration"},
                ],
            )

            # When the caller's revision does not bind that checkout exactly
            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=runner,
                readiness=_ready,
                run_verification=True,
                integrated_worktree=repo,
                integrated_revision="stale-tree",
            )

            # Then no full gate process is spawned and integration remains HOLD.
            core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]
            self.assertEqual(core["verification_status"], "held")
            self.assertFalse(core["unit_verification_observed"])
            self.assertEqual(len(runner.verified), 1)

    def test_a_forged_sidecar_head_cannot_substitute_for_the_observed_producer_head(self) -> None:
        # Given a clean integrated checkout at base and a producer whose actual
        # HEAD moved while its sidecar falsely reports the base revision
        with TemporaryDirectory() as tmp:
            repo, base_sha = _make_repo(Path(tmp))
            branch = subprocess.run(
                ["git", "branch", "--show-current"], cwd=repo, check=True, text=True, capture_output=True
            ).stdout.strip()
            _git(repo, "checkout", "-qb", "producer")
            (repo / "producer.txt").write_text("producer\n", encoding="utf-8")
            _git(repo, "add", "producer.txt")
            _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "producer")
            observed_head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
            ).stdout.strip()
            _git(repo, "checkout", "-q", branch)
            results = {
                "core": {
                    "unit_result": {"head_sha": base_sha},
                    "producer_head_sha": observed_head,
                }
            }

            # When fan-in checks ancestry, Then it uses the dispatcher's actual
            # post-execution observation, not the executor-reported base SHA.
            self.assertFalse(_integrated_checkout_contains_producer_heads(subprocess.run, repo, results))

    def test_a_forged_base_sidecar_after_producer_head_moves_holds_the_integration_gate(self) -> None:
        # Given an executor that commits after reporting the stale base SHA
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, original_runner = self._two_unit_setup(
                tmp,
                [
                    {"command": _PASSING_COMMAND, "id": "unit-tests", "safety": "read_only"},
                    {"command": _ENV_COMMAND, "id": "full-gate", "tier": "integration"},
                ],
            )
            committed = threading.Event()

            def runner(argv, **kwargs):
                completed = original_runner(argv, **kwargs)
                if argv[0] == "codex" and not committed.is_set():
                    worktree = Path(kwargs["cwd"])
                    (worktree / "moved-after-sidecar.txt").write_text("moved\n", encoding="utf-8")
                    _git(worktree, "add", "moved-after-sidecar.txt")
                    _git(worktree, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "moved")
                    committed.set()
                return completed

            integrated_revision = subprocess.run(
                ["git", "rev-parse", "HEAD^{tree}"], cwd=repo, check=True, text=True, capture_output=True
            ).stdout.strip()

            # When dispatch observes the producer after process completion,
            # Then stale sidecar identity invalidates producer evidence and no gate runs.
            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["core"],
                runner=runner,
                readiness=_ready,
                run_verification=True,
                integrated_worktree=repo,
                integrated_revision=integrated_revision,
            )
            core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]
            self.assertTrue(committed.is_set())
            self.assertFalse(core["result_schema_valid"])
            self.assertNotIn("verification_status", core)
            self.assertEqual(original_runner.verified, [])

    def test_a_dirty_producer_cannot_enter_integration_fan_in(self) -> None:
        # Given an executor that leaves uncommitted content after a valid sidecar
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, original_runner = self._two_unit_setup(
                tmp,
                [
                    {"command": _PASSING_COMMAND, "id": "unit-tests", "safety": "read_only"},
                    {"command": _ENV_COMMAND, "id": "full-gate", "tier": "integration"},
                ],
            )
            dirtied = threading.Event()

            def runner(argv, **kwargs):
                completed = original_runner(argv, **kwargs)
                if argv[0] == "codex" and not dirtied.is_set():
                    (Path(kwargs["cwd"]) / "dirty-after-sidecar.txt").write_text("dirty\n", encoding="utf-8")
                    dirtied.set()
                return completed

            integrated_revision = subprocess.run(
                ["git", "rev-parse", "HEAD^{tree}"], cwd=repo, check=True, text=True, capture_output=True
            ).stdout.strip()
            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["core"],
                runner=runner,
                readiness=_ready,
                run_verification=True,
                integrated_worktree=repo,
                integrated_revision=integrated_revision,
            )

            # Then canonical identity cannot be observed and integration remains HOLD.
            core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]
            self.assertTrue(dirtied.is_set())
            self.assertFalse(core["result_schema_valid"])
            self.assertNotIn("verification_status", core)
            self.assertEqual(original_runner.verified, [])

    def test_a_clean_integrated_checkout_missing_a_producer_commit_holds_without_a_full_gate(self) -> None:
        # Given producer evidence that names a commit outside the clean base checkout
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, runner = self._two_unit_setup(
                tmp,
                [
                    {"command": _PASSING_COMMAND, "id": "unit-tests", "safety": "read_only"},
                    {"command": _ENV_COMMAND, "id": "full-gate", "tier": "integration"},
                ],
                producer_head_outside_integrated=True,
            )
            integrated_revision = subprocess.run(
                ["git", "rev-parse", "HEAD^{tree}"], cwd=repo, check=True, text=True, capture_output=True
            ).stdout.strip()

            # When the supplied clean checkout omits the observed producer commit
            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=runner,
                readiness=_ready,
                run_verification=True,
                integrated_worktree=repo,
                integrated_revision=integrated_revision,
            )

            # Then the mismatched sidecar fails producer identity before any
            # producer or integration verification can be claimed.
            core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]
            self.assertNotIn("verification_status", core)
            self.assertFalse(core["unit_verification_observed"])
            self.assertEqual(len(runner.verified), 0)

    def test_a_failing_integration_check_holds_the_unit_after_fan_in(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, runner = self._two_unit_setup(
                tmp,
                [
                    {"command": _PASSING_COMMAND, "id": "unit-tests", "safety": "read_only"},
                    {"command": _FAILING_COMMAND, "id": "full-gate", "tier": "integration"},
                ],
            )

            integrated_revision = subprocess.run(
                ["git", "rev-parse", "HEAD^{tree}"], cwd=repo, check=True, text=True, capture_output=True
            ).stdout.strip()
            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=runner,
                readiness=_ready,
                run_verification=True,
                integrated_worktree=repo,
                integrated_revision=integrated_revision,
            )
            core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]

            self.assertEqual(core["verification_status"], "failed")
            self.assertEqual(
                [row["status"] for row in core["verification_checks"]], ["passed", "failed"]
            )
            self.assertFalse(core["unit_verification_observed"])
            self.assertFalse(core["integration_ready"])

    def test_dispatch_shuts_the_shared_execution_gate_after_recovery_raises(self) -> None:
        # Given a dispatch-scoped verification gate and a recovery seam that fails
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract, runner = self._setup(
                tmp, [{"command": _PASSING_COMMAND, "id": "unit-tests", "safety": "read_only"}]
            )
            closed = threading.Event()

            class TrackingGate(VerificationExecutionGate):
                def shutdown(self) -> None:
                    super().shutdown()
                    closed.set()

            # When post-pool recovery raises, Then the gate is still shut down.
            with (
                mock.patch("omh.coding.fanout_dispatch.VerificationExecutionGate", TrackingGate),
                mock.patch(
                    "omh.coding.fanout_dispatch._run_failure_recovery", side_effect=RuntimeError("recovery")
                ),
                self.assertRaisesRegex(RuntimeError, "recovery"),
            ):
                self._dispatch(paths, repo, sha, contract, runner, run_verification=True)
            self.assertTrue(closed.is_set())

    def test_the_aggregate_decision_matches_the_serial_path(self) -> None:
        decisions: list[tuple[str, list[str], bool, bool]] = []
        for tmp_index, use_metadata in enumerate((False, True)):
            with TemporaryDirectory() as tmp:
                if use_metadata:
                    paths, repo, sha, contract, runner = self._setup(
                        tmp,
                        [
                            {"command": _PASSING_COMMAND, "id": "a"},
                            {"command": _FAILING_COMMAND, "id": "b"},
                        ],
                    )
                else:
                    root = Path(tmp)
                    paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
                    repo, sha = _make_repo(root)
                    units = [dict(unit) for unit in _UNITS]
                    units[0]["verification_commands"] = [_PASSING_COMMAND, _FAILING_COMMAND]
                    contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units))
                    sidecar = unit_result_path(paths, contract["fanout_id"], "core")
                    runner = _verification_runner(
                        _stub_executor_script(root), sidecar, _unit_result_payload(contract, sha)
                    )

                core = self._dispatch(paths, repo, sha, contract, runner, run_verification=True)
                decisions.append(
                    (
                        core["verification_status"],
                        [row["status"] for row in core["verification_checks"]],
                        core["unit_verification_observed"],
                        core["integration_ready"],
                    )
                )

        self.assertEqual(decisions[0], decisions[1])
        self.assertEqual(decisions[0][0], "failed")


class FanoutDispatchVerificationCliTests(unittest.TestCase):
    def _prepare(self, root: Path, base: list[str]) -> str:
        units_path = root / "units.json"
        units = [dict(unit) for unit in _UNITS]
        units[0]["verification_commands"] = [_PASSING_COMMAND]
        units_path.write_text(json.dumps(units), encoding="utf-8")
        status, stdout, stderr = run_cli(
            base
            + ["coding", "fanout", "prepare", "--goal", *_GOAL.split(), "--units", str(units_path), "--record"]
        )
        self.assertEqual(status, 0, stderr)
        contract = json.loads(stdout)
        units_by_id = {unit["unit_id"]: unit for unit in contract["units"]}
        self.assertEqual(units_by_id["core"]["verification_commands"], [_PASSING_COMMAND])
        return str(contract["fanout_id"])

    def test_flag_is_off_by_default_and_threaded_when_passed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, _sha = _make_repo(root)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            fanout_id = self._prepare(root, base)
            goal_path = root / "goal.txt"
            goal_path.write_text(_GOAL, encoding="utf-8")
            captured: dict[str, object] = {}

            def fake_dispatch(paths, contract, **kwargs):
                captured.update(kwargs)
                return {"schema_version": "fanout_dispatch_summary/v1", "units": []}

            argv = base + [
                "coding",
                "fanout",
                "dispatch",
                fanout_id,
                "--goal-file",
                str(goal_path),
                "--repo-root",
                str(repo),
                "--dry-run",
            ]
            with mock.patch("omh.coding.fanout_dispatch.dispatch_fanout", fake_dispatch):
                status, _stdout, stderr = run_cli(argv)
            self.assertEqual(status, 0, stderr)
            self.assertFalse(captured["run_verification"])

            with mock.patch("omh.coding.fanout_dispatch.dispatch_fanout", fake_dispatch):
                status, _stdout, stderr = run_cli(argv + ["--run-verification"])
            self.assertEqual(status, 0, stderr)
            self.assertTrue(captured["run_verification"])

    def test_health_events_flag_is_threaded_to_dispatch(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, _sha = _make_repo(root)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            fanout_id = self._prepare(root, base)
            goal_path = root / "goal.txt"
            goal_path.write_text(_GOAL, encoding="utf-8")
            captured: dict[str, object] = {}

            def fake_dispatch(paths, contract, **kwargs):
                captured.update(kwargs)
                return {"schema_version": "fanout_dispatch_summary/v1", "units": []}

            argv = base + [
                "coding", "fanout", "dispatch", fanout_id, "--goal-file", str(goal_path),
                "--repo-root", str(repo), "--dry-run",
            ]
            with mock.patch("omh.coding.fanout_dispatch.dispatch_fanout", fake_dispatch):
                status, _stdout, stderr = run_cli(argv)
            self.assertEqual(status, 0, stderr)
            self.assertFalse(captured["emit_health_events"])

            with mock.patch("omh.coding.fanout_dispatch.dispatch_fanout", fake_dispatch):
                status, _stdout, stderr = run_cli(argv + ["--health-events"])
            self.assertEqual(status, 0, stderr)
            self.assertTrue(captured["emit_health_events"])

    def test_integration_target_requires_verification_and_a_complete_pair(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, _sha = _make_repo(root)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            fanout_id = self._prepare(root, base)
            goal_path = root / "goal.txt"
            goal_path.write_text(_GOAL, encoding="utf-8")
            argv = base + [
                "coding",
                "fanout",
                "dispatch",
                fanout_id,
                "--goal-file",
                str(goal_path),
                "--repo-root",
                str(repo),
                "--dry-run",
            ]

            for incomplete in (
                ["--integration-worktree", str(repo)],
                ["--integration-revision", "tree"],
            ):
                with self.subTest(incomplete=incomplete):
                    status, _stdout, stderr = run_cli(argv + incomplete)
                    self.assertNotEqual(status, 0)
                    self.assertIn("must be supplied together", stderr)

            with mock.patch(
                "omh.coding.fanout_dispatch.dispatch_fanout",
                return_value={"schema_version": "fanout_dispatch_summary/v1", "units": []},
            ) as dispatch:
                status, _stdout, stderr = run_cli(
                    argv
                    + [
                        "--integration-worktree",
                        str(repo),
                        "--integration-revision",
                        "tree",
                    ]
                )
            self.assertNotEqual(status, 0)
            self.assertIn("require --run-verification", stderr)
            dispatch.assert_not_called()


class SpawnStaggerTests(unittest.TestCase):
    """Cache-warm dispatch spacing: the first real spawn writes the provider
    prompt cache the byte-identical sibling preambles read, so real spawns are
    staggered while injected test runners stay untouched."""

    def test_reserve_spaces_consecutive_slots(self) -> None:
        # A real wall-clock sleep here is inherently racy under CPU
        # contention: the assertion has been observed failing on loaded
        # machines when the scheduler delivers a slightly-short gap. Inject
        # a fake clock/sleep instead — same seam as the retry policy's
        # `sleep` parameter elsewhere in this module — and assert on the
        # reservation schedule the code actually computed, which is
        # deterministic regardless of real scheduling.
        from omh.coding.fanout_dispatch import _SpawnStagger

        class _FakeClock:
            def __init__(self) -> None:
                self.now = 0.0
                self.slept: list[float] = []

            def monotonic(self) -> float:
                return self.now

            def sleep(self, seconds: float) -> None:
                self.slept.append(seconds)
                self.now += seconds

        clock = _FakeClock()
        stagger = _SpawnStagger(0.05, monotonic=clock.monotonic, sleep=clock.sleep)
        starts: list[float] = []
        for _ in range(3):
            stagger.reserve()
            starts.append(clock.now)
        self.assertGreaterEqual(starts[1] - starts[0], 0.045)
        self.assertGreaterEqual(starts[2] - starts[1], 0.045)
        # The fake sleep advances the clock by exactly the requested delay,
        # so the reserved slots land exactly one interval apart.
        self.assertEqual(clock.slept, [0.05, 0.05])

    def test_injected_runner_without_marker_never_staggers(self) -> None:
        import time as _time

        import omh.coding.fanout_dispatch as engine

        units = [
            {"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["src/core/"]},
            {"unit_id": "docs", "title": "Docs", "owner": "claude-code", "file_scope": ["docs/"]},
        ]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units))
            started = _time.monotonic()
            with mock.patch.object(engine, "CACHE_WARM_SPAWN_STAGGER_SECONDS", 60.0):
                summary = dispatch_fanout(
                    paths,
                    contract,
                    goal_text=_GOAL,
                    repo_root=repo,
                    base_sha=sha,
                    runner=_agent_runner(),
                    readiness=_ready,
                )
            elapsed = _time.monotonic() - started
            statuses = {entry["unit_id"]: entry["status"] for entry in summary["units"]}
            self.assertEqual(statuses, {"core": "completed", "docs": "completed"})
            # A 60s interval that engaged would hold the second spawn for a
            # minute; injected runners without accepts_on_spawn never wait.
            self.assertLess(elapsed, 30.0)

    def test_marked_runner_spawns_are_spaced(self) -> None:
        import time as _time

        import omh.coding.fanout_dispatch as engine

        units = [
            {"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["src/core/"]},
            {"unit_id": "docs", "title": "Docs", "owner": "claude-code", "file_scope": ["docs/"]},
        ]
        spawn_times: list[float] = []

        def runner(argv, **kwargs):
            if argv[0] == "git":
                return subprocess.run(argv, **kwargs)
            spawn_times.append(_time.monotonic())
            return _FakeCompleted(0, "done")

        runner.accepts_on_spawn = True
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units))
            with mock.patch.object(engine, "CACHE_WARM_SPAWN_STAGGER_SECONDS", 0.3):
                summary = dispatch_fanout(
                    paths,
                    contract,
                    goal_text=_GOAL,
                    repo_root=repo,
                    base_sha=sha,
                    runner=runner,
                    readiness=_ready,
                )
            statuses = {entry["unit_id"]: entry["status"] for entry in summary["units"]}
            self.assertEqual(statuses, {"core": "completed", "docs": "completed"})
            self.assertEqual(len(spawn_times), 2)
            self.assertGreaterEqual(spawn_times[1] - spawn_times[0], 0.25)


def _env_capturing_runner():
    """Like `_agent_runner`, but keeps the env each fake agent spawn was given."""
    envs: list[dict[str, str]] = []

    def runner(argv, **kwargs):
        if argv[0] == "git":
            return subprocess.run(argv, **kwargs)
        envs.append(dict(kwargs.get("env") or {}))
        return _FakeCompleted(0, "done")

    runner.envs = envs
    return runner


class FanoutSpawnGuardTests(unittest.TestCase):
    """Recursion depth cap and per-run spawn ceiling.

    `omh coding fanout dispatch` is OMH's only surface that starts real
    processes, and a dispatched agent CLI can read its own instructions and
    invoke the same command. These tests pin that a child is stamped with its
    depth, that a stamped process refuses before any spawn, that one run can
    only ever start `run_spawn_ceiling` agents, and — the negative controls —
    that an ordinary operator dispatch is untouched by either bound.
    """

    _TWO_UNITS = [
        {"unit_id": "core", "title": "Core work", "owner": "codex", "file_scope": ["src/core/"]},
        {"unit_id": "docs", "title": "Docs work", "owner": "claude-code", "file_scope": ["docs/"]},
    ]

    def _setup(self, tmp: str, units=None):
        root = Path(tmp)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units or _UNITS))
        return paths, repo, sha, contract

    def test_depth_zero_dispatches_and_records_the_bounds_it_ran_under(self) -> None:
        # The negative control for the whole feature: an operator's own
        # invocation carries no marker, runs normally, and the summary states
        # the bounds rather than leaving them implicit.
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            runner = _agent_runner()
            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=runner,
                readiness=_ready,
                env={},
            )
        self.assertNotIn("refused", summary)
        statuses = {entry["unit_id"]: entry["status"] for entry in summary["units"]}
        self.assertEqual(statuses, {"core": "completed", "docs": "completed", "tests": "completed"})
        self.assertEqual(summary["spawn_guard"]["depth"], 0)
        self.assertEqual(summary["spawn_guard"]["max_depth"], FANOUT_MAX_DEPTH_DEFAULT)
        self.assertEqual(summary["spawn_guard"]["run_spawn_ceiling"], FANOUT_RUN_SPAWN_CEILING_DEFAULT)
        self.assertEqual(summary["spawn_guard"]["spawns_claimed"], 3)

    def test_every_child_environment_carries_the_depth_and_lineage_stamp(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, self._TWO_UNITS)
            runner = _env_capturing_runner()
            dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=runner,
                readiness=_ready,
                env={"PATH": "/usr/bin"},
            )
        self.assertEqual(len(runner.envs), 2)
        lineages = set()
        for child in runner.envs:
            # The base environment is carried through, not replaced: a child
            # that lost PATH would fail for reasons the guard never intended.
            self.assertEqual(child["PATH"], "/usr/bin")
            self.assertEqual(child[FANOUT_DEPTH_ENV_VAR], "1")
            lineages.add(child[FANOUT_LINEAGE_ENV_VAR])
        self.assertEqual(
            lineages,
            {f"{contract['fanout_id']}:core", f"{contract['fanout_id']}:docs"},
        )

    def test_a_nested_lineage_is_appended_not_replaced(self) -> None:
        # Depth 0 with an inherited lineage is the shape a wrapper produces
        # when it stamps provenance itself; the chain must extend so a later
        # refusal names the whole path it came down.
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, self._TWO_UNITS[:1])
            runner = _env_capturing_runner()
            dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["core"],
                runner=runner,
                readiness=_ready,
                env={FANOUT_LINEAGE_ENV_VAR: "outer:seed"},
            )
        self.assertEqual(
            runner.envs[0][FANOUT_LINEAGE_ENV_VAR],
            f"outer:seed/{contract['fanout_id']}:core",
        )

    def test_a_dispatch_at_max_depth_refuses_before_any_spawn(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            runner = _agent_runner()
            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=runner,
                readiness=_ready,
                env={FANOUT_DEPTH_ENV_VAR: "1", FANOUT_LINEAGE_ENV_VAR: "outer:core"},
            )
            self.assertTrue(summary["refused"])
            self.assertEqual(summary["refusal_reason"], "fanout_depth_exceeded")
            self.assertEqual(summary["spawn_guard"]["depth"], 1)
            self.assertEqual(summary["spawn_guard"]["max_depth"], 1)
            self.assertEqual(summary["spawn_guard"]["lineage"], "outer:core")
            self.assertEqual(summary["units"], [])
            # Nothing spawned, and no worktree was built for a unit that was
            # never going to start.
            self.assertEqual(runner.spawned, [])
            self.assertEqual(sorted(p.name for p in Path(tmp).glob("*core*")), [])

    def test_the_depth_refusal_traces_to_the_approval_tier_resolver_and_is_posture_invariant(self) -> None:
        # `dispatch_fanout`'s depth guard now asks
        # `resolve_approval_tier("fanout_recursion_depth", ...)` instead of
        # refusing unconditionally; that operation class carries no
        # `posture_key` (`system.approval_tier.APPROVAL_RULE_TABLE`), so the
        # same refusal must fire in strict posture too.
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            runner = _agent_runner()
            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=runner,
                readiness=_ready,
                env={FANOUT_DEPTH_ENV_VAR: "1", "OMH_SECURITY": "strict"},
            )
            self.assertTrue(summary["refused"])
            self.assertEqual(summary["refusal_reason"], "fanout_depth_exceeded")
            self.assertEqual(runner.spawned, [])
            # And nothing was persisted: a refusal must not overwrite the
            # stored summary of the run that is actually in flight.
            self.assertFalse(fanout_dispatch_summary_path(paths, contract["fanout_id"]).exists())

    def test_a_deeper_marker_refuses_too_and_a_raised_cap_admits_it(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, self._TWO_UNITS[:1])
            refused = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["core"],
                runner=_agent_runner(),
                readiness=_ready,
                env={FANOUT_DEPTH_ENV_VAR: "3"},
            )
            self.assertTrue(refused["refused"])
            # The cap is a tunable, not a hardcoded 1: raising it admits the
            # same depth, and the child is stamped one deeper again.
            runner = _env_capturing_runner()
            allowed = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                only_units=["core"],
                runner=runner,
                readiness=_ready,
                max_depth=4,
                env={FANOUT_DEPTH_ENV_VAR: "3"},
            )
        self.assertNotIn("refused", allowed)
        self.assertEqual(runner.envs[0][FANOUT_DEPTH_ENV_VAR], "4")

    def test_a_corrupt_depth_marker_reads_as_depth_zero(self) -> None:
        # Negative control on the reader: a malformed marker must not read as
        # a LARGER depth and refuse a legitimate operator run.
        from omh.coding.fanout_dispatch import read_fanout_depth

        for raw in ("", "   ", "deep", "-1", "1.5", "٢"):
            self.assertEqual(read_fanout_depth({FANOUT_DEPTH_ENV_VAR: raw}), 0, raw)
        self.assertEqual(read_fanout_depth({}), 0)
        self.assertEqual(read_fanout_depth({FANOUT_DEPTH_ENV_VAR: "2"}), 2)

    def test_the_run_spawn_ceiling_stops_units_it_cannot_afford(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, self._TWO_UNITS)
            runner = _agent_runner()
            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                concurrency=1,
                runner=runner,
                readiness=_ready,
                spawn_ceiling=1,
                env={},
            )
            statuses = {entry["unit_id"]: entry["status"] for entry in summary["units"]}
            self.assertEqual(statuses["core"], "completed")
            self.assertEqual(statuses["docs"], "spawn_ceiling_reached")
            self.assertEqual(len(runner.spawned), 1)
            self.assertEqual(summary["spawn_guard"]["spawns_claimed"], 1)
            refused = next(entry for entry in summary["units"] if entry["unit_id"] == "docs")
            self.assertIn("run_spawn_ceiling", refused["reason"])
            # A unit stopped by the ceiling never reached its worktree, so it
            # claims none of the evidence ladder.
            self.assertFalse(refused["process_succeeded"])
            self.assertFalse(refused["integration_ready"])
            self.assertFalse((repo.parent / f"{repo.name}-unit-docs").exists())

    def test_a_ceiling_above_the_unit_count_changes_nothing(self) -> None:
        # The negative control for the ceiling: an ordinary run inside its
        # budget dispatches exactly as it did before the guard existed.
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            runner = _agent_runner()
            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=runner,
                readiness=_ready,
                spawn_ceiling=10,
                env={},
            )
        statuses = {entry["unit_id"]: entry["status"] for entry in summary["units"]}
        self.assertEqual(statuses, {"core": "completed", "docs": "completed", "tests": "completed"})
        self.assertEqual(len(runner.spawned), 3)

    def test_a_dry_run_neither_spends_the_budget_nor_stamps_a_child(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            runner = _env_capturing_runner()
            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                dry_run=True,
                runner=runner,
                readiness=_ready,
                spawn_ceiling=1,
                env={},
            )
        statuses = {entry["status"] for entry in summary["units"]}
        self.assertEqual(statuses, {"dry_run_planned"})
        self.assertEqual(runner.envs, [])
        self.assertEqual(summary["spawn_guard"]["spawns_claimed"], 0)

    def test_the_cli_prints_the_refusal_and_exits_non_zero(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, self._TWO_UNITS[:1])
            goal = Path(tmp) / "goal.txt"
            goal.write_text(_GOAL, encoding="utf-8")
            argv = [
                "--omh-home",
                str(paths.omh_home),
                "--hermes-home",
                str(paths.hermes_home),
                "coding",
                "fanout",
                "dispatch",
                contract["fanout_id"],
                "--goal-file",
                str(goal),
                "--repo-root",
                str(repo),
                "--dry-run",
            ]
            with mock.patch.dict("os.environ", {FANOUT_DEPTH_ENV_VAR: "1"}):
                status, stdout, stderr = run_cli(argv)
        self.assertEqual(status, 1, stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["refused"])
        self.assertEqual(payload["refusal_reason"], "fanout_depth_exceeded")


def _flaky_runner(*, failures: dict[str, list[str]], write_units: set[str] | None = None):
    """A fake agent whose per-unit stdout is scripted attempt by attempt.

    `failures[unit_id]` is the tail each successive FAILED attempt reports; the
    list running out means the next attempt succeeds. Units in `write_units`
    write a real file into their worktree on every attempt, which is what makes
    the replay-safety predicate observe a side effect.
    """
    attempts: dict[str, int] = {}

    def owns(prompt: str, unit_id: str) -> bool:
        return f"agent/{unit_id} in the current worktree" in prompt

    def runner(argv, **kwargs):
        if argv[0] == "git":
            return subprocess.run(argv, **kwargs)
        prompt = " ".join(argv)
        cwd = Path(str(kwargs.get("cwd", ".")))
        for unit_id, tails in failures.items():
            if not owns(prompt, unit_id):
                continue
            index = attempts.get(unit_id, 0)
            attempts[unit_id] = index + 1
            if unit_id in (write_units or set()):
                (cwd / f"{unit_id}_partial.py").write_text("value = 1\n", encoding="utf-8")
            if index < len(tails):
                return _FakeCompleted(1, tails[index])
            return _FakeCompleted(0, "done")
        return _FakeCompleted(0, "done")

    runner.attempts = attempts
    return runner


class FanoutUnitRetryTests(unittest.TestCase):
    """The retry policy driven through the real dispatch engine.

    No sleeps: the clock and the random source are injected, so a delay is
    asserted by the value handed to the recorder rather than by waiting for it.
    """

    _ONE_UNIT = [{"unit_id": "core", "title": "Core work", "owner": "codex", "file_scope": ["src/core/"]}]

    def _setup(self, tmp: str):
        root = Path(tmp)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, self._ONE_UNIT))
        return paths, repo, sha, contract

    def _dispatch(self, paths, repo, sha, contract, runner, delays, **kwargs):
        return dispatch_fanout(
            paths,
            contract,
            goal_text=_GOAL,
            repo_root=repo,
            base_sha=sha,
            runner=runner,
            readiness=_ready,
            # Floor jitter, so the asserted delay is an exact number rather
            # than a range.
            rng=lambda: 0.0,
            sleep=delays.append,
            **kwargs,
        )

    def test_a_transient_failure_on_a_clean_worktree_is_retried_with_backoff(self) -> None:
        delays: list[float] = []
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            runner = _flaky_runner(failures={"core": ["Error: socket hang up", "http 503 service unavailable"]})
            summary = self._dispatch(paths, repo, sha, contract, runner, delays)
        entry = summary["units"][0]
        self.assertEqual(entry["status"], "completed")
        self.assertEqual(runner.attempts["core"], 3)
        self.assertEqual(entry["retry"]["attempts"], 3)
        self.assertEqual(
            [row["decision"] for row in entry["retry"]["decisions"]], ["retrying", "retrying"]
        )
        self.assertEqual(
            [row["failure_class"] for row in entry["retry"]["decisions"]],
            ["transient_transport", "transient_transport"],
        )
        # min(2 * 2^(n-1), 30) at the 75% jitter floor.
        self.assertEqual(delays, [1.5, 3.0])

    def test_a_transient_failure_with_observed_side_effects_is_surfaced_not_retried(self) -> None:
        # The predicate this whole policy exists for: the failure is retryable,
        # the budget is untouched, and the unit is still not re-run because a
        # re-dispatch would destroy the work its worktree already holds.
        delays: list[float] = []
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            runner = _flaky_runner(
                failures={"core": ["Error: socket hang up"]}, write_units={"core"}
            )
            summary = self._dispatch(paths, repo, sha, contract, runner, delays)
        entry = summary["units"][0]
        self.assertEqual(entry["status"], "failed")
        self.assertEqual(runner.attempts["core"], 1)
        self.assertEqual(delays, [])
        self.assertTrue(entry["retry_blocked_by_side_effects"])
        decision = entry["retry"]["decisions"][0]
        self.assertEqual(decision["decision"], "surfaced_for_continuation")
        self.assertTrue(decision["retryable"])
        self.assertEqual(decision["replay_verdict"], "observed_side_effects")
        # Surfaced through the path an operator already reads, not a new one.
        self.assertEqual(entry["recovery"]["outcome"], "recovery_available")
        self.assertEqual(summary["recovery_available_units"], ["core"])

    def test_a_real_test_failure_is_never_retried(self) -> None:
        delays: list[float] = []
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            runner = _flaky_runner(failures={"core": ["FAILED (failures=2, errors=0)", "done"]})
            summary = self._dispatch(paths, repo, sha, contract, runner, delays)
        entry = summary["units"][0]
        self.assertEqual(entry["status"], "failed")
        # One attempt, even though a second one would have "succeeded": a
        # terminal failure is the unit's answer, not a transport blip.
        self.assertEqual(runner.attempts["core"], 1)
        self.assertEqual(delays, [])
        self.assertEqual(entry["retry"]["final_decision"], "terminal")
        self.assertNotIn("retry_blocked_by_side_effects", entry)

    def test_retries_are_bounded_and_the_exhaustion_is_recorded(self) -> None:
        delays: list[float] = []
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            runner = _flaky_runner(failures={"core": ["socket hang up"] * 6})
            summary = self._dispatch(paths, repo, sha, contract, runner, delays, max_retries=2)
        entry = summary["units"][0]
        self.assertEqual(entry["status"], "failed")
        self.assertEqual(runner.attempts["core"], 3)
        self.assertEqual(len(delays), 2)
        self.assertEqual(entry["retry"]["final_decision"], "retries_exhausted")

    def test_a_first_try_success_carries_no_retry_record(self) -> None:
        # The negative control: the presence of the block is itself the signal,
        # so an untroubled dispatch must not grow one.
        delays: list[float] = []
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            summary = self._dispatch(paths, repo, sha, contract, _agent_runner(), delays)
        entry = summary["units"][0]
        self.assertEqual(entry["status"], "completed")
        self.assertNotIn("retry", entry)
        self.assertEqual(delays, [])

    def test_a_retry_spends_the_run_spawn_budget(self) -> None:
        # A retry is a real spawn. Left uncounted it would let one flaky unit
        # walk past the ceiling the operator set.
        delays: list[float] = []
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            runner = _flaky_runner(failures={"core": ["socket hang up"] * 4})
            summary = self._dispatch(
                paths, repo, sha, contract, runner, delays, spawn_ceiling=2, max_retries=3
            )
        self.assertEqual(runner.attempts["core"], 2)
        self.assertEqual(summary["spawn_guard"]["spawns_claimed"], 2)
        self.assertEqual(summary["units"][0]["retry"]["final_decision"], "spawn_ceiling_reached")


def _live_output_runner(snapshots_by_unit: dict[str, list[str]]):
    """Like `_agent_runner`, but opts into the mid-run stdout seam: for a
    matching unit it hands the dispatch's `on_output` hook each snapshot in
    order before returning, with the last snapshot as the final stdout —
    the same cumulative-stream shape the signal-safe runner produces."""

    spawned: list[list[str]] = []

    def runner(argv, **kwargs):
        if argv[0] == "git":
            return subprocess.run(argv, **kwargs)
        spawned.append(list(argv))
        prompt = " ".join(argv)
        on_output = kwargs.get("on_output")
        stdout = "done"
        for unit_id, snapshots in snapshots_by_unit.items():
            if unit_id in prompt and snapshots:
                for snapshot in snapshots:
                    if on_output is not None:
                        on_output(snapshot)
                stdout = snapshots[-1]
        return _FakeCompleted(0, stdout)

    runner.accepts_on_output = True
    runner.spawned = spawned
    return runner


class FanoutDispatchLiveUnitTelemetryTests(unittest.TestCase):
    """Mid-run token telemetry for Maestro-lane HUD rows: the runner hands the
    dispatch periodic stdout snapshots, the reporter parses the same
    `omh_unit_telemetry/v1` surface the terminal close uses, and the unit's
    binding journal carries `running` events whose signal holds the count —
    which is what lets the TUI row show tokens while the process still runs
    instead of only in the instant before the closed row disappears."""

    def _setup(self, tmp: str, units=None):
        root = Path(tmp)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units or _UNITS))
        return paths, repo, sha, contract

    def _codex_usage_line(self, input_tokens: int, output_tokens: int, total: int) -> str:
        return (
            json.dumps(
                {
                    "type": "token_count",
                    "total_token_usage": {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": total,
                    },
                }
            )
            + "\n"
        )

    def test_mid_run_codex_token_updates_surface_as_running_events(self) -> None:
        from omh.coding import fanout_dispatch as dispatch_module

        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            core = {entry["unit_id"]: entry for entry in contract["units"]}["core"]
            run_ref = core["run_ref"]
            first = self._codex_usage_line(900, 100, 1000)
            second = first + self._codex_usage_line(2000, 500, 2500)
            # Three snapshots: the middle repeats the first count, proving the
            # reporter writes only when the reported count actually moved.
            runner = _live_output_runner({"core": [first, first, second]})

            interval = dispatch_module.LIVE_UNIT_TELEMETRY_MIN_INTERVAL_SECONDS
            dispatch_module.LIVE_UNIT_TELEMETRY_MIN_INTERVAL_SECONDS = 0.0
            try:
                dispatch_fanout(
                    paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                    only_units=["core"], runner=runner, readiness=_ready,
                )
            finally:
                dispatch_module.LIVE_UNIT_TELEMETRY_MIN_INTERVAL_SECONDS = interval

            events = _progress_events(paths, run_ref)
            running = [event for event in events if event["event_type"] == "running_no_diff_observed"]
            self.assertEqual(
                [event["signal"]["tokens_total"] for event in running], [1000, 2500]
            )
            completed = next(event for event in events if event["event_type"] == "executor_completed")
            # The terminal close re-parses the full stdout independently of
            # every snapshot, so the closing event carries the final count.
            self.assertEqual(completed["signal"]["tokens_total"], 2500)

    def test_live_reports_throttle_to_the_minimum_parse_interval(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            core = {entry["unit_id"]: entry for entry in contract["units"]}["core"]
            run_ref = core["run_ref"]
            first = self._codex_usage_line(900, 100, 1000)
            second = first + self._codex_usage_line(2000, 500, 2500)
            # Default 10s interval, two immediate snapshots with different
            # counts: the second parse is throttled, so only one live event
            # lands and the moved count still arrives via the terminal close.
            runner = _live_output_runner({"core": [first, second]})

            dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                only_units=["core"], runner=runner, readiness=_ready,
            )

            events = _progress_events(paths, run_ref)
            running = [event for event in events if event["event_type"] == "running_no_diff_observed"]
            self.assertEqual([event["signal"]["tokens_total"] for event in running], [1000])
            completed = next(event for event in events if event["event_type"] == "executor_completed")
            self.assertEqual(completed["signal"]["tokens_total"], 2500)

    def test_plain_protocol_runner_sees_no_on_output_kwarg(self) -> None:
        """An injected runner without the capability marker keeps the plain
        protocol — the dispatch must not hand it a kwarg it never accepted."""
        seen_kwargs: list[set[str]] = []

        def runner(argv, **kwargs):
            if argv[0] == "git":
                return subprocess.run(argv, **kwargs)
            seen_kwargs.append(set(kwargs))
            return _FakeCompleted(0, "done")

        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                only_units=["core"], runner=runner, readiness=_ready,
            )
        self.assertTrue(seen_kwargs)
        for kwargs in seen_kwargs:
            self.assertNotIn("on_output", kwargs)
            self.assertNotIn("on_spawn", kwargs)

    def test_claude_result_usage_sums_input_and_output_at_close(self) -> None:
        """Claude's result object states input and output but no total; the
        close path now reports their sum (the Hermes-native input+output
        convention) instead of leaving the row's count absent forever."""

        stdout = json.dumps(
            {
                "result": "done",
                "session_id": "sess_x",
                "usage": {"input_tokens": 2, "output_tokens": 4, "cache_read_input_tokens": 100},
            }
        )

        def runner(argv, **kwargs):
            if argv[0] == "git":
                return subprocess.run(argv, **kwargs)
            return _FakeCompleted(0, stdout)

        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            docs = {entry["unit_id"]: entry for entry in contract["units"]}["docs"]
            run_ref = docs["run_ref"]
            dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                only_units=["docs"], runner=runner, readiness=_ready,
            )
            completed = next(
                event for event in _progress_events(paths, run_ref)
                if event["event_type"] == "executor_completed"
            )
            self.assertEqual(completed["signal"]["tokens_total"], 6)

    def test_reported_unit_tokens_prefers_stated_total_and_sums_reported_parts(self) -> None:
        from omh.coding.fanout_dispatch import _reported_unit_tokens

        self.assertEqual(_reported_unit_tokens({"tokens_total": 1000, "input_tokens": 1}), 1000)
        self.assertEqual(_reported_unit_tokens({"input_tokens": 2, "output_tokens": 4}), 6)
        self.assertEqual(_reported_unit_tokens({"output_tokens": 4}), 4)
        # Absent counts stay absent, and bools never read as counts.
        self.assertIsNone(_reported_unit_tokens({}))
        self.assertIsNone(_reported_unit_tokens({"tokens_total": True}))


if __name__ == "__main__":
    unittest.main()
