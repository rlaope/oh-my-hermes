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
            argv = build_dispatch_argv("codex", "P", spec=next(iter(registry.entries.values())))
        # The spec's id is not "codex", so it is ignored and the template wins.
        self.assertEqual(argv, ["codex", "exec", "P"])


class UserExecutorArgvTests(unittest.TestCase):
    def test_prompt_is_one_argv_element_whatever_it_contains(self) -> None:
        prompt = "line one\nline two $(rm -rf /) `id` 'quote' {brace} --flag"
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), {"my-agent": ("my-agent", "")})
            spec = load_user_executors(paths.omh_home).entries["my-agent"]
        argv = build_dispatch_argv("my-agent", prompt, spec=spec)
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
            build_dispatch_argv(
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

    def test_a_nonzero_exit_is_failed_even_with_confident_output(self) -> None:
        with TemporaryDirectory() as tmp:
            _paths, _repo, _sha, unit, _summary = self._dispatch(
                tmp, executor_id="my-agent", mode="fail"
            )
        self.assertEqual(unit["status"], "failed", unit)
        self.assertEqual(unit["exit_code"], 1)
        self.assertFalse(unit["process_succeeded"])

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
            argv = build_dispatch_argv("my-agent", "do the thing", spec=spec)
        assert argv is not None
        self.assertEqual(argv[0], "my-agent")
        # No shell launcher and no `-c` anywhere the worker could read as one.
        self.assertNotIn("sh", argv)
        self.assertNotIn("bash", argv)
        self.assertNotIn("-c", argv)


if __name__ == "__main__":
    unittest.main()
