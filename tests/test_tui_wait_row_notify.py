"""The waiting row stands while a background process Hermes will wake the session for runs.

The owner's report of 2026-11-14: a `terminal(background=true, notify=true)`
ran for twelve minutes after the turn ended and no `✳ Waiting… (… · terminal)`
row showed. Hermes writes `processes.json` at the spawn (`ProcessRegistry`
`_write_checkpoint`, from `spawn_local`) and only afterwards sets
`notify_on_complete` on the session (`tools/terminal_tool_background.py`,
`spawn_background_process`), with no rewrite until the process exits. So the
checkpoint said `"notify_on_complete": false` for the whole run, and the TUI
took the process for one nobody would be told about. The `terminal` result
Hermes sent back says `"notify_on_complete": true`; the TUI now takes it from
there.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from test_tui_modes import SID, drawn, make_app
from omh.tui.background import PROCESSES_FILE
from omh.tui.gateway import Event
from omh.tui.panels import HudSnapshot

STORED = "local-2a4c083d5eee"
PROC = "proc_ef351977cfd7"
NOW = 1_794_644_600.0


def checkpoint_row(proc: str = PROC, **fields: object) -> dict:
    """The row Hermes' checkpoint holds for a `notify=true` process all its life: written at the spawn, before
    `notify_on_complete` was set (the owner's processes.json, 2026-11-14)."""
    row = {"session_id": proc, "command": "sleep 240; echo WAIT_PROBE_DONE", "pid": 41092, "pid_scope": "host",
           "host_start_time": None, "started_at": NOW - 169, "session_key": f"agent:main:local:dm:{STORED}",
           "parent_session_id": STORED, "notify_on_complete": False, "watch_patterns": []}
    row.update(fields)
    return row


def complete(result: object, name: str = "terminal", tool_id: str = "toolu_1") -> Event:
    return Event("tool.complete", SID, {"tool_id": tool_id, "name": name, "result": result})


STARTED = {"output": "Background process started", "session_id": PROC, "pid": 41092, "exit_code": 0, "error": None,
           "notify_on_complete": True}


class WaitingRowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app, _client = make_app(cols=120, rows=20, wall_clock=lambda: NOW)
        self.app.stored_id = STORED

    def checkpoint(self, *rows: dict) -> None:
        """A HUD read whose checkpoint lists `rows`, through the real reader."""
        from omh.tui.background import read_processes

        home = tempfile.mkdtemp()
        (Path(home) / PROCESSES_FILE).write_text(json.dumps(list(rows)), encoding="utf-8")
        processes = read_processes(home, STORED)
        snapshot = HudSnapshot(STORED, {"privacy": "metadata_only"}, 0.0, {}, processes, refreshes=10**6)
        self.app.hud = snapshot
        self.app._take_background(snapshot)  # what `_take_hud` does with a delivered read

    def waiting(self) -> str:
        return next((line for line in drawn(self.app) if "Waiting…" in line), "")

    def run_turn(self, *events: Event) -> None:
        self.app._on_event(Event("message.start", SID, {}))
        for event in events:
            self.app._on_event(event)
        self.app._on_event(Event("message.complete", SID, {"text": "done"}))

    def test_the_owners_run_shows_the_waiting_row(self) -> None:
        self.run_turn(Event("tool.start", SID, {"tool_id": "toolu_1", "name": "terminal", "args": {}}),
                      complete(STARTED))
        self.checkpoint(checkpoint_row())
        self.assertIsNotNone(self.app._pending_wait())
        self.assertIn("· terminal)", self.waiting())

    def test_a_result_that_arrives_after_the_read_still_counts(self) -> None:
        self.checkpoint(checkpoint_row())
        self.run_turn(complete(STARTED))
        self.assertIn("· terminal)", self.waiting())

    def test_without_notify_there_is_no_waiting_row(self) -> None:
        # Hermes will not wake the session: the info line's chip says OMH watches it, and nothing waits.
        self.run_turn(complete({**STARTED, "notify_on_complete": False}))
        self.checkpoint(checkpoint_row())
        self.assertIsNone(self.app._pending_wait())
        self.assertEqual(self.waiting(), "")

    def test_a_refused_notify_counts_as_none(self) -> None:
        # A subagent or a session that cannot take a completion: Hermes says false and why.
        self.run_turn(complete({**STARTED, "notify_on_complete": False, "subagent_note": "…"}))
        self.checkpoint(checkpoint_row())
        self.assertEqual(self.waiting(), "")

    def test_watch_patterns_in_the_result_wake_it_too(self) -> None:
        self.run_turn(complete({**STARTED, "notify_on_complete": False, "watch_patterns": ["READY"]}))
        self.checkpoint(checkpoint_row())
        self.assertIn("· terminal)", self.waiting())

    def test_another_tools_result_or_another_process_counts_for_nothing(self) -> None:
        self.run_turn(complete(STARTED, name="process_manage"), complete({**STARTED, "session_id": "proc_other"}))
        self.checkpoint(checkpoint_row())
        self.assertEqual(self.waiting(), "")

    def test_a_result_that_is_not_json_counts_for_nothing(self) -> None:
        self.run_turn(complete("Background process started"))
        self.checkpoint(checkpoint_row())
        self.assertEqual(self.waiting(), "")

    def test_a_woken_process_that_ends_is_not_offered_as_finished_unreported(self) -> None:
        # Hermes reports its end itself, so the row never asks Enter to tell the session.
        self.run_turn(complete(STARTED))
        self.checkpoint(checkpoint_row())
        self.checkpoint()
        self.assertIsNone(self.app.bg_done)

    def test_the_remembered_ids_are_bounded(self) -> None:
        from omh.tui.app import BG_WAKING_KEPT

        for index in range(BG_WAKING_KEPT + 5):
            self.app._take_waking({"name": "terminal", "result": {**STARTED, "session_id": f"proc_{index}"}})
        self.assertEqual(len(self.app.bg_waking), BG_WAKING_KEPT)
        self.assertNotIn("proc_0", self.app.bg_waking)
        self.assertIn(f"proc_{BG_WAKING_KEPT + 4}", self.app.bg_waking)


if __name__ == "__main__":
    unittest.main()
