"""Dispatch, readiness and owner admission for user-declared executors.

A person declares a headless coding CLI in `<omh_home>/routing/executors.toml`
and names its id as a fanout owner. These tests hold the dispatcher to the
same lane guarantees the built-ins get:

* spawn argv comes from the declaration, with `{prompt}` as ONE element and
  no shell anywhere in the launch;
* readiness runs the declared version argv, and a program that is not on PATH
  is not ready;
* completion is judged from git -- a real descendant commit -- never from what
  the CLI printed, and a nonzero exit stays failed;
* the built-in codex / claude-code / pi-family argv is byte-identical to the
  shipped templates, and their launch keeps the `exec -a` shim;
* an owner id is admitted only when the registry this invocation loaded
  contains it.

No vendor CLI is installed: every executor here is a small script on a
temporary PATH.
"""

from __future__ import annotations

import os
import json
from contextlib import chdir
from pathlib import Path

import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

from omh.coding.executor_readiness import probe_executor_readiness  # noqa: E402
from omh.coding.fanout import (  # noqa: E402
    FanoutContractError,
    build_fanout_contract,
    validate_fanout_units,
)
from omh.coding.fanout_artifacts import write_fanout_contract  # noqa: E402
from omh.coding.fanout_confinement import (  # noqa: E402
    external_launch_argv,
    named_launch_argv,
    observe_named_launch,
)
from omh.coding.fanout_dispatch import (  # noqa: E402
    build_dispatch_argv,
    build_user_executor_argv,
    dispatch_fanout,
)
from omh.coding.user_executors import (  # noqa: E402
    load_user_executors,
    render_user_argv,
)
from omh.system.paths import OmhPaths  # noqa: E402

_GOAL = "hand one bounded unit to a user-declared executor"

# A fake harness CLI: `--version` answers, `run -- <prompt>` does exactly one
# of the three things the dispatcher must tell apart.
_FAKE_CLI = '''#!{python}
import pathlib
import subprocess
import sys

MODE = {mode!r}
args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("fake-agent 2.3.4")
    raise SystemExit(0)
prompt = args[-1]
if MODE == "fail":
    print("everything passed and the work is complete")
    raise SystemExit(1)
if MODE == "prose":
    print("Committed the change. All checks pass.")
    raise SystemExit(0)
pathlib.Path("agent_output.txt").write_text("worked: " + prompt.splitlines()[0] + "\\n", encoding="utf-8")
subprocess.run(["git", "add", "agent_output.txt"], check=True)
subprocess.run(
    ["git", "-c", "user.name=fake-agent", "-c", "user.email=fake@example.test",
     "commit", "-q", "-m", "agent: unit work"],
    check=True,
)
print("done")
'''


_FAKE_PROMPT_FILE_CLI = '''#!{python}
import pathlib
import subprocess
import sys

args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("fake-agent 2.3.4")
    raise SystemExit(0)
text = pathlib.Path(args[1]).read_text(encoding="utf-8")
pathlib.Path("prompt_copy.txt").write_text(text, encoding="utf-8")
subprocess.run(["git", "add", "prompt_copy.txt"], check=True)
subprocess.run(
    ["git", "-c", "user.name=fake-agent", "-c", "user.email=fake@example.test",
     "commit", "-q", "-m", "agent: file transport"],
    check=True,
)
print("done")
'''


