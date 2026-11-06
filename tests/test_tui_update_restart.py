"""A running OMH TUI notices `omh update` and offers to restart on the generation it installed.

`omh update` moves `<installer root>/current` to a new generation; the TUI,
which imports from the generation it started on, reads that link at most every
few seconds (`generation_watch`). A move is named on the info line (`restart
to update`) and asked about once, between turns, with Not now first. Restart
leaves with `RELAUNCH_EXIT` after creating the marker `omh` named, once no turn
runs and nothing typed waits, and `omh` opens the installed generation on the
same session. A TUI `omh` relaunched for an update offers `/gateway restart`
once when the shared gateway still runs the old OMH plugin code. Every case
drives an `App` over a fake link reader and recording clients: no installer
root, no gateway, no process.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_tui_gateway_restart import HOST, pick, restart_app
from test_tui_modes import make_app, notices, type_text
from omh.install.generation_hold import generation_of
from omh.install.self_update_state import (
    committed_generation,
    generation_entry,
    load_state,
    mark_activation,
    mark_switched,
    save_state,
    state_path,
)
from omh.tui import launch
from omh.tui.app import (
    GATEWAY_CANCEL_CHOICE,
    GATEWAY_RESTART_CHOICE,
    GATEWAY_RESTART_QUESTION,
    GATEWAY_UPDATE_LEAD,
    RELAUNCH_AFTER_DRAFT,
    RELAUNCH_AFTER_GATEWAY,
    RELAUNCH_AFTER_TURN,
    RELAUNCH_AFTER_WAIT,
    RELAUNCH_CANCELLED,
    RELAUNCH_FAILED,
    RELAUNCH_FAREWELL,
    RESTART_TO_UPDATE,
    SLOT_ARM_SECONDS,
    UPDATE_LATER_CHOICE,
    UPDATE_LATER_NOTICE,
    UPDATE_RESTART_CHOICE,
    UPDATE_RESTART_QUESTION,
    App,
    _Pending,
)
from omh.tui.gateway_restart import RestartImpact
from omh.tui.generation_watch import CHECK_SECONDS, GenerationWatch, watch_for
from omh.tui.keys import ESCAPE, Key
from omh.tui.style import Line
from omh.tui.transcript import NOTICE_WARN

ROOT = Path("/opt/omh-root")
OLD, NEW, NEWER = "20261101000000000000-aaaaaaaaaa", "20261106000000000000-bbbbbbbbbb", "20261107000000000000-cc"


def line_text(line: Line) -> str:
    return "".join(span.text for span in line)


class Pointer:
    """The `current` link as a test sets it: what `read_link` answers, and how often it was read."""

    def __init__(self, target: str = f"generations/{OLD}") -> None:
        self.target: str | None = target
        self.reads = 0
        self.activating = False

    def committed(self, root: Path) -> str:
        """What the update's state file says: the link's generation, or nothing while the update runs."""
        return "" if self.activating or self.target is None else Path(self.target).name

    def __call__(self, path: Path) -> str:
        self.reads += 1
        if path != ROOT / "current":
            raise AssertionError(path)
        if self.target is None:
            raise OSError("not a link")
        return self.target

    def move(self, name: str) -> None:
        self.target = f"generations/{name}"


def watched(app: App, pointer: Pointer, labels: dict[str, str] | None = None) -> GenerationWatch:
    watch = GenerationWatch(ROOT / "generations" / OLD, read_link=pointer, read_committed=pointer.committed)
    watch.label = lambda name: (labels or {}).get(name, name)  # type: ignore[method-assign]
    app.generation_watch = watch
    return watch


def update_app(tmp: str, *, busy: bool = False, relaunch: bool = True, cols: int = 120) -> tuple[App, Pointer, list[float]]:
    """A session past its launch, run by an `omh` that can relaunch it (the marker under `tmp`), watching `OLD`."""
    now = [100.0]
    environ = {launch.SESSION_FILE_ENV: os.path.join(tmp, "session")}
    if relaunch:
        environ[launch.RELAUNCH_FILE_ENV] = os.path.join(tmp, "relaunch")
    app, _client = make_app(busy=busy, cols=cols, environ=environ, clock=lambda: now[0])
    app.stored_id = "20261106_120000_abcdef"
    pointer = Pointer()
    watched(app, pointer, {NEW: "4.0.6 main@1a2b3c4d", NEWER: "4.0.7 main@9f8e7d6c"})
    return app, pointer, now


def tick(app: App, now: list[float], seconds: float = CHECK_SECONDS) -> None:
    """The loop's generation work for one step, `seconds` after the last."""
    now[0] += seconds
    app._watch_generation()
    app._offer_restart_when_due()
    app._relaunch_when_due()


