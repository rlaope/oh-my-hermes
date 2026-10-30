"""A turn that starts remote work and arms nothing gets told so (#1721).

The defect: a Hermes session cannot wake itself, so "waiting for CI" is a real
wait only when the turn armed a background process that exits when CI does.
Measured on the reporter's own history, 43 of 48 such turn endings had armed
nothing.

Two properties are what these tests exist to pin, and both have a mutation
case beside them in `MutationProofTests`:

* whether a waiter is armed is read from two host records and never from
  anything the model wrote: the process record for liveness, and the
  background spawn's own result for whether a live process will notify.
  `test_wording_alone_cannot_satisfy_the_armed_check` is the direct proof: a
  response and a command that say every true thing about watching CI still
  get the directive while the records are empty. `CheckpointWriteOrderTests`
  is why it takes two, and it is a reproduced defect, not a precaution.
* the command trigger is anchored on executable plus subcommand tokens, so
  `git push --help`, `echo git push` and a heredoc body carrying the words are
  all misses.

`reset_nudge_budget` and `reset_remote_wait_state` are module-global state.
They are cleared in `setUp` rather than at the end of each test because the
shard planner reorders tests run to run, so a leak surfaces as a CI-only
failure in whichever test ran next.
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from unittest import mock
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from _local_package import load_local_package
from test_plugin_distribution import FakeHermesContext, load_installed_plugin

load_local_package()
from omh.plugin_bundle.omh.code_mode_guidance import CODE_MODE_GUIDANCE_TOOL
from omh.plugin_bundle.omh.engagement_nudges import (
    DELEGATION_TOOLS,
    DIRECT_READ_TOOLS,
    FILE_MUTATING_TOOLS,
)
from omh.plugin_bundle.omh.hooks.nudge_budget import reset_nudge_budget
from omh.plugin_bundle.omh.hooks.result_transforms import (
    transform_llm_output,
    transform_tool_result,
)
from omh.plugin_bundle.omh.hooks.session_hooks import subagent_start
from omh.plugin_bundle.omh.kanban_readback import KANBAN_READBACK_TOOLS
from omh.plugin_bundle.omh.search_hit_context import SEARCH_HIT_CONTEXT_TOOL
from omh.plugin_bundle.omh import remote_wait_nudge
from omh.plugin_bundle.omh.remote_wait_nudge import (
    APPROVAL_GATE_CAUSE,
    APPROVAL_GATE_TEXT,
    HONEST_STOP_TEXT,
    HONEST_STOP_TEXTS,
    REPLY_SCRIPT_MIN_RUN,
    PROCESS_RECORD_FILENAME,
    REMOTE_WAIT_NUDGE_KEY,
    REMOTE_WORK_COMMANDS,
    remote_work_anchors,
    TERMINAL_TOOL,
    UNARMED_WAIT_CAUSE,
    UNARMED_WAIT_TEXT,
    annotate_remote_wait,
    armed_waiter_present,
    honest_stop_output,
    observed_spawns,
    remote_wait_declines,
    remote_work_command,
    reset_remote_wait_state,
    reply_language,
)
from omh.plugin_bundle.omh.truncated_read_recovery import TRUNCATED_READ_TOOL

OK_RESULT = json.dumps({"status": "ok", "exit_code": 0, "output": "Everything up-to-date"})
APPROVAL_RESULT = json.dumps(
    {"error": "", "status": "pending_approval", "approval_pending": True, "command": "git push"}
)


class RemoteWaitTestCase(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        reset_nudge_budget()
        reset_remote_wait_state()
        self.addCleanup(reset_nudge_budget)
        self.addCleanup(reset_remote_wait_state)
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "hermes"
        self.home.mkdir()

    def arm(self, *entries: dict[str, object]) -> None:
        """Write the host's live-process record with *entries* in it."""
        (self.home / PROCESS_RECORD_FILENAME).write_text(
            json.dumps(list(entries)), encoding="utf-8"
        )

    def spawn_result(self, process_id: str = "proc_abc123", **overrides: object) -> str:
        """A background spawn's tool result, in the host's own shape.

        `tools/terminal_tool_background.py::spawn_background_process` returns
        the process id as `session_id` alongside `notify_on_complete` and
        `watch_patterns`. The foreground path returns no `session_id` at all,
        which is how this pass tells the two apart.
        """
        payload: dict[str, object] = {
            "output": "Background process started",
            "session_id": process_id,
            "pid": 4242,
            "exit_code": 0,
            "error": None,
        }
        payload.update(overrides)
        return json.dumps(payload)

    def watcher(self, session: str, **overrides: object) -> dict[str, object]:
        entry: dict[str, object] = {
            "session_id": "proc_abc123",
            "command": "gh pr checks 1721 --watch",
            "pid": 4242,
            "parent_session_id": session,
            "notify_on_complete": True,
            "watch_patterns": [],
        }
        entry.update(overrides)
        return entry

    def fire(
        self,
        command: str,
        *,
        session: str = "s1",
        turn: str = "t1",
        result: str = OK_RESULT,
        tool: str = "terminal",
        background: object = None,
        arm: dict[str, object] | None = None,
    ) -> str | None:
        args: dict[str, object] = {"command": command}
        if background is not None:
            args["background"] = background
        if arm:
            args.update(arm)
        return annotate_remote_wait(
            tool_name=tool,
            args=args,
            result=result,
            session_id=session,
            turn_id=turn,
            hermes_home=str(self.home),
        )

    def directive(self, *args: object, **kwargs: object) -> str:
        carried = self.fire(*args, **kwargs)  # type: ignore[arg-type]
        self.assertIsNotNone(carried, "expected a directive")
        return str(json.loads(str(carried))[REMOTE_WAIT_NUDGE_KEY])