def _git(repo: Path, *argv: str) -> str:
    completed = subprocess.run(
        ["git", *argv], cwd=str(repo), check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _make_repo(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "seed.txt")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    return repo, _git(repo, "rev-parse", "HEAD")


def _bin_dir(root: Path, name: str, mode: str, template: str = _FAKE_CLI) -> Path:
    """One executable fake CLI named `name` on its own temp PATH entry."""
    directory = root / f"bin-{name}"
    directory.mkdir()
    script = directory / name
    script.write_text(
        template.format(python=sys.executable, mode=mode), encoding="utf-8"
    )
    script.chmod(0o755)
    return directory


def _home_with_argv(root: Path, executor_id: str, argv_line: str) -> OmhPaths:
    """A home whose one executor declares `argv_line` verbatim."""
    home = root / ".omh"
    routing = home / "routing"
    routing.mkdir(parents=True)
    (routing / "executors.toml").write_text(
        "schema_version = 1\n\n"
        f"[executors.{executor_id}]\n"
        f"argv = {argv_line}\n"
        f'version = ["{executor_id}", "--version"]\n',
        encoding="utf-8",
    )
    return OmhPaths(omh_home=home, hermes_home=root / ".hermes")


def _home(root: Path, entries: dict[str, tuple[str, str]]) -> OmhPaths:
    """A disposable OMH home with one `routing/executors.toml`."""
    home = root / ".omh"
    routing = home / "routing"
    routing.mkdir(parents=True)
    lines = ["schema_version = 1", ""]
    for executor_id, (program, extra) in entries.items():
        lines.extend([
            f"[executors.{executor_id}]",
            f'label = "{executor_id} fake"',
            f'argv = ["{program}", "run", "--", "{{prompt}}"]',
            f'version = ["{program}", "--version"]',
        ])
        if extra:
            lines.append(extra)
        lines.append("")
    (routing / "executors.toml").write_text("\n".join(lines), encoding="utf-8")
    return OmhPaths(omh_home=home, hermes_home=root / ".hermes")


def _unit(owner: str) -> dict[str, object]:
    return {
        "unit_id": "core",
        "title": "Core work",
        "owner": owner,
        "file_scope": ["src/"],
    }


class BuiltinArgvPinsTests(unittest.TestCase):
    """The shipped templates stay byte-identical: fixed prompt, model, effort."""

    PROMPT = "-fix the bug\nwith two lines"

    def test_codex_argv_is_pinned(self) -> None:
        argv = build_dispatch_argv(
            "codex", self.PROMPT,
            {"selected_model": "gpt-5.1-codex", "selected_reasoning_effort": "high"},
        )
        self.assertEqual(argv, [
            "codex", "exec",
            "--model", "gpt-5.1-codex",
            "--config", "model_reasoning_effort=high",
            self.PROMPT,
        ])
        self.assertEqual([part.encode("utf-8") for part in argv], [
            b"codex", b"exec",
            b"--model", b"gpt-5.1-codex",
            b"--config", b"model_reasoning_effort=high",
            self.PROMPT.encode("utf-8"),
        ])

    def test_claude_code_argv_is_pinned(self) -> None:
        argv = build_dispatch_argv(
            "claude-code", self.PROMPT,
            {"selected_model": "opus", "selected_reasoning_effort": "high"},
        )
        self.assertEqual(argv, [
            "claude", "-p", self.PROMPT,
            "--permission-mode", "acceptEdits",
            "--allowedTools", "Bash(git add:*),Bash(git commit:*)",
            "--model", "opus", "--effort", "high",
        ])

    def test_claude_code_no_route_argv_is_pinned(self) -> None:
        self.assertEqual(build_dispatch_argv("claude-code", self.PROMPT), [
            "claude", "-p", self.PROMPT,
            "--permission-mode", "acceptEdits",
            "--allowedTools", "Bash(git add:*),Bash(git commit:*)",
        ])

    def test_pi_family_host_argv_is_pinned(self) -> None:
        with mock.patch("omh.coding.fanout_dispatch.pi_family_host", return_value="pi"):
            argv = build_dispatch_argv(
                "pi-family-runtime", self.PROMPT,
                {"selected_model": "anthropic/claude", "selected_reasoning_effort": "high"},
            )
        self.assertEqual(argv, [
            "pi", "--print", "--no-session", "--permission-preset", "workspace",
            "--model", "anthropic/claude", "--thinking", "high",
            self.PROMPT,
        ])

    def test_no_host_means_no_argv(self) -> None:
        with mock.patch("omh.coding.fanout_dispatch.pi_family_host", return_value=None):
            self.assertIsNone(build_dispatch_argv("pi-family-runtime", "P"))

    def test_a_spec_never_overrides_a_builtin_template(self) -> None:
        registry = None
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), {"my-agent": ("my-agent", "")})
            registry = load_user_executors(paths.omh_home)
        with mock.patch("omh.coding.fanout_dispatch.pi_family_host", return_value="pi"):
            argv = build_dispatch_argv("codex", "P")
            foreign = build_user_executor_argv("codex", "P", spec=next(iter(registry.entries.values())))
        # The built-in template is the only authority; a spec never renders codex.
        self.assertEqual(argv, ["codex", "exec", "P"])
        self.assertIsNone(foreign)


class UserExecutorArgvTests(unittest.TestCase):
    def test_prompt_is_one_argv_element_whatever_it_contains(self) -> None:
        prompt = "line one\nline two $(rm -rf /) `id` 'quote' {brace} --flag"
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), {"my-agent": ("my-agent", "")})
            spec = load_user_executors(paths.omh_home).entries["my-agent"]
        argv = build_user_executor_argv("my-agent", prompt, spec=spec)
        self.assertEqual(argv, ["my-agent", "run", "--", prompt])
        self.assertEqual(argv.count(prompt), 1)

    def test_no_template_and_no_spec_is_still_unspawnable(self) -> None:
        self.assertIsNone(build_dispatch_argv("generic", "P"))
        self.assertIsNone(build_dispatch_argv("my-agent", "P"))

    def test_an_unsupported_selected_model_refuses_instead_of_dropping_it(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), {"my-agent": ("my-agent", "")})
            spec = load_user_executors(paths.omh_home).entries["my-agent"]
        with self.assertRaises(Exception) as caught:
            build_user_executor_argv(
                "my-agent", "P", {"selected_model": "m"}, spec=spec
            )
        self.assertEqual(str(caught.exception), "model_unsupported")

    def test_model_and_effort_fragments_splice_at_the_declared_index(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), {
                "my-agent": (
                    "my-agent",
                    'model = ["-m", "{model}"]\neffort = ["--effort", "{effort}"]\ninsert = 1',
                ),
            })
            spec = load_user_executors(paths.omh_home).entries["my-agent"]
            argv = render_user_argv(
                spec, prompt="P", model="m-1", effort="high"
            )
        self.assertEqual(argv, ["my-agent", "-m", "m-1", "--effort", "high", "run", "--", "P"])


