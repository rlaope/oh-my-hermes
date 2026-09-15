"""Contracts for how much of the host's turn-end budget an open plan may spend.

The turn-end directive lands on `pre_verify`, which a Hermes host calls up to
`agent.max_verify_nudges` times per turn (3 by default). Its first form spent
exactly one of them -- `attempt > 0` returned `None`, per the host docs'
idempotency guidance -- so a five-item plan got one extra pass per turn and then
waited for the person again.

The guidance protects against a real failure: a hook that always continues
argues to the bound whether or not anything is happening. These tests pin the
narrower condition that keeps the budget safe to spend without reinstating that
failure -- a later attempt nudges only while the PLAN KEPT MOVING since the
previous nudge in the same turn -- and, at least as importantly, every state
that still stops the line at every attempt: a next item recorded blocked, a plan
that finished or vanished mid-turn, a stamp that did not move or went
backwards, a session with no identity, and another session's movement.

The stamp is the plan record's own `updated_at`. `todo_store` restamps it on
every write, so re-scoping the list or marking the next item active counts as
movement while `done/total` does not change -- which is the point: a
continuation that starts the next item has advanced the run, and a completed
item is not the only evidence of that.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh import todo_reconciliation
from omh.plugin_bundle.omh.hooks import nudge_budget, verify_hooks
from omh.plugin_bundle.omh.todo_reconciliation import TODO_CONTINUATION_RULE
from omh.plugin_bundle.omh.todo_store import build_todo_record, todo_path, write_todo

# `agent.max_verify_nudges` default. The host owns this bound and enforces it at
# its own gate (`attempt < max_verify_nudges()`), so the plugin does not carry a
# second copy of the number -- these tests model the host loop instead, and one
# of them proves the plugin really is leaving the ceiling to the host.
MAX_VERIFY_NUDGES = 3

OPEN_PLAN = (("land the fix", "done"), ("open the PR", "active"), ("report", "pending"))

SESSION = "budget-session"

_UNSET = object()


class _PlanHome(unittest.TestCase):
    """A temp OMH/Hermes home pair, a session id, and a cleared budget.

    The budget's memory is process-global, so a test that fires the hook leaves
    a baseline behind for whichever test runs next -- and the CI shard planner
    reorders tests run to run, which is how `fanout_dispatch._INTERRUPT_FLAG`
    became a CI-only failure in this repository. Cleared through the module's
    named seam on the way in and again on the way out, so neither direction
    depends on execution order.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "omh"
        self.hermes = Path(self._tmp.name) / "hermes"
        self.hermes.mkdir(parents=True, exist_ok=True)
        nudge_budget.reset_nudge_budget()
        self.addCleanup(nudge_budget.reset_nudge_budget)
        self.session = SESSION
        # Well inside `TODO_STALE_SECONDS`, so every stamp below is a live plan
        # and the only thing that varies between attempts is its order.
        self._base = datetime.now(timezone.utc) - timedelta(seconds=600)

    def _stamp(self, step):
        return (self._base + timedelta(seconds=60 * step)).isoformat().replace("+00:00", "Z")

    def _write_plan(self, items=OPEN_PLAN, *, step=0, session_ref=None, updated_at=None):
        record = build_todo_record(
            "plan",
            [
                {"text": item[0], "state": item[1], "blocked_reason": item[2] if len(item) > 2 else ""}
                for item in items
            ],
            source="test",
            session_ref=self.session if session_ref is None else session_ref,
        )
        # The record's own stamp, set explicitly rather than taken from the
        # clock: movement is the thing under test, so the test has to own which
        # write is newer instead of relying on two writes landing in different
        # microseconds.
        record["updated_at"] = self._stamp(step) if updated_at is None else updated_at
        _ = write_todo(self.home, record)
        return record["updated_at"]

    def _fire(self, **overrides):
        payload = {
            "session_id": self.session,
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


class AdvancingPlanKeepsItsBudgetTest(_PlanHome):
    def test_a_plan_that_keeps_moving_nudges_on_every_attempt_the_host_offers(self):
        # The capability this replaces one-nudge-per-turn with: a run that is
        # advancing keeps being told to advance, inside a single turn.
        self._write_plan(step=0)
        messages = [self._fire(attempt=0)["message"]]

        for attempt in (1, 2):
            self._write_plan(step=attempt)
            result = self._fire(attempt=attempt)

            self.assertIsNotNone(result, f"attempt {attempt} stopped an advancing plan")
            messages.append(result["message"])

        self.assertEqual(len(messages), MAX_VERIFY_NUDGES)
        for message in messages:
            self.assertIn("[OMH plan todo] 1/3 done", message)
            self.assertIn("next: open the PR", message)
            self.assertIn(TODO_CONTINUATION_RULE, message)

    def test_the_host_bound_is_what_stops_an_advancing_plan_and_the_plugin_does_not_copy_it(self):
        # The loop runs the host's own gate. It spends all three nudges because
        # the plan moves each time, and the fourth call never happens -- the
        # host stops it, which is why the plugin carries no second copy of the
        # number. Asserted rather than described: the handler still answers at
        # attempt 3, so the ceiling observed above is the host's.
        nudges = 0
        attempt = 0
        while attempt < MAX_VERIFY_NUDGES:
            self._write_plan(step=attempt)
            result = self._fire(attempt=attempt)
            if result is None:
                break
            nudges += 1
            attempt += 1

        self.assertEqual(nudges, MAX_VERIFY_NUDGES)
        self._write_plan(step=MAX_VERIFY_NUDGES)
        self.assertIsNotNone(
            self._fire(attempt=MAX_VERIFY_NUDGES),
            "the plugin reimplemented the host's bound instead of leaving it to the host",
        )

    def test_a_rewrite_that_changes_nothing_observable_still_counts_as_movement(self):
        # The deliberate reading of `updated_at`, pinned so it stays a decision.
        # `todo_store` restamps on every write, so an identical list written
        # again is movement here. The alternative -- counting only `done/total`
        # -- would refuse to continue the turn where the model marked the next
        # item active or re-scoped the plan, which is exactly what a
        # continuation is supposed to do.
        self._write_plan(step=0)
        _ = self._fire(attempt=0)
        self._write_plan(step=1)

        self.assertIsNotNone(self._fire(attempt=1))

    def test_a_new_turn_restores_the_whole_budget(self):
        # `attempt` returning to 0 is the only turn boundary a hook can see, so
        # it has to be the one that resets the baseline.
        self._write_plan(step=0)
        _ = self._fire(attempt=0)
        self.assertIsNone(self._fire(attempt=1), "an unmoved plan spent a second nudge")

        self.assertIsNotNone(self._fire(attempt=0), "a new turn did not get its first nudge back")


class AStalledPlanSpendsOneNudgeTest(_PlanHome):
    def test_a_plan_that_did_not_move_stops_after_one_nudge(self):
        # The failure the host's idempotency guidance names, still closed: a
        # nudge that produced nothing does not repeat.
        self._write_plan(step=0)
        self.assertIsNotNone(self._fire(attempt=0))

        self.assertIsNone(self._fire(attempt=1))

    def test_a_plan_that_moves_once_then_stops_stops_there(self):
        self._write_plan(step=0)
        self.assertIsNotNone(self._fire(attempt=0))
        self._write_plan(step=1)
        self.assertIsNotNone(self._fire(attempt=1))

        self.assertIsNone(self._fire(attempt=2), "a stalled second attempt kept nudging")

    def test_the_host_loop_ends_on_the_first_attempt_that_did_not_move_the_plan(self):
        # The same three-attempt loop as the advancing case, with the plan
        # written once: one nudge of the three, then the turn finishes.
        self._write_plan(step=0)
        nudges = 0
        attempt = 0
        while attempt < MAX_VERIFY_NUDGES:
            if self._fire(attempt=attempt) is None:
                break
            nudges += 1
            attempt += 1

        self.assertEqual(nudges, 1)

    def test_a_stamp_that_went_backwards_is_not_movement(self):
        # A clock that stepped back, or a record restored from an older copy.
        # Different from an unchanged plan and treated the same way, because
        # neither is a run that advanced.
        self._write_plan(step=2)
        self.assertIsNotNone(self._fire(attempt=0))
        self._write_plan(step=1)

        self.assertIsNone(self._fire(attempt=1))


class ThePlansOwnStopCriterionHoldsAtEveryAttemptTest(_PlanHome):
    def test_a_next_item_recorded_blocked_stops_the_line_at_every_attempt(self):
        # #1549's stop criterion, and the one thing progress gating must not
        # weaken: a plan that keeps being written while its next item carries a
        # reason is still a plan that says stop. Movement buys budget; it does
        # not buy the right to argue with a blocked item.
        blocked = (
            ("land the fix", "done"),
            ("open the PR", "active", "waiting on the owner's review"),
            ("report", "pending"),
        )
        for attempt in (0, 1, 2):
            with self.subTest(attempt=attempt):
                self._write_plan(blocked, step=attempt)

                self.assertIsNone(self._fire(attempt=attempt))

    def test_a_plan_that_finishes_during_the_turn_stops_the_line(self):
        self._write_plan(step=0)
        self.assertIsNotNone(self._fire(attempt=0))
        self._write_plan((("land the fix", "done"), ("open the PR", "done")), step=1)

        self.assertIsNone(self._fire(attempt=1))

    def test_a_plan_that_vanishes_during_the_turn_stops_the_line(self):
        self._write_plan(step=0)
        self.assertIsNotNone(self._fire(attempt=0))
        todo_path(self.home, self.session).unlink()

        self.assertIsNone(self._fire(attempt=1))

    def test_no_plan_never_nudges_at_any_attempt(self):
        for attempt in (0, 1, 2):
            with self.subTest(attempt=attempt):
                self.assertIsNone(self._fire(attempt=attempt))

    def test_a_reader_failure_on_a_later_attempt_is_silence_and_never_an_exception(self):
        # Hermes wraps the whole `pre_verify` call in `except Exception` and
        # logs at debug, so a raise ends the turn with no trace -- the symptom
        # the directive exists to fix. The later attempts added here read the
        # plan too, so they inherit that obligation.
        self._write_plan(step=0)
        self.assertIsNotNone(self._fire(attempt=0))

        for failure in (OSError("denied"), RuntimeError("symlinked root"), ValueError("bad")):
            with self.subTest(failure=type(failure).__name__):
                with patch.object(todo_reconciliation, "read_omh_todo", side_effect=failure):
                    self.assertIsNone(self._fire(attempt=1))


class TheBudgetIsPerSessionTest(_PlanHome):
    def test_a_session_with_no_id_keeps_the_one_nudge_budget(self):
        # With no session id there is nothing to key the memory by, and a
        # shared untracked row would measure one session's turn against
        # another's plan. Losing two nudges is the cheaper failure, so an
        # anonymous caller degrades to the one-nudge behaviour.
        self._write_plan(step=0, session_ref="")
        self.assertIsNotNone(self._fire(attempt=0, session_id=""))
        self._write_plan(step=1, session_ref="")

        self.assertIsNone(self._fire(attempt=1, session_id=""))

    def test_a_populated_budget_cannot_reach_a_session_that_never_nudged(self):
        # Cross-contamination made impossible rather than merely absent in this
        # ordering. Session A records a baseline and its plan moves; session B
        # has never called the hook. B's first attempt must behave as a first
        # attempt -- nudge, and rebaseline on B's OWN plan -- and B's second
        # attempt must then answer to B's plan alone. Session ids are what make
        # that true, so this is the case that pins them.
        other = f"{self.session}-never-nudged"
        self._write_plan(step=0)
        self._write_plan(step=0, session_ref=other)
        self.assertIsNotNone(self._fire(attempt=0))
        self._write_plan(step=2)

        # B has no baseline, so a later attempt cannot borrow A's movement.
        self.assertIsNone(
            self._fire(attempt=1, session_id=other),
            "a session that never nudged inherited another session's baseline",
        )
        # And B's own first attempt is still a first attempt.
        self.assertIsNotNone(self._fire(attempt=0, session_id=other))
        self.assertIsNone(
            self._fire(attempt=1, session_id=other),
            "B's second attempt answered to a plan that is not B's",
        )

    def test_one_sessions_movement_does_not_spend_another_sessions_budget(self):
        # Two sessions served by one process. The first is advancing, the
        # second is not; the second must not inherit the first's movement.
        other = f"{self.session}-other"
        self._write_plan(step=0)
        self._write_plan(step=0, session_ref=other)
        self.assertIsNotNone(self._fire(attempt=0))
        self.assertIsNotNone(self._fire(attempt=0, session_id=other))
        self._write_plan(step=1)

        self.assertIsNotNone(self._fire(attempt=1), "the advancing session lost its budget")
        self.assertIsNone(
            self._fire(attempt=1, session_id=other),
            "a stalled session nudged on another session's movement",
        )


class TheServedSurfaceGateStaysOneShotTest(_PlanHome):
    def test_the_served_surface_check_does_not_repeat_on_a_later_attempt(self):
        # The surface gate asks for the check this turn's edit earned, and the
        # edits are the same on every attempt of that turn. Only the plan line
        # spends more of the budget.
        self._write_plan(step=0)
        first = self._fire(attempt=0, changed_paths=["src/app.tsx"])["message"]
        self._write_plan(step=1)
        second = self._fire(attempt=1, changed_paths=["src/app.tsx"])["message"]

        self.assertIn("rendered surface", first)
        self.assertIn("[OMH plan todo] 1/3 done", first)
        self.assertNotIn("rendered surface", second)
        self.assertIn("[OMH plan todo] 1/3 done", second)

    def test_a_served_surface_edit_alone_does_not_extend_the_turn(self):
        # No plan at all: the surface gate fires once and the later attempts
        # have nothing to spend budget on, so the turn ends as it does today.
        self.assertIsNotNone(self._fire(attempt=0, changed_paths=["src/app.tsx"]))

        self.assertIsNone(self._fire(attempt=1, changed_paths=["src/app.tsx"]))


class PlanNudgeBudgetUnitTest(unittest.TestCase):
    """The gate itself, on inputs the plan reader cannot produce on demand."""

    def setUp(self):
        nudge_budget.reset_nudge_budget()
        self.addCleanup(nudge_budget.reset_nudge_budget)
        self.key = "unit-session"
        self.earlier = "2026-09-15T10:00:00Z"
        self.later = "2026-09-15T10:01:00Z"

    def _allow(self, attempt, stamp, session_id=_UNSET):
        # `None` is one of the session ids under test, so the "use this test's
        # own key" default cannot be spelled `None`.
        return nudge_budget.plan_nudge_allowed(
            session_id=self.key if session_id is _UNSET else session_id,
            attempt=attempt,
            stamp=stamp,
        )

    def test_a_stamp_that_does_not_parse_is_not_movement(self):
        # Corruption must not buy a nudge.
        self.assertTrue(self._allow(0, self.earlier))

        for stamp in ("soon", "", "2026-13-45T99:99:99Z", None, 7, {"at": "now"}):
            with self.subTest(stamp=stamp):
                self.assertFalse(self._allow(1, stamp))

    def test_a_baseline_that_does_not_parse_is_movement_once_a_real_stamp_appears(self):
        # The other direction, and the opposite answer: the first attempt saw
        # no readable plan and the second does. A plan written during the turn
        # is the run advancing.
        self.assertTrue(self._allow(0, ""))

        self.assertTrue(self._allow(1, self.later))

    def test_an_identical_stamp_is_not_movement(self):
        self.assertTrue(self._allow(0, self.later))

        self.assertFalse(self._allow(1, self.later))

    def test_each_nudge_rebaselines_on_the_plan_it_was_issued_on(self):
        # Not on the start of the turn: a second attempt that moved the plan
        # and a third that did not must give different answers.
        self.assertTrue(self._allow(0, "2026-09-15T10:00:00Z"))
        self.assertTrue(self._allow(1, "2026-09-15T10:01:00Z"))

        self.assertFalse(self._allow(2, "2026-09-15T10:01:00Z"))

    def test_a_session_id_that_is_not_a_string_is_not_tracked(self):
        for session_id in (None, 7, ["s"], "", "   "):
            with self.subTest(session_id=session_id):
                self.assertTrue(self._allow(0, self.earlier, session_id=session_id))

                self.assertFalse(self._allow(1, self.later, session_id=session_id))

    def test_the_memory_is_bounded_and_an_evicted_baseline_refuses_rather_than_nudges(self):
        # A host outlives every session it runs, so the map may not grow with
        # one row per session ever seen. Eviction has to fail toward silence:
        # the evicted session is refused, never nudged on a baseline that is
        # gone.
        self.assertTrue(self._allow(0, self.earlier))
        fillers = [f"{self.key}-filler-{index}" for index in range(nudge_budget.MAX_TRACKED_SESSIONS)]
        for filler in fillers:
            _ = self._allow(0, self.earlier, session_id=filler)

        self.assertFalse(self._allow(1, self.later), "the oldest baseline was not evicted")
        # Eviction, not a wipe: the row recorded most recently is still there,
        # which is what makes the assertion above a bound rather than a bug.
        self.assertTrue(self._allow(1, self.later, session_id=fillers[-1]))


if __name__ == "__main__":
    unittest.main()
