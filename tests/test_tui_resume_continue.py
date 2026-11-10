"""A resumed session with work left goes on by itself in the OMH TUI.

`omh --resume <id>` (the launch's `session.resume`) and `/resume` or the
session picker (`_on_session_resumed`) open a stored session. When the turn
it left was one Hermes interrupted itself, as the TUI that saw it end wrote
under the OMH home (`turn_ends`), or when the session holds an open dag-ulw
run a turn would move with no node running (`dag_open_run_nudge.waiting_run`),
the TUI says why and sends `continue` after `AUTO_CONTINUE_SECONDS`, the way
#2557 goes on with a turn Hermes interrupted while it watched. Never for the
person's own stop, a session with a turn running, one Hermes resubmits itself
(`auto_continue`), a draft or an open question. The last class reads a real
run record in a temporary home over a recording client: no gateway runs.
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from _delegation_state import PARENT, homes
from test_dag_open_run_nudge import stored
from test_dag_tool import node
from test_tui_app import FakePoller, ScriptedTerminal
from test_tui_gateway_recovery import HERMES_STOPPED, sent, streaming, wait_out
from test_tui_modes import SID, RecordingClient, answer, make_app, notices, type_text
from omh.plugin_bundle.omh.dag_open_run_nudge import RESUMABLE_REASONS, waiting_run
from omh.tui.app import (
    AUTO_CONTINUE_ESCAPED,
    AUTO_CONTINUE_HELD_NOTICE,
    AUTO_CONTINUE_LIMIT,
    AUTO_CONTINUE_SECONDS,
    RESUME_CONTINUE_NOTICE,
    RESUME_WHY_INTERRUPTED,
    App,
    resume_run_why,
)
from omh.tui.gateway import Event
from omh.tui.keys import ENTER, ESCAPE, Key
from omh.tui.turn_ends import (
    MAX_SESSIONS,
    TURN_DONE,
    TURN_INTERRUPTED,
    TURN_OPEN,
    TURN_STOPPED,
    read_turn_end,
    record_turn_end,
    turn_ends_path,
)

STORED = "20261105_010101_resumed"


def resuming(why: str) -> str:
    return RESUME_CONTINUE_NOTICE.format(why=why, seconds=f"{AUTO_CONTINUE_SECONDS:g}")


class ResumeClient(RecordingClient):
    """Answers the launch's blocking `session.resume` with `resumed`."""

    def __init__(self, resumed: dict) -> None:
        super().__init__()
        self.resumed = resumed

    def call(self, method: str, params: dict, timeout: float = 30.0, cancel: object = None) -> dict:
        self.calls.append((method, params))
        return self.resumed


def answered(stored_id: str = STORED, **extra: object) -> dict:
    return {"session_id": SID, "stored_session_id": stored_id, "info": {"model": "m", "cwd": "/p"}, "messages": [
        {"role": "user", "text": "build the feature"}, {"role": "tool", "name": "terminal", "context": "make"}],
        **extra}


def launched(omh_home: Path, *, run: tuple[str, str, list[str]] | None = None, stored_id: str = STORED,
             hermes_home: str = "/no/hermes", **extra: object) -> tuple[App, ResumeClient, list[float]]:
    """`omh --resume <stored_id>` on the test's clock; `run` is what the dag-ulw read finds (None: nothing)."""
    now = [100.0]
    client = ResumeClient(answered(stored_id, **extra))
    environ = {"OMH_HOME": str(omh_home), "HERMES_HOME": hermes_home, "HERMES_TUI_RESUME": stored_id,
               "OMH_TUI_WALLPAPER": "0", "OMH_TUI_UPDATE_CHECK": "0"}
    app = App(ScriptedTerminal(24, 80), client, environ, poller=FakePoller(), clock=lambda: now[0])  # type: ignore[arg-type]
    app.read_waiting_run = lambda _omh, _hermes, _session: run  # type: ignore[method-assign]
    app.startup()
    return app, client, now


