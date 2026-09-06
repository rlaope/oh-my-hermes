"""Signal-safe fanout dispatch: process groups, interrupts, and the reaper.

OMO shipped the incident this guards against: a launcher blocked in a
synchronous spawn died on SIGTERM and its engine reparented to pid 1, still
writing into the tree. The fanout runner now owns each unit as a process
group, an interrupt terminates the groups and records the batch honestly,
and the reaper terminates only marker-named pids — never by process name.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from omh.coding.fanout import build_fanout_contract
from omh.coding.fanout_artifacts import fanout_dispatch_summary_path, write_fanout_contract
from omh.coding import fanout_dispatch as fanout_dispatch_module
from omh.coding.fanout_dispatch import (
    dispatch_fanout,
    signal_safe_unit_runner,
    terminate_live_unit_groups,
)
from omh.coding.fanout_reap import reap_fanout_units
from omh.coding.inflight import read_inflight_markers, write_inflight_marker
from omh.system.local_store import read_json_object
from omh.system.paths import OmhPaths

posix_only = unittest.skipIf(os.name == "nt", "POSIX process groups required")

_GOAL = "signal safety drill"
_UNITS = [
    {"unit_id": "one", "title": "One", "owner": "codex", "file_scope": ["src/one/"]},
    {"unit_id": "two", "title": "Two", "owner": "codex", "file_scope": ["src/two/"]},
]


def _paths(tmp: str) -> OmhPaths:
    root = Path(tmp)
    return OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")


def _make_repo(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "seed.txt"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"],
        cwd=str(repo),
        check=True,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout.strip()
    return repo, sha


def _ready(paths, profile, **kwargs):
    return {"status": "ready", "profile": profile}


class SignalSafeRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        # The interrupt flag is process-global (one dispatch per process is
        # the supported shape); direct runner tests must not inherit a
        # sibling test's interrupt.
        from omh.coding.fanout_dispatch import _INTERRUPT_FLAG

        _INTERRUPT_FLAG.clear()

    @posix_only
    def test_unit_runs_as_its_own_group_leader(self) -> None:
        seen: dict[str, int] = {}

        def on_spawn(process) -> None:
            seen["pid"] = process.pid

        completed = signal_safe_unit_runner(
            [sys.executable, "-c", "import os; print(os.getpgid(0))"],
            text=True,
            capture_output=True,
            timeout=30,
            on_spawn=on_spawn,
        )
        self.assertEqual(completed.returncode, 0)
        child_pgid = int(completed.stdout.strip())
        # The child led its own group — not ours — so the whole group can be
        # terminated without touching the dispatcher.
        self.assertEqual(child_pgid, seen["pid"])
        self.assertNotEqual(child_pgid, os.getpgid(0))

    @posix_only
    def test_timeout_kills_the_whole_group_including_grandchildren(self) -> None:
        seen: dict[str, int] = {}

        def on_spawn(process) -> None:
            seen["pid"] = process.pid

        script = "import subprocess, time; subprocess.Popen(['sleep', '60']); time.sleep(60)"
        with self.assertRaises(subprocess.TimeoutExpired):
            signal_safe_unit_runner(
                [sys.executable, "-c", script],
                text=True,
                capture_output=True,
                timeout=0.5,
                on_spawn=on_spawn,
            )
        # The leader AND its grandchild are gone: signalling the dead group
        # raises, which is the proof the tree did not outlive the timeout.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.killpg(seen["pid"], 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        with self.assertRaises(ProcessLookupError):
            os.killpg(seen["pid"], 0)

    def test_on_output_hands_mid_run_stdout_snapshots_and_final_output_is_complete(self) -> None:
        """The mid-run stdout seam: every snapshot is a prefix of the final
        stdout (the reader drains continuously, the hook only ever sees what
        was captured so far), at least one snapshot arrives while the child
        still runs, and the returned CompletedProcess is byte-complete."""
        script = (
            "import time\n"
            "print('line-a', flush=True)\n"
            "time.sleep(2)\n"
            "print('line-b', flush=True)\n"
        )
        snapshots: list[str] = []
        poll = fanout_dispatch_module.UNIT_OUTPUT_POLL_SECONDS
        fanout_dispatch_module.UNIT_OUTPUT_POLL_SECONDS = 0.2
        try:
            completed = signal_safe_unit_runner(
                [sys.executable, "-c", script],
                text=True,
                capture_output=True,
                timeout=30,
                on_output=snapshots.append,
            )
        finally:
            fanout_dispatch_module.UNIT_OUTPUT_POLL_SECONDS = poll
        self.assertEqual(completed.returncode, 0)
        self.assertIn("line-a", completed.stdout)
        self.assertIn("line-b", completed.stdout)
        self.assertTrue(snapshots)
        for snapshot in snapshots:
            self.assertTrue(completed.stdout.startswith(snapshot))
        self.assertTrue(any("line-a" in snapshot and "line-b" not in snapshot for snapshot in snapshots))

    @posix_only
    def test_timeout_with_on_output_still_raises_and_kills_the_group(self) -> None:
        seen: dict[str, int] = {}

        def on_spawn(process) -> None:
            seen["pid"] = process.pid

        poll = fanout_dispatch_module.UNIT_OUTPUT_POLL_SECONDS
        fanout_dispatch_module.UNIT_OUTPUT_POLL_SECONDS = 0.2
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                signal_safe_unit_runner(
                    [sys.executable, "-c", "import time; time.sleep(60)"],
                    text=True,
                    capture_output=True,
                    timeout=0.5,
                    on_spawn=on_spawn,
                    on_output=lambda text: None,
                )
        finally:
            fanout_dispatch_module.UNIT_OUTPUT_POLL_SECONDS = poll
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.killpg(seen["pid"], 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        with self.assertRaises(ProcessLookupError):
            os.killpg(seen["pid"], 0)

    def test_raising_on_output_hook_never_kills_the_unit(self) -> None:
        def raising_hook(text: str) -> None:
            raise RuntimeError("telemetry-only hook must be swallowed")

        poll = fanout_dispatch_module.UNIT_OUTPUT_POLL_SECONDS
        fanout_dispatch_module.UNIT_OUTPUT_POLL_SECONDS = 0.2
        try:
            completed = signal_safe_unit_runner(
                [sys.executable, "-c", "import time; print('ok', flush=True); time.sleep(1)"],
                text=True,
                capture_output=True,
                timeout=30,
                on_output=raising_hook,
            )
        finally:
            fanout_dispatch_module.UNIT_OUTPUT_POLL_SECONDS = poll
        self.assertEqual(completed.returncode, 0)
        self.assertIn("ok", completed.stdout)

    @posix_only
    def test_terminate_live_unit_groups_reaps_a_registered_unit(self) -> None:
        import threading

        seen: dict[str, int] = {}
        started = threading.Event()

        def on_spawn(process) -> None:
            seen["pid"] = process.pid
            started.set()

        def run() -> None:
            try:
                signal_safe_unit_runner(
                    ["sleep", "60"], text=True, capture_output=True, timeout=60, on_spawn=on_spawn
                )
            except (subprocess.SubprocessError, OSError):
                pass

        worker = threading.Thread(target=run)
        worker.start()
        self.assertTrue(started.wait(timeout=10))
        terminated = terminate_live_unit_groups(grace=2)
        worker.join(timeout=10)
        self.assertIn(seen["pid"], terminated)
        with self.assertRaises(ProcessLookupError):
            os.killpg(seen["pid"], 0)


class InterruptedDispatchTests(unittest.TestCase):
    def _fixture(self, tmp: str):
        root = Path(tmp)
        paths = _paths(tmp)
        repo, sha = _make_repo(root)
        contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, _UNITS))
        return paths, repo, sha, contract

    def test_keyboard_interrupt_marks_unstarted_units_and_returns_the_summary(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._fixture(tmp)

            def runner(argv, **kwargs):
                if argv[0] == "git":
                    return subprocess.run(argv, **kwargs)
                raise KeyboardInterrupt

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                concurrency=1,
                runner=runner,
                readiness=_ready,
            )

            self.assertTrue(summary["interrupted"])
            statuses = {entry["unit_id"]: entry["status"] for entry in summary["units"]}
            # Both units surface in the rollup — nothing silently vanishes as
            # if it were never planned.
            self.assertEqual(set(statuses), {"one", "two"})
            # A unit a cancelled batch never spawned says exactly that. It is
            # not `failed` (nothing ran) and not the older undifferentiated
            # `interrupted` (which said nothing about whether a process had
            # started), so a resume knows there is nothing to preserve.
            self.assertEqual(set(statuses.values()), {"not_started_cancelled"})
            rollup = summary["cancellation"]
            self.assertEqual(sorted(rollup["never_started"]), ["one", "two"])
            self.assertEqual(rollup["cancelled"], [])
            self.assertEqual(rollup["outcome_unknown"], [])
            self.assertEqual(rollup["blocked_by_cancelled_dependency"], [])

    def test_system_exit_re_raises_after_the_summary_is_written(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._fixture(tmp)

            def runner(argv, **kwargs):
                if argv[0] == "git":
                    return subprocess.run(argv, **kwargs)
                raise SystemExit(143)

            with self.assertRaises(SystemExit):
                dispatch_fanout(
                    paths,
                    contract,
                    goal_text=_GOAL,
                    repo_root=repo,
                    base_sha=sha,
                    concurrency=1,
                    runner=runner,
                    readiness=_ready,
                )
            # The stored summary was written before the re-raise: a
            # supervisor observes the death it asked for AND the record
            # says the batch was cut short.
            stored = read_json_object(fanout_dispatch_summary_path(paths, contract["fanout_id"]))
            self.assertTrue(stored and stored.get("interrupted"))


class AsyncSignalTests(unittest.TestCase):
    @posix_only
    def test_sigterm_mid_flight_kills_groups_and_blocks_new_spawns(self) -> None:
        # A REAL signal, delivered while workers are mid-flight — the shape
        # the synchronous raise-inside-a-worker tests cannot reach. The
        # spawned group must die, no unit spawn may survive the signal, the
        # summary file must say interrupted, and the whole thing must settle
        # within the grace budget rather than the 1800s unit timeout.
        import threading as _threading

        from omh.coding.fanout_dispatch import signal_safe_unit_runner as safe_runner

        units = [
            {"unit_id": f"u{index}", "title": f"U{index}", "owner": "codex", "file_scope": [f"src/u{index}/"]}
            for index in range(3)
        ]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _paths(tmp)
            repo, sha = _make_repo(root)
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units))
            spawn_pids: list[int] = []
            first_spawn = _threading.Event()
            lock = _threading.Lock()

            def runner(argv, **kwargs):
                if argv[0] == "git":
                    return subprocess.run(argv, **kwargs)

                def on_spawn(process) -> None:
                    with lock:
                        spawn_pids.append(process.pid)
                    first_spawn.set()

                # Delegate to the real signal-safe runner with a long-lived
                # stand-in child so the signal lands mid-communicate.
                return safe_runner(
                    ["sleep", "30"], text=True, capture_output=True, timeout=60, on_spawn=on_spawn
                )

            def fire_sigterm() -> None:
                first_spawn.wait(timeout=30)
                time.sleep(0.2)
                os.kill(os.getpid(), signal.SIGTERM)

            killer = _threading.Thread(target=fire_sigterm)
            killer.start()
            started = time.monotonic()
            with self.assertRaises(SystemExit) as caught:
                dispatch_fanout(
                    paths,
                    contract,
                    goal_text=_GOAL,
                    repo_root=repo,
                    base_sha=sha,
                    concurrency=2,
                    runner=runner,
                    readiness=_ready,
                )
            elapsed = time.monotonic() - started
            killer.join(timeout=10)
            self.assertEqual(caught.exception.code, 143)
            # Settled within the grace budget, not the unit timeout.
            self.assertLess(elapsed, 25)
            stored = read_json_object(fanout_dispatch_summary_path(paths, contract["fanout_id"]))
            self.assertTrue(stored and stored.get("interrupted"))
            # Every spawned stand-in group is dead — a spawn that raced the
            # signal was terminated by the runner's register-then-check.
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if all(not _group_exists(pid) for pid in spawn_pids):
                    break
                time.sleep(0.05)
            for pid in spawn_pids:
                self.assertFalse(_group_exists(pid), f"group {pid} outlived the interrupt")


def _group_exists(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class FanoutReapTests(unittest.TestCase):
    @posix_only
    def test_reaps_only_marker_named_group_leaders(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, _UNITS))
            fanout_id = contract["fanout_id"]
            # A genuinely reparented orphan — the intermediary exits after
            # printing the leader pid, exactly the state a dead dispatcher
            # leaves behind. A direct child would linger as our own zombie
            # and read as alive after the kill.
            intermediary = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import subprocess; p = subprocess.Popen(['sleep', '60'], start_new_session=True,"
                    " stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); print(p.pid)",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            orphan_pid = int(intermediary.stdout.strip())
            try:
                write_inflight_marker(
                    paths,
                    fanout_id,
                    "one",
                    {"owner": "codex", "pid": str(orphan_pid), "started_at": ""},
                )
                report = reap_fanout_units(paths, fanout_id, grace=2)
                rows = {row["pid"]: row for row in report["candidates"]}
                self.assertEqual(rows[orphan_pid]["status"], "reaped")
                self.assertIn("SIGTERM", rows[orphan_pid]["signals_sent"])
                # The reaped unit's marker is cleared; presence-is-not-liveness
                # never had to be weakened to get here.
                remaining = [
                    entry
                    for entry in read_inflight_markers(paths, limit=50)
                    if entry.get("fanout_id") == fanout_id
                ]
                self.assertEqual(remaining, [])
            finally:
                try:
                    os.killpg(orphan_pid, signal.SIGKILL)
                except OSError:
                    pass

    @posix_only
    def test_refuses_pids_the_markers_do_not_name(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, _UNITS))
            bystander = subprocess.Popen(["sleep", "60"], start_new_session=True)
            try:
                report = reap_fanout_units(paths, contract["fanout_id"], pids=[bystander.pid], grace=1)
                row = report["candidates"][0]
                self.assertEqual(row["status"], "refused_not_marker_named")
                # The bystander survives: no marker, no kill, whatever the name.
                self.assertIsNone(bystander.poll())
            finally:
                bystander.kill()
                bystander.wait(timeout=10)

    @posix_only
    def test_a_recycled_pid_with_a_dead_group_is_already_gone_and_never_signalled(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, _UNITS))
            # Our own pid is alive but the GROUP named by it does not exist —
            # the recycled-pid shape after the original unit group fully
            # exited. Group-level liveness reports the truth (`already_gone`)
            # and nothing is ever signalled at the live bystander.
            own_pid = os.getpid()
            if os.getpgid(own_pid) == own_pid:
                self.skipTest("test process is itself a group leader")
            write_inflight_marker(
                paths,
                contract["fanout_id"],
                "one",
                {"owner": "codex", "pid": str(own_pid), "started_at": ""},
            )
            report = reap_fanout_units(paths, contract["fanout_id"], grace=1)
            row = report["candidates"][0]
            self.assertEqual(row["status"], "already_gone")
            self.assertNotIn("signals_sent", row)

    @posix_only
    def test_a_dead_leader_with_live_grandchildren_is_still_reapable(self) -> None:
        # The OMO incident shape: the leader exited, the engine below it
        # survives in the group. Leader-only liveness called this
        # `already_gone` and destroyed the marker while the orphan ran on;
        # group-level liveness reaps it.
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, _UNITS))
            fanout_id = contract["fanout_id"]
            probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import os, subprocess, sys\n"
                    "leader = subprocess.Popen([sys.executable, '-c', "
                    "\"import subprocess, sys; subprocess.Popen(['sleep', '60'], "
                    "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); sys.exit(0)\"], "
                    "start_new_session=True)\n"
                    "leader.wait()\n"
                    "print(leader.pid)\n",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            leader_pid = int(probe.stdout.strip())
            try:
                # The leader is dead; the group it led still exists.
                with self.assertRaises(ProcessLookupError):
                    os.kill(leader_pid, 0)
                write_inflight_marker(
                    paths,
                    fanout_id,
                    "one",
                    {"owner": "codex", "pid": str(leader_pid), "started_at": ""},
                )
                report = reap_fanout_units(paths, fanout_id, grace=2)
                row = report["candidates"][0]
                self.assertEqual(row["status"], "reaped")
            finally:
                try:
                    os.killpg(leader_pid, signal.SIGKILL)
                except OSError:
                    pass


if __name__ == "__main__":
    unittest.main()