class OwnerAdmissionTests(unittest.TestCase):
    def test_a_loaded_id_is_admitted_and_an_unknown_one_is_not(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), {"my-agent": ("my-agent", "")})
            registry = load_user_executors(paths.omh_home)
            validate_fanout_units([_unit("my-agent")], registry=registry)
            with self.assertRaises(FanoutContractError) as caught:
                validate_fanout_units([_unit("not-configured")], registry=registry)
            self.assertIn("not-configured", str(caught.exception))
            # No registry means built-ins only: never "guess the home".
            with self.assertRaises(FanoutContractError):
                validate_fanout_units([_unit("my-agent")])
            # Built-in ids are unchanged.
            validate_fanout_units([_unit("codex")])

    def test_a_non_string_owner_is_refused_rather_than_stringified(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), {"my-agent": ("my-agent", "")})
            registry = load_user_executors(paths.omh_home)
        with self.assertRaises(FanoutContractError):
            validate_fanout_units([_unit({"id": "my-agent"})], registry=registry)  # type: ignore[arg-type]

    def test_freeze_records_the_definition_digest_for_a_user_owner_only(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), {"my-agent": ("my-agent", "")})
            registry = load_user_executors(paths.omh_home)
            contract = build_fanout_contract(_GOAL, [_unit("my-agent")], registry=registry)
            builtin = build_fanout_contract(_GOAL, [_unit("codex")])
        handoff = contract["units"][0]["handoff"]
        self.assertEqual(handoff["user_executor"], {
            "id": "my-agent",
            "definition_sha256": registry.entries["my-agent"].definition_sha256,
        })
        self.assertNotIn("user_executor", builtin["units"][0]["handoff"])

    def test_two_homes_in_one_interpreter_do_not_share_entries(self) -> None:
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            first_paths = _home(Path(first), {"my-agent": ("my-agent", "")})
            second_paths = _home(Path(second), {"other-agent": ("other-agent", "")})
            first_registry = load_user_executors(first_paths.omh_home)
            second_registry = load_user_executors(second_paths.omh_home)
        self.assertIn("my-agent", first_registry.entries)
        self.assertNotIn("my-agent", second_registry.entries)
        self.assertIn("other-agent", second_registry.entries)
        self.assertNotIn("other-agent", first_registry.entries)


class ProgressRecordTests(unittest.TestCase):
    """`external.<id>` is a tagged dialect; stored built-in records stay valid."""

    def test_normalization_is_exact_for_a_tagged_id(self) -> None:
        from omh.coding.executor_progress import (
            ExecutorProgressError,
            normalize_executor_profile,
        )

        self.assertEqual(normalize_executor_profile("external.my-agent"), "external.my-agent")
        for bad in ("external.My-Agent", "external.", "external.my_agent", "my-agent"):
            with self.assertRaises(ExecutorProgressError):
                normalize_executor_profile(bad)

    def test_a_tagged_binding_and_event_round_trip(self) -> None:
        from omh.coding.executor_progress import (
            build_progress_binding,
            validate_progress_binding,
        )

        binding = build_progress_binding(
            target_type="run", target_id="run-1", executor_profile="external.my-agent"
        )
        self.assertEqual(validate_progress_binding(binding), [])
        self.assertEqual(binding["executor_profile"], "external.my-agent")


class ReadinessTests(unittest.TestCase):
    def test_a_stored_builtin_binding_stays_valid(self) -> None:
        from omh.coding.executor_progress import (
            build_progress_binding,
            validate_progress_binding,
        )

        binding = build_progress_binding(
            target_type="run", target_id="run-1", executor_profile="claude_code"
        )
        self.assertEqual(validate_progress_binding(binding), [])

    @mock.patch("omh.coding.user_executors.USER_EXECUTOR_LAUNCH_SUPPORTED", True)
    def test_a_program_that_is_not_on_path_is_not_ready(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), {"my-agent": ("my-agent", "")})
            empty = Path(tmp) / "empty-bin"
            empty.mkdir()
            with mock.patch.dict(os.environ, {"PATH": str(empty)}):
                result = probe_executor_readiness(paths, "my-agent")
        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["reason"], "not_installed")
        self.assertFalse(result["available"])

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_the_declared_version_argv_is_probed_through_the_shim_path(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _home(root, {"my-agent": ("my-agent", "")})
            binaries = _bin_dir(root, "my-agent", "commit")
            with mock.patch.dict(os.environ, {"PATH": f"{binaries}{os.pathsep}{os.environ.get('PATH', '')}"}):
                result = probe_executor_readiness(paths, "my-agent")
                identity = observe_named_launch("my-agent", {"PATH": os.environ["PATH"]})
        self.assertEqual(result["status"], "ready", result)
        self.assertTrue(result["available"])
        self.assertEqual(result["version"], "2.3.4")
        # The link name is what runs; the resolved file is the identity.
        self.assertEqual(result["command_path"], str(binaries / "my-agent"))
        self.assertIsNotNone(identity)
        self.assertEqual(identity.link_path, str(binaries / "my-agent"))

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_a_failing_version_probe_is_blocked(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _home(root, {"my-agent": ("my-agent", "")})
            binaries = root / "bin-broken"
            binaries.mkdir()
            broken = binaries / "my-agent"
            broken.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
            broken.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": f"{binaries}{os.pathsep}{os.environ.get('PATH', '')}"}):
                result = probe_executor_readiness(paths, "my-agent")
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["available"])

    def test_a_builtin_profile_is_unchanged(self) -> None:
        # No registry entry for codex: the built-in table answers, unchanged.
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), {"my-agent": ("my-agent", "")})
            contract = probe_executor_readiness(paths, "codex", dry_run=True)
        self.assertEqual(contract["profile"], "codex")
        self.assertEqual(contract["probe"]["command"], "codex")


