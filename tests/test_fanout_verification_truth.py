"""A unit's verdict says what the dispatcher observed, and a check can pass (#2460, #2461).

#2460: `fanout validate` accepted `test -f X && grep -q Y X` as a
verification command. The dispatcher runs every check with `shell=False`, so
`&&` reached `test` as a literal argument, `test` exited 2, and a unit whose
work was right landed `failed` / `verification_failed`. A contract that can
never pass must not validate.

#2461: a unit that exited 0 with a validated result and no declared check
landed `unit_state: failed`, although nothing ran and failed. It is
`unverified` now, and `omh coding run` can declare its own checks with
`--verification-command`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from _fanout_host_fence import host_cannot_fence_fanout  # noqa: E402
from _platform_support import requires_posix  # noqa: E402
from omh.cli import main as cli_main  # noqa: E402
from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_artifacts import write_fanout_contract  # noqa: E402
from omh.coding.fanout_contracts import (  # noqa: E402
    FanoutContractError,
    require_shell_free_command,
    unquoted_shell_operator,
    verification_command_argv,
)
from omh.coding.fanout_dispatch import _verification_unit_state, dispatch_fanout  # noqa: E402
from omh.coding.unit_execution_state import (  # noqa: E402
    UNIT_STATE_FAILED,
    UNIT_STATE_UNVERIFIED,
    UNIT_STATE_VERIFIED,
    UNIT_TERMINAL_STATES,
    is_terminal,
)
from omh.commands.coding import _fanout_dispatch_exit_code, _fanout_status_wait_exit_code  # noqa: E402
from omh.plugin_bundle.omh.dispatch_outcomes import (  # noqa: E402
    NEXT_RUN_RECOVERY,
    NEXT_VERIFY_RESULT,
    _next_verb,
)
from omh.system.paths import OmhPaths  # noqa: E402

_PY = shlex.quote(sys.executable)
_GOAL = "Append the B marker to NOTES.md"
# The reporter's contract, verbatim.
_REPORTED_CHECK = "test -f NOTES.md && grep -qx 'OMH green B' NOTES.md"
_PASSING = f"{_PY} -c pass"


def _units(commands: list[str] | None = None, **extra: object) -> list[dict[str, object]]:
    unit: dict[str, object] = {
        "unit_id": "green-b",
        "title": _GOAL,
        "goal": _GOAL,
        "owner": "codex",
        "file_scope": ["NOTES.md"],
    }
    if commands is not None:
        unit["verification_commands"] = commands
    unit.update(extra)
    return [unit]


def _run_cli(argv: list[str]) -> tuple[int, str]:
    import contextlib
    import io

    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        try:
            code = cli_main(argv)
        except SystemExit as exc:
            code = int(exc.code or 0)
    return int(code or 0), out.getvalue()


class ShellOperatorScanTests(unittest.TestCase):
    def test_operators_outside_quotes_are_found(self) -> None:
        for command, operator in (
            (_REPORTED_CHECK, "&&"),
            ("make test || true", "||"),
            ("pytest -q | tee log", "|"),
            ("cd pkg; pytest", ";"),
            ("server &", "&"),
            ("pytest > log", ">"),
            ("pytest 2>/dev/null", ">"),
            ("wc -l < NOTES.md", "<"),
            ("echo $(id)", "$("),
            ("echo `id`", "`"),
            ('echo "$(id)"', "$("),
        ):
            with self.subTest(command=command):
                self.assertEqual(unquoted_shell_operator(command), operator)

    def test_quoted_or_escaped_operator_text_is_an_ordinary_argument(self) -> None:
        for command in (
            "grep -E 'a|b' NOTES.md",
            'grep -E "a|b" NOTES.md',
            "grep -c '&&' NOTES.md",
            "echo '$(id)'",
            "grep a\\|b NOTES.md",
            "PYTHONPATH=tests python -m unittest test_x",
            f"{_PY} -c 'import sys; sys.exit(0)'",
            "sh -c 'test -f NOTES.md && grep -q B NOTES.md'",
        ):
            with self.subTest(command=command):
                self.assertEqual(unquoted_shell_operator(command), "")

    def test_the_refusal_names_the_operator_and_both_fixes(self) -> None:
        with self.assertRaises(FanoutContractError) as raised:
            require_shell_free_command(_REPORTED_CHECK)
        message = str(raised.exception)
        self.assertIn("'&&'", message)
        self.assertIn("without a shell", message)
        self.assertIn("declare each step as its own command", message)
        # The suggested wrapper is itself a command the freeze path accepts,
        # and it splits back to the reporter's exact line.
        wrapped = message.rsplit("explicitly: ", 1)[1]
        require_shell_free_command(wrapped)
        _env, argv = verification_command_argv(wrapped)
        self.assertEqual(argv, ["sh", "-c", _REPORTED_CHECK])

    def test_the_argv_split_itself_is_unchanged(self) -> None:
        # `handoff_contract` postconditions compile through this parser and
        # the executor runs them, so the refusal lives beside it, not in it.
        _env, argv = verification_command_argv("python -c 'print(1)' | tee log")
        self.assertEqual(argv, ["python", "-c", "print(1)", "|", "tee", "log"])


class FreezeTimeRefusalTests(unittest.TestCase):
    def test_validate_refuses_the_reported_contract(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            units = root / "units.json"
            units.write_text(json.dumps(_units([_REPORTED_CHECK])), encoding="utf-8")
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            code, stdout = _run_cli(base + ["coding", "fanout", "validate", "--units", str(units)])

        payload = json.loads(stdout)
        self.assertFalse(payload["ok"])
        self.assertNotEqual(code, 0)
        self.assertIn("unit at index 0", payload["error"])
        self.assertIn("'&&'", payload["error"])

    def test_validate_accepts_the_split_and_the_wrapped_forms(self) -> None:
        for commands in (
            ["test -f NOTES.md", "grep -qx 'OMH green B' NOTES.md"],
            [f"sh -c {shlex.quote(_REPORTED_CHECK)}"],
        ):
            with self.subTest(commands=commands), TemporaryDirectory() as tmp:
                root = Path(tmp)
                units = root / "units.json"
                units.write_text(json.dumps(_units(commands)), encoding="utf-8")
                base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

                code, stdout = _run_cli(base + ["coding", "fanout", "validate", "--units", str(units)])

                self.assertEqual(code, 0, stdout)
                self.assertTrue(json.loads(stdout)["ok"])

    def test_every_dispatcher_run_command_field_refuses_at_freeze(self) -> None:
        # Each field the dispatcher runs with `shell=False` gets the same
        # refusal, each naming the field it came from.
        for extra, field in (
            ({"verification_commands": [_REPORTED_CHECK]}, "verification command"),
            ({"verification_checks": [{"command": _REPORTED_CHECK}]}, "verification command"),
            ({"kind": "reproduction", "reproduction_command": "pytest -q | grep FAIL"}, "reproduction_command"),
            ({"task_linked_test_runner": "cd tests && python -m unittest"}, "task_linked_test_runner"),
        ):
            with self.subTest(field=field, extra=extra):
                with self.assertRaises(FanoutContractError) as raised:
                    build_fanout_contract(_GOAL, _units(**extra))
                self.assertIn(field, str(raised.exception))
                self.assertIn("unit at index 0", str(raised.exception))


def _make_repo(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "NOTES.md").write_text("notes\n", encoding="utf-8")
    subprocess.run(["git", "add", "NOTES.md"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"], cwd=repo, check=True
    )
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True)
    return repo, sha.stdout.strip()


def _ready(paths: OmhPaths, profile: str, **kwargs: object) -> dict[str, object]:
    return {"status": "ready", "profile": profile}


class _Executor:
    """A fake codex that writes the B marker, commits, and returns a valid sidecar."""

    def __init__(self, contract: dict[str, object], base: str) -> None:
        self.contract = contract
        self.base = base
        self.checks: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        if argv[0] == "git":
            return subprocess.run(argv, **kwargs)
        cwd = Path(str(kwargs.get("cwd")))
        if argv[0] == "codex":
            (cwd / "NOTES.md").write_text("notes\nOMH green B\n", encoding="utf-8")
            subprocess.run(["git", "add", "NOTES.md"], cwd=cwd, check=True)
            subprocess.run(
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "B"], cwd=cwd, check=True
            )
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, check=True, capture_output=True, text=True)
            unit = self.contract["units"][0]  # type: ignore[index]
            payload = {
                "schema_version": "fanout_unit_result/v1",
                "unit_id": unit["unit_id"],
                "run_id": unit["run_ref"],
                "fanout_id": self.contract["fanout_id"],
                "base_sha": self.base,
                "head_sha": head.stdout.strip(),
                "process_status": "process_succeeded",
                "changed_paths": ["NOTES.md"],
                "checks": [],
                "findings": [],
            }
            match = re.search(r"JSON sidecar to exactly (.+)\.", " ".join(argv))
            assert match is not None
            sidecar = Path(match[1])
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.write_text(json.dumps(payload), encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, "done", "")
        self.checks.append(list(argv))
        return subprocess.run(
            argv, cwd=kwargs.get("cwd"), env=kwargs.get("env"), text=True,
            capture_output=True, timeout=kwargs.get("timeout"),
        )


class UnitVerdictTests(unittest.TestCase):
    def _dispatch(self, commands: list[str] | None, *, run_verification: bool, frozen: list[str] | None = None):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        contract = build_fanout_contract(_GOAL, _units(commands))
        if frozen is not None:
            # A contract recorded before the freeze-time refusal existed.
            contract["units"][0]["verification_commands"] = frozen
        contract = write_fanout_contract(paths, contract)
        runner = _Executor(contract, sha)
        summary = dispatch_fanout(
            paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
            runner=runner, readiness=_ready, run_verification=run_verification,
        )
        return summary, summary["units"][0], runner

    def test_completed_work_with_no_declared_check_is_unverified_not_failed(self) -> None:
        summary, unit, _runner = self._dispatch(None, run_verification=False)

        self.assertEqual(unit["status"], "completed")
        self.assertTrue(unit["process_succeeded"])
        self.assertTrue(unit["result_schema_valid"])
        self.assertEqual(unit["unit_state"], UNIT_STATE_UNVERIFIED)
        self.assertEqual(unit["unit_state_reason"], "verification_not_observed")
        self.assertFalse(unit["unit_verification_observed"])
        self.assertFalse(unit["integration_ready"])
        self.assertEqual(_fanout_dispatch_exit_code(summary), 0)

    def test_a_declared_check_that_was_not_asked_to_run_is_unverified_too(self) -> None:
        _summary, unit, runner = self._dispatch([_PASSING], run_verification=False)

        self.assertEqual(runner.checks, [])
        self.assertEqual(unit["unit_state"], UNIT_STATE_UNVERIFIED)

    def test_a_passing_check_still_verifies(self) -> None:
        summary, unit, runner = self._dispatch(
            ["test -f NOTES.md", "grep -qx 'OMH green B' NOTES.md"], run_verification=True
        )

        self.assertEqual(len(runner.checks), 2)
        self.assertEqual(unit["unit_state"], UNIT_STATE_VERIFIED)
        self.assertTrue(unit["integration_ready"])
        self.assertEqual(_fanout_dispatch_exit_code(summary), 0)

    def test_the_wrapped_form_of_the_reported_check_passes_on_the_same_work(self) -> None:
        _summary, unit, runner = self._dispatch([f"sh -c {shlex.quote(_REPORTED_CHECK)}"], run_verification=True)

        self.assertEqual(runner.checks, [["sh", "-c", _REPORTED_CHECK]])
        self.assertEqual(unit["unit_state"], UNIT_STATE_VERIFIED)

    def test_a_check_that_ran_and_failed_is_still_failed(self) -> None:
        summary, unit, _runner = self._dispatch(["grep -qx 'OMH green A' NOTES.md"], run_verification=True)

        self.assertEqual(unit["unit_state"], UNIT_STATE_FAILED)
        self.assertEqual(unit["unit_state_reason"], "verification_failed")
        self.assertEqual(_fanout_dispatch_exit_code(summary), 1)

    def test_a_previously_frozen_shell_check_is_refused_unrun_not_misreported(self) -> None:
        # An old contract still carries the reporter's line. Running it would
        # only report `test`'s own usage error as the work failing.
        _summary, unit, runner = self._dispatch(None, run_verification=True, frozen=[_REPORTED_CHECK])

        self.assertEqual(runner.checks, [])
        self.assertEqual(unit["unit_state"], UNIT_STATE_FAILED)
        failure = unit["verification_failures"][0]
        self.assertIn("invalid verification command", failure)
        self.assertIn("'&&'", failure)
        self.assertNotIn("exit 2", failure)


class UnverifiedStateVocabularyTests(unittest.TestCase):
    def test_unverified_is_terminal_and_is_neither_success_nor_failure(self) -> None:
        self.assertIn(UNIT_STATE_UNVERIFIED, UNIT_TERMINAL_STATES)
        self.assertTrue(is_terminal(UNIT_STATE_UNVERIFIED))
        self.assertNotIn(UNIT_STATE_UNVERIFIED, (UNIT_STATE_FAILED, UNIT_STATE_VERIFIED))

    def test_the_verdict_has_three_answers(self) -> None:
        self.assertEqual(_verification_unit_state("passed", True), (UNIT_STATE_VERIFIED, ""))
        self.assertEqual(_verification_unit_state("failed", False), (UNIT_STATE_FAILED, "verification_failed"))
        for status in (None, "held", ""):
            with self.subTest(status=status):
                self.assertEqual(
                    _verification_unit_state(status, False), (UNIT_STATE_UNVERIFIED, "verification_not_observed")
                )

    def test_a_supervisor_reads_the_result_rather_than_retrying(self) -> None:
        entry = {"unit_state": UNIT_STATE_UNVERIFIED, "process_succeeded": True}
        self.assertEqual(_next_verb(entry), NEXT_VERIFY_RESULT)
        self.assertEqual(_next_verb({"unit_state": UNIT_STATE_FAILED, "process_succeeded": True}), NEXT_RUN_RECOVERY)

    def test_the_status_watcher_still_does_not_call_unverified_success(self) -> None:
        roster = {"units": [{"unit_id": "a", "unit_state": UNIT_STATE_UNVERIFIED}], "wait": {"outcome": "all_units_terminal"}}
        self.assertEqual(_fanout_status_wait_exit_code(roster), 1)


@requires_posix
class CodingRunVerificationCommandTests(unittest.TestCase):
    """The reporter's shorthand path, through the real CLI and a fake codex binary."""

    def _run(self, *extra: str) -> tuple[int, dict[str, object], str]:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        bin_dir = root / "bin"
        bin_dir.mkdir()
        codex = bin_dir / "codex"
        codex.write_text(_FAKE_CODEX.replace("__PYTHON__", shlex.quote(sys.executable)), encoding="utf-8")
        codex.chmod(0o755)
        home = root / "home"
        (home / ".codex").mkdir(parents=True)
        repo, _sha = _make_repo(root)
        env = {
            **os.environ,
            "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
            "HOME": str(home),
            "OMH_HOME": str(root / "omh"),
            "HERMES_HOME": str(root / "hermes"),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        }
        env.pop("CODEX_HOME", None)
        argv = [
            sys.executable, "-m", "omh.cli", "--omh-home", str(root / "omh"), "--hermes-home", str(root / "hermes"),
            "coding", "run", "--owner", "codex", "--goal", "write one line to NOTES.md",
            "--unit-id", "live-check", "--repo-root", str(repo), "--file-scope", "NOTES.md", "--timeout", "60",
            *extra,
        ]
        if host_cannot_fence_fanout():
            argv.append("--allow-unconfined")
        completed = subprocess.run(
            argv, env=env, cwd=str(root), capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL,
        )
        self.assertTrue(completed.stdout.strip(), completed.stderr[-2000:])
        return completed.returncode, json.loads(completed.stdout)["dispatch"]["units"][0], completed.stderr

    def test_the_reported_shorthand_run_is_unverified_not_failed(self) -> None:
        code, unit, stderr = self._run()

        observed = {key: unit.get(key) for key in ("status", "exit_code", "result_schema_valid", "unit_state")}
        self.assertEqual(
            observed,
            {"status": "completed", "exit_code": 0, "result_schema_valid": True, "unit_state": "unverified"},
            stderr[-2000:],
        )
        self.assertEqual(code, 0)

    def test_a_declared_verification_command_runs_and_verifies(self) -> None:
        code, unit, stderr = self._run(
            "--verification-command", "test -f NOTES.md",
            "--verification-command", "grep -qx 'OMH green B' NOTES.md",
        )

        self.assertEqual(unit.get("unit_state"), "verified", stderr[-2000:])
        self.assertEqual(
            [row["command"] for row in unit["verification_checks"]],
            ["test -f NOTES.md", "grep -qx 'OMH green B' NOTES.md"],
        )
        self.assertEqual(code, 0)

    def test_a_declared_check_with_a_shell_operator_is_refused_before_any_spawn(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        code, stdout = _run_cli([
            "--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes"),
            "coding", "run", "--owner", "codex", "--goal", "g", "--repo-root", str(root),
            "--verification-command", _REPORTED_CHECK,
        ])

        self.assertNotEqual(code, 0)
        self.assertFalse((root / ".omh" / "coding" / "fanout").exists() and any((root / ".omh" / "coding" / "fanout").iterdir()))


