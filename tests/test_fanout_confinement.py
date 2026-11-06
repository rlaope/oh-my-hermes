from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from _local_package import load_local_package
from _platform_support import requires_posix

load_local_package()

from omh.coding.fanout_confinement import (  # noqa: E402
    FanoutFilesystemConfinement,
    _git_write_roots,
    _probe,
    git_roots_skip_reason,
    owner_state_directories,
    owner_state_files,
    prepare_fanout_filesystem_confinement,
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
from omh.coding.pi_family_interop import PI_DISTRIBUTION_AGENT_DIR_ENV, PI_DISTRIBUTION_BRAND_ENV, PI_DISTRIBUTION_HOME, PI_DISTRIBUTION_HOST, RUNTIME_HOME, RUNTIME_SHORT_NAME
import json


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
                PI_DISTRIBUTION_HOST: (home / PI_DISTRIBUTION_HOME / "agent",),
                "opencode": (
                    home / ".local" / "share" / "opencode",
                    home / ".local" / "state" / "opencode",
                ),
            }.items():
                with self.subTest(host=host):
                    with mock.patch("omh.coding.fanout_dispatch.pi_family_host", return_value=host):
                        self.assertEqual(owner_state_directories("pi-family-runtime", {}), expected)
            with mock.patch("omh.coding.fanout_dispatch.pi_family_host", return_value="pi"):
                self.assertEqual(
                    owner_state_directories("pi-family-runtime", {"PI_CODING_AGENT_DIR": str(home / "pi-override")}),
                    (home / "pi-override",),
                )
            with mock.patch("omh.coding.fanout_dispatch.pi_family_host", return_value=PI_DISTRIBUTION_HOST):
                self.assertEqual(
                    owner_state_directories("pi-family-runtime", {f"{RUNTIME_SHORT_NAME.upper()}_CODING_AGENT_DIR": str(home / "runtime-state")}),
                    (home / PI_DISTRIBUTION_HOME / "agent",),
                )
                self.assertEqual(
                    owner_state_directories("pi-family-runtime", {"PI_CODING_AGENT_DIR": str(home / "legacy-pi-override")}),
                    (home / "legacy-pi-override",),
                )
                self.assertEqual(
                    owner_state_directories(
                        "pi-family-runtime",
                        {
                            PI_DISTRIBUTION_AGENT_DIR_ENV: str(home / "distribution-override"),
                            "PI_CODING_AGENT_DIR": str(home / "ignored-pi-override"),
                        },
                    ),
                    (home / "distribution-override",),
                )
        self.assertEqual(owner_state_directories("unassigned", {}), ())

    def test_pi_family_runtime_child_env_pins_agent_dir_and_scrubs_pi_distribution_brand(self) -> None:
        home = Path("/tmp/fanout-owner-home").resolve()
        cases = {
            "pi": ("PI_CODING_AGENT_DIR", {}, home / ".pi" / "agent"),
            PI_DISTRIBUTION_HOST: (
                PI_DISTRIBUTION_AGENT_DIR_ENV,
                {"PI_CODING_AGENT_DIR": str(home / "legacy-distribution-override")},
                home / "legacy-distribution-override",
            ),
        }
        for host, (environment_variable, overrides, expected) in cases.items():
            with (
                self.subTest(host=host),
                mock.patch("omh.coding.fanout_confinement.Path.home", return_value=home),
                mock.patch("omh.coding.fanout_dispatch.pi_family_host", return_value=host),
            ):
                child_env = fanout_child_env(
                    {
                        PI_DISTRIBUTION_BRAND_ENV: json.dumps({"name": RUNTIME_SHORT_NAME, "envPrefix": RUNTIME_SHORT_NAME.upper(), "configDir": RUNTIME_HOME}, separators=(",", ":")),
                        **overrides,
                    },
                    depth=0,
                    fanout_id="fanout",
                    unit_id="unit",
                    owner="pi-family-runtime",
                )
                self.assertEqual(child_env[environment_variable], str(expected))
                self.assertEqual(owner_state_directories("pi-family-runtime", child_env), (expected,))
                self.assertNotIn(PI_DISTRIBUTION_BRAND_ENV, child_env)
        with mock.patch("omh.coding.fanout_dispatch.pi_family_host", return_value="opencode"):
            child_env = fanout_child_env(
                {PI_DISTRIBUTION_BRAND_ENV: "ambient"},
                depth=0,
                fanout_id="fanout",
                unit_id="unit",
                owner="pi-family-runtime",
            )
        self.assertEqual(child_env[PI_DISTRIBUTION_BRAND_ENV], "ambient")

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

        scratch = worktree / ".omh" / "confinement-tmp"
        self.assertEqual(
            environment,
            {
                "PATH": "/usr/bin",
                "OMH_MARK": "present",
                "TMPDIR": str(scratch),
                "TMPPREFIX": str(scratch / "zsh"),
                "UV_CACHE_DIR": str(scratch / "uv-cache"),
                "CLAUDE_CODE_TMPDIR": str(scratch / "claude-code"),
            },
        )

    def _scratch_confinement(self, worktree: Path, *, enforced: bool = True) -> FanoutFilesystemConfinement:
        child = ChildContext(
            worktree, worktree, worktree, worktree, worktree,
            worktree / "request", worktree / "artifact", "fanout-filesystem-confinement",
        )
        return FanoutFilesystemConfinement(
            selected="sandbox-exec",
            roots=(worktree,),
            write_roots=(worktree,),
            write_literals=(),
            child=child,
            environment={"PATH": "/usr/bin"},
            backend_digest="digest",
            executables={},
            receipt={"enforced": enforced},
        )

    def test_zsh_and_uv_scratch_follow_tmpdir_only_for_an_enforced_fence(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree = Path(temporary).resolve() / "worktree"
            worktree.mkdir()
            scratch = worktree / ".omh" / "confinement-tmp"

            enforced = self._scratch_confinement(worktree).command_environment({"PATH": "/usr/bin"})
            unenforced = self._scratch_confinement(worktree, enforced=False).command_environment({"PATH": "/usr/bin"})

            self.assertEqual(enforced["TMPPREFIX"], str(scratch / "zsh"))
            self.assertEqual(enforced["UV_CACHE_DIR"], str(scratch / "uv-cache"))
            self.assertEqual(enforced["CLAUDE_CODE_TMPDIR"], str(scratch / "claude-code"))
            claude_temp = Path(enforced["CLAUDE_CODE_TMPDIR"])
            (claude_temp / "claude-501" / "project").mkdir(parents=True)
            (claude_temp / "cc-socks").mkdir()
            self.assertEqual(unenforced, {"PATH": "/usr/bin"})

    def test_caller_uv_cache_and_tmpprefix_are_kept_only_inside_a_write_root(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worktree = root / "worktree"
            worktree.mkdir()
            scratch = worktree / ".omh" / "confinement-tmp"
            confinement = self._scratch_confinement(worktree)
            inside = str(worktree / "cache" / "uv")
            outside = str(root / "home" / ".cache" / "uv")

            kept = confinement.command_environment(
                {"UV_CACHE_DIR": inside, "TMPPREFIX": str(worktree / "zsh-tmp" / "zsh")}
            )
            replaced = confinement.command_environment({"UV_CACHE_DIR": outside, "TMPPREFIX": "/tmp/zsh"})
            relative = confinement.command_environment({"UV_CACHE_DIR": "cache/uv"})
            # TMPPREFIX is a file-name prefix: `<root>` itself writes `<root>XXXX` beside the root.
            root_prefix = confinement.command_environment({"TMPPREFIX": str(worktree)})
            self.assertEqual(root_prefix["TMPPREFIX"], str(scratch / "zsh"))

            self.assertEqual(kept["UV_CACHE_DIR"], inside)
            self.assertEqual(kept["TMPPREFIX"], str(worktree / "zsh-tmp" / "zsh"))
            self.assertEqual(replaced["UV_CACHE_DIR"], str(scratch / "uv-cache"))
            self.assertEqual(replaced["TMPPREFIX"], str(scratch / "zsh"))
            self.assertEqual(relative["UV_CACHE_DIR"], str(scratch / "uv-cache"))
            for configured, expected in (
                (str(worktree / "claude-temp"), str(worktree / "claude-temp")),
                (str(worktree), str(worktree)),
                (str(root / "outside"), str(scratch / "claude-code")),
                ("relative/claude", str(scratch / "claude-code")),
            ):
                with self.subTest(claude_temp=configured):
                    environment = confinement.command_environment({"CLAUDE_CODE_TMPDIR": configured})
                    self.assertEqual(environment["CLAUDE_CODE_TMPDIR"], expected)
            unenforced = self._scratch_confinement(worktree, enforced=False)
            self.assertEqual(
                unenforced.command_environment({"CLAUDE_CODE_TMPDIR": "/outside"}),
                {"CLAUDE_CODE_TMPDIR": "/outside"},
            )

    def test_seatbelt_profile_adds_only_the_preference_read_ipc_and_no_write(self) -> None:
        # #1996: Codex fails startup when CFPreferencesAppSynchronize returns
        # false. The fence adds the cfprefsd lookups and read-only cfprefs
        # shared memory, and the profile is otherwise byte-identical.
        worktree = Path("/tmp/fanout-seatbelt-worktree")
        state = Path("/tmp/fanout-seatbelt-state")
        child = ChildContext(
            worktree, worktree, worktree, worktree, worktree,
            worktree / "request", worktree / "artifact", "fanout-filesystem-confinement",
        )
        confinement = FanoutFilesystemConfinement(
            selected="sandbox-exec",
            roots=(worktree, Path("/bin")),
            write_roots=(worktree, state),
            write_literals=(state / "state.json",),
            child=child,
            environment={"PATH": "/usr/bin"},
            backend_digest="digest",
            executables={"/bin/sh": "/bin/sh"},
            receipt={"enforced": True},
        )
        command = confinement.command(("/bin/sh", "-c", "exit 0"))
        assert command is not None
        policy = command[2]
        added = (
            '(allow mach-lookup (global-name "com.apple.cfprefsd.daemon"))'
            '(allow mach-lookup (global-name "com.apple.cfprefsd.agent"))'
            '(allow mach-lookup (global-name "com.apple.trustd.agent"))'
            '(allow mach-lookup (global-name "com.apple.trustd"))'
            '(allow ipc-posix-shm-read-data (ipc-posix-name-prefix "apple.cfprefs."))'
        )
        self.assertEqual(policy.count(added), 1)
        without_preferences = sandbox_command(
            ("/bin/sh", "-c", "exit 0"), "sandbox-exec", confinement.roots, child, True,
            confinement.environment, "digest",
            allow_broad_process_exec=True,
            macos_write_data_literals=(Path("/dev/null"),),
            write_literals=confinement.write_literals,
            macos_mach_lookup_names=("com.apple.securityd.xpc", "com.apple.SecurityServer"),
            allow_broad_file_read=True,
            write_roots=confinement.write_roots,
            inherit_environment=True,
            write_paths_resolved=True,
        )[2]
        # Removing exactly these five rules restores the previous profile, so no
        # file-write, process, or other IPC allowance moved with them.
        self.assertEqual(policy.replace(added, ""), without_preferences)
        # cfprefsd refuses a write from a client whose sandbox lacks this.
        self.assertNotIn("user-preference", policy)


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

    @unittest.skipUnless(Path("/usr/bin/sandbox-exec").exists() and Path("/bin/zsh").exists(), "needs sandbox-exec and zsh")
    def test_zsh_heredoc_runs_inside_the_fence(self) -> None:
        # zsh puts heredoc temp files under TMPPREFIX (default /tmp/zsh), which
        # the fence denies; Codex writes every multi-line edit this way.
        argv = ("/bin/zsh", "-c", "cat <<'EOF'\nok\nEOF")
        with TemporaryDirectory() as temporary:
            worktree = Path(temporary).resolve() / "worktree"
            worktree.mkdir()
            confinement = prepare_fanout_filesystem_confinement(
                worktree, {"PATH": "/usr/bin:/bin", "TMPPREFIX": "/tmp/zsh"}, (argv,)
            )
            self.assertTrue(confinement.receipt["enforced"])
            command = confinement.command(argv)
            assert command is not None
            completed = subprocess.run(
                command, cwd=worktree, env=confinement.command_environment(),
                text=True, capture_output=True, check=False,
            )

            self.assertEqual((completed.returncode, completed.stdout), (0, "ok\n"), completed.stderr)

    def test_preferences_synchronize_inside_the_fence_and_preference_writes_stay_refused(self) -> None:
        # #1996: the exact CoreFoundation call Codex makes at startup, after the
        # managed-key query that makes it reach the preferences daemon.
        script = r'''
import ctypes, sys
cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
cf.CFStringCreateWithCString.restype = ctypes.c_void_p
cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
cf.CFPreferencesAppValueIsForced.restype = ctypes.c_bool
cf.CFPreferencesAppValueIsForced.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
cf.CFPreferencesAppSynchronize.restype = ctypes.c_bool
cf.CFPreferencesAppSynchronize.argtypes = [ctypes.c_void_p]
cf.CFPreferencesSetAppValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
def string(value):
    return cf.CFStringCreateWithCString(None, value.encode(), 0x08000100)
codex = string("com.openai.codex")
cf.CFPreferencesAppValueIsForced(string("config_toml_base64"), codex)
print("synchronize=%s" % cf.CFPreferencesAppSynchronize(codex))
domain = string(sys.argv[1])
cf.CFPreferencesSetAppValue(string("written"), string("written"), domain)
print("write_synchronize=%s" % cf.CFPreferencesAppSynchronize(domain))
'''
        domain = f"ai.omh.fence-probe-{os.getpid()}"
        plist = Path.home() / "Library" / "Preferences" / f"{domain}.plist"
        argv = (sys.executable, "-I", "-c", script, domain)
        defaults_argv = ("/bin/sh", "-c", f"/usr/bin/defaults write {domain} k v")
        with TemporaryDirectory() as temporary:
            worktree = Path(temporary).resolve() / "worktree"
            worktree.mkdir()
            confinement = prepare_fanout_filesystem_confinement(
                # Dispatch keeps HOME (fanout_environment); without it this call
                # still fails inside the fence, a case no dispatch reaches.
                worktree, {"PATH": "/usr/bin:/bin", "HOME": str(Path.home())}, (argv, defaults_argv)
            )
            self.assertTrue(confinement.receipt["enforced"])
            command = confinement.command(argv)
            defaults_command = confinement.command(defaults_argv)
            assert command is not None and defaults_command is not None
            try:
                completed = subprocess.run(
                    command, cwd=worktree, env=confinement.command_environment(),
                    text=True, capture_output=True, check=False, timeout=60,
                )
                defaults = subprocess.run(
                    defaults_command, cwd=worktree, env=confinement.command_environment(), capture_output=True, check=False,
                )
            finally:
                # cfprefsd may hold a write before flushing it to the plist.
                read_back = subprocess.run(("/usr/bin/defaults", "read", domain), capture_output=True, check=False)
                plist_written = read_back.returncode == 0 or plist.exists()
                if plist_written:
                    _ = subprocess.run(("/usr/bin/defaults", "delete", domain), capture_output=True, check=False)
                    plist.unlink(missing_ok=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("synchronize=True", completed.stdout.splitlines())
            self.assertIn("write_synchronize=False", completed.stdout.splitlines())
            self.assertNotEqual(defaults.returncode, 0)
            self.assertFalse(plist_written)

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



@unittest.skipUnless(_working_linux_bwrap(), "bwrap confinement is exercised on Linux hosts with a trusted, working bwrap")
class LinkedWorktreeGitWriteRootTests(unittest.TestCase):
    """A dispatched unit commits on its own agent/<unit> branch and nothing else in the shared repository is writable."""

    def _run(self, confinement: FanoutFilesystemConfinement, worktree: Path, script: str) -> subprocess.CompletedProcess[str]:
        argv = ("/bin/sh", "-c", script)
        return subprocess.run(
            confinement.command(argv), cwd=worktree, env=confinement.command_environment(),
            text=True, capture_output=True, check=False,
        )

    _repo: Path | None = None

    def _prepare(self, worktree: Path, unit_branch: str) -> FanoutFilesystemConfinement:
        return prepare_fanout_filesystem_confinement(
            worktree, {}, (("/bin/sh", "-c", "exit 0"),), owner="", unit_branch=unit_branch, repo_root=self._repo,
        )

    def test_own_branch_commits_and_shared_metadata_stays_read_only(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worktree = _linked_worktree(root)
            self._repo = root / "repo"
            common = (root / "repo" / ".git").resolve()
            _ = subprocess.run(("/usr/bin/git", "branch", "release/x"), cwd=root / "repo", check=True)
            main_before = subprocess.run(("/usr/bin/git", "rev-parse", "HEAD"), cwd=root / "repo", text=True, capture_output=True, check=True).stdout
            confinement = self._prepare(worktree, "agent/unit")
            self.assertTrue(confinement.receipt["enforced"])
            roots = set(confinement.receipt["write_roots"])
            self.assertNotIn(str(common), roots)
            self.assertIn(str(common / "objects"), roots)
            self.assertIn(str(common / "refs" / "heads" / "agent"), roots)
            self.assertIn(str(common / "lfs"), roots)  # git-lfs filters write <C>/lfs/tmp on `git add`
            commit = self._run(
                confinement, worktree,
                "echo y >> seed && /usr/bin/git add seed && "
                "/usr/bin/git -c user.name=t -c user.email=t@example.test commit -qm unit",
            )
            self.assertEqual(commit.returncode, 0, commit.stderr)
            refused = {
                "hooks": f'printf x > "{common}/hooks/post-checkout"',
                "config": f'printf "[x]" >> "{common}/config"',
                "packed_refs": f'printf x > "{common}/packed-refs"',
                "default_branch": "/usr/bin/git update-ref refs/heads/master HEAD",
                "other_branch": "/usr/bin/git update-ref refs/heads/release/x HEAD",
                "tag": "/usr/bin/git tag unit-tag",
            }
            for name, script in refused.items():
                with self.subTest(name=name):
                    self.assertNotEqual(self._run(confinement, worktree, script).returncode, 0)
            self.assertFalse((common / "hooks" / "post-checkout").exists())
            self.assertNotIn("[x]", (common / "config").read_text(encoding="utf-8"))
            main_after = subprocess.run(("/usr/bin/git", "rev-parse", "HEAD"), cwd=root / "repo", text=True, capture_output=True, check=True).stdout
            self.assertEqual(main_before, main_after)

    def test_no_git_write_root_unless_head_is_the_units_own_agent_branch(self) -> None:
        cases = {
            "branch_mismatch": ("agent/other", None),
            "empty_branch": ("", None),
            "path_traversal_branch": ("agent/unit/../master", None),
            "detached_head": ("agent/unit", ("/usr/bin/git", "checkout", "-q", "--detach")),
        }
        # A non-linked repository (gitdir == common dir) never receives a git root either.
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worktree = _linked_worktree(root)
            repo = root / "repo"
            _ = subprocess.run(("/usr/bin/git", "checkout", "-qb", "agent/main-unit"), cwd=repo, check=True)
            self._repo = repo
            confinement = self._prepare(repo, "agent/main-unit")
            common = (repo / ".git").resolve()
            self.assertFalse(
                [r for r in confinement.receipt["write_roots"] if Path(r) == common or common in Path(r).parents]
            )
        for name, (unit_branch, setup) in cases.items():
            with self.subTest(name=name), TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                worktree = _linked_worktree(root)
                self._repo = root / "repo"
                common = (root / "repo" / ".git").resolve()
                if setup is not None:
                    _ = subprocess.run(setup, cwd=worktree, check=True)
                confinement = self._prepare(worktree, unit_branch)
                self.assertTrue(confinement.receipt["enforced"])
                self.assertFalse(
                    [r for r in confinement.receipt["write_roots"] if Path(r) == common or common in Path(r).parents]
                )

    def test_symlinked_namespace_or_objects_gets_no_git_root(self) -> None:
        for target in ("refs/heads/agent", "objects", "lfs"):
            with self.subTest(target=target), TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                worktree = _linked_worktree(root)
                self._repo = root / "repo"
                common = (root / "repo" / ".git").resolve()
                real = root / "moved"
                (common / target).mkdir(parents=True, exist_ok=True)  # lfs/ exists only once git-lfs has run
                (common / target).rename(real)
                (common / target).symlink_to(common if target != "objects" else real, target_is_directory=True)
                confinement = self._prepare(worktree, "agent/unit")
                self.assertTrue(confinement.receipt["enforced"])
                self.assertFalse(
                    [r for r in confinement.receipt["write_roots"] if Path(r) == common or common in Path(r).parents]
                )

    def test_planted_symlink_or_alternates_gets_no_git_root(self) -> None:
        for plant in ("ns_symlink", "alternates"):
            with self.subTest(plant=plant), TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                worktree = _linked_worktree(root)
                self._repo = root / "repo"
                common = (root / "repo" / ".git").resolve()
                if plant == "ns_symlink":
                    (common / "refs" / "heads" / "agent" / "hooks").symlink_to(common / "hooks", target_is_directory=True)
                else:
                    (common / "objects" / "info").mkdir(exist_ok=True)
                    (common / "objects" / "info" / "alternates").write_text("/tmp/x\n", encoding="utf-8")
                confinement = self._prepare(worktree, "agent/unit")
                self.assertFalse(
                    [r for r in confinement.receipt["write_roots"] if Path(r) == common or common in Path(r).parents]
                )

    def test_gitdir_of_another_repository_gets_no_git_root(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worktree = _linked_worktree(root)
            other_root = root / "other"
            other_root.mkdir()
            other_worktree = _linked_worktree(other_root)
            other_common = (other_root / "repo" / ".git").resolve()
            (worktree / ".git").write_text(f"gitdir: {other_common}/worktrees/{other_worktree.name}\n", encoding="utf-8")
            self._repo = root / "repo"
            confinement = self._prepare(worktree, "agent/unit")
            self.assertFalse(
                [r for r in confinement.receipt["write_roots"] if Path(r) == other_common or other_common in Path(r).parents]
            )

    def test_unreadable_or_special_entries_get_no_git_root(self) -> None:
        for plant in ("unreadable_dir", "fifo_ref", "fifo_commit_graph"):
            with self.subTest(plant=plant), TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                worktree = _linked_worktree(root)
                self._repo = root / "repo"
                common = (root / "repo" / ".git").resolve()
                hidden = None
                if plant == "unreadable_dir":
                    hidden = common / "refs" / "heads" / "agent" / "x"
                    hidden.mkdir()
                    (hidden / "hooks").symlink_to(common / "hooks", target_is_directory=True)
                    hidden.chmod(0)
                elif plant == "fifo_ref":
                    os.mkfifo(common / "refs" / "heads" / "agent" / "stall")
                else:
                    (common / "objects" / "info").mkdir(exist_ok=True)
                    os.mkfifo(common / "objects" / "info" / "commit-graph")
                try:
                    confinement = self._prepare(worktree, "agent/unit")
                    self.assertFalse(
                        [r for r in confinement.receipt["write_roots"] if Path(r) == common or common in Path(r).parents]
                    )
                finally:
                    if hidden is not None:
                        hidden.chmod(0o755)

    def test_git_failure_adds_no_root_and_never_falls_back_to_unconfined(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worktree = _linked_worktree(root)
            with mock.patch("subprocess.run", side_effect=FileNotFoundError("git")):
                from omh.coding.fanout_confinement import _git_write_roots
                self.assertEqual(_git_write_roots(worktree, "agent/unit", root / "repo"), ())


@unittest.skipUnless(sys.platform == "darwin", "sandbox-exec confinement is exercised on macOS")
class MacosLinkedWorktreeGitWriteRootTests(unittest.TestCase):
    """The sandbox-exec twin of the class above, plus the swaps a path-named grant has to survive."""

    def _run(
        self, confinement: FanoutFilesystemConfinement, cwd: Path, script: str,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            confinement.command(("/bin/sh", "-c", script)), cwd=cwd,
            env=confinement.command_environment(environment), text=True, capture_output=True, check=False,
        )

    def test_own_branch_commits_and_shared_metadata_stays_read_only(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worktree = _linked_worktree(root)
            repo = root / "repo"
            common = (repo / ".git").resolve()
            default_branch = subprocess.run(
                ("/usr/bin/git", "symbolic-ref", "--short", "HEAD"), cwd=repo, text=True, capture_output=True, check=True,
            ).stdout.strip()
            before = subprocess.run(("/usr/bin/git", "rev-parse", "HEAD"), cwd=repo, text=True, capture_output=True, check=True).stdout
            confinement = prepare_fanout_filesystem_confinement(
                worktree, {}, (("/bin/sh", "-c", "exit 0"),), owner="", unit_branch="agent/unit", repo_root=repo,
            )
            self.assertTrue(confinement.receipt["enforced"])
            self.assertIn(str(common / "refs" / "heads" / "agent"), confinement.receipt["write_roots"])
            commit = self._run(
                confinement, worktree,
                "echo y >> seed && /usr/bin/git add seed && "
                "/usr/bin/git -c user.name=t -c user.email=t@example.test commit -qm unit",
            )
            self.assertEqual(commit.returncode, 0, commit.stderr)
            ahead = subprocess.run(
                ("/usr/bin/git", "rev-list", "--count", f"{default_branch}..agent/unit"),
                cwd=repo, text=True, capture_output=True, check=True,
            ).stdout.strip()
            self.assertEqual(ahead, "1")
            # What the git-lfs clean filter does on `git add`: a temp file, then the stored object.
            staged = self._run(
                confinement, worktree,
                f'mkdir -p "{common}/lfs/tmp" "{common}/lfs/objects/ab/cd" && '
                f'printf x > "{common}/lfs/tmp/staged" && mv "{common}/lfs/tmp/staged" "{common}/lfs/objects/ab/cd/abcd"',
            )
            self.assertEqual(staged.returncode, 0, staged.stderr)
            refused = {
                "hooks": f'printf x > "{common}/hooks/post-checkout"',
                "config": f'printf "[x]" >> "{common}/config"',
                "packed_refs": f'printf x > "{common}/packed-refs"',
                "default_branch": f"/usr/bin/git update-ref refs/heads/{default_branch} HEAD",
                "other_namespace": "/usr/bin/git update-ref refs/heads/release/x HEAD",
                "tag": "/usr/bin/git tag unit-tag",
            }
            for name, script in refused.items():
                with self.subTest(name=name):
                    self.assertNotEqual(self._run(confinement, worktree, script).returncode, 0)
            self.assertFalse((common / "hooks" / "post-checkout").exists())
            self.assertNotIn("[x]", (common / "config").read_text(encoding="utf-8"))
            after = subprocess.run(("/usr/bin/git", "rev-parse", "HEAD"), cwd=repo, text=True, capture_output=True, check=True).stdout
            self.assertEqual(before, after)

    def test_a_git_write_root_cannot_be_swapped_for_a_symlink_into_hooks(self) -> None:
        # The write through the swapped name is made by a SECOND command: a
        # grant only follows the symlink when the host resolves the root again
        # to build a later command, never inside the process that planted it.
        for target in ("refs/heads/agent", "logs/refs/heads/agent", "objects", "lfs", "worktrees/linked-worktree"):
            with self.subTest(target=target), TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                worktree = _linked_worktree(root)
                repo = root / "repo"
                common = (repo / ".git").resolve()
                confinement = prepare_fanout_filesystem_confinement(
                    worktree, {}, (("/bin/sh", "-c", "exit 0"),), owner="", unit_branch="agent/unit", repo_root=repo,
                )
                self.assertIn(str(common / target), confinement.receipt["write_roots"])
                swap = self._run(
                    confinement, worktree,
                    f'mv "{common}/{target}" "{worktree}/moved-aside" && ln -s "{common}/hooks" "{common}/{target}"',
                )
                self.assertNotEqual(swap.returncode, 0)
                self.assertIn("Operation not permitted", swap.stderr)
                self.assertTrue((common / target).is_dir())
                self.assertFalse((common / target).is_symlink())
                _ = self._run(confinement, root, f'printf x > "{common}/{target}/post-checkout"')
                self.assertFalse((common / "hooks" / "post-checkout").exists())

    def test_the_worktree_cannot_be_swapped_through_an_owner_state_root(self) -> None:
        """No git root involved: any second write root is a place to park the first one."""
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worktree = root / "worktree"
            worktree.mkdir()
            state = root / "codex-state"
            state.mkdir()
            victim = root / "victim"
            victim.mkdir()
            environment = {"CODEX_HOME": str(state)}
            confinement = prepare_fanout_filesystem_confinement(
                worktree, environment, (("/bin/sh", "-c", "exit 0"),), owner="codex",
            )
            self.assertTrue(confinement.receipt["enforced"])
            for moved, parked in ((worktree, state / "parked"), (state, worktree / "parked")):
                with self.subTest(moved=moved.name):
                    swap = self._run(
                        confinement, root, f'mv "{moved}" "{parked}" && ln -s "{victim}" "{moved}"', environment,
                    )
                    self.assertNotEqual(swap.returncode, 0)
                    self.assertTrue(moved.is_dir())
                    self.assertFalse(moved.is_symlink())
            inside = self._run(confinement, root, f'printf x > "{worktree}/kept" && printf x > "{state}/kept"', environment)
            self.assertEqual(inside.returncode, 0, inside.stderr)
            _ = self._run(confinement, root, f'printf x > "{victim}/reached"', environment)
            self.assertEqual(list(victim.iterdir()), [])

    def test_a_path_planted_after_preparation_is_not_resolved_into_a_grant(self) -> None:
        """Each command reuses the paths resolved once at preparation, so a later symlink grants nothing."""
        cases = ("exact_file_literal", "nested_parent", "root_removed_by_the_host")
        for case in cases:
            with self.subTest(case=case), TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                worktree = _linked_worktree(root)
                repo = root / "repo"
                common = (repo / ".git").resolve()
                home = root / "home"
                (home / ".claude").mkdir(parents=True)
                victim = root / "victim"
                victim.mkdir()
                environment: dict[str, str] = {}
                owner = "claude-code"
                if case == "nested_parent":
                    owner = "codex"
                    (worktree / "sub" / "state").mkdir(parents=True)
                    environment = {"CODEX_HOME": str(worktree / "sub" / "state")}
                with mock.patch.dict(os.environ, {"HOME": str(home)}):
                    confinement = prepare_fanout_filesystem_confinement(
                        worktree, environment, (("/bin/sh", "-c", "exit 0"),),
                        owner=owner, unit_branch="agent/unit", repo_root=repo,
                    )
                self.assertTrue(confinement.receipt["enforced"])
                self.assertIn(str(common / "refs" / "heads" / "agent"), confinement.receipt["write_roots"])
                if case == "exact_file_literal":
                    literal = home / ".claude.json"
                    self.assertIn(literal, confinement.write_literals)
                    plant = f'rm -f "{literal}" && ln -s "{common}/config" "{literal}"'
                    reach = f'printf "[planted]" >> "{common}/config"'
                    reached = lambda: "[planted]" in (common / "config").read_text(encoding="utf-8")  # noqa: E731
                elif case == "nested_parent":
                    plant = f'mv "{worktree}/sub" "{worktree}/sub.away" && ln -s "{victim}" "{worktree}/sub"'
                    (victim / "state").mkdir()
                    reach = f'printf x > "{victim}/state/reached"'
                    reached = lambda: (victim / "state" / "reached").exists()  # noqa: E731
                else:
                    # `git pack-refs --all` on the host moves the unit's loose ref into
                    # packed-refs and prunes the now-empty namespace directory.
                    _ = subprocess.run(("/usr/bin/git", "pack-refs", "--all"), cwd=repo, check=True)
                    namespace = common / "refs" / "heads" / "agent"
                    if namespace.exists():
                        namespace.rmdir()
                    plant = f'ln -s "{common}/hooks" "{namespace}"'
                    reach = f'printf x > "{common}/hooks/post-checkout"'
                    reached = lambda: (common / "hooks" / "post-checkout").exists()  # noqa: E731
                planted = self._run(confinement, worktree, plant, environment)
                self.assertEqual(planted.returncode, 0, planted.stderr)
                attempt = self._run(confinement, root, reach, environment)
                self.assertNotEqual(attempt.returncode, 0)
                self.assertFalse(reached())


@requires_posix
class GitLfsWriteRootTests(unittest.TestCase):
    """`_git_write_roots` needs no sandbox, so these run on every POSIX job, CI included."""

    def test_lfs_is_granted_and_created_as_a_real_directory(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worktree = _linked_worktree(root)
            common = (root / "repo" / ".git").resolve()
            self.assertFalse((common / "lfs").exists())
            roots = _git_write_roots(worktree, "agent/unit", root / "repo")
            self.assertEqual(git_roots_skip_reason(worktree), "")
            self.assertIn(common / "lfs", roots)
            self.assertTrue((common / "lfs").is_dir())
            self.assertFalse((common / "lfs").is_symlink())

    def test_a_symlinked_lfs_root_gets_no_git_root(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worktree = _linked_worktree(root)
            common = (root / "repo" / ".git").resolve()
            (common / "lfs").symlink_to(common / "hooks", target_is_directory=True)
            self.assertEqual(_git_write_roots(worktree, "agent/unit", root / "repo"), ())
            self.assertEqual(git_roots_skip_reason(worktree), "symlink")

    def test_a_symlink_planted_inside_lfs_gets_no_git_root(self) -> None:
        for planted in ("objects", "tmp", "objects/ab"):
            with self.subTest(planted=planted), TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                worktree = _linked_worktree(root)
                common = (root / "repo" / ".git").resolve()
                (common / "lfs" / planted).parent.mkdir(parents=True, exist_ok=True)
                (common / "lfs" / planted).symlink_to(common / "hooks", target_is_directory=True)
                self.assertEqual(_git_write_roots(worktree, "agent/unit", root / "repo"), ())
                self.assertEqual(git_roots_skip_reason(worktree), "hygiene")

    def test_an_ordinary_lfs_store_keeps_its_git_roots(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worktree = _linked_worktree(root)
            common = (root / "repo" / ".git").resolve()
            for directory in ("tmp", "cache/locks", "objects/ab/cd"):
                (common / "lfs" / directory).mkdir(parents=True)
            (common / "lfs" / "objects" / "ab" / "cd" / "abcd").write_bytes(b"x")
            self.assertIn(common / "lfs", _git_write_roots(worktree, "agent/unit", root / "repo"))



def _dispatch_repo(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    (repo / "seed").write_text("seed\n", encoding="utf-8")
    for command in (
        ("init", "-q"),
        ("add", "seed"),
        ("-c", "user.name=test", "-c", "user.email=test@example.test", "commit", "-qm", "init"),
    ):
        _ = subprocess.run(("git", *command), cwd=repo, capture_output=True, check=True)
    base = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    return repo, base


@requires_posix
class UnconfinedDispatchRefusalTests(unittest.TestCase):
    """A host that cannot prove a write fence does not run the unit unfenced unless told to (#1982).

    `backend_available` is patched to False so every job, macOS included,
    measures the host the issue reported: no backend, so no fence.
    """

    def _dispatch(self, root: Path, *, allow_unconfined: bool) -> tuple[dict[str, object], Path]:
        from five_issue_cases.capacity import no_stagger, ready
        from omh.coding.fanout import build_fanout_contract
        from omh.coding.fanout_artifacts import write_fanout_contract
        from omh.coding.fanout_dispatch import dispatch_fanout

        repo, base = _dispatch_repo(root)
        outside = root / "written-outside"
        argv = ["/bin/sh", "-c", f'printf x > "{outside}"']
        paths = OmhPaths(omh_home=root / "omh", hermes_home=root / "hermes")
        goal = "Prove the unit never runs outside a write fence silently."
        contract = write_fanout_contract(paths, build_fanout_contract(goal, [
            {"unit_id": "unit", "title": "unit", "owner": "codex", "file_scope": ["unit/"]},
        ]))
        environment = {"PATH": "/usr/bin:/bin", "HOME": str(root / "home")}
        with (
            mock.patch("omh.coding.fanout_confinement.backend_available", return_value=False),
            mock.patch("omh.coding.fanout_dispatch.build_dispatch_argv", lambda *_args, **_kwargs: list(argv)),
            mock.patch("omh.coding.fanout_dispatch.negotiate_session_capability", return_value=None),
            mock.patch("omh.coding.fanout_dispatch._SpawnStagger.reserve", no_stagger),
        ):
            summary = dispatch_fanout(
                paths, contract, goal_text=goal, repo_root=repo, base_sha=base, concurrency=1,
                runner=signal_safe_unit_runner, readiness=ready, max_retries=0, env=environment,
                allow_unconfined=allow_unconfined,
            )
        return summary, outside

    def test_the_unit_is_refused_and_never_spawned_by_default(self) -> None:
        from omh.commands.coding import _fanout_dispatch_exit_code

        with TemporaryDirectory() as temporary:
            summary, outside = self._dispatch(Path(temporary).resolve(), allow_unconfined=False)
            self.assertFalse(outside.exists(), "the unit ran with the operator's full write access")
        (unit,) = summary["units"]  # type: ignore[misc]
        self.assertEqual(unit["status"], "worktree_failed")
        self.assertEqual(unit["reason_code"], "filesystem_confinement_unavailable")
        self.assertEqual(unit["failure_kind"], "workspace_blocked")
        self.assertEqual(unit["unit_state"], "permission_blocked")
        self.assertIn("--allow-unconfined", unit["reason"])
        self.assertIn("sandbox_backend_unavailable", unit["reason"])
        self.assertEqual(unit["filesystem_confinement"]["reason_code"], "sandbox_backend_unavailable")
        self.assertFalse(unit["filesystem_confinement"]["unconfined_opt_in"])
        self.assertEqual(summary["unconfined_units"], [])
        self.assertEqual(_fanout_dispatch_exit_code(summary), 1)

    def test_the_operator_opt_in_runs_it_unfenced_and_says_so(self) -> None:
        with TemporaryDirectory() as temporary:
            summary, outside = self._dispatch(Path(temporary).resolve(), allow_unconfined=True)
            self.assertTrue(outside.exists())
        (unit,) = summary["units"]  # type: ignore[misc]
        self.assertNotEqual(unit.get("reason_code"), "filesystem_confinement_unavailable")
        self.assertFalse(unit["filesystem_confinement"]["enforced"])
        self.assertTrue(unit["filesystem_confinement"]["unconfined_opt_in"])
        self.assertEqual(summary["unconfined_units"], ["unit"])

    def test_a_verification_command_is_not_run_unfenced(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worktree = root / "worktree"
            worktree.mkdir()
            outside = root / "outside"
            command = shlex.join(["/bin/sh", "-c", f'printf x > "{outside}"'])
            with mock.patch("omh.coding.fanout_confinement.backend_available", return_value=False):
                implicit = _run_verification_command(command, worktree, signal_safe_unit_runner)
                passed = prepare_fanout_filesystem_confinement(
                    worktree, {"PATH": "/usr/bin:/bin"}, (("/bin/sh",),)
                )
                refused = _run_verification_command(
                    command, worktree, signal_safe_unit_runner, confinement=passed
                )
            self.assertEqual(implicit[0], "failed")
            self.assertEqual(refused[0], "failed")
            self.assertIn("--allow-unconfined", refused[1])
            self.assertFalse(outside.exists(), "a check ran with the operator's full write access")

            with mock.patch("omh.coding.fanout_confinement.backend_available", return_value=False):
                opted_in = prepare_fanout_filesystem_confinement(
                    worktree, {"PATH": "/usr/bin:/bin"}, (("/bin/sh",),), allow_unconfined=True
                )
                allowed = _run_verification_command(
                    command, worktree, signal_safe_unit_runner, confinement=opted_in
                )
            self.assertEqual(allowed[0], "passed")
            self.assertTrue(outside.exists())

    def test_the_opt_in_never_marks_an_enforced_fence(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree = Path(temporary) / "worktree"
            worktree.mkdir()
            with mock.patch("omh.coding.fanout_confinement.backend_available", return_value=False):
                refused = prepare_fanout_filesystem_confinement(worktree, {}, (("/bin/sh",),))
                opted_in = prepare_fanout_filesystem_confinement(
                    worktree, {}, (("/bin/sh",),), allow_unconfined=True
                )
        self.assertFalse(refused.unconfined_allowed)
        self.assertFalse(refused.receipt["unconfined_opt_in"])
        self.assertTrue(opted_in.unconfined_allowed)
        self.assertTrue(opted_in.receipt["unconfined_opt_in"])
        self.assertEqual(opted_in.receipt["reason_code"], "sandbox_backend_unavailable")



class AllowUnconfinedCliTests(unittest.TestCase):
    """The opt-in is off unless the operator types it, and it reaches the dispatcher on both commands."""

    def test_both_commands_thread_the_flag_and_default_it_off(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        from omh.commands.coding import cmd_coding_fanout_dispatch, cmd_coding_run
        from omh.commands.main import build_parser

        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo, _base = _dispatch_repo(root)
            goal = root / "goal.txt"
            goal.write_text("thread the opt-in", encoding="utf-8")
            paths = OmhPaths(omh_home=root / "omh", hermes_home=root / "hermes")
            from omh.coding.fanout import build_fanout_contract
            from omh.coding.fanout_artifacts import write_fanout_contract

            contract = write_fanout_contract(paths, build_fanout_contract("thread the opt-in", [
                {"unit_id": "unit", "title": "unit", "owner": "codex", "file_scope": ["unit/"]},
            ]))
            dispatch_args = ["coding", "fanout", "dispatch", str(contract["fanout_id"]), "--goal-file", str(goal),
                             "--repo-root", str(repo)]
            run_args = ["coding", "run", "--owner", "codex", "--goal", "thread the opt-in", "--repo-root", str(repo)]
            seen: list[object] = []

            def dispatch(*_args: object, **kwargs: object) -> dict[str, object]:
                seen.append(kwargs.get("allow_unconfined"))
                return {"dry_run": False, "units": []}

            for command, argv in ((cmd_coding_fanout_dispatch, dispatch_args), (cmd_coding_run, run_args)):
                for extra in ([], ["--allow-unconfined"]):
                    args = build_parser().parse_args([*argv, *extra])
                    with (
                        mock.patch("omh.commands.coding._paths", return_value=paths),
                        mock.patch("omh.coding.fanout_dispatch.dispatch_fanout", side_effect=dispatch),
                        redirect_stdout(StringIO()),
                    ):
                        _ = command(args)
        self.assertEqual(seen, [False, True, False, True])


if __name__ == "__main__":
    unittest.main()