class UnarmedWaitTests(RemoteWaitTestCase):
    """The positive case, and every way a real waiter suppresses it."""

    def test_a_push_with_nothing_armed_gets_the_directive(self) -> None:
        text = self.directive("git push origin HEAD")
        self.assertIn("[OMH unarmed wait]", text)
        self.assertIn("git push", text)
        # The fact the model cannot look up.
        self.assertIn("A session resumes only when a person writes to it", text)
        # Both exits, each with something to do, and neither forced.
        self.assertIn("notify=true", text)
        self.assertIn("gh pr checks", text)
        self.assertIn("say plainly that the session has stopped", text)
        self.assertIn("Do not poll in the foreground", text)

    def test_the_claim_is_narrowed_to_background_processes(self) -> None:
        # The check covers background processes only. An async delegation
        # also wakes a session, through the same completion queue but with
        # no `processes.json` row at all, so a flat "nothing will wake it"
        # would be a claim this pass cannot support (#1738 review R2).
        text = self.directive("git push")
        self.assertIn("no background process this session started will wake it", text)
        self.assertNotIn("nothing this session armed", text)

    def test_the_obligation_is_conditional_on_actually_waiting(self) -> None:
        # At the moment a push returns the model has not decided whether to
        # wait, so the directive may not assume that it will.
        self.assertIn("If this turn will wait on that work", self.directive("git push"))

    def test_the_directive_carries_no_evidence_boundary_sentence(self) -> None:
        # That sentence lives in the module docstring instead: a reviewer
        # needs it, the model cannot act on it, so it does not ride a push.
        text = self.directive("git push")
        for phrase in ("prepared instruction", "never evidence", "This line is"):
            self.assertNotIn(phrase, text)
        self.assertIn("prepared instruction", str(remote_wait_nudge.__doc__))

    def test_the_directive_rides_the_result_as_its_own_json_key(self) -> None:
        carried = self.fire("git push")
        payload = json.loads(str(carried))
        # The host result must keep parsing, and keep every field it had.
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["exit_code"], 0)
        self.assertIn(REMOTE_WAIT_NUDGE_KEY, payload)

    def test_a_watcher_armed_by_this_session_suppresses_it(self) -> None:
        self.arm(self.watcher("s1"))
        self.assertIsNone(self.fire("git push"))
        self.assertEqual(remote_wait_declines().get("waiter_armed"), 1)

    def test_a_watcher_armed_by_another_session_does_not_count(self) -> None:
        self.arm(self.watcher("some-other-session"))
        self.assertIn("[OMH unarmed wait]", self.directive("git push"))

    def test_a_finished_watcher_does_not_count_as_armed(self) -> None:
        # The host removes an exited session from the record on
        # move-to-finished (`ProcessCheckpointMixin._write_checkpoint` skips
        # `s.exited`), so a finished watcher is an ABSENT row, not a row with
        # a flag. An empty record is the shape a finished watcher leaves.
        self.arm(self.watcher("s1"))
        self.arm()
        self.assertIn("[OMH unarmed wait]", self.directive("git push"))

    def test_the_directive_names_the_advertised_parameter(self) -> None:
        # The schema advertises `notify`; `notify_on_complete` is an
        # unadvertised legacy alias the dispatch wrapper still accepts. If it
        # were ever dropped, a call made the way this text described would
        # background silently and the model would believe it armed a waiter,
        # which is the failure this pass exists to prevent.
        text = self.directive("git push")
        self.assertIn("notify=true", text)
        self.assertNotIn("notify_on_complete", text)
        self.assertIn("background=true", text)

    def test_watch_patterns_alone_arm_the_session(self) -> None:
        self.arm(self.watcher("s1", notify_on_complete=False, watch_patterns=["passed"]))
        self.assertIsNone(self.fire("git push"))

    def test_a_push_that_failed_started_no_remote_work(self) -> None:
        # A rejected push is the common one: exit 1, nothing reached the
        # remote, nothing to wait on.
        rejected = json.dumps(
            {"status": "ok", "exit_code": 1, "error": None, "output": "! [rejected] non-fast-forward"}
        )
        self.assertIsNone(self.fire("git push", result=rejected))
        self.assertEqual(remote_wait_declines().get("command_did_not_succeed"), 1)

    def test_a_result_that_does_not_parse_cannot_confirm_a_push(self) -> None:
        self.assertIsNone(self.fire("git push", result="Everything up-to-date"))
        self.assertEqual(remote_wait_declines().get("result_not_parseable"), 1)

    def test_a_call_already_made_in_the_background_is_not_the_unarmed_shape(self) -> None:
        self.assertIsNone(self.fire("git push", background=True))
        self.assertEqual(remote_wait_declines().get("call_was_backgrounded"), 1)

    def test_an_unreadable_record_declines_rather_than_accusing(self) -> None:
        (self.home / PROCESS_RECORD_FILENAME).write_text("{not json", encoding="utf-8")
        self.assertIsNone(self.fire("git push"))
        self.assertEqual(remote_wait_declines().get("process_record_unreadable"), 1)

    def test_a_host_that_never_spawned_anything_reads_as_unarmed(self) -> None:
        # No file at all is a readable answer, not an unreadable record: a
        # host with no background processes has written none.
        self.assertFalse((self.home / PROCESS_RECORD_FILENAME).exists())
        self.assertIn("[OMH unarmed wait]", self.directive("git push"))

    def test_every_shipped_anchor_fires(self) -> None:
        for index, anchor in enumerate(remote_work_anchors()):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, self.directive(anchor, turn=f"t{index}"))


class SessionArmsWatchersTests(RemoteWaitTestCase):
    """A session observed arming a watcher stops being reminded how.

    The rate is why this exists: at the moment a push returns a session has
    almost never armed anything, so the unarmed case is true on nearly every
    push. Both observations here are records -- a tool call's own arguments,
    and the host's process record -- never anything the model wrote.
    """

    def test_a_session_that_armed_a_notifying_watcher_is_not_reminded_again(self) -> None:
        self.assertIsNotNone(self.fire("git push", turn="t1"))
        self.assertIsNone(
            self.fire("gh pr checks 1738 --watch", turn="t1", background=True,
                      result=self.spawn_result(notify_on_complete=True))
        )
        self.assertEqual(remote_wait_declines().get("background_spawn_observed"), 1)
        # Later turns, later pushes: the mechanism is known, so nothing is said.
        self.assertIsNone(self.fire("git push", turn="t2"))
        self.assertIsNone(self.fire("gh pr create --fill", turn="t3"))
        self.assertEqual(remote_wait_declines().get("session_arms_watchers"), 2)

    def test_watch_patterns_alone_also_latch_the_session(self) -> None:
        self.assertIsNone(
            self.fire("tail -f build.log", turn="t1", background=True,
                      result=self.spawn_result(watch_patterns=["BUILD OK"]))
        )
        self.assertIsNone(self.fire("git push", turn="t2"))

    def test_a_silent_background_spawn_does_not_latch_the_session(self) -> None:
        # A spawn the host reported with neither field wakes nobody, so it is
        # no evidence that the session knows the mechanism.
        self.assertIsNone(
            self.fire("python -m http.server", turn="t1", background=True,
                      result=self.spawn_result())
        )
        self.assertIsNotNone(self.fire("git push", turn="t2"))

    def test_the_host_zeroing_the_flag_for_a_subagent_does_not_latch(self) -> None:
        # The host rewrites `notify_on_complete` to False in the result and
        # attaches `subagent_note` when the spawn came from a delegated
        # child, because that notice will not reach the parent. Reading the
        # RESULT rather than the call's arguments is what makes this land.
        self.assertIsNone(
            self.fire("gh pr checks 1 --watch", turn="t1", background=True,
                      result=self.spawn_result(notify_on_complete=False, subagent_note="..."))
        )
        self.assertIsNotNone(self.fire("git push", turn="t2"))

    def test_the_record_latches_the_session_too(self) -> None:
        # A repaired row is good evidence in its own right.
        self.arm(self.watcher("s1"))
        self.assertIsNone(self.fire("git push", turn="t1"))
        self.arm()
        self.assertIsNone(self.fire("git push", turn="t2"))
        self.assertEqual(remote_wait_declines().get("session_arms_watchers"), 1)

    def test_the_latch_belongs_to_one_session(self) -> None:
        self.assertIsNone(
            self.fire("gh pr checks 1 --watch", session="s1", turn="t1", background=True,
                      result=self.spawn_result(notify_on_complete=True))
        )
        self.assertIsNotNone(self.fire("git push", session="s2", turn="t1"))