class Home(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name) / ".omh"


class LaunchResumeTests(Home):
    """`omh --resume <id>`. Mutation: drop a guard in `_resume_evidence` or `_offer_resume_continue`."""

    def test_a_session_whose_turn_hermes_interrupted_goes_on(self) -> None:
        record_turn_end(self.home, STORED, TURN_INTERRUPTED, 1.0)
        app, client, now = launched(self.home)
        self.assertIn(resuming(RESUME_WHY_INTERRUPTED), notices(app))
        wait_out(app, now, AUTO_CONTINUE_SECONDS - 0.5)
        self.assertEqual(sent(client), [])
        wait_out(app, now, 0.5)
        self.assertEqual(sent(client), ["continue"])
        self.assertEqual(client.named("prompt.submit")[0]["session_id"], SID)

    def test_an_open_dag_run_goes_on_after_a_turn_that_completed(self) -> None:
        record_turn_end(self.home, STORED, TURN_DONE, 1.0)  # a run's parent turn ends while the run waits
        app, client, now = launched(self.home, run=("ready_idle", "feat", ["a", "b", "c"]))
        self.assertIn(resuming("dag-ulw run feat has 3 ready nodes"), notices(app))
        wait_out(app, now)
        self.assertEqual(sent(client), ["continue"])

    def test_a_session_no_tui_recorded_goes_on_for_its_open_run(self) -> None:
        app, client, now = launched(self.home, run=("lost", "feat", ["a"]))
        self.assertIn(resuming("dag-ulw run feat has 1 node a restart ended"), notices(app))
        wait_out(app, now)
        self.assertEqual(sent(client), ["continue"])

    def test_the_persons_stop_is_never_resumed_even_with_an_open_run(self) -> None:
        record_turn_end(self.home, STORED, TURN_STOPPED, 1.0)
        app, client, now = launched(self.home, run=("ready_idle", "feat", ["a"]))
        self.assertFalse([line for line in notices(app) if line.startswith("Resuming")])
        wait_out(app, now)
        self.assertEqual(sent(client), [])

    def test_nothing_left_is_never_resumed(self) -> None:
        for end in (TURN_DONE, TURN_OPEN, None):
            with self.subTest(end=end):
                home = self.home / str(end)
                if end is not None:
                    record_turn_end(home, STORED, end, 1.0)
                app, client, now = launched(home)
                self.assertIsNone(app.auto_continue)
                wait_out(app, now)
                self.assertEqual(sent(client), [])

    def test_a_turn_running_is_never_resumed(self) -> None:
        # Its own turn still going, or another client's: either way the session is busy and the TUI attaches only.
        record_turn_end(self.home, STORED, TURN_INTERRUPTED, 1.0)
        app, client, now = launched(self.home, run=("ready_idle", "feat", ["a"]), running=True)
        self.assertIsNone(app.auto_continue)
        wait_out(app, now)
        self.assertEqual(sent(client), [])

    def test_a_turn_hermes_resubmits_itself_is_not_resumed_twice(self) -> None:
        record_turn_end(self.home, STORED, TURN_INTERRUPTED, 1.0)
        app, client, now = launched(self.home, auto_continue={"scheduled": True})
        self.assertIsNone(app.auto_continue)
        wait_out(app, now)
        self.assertEqual(sent(client), [])

    def test_esc_in_the_wait_cancels_it(self) -> None:
        record_turn_end(self.home, STORED, TURN_INTERRUPTED, 1.0)
        app, client, now = launched(self.home)
        app._on_input(Key(ESCAPE))
        self.assertEqual(notices(app)[-1], AUTO_CONTINUE_HELD_NOTICE.format(why=AUTO_CONTINUE_ESCAPED))
        wait_out(app, now)
        self.assertEqual(sent(client), [])

    def test_an_open_question_holds_it_without_a_row(self) -> None:
        record_turn_end(self.home, STORED, TURN_INTERRUPTED, 1.0)
        open_request = {"id": "srq-1", "method": "approval", "params": {"command": "rm -rf ./x"}}
        app, client, now = launched(self.home, open_requests=[open_request])
        self.assertIsNotNone(app.slot)  # Hermes asks the person something: that is theirs to answer first
        self.assertIsNone(app.auto_continue)
        self.assertFalse([line for line in notices(app) if line.startswith("Resuming")])
        wait_out(app, now)
        self.assertEqual(sent(client), [])

    def test_past_the_limit_it_is_not_resumed(self) -> None:
        record_turn_end(self.home, STORED, TURN_INTERRUPTED, 1.0)
        app, _client, _now = launched(self.home)
        app.auto_continue = None
        app.auto_continues = AUTO_CONTINUE_LIMIT
        app._offer_resume_continue(answered())
        self.assertIsNone(app.auto_continue)

    def test_a_draft_typed_in_the_wait_holds_it(self) -> None:
        record_turn_end(self.home, STORED, TURN_INTERRUPTED, 1.0)
        app, client, now = launched(self.home)
        type_text(app, "wait")
        wait_out(app, now)
        self.assertEqual(sent(client), [])
        self.assertEqual(app.composer.text, "wait")


