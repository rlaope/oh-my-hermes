"""Contracts for the turn-end open-plan continuation directive.

An ULW run advances one item and stops: the plan still shows open items,
nothing is blocked, and the turn ends on a status report. `TODO_CONTINUATION_RULE`
already says the right thing, but `_open_plan_line` renders it into the context
of a turn that is ALREADY happening -- nothing observes a turn that ends with
open items, so continuation waits for the person.

`pre_verify` is the one moment a Hermes host lets a plugin start the next turn
instead of describing the current one. These tests pin what the directive says
and, at least as importantly, every state in which it must stay silent: no
plan, a finished plan, a next item carrying a `blocked_reason`, a later attempt
with no first nudge behind it, a non-coding turn, and another session's plan.

Which LATER attempts inside one turn may nudge is its own contract, decided on
whether the plan moved since the previous nudge; it lives in
`test_plan_nudge_progress_budget.py`.

The last test is the anti-drift one: the context line and the directive must
decide "does this plan have open work" through the same helper, so a plan that
stops one has to stop the other.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh import runtime_paths, todo_reconciliation
from omh.plugin_bundle.omh.hooks import nudge_budget, verify_hooks
from omh.plugin_bundle.omh.runtime_reader import read_omh_todo
from omh.plugin_bundle.omh.todo_reconciliation import (
    DISPATCH_COMPLETION_RULE,
    PLAN_CONTINUATION_BOUNDARY,
    TODO_CONTINUATION_RULE,
    open_plan_position,
    open_todo_reminder,
    plan_continuation_reading,
)
from omh.plugin_bundle.omh.todo_store import (
    TODO_SCHEMA_VERSION,
    build_todo_record,
    todo_path,
    write_todo,
)

FANOUT_ID = "fanout-0123456789ab"
SESSION = "tui-session"


class PlanContinuationDirectiveTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "omh"
        self.hermes = Path(self._tmp.name) / "hermes"
        self.hermes.mkdir(parents=True, exist_ok=True)
        # The turn-end budget remembers the plan stamp its last nudge was
        # issued on in a process-global map, so a test that fires the hook
        # leaves a baseline behind for whichever test runs next -- and the CI
        # shard planner reorders tests run to run. Cleared here and again on
        # the way out, through the module's named seam.
        nudge_budget.reset_nudge_budget()
        self.addCleanup(nudge_budget.reset_nudge_budget)

    def _write_plan(self, items, session_ref=SESSION):
        """`items` is a list of `(text, state)` pairs, or `(text, state, blocked_reason)`."""
        record = build_todo_record(
            "plan",
            [
                {"text": item[0], "state": item[1], "blocked_reason": item[2] if len(item) > 2 else ""}
                for item in items
            ],
            source="test",
            session_ref=session_ref,
        )
        write_todo(self.home, record)
        return datetime.fromisoformat(record["updated_at"].replace("Z", "+00:00"))

    def _write_finished_unit(self, unit_id, finished_at):
        directory = self.home / "coding" / "fanout" / FANOUT_ID
        directory.mkdir(parents=True, exist_ok=True)
        _ = (directory / "dispatch_summary.json").write_text(
            json.dumps(
                {
                    "schema_version": "fanout_dispatch_summary/v1",
                    "fanout_id": FANOUT_ID,
                    "units": [
                        {
                            "unit_id": unit_id,
                            "run_ref": f"{FANOUT_ID}-{unit_id}",
                            "status": "completed",
                            "process_succeeded": True,
                            "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def _fire(self, **overrides):
        payload = {
            "session_id": SESSION,
            "coding": True,
            "attempt": 0,
            # A plain source file: no served-surface category, so what comes
            # back is the plan directive alone.
            "changed_paths": ["src/example.py"],
            "omh_home": str(self.home),
            "hermes_home": str(self.hermes),
        }
        payload.update(overrides)
        return verify_hooks.pre_verify(**payload)

    def test_a_turn_ending_with_open_items_is_told_to_advance_the_next_one(self):
        self._write_plan([("land the fix", "done"), ("open the PR", "active"), ("report", "pending")])

        result = self._fire()

        self.assertEqual(result["action"], "continue")
        self.assertIn("[OMH plan todo] 1/3 done", result["message"])
        self.assertIn("next: open the PR", result["message"])
        self.assertIn(TODO_CONTINUATION_RULE, result["message"])
        self.assertIn(PLAN_CONTINUATION_BOUNDARY, result["message"])

    def test_the_next_item_is_the_first_pending_one_when_nothing_is_active(self):
        self._write_plan([("land the fix", "done"), ("open the PR", "pending"), ("report", "pending")])

        self.assertIn("next: open the PR", self._fire()["message"])

    def test_no_plan_does_not_nudge(self):
        self.assertIsNone(self._fire())

    def test_a_finished_plan_does_not_nudge(self):
        self._write_plan([("land the fix", "done"), ("open the PR", "done")])

        self.assertIsNone(self._fire())

    def test_a_next_item_recorded_blocked_with_its_reason_stops_the_nudge(self):
        # The plan's own stop criterion. Nudging here would argue with a
        # blocked item once per turn until `max_verify_nudges` ran out.
        # Phrasing is irrelevant: the reason is a field, so a Korean reason and
        # an English one stop the plan identically.
        reasons = (
            "the owner's review",
            "소유자 승인 대기",
            "waiting on the API key",
            "차단됨: 상위 태스크 미완료",
        )

        for reason in reasons:
            with self.subTest(reason=reason):
                self._write_plan(
                    [
                        ("land the fix", "done"),
                        ("open the PR", "active", reason),
                        ("release", "pending"),
                    ]
                )

                self.assertIsNone(self._fire())

    def test_a_reason_that_says_nothing_is_wrong_still_stops_the_plan(self):
        # The deliberate choice, pinned so it stays a decision rather than an
        # accident. With no `blocked` item state the field's PRESENCE is the
        # whole declaration, so a speculative fill does stop the loop. Ranking
        # wordings instead would need a list of reasons that do not count --
        # uncompletable in one language let alone four, which is exactly what
        # sank text inference. The guard lives in the tool description, which
        # says to omit the field unless the item cannot proceed.
        for reason in ("none", "n/a", "not blocked", "없음"):
            with self.subTest(reason=reason):
                self._write_plan([("land the fix", "done"), ("open the PR", "active", reason)])

                self.assertIsNone(self._fire())

    def test_a_reason_that_is_not_a_string_is_read_as_absent(self):
        # A record written by hand, or by a writer that skipped
        # `validate_todo_items`, can carry anything. Each value below
        # stringifies to something truthy, so reading it as a block would be
        # the silent stop this surface exists to end: corruption is not a
        # declaration, and malformed data fails toward continuing. This is the
        # other side of the sentinel rule, not a softening of it -- "none"
        # counts because a string is a declaration; 7 is not one.
        for reason in (7, {"a": 1}, [1], True, None, False, 0, [], "   "):
            with self.subTest(reason=reason):
                item = {"text": "open the PR", "state": "active", "blocked_reason": reason}

                self.assertEqual(todo_reconciliation.recorded_blocked_reason(item), "")

    def test_item_text_about_a_block_is_not_a_block(self):
        # The regression that made the field necessary. Every item below is
        # ordinary descriptive text with no recorded reason, and each one used
        # to stop the run silently -- the exact defect this directive exists to
        # fix, reintroduced by the mechanism meant to bound it. Note the
        # negations: "not blocked" contains "blocked on".
        descriptive_texts = (
            "Verify the retry is not blocked on the session limit",
            "Make sure nothing is blocked by the lock",
            "Test that a task blocked by its parent is skipped",
            "Investigate why the queue is blocked on shard 3",
            "Add a `blocked:` reason field to the todo schema",
            "unblock the release queue",
            "blocked",
        )

        for text in descriptive_texts:
            with self.subTest(text=text):
                self._write_plan([("land the fix", "done"), (text, "active")])

                result = self._fire()

                self.assertIsNotNone(result, "descriptive text must not stop the run")
                self.assertIn(TODO_CONTINUATION_RULE, result["message"])

    def test_a_recorded_reason_is_read_whole_however_long_the_item_is(self):
        # Truncation is a display bound, not a decision bound. The item text is
        # longer than the 80-character display window and the reason is longer
        # than it too; neither may reach the stop criterion.
        long_text = (
            "Verify the retry path end to end across every shard and record what each one observed"
        )
        self._write_plan(
            [
                ("land the fix", "done"),
                (f"{long_text} and then some more", "active", "x" * 150),
            ]
        )

        self.assertIsNone(self._fire())

    def test_a_long_item_still_renders_truncated_when_it_is_not_blocked(self):
        long_text = (
            "Verify the retry path end to end across every shard and record what each one observed"
        )
        self._write_plan([("land the fix", "done"), (long_text, "active")])

        message = self._fire()["message"]

        self.assertIn(f"next: {long_text[:80]}", message)
        self.assertNotIn(long_text, message)

    def test_a_later_attempt_with_no_first_nudge_behind_it_does_not_nudge(self):
        # A later attempt nudges only on movement MEASURED against the previous
        # nudge in the same turn. With no first attempt recorded there is
        # nothing to measure, and an unmeasured attempt must not invent
        # movement -- so this stays silent however open the plan is.
        self._write_plan([("land the fix", "done"), ("open the PR", "active")])

        self.assertIsNone(self._fire(attempt=1))

    def test_a_non_coding_turn_does_not_nudge(self):
        self._write_plan([("land the fix", "done"), ("open the PR", "active")])

        self.assertIsNone(self._fire(coding=False))

    def test_another_session_plan_is_not_this_session_open_work(self):
        self._write_plan(
            [("land the fix", "done"), ("open the PR", "active")], session_ref="slack-session"
        )

        self.assertIsNone(self._fire())

    def test_an_unacknowledged_dispatch_outcome_nudges_on_the_same_path(self):
        plan_updated_at = self._write_plan(
            [("land the fix", "done"), ("open the PR", "done")]
        )
        self._write_finished_unit("unit-a", plan_updated_at + timedelta(seconds=30))

        result = self._fire()

        self.assertEqual(result["action"], "continue")
        self.assertIn(f"dispatch {FANOUT_ID}-unit-a/unit-a ended completed", result["message"])
        self.assertIn(DISPATCH_COMPLETION_RULE, result["message"])
        # A finished plan says nothing about its position; the unacknowledged
        # outcome is the whole reason this turn is being kept open.
        self.assertNotIn("[OMH plan todo]", result["message"])

    def test_a_blocked_item_does_not_suppress_an_unacknowledged_dispatch(self):
        # Two obligations, not one. A finished dispatch nobody wrote down still
        # owes a verify-and-record, and it is frequently the very thing that
        # ends the block -- so gating it on another item's state would bury the
        # event that clears the wait.
        plan_updated_at = self._write_plan(
            [
                ("land the fix", "done"),
                ("release", "active", "the owner's review"),
            ]
        )
        self._write_finished_unit("unit-a", plan_updated_at + timedelta(seconds=30))

        result = self._fire()

        self.assertEqual(result["action"], "continue")
        self.assertIn(f"dispatch {FANOUT_ID}-unit-a/unit-a ended completed", result["message"])
        self.assertIn(DISPATCH_COMPLETION_RULE, result["message"])
        # The blocked item stops the plan line and only the plan line.
        self.assertNotIn("[OMH plan todo]", result["message"])

    def test_the_served_surface_check_and_the_plan_directive_ride_one_turn(self):
        self._write_plan([("land the fix", "done"), ("open the PR", "active")])

        message = self._fire(changed_paths=["src/app.tsx"])["message"]

        self.assertIn("rendered surface", message)
        self.assertIn("[OMH plan todo] 1/2 done", message)

    def test_a_corrupt_plan_record_is_silence_and_never_an_exception(self):
        # Hermes wraps the whole `pre_verify` call in `except Exception` and
        # logs at debug (`agent/turn_stop_gates.py`, `_pre_verify_nudge`), so a
        # handler that raised would end the turn with no trace -- the exact
        # symptom this directive exists to fix. Every malformed record below
        # must therefore come back as silence, not as a raise.
        path = todo_path(self.home, SESSION)
        path.parent.mkdir(parents=True, exist_ok=True)
        corrupt_records = (
            "{not json",
            "[]",
            json.dumps({"schema_version": "omh_todo/v0", "items": [{"text": "x", "state": "active"}]}),
            json.dumps({"schema_version": TODO_SCHEMA_VERSION, "items": "all of them"}),
            json.dumps({"schema_version": TODO_SCHEMA_VERSION, "items": ["not an item"]}),
            json.dumps({"schema_version": TODO_SCHEMA_VERSION, "items": [{"text": "x", "state": 7}]}),
            json.dumps({"schema_version": TODO_SCHEMA_VERSION, "counts": "1/3", "items": []}),
        )

        for record in corrupt_records:
            with self.subTest(record=record[:40]):
                _ = path.write_text(record, encoding="utf-8")

                self.assertIsNone(self._fire())

    def test_a_reader_that_fails_is_silence_and_never_an_exception(self):
        # The read touches the filesystem, so it can fail for reasons that have
        # nothing to do with the plan's shape. `RuntimeBindingError` is in the
        # list because it subclasses `ValueError`: an unbindable home must not
        # reach the host as a raise either.
        failures = (
            OSError("permission denied"),
            ValueError("bad payload"),
            TypeError("bad type"),
            runtime_paths.RuntimeBindingError("no safe store"),
            # Not a `ValueError`: the reader's state-root guard raises a plain
            # `RuntimeError` for a symlinked home or a symlink loop, and so does
            # `TodoStoreError`. It is the one type in this chain the guard used
            # to miss while a comment asserted the list was complete.
            RuntimeError("cannot use a symlink as a state root"),
        )

        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with patch.object(todo_reconciliation, "read_omh_todo", side_effect=failure):
                    self.assertIsNone(self._fire())

    def test_a_symlinked_home_is_silence_and_never_an_exception(self):
        # The same guard through the real code path rather than a patched one:
        # the reader refuses a symlinked state root, and that refusal has to
        # reach the host as silence.
        self._write_plan([("land the fix", "done"), ("open the PR", "active")])
        linked = Path(self._tmp.name) / "linked-omh"
        try:
            linked.symlink_to(self.home, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform dependent
            self.skipTest(f"symlinks unavailable here: {exc}")

        self.assertEqual(
            todo_reconciliation.plan_continuation_reading(
                omh_home=str(linked), hermes_home=str(self.hermes), session_ref=SESSION
            ),
            ("", ""),
        )

    def test_a_failed_outcome_read_does_not_take_the_plan_line_with_it(self):
        # Two independent obligations, two guards. Folding them into one try
        # would let a fanout-side failure silence the plan line -- the same
        # coupling the blocked check had before F3.
        self._write_plan([("land the fix", "done"), ("open the PR", "active")])

        with patch.object(
            todo_reconciliation, "unacknowledged_outcomes", side_effect=RuntimeError("bad root")
        ):
            result = self._fire()

        self.assertIn("[OMH plan todo] 1/2 done", result["message"])
        self.assertNotIn(DISPATCH_COMPLETION_RULE, result["message"])

    def test_a_reader_returning_something_other_than_a_record_is_silence(self):
        for payload in (None, [], "plan"):
            with self.subTest(payload=payload):
                with patch.object(todo_reconciliation, "read_omh_todo", return_value=payload):
                    self.assertIsNone(self._fire())

    def test_the_plan_is_read_from_the_host_home_when_no_path_is_passed(self):
        # Hermes calls `pre_verify` with the documented kwargs and nothing
        # else -- there is no `omh_home` among them -- so the binding that runs
        # in production is the default one every other test here bypasses.
        self._write_plan([("land the fix", "done"), ("open the PR", "active")])

        with patch.dict(
            "os.environ", {"OMH_HOME": str(self.home), "HERMES_HOME": str(self.hermes)}
        ):
            result = verify_hooks.pre_verify(
                session_id=SESSION, coding=True, attempt=0, changed_paths=["src/example.py"]
            )

        self.assertIn("[OMH plan todo] 1/2 done", result["message"])

    def test_both_surfaces_route_their_gate_through_the_one_helper(self):
        # The structural property, tested structurally. An earlier version of
        # this compared the two surfaces' output across four well-formed plans,
        # which proved nothing: an inline copy of the condition that dropped
        # `done >= total`, or dropped `status == "established"`, agreed with the
        # original on every plan in the matrix and the test still passed. A
        # guard that agrees with itself proves nothing -- so patch the helper
        # and require both surfaces to come through it.
        self._write_plan([("land the fix", "done"), ("open the PR", "active")])
        homes = {"omh_home": str(self.home), "hermes_home": str(self.hermes), "session_ref": SESSION}

        surfaces = (
            open_todo_reminder,
            # The directive hands its plan stamp back beside the message, so
            # the rendered half is the one this compares.
            lambda **kwargs: plan_continuation_reading(**kwargs)[0],
        )

        for name, surface in zip(("open_todo_reminder", "plan_continuation_reading"), surfaces):
            with self.subTest(surface=name):
                with patch.object(
                    todo_reconciliation, "open_plan_position", return_value=None
                ) as gate:
                    rendered = surface(**homes)

                self.assertTrue(gate.called, "the surface decided open work without the helper")
                self.assertNotIn("[OMH plan todo]", rendered)

    def test_the_two_surfaces_name_different_items_on_purpose(self):
        # The context line names what is running; the directive names what to
        # start, and a plan between items has no active entry to name. Pinned
        # because the asymmetry is deliberate and would otherwise read as a bug
        # to the next person who compares the two strings.
        self._write_plan([("land the fix", "done"), ("open the PR", "pending")])
        homes = {"omh_home": str(self.home), "hermes_home": str(self.hermes), "session_ref": SESSION}

        reminder = open_todo_reminder(**homes)
        directive, _stamp = plan_continuation_reading(**homes)

        self.assertIn("[OMH plan todo] 1/2 done.", reminder)
        self.assertNotIn("open the PR", reminder)
        self.assertIn("next: open the PR", directive)

    def test_the_gate_itself_still_answers_for_each_plan_state(self):
        matrices = (
            ([("a", "active")], True),
            ([("a", "done"), ("b", "active")], True),
            ([("a", "done"), ("b", "done")], False),
            ([("a", "done"), ("b", "pending")], True),
        )

        for items, open_work in matrices:
            with self.subTest(items=items):
                self._write_plan(items)
                todo = read_omh_todo(str(self.home), str(self.hermes), session_ref=SESSION)

                self.assertEqual(open_plan_position(todo) is not None, open_work)


if __name__ == "__main__":
    unittest.main()