class LaunchPathTests(unittest.TestCase):
    """External workers launch by a named path with no shell; built-ins do not change."""

    def test_builtin_shim_launch_keeps_its_bytes(self) -> None:
        # Pinned: a basename-changing built-in still goes through the `exec -a`
        # shim, exactly as #3014 shipped it.
        if not os.path.isfile("/bin/bash"):
            self.skipTest("needs /bin/bash")
        argv = named_launch_argv("codex", "/opt/mise/bin/mise", ("exec", "go"))
        self.assertEqual(argv[:6], (
            "/bin/bash", "--noprofile", "--norc", "--posix", "-c",
            'exec -a "$0" "$1" "${@:2}"',
        ))
        self.assertEqual(argv[6:], ("codex", "/opt/mise/bin/mise", "exec", "go"))

    def test_external_launch_is_direct_and_shell_free(self) -> None:
        argv = external_launch_argv("/opt/tools/bin/my-agent", ("run", "--", "a b"))
        self.assertEqual(argv, ("/opt/tools/bin/my-agent", "run", "--", "a b"))
        self.assertNotIn("/bin/bash", argv)

    def test_a_relative_path_entry_is_not_a_trusted_launch(self) -> None:
        with TemporaryDirectory() as tmp:
            _bin_dir(Path(tmp), "my-agent", "commit")
            self.assertIsNone(observe_named_launch("my-agent", {"PATH": "."}))
            self.assertIsNone(observe_named_launch("my-agent", {"PATH": os.pathsep}))


class PlatformGateTests(unittest.TestCase):
    def test_external_dispatch_readiness_and_check_refuse_without_a_process(self):
        from _cli_harness import run_cli
        from test_fanout_remote_pr import _no_process
        from omh.coding import user_executors
        from omh.coding.fanout_dispatch import fanout_dispatch_preflight

        reason = "user_executor_platform_unsupported"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _home(root, {"my-agent": ("my-agent", "")})
            user_executors.add_executor_preset(paths.omh_home, "devin")
            registry = load_user_executors(paths.omh_home)
            prefix = ["--omh-home", str(paths.omh_home), "coding"]
            with mock.patch.object(user_executors, "USER_EXECUTOR_LAUNCH_SUPPORTED", False), _no_process():
                for owner in ("my-agent", "devin"):
                    with self.subTest(owner=owner):
                        contract = build_fanout_contract(_GOAL, [_unit(owner)], registry=registry)
                        dispatch = dispatch_fanout(paths, contract, goal_text=_GOAL, repo_root=root, base_sha="")
                        self.assertTrue(dispatch["refused"])
                        self.assertEqual(dispatch["refusal_reason"], reason)
                        self.assertFalse((root.parent / f"{root.name}-fanout-core").exists())
                        write_fanout_contract(paths, contract)
                        code, out, err = run_cli(prefix + ["fanout", "dispatch", contract["fanout_id"],
                                                           "--goal-file", "-"], stdin_text=_GOAL)
                        self.assertNotEqual(code, 0, err)
                        self.assertEqual(json.loads(out)["refusal_reason"], reason)
                        readiness = probe_executor_readiness(paths, owner, force=True)
                        self.assertEqual((readiness["status"], readiness["reason"]), ("blocked", reason))
                        self.assertFalse(readiness["observed_once"])
                        code, out, _ = run_cli(prefix + ["executors", "check", owner])
                        self.assertNotEqual(code, 0)
                        self.assertEqual(json.loads(out)["checked"][0]["reason"], reason)
                        code, _, err = run_cli(prefix + ["run", "--owner", owner, "--goal", _GOAL])
                        self.assertNotEqual(code, 0)
                        self.assertIn(reason, err)
                # Built-in owners still get their normal plan, not the external-lane refusal.
                for owner in ("codex", "claude-code", "pi-family-runtime"):
                    with self.subTest(owner=owner):
                        contract = build_fanout_contract(_GOAL, [_unit(owner)])
                        plan = fanout_dispatch_preflight(paths, contract)
                        self.assertEqual(plan["invalid_selected"], [])
                        self.assertEqual(plan["capability_prechecks"]["core"][0], owner)


class DispatchGuardTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.paths = _home(self.root, {"my-agent": ("my-agent", "")})
        self.repo, self.base = _make_repo(self.root)
        self.bin = _bin_dir(self.root, "my-agent", "prose")
        self.env = {**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"}
        self.config = self.paths.omh_home / "routing" / "executors.toml"
        self.freeze()

    def freeze(self):
        registry = load_user_executors(self.paths.omh_home)
        self.contract = build_fanout_contract(_GOAL, [_unit("my-agent")], registry=registry)

    def dispatch(self, **kwargs):
        with mock.patch.dict(os.environ, self.env):
            return dispatch_fanout(self.paths, self.contract, goal_text=_GOAL,
                                   repo_root=self.repo, base_sha=self.base,
                                   env=self.env, **kwargs)["units"][0]

    def test_project_scope_checkout_registry_cannot_admit_dispatch_or_readiness(self):
        from _cli_harness import run_cli
        from omh.system.paths import resolve_paths

        # One repo-owned definition and a matching historical contract. The
        # operator has no entry, so the matching digest grants no authority.
        routing = self.repo / ".omh" / "routing"
        routing.mkdir(parents=True)
        (routing / "executors.toml").write_bytes(self.config.read_bytes())
        operator = self.root / "empty-operator-home"
        prefix = ["--scope", "project", "coding"]
        with chdir(self.repo), mock.patch.dict(os.environ, {**self.env, "OMH_HOME": str(operator)}):
            paths = resolve_paths(scope="project")
            self.assertEqual(paths.omh_home.resolve(), routing.parent.resolve())
            write_fanout_contract(paths, self.contract)
            with self.subTest(surface="readiness"):
                code, _, err = run_cli(prefix + ["executor-readiness", "--executor", "my-agent", "--dry-run"])
                self.assertNotEqual(code, 0)
                self.assertIn("unsupported executor readiness profile", err)
            with self.subTest(surface="dispatch"), mock.patch(
                    "omh.coding.executor_readiness.bounded_session_probe", return_value=(b"2.3.4", "observed")) as probe:
                _, stdout, _ = run_cli(prefix + ["fanout", "dispatch", self.contract["fanout_id"],
                                                  "--goal-file", "-", "--dry-run"], stdin_text=_GOAL)
                unit = json.loads(stdout)["units"][0]
                self.assertEqual(unit["status"], "user_executor_binding_refused")
                probe.assert_not_called()

    def test_version_cloud_subcommand_is_never_probed(self):
        from _cli_harness import run_cli

        self.config.write_text(self.config.read_text().replace('["my-agent", "--version"]',
                                                               '["my-agent", "cloud", "--version"]'))
        with mock.patch.dict(os.environ, self.env), mock.patch(
                "omh.coding.executor_readiness.bounded_session_probe", return_value=(b"2.3.4", "observed")) as probe:
            code, _, err = run_cli(["--omh-home", str(self.paths.omh_home), "coding", "executor-readiness",
                                    "--executor", "my-agent"])
        self.assertEqual(probe.call_count, 0)
        self.assertNotEqual(code, 0)
        self.assertIn("unsupported executor readiness profile", err)

    @mock.patch("omh.coding.user_executors.USER_EXECUTOR_LAUNCH_SUPPORTED", True)
    def test_dry_run_never_probes(self):
        with mock.patch("omh.coding.executor_readiness.bounded_session_probe",
                        return_value=(b"2.3.4", "observed")) as probe:
            result = self.dispatch(dry_run=True)
        self.assertEqual(probe.call_count, 0)
        self.assertEqual(result["status"], "dry_run_planned")

    def test_clean_merge_from_before_the_frozen_base_is_accepted(self):
        from omh.coding.fanout_dispatch import _external_history_refusal

        def git(*args):
            return _git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t", *args)

        git("branch", "topic")
        git("commit", "--allow-empty", "-qm", "frozen base")
        base = git("rev-parse", "HEAD")
        branch = git("branch", "--show-current")
        git("checkout", "-q", "topic")
        (self.repo / "ordinary.txt").write_text("ordinary change\n")
        git("add", "ordinary.txt")
        git("commit", "-qm", "ordinary change")
        self.assertEqual(_external_history_refusal(subprocess.run, self.repo, base), "executor_history_unverified")
        git("checkout", "-q", branch)
        git("merge", "--no-ff", "-qm", "merge old topic", "topic")
        self.assertEqual(git("status", "--porcelain"), "")
        self.assertEqual(git("diff", "--name-only", base, "HEAD"), "ordinary.txt")
        self.assertEqual(_external_history_refusal(subprocess.run, self.repo, base), "")

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_version_probe_excludes_checkout_and_sibling_lane(self):
        lane = self.repo.parent / "repo-fanout-other"
        lane.mkdir()
        for untrusted in (self.repo, lane):
            # Inert files; the mock intercepts every attempted probe on old code.
            decoy = untrusted / "my-agent"
            decoy.touch(mode=0o700)
        self.env["PATH"] = os.pathsep.join(map(str, (self.repo, lane, self.bin)))
        self.env["UNRELATED_SECRET"] = "not for a version query"
        with mock.patch("omh.coding.executor_readiness.bounded_session_probe",
                        return_value=(None, "probe_failed")) as probe:
            self.dispatch()
        args, kwargs = probe.call_args
        self.assertEqual(args[0][0], str(self.bin / "my-agent"))
        self.assertIsNotNone(kwargs.get("cwd"))
        self.assertFalse(Path(kwargs["cwd"]).is_relative_to(self.repo))
        self.assertNotIn("UNRELATED_SECRET", kwargs["env"])
        self.assertEqual(kwargs["env"]["PATH"], str(self.bin))

    def _assert_path_alias_excluded(self, alias):
        from omh.coding.fanout_confinement import external_search_path

        (self.repo / "tools").mkdir()
        entries = (alias, alias / "tools", self.bin)
        trusted = external_search_path({"PATH": os.pathsep.join(map(str, entries))},
                                       binary="my-agent", repositories=(self.repo,), write_roots=())
        self.assertEqual(trusted.split(os.pathsep), [str(self.bin)])

    def test_checkout_case_alias_excluded_by_identity(self):
        alias = self.repo.with_name(self.repo.name.upper())
        if not alias.exists() or not alias.samefile(self.repo):
            self.skipTest("case-sensitive temp filesystem")
        self._assert_path_alias_excluded(alias)

    def test_checkout_symlink_alias_excluded_by_identity(self):
        alias = self.root / "alias"
        alias.symlink_to(self.repo, target_is_directory=True)
        self._assert_path_alias_excluded(alias)

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_probe_ignores_a_link_routed_through_a_checkout(self):
        aliases = self.root / "aliases"
        aliases.mkdir()
        (self.repo / "alias").symlink_to(self.bin / "my-agent")
        (aliases / "my-agent").symlink_to(self.repo / "alias")
        self.env["PATH"] = os.pathsep.join(map(str, (aliases, self.bin)))
        with mock.patch("omh.coding.executor_readiness.bounded_session_probe",
                        return_value=(None, "probe_failed")) as probe:
            self.dispatch()
        self.assertEqual(probe.call_args.args[0][0], str(self.bin / "my-agent"))

    @mock.patch("omh.coding.user_executors.USER_EXECUTOR_LAUNCH_SUPPORTED", True)
    def test_file_prompt_dry_run_plans_path_without_allocation(self):
        self.config.write_text(self.config.read_text().replace("{prompt}", "{prompt_file}"))
        self.freeze()
        result = self.dispatch(dry_run=True)
        self.assertEqual(result["planned_argv"][-1], "<prompt file>")
        self.assertFalse(Path(result["worktree_path"]).exists())

    def _check_lost_fence(self, lose_after, *, retry=False):
        # The worker is a recording stub: no unconfined command is ever run,
        # including when exercising old code. Git runs only in the fixture.
        from omh.coding.fanout_dispatch import signal_safe_unit_runner as real_runner

        calls = []
        def runner(command, **kwargs):
            if Path(command[0]).name == "my-agent":
                calls.append(kwargs.get("confinement_command"))
                return subprocess.CompletedProcess(command, 1, "", "")
            return real_runner(command, **kwargs)

        fence = mock.Mock(unconfined_allowed=False, receipt={"enforced": True})
        validations = []
        def checked(command):
            validations.append(True)
            return ("fixture-proof",) if (len(validations) <= lose_after and not (retry and calls)) else None
        fence.external_command.side_effect = checked
        def prepare(_worktree, environment, *args, **kwargs):
            fence.command_environment.return_value = environment
            return None if lose_after == 0 else fence
        fence.dispatcher_git_command.side_effect = lambda argv, env: (argv, self.env)
        with mock.patch("omh.coding.fanout_dispatch.signal_safe_unit_runner", runner), mock.patch(
                "omh.coding.fanout_dispatch.prepare_fanout_filesystem_confinement",
                side_effect=prepare), mock.patch(
                "omh.coding.fanout_dispatch._consider_unit_retry",
                side_effect=lambda *a, **k: {"retry": retry and k["attempt"] == 1, "delay_seconds": 0}):
            result = self.dispatch(runner=runner, max_retries=1)
        self.assertEqual(calls, [("fixture-proof",)] if retry else [])
        self.assertEqual(result.get("reason_code"), "filesystem_confinement_unavailable")

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_absent_fence_cannot_launch(self):
        self._check_lost_fence(0)

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_lost_initial_fence_cannot_launch(self):
        self._check_lost_fence(1)

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_lost_retry_fence_cannot_launch(self):
        self._check_lost_fence(100, retry=True)

    def test_binding_required_before_readiness(self):
        del self.contract["units"][0]["handoff"]["user_executor"]
        readiness = mock.Mock(return_value={"status": "blocked"})
        result = self.dispatch(readiness=readiness)
        self.assertEqual(result["status"], "user_executor_binding_refused")
        readiness.assert_not_called()

    def test_retarget_rebinds_only_the_new_external_owner(self):
        from omh.coding.fanout_dispatch import _retarget_dispatch

        external = self.contract["units"][0]
        builtin = build_fanout_contract(_GOAL, [_unit("codex")])["units"][0]
        entries = load_user_executors(self.paths.omh_home).entries
        for original, target in ((builtin, "my-agent"), (external, "codex")):
            with self.subTest(target=target), mock.patch(
                    "omh.coding.fanout_dispatch._dispatch_unit", return_value={}) as dispatch:
                _retarget_dispatch(self.paths, unit=original, new_owner=target,
                                   failed_owner=original["owner"], unit_dispatch_kwargs={"executor_entries": entries})
                binding = dispatch.call_args.args[1]["handoff"].get("user_executor")
                self.assertEqual(binding, external["handoff"]["user_executor"] if target == "my-agent" else None)

    @mock.patch("omh.coding.user_executors.USER_EXECUTOR_LAUNCH_SUPPORTED", True)
    def test_cli_freeze_preflight_and_dispatch_use_one_registry_read(self):
        from _cli_harness import run_cli

        write_fanout_contract(self.paths, self.contract)
        prefix = ["--omh-home", str(self.paths.omh_home), "coding"]
        for surface, args in (
            ("dispatch", ["fanout", "dispatch", self.contract["fanout_id"], "--goal-file", "-"]),
            ("run", ["run", "--owner", "my-agent", "--goal-file", "-"]),
        ):
            with self.subTest(surface=surface), mock.patch.dict(os.environ, self.env), mock.patch(
                    "omh.coding.user_executors.load_user_executors", wraps=load_user_executors) as load:
                code, out, err = run_cli(prefix + args + ["--repo-root", str(self.repo), "--dry-run"],
                                         stdin_text=_GOAL)
                self.assertEqual(code, 0, err)
                summary = json.loads(out)
                if surface == "run":
                    summary = summary["dispatch"]
                self.assertEqual(summary["base_sha"], self.base)
                self.assertEqual(summary["units"][0]["status"], "dry_run_planned")
                self.assertEqual(load.call_count, 1)

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_one_registry_read_including_readiness(self):
        with mock.patch("omh.coding.user_executors.load_user_executors",
                        wraps=load_user_executors) as load, mock.patch(
                "omh.coding.executor_readiness.bounded_session_probe",
                return_value=(None, "probe_failed")):
            self.dispatch()
        self.assertEqual(load.call_count, 1)


class ExternalDispatchTests(unittest.TestCase):
    """Real spawns of a fake CLI on a temporary PATH, judged from git."""

    def _dispatch(self, tmp: str, *, executor_id: str, mode: str):
        root = Path(tmp)
        binaries = _bin_dir(root, executor_id, mode)
        paths = _home(root, {executor_id: (executor_id, "")})
        repo, sha = _make_repo(root)
        registry = load_user_executors(paths.omh_home)
        contract = write_fanout_contract(
            paths, build_fanout_contract(_GOAL, [_unit(executor_id)], registry=registry)
        )
        environment = {
            **os.environ,
            "PATH": f"{binaries}{os.pathsep}{os.environ.get('PATH', '')}",
        }
        with mock.patch.dict(os.environ, environment):
            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                env=environment,
            )
        unit = summary["units"][0]
        return paths, repo, sha, unit, summary

    def _worktree(self, repo: Path) -> Path:
        return repo.parent / "repo-fanout-core"

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_a_fake_cli_that_commits_completes_the_unit(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, unit, _summary = self._dispatch(
                tmp, executor_id="my-agent", mode="commit"
            )
            worktree = self._worktree(repo)
            head = _git(worktree, "rev-parse", "HEAD")
            self.assertEqual(unit["status"], "completed", unit)
            self.assertTrue(unit["process_succeeded"], unit)
            self.assertNotEqual(head, sha, "the fake CLI committed in the unit worktree")
            self.assertEqual(_git(worktree, "show", "--name-only", "--format=", head), "agent_output.txt")
            # The private scratch the dispatcher wrote is gone.
            self.assertEqual(list(worktree.glob(".omh-executor-tmp-*")), [])

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_a_nonzero_exit_is_failed_even_with_confident_output(self) -> None:
        with TemporaryDirectory() as tmp:
            _paths, _repo, _sha, unit, _summary = self._dispatch(
                tmp, executor_id="my-agent", mode="fail"
            )
        self.assertEqual(unit["status"], "failed", unit)
        self.assertEqual(unit["exit_code"], 1)
        self.assertFalse(unit["process_succeeded"])

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_exit_zero_without_a_commit_is_not_a_completed_edit(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, unit, _summary = self._dispatch(
                tmp, executor_id="my-agent", mode="prose"
            )
            head = _git(self._worktree(repo), "rev-parse", "HEAD")
        self.assertEqual(head, sha)
        # Stdout said "Committed the change. All checks pass."; git says nothing happened.
        self.assertEqual(unit["status"], "failed", unit)
        self.assertEqual(unit["exit_code"], 0)
        self.assertFalse(unit["process_succeeded"])
        self.assertIn("no clean descendant commit", unit["reason"])

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_a_prompt_file_declaration_receives_the_exact_prompt_privately(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            binaries = _bin_dir(root, "my-agent", "file", template=_FAKE_PROMPT_FILE_CLI)
            paths = _home_with_argv(
                root, "my-agent", '["my-agent", "read", "{prompt_file}"]'
            )
            repo, sha = _make_repo(root)
            registry = load_user_executors(paths.omh_home)
            contract = write_fanout_contract(
                paths, build_fanout_contract(_GOAL, [_unit("my-agent")], registry=registry)
            )
            environment = {
                **os.environ,
                "PATH": f"{binaries}{os.pathsep}{os.environ.get('PATH', '')}",
            }
            with mock.patch.dict(os.environ, environment):
                summary = dispatch_fanout(
                    paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                    env=environment,
                )
            unit = summary["units"][0]
            worktree = repo.parent / "repo-fanout-core"
            head = _git(worktree, "rev-parse", "HEAD")
            committed = sorted(_git(worktree, "show", "--name-only", "--format=", head).splitlines())
            copied = (worktree / "prompt_copy.txt").read_text(encoding="utf-8")
            leftovers = list(worktree.glob(".omh-executor-tmp-*"))
        self.assertEqual(unit["status"], "completed", unit)
        # The file transport carried the assembled prompt verbatim ...
        self.assertIn("Work unit: Core work", copied)
        self.assertIn("Stay strictly inside these paths: src/", copied)
        # ... its scratch was private and is gone, and only the executor's own
        # file was committed -- never the prompt.
        self.assertEqual(committed, ["prompt_copy.txt"])
        self.assertEqual(leftovers, [])

    def test_a_changed_definition_is_refused_before_any_spawn(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            binaries = _bin_dir(root, "my-agent", "commit")
            paths = _home(root, {"my-agent": ("my-agent", "")})
            repo, sha = _make_repo(root)
            registry = load_user_executors(paths.omh_home)
            contract = write_fanout_contract(
                paths, build_fanout_contract(_GOAL, [_unit("my-agent")], registry=registry)
            )
            # Rewrite the declaration after the freeze: same id, new argv.
            routing = paths.omh_home / "routing" / "executors.toml"
            routing.write_text(
                routing.read_text(encoding="utf-8").replace(
                    'argv = ["my-agent", "run", "--", "{prompt}"]',
                    'argv = ["my-agent", "--headless", "--", "{prompt}"]',
                ),
                encoding="utf-8",
            )
            environment = {
                **os.environ,
                "PATH": f"{binaries}{os.pathsep}{os.environ.get('PATH', '')}",
            }
            with mock.patch.dict(os.environ, environment):
                summary = dispatch_fanout(
                    paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                    env=environment,
                )
            unit = summary["units"][0]
            worktree = repo.parent / "repo-fanout-core"
        self.assertEqual(unit["status"], "user_executor_binding_refused", unit)
        self.assertIn("changed since the contract was frozen", unit["reason"])
        self.assertFalse(worktree.exists(), "a refused unit never allocates a worktree")

    def test_an_unknown_owner_keeps_the_prepared_prompt_fallback(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _home(root, {"my-agent": ("my-agent", "")})
            repo, sha = _make_repo(root)
            # A contract frozen for a built-in handoff-only owner still says
            # "unsupported for local dispatch" rather than guessing a CLI.
            contract = write_fanout_contract(
                paths, build_fanout_contract(_GOAL, [_unit("generic")])
            )
            summary = dispatch_fanout(
                paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                env=dict(os.environ),
            )
            unit = summary["units"][0]
        self.assertEqual(unit["status"], "unsupported_for_local_dispatch", unit)


class ShellFreeLaunchTests(unittest.TestCase):
    """The external launch path never hands a worker argv to a shell."""

    def test_the_declared_program_is_the_first_element(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), {"my-agent": ("my-agent", "")})
            spec = load_user_executors(paths.omh_home).entries["my-agent"]
            argv = build_user_executor_argv("my-agent", "do the thing", spec=spec)
        assert argv is not None
        self.assertEqual(argv[0], "my-agent")
        # No shell launcher and no `-c` anywhere the worker could read as one.
        self.assertNotIn("sh", argv)
        self.assertNotIn("bash", argv)
        self.assertNotIn("-c", argv)


if __name__ == "__main__":
    unittest.main()