class CheckpointWriteOrderTests(RemoteWaitTestCase):
    """The row of a just-armed watcher has no flags yet (#1738 review F1).

    `_track_started` writes the checkpoint during `_spawn()`, and the host
    sets `notify_on_complete` / `watch_patterns` on the session object only
    after the spawn returned, with no write in between. So the most recently
    armed process is always recorded without its flags until a later write
    repairs the row. Reading those flags alone made the first draft tell a
    session that had just armed a watcher that it had armed nothing.
    """

    def unflagged_row(self, session: str, process_id: str = "proc_abc123") -> dict[str, object]:
        return self.watcher(session, session_id=process_id, notify_on_complete=False,
                            watch_patterns=[])

    def test_a_watcher_armed_this_turn_is_armed_despite_an_unflagged_row(self) -> None:
        self.assertIsNone(
            self.fire("gh pr checks 1738 --watch", turn="t1", background=True,
                      result=self.spawn_result("proc_w1", notify_on_complete=True))
        )
        # The host's row for it, exactly as the checkpoint holds it right now.
        self.arm(self.unflagged_row("s1", "proc_w1"))
        self.assertTrue(armed_waiter_present(session_id="s1", hermes_home=str(self.home)))
        self.assertIsNone(self.fire("git push", turn="t2"))

    def test_an_unflagged_row_this_session_never_spawned_is_unknown(self) -> None:
        # Not False. It may be an arming whose flags have not landed, and
        # answering False there is how the reproduced defect happened.
        self.arm(self.unflagged_row("s1", "proc_stranger"))
        self.assertIsNone(armed_waiter_present(session_id="s1", hermes_home=str(self.home)))
        self.assertIsNone(self.fire("git push", turn="t1"))
        self.assertEqual(remote_wait_declines().get("process_record_unreadable"), 1)

    def test_an_unflagged_row_OMH_saw_spawn_silent_is_not_armed(self) -> None:
        # This is the one unflagged row that can be answered: OMH watched the
        # host start it and report neither field.
        self.assertIsNone(
            self.fire("python -m http.server", turn="t1", background=True,
                      result=self.spawn_result("proc_srv"))
        )
        self.arm(self.unflagged_row("s1", "proc_srv"))
        self.assertFalse(armed_waiter_present(session_id="s1", hermes_home=str(self.home)))
        self.assertIsNotNone(self.fire("git push", turn="t2"))

    def test_an_observed_arming_that_has_since_exited_is_not_armed(self) -> None:
        # Presence in the record is liveness; the host drops exited sessions.
        self.assertIsNone(
            self.fire("gh pr checks 1 --watch", session="s9", turn="t1", background=True,
                      result=self.spawn_result("proc_gone", notify_on_complete=True))
        )
        self.arm()
        self.assertFalse(armed_waiter_present(session_id="s9", hermes_home=str(self.home)))

    def test_an_observed_arming_belongs_to_the_session_that_made_it(self) -> None:
        self.assertIsNone(
            self.fire("gh pr checks 1 --watch", session="s1", turn="t1", background=True,
                      result=self.spawn_result("proc_w1", notify_on_complete=True))
        )
        self.arm(self.unflagged_row("s2", "proc_w1"))
        self.assertIsNone(armed_waiter_present(session_id="s2", hermes_home=str(self.home)))

    def test_a_foreground_result_is_not_recorded_as_a_spawn(self) -> None:
        # The foreground path returns no `session_id`, which is the shape
        # test; without it every ordinary command would enter the map.
        self.assertIsNotNone(self.fire("git push", turn="t1"))
        self.assertEqual(observed_spawns("s1"), {})


class DelegatedChildTests(RemoteWaitTestCase):
    """A subagent gets nothing, through the predicate that already exists.

    Two reasons, both the host's. A delegated child must not be told to tell
    "the person" that the session has stopped, because the person is not who
    it reports to. And the watcher the directive names would not reach its
    parent anyway: the host attaches `_SUBAGENT_NOTIFY_NOTE` to that very
    spawn and zeroes the notify flag in the result. `engagement_nudges`
    refuses the same sessions through the same predicate.
    """

    def test_a_delegated_child_that_pushes_is_not_nudged(self) -> None:
        subagent_start(child_session_id="child-1")
        self.assertIsNone(self.fire("git push", session="child-1"))
        self.assertEqual(remote_wait_declines().get("delegated_session"), 1)

    def test_a_delegated_child_held_at_the_approval_gate_is_not_nudged(self) -> None:
        subagent_start(child_session_id="child-1")
        self.assertIsNone(self.fire("ls", session="child-1", result=APPROVAL_RESULT))

    def test_the_orchestrator_that_spawned_it_is_still_nudged(self) -> None:
        # The pinned positive beside the guard: refusing the child must not
        # refuse the session that created it.
        subagent_start(child_session_id="child-1")
        self.assertIsNotNone(self.fire("git push", session="s1"))


class NoPromiseTests(RemoteWaitTestCase):
    """No change to a turn that starts no remote work."""

    def test_a_turn_with_no_such_call_gets_nothing(self) -> None:
        for command in ("uv run python -m unittest", "git status", "ls -la", "gh pr view 1721"):
            with self.subTest(command=command):
                self.assertIsNone(self.fire(command))

    def test_a_non_terminal_tool_is_never_touched(self) -> None:
        self.assertIsNone(self.fire("git push", tool="write_file"))
        self.assertEqual(remote_wait_declines().get("tool_not_terminal"), 1)