class SwitchResumeTests(Home):
    """`/sessions <id>` (and `/resume`, the picker): the same, once the session it opened is drawn."""

    def switched(self, **extra: object) -> tuple[App, RecordingClient, list[float]]:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0], environ={"OMH_HOME": str(self.home), "HERMES_HOME": "/h"})
        app.stored_id = "stored-before"
        app.read_waiting_run = lambda _omh, _hermes, _session: extra.pop("run", None)  # type: ignore[method-assign]
        type_text(app, f"/sessions {STORED}")
        app._on_input(Key(ENTER))
        answer(app, client, {**answered(), "session_id": "live-3", **extra})
        self.assertEqual(app.stored_id, STORED)
        return app, client, now

    def test_a_switch_to_a_session_hermes_interrupted_goes_on(self) -> None:
        record_turn_end(self.home, STORED, TURN_INTERRUPTED, 1.0)
        app, client, now = self.switched()
        self.assertIn(resuming(RESUME_WHY_INTERRUPTED), notices(app))
        wait_out(app, now)
        self.assertEqual(sent(client), ["continue"])
        self.assertEqual(client.named("prompt.submit")[0]["session_id"], "live-3")

    def test_a_switch_to_a_session_with_an_open_run_goes_on(self) -> None:
        app, client, now = self.switched(run=("parked_due", "feat", ["a"]))
        self.assertIn(resuming("dag-ulw run feat has 1 parked node due"), notices(app))
        wait_out(app, now)
        self.assertEqual(sent(client), ["continue"])

    def test_a_switch_to_a_session_the_person_stopped_does_not(self) -> None:
        record_turn_end(self.home, STORED, TURN_STOPPED, 1.0)
        app, client, now = self.switched(run=("ready_idle", "feat", ["a"]))
        wait_out(app, now)
        self.assertEqual(sent(client), [])