def arm(now: list[float]) -> None:
    now[0] += SLOT_ARM_SECONDS


def question(app: App) -> dict:
    (asked,) = app.slot.params["questions"]  # type: ignore[union-attr]
    return asked


class GenerationWatchTests(unittest.TestCase):
    def test_it_reads_the_link_at_most_every_few_seconds_and_says_only_a_move(self) -> None:
        pointer = Pointer()
        watch = GenerationWatch(ROOT / "generations" / OLD, read_link=pointer, read_committed=pointer.committed)
        self.assertEqual((watch.root, watch.running), (ROOT, OLD))
        self.assertIsNone(watch.poll(0.0))  # its own: no move
        self.assertIsNone(watch.poll(CHECK_SECONDS - 0.1))
        self.assertEqual(pointer.reads, 1)  # not read again before it is due
        pointer.move(NEW)
        self.assertEqual(watch.poll(CHECK_SECONDS), NEW)
        self.assertIsNone(watch.poll(2 * CHECK_SECONDS))  # the same move is said once
        self.assertEqual(pointer.reads, 3)
        pointer.move(OLD)
        self.assertEqual(watch.poll(3 * CHECK_SECONDS), OLD)  # back on its own: a move too, which the TUI clears on

    def test_a_move_counts_only_once_the_update_that_made_it_finished(self) -> None:
        pointer = Pointer()
        watch = GenerationWatch(ROOT / "generations" / OLD, read_link=pointer, read_committed=pointer.committed)
        watch.poll(0.0)
        pointer.activating = True
        pointer.move(NEW)
        self.assertIsNone(watch.poll(CHECK_SECONDS))  # the re-entry still runs, and may yet move it back
        self.assertEqual(watch.seen, OLD)
        pointer.activating = False
        self.assertEqual(watch.poll(2 * CHECK_SECONDS), NEW)

    def test_an_update_that_fails_after_moving_the_pointer_is_never_said(self) -> None:
        pointer = Pointer()
        watch = GenerationWatch(ROOT / "generations" / OLD, read_link=pointer, read_committed=pointer.committed)
        watch.poll(0.0)
        pointer.activating = True
        pointer.move(NEW)
        self.assertIsNone(watch.poll(CHECK_SECONDS))
        pointer.activating = False
        pointer.move(OLD)
        self.assertIsNone(watch.poll(2 * CHECK_SECONDS))

    def test_the_state_file_names_a_finished_generation_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(committed_generation(root), "")  # none yet
            state_path(root).write_text(json.dumps({"active": {"id": NEW}, "activation_in_progress": None}))
            self.assertEqual(committed_generation(root), NEW)
            state_path(root).write_text(json.dumps({"active": {"id": OLD}, "activation_in_progress": {"candidate": NEW}}))
            self.assertEqual(committed_generation(root), "")
            state_path(root).write_text("{not json")
            self.assertEqual(committed_generation(root), "")

    def test_the_update_s_own_transaction_says_finished_only_at_its_last_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            previous, candidate = root / "generations" / OLD, root / "generations" / NEW
            (previous / "venv").mkdir(parents=True)
            (candidate / "venv").mkdir(parents=True)
            state = load_state(root, previous)
            state["active"] = generation_entry(previous)
            save_state(root, state)
            self.assertEqual(committed_generation(root), OLD)
            mark_activation(state, candidate, previous)
            save_state(root, state)
            self.assertEqual(committed_generation(root), "")  # the pointer moves after this
            mark_switched(state)
            save_state(root, state)
            self.assertEqual(committed_generation(root), "")  # the re-entry runs here
            state["activation_in_progress"] = None
            state["active"] = generation_entry(candidate)
            save_state(root, state)
            self.assertEqual(committed_generation(root), NEW)

    def test_a_link_that_cannot_be_read_is_no_move(self) -> None:
        pointer = Pointer()
        pointer.target = None
        watch = GenerationWatch(ROOT / "generations" / OLD, read_link=pointer, read_committed=pointer.committed)
        self.assertIsNone(watch.poll(0.0))
        self.assertEqual(watch.seen, OLD)

    def test_an_absolute_windows_junction_names_the_generation_too(self) -> None:
        pointer = Pointer(rf"\\?\C:\Users\me\omh\generations\{NEW}".replace("\\", "/"))
        watch = GenerationWatch(ROOT / "generations" / OLD, read_link=pointer, read_committed=pointer.committed)
        self.assertEqual(watch.poll(0.0), NEW)

    def test_the_label_is_the_version_and_commit_the_generation_records_else_its_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            generations = Path(tmp) / "generations"
            site = generations / NEW / "venv" / "lib" / "python3.11" / "site-packages"
            (site / "omh").mkdir(parents=True)
            (site / "oh_my_hermes-4.0.6.dist-info").mkdir()
            (generations / OLD / "venv").mkdir(parents=True)
            watch = GenerationWatch(generations / OLD)
            self.assertEqual(watch.label(NEW), "4.0.6")  # no archive commit recorded: the version alone
            self.assertEqual(watch.label(NEWER), NEWER)  # nothing recorded: the directory's name

    def test_only_a_process_on_an_installer_generation_is_watched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "generations" / OLD / "venv"
            venv.mkdir(parents=True)
            watch = watch_for(str(venv))
            self.assertIsNotNone(watch)
            self.assertEqual((watch.root, watch.running), (Path(tmp).resolve(), OLD))  # type: ignore[union-attr]
            self.assertIsNone(watch_for(str(Path(tmp) / ".venv")))  # a checkout, pip or the npm launcher's cache
            self.assertEqual(generation_of(venv), venv.resolve().parent)


