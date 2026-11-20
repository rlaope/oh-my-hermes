"""The opt-in auto-resume shell-rc block (`omh.tui.shell_hook`).

Install appends one marked block at the end of the rc and remove gives the
file back byte for byte; the generated zsh and bash blocks parse, and a real
interactive zsh and bash under a pseudo-terminal run `omh auto-resume
shell-start` exactly once when the pending marker exists, never without it,
and never again in a nested shell.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import unittest
from collections.abc import Callable
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()

from omh.tui import live_sessions, shell_hook  # noqa: E402
from omh.tui.shell_hook import BEGIN, END, ShellHookError, install, remove, render_block  # noqa: E402


def _env(home: Path, **extra: str) -> dict[str, str]:
    return {"HOME": str(home), "USERPROFILE": str(home), **extra}


class RcPathTests(unittest.TestCase):
    def test_each_shell_reads_its_own_rc(self) -> None:
        home = Path("/h")
        self.assertEqual(shell_hook.rc_path("zsh", _env(home)), home / ".zshrc")
        self.assertEqual(shell_hook.rc_path("zsh", _env(home, ZDOTDIR="/z")), Path("/z/.zshrc"))
        self.assertEqual(shell_hook.rc_path("bash", _env(home)), home / ".bashrc")
        self.assertEqual(shell_hook.rc_path("powershell", _env(home), platform="linux"),
                         home / ".config" / "powershell" / "Microsoft.PowerShell_profile.ps1")
        self.assertEqual(shell_hook.rc_path("powershell", _env(home), platform="win32", which=lambda _n: "pwsh"),
                         home / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1")
        self.assertEqual(shell_hook.rc_path("powershell", _env(home), platform="win32", which=lambda _n: None),
                         home / "Documents" / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1")
        with self.assertRaises(ShellHookError):
            shell_hook.rc_path("fish", _env(home))

    def test_the_default_shell_comes_from_shell_or_windows(self) -> None:
        self.assertEqual(shell_hook.default_shell({"SHELL": "/bin/zsh"}, "darwin"), "zsh")
        self.assertEqual(shell_hook.default_shell({"SHELL": "/usr/bin/bash"}, "linux"), "bash")
        self.assertIsNone(shell_hook.default_shell({"SHELL": "/usr/bin/fish"}, "linux"))
        self.assertEqual(shell_hook.default_shell({}, "win32"), "powershell")


class InstallRemoveTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.omh = self.root / "omh"

    def _round_trip(self, shell: str, original: bytes | None) -> Path:
        environ = _env(self.home, ZDOTDIR=str(self.home))
        rc = shell_hook.rc_path(shell, environ, platform="linux")
        if original is not None:
            rc.parent.mkdir(parents=True, exist_ok=True)
            rc.write_bytes(original)
        result = install(shell, self.omh, environ, platform="linux")
        self.assertEqual((result.action, result.changed), ("installed", True))
        data = rc.read_bytes()
        self.assertTrue(data.rstrip(b"\r\n").endswith(END.encode()))
        self.assertEqual(data.count(BEGIN.encode()), 1)
        if original:
            self.assertTrue(data.startswith(original))
        again = install(shell, self.omh, environ, platform="linux")
        self.assertEqual((again.action, again.changed), ("unchanged", False))
        self.assertEqual(rc.read_bytes(), data)
        removed = remove(shell, environ, platform="linux")
        self.assertEqual(removed.action, "removed")
        if original is None:
            self.assertFalse(rc.exists())
        else:
            self.assertEqual(rc.read_bytes(), original)
        self.assertEqual(remove(shell, environ, platform="linux").action, "absent")
        return rc

    def test_round_trip_is_byte_exact_for_every_ending(self) -> None:
        for shell in shell_hook.SHELLS:
            for original in (b"export A=1\n", b"export A=1", b"", b"a\r\nb\r\n", b"a\r\nb", b"\n\n",
                             "# caf\u00e9\n".encode()):
                with self.subTest(shell=shell, original=original):
                    self._round_trip(shell, original)

    def test_a_crlf_rc_keeps_its_bytes_and_gets_an_lf_block_the_shells_parse(self) -> None:
        # A CR inside `then` or `fi` is a syntax error to zsh and bash: the block is LF, the person's bytes are theirs.
        for shell, binary in (("zsh", "zsh"), ("bash", "bash")):
            for original in (b"# preexisting comment\r\n", b"a=1\r\nb=2"):
                with self.subTest(shell=shell, original=original):
                    rc = self.home / (".zshrc" if shell == "zsh" else ".bashrc")
                    rc.write_bytes(original)
                    install(shell, self.omh, _env(self.home, ZDOTDIR=str(self.home)))
                    data = rc.read_bytes()
                    head = original if original.endswith(b"\r\n") else original + b"\r\n"
                    self.assertTrue(data.startswith(head + BEGIN.encode() + b"\n"), data)
                    self.assertNotIn(b"\r", data[len(head):])
                    path = shutil.which(binary)
                    if path is not None:
                        done = subprocess.run([path, "-n", str(rc)], capture_output=True, text=True, timeout=30)
                        self.assertEqual(done.returncode, 0, done.stderr)
                    self.assertEqual(install(shell, self.omh, _env(self.home, ZDOTDIR=str(self.home))).action,
                                     "unchanged")
                    remove(shell, _env(self.home, ZDOTDIR=str(self.home)))
                    self.assertEqual(rc.read_bytes(), original)

    def test_a_crlf_powershell_profile_gets_a_crlf_block(self) -> None:
        environ = _env(self.home)
        rc = shell_hook.rc_path("powershell", environ, platform="linux")
        rc.parent.mkdir(parents=True)
        rc.write_bytes(b"a\r\nb")
        install("powershell", self.omh, environ, platform="linux")
        data = rc.read_bytes()
        self.assertTrue(data.startswith(b"a\r\nb\r\n" + BEGIN.encode() + b"\r\n"))
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))

    def test_a_missing_rc_is_created_0644_and_removed_with_the_block(self) -> None:
        rc = self._round_trip("bash", None)
        install("bash", self.omh, _env(self.home))
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(rc.stat().st_mode), 0o644)

    @unittest.skipIf(os.name == "nt", "POSIX file modes")
    def test_the_file_mode_is_kept(self) -> None:
        rc = self.home / ".zshrc"
        rc.write_bytes(b"x\n")
        rc.chmod(0o600)
        install("zsh", self.omh, _env(self.home))
        self.assertEqual(stat.S_IMODE(rc.stat().st_mode), 0o600)
        remove("zsh", _env(self.home))
        self.assertEqual(stat.S_IMODE(rc.stat().st_mode), 0o600)

    def test_lines_added_after_the_block_survive_removal(self) -> None:
        rc = self.home / ".zshrc"
        rc.write_bytes(b"one\n")
        install("zsh", self.omh, _env(self.home))
        with rc.open("ab") as handle:
            handle.write(b"two\n")
        remove("zsh", _env(self.home))
        self.assertEqual(rc.read_bytes(), b"one\ntwo\n")

    def test_a_block_for_another_home_is_updated_in_place(self) -> None:
        rc = self.home / ".zshrc"
        rc.write_bytes(b"one")
        install("zsh", self.root / "old", _env(self.home))
        with rc.open("ab") as handle:
            handle.write(b"after\n")
        result = install("zsh", self.omh, _env(self.home))
        self.assertEqual(result.action, "updated")
        data = rc.read_bytes()
        self.assertIn(str(self.omh).encode(), data)
        self.assertNotIn(str(self.root / "old").encode() + b"/", data)
        self.assertTrue(data.endswith(b"after\n"))
        remove("zsh", _env(self.home))
        self.assertEqual(rc.read_bytes(), b"oneafter\n")

    def test_dry_run_writes_nothing(self) -> None:
        rc = self.home / ".bashrc"
        rc.write_bytes(b"x")
        result = install("bash", self.omh, _env(self.home), dry_run=True)
        self.assertEqual((result.action, result.dry_run), ("installed", True))
        self.assertIn(BEGIN, result.block)
        self.assertEqual(rc.read_bytes(), b"x")
        self.assertFalse((self.home / ".zshrc").exists())
        install("zsh", self.omh, _env(self.home), dry_run=True)
        self.assertFalse((self.home / ".zshrc").exists())
        install("bash", self.omh, _env(self.home))
        installed = rc.read_bytes()
        self.assertEqual(remove("bash", _env(self.home), dry_run=True).action, "removed")
        self.assertEqual(rc.read_bytes(), installed)

    def test_an_unterminated_block_is_refused(self) -> None:
        rc = self.home / ".zshrc"
        rc.write_bytes(f"x\n{BEGIN}\nstuff\n".encode())
        for action in (lambda: install("zsh", self.omh, _env(self.home)), lambda: remove("zsh", _env(self.home))):
            with self.assertRaises(ShellHookError):
                action()
        self.assertEqual(rc.read_bytes(), f"x\n{BEGIN}\nstuff\n".encode())

    @unittest.skipIf(os.name == "nt", "symbolic links need privileges on Windows")
    def test_a_symlink_inside_home_writes_its_target(self) -> None:
        dotfiles = self.home / "dotfiles"
        dotfiles.mkdir()
        target = dotfiles / "zshrc"
        target.write_bytes(b"mine\n")
        (self.home / ".zshrc").symlink_to(target)
        result = install("zsh", self.omh, _env(self.home))
        self.assertEqual(result.rc, target.resolve())
        self.assertTrue((self.home / ".zshrc").is_symlink())
        self.assertIn(BEGIN.encode(), target.read_bytes())
        remove("zsh", _env(self.home))
        self.assertEqual(target.read_bytes(), b"mine\n")

    @unittest.skipIf(os.name == "nt", "symbolic links need privileges on Windows")
    def test_a_symlink_outside_home_is_refused(self) -> None:
        outside = self.root / "elsewhere"
        outside.write_bytes(b"theirs\n")
        (self.home / ".bashrc").symlink_to(outside)
        with self.assertRaises(ShellHookError):
            install("bash", self.omh, _env(self.home))
        self.assertEqual(outside.read_bytes(), b"theirs\n")

    def test_hook_state_and_offer(self) -> None:
        environ = _env(self.home, SHELL="/bin/zsh")
        self.assertIsNone(shell_hook.offer(environ, platform="linux"))  # no rc yet: nothing to offer
        (self.home / ".zshrc").write_bytes(b"")
        self.assertEqual(shell_hook.offer(environ, platform="linux"), ("zsh", self.home / ".zshrc"))
        install("zsh", self.omh, environ)
        self.assertIsNone(shell_hook.offer(environ, platform="linux"))
        state = shell_hook.hook_state("zsh", environ)
        self.assertEqual((state["exists"], state["installed"]), (True, True))

    def test_a_path_that_cannot_be_quoted_into_a_shell_is_refused(self) -> None:
        with self.assertRaises(ShellHookError):
            render_block("bash", "/tmp/bad\nhome")


class BlockSyntaxTests(unittest.TestCase):
    def test_generated_blocks_parse(self) -> None:
        for shell, binary in (("zsh", "zsh"), ("bash", "bash")):
            path = shutil.which(binary)
            if path is None:
                continue
            for home in ("/tmp/omh", "/tmp/it's an omh home", "/tmp/$(touch x)"):
                with self.subTest(shell=shell, home=home), TemporaryDirectory() as tmp:
                    script = Path(tmp) / "block"
                    script.write_text("\n".join(render_block(shell, home)) + "\n", encoding="utf-8")
                    done = subprocess.run([path, "-n", str(script)], capture_output=True, text=True, timeout=30)
                    self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_marker_and_home_are_quoted_and_baked_in(self) -> None:
        for shell in shell_hook.SHELLS:
            text = "\n".join(render_block(shell, "/tmp/omh home"))
            self.assertIn("resume-pending", text)
            self.assertIn("live-pids", text)
            self.assertIn("auto-resume shell-start", text)
            self.assertIn("OMH_AUTO_RESUME_DONE", text)
            for guard in ("HERMES_SESSION_ID", "OMH_TUI_SESSION_FILE", "CI"):
                self.assertIn(guard, text)
        self.assertIn("ConsoleHost", "\n".join(render_block("powershell", "/x")))
        self.assertIn("zle-line-init", "\n".join(render_block("zsh", "/x")))
        self.assertNotIn("precmd", "\n".join(render_block("zsh", "/x")))
        self.assertIn("PROMPT_COMMAND", "\n".join(render_block("bash", "/x")))


@unittest.skipIf(os.name == "nt" or sys.platform == "win32", "pseudo-terminals are POSIX")
class InteractiveShellTests(unittest.TestCase):
    """A real interactive shell under a pty, with a fake `omh` that logs how it was called."""

    def _shell(self, shell: str, *, marker: bool, nested: bool = False, extra_env: dict[str, str] | None = None,
               before: str = "", expect_run: bool | None = None, enter: bool = False,
               prepare: Callable[[Path], None] | None = None, crlf: bool = False,
               typed: tuple[bytes, ...] = ()) -> tuple[list[str], str]:
        """`prepare(omh_home)` runs before the shell starts; `crlf` writes the person's rc lines with CRLF ends;
        `typed` lines are entered at the prompt after the hook ran. `self.last_root` is the temporary root."""
        import pty
        import select

        binary = shutil.which(shell)
        if binary is None:
            self.skipTest(f"{shell} is not installed")
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.last_root = root
        home, omh, bindir = root / "home", root / "omh", root / "bin"
        for directory in (home, omh / "tui", bindir):
            directory.mkdir(parents=True)
        log = root / "omh.log"
        fake = bindir / "omh"
        fake.write_text(f'#!/bin/sh\necho "$* DONE=$OMH_AUTO_RESUME_DONE" >> {str(log)!r}\n', encoding="utf-8")
        fake.chmod(0o755)
        if marker:
            (omh / "tui" / "resume-pending").touch()
        if prepare is not None:
            prepare(omh)
        if expect_run is None:
            expect_run = marker or prepare is not None
        rc_name = ".zshrc" if shell == "zsh" else ".bashrc"
        prompt = "PROMPT='READY> '\n" if shell == "zsh" else "PS1='READY> '\n"
        mine = (prompt + before).encode("utf-8")
        (home / rc_name).write_bytes(mine.replace(b"\n", b"\r\n") if crlf else mine)
        install(shell, omh, _env(home, ZDOTDIR=str(home)))
        argv = [binary, "-d", "-i"] if shell == "zsh" else [binary, "--noprofile", "--rcfile", str(home / rc_name), "-i"]
        environ = {
            "HOME": str(home), "ZDOTDIR": str(home), "PATH": f"{bindir}{os.pathsep}/usr/bin:/bin",
            "TERM": "xterm", "BASH_SILENCE_DEPRECATION_WARNING": "1", **(extra_env or {}),
        }
        # pty.fork gives the shell the pty as its controlling terminal, as a terminal emulator does.
        pid, master = pty.fork()
        if pid == 0:  # the child: become the shell
            try:
                os.chdir(home)
                os.execve(binary, argv, environ)
            finally:
                os._exit(127)
        output = bytearray()
        status: list[int] = []

        def exited() -> bool:
            if not status:
                done, code = os.waitpid(pid, os.WNOHANG)
                if done:
                    status.append(code)
            return bool(status)

        def pump(until, seconds: float) -> bool:
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if until():
                    return True
                ready, _w, _x = select.select([master], [], [], 0.05)
                if ready:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        exited()
                        return until()
                    output.extend(chunk)
            return until()

        def prompts() -> int:
            return output.count(b"READY> ")

        try:
            pump(lambda: prompts() >= 1, 15)
            if expect_run:
                pump(log.exists, 15)
            pump(lambda: False, 0.7)
            for line in typed:
                seen = prompts()
                os.write(master, line + b"\n")
                pump(lambda: prompts() > seen, 15)
            if enter:  # one more prompt, after the hook took itself out
                seen = prompts()
                os.write(master, b"\n")
                pump(lambda: prompts() > seen, 15)
            if nested:
                seen = prompts()
                os.write(master, " ".join(argv).encode() + b"\n")
                pump(lambda: prompts() >= seen + 1, 15)
                pump(lambda: False, 0.5)
                os.write(master, b"exit\n")
                pump(lambda: False, 0.3)
            os.write(master, b"exit\n")
            pump(exited, 15)
        finally:
            if not exited():
                os.kill(pid, 9)
                os.waitpid(pid, 0)
            os.close(master)
        lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        return lines, output.decode("utf-8", "replace")

    def test_marker_absent_runs_nothing(self) -> None:
        for shell in ("zsh", "bash"):
            with self.subTest(shell=shell):
                lines, output = self._shell(shell, marker=False)
                self.assertEqual(lines, [], output)

    def test_marker_present_runs_shell_start_once(self) -> None:
        for shell in ("zsh", "bash"):
            with self.subTest(shell=shell):
                lines, output = self._shell(shell, marker=True)
                self.assertEqual(len(lines), 1, output)
                self.assertTrue(lines[0].endswith("auto-resume shell-start DONE=1"), lines)
                self.assertIn("--omh-home", lines[0])

    def test_a_nested_shell_does_not_run_it_again(self) -> None:
        for shell in ("zsh", "bash"):
            with self.subTest(shell=shell):
                lines, output = self._shell(shell, marker=True, nested=True)
                self.assertEqual(len(lines), 1, output)

    def test_inside_a_session_or_on_ci_nothing_runs(self) -> None:
        for shell in ("zsh", "bash"):
            for name in ("OMH_AUTO_RESUME_DONE", "HERMES_SESSION_ID", "OMH_TUI_SESSION_FILE", "CI"):
                with self.subTest(shell=shell, guard=name):
                    lines, output = self._shell(shell, marker=True, extra_env={name: "1"}, expect_run=False)
                    self.assertEqual(lines, [], output)

    def test_a_tui_killed_outright_wakes_a_new_shell_before_anything_swept(self) -> None:
        # A real process records a live session through the store and is SIGKILLed: no exit code ran, so there is
        # no `resume-pending`; only its pid in `live-pids`, which no longer runs, can tell the new shell.
        script = (
            "import sys; sys.path.insert(0, sys.argv[1])\n"
            "from _local_package import load_local_package; load_local_package()\n"
            "from pathlib import Path\n"
            "from omh.tui.live_sessions import record_live\n"
            "record_live(Path(sys.argv[2]), 's-killed', sys.argv[3], sys.argv[3], {'TMUX_PANE': '%9'})\n"
            "print('recorded', flush=True)\n"
            "sys.stdin.read()\n"
        )
        tests_dir = str(Path(__file__).resolve().parent)

        def killed_tui(omh: Path) -> None:
            child = subprocess.Popen([sys.executable, "-c", script, tests_dir, str(omh), str(omh.parent)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            try:
                self.assertEqual(child.stdout.readline(), b"recorded\n")
            finally:
                child.kill()
                child.wait(timeout=10)
                child.stdin.close()
                child.stdout.close()
            self.assertEqual(child.returncode, -9)
            self.assertFalse((omh / "tui" / live_sessions.PENDING_MARKER).exists())
            pids = (omh / "tui" / live_sessions.LIVE_PIDS_FILE).read_text(encoding="ascii").split()
            self.assertIn(str(child.pid), pids)

        for shell in ("zsh", "bash"):
            with self.subTest(shell=shell):
                lines, output = self._shell(shell, marker=False, prepare=killed_tui)
                self.assertEqual(len(lines), 1, output)
                self.assertTrue(lines[0].endswith("auto-resume shell-start DONE=1"), lines)

    def test_live_pids_that_all_run_wake_nothing(self) -> None:
        def alive(omh: Path) -> None:
            (omh / "tui" / "live-pids").write_text(f"{os.getpid()} {os.getppid()}\n", encoding="ascii")

        def junk(omh: Path) -> None:  # not pids: skipped, never handed to `kill`
            (omh / "tui" / "live-pids").write_text("-1 0x10 $(touch x) 99999999999\n", encoding="ascii")

        for shell in ("zsh", "bash"):
            for label, prepare in (("alive", alive), ("junk", junk)):
                with self.subTest(shell=shell, live_pids=label):
                    lines, output = self._shell(shell, marker=False, prepare=prepare, expect_run=False)
                    self.assertEqual(lines, [], output)

    def test_a_dead_pid_among_live_ones_wakes_the_shell(self) -> None:
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait(timeout=30)

        def mixed(omh: Path) -> None:
            (omh / "tui" / "live-pids").write_text(f"{os.getpid()} {gone.pid}\n", encoding="ascii")

        for shell in ("zsh", "bash"):
            with self.subTest(shell=shell):
                lines, output = self._shell(shell, marker=False, prepare=mixed)
                self.assertEqual(len(lines), 1, output)

    def test_an_installed_crlf_rc_starts_and_runs_the_hook(self) -> None:
        for shell in ("zsh", "bash"):
            with self.subTest(shell=shell):
                lines, output = self._shell(shell, marker=True, crlf=True, before="export MINE=1\n")
                self.assertEqual(len(lines), 1, output)
                self.assertNotIn("parse error", output)
                self.assertNotIn("syntax error", output)

    def test_zsh_keeps_the_injected_line_out_of_history_and_the_persons_lines_in(self) -> None:
        history = "HISTFILE=$HOME/history\nSAVEHIST=50\nHISTSIZE=50\n"
        lines, output = self._shell("zsh", marker=True, before=history, typed=(b"echo mine",))
        self.assertEqual(len(lines), 1, output)
        saved = (self.last_root / "home" / "history").read_text(encoding="utf-8", errors="replace")
        self.assertIn("echo mine", saved)
        self.assertNotIn("shell-start", saved)

    def test_bash_keeps_an_existing_prompt_command(self) -> None:
        lines, output = self._shell("bash", marker=True, before="PROMPT_COMMAND='echo PC''RAN'\n", enter=True)
        self.assertEqual(len(lines), 1, output)
        self.assertGreaterEqual(output.count("PCRAN"), 2, output)  # still runs at the prompt after the hook left


if __name__ == "__main__":
    unittest.main()