class TurnEndRecordTests(Home):
    """What the TUI writes as each turn of the live session ends. Mutation: write the wrong end, or none."""

    def app(self) -> tuple[App, RecordingClient, list[float]]:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0], environ={"OMH_HOME": str(self.home)})
        app.stored_id = STORED
        return app, client, now

    def test_a_turn_started_is_open_until_its_end_is_seen(self) -> None:
        app, _client, _now = self.app()
        streaming(app, ours=True)
        self.assertEqual(read_turn_end(self.home, STORED), TURN_OPEN)

    def test_hermes_interrupting_a_turn_this_tui_sent_is_kept(self) -> None:
        app, _client, _now = self.app()
        streaming(app, ours=True)
        app._on_event(Event("message.complete", SID, dict(HERMES_STOPPED)))
        self.assertEqual(read_turn_end(self.home, STORED), TURN_INTERRUPTED)

    def test_another_clients_interrupted_turn_is_not_kept_as_one(self) -> None:
        app, _client, _now = self.app()
        streaming(app)
        app._on_event(Event("message.complete", SID, dict(HERMES_STOPPED)))
        self.assertEqual(read_turn_end(self.home, STORED), TURN_DONE)

    def test_an_interrupt_with_an_error_is_not_kept_as_one(self) -> None:
        app, _client, _now = self.app()
        streaming(app, ours=True)
        app._on_event(Event("message.complete", SID, {**HERMES_STOPPED, "error": "provider down"}))
        self.assertEqual(read_turn_end(self.home, STORED), TURN_DONE)

    def test_a_completed_turn_is_done(self) -> None:
        app, _client, _now = self.app()
        streaming(app, ours=True)
        app._on_event(Event("message.complete", SID, {"text": "done", "status": "complete"}))
        self.assertEqual(read_turn_end(self.home, STORED), TURN_DONE)

    def test_the_persons_esc_is_kept_as_they_press_it(self) -> None:
        app, _client, _now = self.app()
        streaming(app, ours=True)
        app._on_input(Key(ESCAPE))
        self.assertEqual(read_turn_end(self.home, STORED), TURN_STOPPED)  # before Hermes ends it: the TUI may quit
        app._on_event(Event("message.complete", SID, dict(HERMES_STOPPED)))
        self.assertEqual(read_turn_end(self.home, STORED), TURN_STOPPED)

    def test_the_persons_stop_command_is_kept_as_they_send_it(self) -> None:
        app, _client, _now = self.app()
        streaming(app, ours=True)
        type_text(app, "/stop")
        app._on_input(Key(ENTER))
        self.assertEqual(read_turn_end(self.home, STORED), TURN_STOPPED)

    def test_a_prompt_sent_during_a_turn_is_no_stop_whatever_the_busy_mode(self) -> None:
        app, _client, _now = self.app()
        app._take_settings({"config": {"display": {"busy_input_mode": "interrupt"}}})
        streaming(app, ours=True)
        app._send_prompt("do this instead")
        self.assertEqual(read_turn_end(self.home, STORED), TURN_OPEN)  # it waits in the queue: the turn runs on

    def test_with_no_omh_home_nothing_is_written(self) -> None:
        app, _client = make_app()
        app.stored_id = STORED
        streaming(app, ours=True)
        app._on_event(Event("message.complete", SID, dict(HERMES_STOPPED)))
        self.assertFalse(turn_ends_path(self.home).exists())


class TurnEndsStoreTests(Home):
    def test_the_newest_sessions_are_kept(self) -> None:
        for index in range(MAX_SESSIONS + 3):
            record_turn_end(self.home, f"s{index}", TURN_DONE, float(index))
        self.assertIsNone(read_turn_end(self.home, "s0"))
        self.assertEqual(read_turn_end(self.home, f"s{MAX_SESSIONS + 2}"), TURN_DONE)
        record_turn_end(self.home, "s3", TURN_INTERRUPTED, 0.0)  # rewritten: the newest again
        for index in range(MAX_SESSIONS - 1):
            record_turn_end(self.home, f"t{index}", TURN_DONE, 0.0)
        self.assertEqual(read_turn_end(self.home, "s3"), TURN_INTERRUPTED)

    def test_one_busy_session_does_not_push_the_others_out(self) -> None:
        record_turn_end(self.home, "quiet", TURN_INTERRUPTED, 0.0)
        for index in range(MAX_SESSIONS * 2):
            record_turn_end(self.home, "busy", TURN_OPEN if index % 2 else TURN_DONE, float(index))
        self.assertEqual(read_turn_end(self.home, "quiet"), TURN_INTERRUPTED)
        self.assertEqual(read_turn_end(self.home, "busy"), TURN_OPEN)

    def test_a_record_of_another_shape_reads_as_none(self) -> None:
        path = turn_ends_path(self.home)
        path.parent.mkdir(parents=True)
        for text in ('{"schema_version": "other/v9", "sessions": [{"id": "x", "end": "interrupted"}]}',
                     '{"schema_version": "omh_tui_turn_ends/v1", "sessions": [{"id": "x", "end": "elsewhere"}]}',
                     '{"schema_version": "omh_tui_turn_ends/v1", "sessions": {"x": {"end": "interrupted"}}}',
                     "not json"):
            with self.subTest(text=text):
                path.write_text(text, encoding="utf-8")
                self.assertIsNone(read_turn_end(self.home, "x"))

    def test_an_unknown_end_or_no_id_is_not_written(self) -> None:
        self.assertFalse(record_turn_end(self.home, STORED, "elsewhere", 0.0))
        self.assertFalse(record_turn_end(self.home, "", TURN_DONE, 0.0))
        self.assertFalse(turn_ends_path(self.home).exists())


