"""The OMH TUI's durable record of its sessions (`omh.tui.live_sessions`): how each one ended, and which a reopen may
run again.

Every test runs in its own temp OMH home with a fake environment; pid liveness
and the boot identity are injected, so no process is signalled and the
machine's own boot is never read.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time
import unittest
from unittest import mock

from _test_temp_root import make_test_tempdir
from omh.tui import live_sessions
from omh.tui.live_sessions import (
    LIVE_PIDS_FILE,
    LIVE_SESSIONS_FILE,
    LIVE_SESSIONS_SCHEMA,
    MAX_ENTRIES,
    PENDING_MARKER,
    TERMINAL_KEY_ENV,
    claim_resumable,
    end_state_for_exit,
    entries,
    pending,
    record_end,
    record_live,
    release_claim,
    terminal_key,
)

BOOT = "boot-1"
REAL_PID_ALIVE = live_sessions.pid_alive
REAL_BOOT_IDENTITY = live_sessions.boot_identity


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class LiveSessionsCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(make_test_tempdir("omh-live-sessions-")))
        self.omh_home = self.root / "omh"
        self.hermes_home = str(self.root / "hermes")
        self.project = self.root / "project"
        self.project.mkdir()
        self.alive: dict[int, bool] = {}  # pids the injected probe answers for; any other pid is alive
        self.boot = BOOT
        self.enterContext(mock.patch.object(live_sessions, "pid_alive", lambda pid: self.alive.get(pid, True)))
        self.enterContext(mock.patch.object(live_sessions, "boot_identity", lambda: self.boot))

    @property
    def store(self) -> Path:
        return self.omh_home / "tui" / LIVE_SESSIONS_FILE

    @property
    def marker(self) -> Path:
        return self.omh_home / "tui" / PENDING_MARKER

    def entries(self) -> list[dict]:
        return json.loads(self.store.read_text(encoding="utf-8"))["sessions"]

    def states(self) -> dict[str, str]:
        return {entry["session_id"]: entry["state"] for entry in self.entries()}

    def write(self, *entries: dict) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self.store.write_text(json.dumps({"schema_version": LIVE_SESSIONS_SCHEMA, "sessions": list(entries)}))

    def entry(self, session_id: str, state: str, *, pid: int = 4242, key: str = "", cwd: str = "",
              home: str | None = None, age: timedelta = timedelta(minutes=5), boot: str = BOOT) -> dict:
        return {
            "session_id": session_id, "hermes_home": home or self.hermes_home, "cwd": cwd, "terminal_key": key,
            "state": state, "pid": pid, "boot": boot, "updated_at": stamp(datetime.now(timezone.utc) - age),
        }

    @property
    def live_pids(self) -> Path:
        return self.omh_home / "tui" / LIVE_PIDS_FILE

    def as_pid(self, pid: int):
        """Run the next store calls as process `pid` (what `os.getpid` answers inside the store)."""
        return mock.patch.object(live_sessions.os, "getpid", return_value=pid)

    def claim(self, environ: dict | None = None, cwd: str = "", homes: tuple[str, ...] | None = None, **options):
        return claim_resumable(self.omh_home, hermes_homes=homes or (self.hermes_home,), cwd=cwd,
                               environ=environ or {}, **options)


class TerminalKeyTests(unittest.TestCase):
    def test_the_first_present_name_wins_in_contract_order(self) -> None:
        self.assertEqual(TERMINAL_KEY_ENV[0], "OMHER_TERMINAL_LINK")
        environ = {"TMUX_PANE": "%3", "ITERM_SESSION_ID": "w0t0p0:ABC", "CMUX_SURFACE_ID": "surf-1"}
        self.assertEqual(terminal_key(environ), "CMUX_SURFACE_ID=surf-1")
        self.assertEqual(terminal_key({"OMHER_TERMINAL_LINK": "abcdefgh23", **environ}),
                         "OMHER_TERMINAL_LINK=abcdefgh23")
        self.assertEqual(terminal_key({"TMUX_PANE": "%3"}), "TMUX_PANE=%3")
        self.assertEqual(terminal_key({}), "")

    def test_empty_non_printable_and_oversize_values_are_skipped(self) -> None:
        for bad in ("", "pane\x1b]0;x", "a\nb", "x" * 201):
            with self.subTest(value=bad[:12]):
                self.assertEqual(terminal_key({"CMUX_SURFACE_ID": bad, "TMUX_PANE": "%1"}), "TMUX_PANE=%1")
        self.assertEqual(terminal_key({"TMUX_PANE": "x" * 200}), "TMUX_PANE=" + "x" * 200)


class EndStateTests(unittest.TestCase):
    def test_a_signal_or_a_crash_drops_and_every_returned_code_closes(self) -> None:
        self.assertEqual(end_state_for_exit(129, True), "dropped")
        self.assertEqual(end_state_for_exit(None, False), "dropped")
        for code in (0, 1, 75, 130, 10):
            self.assertEqual(end_state_for_exit(code, False), "closed")


class RecordTests(LiveSessionsCase):
    def test_record_live_then_record_end_round_trips_with_a_private_file(self) -> None:
        environ = {"TMUX_PANE": "%7"}
        record_live(self.omh_home, "s1", self.hermes_home, str(self.project), environ)
        (entry,) = self.entries()
        self.assertEqual({key: entry[key] for key in ("session_id", "hermes_home", "cwd", "terminal_key", "state")},
                         {"session_id": "s1", "hermes_home": self.hermes_home, "cwd": str(self.project),
                          "terminal_key": "TMUX_PANE=%7", "state": "live"})
        self.assertEqual(entry["owners"], [{"pid": os.getpid(), "boot": BOOT, "terminal_key": "TMUX_PANE=%7"}])
        self.assertTrue(entry["updated_at"].endswith("Z"))
        self.assertEqual(json.loads(self.store.read_text())["schema_version"], LIVE_SESSIONS_SCHEMA)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.store.stat().st_mode), 0o600)
        self.assertFalse(self.marker.exists())
        record_end(self.omh_home, "s1", "closed")
        self.assertEqual(self.states(), {"s1": "closed"})
        self.assertFalse(self.marker.exists())

    def test_a_dropped_end_writes_the_marker(self) -> None:
        record_live(self.omh_home, "s1", self.hermes_home, "", {})
        record_end(self.omh_home, "s1", "dropped")
        self.assertEqual(self.states(), {"s1": "dropped"})
        self.assertTrue(self.marker.is_file())
        self.assertTrue(pending(self.omh_home))

    def test_moving_to_a_new_session_closes_the_previous_one_and_keeps_one_entry_per_id(self) -> None:
        record_live(self.omh_home, "s1", self.hermes_home, "", {})
        record_live(self.omh_home, "s2", self.hermes_home, "", {}, previous="s1")
        self.assertEqual([(e["session_id"], e["state"]) for e in self.entries()], [("s1", "closed"), ("s2", "live")])
        record_live(self.omh_home, "s1", self.hermes_home, "", {}, previous="s2")  # back to s1: moved last, live
        self.assertEqual([(e["session_id"], e["state"]) for e in self.entries()], [("s2", "closed"), ("s1", "live")])

    def test_an_end_or_a_previous_held_by_another_process_is_left_alone(self) -> None:
        self.write(self.entry("theirs", "live", pid=999_999))
        record_live(self.omh_home, "mine", self.hermes_home, "", {}, previous="theirs")
        record_end(self.omh_home, "theirs", "dropped")
        self.assertEqual(self.states(), {"theirs": "live", "mine": "live"})

    def test_bad_arguments_write_nothing(self) -> None:
        record_live(self.omh_home, "", self.hermes_home, "", {})
        record_live(self.omh_home, "s\x1b", self.hermes_home, "", {})
        record_live(self.omh_home, "s1", "", "", {})
        record_end(self.omh_home, "s1", "resumed")
        self.assertFalse(self.store.exists())

    def test_reads_that_find_no_store_create_nothing(self) -> None:
        self.assertFalse(pending(self.omh_home))
        self.assertIsNone(self.claim(cwd=str(self.project)))
        record_end(self.omh_home, "s1", "dropped")
        self.assertFalse((self.omh_home / "tui").exists())

    def test_at_most_64_entries_are_kept_newest_last(self) -> None:
        self.write(*(self.entry(f"old{index}", "dropped") for index in range(MAX_ENTRIES)))
        record_live(self.omh_home, "new", self.hermes_home, "", {})
        ids = [entry["session_id"] for entry in self.entries()]
        self.assertEqual(len(ids), MAX_ENTRIES)
        self.assertEqual((ids[0], ids[-1]), ("old1", "new"))

    def test_closed_and_resumed_entries_older_than_a_week_are_pruned(self) -> None:
        week = timedelta(days=7, hours=1)
        self.write(self.entry("c", "closed", age=week), self.entry("r", "resumed", age=week),
                   self.entry("d", "dropped", age=week), self.entry("fresh", "closed"))
        record_live(self.omh_home, "s", self.hermes_home, "", {})
        self.assertEqual(self.states(), {"d": "dropped", "fresh": "closed", "s": "live"})


class SweepTests(LiveSessionsCase):
    def test_a_dead_pid_is_swept_to_dropped_and_the_marker_appears(self) -> None:
        self.write(self.entry("gone", "live", pid=31337))
        self.alive[31337] = False
        self.assertTrue(pending(self.omh_home))
        self.assertEqual(self.states(), {"gone": "dropped"})
        self.assertTrue(self.marker.is_file())

    def test_a_changed_boot_is_swept_to_dropped_even_when_the_pid_answers(self) -> None:
        self.write(self.entry("rebooted", "live", pid=31337, boot="boot-0"))
        self.assertTrue(pending(self.omh_home))
        self.assertEqual(self.states(), {"rebooted": "dropped"})

    def test_unknown_liveness_stays_live(self) -> None:
        self.write(self.entry("maybe", "live", pid=31337, boot=""))  # pid answers alive (unknown), boot unknown
        self.assertFalse(pending(self.omh_home))
        self.assertEqual(self.states(), {"maybe": "live"})
        self.assertFalse(self.marker.exists())

    def test_numeric_boots_within_the_tolerance_are_one_boot(self) -> None:
        self.boot = "1700000010"
        self.write(self.entry("same", "live", pid=31337, boot="1700000000"),
                   self.entry("other", "live", pid=31338, boot="1690000000"))
        pending(self.omh_home)
        self.assertEqual(self.states(), {"same": "live", "other": "dropped"})

    def test_the_real_pid_probe_says_this_process_runs(self) -> None:
        self.assertTrue(REAL_PID_ALIVE(os.getpid()))
        self.assertTrue(REAL_PID_ALIVE(0))  # not a pid the store keeps: unknown, so alive
        self.assertIsInstance(REAL_BOOT_IDENTITY(), str)


class ClaimTests(LiveSessionsCase):
    def test_the_terminal_key_beats_the_directory(self) -> None:
        here = str(self.project)
        self.write(self.entry("by-key", "dropped", key="TMUX_PANE=%1", age=timedelta(hours=2)),
                   self.entry("by-cwd", "dropped", cwd=here))
        claimed = self.claim({"TMUX_PANE": "%1"}, cwd=here)
        self.assertEqual(claimed and claimed["session_id"], "by-key")
        self.assertEqual(claimed and claimed["state"], "resumed")
        self.assertEqual(self.states(), {"by-cwd": "dropped", "by-key": "resumed"})

    def test_the_directory_is_the_fallback_compared_by_realpath(self) -> None:
        link = self.root / "link"
        try:
            link.symlink_to(self.project, target_is_directory=True)
        except OSError:
            self.skipTest("no symlinks here")
        self.write(self.entry("older", "dropped", cwd=str(self.project), age=timedelta(hours=3)),
                   self.entry("newer", "dropped", cwd=str(link)))
        claimed = self.claim({"TMUX_PANE": "%9"}, cwd=str(self.project))
        self.assertEqual(claimed and claimed["session_id"], "newer")

    def test_no_directory_fallback_inside_omher(self) -> None:
        here = str(self.project)
        self.write(self.entry("by-cwd", "dropped", cwd=here))
        self.assertIsNone(self.claim({"TERM_PROGRAM": "omher"}, cwd=here))
        self.assertEqual(self.states(), {"by-cwd": "dropped"})
        claimed = self.claim({"TERM_PROGRAM": "otty"}, cwd=here)
        self.assertEqual(claimed and claimed["session_id"], "by-cwd")

    def test_refused_candidates(self) -> None:
        here = str(self.project)
        self.write(
            self.entry("other-home", "dropped", cwd=here, home=str(self.root / "elsewhere")),
            self.entry("closed", "closed", cwd=here),
            self.entry("resumed", "resumed", cwd=here),
            self.entry("too-old", "dropped", cwd=here, age=timedelta(hours=73)),
            self.entry("running", "live", cwd=here, pid=31337),
        )
        self.assertIsNone(self.claim(cwd=here))
        self.assertIsNone(self.claim(cwd=here, max_age_hours=72))
        claimed = self.claim(cwd=here, max_age_hours=80)
        self.assertEqual(claimed and claimed["session_id"], "too-old")

    def test_an_id_another_live_tui_holds_is_never_claimed(self) -> None:
        here = str(self.project)
        self.write(self.entry("s1", "dropped", cwd=here))
        record_live(self.omh_home, "s1", self.hermes_home, here, {})  # another reopen already runs it
        self.assertIsNone(self.claim(cwd=here))
        self.assertEqual(self.states(), {"s1": "live"})

    def test_a_claim_is_one_shot_and_clears_the_marker(self) -> None:
        here = str(self.project)
        self.write(self.entry("s1", "dropped", cwd=here))
        self.assertTrue(pending(self.omh_home))
        self.assertTrue(self.marker.exists())
        claimed = self.claim(cwd=here)
        self.assertEqual(claimed and claimed["session_id"], "s1")
        self.assertIsNone(self.claim(cwd=here))
        self.assertFalse(self.marker.exists())
        self.assertFalse(pending(self.omh_home))

    def test_the_marker_stays_while_another_dropped_session_remains(self) -> None:
        self.write(self.entry("a", "dropped", key="TMUX_PANE=%1"), self.entry("b", "dropped", key="TMUX_PANE=%2"))
        self.claim({"TMUX_PANE": "%1"})
        self.assertTrue(self.marker.exists())

    def test_the_hermes_home_is_compared_by_realpath(self) -> None:
        real = self.root / "hermes-real"
        real.mkdir()
        alias = self.root / "hermes-alias"
        try:
            alias.symlink_to(real, target_is_directory=True)
        except OSError:
            self.skipTest("no symlinks here")
        self.write(self.entry("s1", "dropped", key="TMUX_PANE=%1", home=str(alias)))
        claimed = self.claim({"TMUX_PANE": "%1"}, homes=(str(real),))
        self.assertEqual(claimed and claimed["session_id"], "s1")


class OwnersTests(LiveSessionsCase):
    """Two TUIs holding one session: the entry ends only when the last one leaves (R2 contract item 2)."""

    def test_a_second_owner_joins_and_the_first_owners_drop_keeps_the_session_live(self) -> None:
        here = str(self.project)
        with self.as_pid(1001):
            record_live(self.omh_home, "s1", self.hermes_home, here, {"TMUX_PANE": "%1"})
        with self.as_pid(1002):
            record_live(self.omh_home, "s1", self.hermes_home, here, {"TMUX_PANE": "%2"})
        (entry,) = self.entries()
        self.assertEqual([owner["pid"] for owner in entry["owners"]], [1001, 1002])
        with self.as_pid(1002):
            record_end(self.omh_home, "s1", "dropped")
        self.assertEqual(self.states(), {"s1": "live"})  # 1001 still holds it
        self.assertIsNone(self.claim({"TMUX_PANE": "%2"}, cwd=here))
        self.assertIsNone(self.claim({}, cwd=here))
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.live_pids.read_text(), "boot-1 1001\n")

    def test_the_last_owner_decides_how_the_entry_ends_and_whose_terminal_it_keeps(self) -> None:
        with self.as_pid(1001):
            record_live(self.omh_home, "s1", self.hermes_home, "", {"TMUX_PANE": "%1"})
        with self.as_pid(1002):
            record_live(self.omh_home, "s1", self.hermes_home, "", {"TMUX_PANE": "%2"})
        record_end(self.omh_home, "s1", "dropped", pid=1001)
        record_end(self.omh_home, "s1", "closed", pid=1002)
        (entry,) = self.entries()
        self.assertEqual((entry["state"], entry["terminal_key"], entry["owners"]), ("closed", "TMUX_PANE=%2", []))
        self.assertFalse(self.live_pids.exists())

    def test_the_last_owner_dropping_makes_it_claimable_by_that_owners_terminal(self) -> None:
        with self.as_pid(1001):
            record_live(self.omh_home, "s1", self.hermes_home, "", {"TMUX_PANE": "%1"})
        with self.as_pid(1002):
            record_live(self.omh_home, "s1", self.hermes_home, "", {"TMUX_PANE": "%2"})
        record_end(self.omh_home, "s1", "closed", pid=1002)
        record_end(self.omh_home, "s1", "dropped", pid=1001)
        self.assertIsNone(self.claim({"TMUX_PANE": "%2"}))
        claimed = self.claim({"TMUX_PANE": "%1"})
        self.assertEqual(claimed and claimed["session_id"], "s1")

    def test_an_end_by_a_pid_that_does_not_hold_the_session_changes_nothing(self) -> None:
        with self.as_pid(1001):
            record_live(self.omh_home, "s1", self.hermes_home, "", {})
        record_end(self.omh_home, "s1", "dropped", pid=1002)
        self.assertEqual(self.states(), {"s1": "live"})

    def test_moving_away_leaves_only_this_owner(self) -> None:
        with self.as_pid(1001):
            record_live(self.omh_home, "s1", self.hermes_home, "", {})
        with self.as_pid(1002):
            record_live(self.omh_home, "s1", self.hermes_home, "", {})
            record_live(self.omh_home, "s2", self.hermes_home, "", {}, previous="s1")
        self.assertEqual(self.states(), {"s1": "live", "s2": "live"})
        self.assertEqual([owner["pid"] for owner in self.entries()[0]["owners"]], [1001])

    def test_the_sweep_removes_a_dead_owner_and_drops_only_an_entry_left_with_none(self) -> None:
        with self.as_pid(1001):
            record_live(self.omh_home, "s1", self.hermes_home, "", {})
        with self.as_pid(1002):
            record_live(self.omh_home, "s1", self.hermes_home, "", {})
        self.alive[1001] = False
        self.assertFalse(pending(self.omh_home))
        self.assertEqual([owner["pid"] for owner in self.entries()[0]["owners"]], [1002])
        self.alive[1002] = False
        self.assertTrue(pending(self.omh_home))
        self.assertEqual(self.states(), {"s1": "dropped"})
        self.assertFalse(self.live_pids.exists())

    def test_an_entry_written_with_one_pid_reads_as_one_owner(self) -> None:
        self.write(self.entry("old", "live", pid=31337, key="TMUX_PANE=%4"))
        (entry,) = entries(self.omh_home)
        self.assertEqual(entry["owners"], [{"pid": 31337, "boot": BOOT, "terminal_key": "TMUX_PANE=%4"}])
        self.alive[31337] = False
        self.assertTrue(pending(self.omh_home))
        self.assertEqual(self.states(), {"old": "dropped"})


class LivePidsTests(LiveSessionsCase):
    """`live-pids`: every live owner's pid on one line, so a shell can see a vanished TUI (R2 contract item 1)."""

    def test_the_file_follows_the_live_owners_and_is_private(self) -> None:
        with self.as_pid(1001):
            record_live(self.omh_home, "s1", self.hermes_home, "", {})
        with self.as_pid(1002):
            record_live(self.omh_home, "s2", self.hermes_home, "", {})
        self.assertEqual(self.live_pids.read_bytes(), b"boot-1 1001 1002\n")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.live_pids.stat().st_mode), 0o600)
        record_end(self.omh_home, "s1", "closed", pid=1001)
        self.assertEqual(self.live_pids.read_bytes(), b"boot-1 1002\n")
        record_end(self.omh_home, "s2", "dropped", pid=1002)
        self.assertFalse(self.live_pids.exists())
        self.assertTrue(self.marker.exists())

    def test_a_reader_rewrites_a_stale_file_and_creates_nothing_without_a_store(self) -> None:
        self.assertFalse(pending(self.omh_home))
        self.assertFalse((self.omh_home / "tui").exists())
        with self.as_pid(1001):
            record_live(self.omh_home, "s1", self.hermes_home, "", {})
        self.live_pids.write_text("9 9 9\n")
        pending(self.omh_home)
        self.assertEqual(self.live_pids.read_text(), "boot-1 1001\n")

    def test_the_first_word_is_the_writers_boot_without_spaces_or_a_dash(self) -> None:
        # R3 (R2-B4): the shell compares the first word with Linux's boot id, so a pid a new boot reused cannot hide
        # a TUI the reboot ended. The store writes Linux's id verbatim; anything it cannot write as one word is `-`.
        for boot, word in (("8f1c-77 aa", "8f1c-77aa"), ("", "-"), ("bo\x01ot", "-"), ("bööt", "-"),
                           ("e3b0c442-98fc-1c14-9afb-f4c8996fb924", "e3b0c442-98fc-1c14-9afb-f4c8996fb924")):
            with self.subTest(boot=boot):
                self.boot = boot
                with self.as_pid(1001):
                    record_live(self.omh_home, "s1", self.hermes_home, "", {})
                self.assertEqual(self.live_pids.read_text(), f"{word} 1001\n")

    def test_after_a_reboot_the_file_names_the_new_boot_and_only_its_owners(self) -> None:
        with self.as_pid(1001):
            record_live(self.omh_home, "old", self.hermes_home, "", {})
        self.boot = "boot-2"  # the machine restarted; pid 1001 is a different process now (alive by default)
        with self.as_pid(2002):
            record_live(self.omh_home, "new", self.hermes_home, "", {})
        self.assertEqual(self.live_pids.read_text(), "boot-2 2002\n")
        self.assertEqual(self.states(), {"old": "dropped", "new": "live"})

    @unittest.skipUnless(hasattr(signal, "SIGKILL"), "SIGKILL is POSIX")
    def test_a_killed_tui_stays_named_in_the_file_for_a_shell_to_find(self) -> None:
        script = ("import sys, time; from pathlib import Path; from omh.tui import live_sessions as s; "
                  "s.record_live(Path(sys.argv[1]), 'killed', sys.argv[2], '', {}); print('up', flush=True); "
                  "time.sleep(60)")
        child = subprocess.Popen([sys.executable, "-c", script, str(self.omh_home), self.hermes_home],
                                 stdout=subprocess.PIPE, text=True)

        def kill_child() -> None:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)

        self.addCleanup(kill_child)
        self.assertEqual(child.stdout.readline().strip() if child.stdout else "", "up")
        if child.stdout:
            child.stdout.close()
        child.send_signal(signal.SIGKILL)
        child.wait(timeout=10)
        self.assertEqual(self.live_pids.read_text().split()[1:], [str(child.pid)])
        self.assertFalse(self.marker.exists())  # nothing swept yet: only live-pids can tell
        self.assertFalse(REAL_PID_ALIVE(child.pid))