class EndOfTurnHonestStopTests(RemoteWaitTestCase):
    """The end-of-turn half: a turn told it was unarmed that ends unarmed.

    `transform_llm_output` fires once per turn after the tool loop. It can
    append to the final response but not re-enter the loop, so the only exit
    left to deliver is the honest stop. Its trigger is two records -- the
    directive's own per-turn latch and a fresh read of the process record --
    and never the response text, which is why the wording case below gives it
    every sentence a waiting session writes and expects silence.
    """

    WAITING_PROSE = (
        "Pushed. I'll wait for CI and merge once it's green -- watching it in the "
        "background, a notice will arrive when it completes."
    )

    def end(
        self, response: object = WAITING_PROSE, *, session: object = "s1", turn: object = "t1"
    ) -> str | None:
        return honest_stop_output(
            response_text=response,
            session_id=session,
            turn_id=turn,
            hermes_home=str(self.home),
        )

    def test_an_unarmed_wait_turn_ends_on_the_honest_stop(self) -> None:
        self.assertIsNotNone(self.fire("git push origin HEAD"))
        self.assertEqual(self.end(), f"{self.WAITING_PROSE}\n\n{HONEST_STOP_TEXT}")

    def test_the_sentence_is_appended_so_a_streamed_response_stays_its_prefix(self) -> None:
        # The CLI prints only the suffix when the new text starts with the
        # streamed one (`cli.py::_post_stream_transform_output`), so trailing
        # whitespace must survive untouched.
        # Once per language: localizing the sentence must keep it a suffix.
        # Ends in spaces on purpose: a newline would survive an `rstrip`
        # followed by the "\n\n" separator and hide the mutation.
        for language, streamed in LOCALIZED_REPLIES.items():
            with self.subTest(language=language):
                self.fire("git push", turn=f"t-{language}")
                streamed = f"{streamed}  "
                ended = self.end(streamed, turn=f"t-{language}")
                self.assertIsNotNone(ended)
                self.assertTrue(str(ended).startswith(streamed))
                self.assertEqual(str(ended), f"{streamed}\n\n{HONEST_STOP_TEXTS[language]}")

    def test_an_armed_turn_is_left_untouched(self) -> None:
        self.fire("git push")
        self.arm(self.watcher("s1"))
        self.assertIsNone(self.end())
        self.assertEqual(remote_wait_declines().get("end_of_turn_waiter_armed"), 1)

    def test_a_watcher_armed_and_already_exited_this_turn_is_left_untouched(self) -> None:
        # A watcher that finished inside the turn has left the record, but
        # its completion notice is queued and will still wake the session.
        self.fire("git push")
        self.assertIsNone(
            self.fire(
                "gh pr checks 1721 --watch",
                background=True,
                result=self.spawn_result(notify_on_complete=True),
            )
        )
        self.assertIsNone(self.end())
        self.assertEqual(remote_wait_declines().get("end_of_turn_session_arms_watchers"), 1)

    def test_a_turn_with_no_remote_promise_is_untouched(self) -> None:
        self.assertIsNone(self.fire("ls -la"))
        self.assertIsNone(self.end("Here is the listing."))

    def test_the_latch_belongs_to_the_turn_that_pushed(self) -> None:
        self.fire("git push", turn="t1")
        self.assertIsNone(self.end(turn="t2"))
        self.assertIsNone(self.end(session="s2"))

    def test_wording_alone_cannot_trigger_the_sentence(self) -> None:
        # Nothing ran and the record is empty, so "nothing armed" is TRUE
        # here; the response says every thing a waiting session says, and
        # even carries the sentence itself, in every language it ships in.
        # Without the latch record: silence.
        self.assertIsNone(self.end("I'll wait for CI. Waiting for CI to finish."))
        for text in HONEST_STOP_TEXTS.values():
            self.assertIsNone(self.end(f"Pushed with git push. {text}"))
        self.assertEqual(
            remote_wait_declines().get("end_of_turn_no_unarmed_wait"), 1 + len(HONEST_STOP_TEXTS)
        )

    def test_a_push_the_directive_never_reached_does_not_end_on_it(self) -> None:
        # A failed push records no latch, so the end of the turn is silent.
        self.fire("git push", result=json.dumps({"status": "error", "exit_code": 1}))
        self.assertIsNone(self.end())

    def test_an_unreadable_record_fails_open(self) -> None:
        self.fire("git push")
        (self.home / PROCESS_RECORD_FILENAME).mkdir()
        self.assertIsNone(self.end())
        self.assertEqual(remote_wait_declines().get("end_of_turn_record_unreadable"), 1)

    def test_an_unparseable_record_fails_open(self) -> None:
        self.fire("git push")
        (self.home / PROCESS_RECORD_FILENAME).write_text("{", encoding="utf-8")
        self.assertIsNone(self.end())

    def test_missing_turn_or_session_identity_fails_open(self) -> None:
        self.fire("git push")
        for session, turn in (("", "t1"), ("s1", ""), (None, "t1"), ("s1", None)):
            with self.subTest(session=session, turn=turn):
                self.assertIsNone(self.end(session=session, turn=turn))

    def test_an_empty_or_non_text_response_is_untouched(self) -> None:
        self.fire("git push")
        for response in ("", "   ", None, ["x"]):
            with self.subTest(response=response):
                self.assertIsNone(self.end(response))

    def test_a_failure_inside_the_pass_fails_open_and_is_counted(self) -> None:
        self.fire("git push")
        with mock.patch.object(
            remote_wait_nudge, "armed_waiter_present", side_effect=RuntimeError("boom")
        ):
            self.assertIsNone(self.end())
        self.assertEqual(remote_wait_declines().get("error:RuntimeError"), 1)

    def test_the_composed_hook_reads_the_hosts_kwargs(self) -> None:
        self.fire("git push")
        ended = transform_llm_output(
            response_text="Pushed.",
            session_id="s1",
            model="any-model",
            platform="cli",
            turn_id="t1",
            hermes_home=str(self.home),
        )
        self.assertEqual(ended, f"Pushed.\n\n{HONEST_STOP_TEXT}")

    def test_the_sentence_is_short_and_executor_neutral_in_every_language(self) -> None:
        # Pinned so a later edit moves the numbers deliberately. It rides the
        # displayed response only: the host persists the transcript before
        # this transform runs (`agent/turn_finalizer.py::finalize_turn`), so
        # the sentence never enters the model's context on a later turn.
        self.assertEqual(sorted(HONEST_STOP_TEXTS), ["en", "ja", "ko", "zh"])
        self.assertEqual(HONEST_STOP_TEXT, HONEST_STOP_TEXTS["en"])
        self.assertEqual(
            {language: len(text) for language, text in HONEST_STOP_TEXTS.items()},
            {"en": 125, "ko": 56, "ja": 53, "zh": 31},
        )
        self.assertTrue(HONEST_STOP_TEXTS["en"].isascii())
        for language, text in HONEST_STOP_TEXTS.items():
            with self.subTest(language=language):
                for name in ("Codex", "Claude", "Hermes", "gh ", "git "):
                    self.assertNotIn(name, text)
                if language != "en":
                    self.assertFalse(text.isascii())
                    self.assertNotEqual(text, HONEST_STOP_TEXTS["en"])
                # Each copy is in the language the detector would give it.
                self.assertEqual(reply_language(text), language)

    def test_the_sentence_carries_no_omh_vocabulary_in_any_language(self) -> None:
        from omh.quality.reply_lint import build_reply_lint, record_term_vocabulary

        for language, text in HONEST_STOP_TEXTS.items():
            with self.subTest(language=language):
                self.assertTrue(build_reply_lint(text)["ok"], build_reply_lint(text)["findings"])
                self.assertNotIn("[OMH", text)
                self.assertNotIn("armed", text.lower())
                # The lint knows English and Korean only. For ja and zh this
                # structural check is what stands in for it: no ASCII record
                # term can appear in the copy at all.
                for term in record_term_vocabulary():
                    if term.isascii():
                        self.assertNotIn(term.lower(), text.lower())

    def test_the_appended_sentence_leaves_a_question_closing_clean(self) -> None:
        # The sentence becomes the reply's closing paragraph, so the question
        # the Turn Ending rule asks for is no longer last; the lint then
        # judges this sentence, and it must not read as a refusal.
        from omh.quality.reply_lint import build_reply_lint

        for language, reply in QUESTION_REPLIES.items():
            with self.subTest(language=language):
                self.assertEqual(reply_language(reply), language)
                ended = f"{reply}\n\n{HONEST_STOP_TEXTS[language]}"
                self.assertTrue(build_reply_lint(ended)["ok"], build_reply_lint(ended)["findings"])

    def test_the_sentence_follows_the_reply_language(self) -> None:
        for language, reply in LOCALIZED_REPLIES.items():
            with self.subTest(language=language):
                self.fire("git push", turn=f"t-{language}")
                self.assertEqual(
                    self.end(reply, turn=f"t-{language}"), f"{reply}\n\n{HONEST_STOP_TEXTS[language]}"
                )


# One ordinary closing per language, as a session would end on a push.
LOCALIZED_REPLIES = {
    "en": "Pushed the branch; CI is running on it now.",
    "ko": "브랜치를 푸시했고 지금 CI가 돌고 있습니다.",
    "ja": "ブランチをプッシュしました。いまCIが動いています。",
    "zh": "已推送分支，持续集成正在运行。",
}

QUESTION_REPLIES = {
    "en": "Pushed the branch.\n\nShall I watch CI, or stop here for review?",
    "ko": "브랜치를 푸시했습니다.\n\nCI를 지켜볼까요, 아니면 리뷰를 기다릴까요?",
    "ja": "ブランチをプッシュしました。\n\nCIを見守りますか、それともレビューを待ちますか？",
    "zh": "已推送分支。\n\n要我继续关注持续集成，还是先等评审？",
}


