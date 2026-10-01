from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest import mock

from _local_package import load_local_package
from _platform_support import requires_posix

load_local_package()

from omh.coding.fanout_confinement import (  # noqa: E402
    FanoutFilesystemConfinement,
    _grant_write_roots,
    _probe,
    owner_state_directories,
    owner_state_files,
    prepare_fanout_filesystem_confinement,
)
from omh.coding.fanout_restricted_token import (  # noqa: E402
    launcher_command,
    main as restricted_token_main,
    parse_launcher_arguments,
    write_root_sid,
)
from omh.quality.cross_harness_adapter_sandbox import (  # noqa: E402
    ChildContext,
    read_roots_are_safe,
    runtime_roots,
    sandbox_command,
)
from omh.coding.fanout_dispatch import (  # noqa: E402
    _run_planned_verification,
    _run_verification_command,
    fanout_child_env,
    signal_safe_unit_runner,
)
from omh.system.paths import OmhPaths  # noqa: E402


def _linked_worktree(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _ = subprocess.run(("/usr/bin/git", "init", "-q"), cwd=repo, check=True)
    (repo / "seed").write_text("seed", encoding="utf-8")
    _ = subprocess.run(("/usr/bin/git", "add", "seed"), cwd=repo, check=True)
    _ = subprocess.run(
        ("/usr/bin/git", "-c", "user.name=test", "-c", "user.email=test@example.test", "commit", "-qm", "init"),
        cwd=repo,
        check=True,
    )
    worktree = root / "linked-worktree"
    _ = subprocess.run(("/usr/bin/git", "worktree", "add", "-qb", "agent/unit", str(worktree), "HEAD"), cwd=repo, check=True)
    return worktree



def _working_linux_bwrap() -> bool:
    """A trusted bwrap that can start an unprivileged user-namespace sandbox here.

    CI runners carry no bwrap, and some distributions restrict unprivileged
    user namespaces; either way the Linux backend is absent, not broken.
    """
    if not sys.platform.startswith("linux"):
        return False
    from omh.quality.cross_harness_adapter_backend import trusted_bwrap

    snapshot = trusted_bwrap()
    if snapshot is None:
        return False
    try:
        completed = subprocess.run(
            (str(snapshot.path), "--unshare-user", "--disable-userns", "--ro-bind", "/", "/", "/usr/bin/true"),
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


class _ConfinedSpawnContract:
    """Real-sandbox checks every enforcing backend must pass on its own host."""

    probe_refusal = ""

    def test_probe_receipt_requires_an_inside_write_and_an_outside_refusal(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree = Path(temporary) / "worktree"
            worktree.mkdir()

            confinement = prepare_fanout_filesystem_confinement(
                worktree,
                {},
                (("/bin/sh", "-c", "exit 0"),),
            )

            self.assertEqual(confinement.receipt["status"], "observed")
            self.assertTrue(confinement.receipt["enforced"])
            self.assertEqual(confinement.receipt["probe"]["inside_write_exit_code"], 0)
            self.assertEqual(confinement.receipt["probe"]["outside_write_exit_code"], 1)
            self.assertIn(self.probe_refusal, confinement.receipt["probe"]["refusal"])

    def test_owner_cli_under_a_sensitive_directory_is_really_fenced(self) -> None:
        """#1602: a CLI installed at `~/.claude/local/<cli>` gets a fence, not an exemption."""
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worktree = root / "worktree"
            worktree.mkdir()
            install = root / ".claude" / "local"
            install.mkdir(parents=True)
            executable = install / "claude"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o700)

            confinement = prepare_fanout_filesystem_confinement(
                worktree,
                {},
                ((str(executable),), ("/bin/sh", "-c", "exit 0")),
            )

            # The install directory is in the read roots and the screen still
            # calls that set unsafe; the run is fenced by its own probe anyway.
            self.assertIn(install, confinement.roots)
            self.assertFalse(read_roots_are_safe(confinement.roots))
            self.assertTrue(confinement.receipt["enforced"])
            self.assertEqual(confinement.receipt["probe"]["inside_write_exit_code"], 0)
            self.assertEqual(confinement.receipt["probe"]["outside_write_exit_code"], 1)

    def test_confined_command_can_exec_a_real_binary_without_widening_writes(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree = (Path(temporary) / "worktree").resolve()
            worktree.mkdir()
            inside = worktree / "inside"
            outside = worktree.parent / "outside"
            confinement = prepare_fanout_filesystem_confinement(
                worktree,
                {},
                (("/bin/sh", "-c", "exit 0"),),
            )
            argv = (
                "/bin/sh",
                "-c",
                '"/bin/ls" / > "$1"; inside=$?; printf x > "$2"; outside=$?; '
                'printf "inside_exit=%s outside_exit=%s\\n" "$inside" "$outside"; '
                'test "$inside" -eq 0 -a "$outside" -ne 0',
                "omh-confinement-exec-probe",
                str(inside),
                str(outside),
            )

            completed = subprocess.run(
                confinement.command(argv),
                cwd=worktree,
                env={},
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0)
            self.assertEqual(completed.stdout.strip(), "inside_exit=0 outside_exit=1")
            self.assertTrue(inside.is_file())
            self.assertFalse(outside.exists())

    def test_confined_toolchain_shims_run(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree = _linked_worktree(Path(temporary))
            confinement = prepare_fanout_filesystem_confinement(
                worktree,
                {},
                (("/usr/bin/git", "--version"), ("/usr/bin/python3", "-c", "print('python-ok')")),
            )

            git = subprocess.run(
                confinement.command(("/usr/bin/git", "--version")),
                cwd=worktree,
                env=confinement.command_environment(),
                text=True,
                capture_output=True,
                check=False,
            )
            python = subprocess.run(
                confinement.command(("/usr/bin/python3", "-c", "print('python-ok')")),
                cwd=worktree,
                env=confinement.command_environment(),
                text=True,
                capture_output=True,
                check=False,
            )

            status = subprocess.run(
                confinement.command(("/usr/bin/git", "status", "--porcelain")),
                cwd=worktree,
                env=confinement.command_environment(),
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(git.returncode, 0, git.stderr)
            self.assertEqual(python.returncode, 0, python.stderr)
            self.assertEqual(status.stdout, "", status.stderr)

    def test_passed_confinement_preserves_verification_environment_overrides(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree = Path(temporary) / "worktree"
            worktree.mkdir()
            confinement = prepare_fanout_filesystem_confinement(
                worktree, {}, (("/bin/sh", "-c", "exit 0"),)
            )

            status, _detail, _truncation = _run_verification_command(
                'OMH_MARK=present /bin/sh -c \'test "$OMH_MARK" = present\'',
                worktree,
                signal_safe_unit_runner,
                confinement=confinement,
            )

            self.assertEqual(status, "passed")

    def test_integration_plan_preserves_confined_verification_environment_overrides(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            worktree = _linked_worktree(root)
            revision = subprocess.run(
                ("/usr/bin/git", "rev-parse", "HEAD^{tree}"),
                cwd=worktree,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            command = 'OMH_MARK=present /bin/sh -c \'test "$OMH_MARK" = present\''
            confinement = prepare_fanout_filesystem_confinement(
                worktree, {}, (("/bin/sh", "-c", "exit 0"),)
            )
            unit = {
                "unit_id": "core",
                "verification_commands": [command],
                "verification_checks": [
                    {"id": "integration-env", "command": command, "tier": "integration", "safety": "read_only"}
                ],
            }
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            with mock.patch("omh.coding.fanout_dispatch.append_journal_observation"):
                result = _run_planned_verification(
                    paths,
                    unit,
                    fanout_id="fanout",
                    run_ref="run",
                    unit_id="core",
                    worktree=worktree,
                    owner="codex",
                    runner=signal_safe_unit_runner,
                    child_env={},
                    wave_width=1,
                    execution_gate=None,
                    integration_ready=lambda: True,
                    required_revision=revision,
                    post_integration=True,
                    producer_evidence=True,
                    confinement=confinement,
                )

            self.assertEqual(result["verification_status"], "passed")

    def test_empty_command_list_is_not_reported_as_a_missing_executable(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree = Path(temporary) / "worktree"
            worktree.mkdir()
            no_command = prepare_fanout_filesystem_confinement(worktree, {}, ())
            missing_executable = prepare_fanout_filesystem_confinement(
                worktree, {}, (("omh-command-that-does-not-exist",),)
            )

            self.assertEqual(no_command.receipt["status"], "prepared_not_observed")
            self.assertFalse(no_command.receipt["enforced"])
            self.assertEqual(no_command.receipt["reason_code"], "sandbox_no_runnable_command")
            self.assertEqual(missing_executable.receipt["reason_code"], "sandbox_executable_not_found")
            self.assertNotEqual(
                no_command.receipt["reason_code"], missing_executable.receipt["reason_code"]
            )

    def test_preflight_failure_is_recorded_as_unconfined(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree = Path(temporary) / "worktree"
            worktree.mkdir()
            with mock.patch("omh.coding.fanout_confinement.preflight", return_value=(False, "test-digest")):
                confinement = prepare_fanout_filesystem_confinement(
                    worktree,
                    {},
                    (("/bin/sh", "-c", "exit 0"),),
                )

            self.assertEqual(confinement.receipt["status"], "prepared_not_observed")
            self.assertFalse(confinement.receipt["enforced"])
            self.assertEqual(confinement.receipt["reason_code"], "sandbox_preflight_failed")

    def test_verification_command_is_confined_when_it_has_no_owner_receipt(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree = Path(temporary) / "worktree"
            worktree.mkdir()
            inside = worktree / "inside"
            outside = worktree.parent / "outside"
            command = shlex.join(
                [
                    "/bin/sh",
                    "-c",
                    'printf inside > inside; inside_code=$?; printf outside > ../outside; outside_code=$?; test "$inside_code" -eq 0 -a "$outside_code" -ne 0',
                ]
            )

            status, _detail, _truncation = _run_verification_command(
                command, worktree, signal_safe_unit_runner
            )

            self.assertEqual(status, "passed")
            self.assertTrue(inside.is_file())
            self.assertFalse(outside.exists())


@requires_posix
class FanoutConfinementPolicyTests(unittest.TestCase):
    """Backend-independent policy; nothing here needs a working sandbox."""

    def test_owner_state_directories_allow_only_the_selected_owner_state(self) -> None:
        home = Path("/tmp/fanout-owner-home").resolve()
        with mock.patch("omh.coding.fanout_confinement.Path.home", return_value=home):
            self.assertEqual(owner_state_directories("codex", {}), (home / ".codex",))
            self.assertEqual(owner_state_directories("claude-code", {}), (home / ".claude",))
            self.assertEqual(owner_state_files("claude-code", {}), (home / ".claude.json",))
            configured_claude = {"CLAUDE_CONFIG_DIR": str(home / "configured-claude")}
            self.assertEqual(owner_state_directories("claude-code", configured_claude), (home / "configured-claude",))
            self.assertEqual(
                owner_state_files("claude-code", configured_claude),
                (home / "configured-claude" / ".claude.json",),
            )
            self.assertEqual(owner_state_directories("hermes", {}), (home / ".hermes",))
            for host, expected in {
                "pi": (home / ".pi" / "agent",),
                "senpi": (home / ".senpi" / "agent",),
                "opencode": (
                    home / ".local" / "share" / "opencode",
                    home / ".local" / "state" / "opencode",
                ),
            }.items():
                with self.subTest(host=host):
                    with mock.patch("omh.coding.fanout_dispatch.omo_runtime_host", return_value=host):
                        self.assertEqual(owner_state_directories("omo-runtime", {}), expected)
            with mock.patch("omh.coding.fanout_dispatch.omo_runtime_host", return_value="pi"):
                self.assertEqual(
                    owner_state_directories("omo-runtime", {"PI_CODING_AGENT_DIR": str(home / "pi-override")}),
                    (home / "pi-override",),
                )
            with mock.patch("omh.coding.fanout_dispatch.omo_runtime_host", return_value="senpi"):
                self.assertEqual(
                    owner_state_directories("omo-runtime", {"OMO_CODING_AGENT_DIR": str(home / "omo-state")}),
                    (home / ".senpi" / "agent",),
                )
                self.assertEqual(
                    owner_state_directories("omo-runtime", {"PI_CODING_AGENT_DIR": str(home / "legacy-pi-override")}),
                    (home / "legacy-pi-override",),
                )
                self.assertEqual(
                    owner_state_directories(
                        "omo-runtime",
                        {
                            "SENPI_CODING_AGENT_DIR": str(home / "senpi-override"),
                            "PI_CODING_AGENT_DIR": str(home / "ignored-pi-override"),
                        },
                    ),
                    (home / "senpi-override",),
                )
        self.assertEqual(owner_state_directories("unassigned", {}), ())

    def test_omo_runtime_child_env_pins_agent_dir_and_scrubs_senpi_brand(self) -> None:
        home = Path("/tmp/fanout-owner-home").resolve()
        cases = {
            "pi": ("PI_CODING_AGENT_DIR", {}, home / ".pi" / "agent"),
            "senpi": (
                "SENPI_CODING_AGENT_DIR",
                {"PI_CODING_AGENT_DIR": str(home / "legacy-senpi-override")},
                home / "legacy-senpi-override",
            ),
        }
        for host, (environment_variable, overrides, expected) in cases.items():
            with (
                self.subTest(host=host),
                mock.patch("omh.coding.fanout_confinement.Path.home", return_value=home),
                mock.patch("omh.coding.fanout_dispatch.omo_runtime_host", return_value=host),
            ):
                child_env = fanout_child_env(
                    {
                        "SENPI_BRAND": '{"name":"omo","envPrefix":"OMO","configDir":".omo"}',
                        **overrides,
                    },
                    depth=0,
                    fanout_id="fanout",
                    unit_id="unit",
                    owner="omo-runtime",
                )
                self.assertEqual(child_env[environment_variable], str(expected))
                self.assertEqual(owner_state_directories("omo-runtime", child_env), (expected,))
                self.assertNotIn("SENPI_BRAND", child_env)
        with mock.patch("omh.coding.fanout_dispatch.omo_runtime_host", return_value="opencode"):
            child_env = fanout_child_env(
                {"SENPI_BRAND": "ambient"},
                depth=0,
                fanout_id="fanout",
                unit_id="unit",
                owner="omo-runtime",
            )
        self.assertEqual(child_env["SENPI_BRAND"], "ambient")

    def test_probe_writes_every_owner_state_root(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            worktree = root / "worktree"
            worktree.mkdir()
            first_state = root / "first-state"
            second_state = root / "second-state"
            first_state.mkdir()
            second_state.mkdir()
            child = ChildContext(
                worktree, worktree, worktree, worktree, worktree,
                worktree / "request", worktree / "artifact", "confinement-probe",
            )
            with (
                mock.patch("omh.coding.fanout_confinement.sandbox_command", side_effect=lambda argv, *_args, **_kwargs: argv),
                mock.patch(
                    "omh.coding.fanout_confinement.subprocess.run",
                    return_value=subprocess.CompletedProcess(
                        (),
                        0,
                        "owner_state_exit=0\nowner_state_exit=0\ninside_exit=0 owner_state_exit=0 outside_exit=1\n",
                        "",
                    ),
                ),
            ):
                receipt = _probe("sandbox-exec", (), (worktree, first_state, second_state), (), child, {}, "digest")
            command = receipt["probe"]["command"]
            self.assertTrue(any(str(second_state) in argument for argument in command))

    def test_command_environment_uses_the_dispatcher_filtered_mapping(self) -> None:
        from omh.coding.fanout_confinement import FanoutFilesystemConfinement

        confinement = FanoutFilesystemConfinement(
            selected="unsupported",
            roots=(),
            write_roots=(),
            write_literals=(),
            child=None,
            environment={"PARENT_SECRET": "must-not-reach-command"},
            backend_digest="",
            executables={},
            receipt={"enforced": False},
        )

        environment = confinement.command_environment({"PATH": "/usr/bin"})

        self.assertEqual(environment, {"PATH": "/usr/bin"})

    def test_owner_cli_in_a_sensitive_directory_is_fenced_like_any_other(self) -> None:
        """#1602: where the executable lives must not decide whether writes are fenced.

        Reads are broad in this lane whatever `roots` say, so the read screen
        could only ever have removed the write fence.
        """
        with TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            worktree = home / "worktree"
            worktree.mkdir()
            directories = {"sensitive": home / ".claude" / "local", "ordinary": home / "opt" / "local"}
            receipts: dict[str, dict[str, object]] = {}
            children: dict[str, ChildContext | None] = {}
            with mock.patch("omh.coding.fanout_confinement.Path.home", return_value=home):
                for label, directory in directories.items():
                    directory.mkdir(parents=True)
                    executable = directory / "claude"
                    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                    executable.chmod(0o700)
                    with (
                        mock.patch("omh.coding.fanout_confinement.backend", return_value="sandbox-exec"),
                        mock.patch("omh.coding.fanout_confinement.backend_available", return_value=True),
                        mock.patch("omh.coding.fanout_confinement.preflight", return_value=(True, "digest")),
                        mock.patch(
                            "omh.coding.fanout_confinement.sandbox_command",
                            side_effect=lambda argv, *_args, **_kwargs: argv,
                        ),
                        mock.patch(
                            "omh.coding.fanout_confinement.subprocess.run",
                            return_value=subprocess.CompletedProcess((), 1, "", "refused"),
                        ),
                    ):
                        confinement = prepare_fanout_filesystem_confinement(
                            worktree, {}, ((str(executable),),)
                        )
                    receipts[label] = confinement.receipt
                    children[label] = confinement.child

            # The detector still calls this shape unsafe. What changed is that
            # the fanout lane no longer answers it by dropping the fence.
            self.assertFalse(read_roots_are_safe((directories["sensitive"],)))
            self.assertIsNotNone(children["sensitive"])
            self.assertNotEqual(receipts["sensitive"]["reason_code"], "unsafe_sandbox_read_root")
            # The probe entry carries a per-run token, so compare the fence the
            # receipt reports rather than the receipt verbatim.
            fence_keys = ("status", "backend", "write_root", "write_roots", "write_literals", "enforced", "reason_code")
            self.assertEqual(
                {key: receipts["sensitive"][key] for key in fence_keys},
                {key: receipts["ordinary"][key] for key in fence_keys},
            )

    def test_host_without_a_trusted_bwrap_has_no_backend_rather_than_a_failed_preflight(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree = Path(temporary) / "worktree"
            worktree.mkdir()
            with (
                mock.patch("omh.coding.fanout_confinement.backend", return_value="bwrap"),
                mock.patch("omh.coding.fanout_confinement.backend_available", return_value=True),
                mock.patch("omh.coding.fanout_confinement.trusted_bwrap", return_value=None),
                mock.patch("omh.coding.fanout_confinement.preflight") as preflight_call,
            ):
                confinement = prepare_fanout_filesystem_confinement(
                    worktree,
                    {},
                    (("/bin/sh", "-c", "exit 0"),),
                )

            self.assertEqual(confinement.receipt["status"], "prepared_not_observed")
            self.assertFalse(confinement.receipt["enforced"])
            self.assertEqual(confinement.receipt["reason_code"], "sandbox_backend_unavailable")
            self.assertIsNone(confinement.command(("/bin/sh", "-c", "exit 0")))
            preflight_call.assert_not_called()

    def test_bwrap_preflight_and_probe_run_under_the_spawn_layout(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree = Path(temporary) / "worktree"
            worktree.mkdir()
            probe_calls: list[dict[str, object]] = []

            def record_probe(argv, *_args, **kwargs):
                probe_calls.append(kwargs)
                return argv

            with (
                mock.patch("omh.coding.fanout_confinement.backend", return_value="bwrap"),
                mock.patch("omh.coding.fanout_confinement.backend_available", return_value=True),
                mock.patch("omh.coding.fanout_confinement.trusted_bwrap", return_value=object()),
                mock.patch("omh.coding.fanout_confinement.preflight", return_value=(True, "digest")) as preflight_call,
                mock.patch("omh.coding.fanout_confinement.sandbox_command", side_effect=record_probe),
                mock.patch(
                    "omh.coding.fanout_confinement.subprocess.run",
                    return_value=subprocess.CompletedProcess((), 1, "", "refused"),
                ),
            ):
                confinement = prepare_fanout_filesystem_confinement(
                    worktree,
                    {},
                    (("/bin/sh", "-c", "exit 0"),),
                )

            self.assertEqual(
                preflight_call.call_args.kwargs,
                {"allow_broad_file_read": True, "inherit_environment": True},
            )
            self.assertEqual(len(probe_calls), 1)
            self.assertTrue(probe_calls[0]["allow_broad_file_read"])
            self.assertTrue(probe_calls[0]["inherit_environment"])
            self.assertTrue((worktree / ".omh" / "confinement-tmp" / ".gitignore").is_file())
            self.assertFalse(confinement.receipt["enforced"])

    def test_sandbox_exec_preflight_and_probe_keep_the_strict_probe_policy(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree = Path(temporary) / "worktree"
            worktree.mkdir()
            probe_calls: list[dict[str, object]] = []

            def record_probe(argv, *_args, **kwargs):
                probe_calls.append(kwargs)
                return argv

            with (
                mock.patch("omh.coding.fanout_confinement.backend", return_value="sandbox-exec"),
                mock.patch("omh.coding.fanout_confinement.backend_available", return_value=True),
                mock.patch("omh.coding.fanout_confinement.preflight", return_value=(True, "digest")) as preflight_call,
                mock.patch("omh.coding.fanout_confinement.sandbox_command", side_effect=record_probe),
                mock.patch(
                    "omh.coding.fanout_confinement.subprocess.run",
                    return_value=subprocess.CompletedProcess((), 1, "", "refused"),
                ),
            ):
                prepare_fanout_filesystem_confinement(
                    worktree,
                    {},
                    (("/bin/sh", "-c", "exit 0"),),
                )

            self.assertEqual(
                preflight_call.call_args.kwargs,
                {"allow_broad_file_read": False, "inherit_environment": False},
            )
            self.assertEqual(len(probe_calls), 1)
            self.assertFalse(probe_calls[0]["allow_broad_file_read"])
            self.assertFalse(probe_calls[0]["inherit_environment"])

    def test_bwrap_command_environment_keeps_toolchain_scratch_in_the_worktree(self) -> None:
        worktree = Path("/tmp/fanout-bwrap-worktree")
        child = ChildContext(
            worktree, worktree, worktree, worktree, worktree,
            worktree / "request", worktree / "artifact", "fanout-filesystem-confinement",
        )
        confinement = FanoutFilesystemConfinement(
            selected="bwrap",
            roots=(worktree,),
            write_roots=(worktree,),
            write_literals=(),
            child=child,
            environment={"PATH": "/usr/bin"},
            backend_digest="digest",
            executables={},
            receipt={"enforced": True},
        )

        environment = confinement.command_environment({"PATH": "/usr/bin", "OMH_MARK": "present"})

        self.assertEqual(
            environment,
            {"PATH": "/usr/bin", "OMH_MARK": "present", "TMPDIR": str(worktree / ".omh" / "confinement-tmp")},
        )


@unittest.skipUnless(sys.platform == "darwin", "sandbox-exec confinement is exercised on macOS")
class FanoutFilesystemConfinementTests(_ConfinedSpawnContract, unittest.TestCase):
    probe_refusal = "Operation not permitted"

    def test_selected_owner_state_is_a_write_only_root_and_escape_routes_stay_refused(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worktree = root / "worktree"
            worktree.mkdir()
            state = root / "claude-state"
            state.mkdir()
            outside = root / "outside"
            unrelated_repo = root / "unrelated-repo"
            unrelated_repo.mkdir()
            _ = subprocess.run(("/usr/bin/git", "init", "-q"), cwd=unrelated_repo, check=True)
            source = worktree / "rename-source"
            source.write_text("source", encoding="utf-8")
            linked_outside = root / "linked-outside"
            linked_outside.mkdir()
            symlink = worktree / "outside-link"
            symlink.symlink_to(linked_outside, target_is_directory=True)
            confinement = prepare_fanout_filesystem_confinement(
                worktree,
                {"CLAUDE_CONFIG_DIR": str(state)},
                (("/bin/sh", "-c", "exit 0"),),
                owner="claude-code",
            )

            self.assertTrue(confinement.receipt["enforced"])
            self.assertEqual(confinement.receipt["write_roots"], [str(worktree), str(state)])
            self.assertEqual(confinement.receipt["write_literals"], [str(state / ".claude.json")])
            self.assertNotIn(state, confinement.roots)
            self.assertNotIn(state / ".claude.json", confinement.roots)
            policy = confinement.command(("/bin/sh", "-c", "exit 0"))[2]
            self.assertIn(f'(allow file-write* (literal "{state / ".claude.json"}"))', policy)
            self.assertIn('(allow mach-lookup (global-name "com.apple.securityd.xpc"))', policy)
            self.assertIn('(allow mach-lookup (global-name "com.apple.SecurityServer"))', policy)
            self.assertEqual(confinement.receipt["probe"]["owner_state_write_exit_code"], 0)
            self.assertEqual(confinement.receipt["probe"]["owner_state_write_exit_codes"], [0])
            write_state = subprocess.run(
                confinement.command(("/bin/sh", "-c", 'printf state > "$1"', "probe", str(state / "state"))),
                cwd=worktree,
                env=confinement.command_environment(),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(write_state.returncode, 0, write_state.stderr)
            self.assertTrue((state / "state").is_file())

            escapes = {
                "direct": ('printf direct > "$1"', (outside,)),
                "child_process": ('/bin/sh -c \'printf child > "$1"\' child "$1"', (outside,)),
                "rename_out": ('mv "$1" "$2"', (source, outside)),
                "hardlink_out": ('ln "$1" "$2"', (source, outside)),
                "symlink_out": ('printf symlink > "$1/file"', (symlink,)),
                "unrelated_repo": ('printf unrelated > "$1/file"', (unrelated_repo,)),
            }
            for name, (script, arguments) in escapes.items():
                with self.subTest(escape=name):
                    completed = subprocess.run(
                        confinement.command(("/bin/sh", "-c", script, name, *(str(path) for path in arguments))),
                        cwd=worktree,
                        env=confinement.command_environment(),
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertNotEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(outside.exists())
            self.assertTrue(source.is_file())
            self.assertFalse((linked_outside / "file").exists())
            self.assertFalse((unrelated_repo / "file").exists())

    def test_seatbelt_literal_replacement_does_not_grant_descendant_writes(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worktree = root / "worktree"
            worktree.mkdir()
            literal = root / "state-file"
            literal.write_text("state", encoding="utf-8")
            child = ChildContext(
                worktree, worktree, worktree, worktree, worktree,
                worktree / "request", worktree / "artifact", "literal-replacement",
            )
            literal.unlink()
            literal.mkdir()
            script = (
                'printf child > "$1/child"; descendant=$?; '
                'printf "descendant=%s\\n" "$descendant"; test "$descendant" -ne 0'
            )
            completed = subprocess.run(
                sandbox_command(
                    ("/bin/sh", "-c", script, "literal-replacement", str(literal)),
                    "sandbox-exec",
                    (worktree, Path("/bin"), *runtime_roots("sandbox-exec")),
                    child,
                    True,
                    {},
                    write_literals=(literal,),
                ),
                cwd=worktree,
                env={},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "descendant=1")
            self.assertTrue(literal.is_dir())
            self.assertFalse((literal / "child").exists())


@unittest.skipUnless(_working_linux_bwrap(), "bwrap confinement is exercised on Linux hosts with a trusted, working bwrap")
class LinuxBwrapFanoutConfinementTests(_ConfinedSpawnContract, unittest.TestCase):
    probe_refusal = "Read-only file system"

    def test_selected_owner_state_is_a_write_only_root_and_escape_routes_stay_refused(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worktree = root / "worktree"
            worktree.mkdir()
            state = root / "claude-state"
            state.mkdir()
            outside = root / "outside"
            outside_directory = root / "outside-directory"
            unrelated_repo = root / "unrelated-repo"
            unrelated_repo.mkdir()
            _ = subprocess.run(("/usr/bin/git", "init", "-q"), cwd=unrelated_repo, check=True)
            source = worktree / "rename-source"
            source.write_text("source", encoding="utf-8")
            linked_outside = root / "linked-outside"
            linked_outside.mkdir()
            symlink = worktree / "outside-link"
            symlink.symlink_to(linked_outside, target_is_directory=True)
            confinement = prepare_fanout_filesystem_confinement(
                worktree,
                {"CLAUDE_CONFIG_DIR": str(state)},
                (("/bin/sh", "-c", "exit 0"),),
                owner="claude-code",
            )

            self.assertTrue(confinement.receipt["enforced"])
            self.assertEqual(confinement.receipt["write_roots"], [str(worktree), str(state)])
            self.assertEqual(confinement.receipt["write_literals"], [str(state / ".claude.json")])
            self.assertEqual(confinement.receipt["probe"]["owner_state_write_exit_codes"], [0])
            command = confinement.command(("/bin/sh", "-c", "exit 0"))
            self.assertEqual(command[command.index("--ro-bind"):command.index("--ro-bind") + 3], ("--ro-bind", "/", "/"))
            state_index = command.index("--bind-try")
            self.assertEqual(
                command[state_index:state_index + 6],
                ("--bind-try", str(state), str(state), "--bind-try", str(state / ".claude.json"), str(state / ".claude.json")),
            )
            self.assertNotIn("--clearenv", command)
            write_state = subprocess.run(
                confinement.command(("/bin/sh", "-c", 'printf state > "$1"', "probe", str(state / "state"))),
                cwd=worktree,
                env=confinement.command_environment(),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(write_state.returncode, 0, write_state.stderr)
            self.assertTrue((state / "state").is_file())

            escapes = {
                "direct": ('printf direct > "$1"', (outside,)),
                "child_process": ('/bin/sh -c \'printf child > "$1"\' child "$1"', (outside,)),
                "rename_out": ('mv "$1" "$2"', (source, outside)),
                "hardlink_out": ('ln "$1" "$2"', (source, outside)),
                "symlink_out": ('printf symlink > "$1/file"', (symlink,)),
                "unrelated_repo": ('printf unrelated > "$1/file"', (unrelated_repo,)),
                "mkdir_out": ('mkdir "$1"', (outside_directory,)),
                "exclusive_create_out": ('/usr/bin/python3 -c "import sys; open(sys.argv[1], \'x\')" "$1"', (outside,)),
                "chdir_then_relative": ('cd .. && printf relative > outside', ()),
            }
            for name, (script, arguments) in escapes.items():
                with self.subTest(escape=name):
                    completed = subprocess.run(
                        confinement.command(("/bin/sh", "-c", script, name, *(str(path) for path in arguments))),
                        cwd=worktree,
                        env=confinement.command_environment(),
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertNotEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(outside.exists())
            self.assertFalse(outside_directory.exists())
            self.assertTrue(source.is_file())
            self.assertFalse((linked_outside / "file").exists())
            self.assertFalse((unrelated_repo / "file").exists())

    def test_spawn_environment_and_toolchain_scratch_reach_the_confined_child(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree = _linked_worktree(Path(temporary))
            confinement = prepare_fanout_filesystem_confinement(
                worktree,
                {"PATH": "/usr/bin:/bin"},
                (("/bin/sh", "-c", "exit 0"),),
            )
            environment = {**confinement.command_environment(), "OMH_SPAWN_MARK": "present"}

            completed = subprocess.run(
                confinement.command(
                    ("/bin/sh", "-c", 'printf "%s|%s" "$OMH_SPAWN_MARK" "$TMPDIR"; scratch=$(mktemp) && printf t > "$scratch"')
                ),
                cwd=worktree,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            status = subprocess.run(
                ("/usr/bin/git", "status", "--porcelain"),
                cwd=worktree,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout, f"present|{worktree / '.omh' / 'confinement-tmp'}")
            self.assertEqual(len(list((worktree / ".omh" / "confinement-tmp").glob("tmp.*"))), 1)
            self.assertEqual(status.stdout, "", status.stderr)

    def test_user_runtime_directory_is_hidden_and_read_only(self) -> None:
        runtime_directory = Path("/run/user") / str(os.getuid())
        if not runtime_directory.is_dir():
            self.skipTest("this host has no per-user runtime directory")
        with TemporaryDirectory() as temporary:
            worktree = (Path(temporary) / "worktree").resolve()
            worktree.mkdir()
            marker = runtime_directory / f"omh-confinement-runtime-probe-{os.getpid()}"
            confinement = prepare_fanout_filesystem_confinement(
                worktree,
                {},
                (("/bin/sh", "-c", "exit 0"),),
            )

            completed = subprocess.run(
                confinement.command(
                    (
                        "/bin/sh",
                        "-c",
                        'test -z "$(ls -A "$1")"; empty=$?; printf x > "$2"; write=$?; '
                        'printf "empty=%s write=%s" "$empty" "$write"; test "$empty" -eq 0 -a "$write" -ne 0',
                        "omh-runtime-probe",
                        str(runtime_directory),
                        str(marker),
                    )
                ),
                cwd=worktree,
                env={},
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("Read-only file system", completed.stderr)
            self.assertFalse(marker.exists())


def _restricted_token_confinement(worktree: Path, **changes: object) -> FanoutFilesystemConfinement:
    child = ChildContext(
        worktree, worktree, worktree, worktree, worktree,
        worktree / "request", worktree / "artifact", "fanout-filesystem-confinement",
    )
    fields: dict[str, object] = {
        "selected": "restricted-token",
        "roots": (worktree,),
        "write_roots": (worktree,),
        "write_literals": (),
        "child": child,
        "environment": {},
        "backend_digest": "",
        "executables": {},
        "receipt": {"enforced": True},
    }
    fields.update(changes)
    return FanoutFilesystemConfinement(**fields)  # type: ignore[arg-type]


class RestrictedTokenPolicyTests(unittest.TestCase):
    """The Windows backend's pure logic, checked on every host."""

    def test_each_write_root_has_its_own_stable_sid(self) -> None:
        first = Path("C:/Work/Unit-A") if sys.platform == "win32" else Path("/work/unit-a")
        second = first.parent / "unit-b"
        sid = write_root_sid(first)

        self.assertRegex(sid, r"^S-1-5-21-\d+-\d+-\d+-\d+$")
        self.assertTrue(all(int(part) < 2**32 for part in sid.split("-")[4:]))
        self.assertEqual(write_root_sid(first), sid)
        # Windows compares paths without case, so the grant must too.
        self.assertEqual(write_root_sid(Path(str(first).upper())), sid)
        self.assertNotEqual(write_root_sid(second), sid)

    def test_launcher_arguments_round_trip_and_reject_a_malformed_list(self) -> None:
        sids = ("S-1-5-21-1-2-3-4", "S-1-5-21-5-6-7-8")
        command = launcher_command("python", sids, ("tool", "--flag", "a b"))

        self.assertEqual(command[:3], ("python", "-I", "-B"))
        self.assertTrue(command[3].endswith("fanout_restricted_token.py"))
        self.assertEqual(parse_launcher_arguments(command[4:]), (sids, ("tool", "--flag", "a b")))
        malformed_lists = (
            (),
            ("S-1-5-21-1-2-3-4", "tool"),
            ("", "--", "tool"),
            ("Everyone", "--", "tool"),
            ("S-1-5-21-1-2-3-4", "--"),
        )
        for malformed in malformed_lists:
            with self.subTest(arguments=malformed), self.assertRaises(ValueError):
                _ = parse_launcher_arguments(malformed)

    def test_launcher_reports_usage_and_refuses_off_windows(self) -> None:
        with mock.patch("sys.stderr"):
            self.assertEqual(restricted_token_main(("S-1-5-21-1-2-3-4", "tool")), 2)
            if sys.platform != "win32":
                self.assertEqual(restricted_token_main(("S-1-5-21-1-2-3-4", "--", "tool")), 125)

    def test_command_names_one_restricting_sid_per_write_root_and_literal(self) -> None:
        worktree = Path("/tmp/fanout-restricted-worktree").resolve()
        state = Path("/tmp/fanout-restricted-state").resolve()
        literal = Path("/tmp/fanout-restricted-state.json").resolve()
        confinement = _restricted_token_confinement(
            worktree,
            write_roots=(worktree, state),
            write_literals=(literal,),
            executables={"tool": "/opt/tool"},
        )

        self.assertEqual(
            confinement.command(("tool", "run")),
            launcher_command(
                sys.executable,
                (write_root_sid(worktree), write_root_sid(state), write_root_sid(literal)),
                ("/opt/tool", "run"),
            ),
        )
        self.assertIsNone(confinement.command(("unresolved", "run")))
        unproven = _restricted_token_confinement(
            worktree, executables={"tool": "/opt/tool"}, receipt={"enforced": False}
        )
        self.assertIsNone(unproven.command(("tool", "run")))

    def test_command_environment_replaces_every_spelling_of_the_temp_variables(self) -> None:
        worktree = Path("/tmp/fanout-restricted-worktree").resolve()
        confinement = _restricted_token_confinement(worktree)
        scratch = str(worktree / ".omh" / "confinement-tmp")

        environment = confinement.command_environment(
            {"PATH": "bin", "Temp": "host-temp", "tmp": "host-tmp", "OMH_MARK": "present"}
        )

        self.assertEqual(
            environment,
            {"PATH": "bin", "OMH_MARK": "present", "TEMP": scratch, "TMP": scratch, "TMPDIR": scratch},
        )

    def test_a_refused_grant_degrades_with_its_own_reason(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree = Path(temporary) / "worktree"
            worktree.mkdir()
            with (
                mock.patch("omh.coding.fanout_confinement.backend", return_value="restricted-token"),
                mock.patch("omh.coding.fanout_confinement.backend_available", return_value=True),
                mock.patch(
                    "omh.coding.fanout_confinement.grant_write_root",
                    side_effect=OSError(5, "SetNamedSecurityInfoW failed (Windows error 5)"),
                ),
            ):
                confinement = prepare_fanout_filesystem_confinement(
                    worktree, {}, ((sys.executable, "-c", "pass"),)
                )

            self.assertEqual(confinement.receipt["backend"], "restricted-token")
            self.assertEqual(confinement.receipt["status"], "prepared_not_observed")
            self.assertFalse(confinement.receipt["enforced"])
            self.assertEqual(confinement.receipt["reason_code"], "sandbox_write_grant_failed")
            self.assertIsNone(confinement.command((sys.executable, "-c", "pass")))

    def test_only_existing_write_roots_are_granted(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worktree = root / "worktree"
            worktree.mkdir()
            literal = root / "state.json"
            literal.write_text("{}", encoding="utf-8")
            calls: list[tuple[Path, str, bool]] = []

            def record(path: Path, sid: str, *, directory: bool) -> bool:
                calls.append((path, sid, directory))
                return True

            with mock.patch("omh.coding.fanout_confinement.grant_write_root", side_effect=record):
                granted = _grant_write_roots((worktree, root / "absent-state"), (root / "absent.json", literal))

            self.assertTrue(granted)
            self.assertEqual(
                calls,
                [(worktree, write_root_sid(worktree), True), (literal, write_root_sid(literal), False)],
            )


_WRITE_CHILD = "import sys; open(sys.argv[1], 'w').write('child')"


@unittest.skipUnless(sys.platform == "win32", "the restricted-token backend is exercised on Windows")
class WindowsRestrictedTokenFanoutConfinementTests(unittest.TestCase):
    """The real Windows fence: a write-restricted token, granted per root, refused elsewhere."""

    def _prepare(
        self, worktree: Path, environment: dict[str, str] | None = None, *, owner: str = ""
    ) -> FanoutFilesystemConfinement:
        confinement = prepare_fanout_filesystem_confinement(
            worktree,
            dict(os.environ) if environment is None else environment,
            ((sys.executable, "-c", "pass"),),
            owner=owner,
        )
        self.assertTrue(confinement.receipt["enforced"], confinement.receipt)
        return confinement

    def _run(
        self, confinement: FanoutFilesystemConfinement, worktree: Path, code: str, *arguments: Path | str
    ) -> subprocess.CompletedProcess[str]:
        command = confinement.command(
            (sys.executable, "-c", "import sys\n" + code, *(str(argument) for argument in arguments))
        )
        assert command is not None
        return subprocess.run(
            command,
            cwd=worktree,
            env=confinement.command_environment(),
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )

    def test_probe_receipt_requires_an_inside_write_and_an_outside_refusal(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree = Path(temporary).resolve() / "worktree"
            worktree.mkdir()

            confinement = self._prepare(worktree)

            self.assertEqual(confinement.receipt["status"], "observed")
            self.assertEqual(confinement.receipt["backend"], "restricted-token")
            self.assertEqual(confinement.receipt["probe"]["inside_write_exit_code"], 0)
            self.assertNotEqual(confinement.receipt["probe"]["outside_write_exit_code"], 0)
            self.assertIn("Permission denied", confinement.receipt["probe"]["refusal"])
            self.assertFalse(any(worktree.parent.glob(".omh-confinement-outside-*")))

    def test_owner_state_is_writable_and_escape_routes_stay_refused(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worktree = root / "worktree"
            worktree.mkdir()
            state = root / "claude-state"
            state.mkdir()
            sibling = root / "sibling-worktree"
            sibling.mkdir()
            existing = root / "existing"
            existing.write_text("original", encoding="utf-8", newline="")
            outside = root / "outside"
            outside_directory = root / "outside-directory"
            junction_target = root / "junction-target"
            junction_target.mkdir()
            source = worktree / "rename-source"
            source.write_text("source", encoding="utf-8", newline="")
            canary = Path.home() / f"omh-confinement-canary-{os.getpid()}"
            self.addCleanup(lambda: canary.unlink(missing_ok=True))
            # A second unit's worktree carries its own grant, to its own SID.
            _ = self._prepare(sibling)
            confinement = self._prepare(
                worktree, {**os.environ, "CLAUDE_CONFIG_DIR": str(state)}, owner="claude-code"
            )
            self.assertEqual(confinement.receipt["write_roots"], [str(worktree), str(state)])
            self.assertEqual(confinement.receipt["probe"]["owner_state_write_exit_codes"], [0])

            spawn_child = "import subprocess; subprocess.run([sys.executable, '-c', %r, sys.argv[1]], check=True)" % _WRITE_CHILD
            allowed = {
                "worktree": ("open(sys.argv[1], 'w').write('inside')", (worktree / "inside",)),
                "owner_state": ("open(sys.argv[1], 'w').write('state')", (state / "state",)),
                "child_process_inside": (spawn_child, (worktree / "child-inside",)),
                "toolchain_temp": (
                    "import os, tempfile; handle, path = tempfile.mkstemp(); os.close(handle); "
                    "assert os.path.dirname(path) == sys.argv[1], (path, sys.argv[1])",
                    (worktree / ".omh" / "confinement-tmp",),
                ),
            }
            for name, (code, arguments) in allowed.items():
                with self.subTest(allowed=name):
                    completed = self._run(confinement, worktree, code, *arguments)
                    self.assertEqual(completed.returncode, 0, completed.stderr)

            escapes = {
                "direct": ("open(sys.argv[1], 'w').write('x')", (outside,)),
                "overwrite_existing": ("open(sys.argv[1], 'w').write('x')", (existing,)),
                "append_existing": ("open(sys.argv[1], 'a').write('x')", (existing,)),
                "delete_existing": ("import os; os.remove(sys.argv[1])", (existing,)),
                "rename_out": ("import os; os.replace(sys.argv[1], sys.argv[2])", (source, outside)),
                "mkdir_out": ("import os; os.mkdir(sys.argv[1])", (outside_directory,)),
                "child_process": (spawn_child, (outside,)),
                "hardlink_then_write": (
                    "import os; os.link(sys.argv[1], sys.argv[2]); open(sys.argv[2], 'w').write('x')",
                    (existing, worktree / "hardlink"),
                ),
                "junction_then_write": (
                    "import os, subprocess; "
                    "subprocess.run(['cmd', '/c', 'mklink', '/J', sys.argv[1], sys.argv[2]], check=True, capture_output=True); "
                    "open(os.path.join(sys.argv[1], 'file'), 'w').write('x')",
                    (worktree / "junction", junction_target),
                ),
                "acl_change": (
                    "import subprocess; "
                    "subprocess.run(['icacls', sys.argv[1], '/grant', '*S-1-1-0:F'], check=True, capture_output=True)",
                    (existing,),
                ),
                "sibling_unit_worktree": ("open(sys.argv[1], 'w').write('x')", (sibling / "file",)),
                "user_profile": ("open(sys.argv[1], 'w').write('x')", (canary,)),
                "chdir_then_relative": ("import os; os.chdir('..'); open('outside', 'w').write('x')", ()),
            }
            for name, (code, arguments) in escapes.items():
                with self.subTest(escape=name):
                    completed = self._run(confinement, worktree, code, *arguments)
                    self.assertNotEqual(completed.returncode, 0, f"{name} was not refused: {completed.stderr}")
            self.assertFalse(outside.exists())
            self.assertFalse(outside_directory.exists())
            self.assertEqual(existing.read_text(encoding="utf-8"), "original")
            self.assertTrue(source.is_file())
            self.assertFalse((junction_target / "file").exists())
            self.assertFalse((sibling / "file").exists())
            self.assertFalse(canary.exists())

    def test_terminating_the_launcher_ends_the_confined_process_tree(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree = Path(temporary).resolve() / "worktree"
            worktree.mkdir()
            started = worktree / "started"
            marker = worktree / "late-write"
            confinement = self._prepare(worktree)
            late_writer = "import sys, time; time.sleep(4); open(sys.argv[1], 'w').write('late')"
            code = (
                "import subprocess, time\n"
                f"subprocess.Popen([sys.executable, '-c', {late_writer!r}, sys.argv[2]])\n"
                "open(sys.argv[1], 'w').write('started')\n"
                "time.sleep(60)\n"
            )
            command = confinement.command((sys.executable, "-c", "import sys\n" + code, str(started), str(marker)))
            assert command is not None
            launcher = subprocess.Popen(
                command, cwd=worktree, env=confinement.command_environment(),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.monotonic() + 60
                while not started.exists() and time.monotonic() < deadline:
                    time.sleep(0.1)
                self.assertTrue(started.exists())
            finally:
                launcher.kill()
                _ = launcher.wait(timeout=30)
            time.sleep(6)
            self.assertFalse(marker.exists())

    def test_verification_command_is_confined_when_it_has_no_owner_receipt(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree = Path(temporary).resolve() / "worktree"
            worktree.mkdir()
            inside = worktree / "inside"
            outside = worktree.parent / "outside"
            script = (
                "import sys\n"
                "open('inside', 'w').write('inside')\n"
                "try:\n"
                "    open('../outside', 'w').write('outside')\n"
                "except PermissionError:\n"
                "    sys.exit(0)\n"
                "sys.exit(1)\n"
            )
            command = shlex.join([sys.executable, "-c", script])

            status, detail, _truncation = _run_verification_command(command, worktree, signal_safe_unit_runner)

            self.assertEqual(status, "passed", detail)
            self.assertTrue(inside.is_file())
            self.assertFalse(outside.exists())

    def test_git_runs_in_a_confined_linked_worktree(self) -> None:
        git = shutil.which("git")
        if git is None:
            self.skipTest("git is not installed")
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo = root / "repo"
            repo.mkdir()
            identity = ("-c", "user.name=test", "-c", "user.email=test@example.test")
            _ = subprocess.run((git, "init", "-q"), cwd=repo, check=True)
            (repo / "seed").write_text("seed", encoding="utf-8", newline="")
            _ = subprocess.run((git, "add", "seed"), cwd=repo, check=True)
            _ = subprocess.run((git, *identity, "commit", "-qm", "init"), cwd=repo, check=True)
            worktree = root / "linked-worktree"
            _ = subprocess.run(
                (git, "worktree", "add", "-qb", "agent/unit", str(worktree), "HEAD"), cwd=repo, check=True
            )
            confinement = prepare_fanout_filesystem_confinement(
                worktree, dict(os.environ), ((git, "--version"), (sys.executable, "-c", "pass"))
            )
            self.assertTrue(confinement.receipt["enforced"], confinement.receipt)

            for argv in ((git, "--version"), (git, "status", "--porcelain")):
                with self.subTest(argv=argv[1:]):
                    command = confinement.command(argv)
                    assert command is not None
                    completed = subprocess.run(
                        command, cwd=worktree, env=confinement.command_environment(),
                        stdin=subprocess.DEVNULL, text=True, capture_output=True, timeout=120, check=False,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    if argv[1] == "status":
                        self.assertEqual(completed.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