class StrictKeysTests(LiveSessionsCase):
    """`strict_keys`: an unattended start never takes the same-folder drop another known terminal left."""

    def test_a_drop_from_another_known_terminal_is_refused_only_when_strict(self) -> None:
        here = str(self.project)
        self.write(self.entry("theirs", "dropped", key="TMUX_PANE=%1", cwd=here))
        self.assertIsNone(self.claim({"TMUX_PANE": "%2"}, cwd=here, strict_keys=True))
        self.assertEqual(self.states(), {"theirs": "dropped"})
        claimed = self.claim({"TMUX_PANE": "%2"}, cwd=here)
        self.assertEqual(claimed and claimed["session_id"], "theirs")

    def test_strict_still_takes_the_folder_when_either_key_is_unknown(self) -> None:
        here = str(self.project)
        self.write(self.entry("unkeyed", "dropped", cwd=here), self.entry("keyed", "dropped", key="TMUX_PANE=%1",
                                                                          cwd=here, age=timedelta(hours=1)))
        claimed = self.claim({"TMUX_PANE": "%2"}, cwd=here, strict_keys=True)
        self.assertEqual(claimed and claimed["session_id"], "unkeyed")
        claimed = self.claim({}, cwd=here, strict_keys=True)
        self.assertEqual(claimed and claimed["session_id"], "keyed")


