"""#3014: a multi-call shim (mise) keeps the name it was launched by.

mise links every tool it manages (`codex`, `python3`, ...) to one `mise`
binary and picks the tool from argv[0]. The fence and the session probe
resolve each command to its real file; run by that path, argv[0] is `mise`,
mise runs as itself, and the unit or check exits 2. These tests stand in for
mise with a fake that answers by its own argv[0].
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from _local_package import load_local_package
from _platform_support import requires_posix

load_local_package()

from omh.coding.executor_readiness import (  # noqa: E402
    negotiate_session_capability,
    observe_session_binary,
    session_launch_path,
)
from omh.coding.fanout_confinement import (  # noqa: E402
    FanoutFilesystemConfinement,
    named_launch_argv,
    prepare_fanout_filesystem_confinement,
)
from omh.quality.cross_harness_adapter_sandbox import ChildContext  # noqa: E402

# Answers as the tool named by argv[0]; run as `mise`, it has lost the tool.
# Compiled, like mise itself: a `#!` script cannot see argv[0], because the
# kernel hands its interpreter the script path instead.
_FAKE_MISE_C = r"""
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv) {
    const char *slash = strrchr(argv[0], '/');
    const char *name = slash ? slash + 1 : argv[0];
    if (strcmp(name, "mise") == 0) { fprintf(stderr, "mise 2026.10.7: no tool for argv[0]\n"); return 2; }
    if (strcmp(name, "codex") == 0 && argc > 1 && strcmp(argv[1], "--version") == 0) { puts("codex-cli 0.200.0"); return 0; }
    if (strcmp(name, "codex") == 0 && argc > 1 && strcmp(argv[1], "exec") == 0 && argc > 2 && strcmp(argv[2], "--help") == 0) {
        puts("Usage: codex exec [--json] [resume]"); return 0; }
    printf("%s ran:", name);
    for (int i = 1; i < argc; i++) printf(" %s", argv[i]);
    putchar('\n');
    return 0;
}
"""
_CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")


def _shims(root: Path) -> Path:
    """A mise install: `<root>/installs/mise` and a shims dir of links to it."""
    assert _CC is not None
    installs = root / "installs"
    installs.mkdir()
    source = installs / "mise.c"
    source.write_text(_FAKE_MISE_C, encoding="utf-8")
    mise = installs / "mise"
    subprocess.run((_CC, "-o", str(mise), str(source)), check=True, capture_output=True)
    shims = root / "shims"
    shims.mkdir()
    for tool in ("codex", "python3"):
        (shims / tool).symlink_to(mise)
    return shims


def _fence(root: Path, shims: Path, selected: str = "bwrap") -> FanoutFilesystemConfinement:
    child = ChildContext(root, root, root, root, root, root / "request", root / "artifact", "fanout-filesystem-confinement")
    return FanoutFilesystemConfinement(
        selected=selected,
        roots=(root,),
        write_roots=(root,),
        write_literals=(),
        child=child,
        environment={"PATH": str(shims)},
        backend_digest="digest",
        executables={"codex": str((shims / "codex").resolve()), "python3": str((shims / "python3").resolve())},
        receipt={"enforced": True},
    )


def _after_separator(command: tuple[str, ...]) -> tuple[str, ...]:
    """What bwrap runs: everything after its `--`."""
    return command[command.index("--") + 1:]


@requires_posix
@unittest.skipUnless(os.path.isfile("/bin/bash") and _CC, "needs /bin/bash and a C compiler for the fake mise")
class NamedLaunchTests(unittest.TestCase):
    def test_a_resolved_shim_runs_as_the_tool_it_was_named(self) -> None:
        with TemporaryDirectory() as temporary:
            shims = _shims(Path(temporary).resolve())
            resolved = str((shims / "codex").resolve())

            bare = subprocess.run((resolved, "exec", "go"), capture_output=True, text=True, check=False)
            named = subprocess.run(named_launch_argv("codex", resolved, ("exec", "go")),
                                   capture_output=True, text=True, check=False)

            # The resolved path alone is the bug; the named launch is the fix.
            self.assertEqual(bare.returncode, 2, bare.stderr)
            self.assertEqual(named.returncode, 0, named.stderr)
            self.assertEqual(named.stdout.strip(), "codex ran: exec go")

    def test_arguments_pass_through_unchanged(self) -> None:
        with TemporaryDirectory() as temporary:
            shims = _shims(Path(temporary).resolve())
            argv = named_launch_argv("python3", str((shims / "python3").resolve()),
                                     ("-c", "a b", "$HOME", "", "--"))
            completed = subprocess.run(argv, capture_output=True, text=True, check=False)
            self.assertEqual(completed.stdout, "python3 ran: -c a b $HOME  --\n")

    def test_bash_env_is_not_sourced_into_the_launch(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            shims = _shims(root)
            marker = root / "sourced"
            rc = root / "bash_env"
            rc.write_text(f"touch {marker}\n", encoding="utf-8")
            argv = named_launch_argv("codex", str((shims / "codex").resolve()), ("x",))
            subprocess.run(argv, env={**os.environ, "BASH_ENV": str(rc)}, capture_output=True, check=False)
            self.assertFalse(marker.exists())

    def test_a_file_already_named_like_the_command_runs_directly(self) -> None:
        self.assertEqual(named_launch_argv("git", "/usr/bin/git", ("status",)), ("/usr/bin/git", "status"))
        self.assertEqual(named_launch_argv("/usr/bin/git", "/usr/bin/git", ()), ("/usr/bin/git",))

    def test_no_bash_falls_back_to_the_resolved_path(self) -> None:
        with mock.patch("omh.coding.fanout_confinement._NAMED_LAUNCH_SHELL", "/nonexistent/bash"):
            self.assertEqual(named_launch_argv("codex", "/opt/mise/bin/mise", ("exec",)),
                             ("/opt/mise/bin/mise", "exec"))


@requires_posix
@unittest.skipUnless(os.path.isfile("/bin/bash") and _CC, "needs /bin/bash and a C compiler for the fake mise")
class FencedShimCommandTests(unittest.TestCase):
    """The command bwrap would run, executed without bwrap: it must reach the tool, not mise."""

    def test_owner_cli_and_check_are_launched_under_their_names(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            shims = _shims(root)
            fence = _fence(root, shims)
            with mock.patch("omh.quality.cross_harness_adapter_sandbox._trusted_bwrap", return_value="/usr/bin/bwrap"):
                owner = fence.command(("codex", "exec", "--json", "go"))
                check = fence.command(("python3", "-m", "pytest"))
            assert owner is not None and check is not None
            for command, expected in ((owner, "codex ran: exec --json go"), (check, "python3 ran: -m pytest")):
                inner = _after_separator(command)
                completed = subprocess.run(inner, capture_output=True, text=True, check=False)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(completed.stdout.strip(), expected)

    def test_dispatcher_command_keeps_the_name_too(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            shims = _shims(root)
            fence = _fence(root, shims)
            with mock.patch("omh.quality.cross_harness_adapter_sandbox._trusted_bwrap", return_value="/usr/bin/bwrap"):
                command = fence.dispatcher_command(("python3", "-V"), path=str(shims))
            assert command is not None
            completed = subprocess.run(_after_separator(command), capture_output=True, text=True, check=False)
            self.assertEqual(completed.stdout.strip(), "python3 ran: -V")

    def test_the_fence_still_binds_the_real_file(self) -> None:
        # The resolved file stays what the fence reads and names; only argv[0] changes.
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            shims = _shims(root)
            fence = _fence(root, shims)
            with mock.patch("omh.quality.cross_harness_adapter_sandbox._trusted_bwrap", return_value="/usr/bin/bwrap"):
                command = fence.command(("codex", "exec", "go"))
            assert command is not None
            self.assertIn(str((shims / "codex").resolve()), _after_separator(command))


@requires_posix
@unittest.skipUnless(sys.platform == "darwin" and _CC, "sandbox-exec confinement is exercised on macOS")
class MacosFencedShimTests(unittest.TestCase):
    def test_a_shim_check_runs_inside_the_real_fence(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            shims = _shims(root)
            worktree = root / "worktree"
            worktree.mkdir()
            fence = prepare_fanout_filesystem_confinement(worktree, {"PATH": str(shims)}, (("python3", "-V"),))
            self.assertTrue(fence.receipt["enforced"], fence.receipt)
            command = fence.command(("python3", "-V"))
            assert command is not None
            completed = subprocess.run(command, cwd=worktree, env={**fence.command_environment(), "PATH": str(shims)},
                                       capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "python3 ran: -V")


@requires_posix
@unittest.skipUnless(_CC, "needs a C compiler for the fake mise")
class SessionProbeShimTests(unittest.TestCase):
    def test_launch_path_is_the_link_while_the_identity_is_the_real_file(self) -> None:
        with TemporaryDirectory() as temporary:
            shims = _shims(Path(temporary).resolve())
            env = {"PATH": str(shims)}
            identity = observe_session_binary("codex", env=env)
            assert identity is not None
            self.assertEqual(identity.resolved_path, str((shims / "codex").resolve()))
            self.assertEqual(session_launch_path("codex", identity, env=env), str(shims / "codex"))

    def test_a_link_that_moved_to_another_file_is_not_run(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            shims = _shims(root)
            env = {"PATH": str(shims)}
            identity = observe_session_binary("codex", env=env)
            assert identity is not None
            other = root / "other"
            other.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            other.chmod(0o755)
            (shims / "codex").unlink()
            (shims / "codex").symlink_to(other)
            self.assertEqual(session_launch_path("codex", identity, env=env), identity.resolved_path)

    def test_negotiation_reads_the_tool_version_not_mise(self) -> None:
        with TemporaryDirectory() as temporary:
            shims = _shims(Path(temporary).resolve())
            env = {**os.environ, "PATH": f"{shims}{os.pathsep}{os.environ.get('PATH', '')}"}
            capability = negotiate_session_capability("codex", "codex", env=env)
            assert capability is not None
            self.assertEqual(capability.version, "0.200.0", capability.reason)
            self.assertIsNotNone(capability.protocol, capability.reason)
            self.assertEqual(capability.binary_identity.resolved_path, str((shims / "codex").resolve()))


if __name__ == "__main__":
    unittest.main()