class ReplyLanguageTests(unittest.TestCase):
    """A run of the script, a share against the Latin letters, then precedence.

    Each case is the mutation it kills: swap the Hangul/kana precedence, drop
    the code stripping or the fence-length match, drop the run minimum or the
    share, move either threshold by one, or give an unsupported script its
    own copy.
    """

    def test_hangul_wins_over_kana(self) -> None:
        # A Korean reply quoting a Japanese product name stays Korean.
        self.assertEqual(reply_language("설정 화면에서 「プッシュ通知」를 켰습니다."), "ko")
        # Unquoted kana is still counted, so only the precedence keeps this
        # Korean; the quoted case above is decided by the quotation drop.
        self.assertEqual(reply_language("일본 앱의 プッシュ 알림을 켰습니다."), "ko")

    def test_camel_case_identifiers_do_not_outvote_a_korean_reply(self) -> None:
        # Four camel-case hook names against two Hangul characters: counted
        # as words they would make this reply English.
        self.assertEqual(reply_language("useEffect useState useMemo useCallback 정리"), "ko")

    def test_kana_wins_over_han(self) -> None:
        # Kanji-heavy Japanese: Han characters outnumber kana four to one,
        # so a majority rule would call this Chinese.
        reply = "設定変更完了、全試験合格確認済。次段階移行予定ですので、ご確認ください。"
        self.assertEqual(reply_language(reply), "ja")

    def test_a_kanji_only_japanese_reply_reads_as_chinese(self) -> None:
        # The stated limit: with no run of two kana nothing in the text tells
        # Japanese from Chinese, so it gets the Chinese copy.
        self.assertEqual(reply_language("設定変更完了。全試験合格。"), "zh")
        self.assertEqual(reply_language("設定を変更し完了。"), "zh")

    def test_code_is_not_prose(self) -> None:
        fenced = "Updated the greeting.\n\n```python\nGREETING = \"안녕하세요 여러분\"\n```\n\nCI is green."
        self.assertEqual(reply_language(fenced), "en")
        tilde = "Updated the label.\n~~~\nlabel = \"設定を保存しました\"\n~~~\nDone."
        self.assertEqual(reply_language(tilde), "en")
        inline = "Renamed `설정_저장하기` to `save_settings` and pushed."
        self.assertEqual(reply_language(inline), "en")

    def test_a_longer_fence_is_closed_only_by_its_own_length(self) -> None:
        # A four-backtick block showing a three-backtick one: the inner ```
        # does not close it, so the Korean after it is still code.
        nested = (
            "Here is the snippet.\n\n````markdown\n```python\nx = 1\n```\n"
            "안녕하세요 여러분 반갑습니다\n````\n\nPushed."
        )
        self.assertEqual(reply_language(nested), "en")
        # And the block does close at its own length: prose after it counts.
        self.assertEqual(reply_language("````\nx = 1\n````\n\n브랜치를 푸시했습니다."), "ko")

    def test_prose_after_an_unclosed_fence_is_still_code(self) -> None:
        self.assertEqual(reply_language("Here it is:\n```\n안녕하세요 여러분"), "en")

    def test_a_short_korean_status_is_korean(self) -> None:
        self.assertEqual(reply_language("CI 대기 중"), "ko")
        self.assertEqual(reply_language("완료."), "ko")
        self.assertEqual(reply_language("PR #1930 올렸고 CI 대기 중입니다."), "ko")

    def test_a_reply_naming_paths_and_identifiers_keeps_its_language(self) -> None:
        # The CI-wait coding turn the honest stop ends: bare paths,
        # identifiers and product words around a Korean or Chinese sentence.
        for reply, language in (
            ("src/quality/reply_lint.py 와 tests/test_reply_lint.py 를 수정했습니다.", "ko"),
            ("reply_language 함수에서 REPLY_SCRIPT_MIN_RUN 기준을 적용했습니다", "ko"),
            ("GitHub Actions workflow 가 실패했습니다", "ko"),
            ("Kubernetes deployment rollout status 확인 완료", "ko"),
            (
                "테스트 결과 tests/test_reply_lint.py tests/test_orchestration_say.py "
                "tests/test_remote_wait_nudge.py 모두 통과했습니다. 다음은 merge 입니다.",
                "ko",
            ),
            ("修改了 src/quality/reply_lint.py 文件", "zh"),
            ('빌드가 "error: could not resolve the module path for the test runner" 로 실패했습니다.', "ko"),
        ):
            with self.subTest(reply=reply):
                self.assertEqual(reply_language(reply), language)

    def test_an_english_reply_quoting_korean_stays_english(self) -> None:
        for reply in (
            "You asked about 설정 on the settings page.",
            "I updated 설정파일.md with the new timeout and pushed the branch.",
            'The user wrote "배포가 끝나면 알려주세요" so I set up a notification for it.',
            "The user wrote “배포가 끝나면 알려주세요” so I set it up.",
            "The screen now reads 「プッシュ通知」 after the rename.",
        ):
            with self.subTest(reply=reply):
                self.assertEqual(reply_language(reply), "en")

    def test_the_run_minimum_is_exact(self) -> None:
        self.assertEqual(REPLY_SCRIPT_MIN_RUN, 2)
        # Two in a row count; the same two apart do not.
        self.assertEqual(reply_language("대기"), "ko")
        self.assertEqual(reply_language("대 기"), "en")
        self.assertEqual(reply_language("ですね"), "ja")
        self.assertEqual(reply_language("で す"), "en")

    def test_the_share_threshold_is_exact(self) -> None:
        # Two Hangul against two Latin words ties and is Korean; a third word
        # outweighs them. Words, not letters: long words weigh the same.
        self.assertEqual(reply_language("대기 ab cd"), "ko")
        self.assertEqual(reply_language("대기 deployment rollout"), "ko")
        self.assertEqual(reply_language("대기 ab cd ef"), "en")

    def test_a_name_token_is_dropped_whole_and_a_period_is_not_one(self) -> None:
        # Its Hangul goes with it, so the file name cannot make a reply Korean.
        self.assertEqual(reply_language("설정파일.md"), "en")
        # A sentence-ending period has no word character after it.
        self.assertEqual(reply_language("대기 ab cd."), "ko")
        self.assertEqual(reply_language("대기 ab cd ef."), "en")

    def test_an_unsupported_script_falls_back_to_english(self) -> None:
        self.assertEqual(reply_language("Готово, изменения отправлены."), "en")
        self.assertEqual(reply_language(""), "en")
        self.assertEqual(reply_language(None), "en")