class ReleaseClaimTests(LiveSessionsCase):
    """`release_claim`: a claim the launch could not open goes back to `dropped` (R3, R2-B3)."""

    def test_a_released_claim_is_dropped_again_and_rearms_the_marker(self) -> None:
        self.write(self.entry("s1", "dropped", key="TMUX_PANE=%1"))
        claimed = self.claim({"TMUX_PANE": "%1"})
        self.assertEqual(claimed and claimed["session_id"], "s1")
        self.assertFalse(self.marker.exists())
        self.assertTrue(release_claim(self.omh_home, "s1"))
        self.assertEqual(self.states(), {"s1": "dropped"})
        self.assertTrue(self.marker.exists())
        again = self.claim({"TMUX_PANE": "%1"})
        self.assertEqual(again and again["session_id"], "s1")

    def test_only_a_resumed_entry_is_released(self) -> None:
        self.write(self.entry("up", "live"), self.entry("done", "closed"))
        for session_id in ("up", "done", "missing", ""):
            with self.subTest(session_id=session_id):
                self.assertFalse(release_claim(self.omh_home, session_id))
        self.assertEqual(self.states(), {"up": "live", "done": "closed"})

    def test_without_a_store_nothing_is_created(self) -> None:
        self.assertFalse(release_claim(self.omh_home, "s1"))
        self.assertFalse((self.omh_home / "tui").exists())