class RunWhyTests(unittest.TestCase):
    def test_every_resumable_reason_says_its_run_and_count(self) -> None:
        for reason in RESUMABLE_REASONS:
            with self.subTest(reason=reason):
                said = resume_run_why(reason, "feat", ["a", "b"])
                self.assertIn("dag-ulw run feat", said)
                self.assertIn("2 ", said)
        self.assertEqual(resume_run_why("needs_repair", "feat", ["a"]), "")
        self.assertEqual(resume_run_why("stuck", "feat", ["a"]), "")


class RealRunRecordTests(unittest.TestCase):
    """A headless repro: a stored session whose dag-ulw run has ready nodes nobody handed out, in temporary homes,
    resumed by an OMH TUI over a recording client; the run is read by the real reader, as the TUI reads it."""

    def test_a_resumed_session_with_ready_nodes_goes_on_with_continue(self) -> None:
        moment = time.time()
        with homes() as home:
            stored(home, [node("a"), node("b"), node("c")], moment)
            self.assertEqual(waiting_run(session_id=PARENT, omh_home=str(home.omh), hermes_home=str(home.hermes),
                                         now=moment), ("ready_idle", "feat", ["a", "b", "c"]))
            now = [100.0]
            client = ResumeClient(answered(PARENT))
            environ = {"OMH_HOME": str(home.omh), "HERMES_HOME": str(home.hermes), "HERMES_TUI_RESUME": PARENT,
                       "OMH_TUI_WALLPAPER": "0", "OMH_TUI_UPDATE_CHECK": "0"}
            app = App(ScriptedTerminal(24, 80), client, environ, poller=FakePoller(), clock=lambda: now[0])  # type: ignore[arg-type]
            app.startup()
            self.assertIn(resuming("dag-ulw run feat has 3 ready nodes"), notices(app))
            wait_out(app, now)
            self.assertEqual(sent(client), ["continue"])

    def test_a_run_that_needs_repair_is_left_to_the_person(self) -> None:
        moment = time.time()
        with homes() as home:
            record = stored(home, [node("a")], moment, out={"a": {}})
            record["nodes"][0]["attempts"][-1].update(settled_at=moment, outcome="failed", reason="tests failed")
            from omh.plugin_bundle.omh import dag_run

            dag_run.write_run(dag_run.record_path(home.omh, PARENT, "feat"), record)
            self.assertEqual(dag_run.run_state(record, dag_run.derive(record, [], moment)), "needs_repair")
            self.assertIsNone(waiting_run(session_id=PARENT, omh_home=str(home.omh), hermes_home=str(home.hermes),
                                          now=moment))

    def test_no_home_or_no_session_reads_nothing(self) -> None:
        self.assertIsNone(waiting_run(session_id="", omh_home="/o", hermes_home="/h"))
        self.assertIsNone(waiting_run(session_id=PARENT, omh_home="", hermes_home="/h"))
        with homes() as home:
            self.assertIsNone(waiting_run(session_id=PARENT, omh_home=str(home.omh), hermes_home=str(home.hermes)))


if __name__ == "__main__":
    unittest.main()