class OfferTests(unittest.TestCase):
    def test_a_move_is_named_on_the_info_line_and_asked_once_with_not_now_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, pointer, now = update_app(tmp)
            tick(app, now)
            self.assertIsNone(app.slot)
            self.assertNotIn(RESTART_TO_UPDATE, line_text(app._info_line(120)))
            pointer.move(NEW)
            tick(app, now)
            self.assertIn(RESTART_TO_UPDATE, line_text(app._info_line(120)))
            asked = question(app)
            self.assertEqual(asked["question"], UPDATE_RESTART_QUESTION.format(label="4.0.6 main@1a2b3c4d"))
            self.assertEqual(asked["choices"], [UPDATE_LATER_CHOICE, UPDATE_RESTART_CHOICE])  # Enter alone: not now
            self.assertIsNone(app.exit_code)

    def test_not_now_or_esc_keeps_the_hint_says_how_and_asks_no_more(self) -> None:
        for answer in ("not now", "esc"):
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as tmp:
                app, pointer, now = update_app(tmp)
                pointer.move(NEW)
                tick(app, now)
                arm(now)
                if answer == "esc":
                    app._on_input(Key(ESCAPE))
                else:
                    pick(app, UPDATE_LATER_CHOICE)
                self.assertIsNone(app.slot)
                how = "quit and run `omh --resume 20261106_120000_abcdef`"
                self.assertIn(UPDATE_LATER_NOTICE.format(how=how, label="4.0.6 main@1a2b3c4d"), notices(app))
                for _ in range(5):
                    tick(app, now)
                self.assertIsNone(app.slot)  # nothing nags
                self.assertIsNone(app.exit_code)
                self.assertFalse(os.path.lexists(os.path.join(tmp, "relaunch")))
                self.assertIn(RESTART_TO_UPDATE, line_text(app._info_line(120)))

    def test_a_newer_generation_after_not_now_is_asked_about_once_more(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, pointer, now = update_app(tmp)
            pointer.move(NEW)
            tick(app, now)
            arm(now)
            pick(app, UPDATE_LATER_CHOICE)
            pointer.move(NEWER)
            tick(app, now)
            self.assertEqual(question(app)["question"], UPDATE_RESTART_QUESTION.format(label="4.0.7 main@9f8e7d6c"))

    def test_restart_leaves_with_the_relaunch_exit_after_creating_the_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, pointer, now = update_app(tmp)
            pointer.move(NEW)
            tick(app, now)
            arm(now)
            pick(app, UPDATE_RESTART_CHOICE)
            self.assertIsNone(app.exit_code)  # the next step leaves, not the key
            tick(app, now, 0.0)
            self.assertEqual(app.exit_code, launch.RELAUNCH_EXIT)
            self.assertTrue(launch.relaunch_requested(app.exit_code, Path(tmp) / "relaunch"))
            self.assertEqual(app.farewell, RELAUNCH_FAREWELL.format(label="4.0.6 main@1a2b3c4d"))

    def test_a_move_seen_during_a_turn_is_asked_once_it_ends(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, pointer, now = update_app(tmp, busy=True)
            pointer.move(NEW)
            tick(app, now)
            self.assertIsNone(app.slot)  # never into a running turn
            self.assertIn(RESTART_TO_UPDATE, line_text(app._info_line(120)))
            app.turn_pending = False
            tick(app, now, 0.0)
            self.assertEqual(question(app)["choices"], [UPDATE_LATER_CHOICE, UPDATE_RESTART_CHOICE])

    def test_restart_picked_waits_for_the_turn_then_for_what_was_typed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, pointer, now = update_app(tmp)
            pointer.move(NEW)
            tick(app, now)
            arm(now)
            pick(app, UPDATE_RESTART_CHOICE)
            app.turn_pending = True  # a turn started before the next step
            tick(app, now)
            tick(app, now)
            label = "4.0.6 main@1a2b3c4d"
            self.assertEqual(notices(app).count(RELAUNCH_AFTER_TURN.format(label=label)), 1)
            self.assertIsNone(app.exit_code)
            app.turn_pending = False
            type_text(app, "next prompt")
            tick(app, now)
            self.assertIn(RELAUNCH_AFTER_DRAFT.format(label=label), notices(app))
            self.assertIsNone(app.exit_code)
            app.composer.replace(0, len(app.composer.text), "")
            tick(app, now)
            self.assertEqual(app.exit_code, launch.RELAUNCH_EXIT)

    def test_restart_picked_waits_while_hermes_gateway_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, pointer, now = update_app(tmp)
            pointer.move(NEW)
            tick(app, now)
            arm(now)
            pick(app, UPDATE_RESTART_CHOICE)
            app.respawn_reason = "Hermes' gateway restarted"
            tick(app, now)
            self.assertIn(RELAUNCH_AFTER_GATEWAY.format(label="4.0.6 main@1a2b3c4d"), notices(app))
            self.assertIsNone(app.exit_code)

    def test_a_turn_about_to_start_or_a_compress_holds_the_question_and_the_restart(self) -> None:
        label = "4.0.6 main@1a2b3c4d"
        for name, value in (("auto_continue", ("20261106_120000_abcdef", 1e9)), ("hermes_next_due", 1e9)):
            with self.subTest(state=name), tempfile.TemporaryDirectory() as tmp:
                app, pointer, now = update_app(tmp)
                setattr(app, name, value)
                pointer.move(NEW)
                tick(app, now)
                self.assertIsNone(app.slot)  # not asked in the gap before that turn
                setattr(app, name, None)
                tick(app, now, 0.0)
                arm(now)
                pick(app, UPDATE_RESTART_CHOICE)
                setattr(app, name, value)  # came up after the answer: the restart waits for it
                tick(app, now)
                self.assertIn(RELAUNCH_AFTER_TURN.format(label=label), notices(app))
                self.assertIsNone(app.exit_code)
                setattr(app, name, None)
                tick(app, now)
                self.assertEqual(app.exit_code, launch.RELAUNCH_EXIT)
        with tempfile.TemporaryDirectory() as tmp, patch.object(App, "_compressing_since", return_value=1.0):
            app, pointer, now = update_app(tmp)
            pointer.move(NEW)
            tick(app, now)
            self.assertIsNone(app.slot)

    def test_a_session_switch_out_holds_the_restart_without_a_notice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(App, "_switching", return_value="switching") as out:
            app, pointer, now = update_app(tmp)
            pointer.move(NEW)
            tick(app, now)
            self.assertIsNone(app.slot)
            out.return_value = ""
            tick(app, now, 0.0)
            arm(now)
            pick(app, UPDATE_RESTART_CHOICE)
            out.return_value = "switching"
            before = list(notices(app))
            tick(app, now)
            self.assertEqual(notices(app), before)
            self.assertIsNone(app.exit_code)

    def test_work_the_session_waits_on_holds_the_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(App, "_pending_wait", return_value=None) as wait:
            app, pointer, now = update_app(tmp)
            pointer.move(NEW)
            wait.return_value = (5.0, 1, 0)
            tick(app, now)
            self.assertIsNone(app.slot)
            wait.return_value = None
            tick(app, now, 0.0)
            arm(now)
            pick(app, UPDATE_RESTART_CHOICE)
            wait.return_value = (5.0, 1, 0)
            tick(app, now)
            self.assertIn(RELAUNCH_AFTER_WAIT.format(label="4.0.6 main@1a2b3c4d"), notices(app))
            self.assertIsNone(app.exit_code)

    def test_a_shell_line_or_command_still_out_holds_the_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, pointer, now = update_app(tmp)
            app.pending["shell"] = _Pending("shell.exec", lambda result: None, command=object())
            pointer.move(NEW)
            tick(app, now)
            self.assertIsNone(app.slot)
            del app.pending["shell"]
            tick(app, now, 0.0)
            arm(now)
            pick(app, UPDATE_RESTART_CHOICE)
            app.pending["shell"] = _Pending("shell.exec", lambda result: None, command=object())
            tick(app, now)
            self.assertIn(RELAUNCH_AFTER_WAIT.format(label="4.0.6 main@1a2b3c4d"), notices(app))
            self.assertIsNone(app.exit_code)
            del app.pending["shell"]
            tick(app, now)
            self.assertEqual(app.exit_code, launch.RELAUNCH_EXIT)

    def test_a_side_answer_still_out_for_this_session_holds_the_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, pointer, now = update_app(tmp)
            app.sid = "sid-1"
            app.side_tasks["task"] = "sid-1"
            pointer.move(NEW)
            tick(app, now)
            self.assertIsNone(app.slot)
            app.side_tasks["task"] = "another-session"  # its view is gone already
            tick(app, now, 0.0)
            self.assertIsNotNone(app.slot)

    def test_an_open_pager_or_picker_is_not_taken_from_the_person(self) -> None:
        for name in ("pager", "picker", "model_picker", "launch_picker", "rewind_picker", "chains_open"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                app, pointer, now = update_app(tmp)
                setattr(app, name, True if name == "chains_open" else object())
                pointer.move(NEW)
                tick(app, now)
                self.assertIsNone(app.slot)
                setattr(app, name, False if name == "chains_open" else None)
                tick(app, now, 0.0)
                self.assertIsNotNone(app.slot)

    def test_plan_mode_leaves_with_the_tui_and_comes_back_in_the_new_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, pointer, now = update_app(tmp)
            app.plan_mode = True
            pointer.move(NEW)
            tick(app, now)
            arm(now)
            pick(app, UPDATE_RESTART_CHOICE)
            tick(app, now)
            self.assertEqual(app.exit_code, launch.RELAUNCH_EXIT)
            self.assertEqual(launch.relaunch_updated_value(Path(tmp) / "relaunch"), launch.UPDATED_PLAN)
        reopened, _client = make_app(environ={launch.UPDATED_ENV: launch.UPDATED_PLAN})
        self.assertTrue(reopened.plan_mode)
        plain, _client = make_app(environ={launch.UPDATED_ENV: launch.UPDATED_PLAIN})
        self.assertFalse(plain.plan_mode)

    def test_a_pointer_that_moved_back_while_the_question_was_open_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, pointer, now = update_app(tmp)
            pointer.move(NEW)
            tick(app, now)
            pointer.move(OLD)
            tick(app, now)
            arm(now)
            pick(app, UPDATE_RESTART_CHOICE)
            self.assertIn(RELAUNCH_CANCELLED, notices(app))
            tick(app, now)
            self.assertIsNone(app.exit_code)
            self.assertEqual(app.relaunch_label, "")

    def test_the_question_does_not_open_over_what_is_being_typed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, pointer, now = update_app(tmp)
            type_text(app, "half a thought")
            pointer.move(NEW)
            tick(app, now)
            self.assertIsNone(app.slot)
            self.assertEqual(app.update_asked, "")  # still to be asked
            self.assertIn(RESTART_TO_UPDATE, line_text(app._info_line(120)))
            app.composer.replace(0, len(app.composer.text), "")
            tick(app, now, 0.0)
            self.assertIsNotNone(app.slot)

    def test_nothing_is_asked_while_another_restart_or_question_is_under_way(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, pointer, now = update_app(tmp)
            app.respawn_reason = "Hermes' gateway restarted"
            pointer.move(NEW)
            tick(app, now)
            self.assertIsNone(app.slot)
            app.respawn_reason = ""
            tick(app, now)
            self.assertIsNotNone(app.slot)

    def test_an_update_rolled_back_onto_this_tui_clears_the_hint_and_the_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, pointer, now = update_app(tmp, busy=True)
            pointer.move(NEW)
            tick(app, now)
            app.turn_pending = False
            tick(app, now, 0.0)
            arm(now)
            pick(app, UPDATE_RESTART_CHOICE)
            app.turn_pending = True
            pointer.move(OLD)
            tick(app, now)
            self.assertIn(RELAUNCH_CANCELLED, notices(app))
            app.turn_pending = False
            tick(app, now)
            self.assertIsNone(app.exit_code)
            self.assertNotIn(RESTART_TO_UPDATE, line_text(app._info_line(120)))

    def test_a_tui_omh_cannot_relaunch_only_shows_the_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, pointer, now = update_app(tmp, relaunch=False)
            pointer.move(NEW)
            for _ in range(3):
                tick(app, now)
            self.assertIsNone(app.slot)
            self.assertIsNone(app.exit_code)
            self.assertIn(RESTART_TO_UPDATE, line_text(app._info_line(120)))

    def test_no_watch_off_an_installer_generation_asks_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, _pointer, now = update_app(tmp)
            app.generation_watch = None
            tick(app, now)
            self.assertIsNone(app.slot)
            self.assertEqual(app._update_notice(), ())

    def test_a_marker_that_cannot_be_created_ends_nothing_and_says_how(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, pointer, now = update_app(tmp)
            app.environ = {**app.environ, launch.RELAUNCH_FILE_ENV: os.path.join(tmp, "gone", "relaunch")}
            pointer.move(NEW)
            tick(app, now)
            arm(now)
            pick(app, UPDATE_RESTART_CHOICE)
            tick(app, now, 0.0)
            self.assertIsNone(app.exit_code)
            failed = RELAUNCH_FAILED.format(command="omh --resume 20261106_120000_abcdef", label="4.0.6 main@1a2b3c4d")
            self.assertIn(failed, notices(app, NOTICE_WARN))

    def test_the_loop_step_runs_the_watch(self) -> None:
        app, _old, _spawner, _started, now = restart_app()
        with tempfile.TemporaryDirectory() as tmp:
            app.environ = {**app.environ, launch.RELAUNCH_FILE_ENV: os.path.join(tmp, "relaunch")}
            pointer = Pointer()
            watched(app, pointer)
            pointer.move(NEW)
            app._step()
            self.assertEqual(question(app)["choices"], [UPDATE_LATER_CHOICE, UPDATE_RESTART_CHOICE])
            arm(now)
            pick(app, UPDATE_RESTART_CHOICE)
            app._step()
            self.assertEqual(app.exit_code, launch.RELAUNCH_EXIT)


class GatewayAfterUpdateTests(unittest.TestCase):
    def offered(self, *, stale: str | None, shared: bool = True, home: Path | None = Path("/h")) -> App:
        app, _old, _spawner, _started, _now = restart_app(impact=RestartImpact(home, HOST))
        app.shared_gateway = shared
        with patch("omh.maintenance.hermes_gateway.stale_bundle_version", return_value=stale):
            app._offer_gateway_after_update()
        return app

    def test_a_stale_shared_gateway_is_offered_its_restart_once_with_cancel_first(self) -> None:
        app = self.offered(stale="4.0.6")
        asked = question(app)
        self.assertEqual(asked["choices"], [GATEWAY_CANCEL_CHOICE, GATEWAY_RESTART_CHOICE])
        lines = asked["question"].splitlines()
        self.assertEqual((lines[0], lines[-1]), (GATEWAY_UPDATE_LEAD, GATEWAY_RESTART_QUESTION))

    def test_nothing_is_offered_for_a_gateway_already_on_the_new_code_its_own_or_unknown(self) -> None:
        for case, options in (("current", {"stale": None}), ("stdio", {"stale": "4.0.6", "shared": False}),
                              ("no record", {"stale": "4.0.6", "home": None})):
            with self.subTest(case=case):
                self.assertIsNone(self.offered(**options).slot)  # type: ignore[arg-type]

    def test_the_person_typed_restart_keeps_restart_first(self) -> None:
        app, _old, _spawner, _started, now = restart_app()
        type_text(app, "/gateway restart")
        from omh.tui.keys import ENTER
        app._on_input(Key(ENTER))
        self.assertEqual(question(app)["choices"], [GATEWAY_RESTART_CHOICE, GATEWAY_CANCEL_CHOICE])
        self.assertNotIn(GATEWAY_UPDATE_LEAD, question(app)["question"])

    def test_only_a_tui_omh_relaunched_for_an_update_offers_it_at_startup(self) -> None:
        from test_tui_respawn import ENVIRON, crashing

        for flag, calls in (("1", 1), ("", 0), ("0", 0)):
            with self.subTest(flag=flag), patch.object(App, "_offer_gateway_after_update") as offer:
                app, _old, _spawner, _now = crashing(environ={**ENVIRON, launch.UPDATED_ENV: flag})
                app.startup()
                self.assertEqual(offer.call_count, calls)


class LaunchMarkerTests(unittest.TestCase):
    def test_the_marker_and_the_exit_together_are_a_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "relaunch"
            self.assertFalse(launch.relaunch_requested(launch.RELAUNCH_EXIT, marker))
            self.assertTrue(launch.request_relaunch({launch.RELAUNCH_FILE_ENV: str(marker)}))
            self.assertTrue(launch.relaunch_requested(launch.RELAUNCH_EXIT, marker))
            self.assertFalse(launch.relaunch_requested(0, marker))
            self.assertFalse(launch.relaunch_requested(launch.CLOSED_EXIT, marker))

    def test_no_named_marker_is_no_request(self) -> None:
        self.assertFalse(launch.request_relaunch({}))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(launch.request_relaunch({launch.RELAUNCH_FILE_ENV: os.path.join(tmp, "gone", "x")}))

    def test_the_exit_code_stays_apart_from_the_others(self) -> None:
        self.assertNotIn(launch.RELAUNCH_EXIT, {0, 1, 2, 42, 130, launch.FALLBACK_EXIT, launch.CLOSED_EXIT})
        self.assertLess(launch.RELAUNCH_EXIT, 128)

    def test_the_environment_names_the_marker_only_when_asked_and_drops_an_inherited_one(self) -> None:
        base = {launch.RELAUNCH_FILE_ENV: "/stale/relaunch"}
        common = dict(python="/p", site="/s", omh_home=Path("/o"), fallback_sentinel=Path("/d/fallback"),
                      session_file=Path("/d/session"))
        self.assertNotIn(launch.RELAUNCH_FILE_ENV, launch.omh_tui_environment(base, **common))
        env = launch.omh_tui_environment(base, relaunch_file=Path("/d/relaunch"), **common)
        self.assertEqual(env[launch.RELAUNCH_FILE_ENV], str(Path("/d/relaunch")))

    def test_the_marker_carries_plan_mode_and_only_that(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "relaunch"
            environ = {launch.RELAUNCH_FILE_ENV: str(marker)}
            self.assertTrue(launch.request_relaunch(environ))
            self.assertEqual(launch.relaunch_updated_value(marker), launch.UPDATED_PLAIN)
            self.assertTrue(launch.request_relaunch(environ, plan_mode=True))
            self.assertEqual(launch.relaunch_updated_value(marker), launch.UPDATED_PLAN)
            self.assertEqual(launch.relaunch_updated_value(Path(tmp) / "absent"), launch.UPDATED_PLAIN)

    def test_the_gateway_child_never_sees_the_marker_or_the_updated_flag(self) -> None:
        from omh.tui.gateway import gateway_spawn
        from test_tui_respawn import ENVIRON

        spawn = gateway_spawn({**ENVIRON, launch.RELAUNCH_FILE_ENV: "/d/relaunch", launch.UPDATED_ENV: "1"})
        self.assertNotIn(launch.RELAUNCH_FILE_ENV, spawn.env)
        self.assertNotIn(launch.UPDATED_ENV, spawn.env)


if __name__ == "__main__":
    unittest.main()