class ReaderTests(LiveSessionsCase):
    """`entries`: the read-only view `omh auto-resume status` shows."""

    def test_it_reads_without_writing_and_marks_a_live_entry_whose_owners_are_gone(self) -> None:
        self.write(self.entry("gone", "live", pid=31337), self.entry("up", "live", pid=31338),
                   self.entry("d", "dropped"))
        self.alive[31337] = False
        before = self.store.read_bytes()
        rows = entries(self.omh_home)
        self.assertEqual([(row["session_id"], row["state"], row["gone"]) for row in rows],
                         [("gone", "live", True), ("up", "live", False), ("d", "dropped", False)])
        self.assertEqual(self.store.read_bytes(), before)
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.live_pids.exists())
        rows[0]["owners"].clear()
        self.assertEqual(len(entries(self.omh_home)[0]["owners"]), 1)  # a copy

    def test_nothing_to_read_is_an_empty_list(self) -> None:
        self.assertEqual(entries(self.omh_home), [])
        self.assertFalse((self.omh_home / "tui").exists())


class DamagedStoreTests(LiveSessionsCase):
    def test_corrupt_wrong_schema_and_oversize_files_read_as_empty(self) -> None:
        self.store.parent.mkdir(parents=True)
        for content in ("{not json", "[]", json.dumps({"schema_version": "other/v9", "sessions": []}),
                        json.dumps({"schema_version": LIVE_SESSIONS_SCHEMA, "sessions": {"a": 1}}),
                        "[" * 100_000, " " * (live_sessions.MAX_FILE_BYTES + 1)):
            with self.subTest(content=content[:20]):
                self.store.write_text(content)
                self.assertFalse(pending(self.omh_home))
                self.assertIsNone(self.claim(cwd=str(self.project)))
                record_live(self.omh_home, "s1", self.hermes_home, "", {})
                self.assertEqual(self.states(), {"s1": "live"})

    def test_malformed_entries_are_dropped_and_the_rest_kept(self) -> None:
        good = self.entry("good", "dropped", key="TMUX_PANE=%1")
        self.write({"session_id": 3}, {**good, "session_id": "bad", "state": "weird"}, {**good, "pid": True}, good)
        claimed = self.claim({"TMUX_PANE": "%1"})
        self.assertEqual(claimed and claimed["session_id"], "good")

    def test_a_symlinked_store_is_not_followed(self) -> None:
        target = self.root / "elsewhere.json"
        target.write_text(json.dumps({"schema_version": LIVE_SESSIONS_SCHEMA,
                                      "sessions": [self.entry("s1", "dropped", key="TMUX_PANE=%1")]}))
        self.store.parent.mkdir(parents=True)
        try:
            self.store.symlink_to(target)
        except OSError:
            self.skipTest("no symlinks here")
        self.assertIsNone(self.claim({"TMUX_PANE": "%1"}))
        record_live(self.omh_home, "s2", self.hermes_home, "", {})
        self.assertFalse(self.store.is_symlink())  # replaced by the store's own file, the target untouched
        self.assertIn('"s1"', target.read_text())
        self.assertEqual(self.states(), {"s2": "live"})

    def test_an_unwritable_home_never_raises(self) -> None:
        blocker = self.root / "file-not-dir"
        blocker.write_text("x")
        record_live(blocker, "s1", self.hermes_home, "", {})
        record_end(blocker, "s1", "dropped")
        self.assertFalse(pending(blocker))
        self.assertIsNone(claim_resumable(blocker, hermes_homes=(self.hermes_home,), cwd="", environ={}))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFOs are POSIX")
    def test_a_fifo_at_any_store_name_never_blocks_and_is_never_opened(self) -> None:
        """A FIFO at the store, the marker, `live-pids` or the lock: every call returns within the lock bound (in a
        child, so a hang fails the test instead of stalling it), and a FIFO at a data name is replaced by rename, never opened."""
        names = (LIVE_SESSIONS_FILE, PENDING_MARKER, LIVE_PIDS_FILE, live_sessions.LOCK_FILE)
        script = ("import sys; from pathlib import Path; from omh.tui import live_sessions as s; h = Path(sys.argv[1]); "
                  "s.record_live(h, 'n', sys.argv[2], '', {}); s.record_end(h, 'n', 'dropped'); s.pending(h); "
                  "s.claim_resumable(h, hermes_homes=[sys.argv[2]], cwd='', environ={}); s.entries(h)")
        for name in names:
            with self.subTest(name=name):
                home = self.root / f"fifo-{name}"
                (home / "tui").mkdir(parents=True)
                if name in (PENDING_MARKER, LIVE_PIDS_FILE):
                    (home / "tui" / LIVE_SESSIONS_FILE).write_text(json.dumps({
                        "schema_version": LIVE_SESSIONS_SCHEMA,
                        "sessions": [self.entry("d", "dropped"), self.entry("l", "live", pid=os.getpid(), boot="")]}))
                os.mkfifo(home / "tui" / name)
                started = time.monotonic()
                try:
                    done = subprocess.run([sys.executable, "-c", script, str(home), self.hermes_home], timeout=8,
                                          capture_output=True, text=True)
                except subprocess.TimeoutExpired:
                    self.fail(f"a FIFO at {name} blocked the store")
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertLess(time.monotonic() - started, 8)
                path = home / "tui" / name
                if name == live_sessions.LOCK_FILE:
                    self.assertTrue(stat.S_ISFIFO(os.lstat(path).st_mode))  # refused: nothing locked, nothing written
                    self.assertFalse((home / "tui" / LIVE_SESSIONS_FILE).exists())
                else:
                    self.assertTrue(stat.S_ISREG(os.lstat(path).st_mode), name)  # replaced by rename, never opened

    def test_a_directory_at_the_lock_name_gives_up_without_raising(self) -> None:
        (self.omh_home / "tui" / live_sessions.LOCK_FILE).mkdir(parents=True)
        record_live(self.omh_home, "s1", self.hermes_home, "", {})
        self.assertFalse(self.store.exists())
        self.assertFalse(pending(self.omh_home))

    def test_lock_contention_gives_up_within_the_bounded_wait(self) -> None:
        self.assertEqual(live_sessions.LOCK_WAIT_SECONDS, 2.0)
        record_live(self.omh_home, "s1", self.hermes_home, "", {})
        with live_sessions._locked(self.omh_home / "tui") as held:
            if not held:
                self.skipTest("no file lock on this platform")
            started = time.monotonic()
            record_end(self.omh_home, "s1", "dropped")
            self.assertLess(time.monotonic() - started, 3.0)
        self.assertEqual(self.states(), {"s1": "live"})  # given up: nothing written
        record_end(self.omh_home, "s1", "dropped")
        self.assertEqual(self.states(), {"s1": "dropped"})


if __name__ == "__main__":
    unittest.main()