class CommandAnchorTests(unittest.TestCase):
    """The near misses. A trigger this coarse would accuse ordinary work."""

    def test_the_shipped_anchors_match(self) -> None:
        self.assertEqual(remote_work_command("git push"), "git push")
        self.assertEqual(remote_work_command("git push -u origin claude/x"), "git push")
        self.assertEqual(remote_work_command("gh pr create --fill"), "gh pr create")
        self.assertEqual(remote_work_command("gh workflow run ci.yml"), "gh workflow run")
        self.assertEqual(remote_work_command("gh pr merge 1721"), "gh pr merge")

    def test_a_subcommand_under_the_wrong_executable_is_a_miss(self) -> None:
        # The executable is now the table's KEY rather than the first element
        # of the anchor tuple, so this is the case that proves the lookup
        # still happens. Without it a matcher that checked every subcommand
        # against every command would pass every other test here.
        for command in ("gh push", "git pr create", "git workflow run", "gh pr push"):
            with self.subTest(command=command):
                self.assertEqual(remote_work_command(command), "")

    def test_asking_about_the_command_is_not_running_it(self) -> None:
        for command in ("git push --help", "git push -h", "git push --dry-run", "man git push"):
            with self.subTest(command=command):
                self.assertEqual(remote_work_command(command), "")

    def test_naming_the_command_is_not_running_it(self) -> None:
        for command in (
            "echo git push",
            "echo 'git push'",
            'echo "run git push when CI is green"',
            "grep -rn 'gh pr create' docs/",
        ):
            with self.subTest(command=command):
                self.assertEqual(remote_work_command(command), "")

    def test_a_heredoc_body_carrying_the_words_is_not_a_push(self) -> None:
        # `<<` is deliberately not a segment separator, and its presence also
        # disables the newline split: shlex flattens a heredoc body into
        # ordinary tokens and its lines are lines, so either one alone would
        # read every documented command as an executed one.
        body = "cat <<EOF\ngit push\ngh pr create\nEOF"
        self.assertEqual(remote_work_command(body), "")

    def test_a_real_push_sharing_a_command_with_a_heredoc_is_missed(self) -> None:
        # The stated cost of that guard, pinned so it is a known miss rather
        # than a surprise. A directive not issued is the safe direction.
        self.assertEqual(remote_work_command("cat <<EOF\nnotes\nEOF\ngit push"), "")

    def test_a_quoted_string_spanning_lines_does_not_lose_the_push(self) -> None:
        # The regression the per-line split introduced (#1738 review R1), and
        # the reason the whole command is still tokenized beside its lines. A
        # commit message with a blank line in it leaves every line unbalanced,
        # so a line-only matcher gets no tokens at all and the push vanishes.
        # Measured over the owner's 10,098 terminal calls, this shape
        # dominated the 47 real pushes a line-only matcher dropped.
        self.assertEqual(
            remote_work_command(
                'git commit -m "feat: thing\n\nbody line" && git push origin main'
            ),
            "git push",
        )
        self.assertEqual(
            remote_work_command('git -c user.email="a b" commit -m "x\ny" && git push'),
            "git push",
        )

    def test_a_leading_shell_setting_does_not_hide_a_later_push(self) -> None:
        # The review's own repro (#1738 F4). A script headed by `set -e`
        # puts the push on a later LINE, not a later segment, so without the
        # newline split the whole command reads as one headed by `set`.
        self.assertEqual(remote_work_command("set -e\ngit push origin main"), "git push")
        self.assertEqual(
            remote_work_command("set -euo pipefail\ncd repo\ngit push"), "git push"
        )

    def test_a_multi_line_block_is_one_command_that_can_start_a_push(self) -> None:
        # The ordinary shape in this repository, and the one the whole
        # feature is for. shlex consumes a newline as plain whitespace, so
        # without splitting first the push sits behind `git add` at the
        # segment head and is never seen.
        self.assertEqual(
            remote_work_command("git add -A\ngit commit -s -m 'x'\ngit push"), "git push"
        )
        self.assertEqual(
            remote_work_command("uv run python -m unittest\ngh pr create --fill"),
            "gh pr create",
        )

    def test_a_later_line_that_only_names_the_command_is_still_a_miss(self) -> None:
        self.assertEqual(remote_work_command("git status\necho git push"), "")
        self.assertEqual(remote_work_command("git status\ngit push --help"), "")

    def test_a_later_segment_of_a_real_command_line_still_counts(self) -> None:
        self.assertEqual(remote_work_command("cd repo && git push"), "git push")
        self.assertEqual(remote_work_command("git commit -s; git push"), "git push")
        self.assertEqual(remote_work_command("git push | tee push.log"), "git push")
        self.assertEqual(remote_work_command("GIT_SSH_COMMAND=ssh git push"), "git push")

    def test_a_command_line_that_will_not_tokenize_is_a_miss(self) -> None:
        self.assertEqual(remote_work_command("git push 'unbalanced"), "")
        self.assertEqual(remote_work_command(""), "")
        self.assertEqual(remote_work_command(None), "")


class ApprovalGateTests(RemoteWaitTestCase):
    """The second stall: blocked on a person who is not there."""

    def test_a_command_held_at_the_approval_gate_says_so(self) -> None:
        text = self.directive("uv run python -m unittest", result=APPROVAL_RESULT)
        self.assertIn("[OMH approval gate]", text)
        self.assertIn("This command did not run", text)
        self.assertIn("say that as your last words", text)

    def test_it_reads_the_hosts_field_not_the_command(self) -> None:
        # The trigger is the result the host built, so a command with no
        # remote work in it still reports the gate.
        self.assertIsNotNone(self.fire("rm -rf build", result=APPROVAL_RESULT))

    def test_an_ordinary_result_reports_no_gate(self) -> None:
        self.assertIsNone(self.fire("uv run python -m unittest"))

    def test_output_that_talks_about_approval_is_not_a_gate(self) -> None:
        # The wording-cannot-satisfy-it proof for this cause. A command that
        # ran fine and printed every word the gate uses is not a gate; only
        # the host's own status field is.
        chatter = json.dumps(
            {
                "status": "ok",
                "exit_code": 0,
                "output": (
                    "approval pending_approval approval_pending=True waiting for "
                    "a person to approve this command"
                ),
            }
        )
        self.assertIsNone(self.fire("uv run python -m unittest", result=chatter))

    def test_either_host_field_alone_reports_the_gate(self) -> None:
        for payload in ({"status": "pending_approval"}, {"approval_pending": True}):
            with self.subTest(payload=payload):
                # The per-turn latch is this pass's own state, so this is the
                # reset that clears it; both fire in the same nominal turn.
                reset_remote_wait_state()
                self.assertIsNotNone(self.fire("ls", result=json.dumps(payload)))

    def test_a_push_held_at_the_gate_is_only_the_gate(self) -> None:
        # It did not run, so it started no remote work and there is nothing to
        # wait on. Saying otherwise would be the directive asserting something
        # the host's own result contradicts.
        text = self.directive("git push", result=APPROVAL_RESULT)
        self.assertIn("[OMH approval gate]", text)
        self.assertNotIn("[OMH unarmed wait]", text)

    def test_one_turn_can_pay_both_causes_on_different_calls(self) -> None:
        gated = self.directive("uv run python -m unittest", result=APPROVAL_RESULT)
        self.assertIn("[OMH approval gate]", gated)
        pushed = self.directive("git push")
        self.assertIn("[OMH unarmed wait]", pushed)


class BudgetTests(RemoteWaitTestCase):
    """At most one directive per turn per cause."""

    def test_the_second_directive_in_one_turn_is_suppressed(self) -> None:
        self.assertIsNotNone(self.fire("git push"))
        self.assertIsNone(self.fire("gh pr create --fill"))
        self.assertEqual(remote_wait_declines().get(f"latched:{UNARMED_WAIT_CAUSE}"), 1)

    def test_a_new_turn_gets_its_own_directive(self) -> None:
        self.assertIsNotNone(self.fire("git push", turn="t1"))
        self.assertIsNotNone(self.fire("git push", turn="t2"))

    def test_each_cause_holds_its_own_latch(self) -> None:
        self.assertIsNotNone(self.fire("git push"))
        # The wait cause is spent; the approval cause has not fired yet.
        text = self.directive("uv run python -m unittest", result=APPROVAL_RESULT)
        self.assertIn("[OMH approval gate]", text)
        self.assertNotIn("[OMH unarmed wait]", text)
        self.assertIsNone(self.fire("ls", result=APPROVAL_RESULT))
        self.assertEqual(remote_wait_declines().get(f"latched:{APPROVAL_GATE_CAUSE}"), 1)

    def test_a_turn_without_an_id_spends_nothing(self) -> None:
        self.assertIsNone(self.fire("git push", turn=""))
        self.assertEqual(remote_wait_declines().get("no_turn_id"), 1)

    def test_a_session_without_an_id_spends_nothing(self) -> None:
        self.assertIsNone(self.fire("git push", session=""))
        self.assertEqual(remote_wait_declines().get("no_session_id"), 1)

    def test_a_result_the_directive_cannot_ride_does_not_spend_the_latch(self) -> None:
        # A result already carrying the key is declined by `_carry`. The turn
        # must keep its one chance to say this on the next call.
        taken = json.dumps({"status": "ok", "exit_code": 0, REMOTE_WAIT_NUDGE_KEY: "already here"})
        self.assertIsNone(self.fire("git push", result=taken))
        self.assertEqual(remote_wait_declines().get("result_not_carryable"), 1)
        self.assertIsNotNone(self.fire("gh pr create --fill"))