# Answers the readiness probe, then does the unit's work and writes the result
# sidecar the prompt names, the way a real codex unit is told to. The prompt is
# multi-line, so the dispatch-bound values are read with Python, not sed.
_FAKE_CODEX = """#!/bin/sh
case "$1" in
  --version) echo "codex-cli 0.165.0"; exit 0 ;;
esac
if [ "$1" = "exec" ] && [ "$2" = "--help" ]; then
  echo "Usage: codex exec [OPTIONS] [PROMPT]"
  exit 0
fi
for last; do :; done
printf 'notes\\nOMH green B\\n' > NOTES.md
git add NOTES.md
git -c user.name=t -c user.email=t@t commit -q -m B
OMH_FAKE_HEAD=$(git rev-parse HEAD) OMH_FAKE_PROMPT="$last" __PYTHON__ -c '
import json, os, pathlib, re
prompt = os.environ["OMH_FAKE_PROMPT"]
sidecar = pathlib.Path(re.search(r"JSON sidecar to exactly (.+?)[.]\\s", prompt)[1])
value = lambda key: re.search(key + r"=([^ ,;]+)", prompt)[1]
sidecar.parent.mkdir(parents=True, exist_ok=True)
sidecar.write_text(json.dumps({
    "schema_version": "fanout_unit_result/v1", "unit_id": value("unit_id"), "run_id": value("run_id"),
    "fanout_id": value("fanout_id"), "base_sha": value("base_sha"), "head_sha": os.environ["OMH_FAKE_HEAD"],
    "process_status": "process_succeeded", "changed_paths": ["NOTES.md"], "checks": [], "findings": [],
}))
'
"""


if __name__ == "__main__":
    unittest.main()
