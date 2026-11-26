"""`_stop_run` ends a run past its time: its whole process group on POSIX, its whole process tree on Windows (the
child is a launcher such as hermes.cmd, so killing the child alone leaves Hermes running). Platform and killer are
injected, so these run on every OS."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import omher_bridge as ob  # noqa: E402


class Proc:
    pid = 4242

    def __init__(self) -> None:
        self.events: list = []

    def kill(self) -> None:
        self.events.append("kill")

    def wait(self, timeout=None) -> None:
        self.events.append(("wait", timeout))


class StopRun(unittest.TestCase):
    def test_windows_ends_the_whole_tree_then_the_child(self):
        proc, trees = Proc(), []
        with mock.patch.object(ob.os, "killpg", create=True) as killpg:
            ob._stop_run(proc, windows=True, tree_killer=trees.append)
        self.assertEqual(trees, [4242])
        self.assertEqual(proc.events, ["kill", ("wait", ob.MCP_STOP_WAIT)])
        killpg.assert_not_called()

    def test_posix_signals_the_process_group_and_runs_no_taskkill(self):
        proc, trees, killed = Proc(), [], []
        with mock.patch.object(ob.os, "killpg", lambda pid, sig: killed.append((pid, sig)), create=True):
            ob._stop_run(proc, windows=False, tree_killer=trees.append)
        self.assertEqual(killed, [(4242, ob.signal.SIGKILL)])
        self.assertEqual((trees, proc.events), ([], [("wait", ob.MCP_STOP_WAIT)]))

    def test_the_tree_kill_is_one_fixed_system32_taskkill_with_no_shell(self):
        with mock.patch.dict(ob.os.environ, {"SystemRoot": "D:\\Win"}), mock.patch.object(ob.subprocess, "run") as run:
            ob._windows_kill_tree(4242)
        self.assertEqual(run.call_args.args[0], ["D:\\Win\\System32\\taskkill.exe", "/T", "/F", "/PID", "4242"])
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertIs(run.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_an_unset_or_relative_systemroot_falls_back_to_c_windows(self):
        for root in (None, "", "Windows", ".\\evil"):
            env = {k: v for k, v in ob.os.environ.items() if k != "SystemRoot"}
            if root is not None:
                env["SystemRoot"] = root
            with mock.patch.dict(ob.os.environ, env, clear=True):
                self.assertEqual(ob._windows_taskkill(), "C:\\Windows\\System32\\taskkill.exe", root)

    def test_a_missing_or_hung_taskkill_still_leaves_the_child_killed(self):
        for err in (FileNotFoundError("taskkill"), subprocess.TimeoutExpired("taskkill", 5)):
            proc = Proc()
            with mock.patch.object(ob.subprocess, "run", side_effect=err):
                ob._stop_run(proc, windows=True)
            self.assertEqual(proc.events, ["kill", ("wait", ob.MCP_STOP_WAIT)])


if __name__ == "__main__":
    unittest.main()