class SeamCompositionTests(RemoteWaitTestCase):
    """The pass reaches the registered `transform_tool_result` entry."""

    def test_the_composed_seam_delivers_the_directive(self) -> None:
        carried = transform_tool_result(
            tool_name="terminal",
            args={"command": "git push"},
            result=OK_RESULT,
            session_id="s1",
            turn_id="t1",
            hermes_home=str(self.home),
            duration_ms=12,
            status="ok",
        )
        self.assertIsInstance(carried, str)
        self.assertIn("[OMH unarmed wait]", json.loads(str(carried))[REMOTE_WAIT_NUDGE_KEY])

    def test_the_composed_seam_leaves_an_ordinary_result_alone(self) -> None:
        self.assertIsNone(
            transform_tool_result(
                tool_name="terminal",
                args={"command": "git status"},
                result=OK_RESULT,
                session_id="s1",
                turn_id="t1",
                hermes_home=str(self.home),
                duration_ms=12,
                status="ok",
            )
        )


class InstalledPluginTests(unittest.TestCase):
    """The pass survives installation and `register(ctx)`, not just import.

    Everything above calls the function or the composed entry directly, which
    cannot tell a working pass from one nothing wires up. This installs the
    plugin the way `setup --with-plugin` does, loads it from the installed
    directory, registers it against the host's context shape, and drives the
    registered `transform_tool_result` callback.
    """

    def setUp(self) -> None:
        super().setUp()
        reset_nudge_budget()
        reset_remote_wait_state()
        self.addCleanup(reset_nudge_budget)
        self.addCleanup(reset_remote_wait_state)

    def test_the_registered_hook_delivers_and_suppresses_the_directive(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home, hermes_home = root / ".omh", root / ".hermes"
            status, _stdout, stderr = run_cli(
                [
                    "--omh-home", str(omh_home), "--hermes-home", str(hermes_home),
                    "setup", "--with-plugin", "--no-interactive",
                ]
            )
            self.assertEqual(status, 0, stderr)

            module = load_installed_plugin(hermes_home / "plugins" / "omh")
            ctx = FakeHermesContext()
            module.register(ctx)
            self.assertIn("transform_tool_result", ctx.hooks)
            hook = ctx.hooks["transform_tool_result"]

            multi_line = "git add -A\ngit commit -s -m 'x'\ngit push"
            carried = hook(
                tool_name="terminal", args={"command": multi_line}, result=OK_RESULT,
                session_id="sess-1", turn_id="turn-1", hermes_home=str(hermes_home),
                task_id="", tool_call_id="c1", api_request_id="", duration_ms=9, status="ok",
            )
            self.assertIsInstance(carried, str)
            self.assertIn(
                "[OMH unarmed wait]", json.loads(str(carried))[REMOTE_WAIT_NUDGE_KEY]
            )

            # The end-of-turn half is wired too, and reads the latch the
            # tool-result half just recorded for this turn.
            self.assertIn("transform_llm_output", ctx.hooks)
            ended = ctx.hooks["transform_llm_output"](
                response_text="Pushed.", session_id="sess-1", model="m", platform="cli",
                turn_id="turn-1", hermes_home=str(hermes_home),
            )
            self.assertIsInstance(ended, str)
            self.assertEqual(str(ended), f"Pushed.\n\n{HONEST_STOP_TEXT}")

            (hermes_home / PROCESS_RECORD_FILENAME).write_text(
                json.dumps(
                    [
                        {
                            "session_id": "proc_1", "pid": 1, "parent_session_id": "sess-1",
                            "notify_on_complete": True, "watch_patterns": [],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            self.assertIsNone(
                hook(
                    tool_name="terminal", args={"command": "git push"}, result=OK_RESULT,
                    session_id="sess-1", turn_id="turn-2", hermes_home=str(hermes_home),
                    task_id="", tool_call_id="c2", api_request_id="", duration_ms=9, status="ok",
                )
            )


class PassDisjointnessTests(unittest.TestCase):
    """`terminal` reaches this pass and no other annotating pass.

    `hooks/result_transforms.py` states which tool sets overlap now that
    there are five annotating passes, and the answer is that `read_file` is
    the only shared one, between engagement nudges and truncated-read
    recovery. That sentence is only worth writing if something checks it, so
    the sets are derived from the modules here rather than restated. A pass
    that later widens into `terminal` fails this instead of quietly sharing a
    result with a directive that assumes it saw the host's own object.
    """

    def setUp(self) -> None:
        super().setUp()
        reset_nudge_budget()
        reset_remote_wait_state()
        self.addCleanup(reset_nudge_budget)
        self.addCleanup(reset_remote_wait_state)
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def other_watched_tools(self) -> frozenset[str]:
        return frozenset(
            {CODE_MODE_GUIDANCE_TOOL, TRUNCATED_READ_TOOL, SEARCH_HIT_CONTEXT_TOOL}
            | set(KANBAN_READBACK_TOOLS)
            | set(FILE_MUTATING_TOOLS)
            | set(DIRECT_READ_TOOLS)
            | set(DELEGATION_TOOLS)
        )

    def test_no_other_annotating_pass_watches_terminal(self) -> None:
        self.assertNotIn(TERMINAL_TOOL, self.other_watched_tools())

    def test_read_file_is_the_only_tool_two_passes_share(self) -> None:
        # Pins the claim the docstring makes about the OTHER overlap, so the
        # paragraph stays true rather than merely plausible.
        self.assertEqual(TRUNCATED_READ_TOOL, "read_file")
        self.assertIn(TRUNCATED_READ_TOOL, DIRECT_READ_TOOLS)
        self.assertEqual(
            KANBAN_READBACK_TOOLS
            & (FILE_MUTATING_TOOLS | DIRECT_READ_TOOLS | DELEGATION_TOOLS),
            frozenset(),
        )

    def test_the_diff_pass_cannot_also_fire_on_a_terminal_result(self) -> None:
        # The diff pass needs a `diff` key on a JSON object, or a result that
        # is itself a bare diff. A terminal result is JSON with neither, so
        # the two never compose and there is no composed case to pin.
        carried = transform_tool_result(
            tool_name="terminal",
            args={"command": "git push"},
            result=json.dumps(
                {
                    "status": "ok",
                    "exit_code": 0,
                    "output": "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b",
                }
            ),
            session_id="s1",
            turn_id="t1",
            hermes_home=str(Path(self._tmp.name)),
            duration_ms=3,
            status="ok",
        )
        payload = json.loads(str(carried))
        self.assertIn(REMOTE_WAIT_NUDGE_KEY, payload)
        self.assertNotIn("diff", payload)


class CannotExecuteAnythingTests(unittest.TestCase):
    """This module recognises commands; it must never be able to run one.

    `tests/test_handoff_safety_contract_enforcement.py` proves INVARIANT 3 by
    visiting every list or tuple literal in `src/` whose first element is a
    constant program name, because that is how this repository spells an
    argv. `REMOTE_WORK_COMMANDS` used to be written that way and the gate
    reported it, correctly: an anchor table shaped like an argv is
    indistinguishable from one. It is now keyed by executable, so the
    executable is not in argv position and the gate no longer reads it as an
    invocation.

    That change alone would only move the data out of a scanner's way. This
    is the test that keeps the property true rather than merely unchecked:
    the module cannot spawn anything, because it imports nothing that could.
    It is derived from the source, so a later import of `subprocess` fails
    here even if the anchors never change.
    """

    SPAWNING_MODULES = frozenset(
        {"subprocess", "os", "multiprocessing", "asyncio", "shutil", "pty", "popen2", "commands"}
    )
    SPAWNING_CALLS = frozenset(
        {"system", "popen", "spawn", "spawnl", "spawnv", "execv", "execvp", "fork", "run", "call"}
    )

    def module_tree(self) -> ast.Module:
        source = Path(remote_wait_nudge.__file__).read_text(encoding="utf-8")
        return ast.parse(source)

    def test_this_module_cannot_execute_anything(self) -> None:
        imported: set[str] = set()
        for node in ast.walk(self.module_tree()):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])
        offending = sorted(imported & self.SPAWNING_MODULES)
        self.assertEqual(
            offending,
            [],
            f"remote_wait_nudge imports {offending}, which can start a process. This module "
            f"matches command text the model already ran; it must never be able to run one. "
            f"See INVARIANT 3 in tests/test_handoff_safety_contract_enforcement.py.",
        )

    def test_this_module_calls_no_spawn_helper(self) -> None:
        # The import check is the strong one; this catches a spawn reached
        # through a name the import check would not see.
        called: set[str] = set()
        for node in ast.walk(self.module_tree()):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                called.add(func.attr)
            elif isinstance(func, ast.Name):
                called.add(func.id)
        self.assertEqual(sorted(called & self.SPAWNING_CALLS), [])

    def test_the_anchor_table_is_not_argv_shaped(self) -> None:
        # The positive form of the gate's complaint: no tuple in the table
        # begins with an executable name, because the executable is the key.
        for executable, subcommands in REMOTE_WORK_COMMANDS.items():
            for subcommand in subcommands:
                self.assertNotIn(executable, subcommand)
        self.assertEqual(
            set(REMOTE_WORK_COMMANDS), {"git", "gh"}
        )

    def test_every_anchor_is_still_reachable_through_the_matcher(self) -> None:
        # The reshaping must not quietly drop one.
        for anchor in remote_work_anchors():
            with self.subTest(anchor=anchor):
                self.assertEqual(remote_work_command(anchor), anchor)


class MutationProofTests(RemoteWaitTestCase):
    """What the two load-bearing checks would let through if they were weaker."""

    def test_wording_alone_cannot_satisfy_the_armed_check(self) -> None:
        # Every true sentence a session could write about watching CI, in the
        # only two places this pass reads: the command it ran and the tool
        # result it got back. The record stays empty, so the directive fires.
        claim = (
            "Watching CI run 35188790301 in the background; a notice will arrive "
            "when it completes. notify_on_complete=true background=true "
            "gh pr checks --watch armed watcher proc_abc123"
        )
        carried = self.fire(
            "git push origin HEAD",
            result=json.dumps(
                {"status": "ok", "exit_code": 0, "output": claim, "final_response": claim}
            ),
        )
        self.assertIsNotNone(carried, "prose claiming a watcher must not suppress the directive")
        self.assertIn("[OMH unarmed wait]", json.loads(str(carried))[REMOTE_WAIT_NUDGE_KEY])

    def test_the_armed_check_answers_from_the_record_alone(self) -> None:
        # Drop the record's tie to this session and the same file stops
        # arming it. Nothing else in the call changes.
        self.arm(self.watcher("s1"))
        self.assertTrue(armed_waiter_present(session_id="s1", hermes_home=str(self.home)))
        self.arm(self.watcher("s1", parent_session_id="other"))
        self.assertFalse(armed_waiter_present(session_id="s1", hermes_home=str(self.home)))
        self.arm(self.watcher("s1", notify_on_complete=False))
        self.assertFalse(armed_waiter_present(session_id="s1", hermes_home=str(self.home)))

    def test_an_unparseable_record_is_not_reported_as_unarmed(self) -> None:
        (self.home / PROCESS_RECORD_FILENAME).write_text("{", encoding="utf-8")
        self.assertIsNone(armed_waiter_present(session_id="s1", hermes_home=str(self.home)))

    def test_a_record_that_cannot_be_OPENED_is_not_reported_as_unarmed(self) -> None:
        # The other half of "unreadable", and a separate handler in the
        # source: the read itself failing, not the parse. A directory where
        # the file belongs raises `IsADirectoryError`, an `OSError`. Without
        # this case that handler could return an empty list and every test
        # above would still pass.
        (self.home / PROCESS_RECORD_FILENAME).mkdir()
        self.assertIsNone(armed_waiter_present(session_id="s1", hermes_home=str(self.home)))
        self.assertIsNone(self.fire("git push"))
        self.assertEqual(remote_wait_declines().get("process_record_unreadable"), 1)

    def test_a_record_that_is_not_a_list_is_not_reported_as_unarmed(self) -> None:
        (self.home / PROCESS_RECORD_FILENAME).write_text('{"proc_a": {}}', encoding="utf-8")
        self.assertIsNone(armed_waiter_present(session_id="s1", hermes_home=str(self.home)))

    def test_the_anchor_is_tokens_and_not_a_substring(self) -> None:
        # Each line CONTAINS a shipped anchor as a substring, so the naive
        # check this deliberately is not would match every one of them. Each
        # one starts no remote work.
        anchors = remote_work_anchors()
        for command in (
            "echo git push",
            "git push --help",
            "cat <<EOF\ngit push\nEOF",
            "grep 'gh pr create' notes.md",
        ):
            with self.subTest(command=command):
                self.assertTrue(
                    any(anchor in command for anchor in anchors),
                    "the negative case must be one a substring check would match",
                )
                self.assertEqual(remote_work_command(command), "")


class TextBudgetTests(unittest.TestCase):
    """The directive rides a tool result, so its size is a cost per turn.

    Review round 1 on #1738 asked for roughly half the first draft's length,
    on the grounds that this fires on very nearly every push and that an
    audit had measured OMH text at 36% of all `api_content` in the owner's
    primary home. These are the numbers that answers it.
    """

    # The first draft, kept so the reduction is a checked fact rather than a
    # sentence in a pull request nobody can re-derive.
    FIRST_DRAFT_UNARMED_CHARS = 885
    FIRST_DRAFT_APPROVAL_CHARS = 321

    def test_each_directive_stays_within_its_stated_size(self) -> None:
        # Pinned so a later edit has to move the number deliberately, the way
        # the skill-body budgets are. The unarmed-wait text carries a format
        # field and is measured with the shortest anchor in it.
        self.assertEqual(len(UNARMED_WAIT_TEXT.format(command="git push")), 462)
        self.assertEqual(len(APPROVAL_GATE_TEXT), 233)

    # Review round 1 asked for "roughly half". The floor is stated as a
    # threshold the shipped text clears comfortably rather than one tuned to
    # the current value, so a later edit has room to say something useful
    # without the gate becoming a rubber stamp.
    MIN_REDUCTION_FRACTION = 0.40

    def test_the_directive_is_far_shorter_than_its_first_draft(self) -> None:
        shipped = len(UNARMED_WAIT_TEXT.format(command="git push"))
        reduction = 1 - shipped / self.FIRST_DRAFT_UNARMED_CHARS
        self.assertGreaterEqual(
            reduction,
            self.MIN_REDUCTION_FRACTION,
            f"unarmed-wait directive is {shipped} characters against "
            f"{self.FIRST_DRAFT_UNARMED_CHARS} in the first draft",
        )
        self.assertLess(len(APPROVAL_GATE_TEXT), self.FIRST_DRAFT_APPROVAL_CHARS)

    def test_a_turn_can_add_at_most_both_directives_once(self) -> None:
        # The worst case a single turn can pay: both causes, one time each.
        worst_case = len(UNARMED_WAIT_TEXT.format(command="git push")) + 2 + len(APPROVAL_GATE_TEXT)
        self.assertEqual(worst_case, 697)


if __name__ == "__main__":
    unittest.main()
